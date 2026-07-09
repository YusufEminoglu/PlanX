# -*- coding: utf-8 -*-
"""Air quality screening kernels.

Pure NumPy. SCREENING quality, not compliance modelling.
"""
from __future__ import annotations

import numpy as np


def road_emission(aadt, ef_gkm):
    """Calculates road emission in g/km/day.

    aadt: daily vehicle volume (AADT)
    ef_gkm: emission factor in g/km (e.g. NOx proxy)
    """
    return np.asarray(aadt, dtype=float) * np.asarray(ef_gkm, dtype=float)


def sample_strength(emission, seg_len):
    """Converts line-source emission (g/km/day) into sample point strength,
    calibrated at 25 m reference.

    strength = emission * (25 * seg_len / pi)
    """
    emission = np.asarray(emission, dtype=float)
    seg_len = np.asarray(seg_len, dtype=float)
    return emission * (25.0 * np.clip(seg_len, 1e-6, None) / np.pi)


def concentration(src_xy, strength, rx, ry, wind_speed, alpha=1.0, d0=0.0, cutoff=None):
    """Calculates the concentration index at a receiver point (rx, ry).

    Index = sum( strength / (wind_speed * (d + d0)**alpha) )
    """
    src_xy = np.asarray(src_xy, dtype=float)
    strength = np.asarray(strength, dtype=float)
    d = np.hypot(src_xy[:, 0] - rx, src_xy[:, 1] - ry)
    keep = np.isfinite(strength)
    if cutoff is not None:
        keep &= d <= cutoff
    if not keep.any():
        return 0.0
    d = d[keep]
    contrib = strength[keep] / (float(wind_speed) * (d + float(d0)) ** float(alpha))
    return float(np.sum(contrib))


def canyon_factor(height_mean, width):
    """Calculates the canyon accumulation factor: 1 + min(2, H/W)."""
    h = np.asarray(height_mean, dtype=float)
    w = np.clip(np.asarray(width, dtype=float), 1e-6, None)
    return 1.0 + np.minimum(2.0, h / w)


def exposure_bands(levels, weights=None,
                   breaks=(10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0)):
    """Weighted population per pollution index band. Returns (labels, totals)."""
    levels = np.asarray(levels, dtype=float)
    if weights is None:
        weights = np.ones_like(levels)
    weights = np.asarray(weights, dtype=float)
    edges = [-np.inf] + [float(b) for b in breaks] + [np.inf]
    labels, totals = [], []
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        mask = (levels >= lo) & (levels < hi)
        if np.isneginf(lo):
            labels.append(f"< {hi:g}")
        elif np.isposinf(hi):
            labels.append(f">= {lo:g}")
        else:
            labels.append(f"{lo:g} - {hi:g}")
        totals.append(float(weights[mask].sum()))
    return labels, np.asarray(totals)
