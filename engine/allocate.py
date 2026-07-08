# -*- coding: utf-8 -*-
"""Land-use allocation: assign parcels to land uses to maximise an objective.

Pure NumPy. A capacitated assignment / generalized-assignment heuristic.
Given per-parcel-per-use suitability scores, parcel areas and a target area
to fill for each use, assign each parcel (whole) to at most one use so that
the area allocated to a use does not exceed its target and an objective is
maximised:

    F = w_suit * sum_p area_p * suit[p, use_p]
        + sum_{(p, q) adjacent} L_pq * C[use_p, use_q]

The first term is per-parcel **suitability**; the optional second term is a
**spatial interaction** over adjacent parcels (``L_pq`` = shared boundary
length): the diagonal of the compatibility matrix ``C`` rewards same-use
neighbours (**compactness**) and the off-diagonal rewards (+) or penalises
(-) specific use pairs being adjacent (**adjacency**). With no edges / a
zero ``C`` the spatial term vanishes and only suitability matters.

Method: greedy construction (best per-unit suitability first) + a local
search of single-parcel reassignments and capacity-respecting pairwise
swaps, scoring the full objective - fast and explainable, not a global
optimum (the problem is NP-hard). ``locked`` parcels are fixed to a use up
front and consume that use's target. Suitability is treated as a
non-negative good (negatives are clipped to zero).
"""
from __future__ import annotations

import numpy as np


def parse_targets(text):
    """``"residential=50000, green=30000"`` -> [("residential", 50000.0), ...].

    Separators: comma or semicolon; keys are lower-cased. Raises ValueError
    on malformed entries.
    """
    targets = []
    for token in str(text).replace(";", ",").split(","):
        token = token.strip()
        if not token:
            continue
        if "=" not in token:
            raise ValueError(f"Target entry needs name=area: '{token}'")
        key, _, value = token.partition("=")
        key = key.strip().lower()
        try:
            area = float(value.strip())
        except ValueError:
            raise ValueError(f"Not a number in '{token}'")
        if not key or area < 0:
            raise ValueError(f"Invalid target entry: '{token}'")
        targets.append((key, area))
    if not targets:
        raise ValueError("No targets given (expected e.g. 'residential=50000').")
    return targets


def _spatial_sum(p, u, assign, adj, compat):
    """Sum over p's neighbours of ``L * compat[u, use(neighbour)]``."""
    if compat is None or u < 0:
        return 0.0
    total = 0.0
    for q, length in adj[p]:
        uq = assign[q]
        if uq >= 0:
            total += length * compat[u, uq]
    return total


def _swap_spatial_delta(p, q, up, uq, assign, adj, compat):
    """Change in the spatial term when p (use up) and q (use uq) swap uses.

    For a symmetric ``compat`` the mutual p-q edge is unchanged, so it is
    excluded; every other neighbour switches interaction partner.
    """
    if compat is None:
        return 0.0
    delta = 0.0
    for r, length in adj[p]:
        if r == q:
            continue
        ur = assign[r]
        if ur >= 0:
            delta += length * (compat[uq, ur] - compat[up, ur])
    for r, length in adj[q]:
        if r == p:
            continue
        ur = assign[r]
        if ur >= 0:
            delta += length * (compat[up, ur] - compat[uq, ur])
    return delta


