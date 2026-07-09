# -*- coding: utf-8 -*-
"""Urban growth kernels: land-cover change, CA growth, sprawl metrics.

Pure NumPy. Three views of urban expansion:

* :func:`change_matrix` - the transition cross-tab of two land-cover
  rasters: who became what, gains/losses/persistence per class.
* :func:`ca_simulate` - a constrained cellular-automaton growth model
  (SLEUTH-flavoured, deliberately simple): per step, non-urban
  unconstrained cells score ``suitability x (base + w x urban
  neighbourhood share)`` and the top cells convert until the step's
  demand is met. Fully deterministic for a given ``rng_seed`` - the tiny
  tie-breaking jitter comes from ``numpy.random.default_rng``, which is
  stable across processes (never seed with ``hash()``).
* :func:`sprawl_metrics` - the SDG 11.3.1 land-consumption-rate to
  population-growth-rate ratio (LCRPGR), patch structure and edge
  density of the urban mask.
"""
from __future__ import annotations

import math

import numpy as np


def change_matrix(lc1, lc2, nodata=None):
    """Transition cross-tab of two equally shaped integer rasters.

    Cells equal to ``nodata`` in either raster are ignored. Returns dict:
    ``classes`` (sorted union), ``matrix`` (K, K) counts with rows = from
    and columns = to, and per-class ``gained`` / ``lost`` / ``persisted``
    / ``net`` cell counts aligned with ``classes``.
    """
    a = np.asarray(lc1).ravel()
    b = np.asarray(lc2).ravel()
    if a.shape != b.shape:
        raise ValueError("the two rasters must share one shape")
    keep = np.ones(a.shape, dtype=bool)
    if nodata is not None:
        keep = (a != nodata) & (b != nodata)
    a, b = a[keep], b[keep]
    classes = sorted(set(np.unique(a).tolist()) | set(np.unique(b).tolist()))
    index = {c: i for i, c in enumerate(classes)}
    k = len(classes)
    matrix = np.zeros((k, k), dtype=np.int64)
    ai = np.asarray([index[v] for v in a.tolist()], dtype=np.int64)
    bi = np.asarray([index[v] for v in b.tolist()], dtype=np.int64)
    np.add.at(matrix, (ai, bi), 1)
    persisted = np.diag(matrix).copy()
    lost = matrix.sum(axis=1) - persisted
    gained = matrix.sum(axis=0) - persisted
    return {
        "classes": classes,
        "matrix": matrix,
        "persisted": persisted,
        "lost": lost,
        "gained": gained,
        "net": gained - lost,
    }


def _neigh_share(mask):
    """Share of the 8 neighbours that are urban (edges count absentees)."""
    m = np.pad(mask.astype(np.float64), 1)
    total = np.zeros_like(mask, dtype=np.float64)
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            total += m[1 + dr:m.shape[0] - 1 + dr,
                       1 + dc:m.shape[1] - 1 + dc]
    return total / 8.0


