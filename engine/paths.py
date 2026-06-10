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
