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