def ca_simulate(seed_urban, suitability, demand_cells, iterations=5,
                constraints=None, neigh_weight=1.0, base=0.1, rng_seed=0,
                cancel=None):
    """Constrained CA growth. Returns dict with the conversion history.

    - ``seed_urban``: boolean start mask.
    - ``suitability``: per-cell development pull (any scale; normalised to
      the 0-1 range internally; NaN cells never convert).
    - ``demand_cells``: total cells to convert over all iterations.
    - ``constraints``: boolean mask of cells that may never convert.
    - score = suit_norm x (``base`` + ``neigh_weight`` x urban share of the
      8 neighbours); the per-step top scorers convert. ``base`` > 0 lets
      isolated but highly suitable cells leapfrog.
    - ``rng_seed`` feeds ``default_rng`` for the tie-breaking jitter only.

    Returns ``masks`` (list of masks, index 0 = start), ``converted``
    (per-step counts) and ``year_of`` (int grid: 0 = initially urban,
    k = converted at step k, -1 = never).
    """
    urban = np.asarray(seed_urban, dtype=bool).copy()
    suit = np.asarray(suitability, dtype=float)
    if suit.shape != urban.shape:
        raise ValueError("suitability shape must match the seed mask")
    finite = np.isfinite(suit)
    smin = float(suit[finite].min()) if finite.any() else 0.0
    smax = float(suit[finite].max()) if finite.any() else 1.0
    span = (smax - smin) or 1.0
    suit_norm = np.where(finite, (suit - smin) / span, 0.0)
    blocked = np.zeros_like(urban)
    if constraints is not None:
        blocked = np.asarray(constraints, dtype=bool)
        if blocked.shape != urban.shape:
            raise ValueError("constraints shape must match the seed mask")
    rng = np.random.default_rng(int(rng_seed))
    jitter = rng.random(urban.shape) * 1e-9

    iterations = max(1, int(iterations))
    demand_cells = max(0, int(demand_cells))
    per_step = [demand_cells // iterations] * iterations
    per_step[-1] += demand_cells - sum(per_step)

    masks = [urban.copy()]
    year_of = np.where(urban, 0, -1).astype(np.int64)
    converted = []
    for step, want in enumerate(per_step, start=1):
        if cancel is not None and cancel():
            break
        score = suit_norm * (base + neigh_weight * _neigh_share(urban))
        score = score + jitter
        score[urban | blocked | ~finite] = -np.inf
        flat = score.ravel()
        avail = int(np.isfinite(flat).sum())
        take = min(want, avail)
        if take > 0:
            top = np.argpartition(flat, -take)[-take:]
            rows, cols = np.unravel_index(top, urban.shape)
            urban[rows, cols] = True
            year_of[rows, cols] = step
        converted.append(take)
        masks.append(urban.copy())
    return {"masks": masks, "converted": converted, "year_of": year_of}


def _patches(mask):
    """4-neighbour connected components of a boolean mask.

    Returns (labels int grid with -1 outside, n_components, sizes list).
    """
    mask = np.asarray(mask, dtype=bool)
    labels = np.full(mask.shape, -1, dtype=np.int64)
    sizes = []
    rows, cols = mask.shape
    for r0 in range(rows):
        for c0 in range(cols):
            if not mask[r0, c0] or labels[r0, c0] >= 0:
                continue
            comp = len(sizes)
            stack = [(r0, c0)]
            labels[r0, c0] = comp
            n = 0
            while stack:
                r, c = stack.pop()
                n += 1
                for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    rr, cc = r + dr, c + dc
                    if (0 <= rr < rows and 0 <= cc < cols
                            and mask[rr, cc] and labels[rr, cc] < 0):
                        labels[rr, cc] = comp
                        stack.append((rr, cc))
            sizes.append(n)
    return labels, len(sizes), sizes


def edge_length(mask, pixel=1.0):
    """Total urban / non-urban boundary length (map units), raster edges
    counted as boundary."""
    m = np.pad(np.asarray(mask, dtype=bool), 1)
    edges = 0
    edges += int(np.sum(m[1:-1, 1:-1] & ~m[:-2, 1:-1]))
    edges += int(np.sum(m[1:-1, 1:-1] & ~m[2:, 1:-1]))
    edges += int(np.sum(m[1:-1, 1:-1] & ~m[1:-1, :-2]))
    edges += int(np.sum(m[1:-1, 1:-1] & ~m[1:-1, 2:]))
    return edges * float(pixel)


def sprawl_metrics(urban_t1, urban_t2, pop_t1, pop_t2, pixel=1.0):
    """Expansion vs population growth + patch structure of the t2 mask.

    LCRPGR (SDG 11.3.1) = ln(Urb2/Urb1) / ln(Pop2/Pop1) - above 1 the
    city consumes land faster than it grows people. Also returns urban
    areas, the patch count, the largest-patch share and the edge density
    of t2 (boundary length per urban area).
    """
    m1 = np.asarray(urban_t1, dtype=bool)
    m2 = np.asarray(urban_t2, dtype=bool)
    a1 = float(m1.sum()) * pixel * pixel
    a2 = float(m2.sum()) * pixel * pixel
    lcr = math.log(a2 / a1) if a1 > 0 and a2 > 0 else float("nan")
    pgr = (math.log(float(pop_t2) / float(pop_t1))
           if pop_t1 > 0 and pop_t2 > 0 else float("nan"))
    ratio = lcr / pgr if pgr not in (0.0,) and math.isfinite(lcr) \
        and math.isfinite(pgr) and pgr != 0 else float("nan")
    _labels, n_patches, sizes = _patches(m2)
    largest = max(sizes) / sum(sizes) if sizes else 0.0
    edge = edge_length(m2, pixel=pixel)
    return {
        "area_t1": a1,
        "area_t2": a2,
        "lcr": lcr,
        "pgr": pgr,
        "lcrpgr": ratio,
        "n_patches": n_patches,
        "largest_share": largest,
        "edge_length": edge,
        "edge_density": edge / a2 if a2 > 0 else 0.0,
    }
