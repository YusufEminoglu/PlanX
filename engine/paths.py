# -*- coding: utf-8 -*-
"""Shortest-path kernels.

SciPy's ``sparse.csgraph`` is used when available (C speed); otherwise a
pure-Python binary-heap Dijkstra produces identical distances. All functions
take raw CSR arrays so they work for both the primal and the dual graph.
"""
from __future__ import annotations

import heapq

import numpy as np

from . import HAS_SCIPY

INF = float("inf")


def _to_scipy(indptr, adj, weights, n):
    from scipy.sparse import csr_matrix
    return csr_matrix((weights, adj, indptr), shape=(n, n))


# --------------------------------------------------------------------------- #
def _heap_dijkstra(indptr, adj, weights, n, source, cutoff=None):
    dist = np.full(n, INF)
    dist[source] = 0.0
    heap = [(0.0, source)]
    while heap:
        d, u = heapq.heappop(heap)
        if d > dist[u]:
            continue
        for k in range(indptr[u], indptr[u + 1]):
            v = adj[k]
            nd = d + weights[k]
            if cutoff is not None and nd > cutoff:
                continue
            if nd < dist[v]:
                dist[v] = nd
                heapq.heappush(heap, (nd, v))
    return dist


def many_to_many(indptr, adj, weights, n, sources, cutoff=None, cancel=None):
    """Distances from each source to every node: (len(sources), n) array."""
    sources = np.asarray(sources, dtype=np.int64)
    if HAS_SCIPY:
        from scipy.sparse import csgraph
        return csgraph.dijkstra(
            _to_scipy(indptr, adj, weights, n),
            directed=False, indices=sources,
            limit=INF if cutoff is None else float(cutoff),
        )
    out = np.empty((len(sources), n))
    for i, s in enumerate(sources):
        if cancel is not None and cancel():
            break
        out[i] = _heap_dijkstra(indptr, adj, weights, n, int(s), cutoff)
    return out


def multi_source(indptr, adj, weights, n, sources, cutoff=None):
    """Min cost from *any* source: returns (dist[n], nearest_source_pos[n]).

    ``nearest_source_pos`` holds the position in ``sources`` of the winning
    source (-1 where unreachable).
    """
    sources = np.asarray(sources, dtype=np.int64)
    if HAS_SCIPY:
        from scipy.sparse import csgraph
        dist, _, src_node = csgraph.dijkstra(
            _to_scipy(indptr, adj, weights, n),
            directed=False, indices=sources, min_only=True,
            return_predecessors=True,
            limit=INF if cutoff is None else float(cutoff),
        )
        pos = {int(node): i for i, node in enumerate(sources)}
        label = np.array([pos.get(int(s), -1) for s in src_node], dtype=np.int64)
        label[~np.isfinite(dist)] = -1
        return dist, label
    dist = np.full(n, INF)
    label = np.full(n, -1, dtype=np.int64)
    heap = []
    for i, s in enumerate(sources):
        s = int(s)
        if dist[s] > 0.0:
            dist[s] = 0.0
            label[s] = i
            heap.append((0.0, s, i))
    heapq.heapify(heap)
    while heap:
        d, u, lab = heapq.heappop(heap)
        if d > dist[u]:
            continue
        for k in range(indptr[u], indptr[u + 1]):
            v = adj[k]
            nd = d + weights[k]
            if cutoff is not None and nd > cutoff:
                continue
            if nd < dist[v]:
                dist[v] = nd
                label[v] = lab
                heapq.heappush(heap, (nd, v, lab))
    return dist, label


def shortest_path_tree(indptr, adj_node, adj_edge, weights, n, source,
                       cutoff=None):
    """Dijkstra with predecessor tracking for route reconstruction.

    Returns ``(dist, pred_node, pred_edge)``: for every node its cost from
    ``source``, the previous node on the shortest path and the id of the
    edge used to arrive (both -1 at the source and where unreachable).
    Pure heapq on purpose - it must report *which* parallel edge was taken,
    which the SciPy kernel cannot; distances are identical to
    :func:`many_to_many`.
    """
    dist = np.full(n, INF)
    pred_node = np.full(n, -1, dtype=np.int64)
    pred_edge = np.full(n, -1, dtype=np.int64)
    dist[source] = 0.0
    heap = [(0.0, source)]
    while heap:
        d, u = heapq.heappop(heap)
        if d > dist[u]:
            continue
        for k in range(indptr[u], indptr[u + 1]):
            v = adj_node[k]
            nd = d + weights[k]
            if cutoff is not None and nd > cutoff:
                continue
            if nd < dist[v]:
                dist[v] = nd
                pred_node[v] = u
                pred_edge[v] = adj_edge[k]
                heapq.heappush(heap, (nd, v))
    return dist, pred_node, pred_edge


def reconstruct_path(pred_node, pred_edge, source, target):
    """Walk the predecessor arrays back from ``target`` to ``source``.

    Returns ``(nodes, edges)`` in travel order (nodes has one more entry
    than edges); both empty when the target is unreachable.
    """
    if target == source:
        return [int(source)], []
    if pred_node[target] < 0:
        return [], []
    nodes = [int(target)]
    edges = []
    cur = int(target)
    while cur != source:
        edges.append(int(pred_edge[cur]))
        cur = int(pred_node[cur])
        nodes.append(cur)
        if len(nodes) > len(pred_node):  # corrupt input guard
            return [], []
    nodes.reverse()
    edges.reverse()
    return nodes, edges


