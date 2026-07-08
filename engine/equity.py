# -*- coding: utf-8 -*-
"""Distributional equity metrics for accessibility analysis.

Pure NumPy. Given a per-unit value ``x`` (an access score, a travel time,
a distance to the nearest facility...) and optional population weights
``w``, these functions measure how (un)equally that value is distributed
across the population - the spatial-equity / environmental-justice view
that complements the level-of-access tools.

The inequality indices (Gini, Theil) assume a non-negative quantity: the
caller passes a non-negative "good" (e.g. an access score) and negatives
are clipped to zero. Everything is weighted by the population ``w`` (each
unit counts for ``w_i`` people); ``w=None`` means one person per unit.

References: Gini (1912) mean-difference form; Theil (1967) T index with
the additive between/within-group decomposition (Shorrocks 1980); the
weighted Gini uses the O(n log n) sorted form, exact against the O(n^2)
mean-difference definition.
"""
from __future__ import annotations

import numpy as np


def _clean(x, w):
    """Coerce values/weights to 1-D float arrays; non-positive weights -> 0."""
    x = np.asarray(x, dtype=float).ravel()
    if w is None:
        w = np.ones_like(x)
    else:
        w = np.asarray(w, dtype=float).ravel()
        if w.shape != x.shape:
            raise ValueError("weights and values must have the same length")
    w = np.where(np.isfinite(w) & (w > 0), w, 0.0)
    return x, w


def weighted_mean(x, w=None):
    x, w = _clean(x, w)
    total = w.sum()
    return float((w * x).sum() / total) if total > 0 else 0.0


def weighted_std(x, w=None):
    x, w = _clean(x, w)
    total = w.sum()
    if total <= 0:
        return 0.0
    mu = (w * x).sum() / total
    var = (w * (x - mu) ** 2).sum() / total
    return float(np.sqrt(max(var, 0.0)))


def coefficient_of_variation(x, w=None):
    """Population-weighted CV = std / |mean| (0 = perfect equality)."""
    mu = weighted_mean(x, w)
    if mu == 0:
        return 0.0
    return float(weighted_std(x, w) / abs(mu))


def weighted_quantile(x, q, w=None):
    """Population-weighted quantile(s) ``q`` in [0, 1].

    Linear interpolation on the cumulative population share evaluated at
    the centre of each unit's mass; clamps outside the sampled range.
    """
    x, w = _clean(x, w)
    order = np.argsort(x, kind="mergesort")
    x, w = x[order], w[order]
    total = w.sum()
    scalar = np.ndim(q) == 0
    if total <= 0:
        return 0.0 if scalar else np.zeros(np.shape(q))
    cum = (np.cumsum(w) - 0.5 * w) / total
    out = np.interp(np.atleast_1d(np.asarray(q, dtype=float)), cum, x)
    return float(out[0]) if scalar else out


def percentile_ratio(x, w=None, hi=0.9, lo=0.1):
    """Weighted P(hi)/P(lo) ratio (e.g. P90/P10). 0.0 if P(lo) is 0."""
    phi = weighted_quantile(x, hi, w)
    plo = weighted_quantile(x, lo, w)
    return float(phi / plo) if plo > 0 else 0.0


def percentile_rank(x, w=None):
    """Per-unit weighted percentile rank in [0, 1] (mid-rank for ties).

    rank_i = (population strictly below x_i + half of the equal mass) / W,
    so the lowest values sit near 0 and the highest near 1.
    """
    x, w = _clean(x, w)
    total = w.sum()
    if total <= 0:
        return np.zeros_like(x)
    order = np.argsort(x, kind="mergesort")
    inv = np.empty_like(order)
    inv[order] = np.arange(len(order))
    xs, ws = x[order], w[order]
    cum_below = np.cumsum(ws) - ws  # weight strictly before in sorted order
    rank = np.empty_like(xs)
    i, n = 0, len(xs)
    while i < n:
        j = i
        while j < n and xs[j] == xs[i]:
            j += 1
        equal = ws[i:j].sum()
        rank[i:j] = (cum_below[i] + 0.5 * equal) / total
        i = j
    return rank[inv]


