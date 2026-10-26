# -*- coding: utf-8 -*-
"""Network link criticality (road-network vulnerability).

For a fixed set of origin-destination pairs, measure how much the total
shortest-path travel cost rises when each street segment (graph edge) is
removed - the Network Robustness Index idea (Scott, Novak, Aultman-Hall &
Guo 2006) and link importance in road-network vulnerability analysis
(Jenelius, Petersen & Mattsson 2006). An edge that carries no shortest path
has zero criticality; a link whose loss forces a long detour - or severs
demand entirely - is critical.

Pure NumPy on top of the embedded Dijkstra kernels: no QGIS, no external
routing plugin. The baseline pass uses the predecessor-tracking Dijkstra so
it also learns which edges each shortest path runs over (that both counts
edge usage and prunes the removal test to edges that can possibly matter -
an edge on no shortest path can never raise a shortest-path cost). Each
candidate edge is then removed and the OD costs recomputed with the fast
``many_to_many`` kernel.
"""
from __future__ import annotations

import numpy as np

from . import paths


def _drop_edge(indptr, adj_node, adj_cost, src, keep_mask, num_nodes):
    """Return CSR arrays with one edge's directed entries removed.

    ``src`` is the source node of every directed adjacency entry (precomputed
    once); ``keep_mask`` selects the entries to keep. Because the adjacency is
    already grouped by source, masking preserves CSR ordering and only the
    per-source counts (hence ``indptr``) need rebuilding.
    """
    counts = np.bincount(src[keep_mask], minlength=num_nodes)
    new_indptr = np.concatenate([[0], np.cumsum(counts)]).astype(np.int64)
    return new_indptr, adj_node[keep_mask], adj_cost[keep_mask]


