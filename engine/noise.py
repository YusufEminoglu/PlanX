# -*- coding: utf-8 -*-
"""Road traffic noise screening kernels.

Pure NumPy. SCREENING quality, not compliance modelling: the emission is
the classic RLS-90-style mean level and the propagation is free-field
geometric spreading with a single fixed insertion loss where a building
blocks the line of sight. No ground effect, no air absorption, no
meteorology, no reflections - the numbers rank exposure and locate
hotspots; a licensed engine is needed for legal noise mapping.

* :func:`emission_rls` - mean emission level at the 25 m reference of an
  RLS-90-style road: ``37.3 + 10 lg(M (1 + 0.082 p))`` with ``M`` the
  hourly volume and ``p`` the heavy share in percent.
* :func:`sample_level` - converts that line-source level into the power
  of one point sample of ``seg_len`` metres of road, calibrated so that
  summing samples along an infinite straight road reproduces the line
  level: ``L_s = L_m25 + 10 lg(25 * seg_len / pi)``.
* :func:`receiver_levels` - energetic sum over the samples with
  ``20 lg r`` point spreading and the screening loss on blocked paths.
"""
from __future__ import annotations

import numpy as np


def emission_rls(m_hourly, heavy_share_pct):
    """RLS-90-style mean level at 25 m for an hourly volume ``M`` (veh/h)
    and heavy-vehicle share ``p`` (percent). Zero traffic -> -inf."""
    m = np.asarray(m_hourly, dtype=float)
    p = np.clip(np.asarray(heavy_share_pct, dtype=float), 0.0, 100.0)
    loud = m * (1.0 + 0.082 * p)
    with np.errstate(divide="ignore"):
        return np.where(loud > 0, 37.3 + 10.0 * np.log10(loud), -np.inf)


def sample_level(lm25, seg_len):
    """Source term of one point sample representing ``seg_len`` m of road."""
    seg_len = np.asarray(seg_len, dtype=float)
    return np.asarray(lm25, dtype=float) + 10.0 * np.log10(
        25.0 * np.clip(seg_len, 1e-6, None) / np.pi)


def receiver_level(src_xy, src_level, rx, ry, blocked=None, screen_db=10.0,
                   min_dist=1.0, cutoff=None):
    """Energetic sum of all samples at one receiver.

    ``blocked`` is an optional boolean array (line of sight to that sample
    interrupted -> subtract ``screen_db``). ``cutoff`` drops samples
    farther than it. Returns dB (or -inf with no audible source).
    """
    src_xy = np.asarray(src_xy, dtype=float)
    lvl = np.asarray(src_level, dtype=float)
    d = np.hypot(src_xy[:, 0] - rx, src_xy[:, 1] - ry)
    keep = np.isfinite(lvl)
    if cutoff is not None:
        keep &= d <= cutoff
    if not keep.any():
        return -np.inf
    d = np.maximum(d[keep], min_dist)
    contrib = lvl[keep] - 20.0 * np.log10(d)
    if blocked is not None:
        contrib = contrib - np.where(np.asarray(blocked)[keep],
                                     float(screen_db), 0.0)
    return float(10.0 * np.log10(np.sum(10.0 ** (contrib / 10.0))))


def exposure_bands(levels, weights=None,
                   breaks=(45.0, 50.0, 55.0, 60.0, 65.0, 70.0, 75.0)):
    """Weighted population per noise band. Returns (labels, totals)."""
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
            labels.append(f"< {hi:g} dB")
        elif np.isposinf(hi):
            labels.append(f">= {lo:g} dB")
        else:
            labels.append(f"{lo:g} - {hi:g} dB")
        totals.append(float(weights[mask].sum()))
    return labels, np.asarray(totals)