def gini(x, w=None):
    """Population-weighted Gini coefficient (0 = equality, ->1 = maximal
    inequality) via the mean-difference form, computed in O(n log n)."""
    x, w = _clean(x, w)
    x = np.clip(x, 0.0, None)
    order = np.argsort(x, kind="mergesort")
    x, w = x[order], w[order]
    total = w.sum()
    sw_x = (w * x).sum()
    if total <= 0 or sw_x <= 0:
        return 0.0
    w_below = np.cumsum(w) - w            # sum of weights strictly below i
    s_below = np.cumsum(w * x) - w * x    # sum of w*x strictly below i
    num = (w * (x * w_below - s_below)).sum()
    return float(num / (total * sw_x))


def theil_t(x, w=None):
    """Population-weighted Theil's T index (0 = equality). Zeros contribute
    0 (limit x*ln x -> 0); negatives are clipped to 0."""
    x, w = _clean(x, w)
    x = np.clip(x, 0.0, None)
    total = w.sum()
    if total <= 0:
        return 0.0
    mu = (w * x).sum() / total
    if mu <= 0:
        return 0.0
    r = x / mu
    term = np.where(r > 0, r * np.log(r), 0.0)
    return float((w * term).sum() / total)


def theil_decomposition(x, w, groups):
    """Additive decomposition of Theil's T: T = T_between + T_within.

    ``groups`` is an array of group labels (any hashable). The between
    term is sum_g s_g * ln(mu_g / mu) and the within term sum_g s_g * T_g,
    where s_g is each group's share of the total value. Returns
    ``(t_total, t_between, t_within, per_group)`` with ``per_group`` a dict
    label -> {pop, mean, theil, value_share}.
    """
    x, w = _clean(x, w)
    x = np.clip(x, 0.0, None)
    groups = np.asarray(groups).ravel()
    if groups.shape != x.shape:
        raise ValueError("groups and values must have the same length")
    total = w.sum()
    t_total = theil_t(x, w)
    mu = (w * x).sum() / total if total > 0 else 0.0
    if total <= 0 or mu <= 0:
        return t_total, 0.0, 0.0, {}
    t_between = t_within = 0.0
    per_group = {}
    for lab in sorted(set(groups.tolist()), key=str):
        m = groups == lab
        wg, xg = w[m], x[m]
        wsum = wg.sum()
        if wsum <= 0:
            continue
        mug = (wg * xg).sum() / wsum
        share = (wsum * mug) / (total * mu)   # group share of total value
        tg = theil_t(xg, wg)
        if mug > 0:
            t_between += share * float(np.log(mug / mu))
        t_within += share * tg
        per_group[lab] = {"pop": float(wsum), "mean": float(mug),
                          "theil": float(tg), "value_share": float(share)}
    return float(t_total), float(t_between), float(t_within), per_group


def atkinson_index(x, w=None, epsilon=1.0):
    """Population-weighted Atkinson inequality index (0 = equality, ->1).

    ``epsilon`` >= 0 is the inequality-aversion parameter: 0 gives no
    aversion (A = 0), larger values weight the lower tail more heavily. The
    index is ``1 - EDE / mean``, where the equally-distributed-equivalent
    level ``EDE`` is the power mean of order ``1 - epsilon`` of the values
    (the weighted geometric mean when ``epsilon == 1``). Values are treated
    as a non-negative good (negatives clipped to 0); if any unit has a zero
    value and ``epsilon >= 1`` the index is 1 (the geometric mean collapses).
    """
    x, w = _clean(x, w)
    x = np.clip(x, 0.0, None)
    eps = float(epsilon)
    if eps < 0:
        raise ValueError("epsilon must be >= 0")
    total = w.sum()
    if total <= 0:
        return 0.0
    mu = (w * x).sum() / total
    if mu <= 0:
        return 0.0
    has_zero = bool(np.any((x <= 0) & (w > 0)))
    if abs(eps - 1.0) < 1e-12:
        if has_zero:
            return 1.0
        ede = float(np.exp((w * np.log(x)).sum() / total))
    else:
        if eps > 1.0 and has_zero:
            return 1.0
        p = 1.0 - eps
        m = (w * np.power(x, p)).sum() / total
        ede = float(np.power(m, 1.0 / p))
    return float(min(1.0, max(0.0, 1.0 - ede / mu)))


