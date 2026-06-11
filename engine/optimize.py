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
