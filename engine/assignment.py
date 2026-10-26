# -*- coding: utf-8 -*-
"""Static traffic assignment: all-or-nothing, MSA and Frank-Wolfe equilibrium.

Step four of the four-step model. The gravity model writes an origin-
destination matrix; this module loads it onto the street network and lets
congestion push traffic onto alternative routes until no driver can save time
by switching - Wardrop's (1952) first principle, user equilibrium.

The formulation is Beckmann, McGuire & Winsten's (1956) convex program: the
equilibrium link volumes minimise

    Z(v) = sum_a  integral_0^{v_a} t_a(x) dx

over all feasible flows, where ``t_a`` is the link's volume-delay function.
PlanX uses the Bureau of Public Roads (1964) function

    t_a(v) = t0_a * (1 + alpha * (v / c_a) ** beta)

with the classic alpha = 0.15 and beta = 4. Two solution methods are offered:

* **Frank-Wolfe** (Frank & Wolfe 1956; LeBlanc, Morlok & Pierskalla 1975):
  each iteration assigns all demand to the current shortest paths (the
  auxiliary flow ``y``) and moves along ``y - v`` by the step that minimises
  ``Z`` exactly - found here by bisection on the directional derivative,
  which is monotone because ``Z`` is convex.
* **Conjugate Frank-Wolfe** (Mitradjieva & Lindberg 2013): the search
  direction is the auxiliary flow mixed with the previous direction so that
  consecutive directions are conjugate with respect to the Hessian of ``Z``
  (diagonal - each link's BPR slope). Same per-iteration cost as Frank-Wolfe,
  and it removes the zig-zag that leaves plain Frank-Wolfe crawling once the
  network is congested: on the runtime matrix's congested fixture plain FW
  was still at a relative gap of 4.8e-3 after 50 iterations.
* **MSA**, the method of successive averages (Sheffi 1985 ch. 5): the same
  auxiliary flow, a predetermined step ``1/k``. Converges more slowly but
  needs no line search; offered because it is what many published screening
  studies used.

Convergence is *reported*, not assumed. The measure is the relative gap
(Boyce, Ralevic-Dekic & Bar-Gera 2004)

    gap = (sum_a t_a v_a - sum_od d_od * u_od) / sum_a t_a v_a

where ``u_od`` is the current shortest-path cost: the share of total travel
time that would be saved if every driver could switch to the current best
route at the current costs. It is zero at equilibrium and never negative.

Arcs, not edges: a two-way street is two directed arcs with their own
volume, capacity and congested time. Parallel arcs between the same ordered
node pair are collapsed to the cheapest one before routing - a shortest path
can only ever use that one, and collapsing makes the SciPy fast path and the
pure-Python fallback route over the identical arc set.

Deterministic: no sampling, fixed iteration order, so the same inputs give
the same volumes to the last bit on the same platform.
"""
from __future__ import annotations

import heapq

import numpy as np

from . import HAS_SCIPY

INF = float("inf")

#: Bureau of Public Roads (1964) defaults - the values every textbook quotes.
BPR_ALPHA = 0.15
BPR_BETA = 4.0


# --------------------------------------------------------------------------- #
# Volume-delay
# --------------------------------------------------------------------------- #
def bpr_time(t0, volume, capacity, alpha=BPR_ALPHA, beta=BPR_BETA):
    """Congested travel time on every arc (same units as ``t0``)."""
    t0 = np.asarray(t0, dtype=np.float64)
    ratio = np.asarray(volume, dtype=np.float64) / np.asarray(capacity, dtype=np.float64)
    return t0 * (1.0 + alpha * np.power(ratio, beta))


def bpr_integral(t0, volume, capacity, alpha=BPR_ALPHA, beta=BPR_BETA):
    """Integral of the BPR function from 0 to ``volume`` (Beckmann's term)."""
    t0 = np.asarray(t0, dtype=np.float64)
    v = np.asarray(volume, dtype=np.float64)
    c = np.asarray(capacity, dtype=np.float64)
    return t0 * (v + alpha * c / (beta + 1.0) * np.power(v / c, beta + 1.0))


def beckmann_objective(t0, volume, capacity, alpha=BPR_ALPHA, beta=BPR_BETA):
    """Beckmann's objective Z(v): the quantity user equilibrium minimises."""
    return float(np.sum(bpr_integral(t0, volume, capacity, alpha, beta)))