def multi_source_offset(indptr, adj, weights, n, sources, offsets,
                        cutoff=None):
    """Min over sources of ``offset_s + path cost`` to every node.

    Like :func:`multi_source` but each source enters the heap at its own
    initial cost - the egress kernel of transit accessibility (offset =
    arrival time at a stop, weights = walking seconds). Pure heapq.
    Returns (cost[n], winning_source_pos[n] with -1 where unreachable).
    """
    sources = np.asarray(sources, dtype=np.int64)
    offsets = np.asarray(offsets, dtype=np.float64)
    dist = np.full(n, INF)
    label = np.full(n, -1, dtype=np.int64)
    heap = []
    for i, s in enumerate(sources):
        s = int(s)
        off = float(offsets[i])
        if not np.isfinite(off):
            continue
        if off < dist[s]:
            dist[s] = off
            label[s] = i
            heap.append((off, s, i))
    heapq.heapify(heap)
    while heap:
        d, u, lab = heapq.heappop(heap)
        if d > dist[u]:
            continue
        for k in range(indptr[u], indptr[u + 1]):
            v = adj[k]
            nd = d + weights[k]
            if cutoff is not None and nd > cutoff:
                continue
            if nd < dist[v]:
                dist[v] = nd
                label[v] = lab
                heapq.heappush(heap, (nd, v, lab))
    return dist, label


def dijkstra_pruned(indptr, adj, w_cost, w_prune, n, source, radius):
    """Dijkstra minimizing ``w_cost`` while pruning expansion once the
    accumulated ``w_prune`` of the settled path exceeds ``radius``.

    This is the standard idiom of space syntax segment analysis: minimize
    *angular* cost within a *metric* radius. Returns (cost[n], prune_dist[n]).
    """
    cost = np.full(n, INF)
    prune = np.full(n, INF)
    cost[source] = 0.0
    prune[source] = 0.0
    heap = [(0.0, 0.0, source)]
    while heap:
        c, p, u = heapq.heappop(heap)
        if c > cost[u]:
            continue
        for k in range(indptr[u], indptr[u + 1]):
            v = adj[k]
            np_ = p + w_prune[k]
            if radius is not None and np_ > radius:
                continue
            nc = c + w_cost[k]
            if nc < cost[v]:
                cost[v] = nc
                prune[v] = np_
                heapq.heappush(heap, (nc, np_, v))
    return cost, prune


def multi_source_tree(indptr, adj_node, adj_edge, weights, n, sources,
                      cutoff=None):
    """Multi-source Dijkstra with predecessor tracking.

    Same relaxation and tie behaviour as ``multi_source`` (labels win by
    strict improvement only, so on an exact tie the earlier-settled source
    keeps the node), but additionally records for every node the previous
    node and the edge id used to arrive. Returns
    ``(dist, label, pred_node, pred_edge)``; ``label`` indexes into
    ``sources``; ``pred_node``/``pred_edge`` are -1 at the sources and at
    unreachable nodes. ``dist`` and ``label`` must be numerically IDENTICAL
    to ``multi_source`` for the same inputs (unit-tested).
    """
    sources = np.asarray(sources, dtype=np.int64)
    dist = np.full(n, INF)
    label = np.full(n, -1, dtype=np.int64)
    pred_node = np.full(n, -1, dtype=np.int64)
    pred_edge = np.full(n, -1, dtype=np.int64)
    heap = []
    for i, s in enumerate(sources):
        s = int(s)
        if dist[s] > 0.0:
            dist[s] = 0.0
            label[s] = i
            heap.append((0.0, s, i))
    heapq.heapify(heap)
    while heap:
        d, u, lab = heapq.heappop(heap)
        if d > dist[u]:
            continue
        for k in range(indptr[u], indptr[u + 1]):
            v = adj_node[k]
            nd = d + weights[k]
            if cutoff is not None and nd > cutoff:
                continue
            if nd < dist[v]:
                dist[v] = nd
                label[v] = lab
                pred_node[v] = u
                pred_edge[v] = adj_edge[k]
                heapq.heappush(heap, (nd, v, lab))
    return dist, label, pred_node, pred_edge


def path_to_root(pred_node, pred_edge, target):
    """Walk predecessors from ``target`` back to its source root.

    Returns ``(nodes, edges)`` in ROOT->TARGET travel order (nodes has one
    more entry than edges). ``([target], [])`` when target is itself a root
    (pred -1 but finite dist is the caller's check); ``([], [])`` when the
    walk exceeds len(pred_node) (corrupt input guard, same as
    reconstruct_path).
    """
    target = int(target)
    if pred_node[target] < 0:
        return [target], []
    nodes = [target]
    edges = []
    cur = target
    while pred_node[cur] >= 0:
        edges.append(int(pred_edge[cur]))
        cur = int(pred_node[cur])
        nodes.append(cur)
        if len(nodes) > len(pred_node):
            return [], []
    nodes.reverse()
    edges.reverse()
    return nodes, edges
