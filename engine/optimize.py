# -*- coding: utf-8 -*-
"""Facility-location optimization: maximal coverage and p-median.

Pure NumPy. Inputs are plain distance matrices ``D`` of shape
(candidates, demand points) - typically network distances - and demand
weights ``w``. Methods follow the classic operations-research heuristics:

- greedy maximal coverage (Church & ReVelle 1974): each step picks the
  candidate adding the most uncovered weighted demand within the radius;
- p-median (ReVelle & Swain 1970) via greedy construction + Teitz & Bart
  (1968) vertex substitution, minimizing demand-weighted travel cost.

``fixed`` indices are existing facilities: they are part of the solution
from the start and do not count against ``p``.
"""
from __future__ import annotations

import numpy as np

INF = float("inf")


def coverage_weights(D, w, radius):
    """Standalone weighted demand within ``radius`` of each candidate.

    The 'site screening' score: how much demand each site could serve on
    its own. Returns an array of length n_candidates.
    """
    D = np.asarray(D, dtype=float)
    w = np.asarray(w, dtype=float)
    return (D <= float(radius)).astype(float) @ w


def greedy_max_coverage(D, w, p, radius, fixed=()):
    """Pick up to ``p`` candidates maximizing covered weighted demand.

    Returns dict with ``selected`` (in pick order), ``gains`` (marginal
    covered weight per pick), ``covered`` (bool per demand point),
    ``covered_weight`` and ``total_weight``. Stops early when no candidate
    adds coverage.
    """
    D = np.asarray(D, dtype=float)
    w = np.asarray(w, dtype=float)
    if D.ndim != 2 or D.shape[1] != len(w):
        raise ValueError("D must be (candidates, demand) matching len(w).")
    if D.shape[0] == 0:
        raise ValueError("No candidate sites.")
    cover = D <= float(radius)
    covered = np.zeros(D.shape[1], dtype=bool)
    taken = {int(f) for f in fixed}
    for f in taken:
        covered |= cover[f]
    selected, gains = [], []
    for _ in range(int(p)):
        gain = (cover & ~covered).astype(float) @ w
        if taken:
            gain[list(taken)] = -1.0
        best = int(np.argmax(gain))
        if gain[best] <= 0.0:
            break
        selected.append(best)
        gains.append(float(gain[best]))
        covered |= cover[best]
        taken.add(best)
    return {
        "selected": selected,
        "gains": gains,
        "covered": covered,
        "covered_weight": float(w[covered].sum()),
        "total_weight": float(w.sum()),
    }


def _objective(Dp, w, sel):
    return float((Dp[list(sel)].min(axis=0) * w).sum())


def p_median(D, w, p, fixed=(), penalty=None, max_iter=100):
    """Greedy + Teitz-Bart vertex-substitution p-median heuristic.

    Unreachable pairs (inf in ``D``) cost ``penalty`` (default: 1.5x the
    largest finite distance). Returns dict with ``selected`` (free picks,
    excluding fixed), ``objective`` (weighted total cost over the full
    solution incl. fixed) and ``swaps`` (improving substitutions applied).
    """
    D = np.asarray(D, dtype=float)
    w = np.asarray(w, dtype=float)
    if D.ndim != 2 or D.shape[1] != len(w):
        raise ValueError("D must be (candidates, demand) matching len(w).")
    finite = D[np.isfinite(D)]
    if penalty is None:
        peak = float(finite.max()) if finite.size else 0.0
        penalty = peak * 1.5 if peak > 0 else 1.0
    Dp = np.where(np.isfinite(D), D, float(penalty))
    fixed = [int(f) for f in fixed]
    free = [i for i in range(D.shape[0]) if i not in set(fixed)]
    p = min(int(p), len(free))
    if p <= 0 and not fixed:
        raise ValueError("p must be >= 1 when there are no fixed facilities.")

    selected = []
    for _ in range(p):  # greedy construction
        best, best_obj = -1, INF
        for c in free:
            if c in selected:
                continue
            obj = _objective(Dp, w, fixed + selected + [c])
            if obj < best_obj:
                best_obj, best = obj, c
        selected.append(best)

    swaps = 0
    improved = True
    it = 0
    while improved and it < int(max_iter):  # vertex substitution
        improved = False
        it += 1
        cur = _objective(Dp, w, fixed + selected)
        for si in range(len(selected)):
            best_c, best_obj = None, cur
            for c in free:
                if c in selected:
                    continue
                trial = selected[:si] + [c] + selected[si + 1:]
                obj = _objective(Dp, w, fixed + trial)
                if obj < best_obj - 1e-12:
                    best_obj, best_c = obj, c
            if best_c is not None:
                selected[si] = best_c
                cur = best_obj
                improved = True
                swaps += 1
    return {
        "selected": selected,
        "objective": _objective(Dp, w, fixed + selected) if (fixed or selected) else 0.0,
        "swaps": swaps,
        "penalty": float(penalty),
    }