def lorenz_points(x, w=None, rank=None):
    """Cumulative population/value shares of the Lorenz (or concentration) curve.

    Units are ordered ascending by their value (the Lorenz curve) or, when
    ``rank`` is given, by that ranking variable (a concentration curve of the
    value with respect to ``rank``). Returns ``(pop_share, value_share)``,
    each length ``n + 1`` and starting at the ``(0, 0)`` origin: ``pop_share``
    is the cumulative population share, ``value_share`` the cumulative share
    of the total value. Both end at 1. Values are clipped to non-negative.
    """
    x, w = _clean(x, w)
    x = np.clip(x, 0.0, None)
    key = x if rank is None else np.asarray(rank, dtype=float).ravel()
    if key.shape != x.shape:
        raise ValueError("rank and values must have the same length")
    order = np.argsort(key, kind="mergesort")
    xs, ws = x[order], w[order]
    n = len(xs)
    pop = np.zeros(n + 1)
    val = np.zeros(n + 1)
    total_w = ws.sum()
    total_v = (ws * xs).sum()
    if total_w > 0:
        pop[1:] = np.cumsum(ws) / total_w
    if total_v > 0:
        val[1:] = np.cumsum(ws * xs) / total_v
    return pop, val


def gini_from_lorenz(pop_share, value_share):
    """Gini (or concentration) index as twice the area between the curve and
    the line of equality, via the trapezoidal rule on the cumulative shares.

    Equals :func:`gini` when the shares come from a value-ordered
    :func:`lorenz_points`; with a ``rank``-ordered curve it is the
    concentration index (which may be negative if the value falls with rank).
    """
    p = np.asarray(pop_share, dtype=float)
    lz = np.asarray(value_share, dtype=float)
    return float(1.0 - np.sum((p[1:] - p[:-1]) * (lz[1:] + lz[:-1])))


def concentration_index(x, rank, w=None):
    """Concentration index of ``x`` when units are ordered by ``rank``.

    Like the Gini but the ordering is external: e.g. how concentrated an
    access score is across units ranked by deprivation. In [-1, 1]; positive
    means the value accrues to the high-rank end.
    """
    pop, val = lorenz_points(x, w, rank=rank)
    return gini_from_lorenz(pop, val)


def value_classes(x, w=None, n_classes=5, breaks=None):
    """Assign each unit to a value class (0 = lowest ... Q-1 = highest).

    By default the classes are population-weighted quantile bins (equal
    population per class): the inner edges are the weighted quantiles at
    ``k / n_classes``. Pass explicit ascending inner ``breaks`` instead to
    class by fixed values (``len(breaks) + 1`` classes). Returns
    ``(class_of, edges)`` where ``class_of`` is an int array and ``edges``
    the inner cut values actually used (a unit falls in class ``k`` when
    ``edges[k-1] < x <= edges[k]``, open-ended at both extremes).
    """
    x, w = _clean(x, w)
    if breaks is not None:
        edges = np.asarray(sorted(float(b) for b in breaks), dtype=float)
    else:
        q = int(n_classes)
        if q < 2:
            raise ValueError("n_classes must be >= 2")
        probs = np.arange(1, q) / q
        edges = np.asarray(weighted_quantile(x, probs, w), dtype=float)
    class_of = np.searchsorted(edges, x, side="left")
    return class_of.astype(np.int64), edges