def edge_criticality(indptr, adj_node, adj_edge, adj_cost, num_nodes, num_edges,
                     o_nodes, d_nodes, same_layer=False, cutoff=None,
                     progress=None, cancel=None):
    """Per-edge criticality over the given origin-destination demand.

    Parameters
    ----------
    indptr, adj_node, adj_edge, adj_cost :
        Undirected primal-graph CSR arrays as built by ``graphs.NodeGraph``:
        for every directed adjacency entry, the destination node, the *edge
        id* (aligned with the input polylines) and the routing cost.
    num_nodes, num_edges : int
        Graph sizes.
    o_nodes, d_nodes : int arrays
        The graph node each origin / destination snaps to.
    same_layer : bool
        When True the destinations ARE the origins; the ``i == j`` self pair is
        skipped.
    cutoff : float or None
        Optional maximum path cost; pairs beyond it count as unreachable.
    progress : callable or None
        ``progress(fraction_0_1)`` for UI feedback over the candidate edges.
    cancel : callable or None
        ``cancel() -> True`` aborts early (partial results are returned).

    Returns
    -------
    dict with per-edge arrays of length ``num_edges`` (aligned with the input
    polylines):
        ``criticality``    - ``extra_cost / base_total``: the relative rise in
            total OD travel cost from losing this edge (dimensionless; 0 for
            edges on no shortest path),
        ``extra_cost``     - absolute added OD travel cost over the pairs that
            stay connected (cost-field units),
        ``n_disconnected`` - OD pairs that were reachable and become
            unreachable when this edge is removed,
        ``used_by``        - OD pairs whose shortest path runs over this edge,
    and the scalars ``base_total`` (sum of reachable baseline OD cost),
    ``n_pairs`` and ``n_reachable``.
    """
    indptr = np.asarray(indptr, dtype=np.int64)
    adj_node = np.asarray(adj_node, dtype=np.int64)
    adj_edge = np.asarray(adj_edge, dtype=np.int64)
    adj_cost = np.asarray(adj_cost, dtype=np.float64)
    o_nodes = np.asarray(o_nodes, dtype=np.int64)
    d_nodes = np.asarray(d_nodes, dtype=np.int64)
    n_o, n_d = len(o_nodes), len(d_nodes)

    criticality = np.zeros(num_edges, dtype=np.float64)
    extra_cost = np.zeros(num_edges, dtype=np.float64)
    n_disconnected = np.zeros(num_edges, dtype=np.int64)
    used_by = np.zeros(num_edges, dtype=np.int64)

    # --- baseline: OD costs + the edges each shortest path uses -------------- #
    base_cost = np.full((n_o, n_d), paths.INF)
    candidates = set()
    for i in range(n_o):
        if cancel is not None and cancel():
            break
        dist, pred_node, pred_edge = paths.shortest_path_tree(
            indptr, adj_node, adj_edge, adj_cost, num_nodes, int(o_nodes[i]),
            cutoff)
        row = dist[d_nodes]
        if same_layer:
            row = row.copy()
            row[i] = paths.INF  # exclude the self pair
        base_cost[i] = row
        for j in range(n_d):
            if not np.isfinite(base_cost[i, j]):
                continue
            _, edges = paths.path_to_root(pred_node, pred_edge, int(d_nodes[j]))
            for e in edges:
                used_by[e] += 1
                candidates.add(int(e))

    reachable_base = np.isfinite(base_cost)
    base_total = float(base_cost[reachable_base].sum())
    n_reachable = int(reachable_base.sum())
    n_pairs = n_o * n_d - (n_o if same_layer else 0)

    # --- remove each candidate edge and remeasure --------------------------- #
    src = np.repeat(np.arange(num_nodes, dtype=np.int64), np.diff(indptr))
    cand = sorted(candidates)
    for ci, e in enumerate(cand):
        if cancel is not None and cancel():
            break
        if progress is not None:
            progress(ci / len(cand))
        keep = adj_edge != e
        new_indptr, new_adj, new_cost = _drop_edge(
            indptr, adj_node, adj_cost, src, keep, num_nodes)
        newd = paths.many_to_many(new_indptr, new_adj, new_cost, num_nodes,
                                  o_nodes, cutoff=cutoff, cancel=cancel)
        new_od = newd[:, d_nodes]
        finite_new = np.isfinite(new_od)
        disc = reachable_base & ~finite_new
        # Removing an edge can only lengthen a shortest path; clip guards fp
        # noise so a still-optimal path never shows a spurious negative delta.
        delta = np.where(reachable_base & finite_new, new_od - base_cost, 0.0)
        np.clip(delta, 0.0, None, out=delta)
        extra_cost[e] = float(delta.sum())
        n_disconnected[e] = int(disc.sum())
        criticality[e] = extra_cost[e] / base_total if base_total > 0 else 0.0
    if progress is not None:
        progress(1.0)

    return {
        "criticality": criticality,
        "extra_cost": extra_cost,
        "n_disconnected": n_disconnected,
        "used_by": used_by,
        "base_total": base_total,
        "n_pairs": int(n_pairs),
        "n_reachable": n_reachable,
    }


# --------------------------------------------------------------------------- #
# Structural robustness: bridges, percolation and efficiency
# --------------------------------------------------------------------------- #
# Link criticality above answers "which link costs the most to lose for THIS
# demand". The functions below answer the demand-free structural questions
# that come before it: which links are the network's only connection between
# two parts (bridges), how fast the network falls apart as links fail at
# random or under attack (percolation), and how efficiently it carries
# movement at all (global efficiency, Latora & Marchiori 2001).


def _undirected_pairs(edge_from, edge_to):
    """Edge endpoint arrays with self-loops flagged (they never connect)."""
    edge_from = np.asarray(edge_from, dtype=np.int64)
    edge_to = np.asarray(edge_to, dtype=np.int64)
    return edge_from, edge_to, edge_from == edge_to


def bridges(num_nodes, edge_from, edge_to):
    """Boolean per edge: True when removing it disconnects its two ends.

    Tarjan's (1974) low-link test on the undirected multigraph, iteratively
    (a recursive DFS overflows Python's stack on a long street). Parallel
    edges are handled by remembering the *edge* the DFS arrived on rather
    than the parent node, so a doubled street is correctly not a bridge.
    """
    edge_from, edge_to, loop = _undirected_pairs(edge_from, edge_to)
    m = len(edge_from)
    adj = [[] for _ in range(num_nodes)]
    for e in range(m):
        if loop[e]:
            continue
        adj[edge_from[e]].append((edge_to[e], e))
        adj[edge_to[e]].append((edge_from[e], e))
    disc = np.full(num_nodes, -1, dtype=np.int64)
    low = np.zeros(num_nodes, dtype=np.int64)
    is_bridge = np.zeros(m, dtype=bool)
    timer = 0
    for root in range(num_nodes):
        if disc[root] >= 0:
            continue
        disc[root] = low[root] = timer
        timer += 1
        stack = [(root, -1, 0)]
        while stack:
            u, in_edge, i = stack[-1]
            if i < len(adj[u]):
                stack[-1] = (u, in_edge, i + 1)
                v, e = adj[u][i]
                if e == in_edge:
                    continue
                if disc[v] < 0:
                    disc[v] = low[v] = timer
                    timer += 1
                    stack.append((v, e, 0))
                else:
                    low[u] = min(low[u], disc[v])
            else:
                stack.pop()
                if stack:
                    p = stack[-1][0]
                    low[p] = min(low[p], low[u])
                    if low[u] > disc[p]:
                        is_bridge[in_edge] = True
    return is_bridge