def _allocate_core(suit, area, targets, locked, w_suit, adj, compat,
                   max_iter, swap_limit):
    suit = np.clip(np.asarray(suit, dtype=float), 0.0, None)
    area = np.asarray(area, dtype=float)
    targets = np.asarray(targets, dtype=float)
    if suit.ndim != 2:
        raise ValueError("suit must be 2-D (parcels x uses).")
    n_parc, n_use = suit.shape
    if area.shape[0] != n_parc:
        raise ValueError("len(area) must match the parcel rows of suit.")
    if targets.shape[0] != n_use:
        raise ValueError("len(targets) must match the use columns of suit.")
    if adj is None:
        adj = [()] * n_parc
    if compat is not None:
        compat = np.asarray(compat, dtype=float)

    assign = np.full(n_parc, -1, dtype=np.int64)
    remaining = targets.astype(float).copy()
    locked_mask = np.zeros(n_parc, dtype=bool)
    if locked is not None:
        locked = np.asarray(locked, dtype=np.int64)
        for p in range(n_parc):
            u = int(locked[p])
            if 0 <= u < n_use:
                assign[p] = u
                remaining[u] -= area[p]
                locked_mask[p] = True

    free = np.where(~locked_mask)[0]

    # ---- greedy construction (separable suitability term), best first ----
    if len(free):
        pairs_p = np.repeat(free, n_use)
        pairs_u = np.tile(np.arange(n_use), len(free))
        pairs_s = suit[pairs_p, pairs_u]
        for k in np.lexsort((pairs_u, pairs_p, -pairs_s)):
            p, u = int(pairs_p[k]), int(pairs_u[k])
            if assign[p] != -1:
                continue
            if remaining[u] + 1e-9 >= area[p]:
                assign[p] = u
                remaining[u] -= area[p]

    # ---- local search on the FULL objective ----
    swaps = reassigned = 0
    do_swaps = len(free) <= int(swap_limit)
    for _ in range(int(max_iter)):
        improved = False
        for p in free:
            p = int(p)
            cur = int(assign[p])
            cur_suit = suit[p, cur] if cur >= 0 else 0.0
            cur_spatial = _spatial_sum(p, cur, assign, adj, compat)
            best_u, best_gain = cur, 1e-12
            for u in range(n_use):
                if u == cur:
                    continue
                room = remaining[u] + (area[p] if cur == u else 0.0)
                if room + 1e-9 < area[p]:
                    continue
                gain = (w_suit * area[p] * (suit[p, u] - cur_suit)
                        + _spatial_sum(p, u, assign, adj, compat) - cur_spatial)
                if gain > best_gain:
                    best_gain, best_u = gain, u
            if best_u != cur:
                if cur >= 0:
                    remaining[cur] += area[p]
                remaining[best_u] -= area[p]
                assign[p] = best_u
                reassigned += 1
                improved = True
        if do_swaps:
            placed = [int(p) for p in free if assign[p] >= 0]
            for a_i in range(len(placed)):
                p = placed[a_i]
                up = int(assign[p])
                for b_i in range(a_i + 1, len(placed)):
                    q = placed[b_i]
                    uq = int(assign[q])
                    if up == uq:
                        continue
                    if (remaining[uq] + area[q] + 1e-9 < area[p]
                            or remaining[up] + area[p] + 1e-9 < area[q]):
                        continue
                    gain = w_suit * (area[p] * (suit[p, uq] - suit[p, up])
                                     + area[q] * (suit[q, up] - suit[q, uq]))
                    gain += _swap_spatial_delta(p, q, up, uq, assign, adj, compat)
                    if gain > 1e-12:
                        remaining[up] += area[p] - area[q]
                        remaining[uq] += area[q] - area[p]
                        assign[p], assign[q] = uq, up
                        up = uq
                        swaps += 1
                        improved = True
        if not improved:
            break

    # ---- scores ----
    suit_score = 0.0
    for p in range(n_parc):
        u = int(assign[p])
        if u >= 0:
            suit_score += area[p] * suit[p, u]
    spatial_score = 0.0
    if compat is not None:
        for p in range(n_parc):
            up = int(assign[p])
            if up < 0:
                continue
            for q, length in adj[p]:
                if q > p and assign[q] >= 0:
                    spatial_score += length * compat[up, assign[q]]

    allocated = np.zeros(n_use)
    counts = np.zeros(n_use, dtype=np.int64)
    for p in range(n_parc):
        u = int(assign[p])
        if u >= 0:
            allocated[u] += area[p]
            counts[u] += 1
    return {
        "assign": assign,
        "objective": float(w_suit * suit_score + spatial_score),
        "suit_score": float(suit_score),
        "spatial_score": float(spatial_score),
        "allocated": allocated,
        "n_parcels": counts,
        "swaps": swaps,
        "reassigned": reassigned,
    }


def allocate_land_use(suit, area, targets, locked=None, max_iter=50,
                      swap_limit=1200):
    """Assign parcels to uses to maximise area-weighted suitability only.

    The single-objective case (no spatial term). See module docstring and
    :func:`allocate_multi`. Returns dict: ``assign`` (use index per parcel,
    ``-1`` = unassigned), ``objective``/``suit_score`` (area-weighted
    suitability), ``allocated`` and ``n_parcels`` per use, ``swaps`` and
    ``reassigned`` counts.
    """
    return _allocate_core(suit, area, targets, locked, 1.0, None, None,
                          max_iter, swap_limit)