def crosstab(x, g, w=None, n_classes=5, breaks=None):
    """Weighted cross-tabulation of a per-unit value by population group.

    ``x`` is the per-unit value (treated as-is, no clipping except inside
    the per-group Gini), ``g`` an integer group code ``0..G-1`` per unit and
    ``w`` the population weight. The value axis is cut into classes via
    :func:`value_classes` (weighted quantiles by default, or fixed
    ``breaks``). Returns a dict:

    - ``edges``            inner class edges used, ``class_of`` per-unit class
    - ``cells``            (G, Q) weighted population per group x class
    - ``rep_ratio``        (G, Q) representation ratio - the group's share of
      the class population divided by its share of the total population
      (1 = proportional, >1 over-represented; NaN when the class or the
      group is empty)
    - ``pop``, ``pop_share``, ``value_share`` (G,) per-group population,
      its share, and the group's share of the total value
    - ``mean``, ``p10``, ``median``, ``p90``, ``vmin``, ``vmax``, ``gini``
      (G,) weighted per-group statistics
    - ``dissimilarity``    (G,) Duncan & Duncan dissimilarity index of the
      group against the rest of the population over the value classes
      (0 = identical distribution, 1 = complete separation)
    """
    x, w = _clean(x, w)
    g = np.asarray(g, dtype=np.int64).ravel()
    if g.shape != x.shape:
        raise ValueError("groups and values must have the same length")
    if g.size and g.min() < 0:
        raise ValueError("group codes must be non-negative")
    n_groups = int(g.max()) + 1 if g.size else 0
    class_of, edges = value_classes(x, w, n_classes=n_classes, breaks=breaks)
    q = len(edges) + 1

    cells = np.zeros((n_groups, q))
    np.add.at(cells, (g, class_of), w)
    col_pop = cells.sum(axis=0)
    pop = cells.sum(axis=1)
    total = pop.sum()

    total_value = (w * x).sum()
    value_share = np.zeros(n_groups)
    mean = np.zeros(n_groups)
    p10 = np.zeros(n_groups)
    median = np.zeros(n_groups)
    p90 = np.zeros(n_groups)
    vmin = np.zeros(n_groups)
    vmax = np.zeros(n_groups)
    gini_g = np.zeros(n_groups)
    dissim = np.zeros(n_groups)
    for gi in range(n_groups):
        m = g == gi
        wg, xg = w[m], x[m]
        wsum = wg.sum()
        if wsum <= 0:
            continue
        mean[gi] = (wg * xg).sum() / wsum
        p10[gi], median[gi], p90[gi] = weighted_quantile(xg, [0.1, 0.5, 0.9], wg)
        pos = xg[wg > 0]
        vmin[gi] = pos.min() if pos.size else 0.0
        vmax[gi] = pos.max() if pos.size else 0.0
        gini_g[gi] = gini(xg, wg)
        if total_value > 0:
            value_share[gi] = (wg * xg).sum() / total_value
        rest_pop = total - wsum
        if rest_pop > 0:
            own = cells[gi] / wsum
            rest = (col_pop - cells[gi]) / rest_pop
            dissim[gi] = 0.5 * float(np.abs(own - rest).sum())

    with np.errstate(divide="ignore", invalid="ignore"):
        class_share = cells / col_pop[None, :]
        overall_share = pop / total if total > 0 else np.zeros(n_groups)
        rep_ratio = class_share / overall_share[:, None]
    rep_ratio[~np.isfinite(rep_ratio)] = np.nan

    return {
        "edges": edges,
        "class_of": class_of,
        "cells": cells,
        "rep_ratio": rep_ratio,
        "pop": pop,
        "pop_share": overall_share,
        "value_share": value_share,
        "mean": mean,
        "p10": p10,
        "median": median,
        "p90": p90,
        "vmin": vmin,
        "vmax": vmax,
        "gini": gini_g,
        "dissimilarity": dissim,
    }


def share_below(x, threshold, w=None, strict=True):
    """Population share with value below (``strict``) or at/below ``threshold``."""
    x, w = _clean(x, w)
    total = w.sum()
    if total <= 0:
        return 0.0
    mask = x < threshold if strict else x <= threshold
    return float(w[mask].sum() / total)


def share_above(x, threshold, w=None, strict=True):
    """Population share with value above (``strict``) or at/above ``threshold``."""
    x, w = _clean(x, w)
    total = w.sum()
    if total <= 0:
        return 0.0
    mask = x > threshold if strict else x >= threshold
    return float(w[mask].sum() / total)
