# -*- coding: utf-8 -*-
"""Cost distance, least-cost paths and least-cost corridors on a raster.

A resistance raster gives the cost of crossing one metre of each cell - for
an animal, a pipeline, a pedestrian on rough ground. The accumulated cost of
the cheapest way from a set of sources to every cell is the *cost-weighted
distance* (Esri's Cost Distance; Adriaensen et al. 2003 for its ecological
reading), computed here as Dijkstra on the grid graph:

    w(a, b) = (r_a + r_b) / 2 * step(a, b)

with ``step`` the cell size for a rook move and ``sqrt(2)`` times it for a
diagonal one under the 8-neighbour rule - the trapezoid rule every GIS uses,
so a path is charged half of each cell it leaves and half of each it enters.
A NaN (nodata) cell is a barrier: nothing enters or leaves it.

A **least-cost corridor** between two habitat sets A and B is the sum of the
two cost-distance surfaces; its minimum is the least-cost path's cost, and
subtracting that minimum gives the normalised corridor of Linkage Mapper
(McRae & Kavanagh 2011): zero along the best path and, everywhere else, how
much dearer a route through that cell would be. Thresholding it at a slack
gives a corridor of near-optimal routes rather than a single line, which is
what a planner can actually protect.

SciPy's ``csgraph.dijkstra`` is used when present; the pure ``heapq`` kernel
gives identical costs (asserted by the tests).
"""
from __future__ import annotations

import heapq
import math

import numpy as np

INF = float("inf")


def _moves(rule):
    rook = ((1, 0), (-1, 0), (0, 1), (0, -1))
    if rule == 4:
        return [(dr, dc, 1.0) for dr, dc in rook]
    diag = ((1, 1), (1, -1), (-1, 1), (-1, -1))
    return [(dr, dc, 1.0) for dr, dc in rook] + [(dr, dc, math.sqrt(2.0)) for dr, dc in diag]


def grid_graph(resistance, cell, rule=8):
    """CSR arrays of the grid graph: (indptr, adj, weights, n)."""
    r = np.asarray(resistance, dtype=np.float64)
    rows, cols = r.shape
    n = rows * cols
    ok = np.isfinite(r) & (r >= 0)
    src_list, dst_list, w_list = [], [], []
    idx = np.arange(n).reshape(rows, cols)
    for dr, dc, factor in _moves(rule):
        r0 = slice(max(0, -dr), rows - max(0, dr))
        c0 = slice(max(0, -dc), cols - max(0, dc))
        r1 = slice(max(0, dr), rows - max(0, -dr) if dr < 0 else rows)
        c1 = slice(max(0, dc), cols - max(0, -dc) if dc < 0 else cols)
        a_ok = ok[r0, c0]
        b_ok = ok[r1, c1]
        both = a_ok & b_ok
        src_list.append(idx[r0, c0][both])
        dst_list.append(idx[r1, c1][both])
        w_list.append(((r[r0, c0] + r[r1, c1]) * 0.5 * factor * cell)[both])
    src = np.concatenate(src_list)
    dst = np.concatenate(dst_list)
    w = np.concatenate(w_list)
    order = np.lexsort((dst, src))
    src, dst, w = src[order], dst[order], w[order]
    indptr = np.concatenate([[0], np.cumsum(np.bincount(src, minlength=n))]).astype(np.int64)
    return indptr, dst.astype(np.int64), w, n


def cost_distance(resistance, sources, cell, rule=8, use_scipy=None):
    """Accumulated cost from the nearest source cell, and predecessor cells.

    ``sources`` is a boolean grid (or flat index array). Returns
    ``(cost grid with inf where unreachable, predecessor grid with -1 at
    sources and unreachable cells)``.
    """
    r = np.asarray(resistance, dtype=np.float64)
    shape = r.shape
    indptr, adj, w, n = grid_graph(r, cell, rule)
    src = np.asarray(sources)
    src = np.nonzero(src.ravel())[0] if src.dtype == bool else src.astype(np.int64)
    src = src[np.isfinite(r.ravel()[src])]
    if not len(src):
        raise ValueError("no source cell lies on a passable (non-nodata) cell")
    if use_scipy is None:
        try:
            import scipy.sparse.csgraph  # noqa: F401
            use_scipy = True
        except Exception:
            use_scipy = False
    if use_scipy:
        from scipy.sparse import csr_matrix
        from scipy.sparse import csgraph
        # Zero-resistance moves would vanish from a CSR ("no edge"); a floor
        # far below any real cost keeps them while changing no total.
        matrix = csr_matrix((np.maximum(w, 1e-12), adj, indptr), shape=(n, n))
        dist, pred, _ = csgraph.dijkstra(matrix, directed=True, indices=src,
                                         min_only=True, return_predecessors=True)
        pred = np.where(pred < 0, -1, pred)
    else:
        dist = np.full(n, INF)
        pred = np.full(n, -1, dtype=np.int64)
        heap = []
        for s in src:
            dist[s] = 0.0
            heap.append((0.0, int(s)))
        heapq.heapify(heap)
        while heap:
            d, u = heapq.heappop(heap)
            if d > dist[u]:
                continue
            for k in range(indptr[u], indptr[u + 1]):
                v = adj[k]
                nd = d + max(w[k], 1e-12)
                if nd < dist[v]:
                    dist[v] = nd
                    pred[v] = u
                    heapq.heappush(heap, (nd, v))
    return dist.reshape(shape), np.asarray(pred, dtype=np.int64).reshape(shape)


def trace_path(pred, end_cell):
    """Cells from a source to ``end_cell`` (flat index), in travel order."""
    flat = np.asarray(pred).ravel()
    path = [int(end_cell)]
    while flat[path[-1]] >= 0:
        path.append(int(flat[path[-1]]))
        if len(path) > flat.size:
            raise ValueError("predecessor grid has a cycle")
    path.reverse()
    return path


def corridor(cost_a, cost_b):
    """Normalised least-cost corridor and the least-cost path cost.

    ``cost_a + cost_b - min``: 0 on the best path, inf where a cell cannot be
    reached from both sides.
    """
    total = np.asarray(cost_a, dtype=np.float64) + np.asarray(cost_b, dtype=np.float64)
    finite = np.isfinite(total)
    if not finite.any():
        raise ValueError("no cell is reachable from both source sets")
    best = float(total[finite].min())
    return total - best, best