class _DisjointSet:
    __slots__ = ("parent", "size", "largest")

    def __init__(self, n):
        self.parent = np.arange(n, dtype=np.int64)
        self.size = np.ones(n, dtype=np.int64)
        self.largest = 1 if n else 0

    def find(self, x):
        parent = self.parent
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.size[ra] < self.size[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        self.size[ra] += self.size[rb]
        if self.size[ra] > self.largest:
            self.largest = int(self.size[ra])


def giant_component_curve(num_nodes, edge_from, edge_to, removal_order):
    """Largest-component share after removing the first k edges of an order.

    Returns an array ``g`` of length ``E + 1``: ``g[k]`` is the share of nodes
    in the largest connected component once the first ``k`` edges of
    ``removal_order`` are gone. Computed in reverse - start empty and add the
    edges back last-removed first - so one union-find pass gives the whole
    curve in near-linear time instead of one component search per step.
    """
    edge_from, edge_to, loop = _undirected_pairs(edge_from, edge_to)
    order = np.asarray(removal_order, dtype=np.int64)
    m = len(order)
    out = np.zeros(m + 1, dtype=np.float64)
    if num_nodes == 0:
        return out
    ds = _DisjointSet(num_nodes)
    out[m] = ds.largest / num_nodes
    for k in range(m - 1, -1, -1):
        e = order[k]
        if not loop[e]:
            ds.union(int(edge_from[e]), int(edge_to[e]))
        out[k] = ds.largest / num_nodes
    return out


def robustness_index(curve):
    """Schneider et al. (2011) R: the mean largest-component share over the
    removal sequence (excluding the intact state). 0.5 is the ceiling a
    simple path approaches; a well-meshed grid holds R well above that
    against random failure and falls toward it under targeted attack."""
    curve = np.asarray(curve, dtype=np.float64)
    if len(curve) < 2:
        return 0.0
    return float(curve[1:].mean())


def critical_fraction(curve, threshold=0.5):
    """Smallest removed-edge share at which the largest component falls
    below ``threshold`` of the nodes (1.0 if it never does)."""
    curve = np.asarray(curve, dtype=np.float64)
    m = len(curve) - 1
    below = np.nonzero(curve < threshold)[0]
    if not len(below) or m <= 0:
        return 1.0
    return float(below[0]) / m


def global_efficiency(indptr, adj, weights, n, sources=None, cancel=None):
    """Latora & Marchiori (2001) global efficiency, weighted by cost.

    ``E = 1 / (n (n - 1)) * sum_{i != j} 1 / d_ij`` with unreachable pairs
    contributing zero - which is what makes it usable on a fragmented
    network where average path length is undefined. With ``sources`` a
    seeded subset is used and the mean is taken over those rows only.
    Returns the efficiency in inverse cost units (1/m for a length graph).
    """
    from . import paths
    if n < 2:
        return 0.0
    src = np.arange(n) if sources is None else np.asarray(sources, dtype=np.int64)
    total = 0.0
    for chunk_start in range(0, len(src), 256):
        if cancel is not None and cancel():
            break
        chunk = src[chunk_start:chunk_start + 256]
        dist = paths.many_to_many(indptr, adj, weights, n, chunk)
        with np.errstate(divide="ignore"):
            inv = np.where(np.isfinite(dist) & (dist > 0), 1.0 / dist, 0.0)
        total += float(inv.sum())
    return total / (len(src) * (n - 1))