# --------------------------------------------------------------------------- #
# Arc network
# --------------------------------------------------------------------------- #
class ArcNetwork:
    """Directed arcs of a CSR graph, with parallel arcs collapsed for routing.

    ``arc_from``/``arc_to`` hold every directed adjacency entry of the input
    CSR (one per arc, in CSR order). ``route_arc`` is the subset routing may
    use: for each ordered node pair the arc with the lowest *free-flow* cost
    (ties go to the lower arc index). Congested costs can reorder parallel
    arcs only if their free-flow costs and capacities differ, which a
    screening network almost never carries; the collapse is stated rather
    than hidden.
    """

    def __init__(self, indptr, adj_node, n, free_flow):
        indptr = np.asarray(indptr, dtype=np.int64)
        self.n = int(n)
        self.arc_to = np.asarray(adj_node, dtype=np.int64)
        counts = np.diff(indptr)
        self.arc_from = np.repeat(np.arange(self.n, dtype=np.int64), counts)
        self.num_arcs = len(self.arc_to)
        free_flow = np.asarray(free_flow, dtype=np.float64)
        if len(free_flow) != self.num_arcs:
            raise ValueError("free_flow needs one cost per arc")
        keep = self.arc_from != self.arc_to          # a self-loop goes nowhere
        idx = np.nonzero(keep)[0]
        key = self.arc_from[idx] * self.n + self.arc_to[idx]
        order = np.lexsort((idx, free_flow[idx], key))
        sorted_keys = key[order]
        first = np.ones(len(order), dtype=bool)
        first[1:] = sorted_keys[1:] != sorted_keys[:-1]
        self.route_arc = np.sort(idx[order][first])
        self.loops = int((~keep).sum())
        self.parallel = int(len(idx) - len(self.route_arc))
        ra = self.route_arc
        counts = np.bincount(self.arc_from[ra], minlength=self.n)
        self.r_indptr = np.concatenate([[0], np.cumsum(counts)]).astype(np.int64)
        self.r_to = self.arc_to[ra]
        # pair key -> arc, sorted, for mapping a SciPy predecessor back to an arc
        self._pair_keys = self.arc_from[ra] * self.n + self.arc_to[ra]
        self._pair_order = np.argsort(self._pair_keys, kind="stable")

    def arc_of(self, pred, node):
        """Arc ids carrying each (pred[i] -> node[i]) step."""
        keys = np.asarray(pred, dtype=np.int64) * self.n + np.asarray(node, dtype=np.int64)
        sk = self._pair_keys[self._pair_order]
        pos = np.searchsorted(sk, keys)
        return self.route_arc[self._pair_order[pos]]


def _tree_pure(net, cost_r, source):
    """Heap Dijkstra over the routing arcs; returns (dist, pred_arc)."""
    dist = np.full(net.n, INF)
    pred_arc = np.full(net.n, -1, dtype=np.int64)
    dist[source] = 0.0
    heap = [(0.0, source)]
    indptr, to = net.r_indptr, net.r_to
    while heap:
        d, u = heapq.heappop(heap)
        if d > dist[u]:
            continue
        for k in range(indptr[u], indptr[u + 1]):
            v = to[k]
            nd = d + cost_r[k]
            if nd < dist[v]:
                dist[v] = nd
                pred_arc[v] = net.route_arc[k]
                heapq.heappush(heap, (nd, v))
    return dist, pred_arc


def shortest_trees(net, arc_cost, sources, use_scipy=None):
    """Distances and predecessor arcs from every source node.

    Returns ``(dist, pred_arc)``, both shaped ``(len(sources), n)``. The
    SciPy and pure paths route over the same collapsed arc set; with no tied
    path costs they return identical trees.
    """
    sources = np.asarray(sources, dtype=np.int64)
    cost_r = np.asarray(arc_cost, dtype=np.float64)[net.route_arc]
    if use_scipy is None:
        use_scipy = HAS_SCIPY
    if use_scipy and len(sources):
        from scipy.sparse import csr_matrix
        from scipy.sparse import csgraph
        # Strictly positive weights: an explicit zero in a CSR is dropped by
        # SciPy as "no edge", which would silently delete zero-cost arcs.
        w = np.maximum(cost_r, 1e-12)
        matrix = csr_matrix((w, net.r_to, net.r_indptr), shape=(net.n, net.n))
        dist, pred = csgraph.dijkstra(matrix, directed=True, indices=sources,
                                      return_predecessors=True)
        pred_arc = np.full(pred.shape, -1, dtype=np.int64)
        ok = pred >= 0
        rows, cols = np.nonzero(ok)
        if len(rows):
            pred_arc[rows, cols] = net.arc_of(pred[rows, cols], cols)
        return dist, pred_arc
    dist = np.empty((len(sources), net.n))
    pred_arc = np.empty((len(sources), net.n), dtype=np.int64)
    for i, s in enumerate(sources):
        dist[i], pred_arc[i] = _tree_pure(net, cost_r, int(s))
    return dist, pred_arc


