# -*- coding: utf-8 -*-
"""Centrality measures on CSR graphs.

* Closeness / harmonic closeness / straightness from chunked Dijkstra rows.
* Betweenness via Brandes (2001), weighted, with optional radius limiting
  (on the routing cost or on a second "prune" weight, as space syntax choice
  requires) and optional source sampling for very large networks.

Everything is exact pure-Python/NumPy; SciPy only accelerates the
distance-matrix part.
"""
from __future__ import annotations

import heapq

import numpy as np

from . import paths

INF = float("inf")
_EPS = 1e-9


def closeness_straightness(indptr, adj, weights, n, node_xy=None,
                           radius=None, chunk=128, cancel=None, progress=None):
    """Per-node reach, farness, closeness (Wasserman-Faust), harmonic
    closeness and (if ``node_xy`` given) straightness centrality.

    Returns dict of float64 arrays.
    """
    reach = np.zeros(n, dtype=np.float64)
    farness = np.zeros(n, dtype=np.float64)
    harmonic = np.zeros(n, dtype=np.float64)
    straight = np.zeros(n, dtype=np.float64)
    all_nodes = np.arange(n, dtype=np.int64)
    for start in range(0, n, chunk):
        if cancel is not None and cancel():
            break
        idx = all_nodes[start:start + chunk]
        dmat = paths.many_to_many(indptr, adj, weights, n, idx, cutoff=radius)
        with np.errstate(divide="ignore", invalid="ignore"):
            for row, s in enumerate(idx):
                d = dmat[row]
                mask = np.isfinite(d)
                mask[s] = False
                r = int(mask.sum())
                reach[s] = r
                if r == 0:
                    continue
                ds = d[mask]
                farness[s] = ds.sum()
                harmonic[s] = (1.0 / ds).sum()
                if node_xy is not None:
                    eu = np.hypot(node_xy[mask, 0] - node_xy[s, 0],
                                  node_xy[mask, 1] - node_xy[s, 1])
                    ok = ds > 0
                    straight[s] = float((eu[ok] / ds[ok]).mean()) if ok.any() else 0.0
        if progress is not None:
            progress(min(1.0, (start + chunk) / max(1, n)))
    # Wasserman-Faust closeness handles disconnected graphs gracefully.
    closeness = np.zeros(n, dtype=np.float64)
    pos = farness > 0
    if n > 1:
        closeness[pos] = (reach[pos] / farness[pos]) * (reach[pos] / (n - 1))
    out = {"reach": reach, "farness": farness,
           "closeness": closeness, "harmonic": harmonic}
    if node_xy is not None:
        out["straightness"] = straight
    return out


def eigenvector(indptr, adj, n, max_iter=200, tol=1e-10):
    """Eigenvector centrality by power iteration on the binary adjacency.

    Influence of a junction given the influence of its neighbours
    (Bonacich). Normalized so the maximum is 1. Converges to the dominant
    connected component; isolated parts get near-zero scores.
    """
    if n == 0:
        return np.zeros(0, dtype=np.float64)
    x = np.full(n, 1.0 / n, dtype=np.float64)
    for _ in range(max_iter):
        # Power-iterate on A + I: same dominant eigenvector as A, but the
        # +I shift breaks the +/-lambda tie on bipartite graphs (trees,
        # grids) where plain iteration oscillates forever.
        nxt = x.copy()
        for u in range(n):
            s = x[u]
            if s != 0.0:
                # np.add.at: parallel edges must each contribute
                np.add.at(nxt, adj[indptr[u]:indptr[u + 1]], s)
        norm = float(np.sqrt((nxt * nxt).sum()))
        if norm <= 0.0:
            return np.zeros(n, dtype=np.float64)
        nxt /= norm
        if float(np.abs(nxt - x).max()) < tol:
            x = nxt
            break
        x = nxt
    peak = float(x.max())
    return x / peak if peak > 0 else x


def brandes_betweenness(indptr, adj, weights, n, adj_edge=None, num_edges=0,
                        w_prune=None, radius=None, sources=None,
                        cancel=None, progress=None, collect_depth=False):
    """Weighted betweenness (Brandes 2001) with options used across PlanX.

    ``w_prune``/``radius``: prune the search once the accumulated prune
    weight exceeds ``radius`` (e.g. angular cost minimized within a metric
    radius for space syntax choice).
    ``sources``: subset of source nodes (results scaled by n/len(sources)).
    ``collect_depth``: also return per-source-reachability stats needed by
    space syntax integration (node count + total cost depth per source),
    sharing the same Dijkstra pass.

    Returns (node_bc, edge_bc or None, depth_stats or None). For an
    undirected graph each unordered pair is counted twice (s->t and t->s);
    callers divide by 2 when reporting pair-based conventions.
    """
    node_bc = np.zeros(n, dtype=np.float64)
    edge_bc = np.zeros(num_edges, dtype=np.float64) if adj_edge is not None else None
    if collect_depth:
        depth_nc = np.zeros(n, dtype=np.float64)
        depth_td = np.zeros(n, dtype=np.float64)

    src_list = range(n) if sources is None else [int(s) for s in sources]
    total_sources = n if sources is None else len(src_list)

    dist = np.empty(n, dtype=np.float64)
    prune_d = np.empty(n, dtype=np.float64)
    sigma = np.empty(n, dtype=np.float64)
    delta = np.empty(n, dtype=np.float64)

    for done, s in enumerate(src_list):
        if cancel is not None and cancel():
            break
        if progress is not None and done % 64 == 0:
            progress(done / max(1, total_sources))
        dist.fill(INF)
        prune_d.fill(INF)
        sigma.fill(0.0)
        dist[s] = 0.0
        prune_d[s] = 0.0
        sigma[s] = 1.0
        preds = [[] for _ in range(n)]
        order = []
        heap = [(0.0, 0.0, s)]
        visited = np.zeros(n, dtype=bool)
        while heap:
            d, p, u = heapq.heappop(heap)
            if visited[u]:
                continue
            visited[u] = True
            order.append(u)
            for k in range(indptr[u], indptr[u + 1]):
                v = adj[k]
                if visited[v]:
                    continue
                if w_prune is not None and radius is not None:
                    np_ = p + w_prune[k]
                    if np_ > radius:
                        continue
                else:
                    np_ = p
                nd = d + weights[k]
                tol = _EPS * max(1.0, abs(nd))
                if nd < dist[v] - tol:
                    dist[v] = nd
                    prune_d[v] = np_
                    sigma[v] = sigma[u]
                    preds[v] = [(u, k)]
                    heapq.heappush(heap, (nd, np_, v))
                elif abs(nd - dist[v]) <= tol:
                    sigma[v] += sigma[u]
                    preds[v].append((u, k))
        if collect_depth:
            depth_nc[s] = len(order)                      # includes the source
            depth_td[s] = sum(dist[v] for v in order[1:])
        delta.fill(0.0)
        for v in reversed(order):
            coeff = (1.0 + delta[v]) / sigma[v] if sigma[v] > 0 else 0.0
            for (u, k) in preds[v]:
                c = sigma[u] * coeff
                delta[u] += c
                if edge_bc is not None:
                    edge_bc[adj_edge[k]] += c
            if v != s:
                node_bc[v] += delta[v]

    if sources is not None and total_sources > 0 and total_sources < n:
        scale = n / float(total_sources)
        node_bc *= scale
        if edge_bc is not None:
            edge_bc *= scale
    depth = {"node_count": depth_nc, "total_depth": depth_td} if collect_depth else None
    return node_bc, edge_bc, depth