def assign_to_nearest(D, solution):
    """Assign every demand point to its nearest facility of ``solution``.

    Returns (assign, cost): position in ``solution`` (-1 if unreachable)
    and the corresponding distance (-1.0 if unreachable).
    """
    D = np.asarray(D, dtype=float)
    sol = [int(s) for s in solution]
    if not sol:
        n = D.shape[1]
        return np.full(n, -1, dtype=np.int64), np.full(n, -1.0)
    sub = D[sol]
    assign = np.argmin(np.where(np.isfinite(sub), sub, INF), axis=0).astype(np.int64)
    cols = np.arange(sub.shape[1])
    cost = sub[assign, cols]
    bad = ~np.isfinite(cost)
    assign[bad] = -1
    cost = np.where(bad, -1.0, cost)
    return assign, cost


def capacitated_assign(D, w, cap, max_cost=None):
    """Greedy nearest-with-capacity allocation (whole demand points).

    Parameters
    ----------
    D : (F, N) array
        Cost from each of ``F`` facilities to each of ``N`` demand points
        (``inf`` where unreachable).
    w : (N,) array
        Demand (population) per point; assigned in full to one facility.
    cap : (F,) array
        Facility capacities, in the same units as ``w``.
    max_cost : float or None
        Catchment limit; pairs costing more are not eligible.

    Each demand point is placed in full at the *nearest* facility that
    still has room for its whole population; if that facility is already
    full it spills to the next-nearest one with room. A point that fits
    nowhere within reach is left uncovered. The cheapest eligible pairs
    are filled first - a fast, explainable greedy heuristic, not a global
    optimum (it does not split a point or solve min-cost flow). Whole-point
    assignment can strand capacity smaller than a single point's demand.

    Returns dict:
      ``assign``    (N,) facility index per point, ``-1`` = uncovered
      ``cost``      (N,) cost to the assigned facility, ``-1.0`` = uncovered
      ``spilled``   (N,) bool: assigned to a farther facility than the
                    nearest reachable one (its nearest was full)
      ``nearest``   (N,) nearest reachable facility (ignoring capacity), -1
      ``load``      (F,) assigned population per facility
      ``remaining`` (F,) leftover capacity per facility
    """
    D = np.asarray(D, dtype=float)
    w = np.asarray(w, dtype=float)
    cap = np.asarray(cap, dtype=float)
    if D.ndim != 2:
        raise ValueError("D must be 2-D (facilities x demand).")
    n_fac, n_dem = D.shape
    if w.shape[0] != n_dem:
        raise ValueError("len(w) must match the demand columns of D.")
    if cap.shape[0] != n_fac:
        raise ValueError("len(cap) must match the facility rows of D.")

    eligible = np.isfinite(D)
    if max_cost is not None:
        eligible &= D <= float(max_cost)

    # nearest reachable facility per demand point (ignores capacity)
    masked = np.where(eligible, D, INF)
    nearest = np.argmin(masked, axis=0).astype(np.int64)
    nearest[~np.isfinite(masked.min(axis=0))] = -1

    assign = np.full(n_dem, -1, dtype=np.int64)
    cost = np.full(n_dem, -1.0)
    remaining = cap.astype(float).copy()

    fac_idx, dem_idx = np.nonzero(eligible)
    costs = D[fac_idx, dem_idx]
    # cheapest pairs first; deterministic tie-break by demand then facility
    for k in np.lexsort((fac_idx, dem_idx, costs)):
        i = int(dem_idx[k])
        if assign[i] != -1:
            continue
        f = int(fac_idx[k])
        if remaining[f] + 1e-9 >= w[i]:
            assign[i] = f
            cost[i] = float(costs[k])
            remaining[f] -= w[i]

    spilled = (assign != -1) & (assign != nearest)
    load = cap.astype(float) - remaining
    return {
        "assign": assign,
        "cost": cost,
        "spilled": spilled,
        "nearest": nearest,
        "load": load,
        "remaining": remaining,
    }