def _load_tree(net, dist, pred_arc, node_demand, volume):
    """Push one origin's demand back along its shortest-path tree.

    ``node_demand[v]`` is the demand from this origin ending at node v. Nodes
    are processed farthest first, so each node's accumulated flow is final
    before it is handed to its predecessor - O(n log n), not O(paths x
    length).
    """
    reach = np.nonzero(np.isfinite(dist) & (pred_arc >= 0))[0]
    if not len(reach):
        return
    order = reach[np.argsort(-dist[reach], kind="stable")]
    flow = node_demand.astype(np.float64).copy()
    for v in order:
        f = flow[v]
        if f <= 0.0:
            continue
        a = pred_arc[v]
        volume[a] += f
        flow[net.arc_from[a]] += f


def all_or_nothing(net, arc_cost, origin_nodes, dest_nodes, demand,
                   use_scipy=None):
    """Assign every OD pair entirely to its current shortest path.

    ``demand`` is (len(origin_nodes), len(dest_nodes)). Returns a dict with
    the arc ``volume``, ``sptt`` (sum of demand x shortest cost - the
    lower bound the gap is measured against), ``unreachable`` demand and
    ``intrazonal`` demand (origin and destination on the same node: it never
    enters the network and is reported, not assigned).
    """
    origin_nodes = np.asarray(origin_nodes, dtype=np.int64)
    dest_nodes = np.asarray(dest_nodes, dtype=np.int64)
    demand = np.asarray(demand, dtype=np.float64)
    volume = np.zeros(net.num_arcs, dtype=np.float64)
    uniq, inverse = np.unique(origin_nodes, return_inverse=True)
    dist, pred_arc = shortest_trees(net, arc_cost, uniq, use_scipy)
    sptt = unreachable = intrazonal = 0.0
    for u_pos, o_node in enumerate(uniq):
        rows = np.nonzero(inverse == u_pos)[0]
        node_demand = np.zeros(net.n, dtype=np.float64)
        for r in rows:
            np.add.at(node_demand, dest_nodes, demand[r])
        same = node_demand[o_node]
        intrazonal += same
        node_demand[o_node] = 0.0
        d = dist[u_pos]
        lost = ~np.isfinite(d) & (node_demand > 0)
        unreachable += float(node_demand[lost].sum())
        node_demand[lost] = 0.0
        ok = node_demand > 0
        sptt += float(np.sum(node_demand[ok] * d[ok]))
        _load_tree(net, d, pred_arc[u_pos], node_demand, volume)
    return {"volume": volume, "sptt": sptt, "unreachable": unreachable,
            "intrazonal": intrazonal}


def bpr_slope(t0, volume, capacity, alpha=BPR_ALPHA, beta=BPR_BETA):
    """dt/dv of the BPR function: the diagonal of Beckmann's Hessian."""
    t0 = np.asarray(t0, dtype=np.float64)
    c = np.asarray(capacity, dtype=np.float64)
    v = np.maximum(np.asarray(volume, dtype=np.float64), 0.0)
    if beta == 0:
        return np.zeros_like(v)
    return t0 * alpha * beta * np.power(v / c, beta - 1.0) / c


def _conjugate_direction(t0, capacity, v, y, previous, alpha, beta, delta=1e-4):
    """Mitradjieva & Lindberg's (2013) conjugate target point.

    ``s = a * previous + (1 - a) * y`` with ``a`` chosen so that ``s - v`` is
    conjugate to ``previous - v`` under the diagonal Hessian; ``a`` is kept in
    [0, 1 - delta] so the new point never collapses onto the old one.
    """
    if previous is None:
        return y
    h = bpr_slope(t0, v, capacity, alpha, beta)
    d_prev = previous - v
    numerator = float(np.sum(d_prev * h * (y - v)))
    denominator = float(np.sum(d_prev * h * (y - previous)))
    if denominator == 0.0:
        return y
    a = numerator / denominator
    a = min(max(a, 0.0), 1.0 - delta)
    return a * previous + (1.0 - a) * y