def allocate_multi(suit, area, targets, edges, compat, locked=None,
                   w_suit=1.0, max_iter=50, swap_limit=1200):
    """Multi-objective allocation: suitability + a spatial interaction term.

    Adds to the area-weighted suitability the term
    ``sum over adjacent (p, q) of L_pq * compat[use_p, use_q]``. ``edges``
    is an iterable of ``(p, q, shared_boundary_length)`` (each undirected
    pair once) and ``compat`` is a symmetric (U, U) matrix - its diagonal
    rewards same-use neighbours (compactness), off-diagonal entries reward
    (+) or penalise (-) specific use pairs being adjacent. ``w_suit``
    weights suitability against the spatial term. With no edges / a zero
    ``compat`` this equals :func:`allocate_land_use`. The returned dict adds
    ``spatial_score`` (the spatial term) to the keys above.
    """
    suit = np.asarray(suit, dtype=float)
    n_parc, n_use = suit.shape
    adj = [[] for _ in range(n_parc)]
    for i, j, length in edges:
        i, j, length = int(i), int(j), float(length)
        adj[i].append((j, length))
        adj[j].append((i, length))
    if compat is None:
        compat = np.zeros((n_use, n_use))
    return _allocate_core(suit, area, targets, locked, float(w_suit), adj,
                          compat, max_iter, swap_limit)


# --------------------------------------------------------------------------- #
# Pareto front: suitability vs compactness trade-off over a weight sweep
# --------------------------------------------------------------------------- #
def _same_use_boundary(assign, edges):
    """Total shared-boundary length between adjacent parcels of the SAME use.

    This is the **compactness** metric, computed directly from an assignment
    and so independent of any optimisation weight.
    """
    total = 0.0
    for i, j, length in edges:
        ui = int(assign[i])
        if ui >= 0 and ui == int(assign[j]):
            total += float(length)
    return total


def pareto_mask(obj1, obj2, tol=1e-9):
    """Boolean mask of the non-dominated points when MAXIMISING both objectives.

    Point ``i`` is dominated when some ``j`` is at least as good on both
    objectives and strictly better on one. Identical points are both kept.
    """
    a = np.asarray(obj1, dtype=float)
    b = np.asarray(obj2, dtype=float)
    n = a.shape[0]
    nd = np.ones(n, dtype=bool)
    for i in range(n):
        for j in range(n):
            if j == i:
                continue
            if (a[j] >= a[i] - tol and b[j] >= b[i] - tol
                    and (a[j] > a[i] + tol or b[j] > b[i] + tol)):
                nd[i] = False
                break
    return nd


def _knee_index(obj1, obj2, front_mask):
    """Index (into the full arrays) of the knee of the Pareto front.

    The knee is the front point furthest from the chord joining the two
    extreme front points, after scaling each objective to [0, 1]. Returns
    ``-1`` when the front has fewer than three distinct points.
    """
    idx = np.where(front_mask)[0]
    if idx.shape[0] < 3:
        return -1
    a = np.asarray(obj1, dtype=float)[idx]
    b = np.asarray(obj2, dtype=float)[idx]

    def _norm(x):
        lo, hi = float(x.min()), float(x.max())
        return (x - lo) / (hi - lo) if hi > lo else np.zeros_like(x)

    an, bn = _norm(a), _norm(b)
    order = np.argsort(an)
    an, bn, idx = an[order], bn[order], idx[order]
    dx, dy = an[-1] - an[0], bn[-1] - bn[0]
    denom = float(np.hypot(dx, dy))
    if denom < 1e-12:
        return -1
    dist = np.abs(dy * (an - an[0]) - dx * (bn - bn[0])) / denom
    return int(idx[int(np.argmax(dist))])


