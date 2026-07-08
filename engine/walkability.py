# -*- coding: utf-8 -*-
"""Street-segment walkability scoring.

Pure NumPy. The QGIS wrapper gathers the raw ingredients per street
segment (intersection density around it, land-use mix in a buffer,
destination count, typical street length, slope); this module normalises
each ingredient to a 0-100 sub-score with documented breakpoints and
combines them into one weighted walk score.

The sub-scores follow the walkability-index literature (Frank et al. 2010
"The development of a walkability index"; Ewing & Cervero 2010 D-variables):
intersection density and land-use mix entropy are the classic ingredients,
destination density stands in for the retail floor-area ratio, and street
length / slope are the micro-scale friction terms. Breakpoints are
parameters, not constants of nature - the defaults mark a comfortably
walkable European urban fabric.
"""
from __future__ import annotations

import numpy as np

#: default component weights (renormalised over the components present)
DEFAULT_WEIGHTS = {
    "intersections": 0.30,
    "mix": 0.25,
    "destinations": 0.25,
    "blocklength": 0.10,
    "slope": 0.10,
}

#: default normalisation breakpoints
DEFAULT_BREAKPOINTS = {
    "intersections_full": 120.0,  # junctions per km2 scoring 100
    "destinations_full": 25.0,    # POIs within the radius scoring 100
    "block_best": 80.0,           # mean street length (m) scoring 100
    "block_worst": 400.0,         # mean street length (m) scoring 0
    "slope_worst": 10.0,          # slope percent scoring 0
}


def linear_score(values, zero, full):
    """Linear 0-100 score: ``zero`` maps to 0, ``full`` to 100 (clamped).

    Works in either direction: pass ``zero > full`` for
    smaller-is-better quantities.
    """
    values = np.asarray(values, dtype=float)
    span = float(full) - float(zero)
    if span == 0:
        return np.full_like(values, 100.0)
    return np.clip((values - float(zero)) / span, 0.0, 1.0) * 100.0


def shannon_mix(areas):
    """Normalised Shannon entropy of a composition (0 = one use, 1 = even).

    ``areas`` are non-negative amounts per category (any iterable). A
    single-category or empty composition scores 0.
    """
    a = np.asarray([max(0.0, float(v)) for v in areas], dtype=float)
    a = a[a > 0]
    if a.size <= 1:
        return 0.0
    p = a / a.sum()
    h = float(-(p * np.log(p)).sum())
    return h / float(np.log(a.size))


def walk_scores(inter_density, mix=None, dest_count=None, block_len=None,
                slope_pct=None, weights=None, breakpoints=None):
    """Combine per-segment ingredients into 0-100 walkability scores.

    Parameters (all aligned 1-D arrays of the same length; every one but
    ``inter_density`` may be None when that ingredient was not supplied):

    - ``inter_density``  junctions (degree >= 3 nodes) per km2 around the
      segment midpoint
    - ``mix``            normalised land-use mix entropy in [0, 1]
    - ``dest_count``     destinations (POIs) within the radius
    - ``block_len``      mean street-segment length (m) around the segment,
      the block-size proxy - shorter is better
    - ``slope_pct``      average slope of the segment in percent

    Returns a dict of sub-score arrays (``s_intersections`` ...) plus
    ``total`` - the weighted mean over the components present, with the
    missing components' weights renormalised away.
    """
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        for key, val in weights.items():
            if key not in w:
                raise ValueError(f"unknown walkability component '{key}'")
            w[key] = max(0.0, float(val))
    bp = dict(DEFAULT_BREAKPOINTS)
    if breakpoints:
        bp.update({k: float(v) for k, v in breakpoints.items()})

    inter_density = np.asarray(inter_density, dtype=float)
    n = len(inter_density)
    subs = {"intersections": linear_score(
        inter_density, 0.0, bp["intersections_full"])}
    if mix is not None:
        subs["mix"] = np.clip(np.asarray(mix, dtype=float), 0.0, 1.0) * 100.0
    if dest_count is not None:
        subs["destinations"] = linear_score(
            dest_count, 0.0, bp["destinations_full"])
    if block_len is not None:
        subs["blocklength"] = linear_score(
            block_len, bp["block_worst"], bp["block_best"])
    if slope_pct is not None:
        subs["slope"] = linear_score(slope_pct, bp["slope_worst"], 0.0)

    for arr in subs.values():
        if arr.shape != (n,):
            raise ValueError("all ingredient arrays must share one length")

    w_total = sum(w[k] for k in subs)
    total = np.zeros(n)
    if w_total > 0:
        for key, arr in subs.items():
            total += w[key] * arr
        total /= w_total
    out = {f"s_{key}": arr for key, arr in subs.items()}
    out["total"] = total
    return out
