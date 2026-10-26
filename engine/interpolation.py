# -*- coding: utf-8 -*-
"""Areal interpolation between incompatible zone systems.

Census tracts never line up with planning zones, school catchments or a
hexagon grid, and every planning study has to move counts and rates from one
set of polygons to another. The engine works on the *intersection table* -
for every overlapping (source, target) pair, the area they share - so the
geometry stays in the algorithm and the arithmetic stays testable:

* **Extensive** variables (counts: population, jobs, dwellings) are split in
  proportion to area: ``v_t = sum_s v_s * A_st / A_s``. Mass is preserved -
  the target totals add up to the source totals times the share of each
  source the targets cover (Goodchild & Lam 1980).
* **Intensive** variables (rates, densities, shares) are averaged over the
  part of the target the sources cover: ``v_t = sum_s v_s * A_st / sum_s A_st``.
  Splitting a rate by area would be meaningless - a 40 percent share does not
  become 20 percent because half the tract lies elsewhere.
* **Dasymetric** weighting (Mennis 2003, binary form) replaces area by the
  area of an *ancillary* mask - residential land, buildings - inside each
  piece: people live on the residential part of a tract, not in its park.
  A source with no ancillary area at all falls back to plain area weights
  rather than losing its count, and the fallback is reported.
"""
from __future__ import annotations

import numpy as np


def interpolate(pairs, source_values, n_targets, source_area, kind="extensive",
                weight_area=None, source_weight=None):
    """Interpolate one variable.

    ``pairs`` is a list of ``(s, t, area_st)``; ``source_values`` one value per
    source (NaN = missing, skipped); ``source_area`` the area of each source.
    For dasymetric weighting pass ``weight_area`` (one per pair: the ancillary
    area inside the piece) and ``source_weight`` (the ancillary area inside
    each source). Returns ``(values per target, info)`` where ``info`` holds
    ``covered_share`` per source and ``fallback`` (sources without ancillary
    area that used plain area weights).
    """
    values = np.asarray(source_values, dtype=np.float64)
    source_area = np.asarray(source_area, dtype=np.float64)
    n_sources = len(values)
    out = np.zeros(n_targets)
    denom = np.zeros(n_targets)
    covered = np.zeros(n_sources)
    fallback = set()
    use_dasy = weight_area is not None
    for k, (s, t, a) in enumerate(pairs):
        covered[s] += a
    for k, (s, t, a) in enumerate(pairs):
        v = values[s]
        if not np.isfinite(v) or a <= 0:
            continue
        if kind == "extensive":
            if use_dasy and source_weight[s] > 0:
                share = weight_area[k] / source_weight[s]
            else:
                if use_dasy:
                    fallback.add(int(s))
                share = a / source_area[s] if source_area[s] > 0 else 0.0
            out[t] += v * share
        elif kind == "intensive":
            w = weight_area[k] if use_dasy and source_weight[s] > 0 else a
            if use_dasy and source_weight[s] <= 0:
                fallback.add(int(s))
            out[t] += v * w
            denom[t] += w
        else:
            raise ValueError(f"unknown variable kind '{kind}'")
    if kind == "intensive":
        out = np.where(denom > 0, out / np.where(denom > 0, denom, 1.0), np.nan)
    share = np.where(source_area > 0, covered / np.where(source_area > 0, source_area, 1.0), 0.0)
    return out, {"covered_share": np.minimum(share, 1.0), "fallback": sorted(fallback)}


def expected_total(source_values, covered_share, source_weight=None, pairs=None,
                   weight_area=None):
    """The target total an extensive interpolation must reproduce.

    Area weighting keeps each source's value times the share of its area the
    targets cover. Dasymetric weighting keeps each source's value times the
    share of its *ancillary* area the targets cover.
    """
    values = np.nan_to_num(np.asarray(source_values, dtype=np.float64))
    if source_weight is None:
        return float(np.sum(values * covered_share))
    kept = np.zeros(len(values))
    for k, (s, _t, _a) in enumerate(pairs):
        kept[s] += weight_area[k]
    total = 0.0
    for s, v in enumerate(values):
        if source_weight[s] > 0:
            total += v * min(1.0, kept[s] / source_weight[s])
        else:
            total += v * covered_share[s]
    return float(total)