def pareto_front(suit, area, targets, edges, weights, locked=None, w_suit=1.0,
                 max_iter=50, swap_limit=1200):
    """Trace the suitability vs compactness trade-off across compactness weights.

    For each ``w`` in ``weights`` the allocation is solved with a pure
    compactness reward matrix ``compat = w * I`` (diagonal ``w``, no adjacency
    off-diagonal), reusing :func:`allocate_multi`. Two objectives, both to be
    MAXIMISED, are recorded per run: ``suit`` (area-weighted suitability) and
    ``compact`` (shared boundary between adjacent same-use parcels). The
    non-dominated subset is the Pareto front; the ``knee`` is its
    best-balanced point.

    Returns a dict with arrays aligned to ``weights``: ``weights``, ``suit``,
    ``compact``, ``suit_norm``/``compact_norm`` (0-1 across all runs),
    ``swaps``, ``reassigned``, ``on_front`` (bool), ``knee`` (index or -1) and
    ``assign`` (list of the per-parcel assignment array of each run).
    """
    suit_arr = np.asarray(suit, dtype=float)
    n_use = suit_arr.shape[1]
    edges = [(int(i), int(j), float(length)) for i, j, length in edges]
    weights = [float(w) for w in weights]
    suit_vals, comp_vals, swaps, reass, assigns = [], [], [], [], []
    for w in weights:
        compat = np.eye(n_use) * w
        res = allocate_multi(suit_arr, area, targets, edges, compat,
                             locked=locked, w_suit=w_suit, max_iter=max_iter,
                             swap_limit=swap_limit)
        assigns.append(res["assign"])
        suit_vals.append(res["suit_score"])
        comp_vals.append(_same_use_boundary(res["assign"], edges))
        swaps.append(res["swaps"])
        reass.append(res["reassigned"])
    suit_vals = np.asarray(suit_vals, dtype=float)
    comp_vals = np.asarray(comp_vals, dtype=float)
    front = pareto_mask(suit_vals, comp_vals)

    def _norm(x):
        lo, hi = float(x.min()), float(x.max())
        return (x - lo) / (hi - lo) if hi > lo else np.zeros_like(x)

    return {
        "weights": np.asarray(weights, dtype=float),
        "suit": suit_vals,
        "compact": comp_vals,
        "suit_norm": _norm(suit_vals),
        "compact_norm": _norm(comp_vals),
        "swaps": np.asarray(swaps, dtype=np.int64),
        "reassigned": np.asarray(reass, dtype=np.int64),
        "on_front": front,
        "knee": _knee_index(suit_vals, comp_vals, front),
        "assign": assigns,
    }


def check_connectivity(use_id, temp_assign, adj):
    """Check if the parcels assigned to use_id form a single connected component."""
    nodes = np.where(temp_assign == use_id)[0]
    if len(nodes) <= 1:
        return True
    start = nodes[0]
    visited = {start}
    queue = [start]
    nodes_set = set(nodes)
    head = 0
    while head < len(queue):
        curr = queue[head]
        head += 1
        for neighbor, _ in adj[curr]:
            if neighbor in nodes_set and neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
    return len(visited) == len(nodes)


