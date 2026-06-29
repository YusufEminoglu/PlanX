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