def _line_search(t0, capacity, v, y, alpha, beta, iterations=40):
    """Exact Frank-Wolfe step: the lambda in [0, 1] minimising Z(v + l(y - v)).

    Z is convex along the segment, so its derivative
    ``sum (y - v) * t(v + l (y - v))`` is non-decreasing in ``l``; bisection on
    its sign finds the minimiser to 2**-40.
    """
    direction = y - v

    def slope(lam):
        return float(np.sum(direction * bpr_time(t0, v + lam * direction, capacity, alpha, beta)))

    if slope(1.0) <= 0.0:
        return 1.0
    if slope(0.0) >= 0.0:
        return 0.0
    lo, hi = 0.0, 1.0
    for _ in range(iterations):
        mid = 0.5 * (lo + hi)
        if slope(mid) > 0.0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def equilibrium(net, t0, capacity, origin_nodes, dest_nodes, demand,
                method="fw", max_iter=50, gap_tol=1e-4,
                alpha=BPR_ALPHA, beta=BPR_BETA, use_scipy=None, cancel=None,
                progress=None):
    """Solve the static assignment.

    ``method`` is ``"aon"`` (one all-or-nothing pass on free-flow costs),
    ``"msa"``, ``"fw"`` or ``"cfw"``. Returns a dict:

    ``volume``, ``time`` (congested), ``history`` - one dict per iteration
    with ``iteration``, ``gap``, ``tstt`` (total system travel time,
    ``sum t v``), ``sptt``, ``objective`` (Beckmann) and ``step`` -, plus
    ``converged``, ``iterations``, ``unreachable`` and ``intrazonal``.
    """
    t0 = np.asarray(t0, dtype=np.float64)
    capacity = np.asarray(capacity, dtype=np.float64)
    if np.any(capacity <= 0) or not np.all(np.isfinite(capacity)):
        raise ValueError("every arc needs a positive, finite capacity")
    if np.any(t0 <= 0) or not np.all(np.isfinite(t0)):
        raise ValueError("every arc needs a positive, finite free-flow time")
    if method not in ("aon", "msa", "fw", "cfw"):
        raise ValueError(f"unknown assignment method '{method}'")

    first = all_or_nothing(net, t0, origin_nodes, dest_nodes, demand, use_scipy)
    v = first["volume"]
    history = []
    converged = False
    if method == "aon":
        t = bpr_time(t0, v, capacity, alpha, beta)
        aux = all_or_nothing(net, t, origin_nodes, dest_nodes, demand, use_scipy)
        tstt = float(np.sum(t * v))
        gap = (tstt - aux["sptt"]) / tstt if tstt > 0 else 0.0
        history.append({"iteration": 1, "gap": gap, "tstt": tstt,
                        "sptt": aux["sptt"], "step": 1.0,
                        "objective": beckmann_objective(t0, v, capacity, alpha, beta)})
        return {"volume": v, "time": t, "history": history, "converged": False,
                "iterations": 1, "unreachable": first["unreachable"],
                "intrazonal": first["intrazonal"]}

    target = None
    for k in range(1, int(max_iter) + 1):
        if cancel is not None and cancel():
            break
        t = bpr_time(t0, v, capacity, alpha, beta)
        aux = all_or_nothing(net, t, origin_nodes, dest_nodes, demand, use_scipy)
        y = aux["volume"]
        tstt = float(np.sum(t * v))
        gap = max(0.0, (tstt - aux["sptt"]) / tstt) if tstt > 0 else 0.0
        if gap <= gap_tol:
            history.append({"iteration": k, "gap": gap, "tstt": tstt,
                            "sptt": aux["sptt"], "step": 0.0,
                            "objective": beckmann_objective(t0, v, capacity, alpha, beta)})
            converged = True
            break
        if method == "cfw":
            target = _conjugate_direction(t0, capacity, v, y, target, alpha, beta)
            step = _line_search(t0, capacity, v, target, alpha, beta)
            v = v + step * (target - v)
        elif method == "fw":
            step = _line_search(t0, capacity, v, y, alpha, beta)
            v = v + step * (y - v)
        else:
            step = 1.0 / (k + 1.0)
            v = v + step * (y - v)
        history.append({"iteration": k, "gap": gap, "tstt": tstt,
                        "sptt": aux["sptt"], "step": step,
                        "objective": beckmann_objective(t0, v, capacity, alpha, beta)})
        if progress is not None:
            progress(k / float(max_iter))
    t = bpr_time(t0, v, capacity, alpha, beta)
    return {"volume": v, "time": t, "history": history, "converged": converged,
            "iterations": len(history), "unreachable": first["unreachable"],
            "intrazonal": first["intrazonal"]}


def level_of_service(vc):
    """HCM-style LOS letter from a volume/capacity ratio (screening bands).

    A <= 0.60, B <= 0.70, C <= 0.80, D <= 0.90, E <= 1.00, F above - the
    v/c bands planning studies commonly use for link screening. They are a
    convention for reporting, not HCM 7th-edition facility LOS, which is
    defined on density or delay.
    """
    vc = float(vc)
    for limit, letter in ((0.60, "A"), (0.70, "B"), (0.80, "C"),
                          (0.90, "D"), (1.00, "E")):
        if vc <= limit:
            return letter
    return "F"