def allocate_contiguous(suit, area, targets, edges, compat=None, locked=None,
                        w_suit=1.0, max_iter=50, swap_limit=1200, log_warning_fn=None):
    """Land-use allocation with hard contiguity constraints.

    Each use forms a single connected component over the parcel adjacency graph.
    Uses region-growing construction, then boundary-swap local search.
    """
    suit = np.clip(np.asarray(suit, dtype=float), 0.0, None)
    area = np.asarray(area, dtype=float)
    targets = np.asarray(targets, dtype=float)
    if suit.ndim != 2:
        raise ValueError("suit must be 2-D (parcels x uses).")
    n_parc, n_use = suit.shape
    if area.shape[0] != n_parc:
        raise ValueError("len(area) must match the parcel rows of suit.")
    if targets.shape[0] != n_use:
        raise ValueError("len(targets) must match the use columns of suit.")

    adj = [[] for _ in range(n_parc)]
    for i, j, length in edges:
        i, j, length = int(i), int(j), float(length)
        adj[i].append((j, length))
        adj[j].append((i, length))

    if compat is None:
        compat = np.eye(n_use)
    else:
        compat = np.asarray(compat, dtype=float)

    assign = np.full(n_parc, -1, dtype=np.int64)
    remaining = targets.astype(float).copy()
    locked_mask = np.zeros(n_parc, dtype=bool)
    if locked is not None:
        locked = np.asarray(locked, dtype=np.int64)
        for p in range(n_parc):
            u = int(locked[p])
            if 0 <= u < n_use:
                assign[p] = u
                remaining[u] -= area[p]
                locked_mask[p] = True

    # 1. Seeding phase: seed each use at its highest-suitability parcel (or user lock)
    for u in range(n_use):
        has_locked = False
        if locked is not None:
            if np.any((locked == u) & locked_mask):
                has_locked = True

        if not has_locked:
            free_indices = np.where(assign == -1)[0]
            if len(free_indices) > 0:
                best_p = free_indices[np.argmax(suit[free_indices, u])]
                assign[best_p] = u
                remaining[u] -= area[best_p]

    # 2. Growth phase: repeatedly add the best-scoring frontier parcel for each active use
    while True:
        added = False
        for u in range(n_use):
            if remaining[u] <= 1e-9:
                continue

            best_p = -1
            best_score = -float("inf")

            unassigned = np.where(assign == -1)[0]
            for p in unassigned:
                p = int(p)
                is_adj = False
                comp_gain = 0.0
                for q, length in adj[p]:
                    if assign[q] == u:
                        is_adj = True
                        comp_gain += length

                if is_adj:
                    score = w_suit * area[p] * suit[p, u] + comp_gain
                    if score > best_score:
                        best_score = score
                        best_p = p

            if best_p != -1:
                assign[best_p] = u
                remaining[u] -= area[best_p]
                added = True

        if not added:
            break

    # Check if targets are infeasible under contiguity
    infeasible = False
    for u in range(n_use):
        if remaining[u] > 1e-9:
            has_frontier = False
            for p in np.where(assign == -1)[0]:
                if any(assign[q] == u for q, _ in adj[p]):
                    has_frontier = True
                    break
            if not has_frontier:
                infeasible = True
                break

    if infeasible:
        msg = "Targets are infeasible under contiguity constraints. Falling back to soft behavior."
        if log_warning_fn:
            log_warning_fn(msg)
        else:
            import warnings
            warnings.warn(msg, UserWarning)
        return allocate_multi(suit, area, targets, edges, compat, locked=locked,
                              w_suit=w_suit, max_iter=max_iter, swap_limit=swap_limit)

    # 3. Local search: connectivity-preserving boundary swaps and reassignments
    swaps = reassigned = 0
    free = np.where(~locked_mask)[0]
    do_swaps = len(free) <= int(swap_limit)

    for _ in range(int(max_iter)):
        improved = False
        for p in free:
            p = int(p)
            cur = int(assign[p])
            cur_suit = suit[p, cur] if cur >= 0 else 0.0
            cur_spatial = _spatial_sum(p, cur, assign, adj, compat)
            best_u, best_gain = cur, 1e-12
            for u in range(n_use):
                if u == cur:
                    continue
                room = remaining[u] + (area[p] if cur == u else 0.0)
                if room + 1e-9 < area[p]:
                    continue

                temp_assign = assign.copy()
                temp_assign[p] = u
                if cur >= 0 and not check_connectivity(cur, temp_assign, adj):
                    continue
                if u >= 0 and not check_connectivity(u, temp_assign, adj):
                    continue

                gain = (w_suit * area[p] * (suit[p, u] - cur_suit)
                        + _spatial_sum(p, u, assign, adj, compat) - cur_spatial)
                if gain > best_gain:
                    best_gain, best_u = gain, u
            if best_u != cur:
                if cur >= 0:
                    remaining[cur] += area[p]
                remaining[best_u] -= area[p]
                assign[p] = best_u
                reassigned += 1
                improved = True

        if do_swaps:
            placed = [int(p) for p in free if assign[p] >= 0]
            for a_i in range(len(placed)):
                p = placed[a_i]
                up = int(assign[p])
                for b_i in range(a_i + 1, len(placed)):
                    q = placed[b_i]
                    uq = int(assign[q])
                    if up == uq:
                        continue
                    if (remaining[uq] + area[q] + 1e-9 < area[p]
                            or remaining[up] + area[p] + 1e-9 < area[q]):
                        continue

                    temp_assign = assign.copy()
                    temp_assign[p] = uq
                    temp_assign[q] = up
                    if not check_connectivity(up, temp_assign, adj):
                        continue
                    if not check_connectivity(uq, temp_assign, adj):
                        continue

                    gain = w_suit * (area[p] * (suit[p, uq] - suit[p, up])
                                     + area[q] * (suit[q, up] - suit[q, uq]))
                    gain += _swap_spatial_delta(p, q, up, uq, assign, adj, compat)
                    if gain > 1e-12:
                        remaining[up] += area[p] - area[q]
                        remaining[uq] += area[q] - area[p]
                        assign[p], assign[q] = uq, up
                        up = uq
                        swaps += 1
                        improved = True
        if not improved:
            break

    suit_score = 0.0
    for p in range(n_parc):
        u = int(assign[p])
        if u >= 0:
            suit_score += area[p] * suit[p, u]
    spatial_score = 0.0
    if compat is not None:
        for p in range(n_parc):
            up = int(assign[p])
            if up < 0:
                continue
            for q, length in adj[p]:
                if q > p and assign[q] >= 0:
                    spatial_score += length * compat[up, assign[q]]

    allocated = np.zeros(n_use)
    counts = np.zeros(n_use, dtype=np.int64)
    for p in range(n_parc):
        u = int(assign[p])
        if u >= 0:
            allocated[u] += area[p]
            counts[u] += 1

    return {
        "assign": assign,
        "objective": float(w_suit * suit_score + spatial_score),
        "suit_score": float(suit_score),
        "spatial_score": float(spatial_score),
        "allocated": allocated,
        "n_parcels": counts,
        "swaps": swaps,
        "reassigned": reassigned,
    }
