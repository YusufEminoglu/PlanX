# -*- coding: utf-8 -*-
"""Landscape pattern metrics on a categorical raster (FRAGSTATS families).

McGarigal's FRAGSTATS defines the vocabulary every landscape-ecology study
reports; this module implements the class- and landscape-level metrics a
planning study most often quotes, on the same raster conventions:

* **Area and density** - class area CA, percentage of landscape PLAND,
  number of patches NP, patch density PD (per 100 ha), largest patch index
  LPI and mean patch area AREA_MN.
* **Edge** - total edge TE and edge density ED. Only edges between two valid
  cells of different classes count: the landscape boundary and edges against
  nodata are *not* edge, FRAGSTATS's "no boundary" choice, stated rather than
  implied.
* **Shape** - mean shape index SHAPE_MN, ``0.25 p / sqrt(a)`` per patch
  (1 for a square, larger for anything less compact), perimeter counted on
  every side of the patch including the landscape boundary.
* **Core area** - cells farther than an edge depth from any cell outside the
  patch: total core area TCA and core-area percentage CPLAND.
* **Aggregation** - the aggregation index AI of He, DeZonia & Mladenoff
  (2000): like adjacencies over the maximum possible for that many cells, and
  contagion CONTAG (Li & Reynolds 1993, FRAGSTATS form).
* **Diversity** - Shannon diversity SHDI and evenness SHEI, Simpson's SIDI,
  patch richness PR.

Patches are connected components under the 8-neighbour rule by default
(FRAGSTATS's default) or the 4-neighbour rule. SciPy's ``ndimage.label`` is
used when available; the pure-Python union-find fallback gives identical
labels up to numbering, which the tests assert.

Areas use the ground cell size the caller passes in (metres), so a raster in
a projected CRS whose unit is not the ground metre is converted once, by the
caller, rather than reported in its own units.
"""
from __future__ import annotations

import math

import numpy as np

_N4 = ((1, 0), (-1, 0), (0, 1), (0, -1))
_N8 = _N4 + ((1, 1), (1, -1), (-1, 1), (-1, -1))


def label_patches(classes, valid, rule=8, use_scipy=None):
    """Patch id per cell (-1 outside), patch class list, patch cell counts.

    Patches never cross class boundaries; numbering follows the first cell of
    each patch in row-major order, so the SciPy and pure paths agree exactly.
    """
    classes = np.asarray(classes)
    valid = np.asarray(valid, dtype=bool)
    if use_scipy is None:
        try:
            import scipy.ndimage  # noqa: F401
            use_scipy = True
        except Exception:
            use_scipy = False
    labels = np.full(classes.shape, -1, dtype=np.int64)
    if use_scipy:
        from scipy import ndimage
        structure = np.ones((3, 3), dtype=bool) if rule == 8 else None
        next_id = 0
        for value in np.unique(classes[valid]):
            lab, n = ndimage.label(valid & (classes == value), structure=structure)
            mask = lab > 0
            labels[mask] = lab[mask] - 1 + next_id
            next_id += n
    else:
        rows, cols = classes.shape
        neigh = _N8 if rule == 8 else _N4
        next_id = 0
        for r0 in range(rows):
            for c0 in range(cols):
                if not valid[r0, c0] or labels[r0, c0] >= 0:
                    continue
                value = classes[r0, c0]
                labels[r0, c0] = next_id
                stack = [(r0, c0)]
                while stack:
                    r, c = stack.pop()
                    for dr, dc in neigh:
                        rr, cc = r + dr, c + dc
                        if (0 <= rr < rows and 0 <= cc < cols and valid[rr, cc]
                                and labels[rr, cc] < 0 and classes[rr, cc] == value):
                            labels[rr, cc] = next_id
                            stack.append((rr, cc))
                next_id += 1
    # Canonical numbering: by first cell in row-major order.
    flat = labels.ravel()
    ids = flat[flat >= 0]
    if not len(ids):
        return labels, np.zeros(0, dtype=classes.dtype), np.zeros(0, dtype=np.int64)
    _, first = np.unique(ids, return_index=True)
    order = np.argsort(first, kind="stable")
    old_ids = np.unique(ids)[order]
    remap = np.full(int(flat.max()) + 1, -1, dtype=np.int64)
    remap[old_ids] = np.arange(len(old_ids))
    labels = np.where(labels >= 0, remap[np.maximum(labels, 0)], -1)
    counts = np.bincount(labels[labels >= 0], minlength=len(old_ids))
    first_cell = np.full(len(old_ids), -1, dtype=np.int64)
    pos = np.nonzero(labels.ravel() >= 0)[0]
    lab_flat = labels.ravel()[pos]
    first_cell[lab_flat[::-1]] = pos[::-1]
    patch_class = classes.ravel()[first_cell]
    return labels, patch_class, counts


def _shift_pairs(grid, valid):
    """(a, b, both_valid) arrays for every horizontally and vertically adjacent
    cell pair, counted once each."""
    a = np.concatenate([grid[:, :-1].ravel(), grid[:-1, :].ravel()])
    b = np.concatenate([grid[:, 1:].ravel(), grid[1:, :].ravel()])
    va = np.concatenate([valid[:, :-1].ravel(), valid[:-1, :].ravel()])
    vb = np.concatenate([valid[:, 1:].ravel(), valid[1:, :].ravel()])
    return a, b, va & vb


def patch_perimeters(labels):
    """Cell-edge perimeter of every patch, counting all four sides of each
    cell that border anything not in the same patch (landscape boundary and
    nodata included)."""
    n = int(labels.max()) + 1 if labels.size and labels.max() >= 0 else 0
    padded = np.pad(labels, 1, constant_values=-1)
    core = padded[1:-1, 1:-1]
    perim = np.zeros(n, dtype=np.int64)
    for dr, dc in _N4:
        other = padded[1 + dr:padded.shape[0] - 1 + dr, 1 + dc:padded.shape[1] - 1 + dc]
        mask = (core >= 0) & (other != core)
        perim += np.bincount(core[mask], minlength=n)
    return perim


def core_cells(labels, depth_cells):
    """Cells of each patch farther than ``depth_cells`` from its outside.

    8-neighbour erosion repeated ``depth_cells`` times; a depth of 0 makes
    every cell core. Returns a boolean grid.
    """
    core = labels >= 0
    for _ in range(int(depth_cells)):
        padded = np.pad(labels, 1, constant_values=-1)
        keep = core.copy()
        for dr, dc in _N8:
            other = padded[1 + dr:padded.shape[0] - 1 + dr, 1 + dc:padded.shape[1] - 1 + dc]
            keep &= other == labels
        core = keep & core
        labels = np.where(core, labels, -1)
    return core


def max_like_adjacencies(cells):
    """He et al. (2000): the most like adjacencies ``cells`` cells can share."""
    a = int(cells)
    if a <= 0:
        return 0
    n = int(math.isqrt(a))
    m = a - n * n
    if m == 0:
        return 2 * n * (n - 1)
    if m <= n:
        return 2 * n * (n - 1) + 2 * m - 1
    return 2 * n * (n - 1) + 2 * m - 2


def metrics(classes, valid, cell_m, rule=8, edge_depth_m=0.0, use_scipy=None):
    """Class and landscape metrics. Returns ``(class_rows, landscape, patches)``.

    ``class_rows``: list of dicts keyed by metric for each class value, sorted
    by value. ``landscape``: dict of landscape-level metrics. ``patches``:
    dict of per-patch arrays (``class``, ``cells``, ``area_ha``, ``perim_m``,
    ``shape``, ``core_ha``) plus the ``labels`` grid.
    """
    classes = np.asarray(classes)
    valid = np.asarray(valid, dtype=bool)
    if not valid.any():
        raise ValueError("the raster has no valid cell")
    cell_ha = cell_m * cell_m / 10000.0
    total_cells = int(valid.sum())
    total_ha = total_cells * cell_ha
    labels, patch_class, counts = label_patches(classes, valid, rule, use_scipy)
    perim_cells = patch_perimeters(labels)
    depth_cells = int(math.ceil(edge_depth_m / cell_m - 1e-9)) if edge_depth_m > 0 else 0
    core = core_cells(labels, depth_cells)
    core_counts = np.bincount(labels[core], minlength=len(counts)) if len(counts) else np.zeros(0)
    shape = 0.25 * perim_cells / np.sqrt(np.maximum(counts, 1))

    a, b, both = _shift_pairs(classes, valid)
    values = np.unique(classes[valid])
    edge_between = both & (a != b)
    like = both & (a == b)
    class_rows = []
    for value in values:
        in_class = patch_class == value
        cells = int(counts[in_class].sum())
        np_ = int(in_class.sum())
        te_cells = int(np.sum(edge_between & ((a == value) | (b == value))))
        g_ii = int(np.sum(like & (a == value)))
        g_max = max_like_adjacencies(cells)
        class_rows.append({
            "class": value.item() if hasattr(value, "item") else value,
            "CA": cells * cell_ha,
            "PLAND": 100.0 * cells / total_cells,
            "NP": np_,
            "PD": 100.0 * np_ / total_ha,
            "LPI": 100.0 * int(counts[in_class].max()) / total_cells,
            "TE": te_cells * cell_m,
            "ED": te_cells * cell_m / total_ha,
            "AREA_MN": cells * cell_ha / np_,
            "SHAPE_MN": float(shape[in_class].mean()),
            "TCA": float(core_counts[in_class].sum()) * cell_ha,
            "CPLAND": 100.0 * float(core_counts[in_class].sum()) / total_cells,
            "AI": 100.0 * g_ii / g_max if g_max > 0 else None,
        })

    p = np.asarray([row["PLAND"] / 100.0 for row in class_rows])
    m = len(values)
    shdi = float(-np.sum(p * np.log(p)))
    landscape = {
        "TA": total_ha,
        "NP": int(len(counts)),
        "PD": 100.0 * len(counts) / total_ha,
        "LPI": 100.0 * int(counts.max()) / total_cells,
        "TE": int(edge_between.sum()) * cell_m,
        "ED": int(edge_between.sum()) * cell_m / total_ha,
        "PR": m,
        "SHDI": shdi,
        "SHEI": shdi / math.log(m) if m > 1 else None,
        "SIDI": float(1.0 - np.sum(p * p)),
        "CONTAG": contagion(classes, valid, values) if m > 1 else None,
        "AI": float(sum(row["AI"] * row["PLAND"] / 100.0
                        for row in class_rows if row["AI"] is not None)),
        "TCA": float(core_counts.sum()) * cell_ha if len(core_counts) else 0.0,
    }
    patches = {"labels": labels, "class": patch_class, "cells": counts,
               "area_ha": counts * cell_ha, "perim_m": perim_cells * cell_m,
               "shape": shape, "core_ha": core_counts * cell_ha}
    return class_rows, landscape, patches


def contagion(classes, valid, values=None):
    """FRAGSTATS contagion (percent), adjacencies double-counted, 4-neighbour.

    ``CONTAG = [1 + sum_i sum_k P_i (g_ik / sum_k g_ik) ln(P_i g_ik / sum_k g_ik)
    / (2 ln m)] * 100``. 0 when every adjacency is between different classes
    in equal proportions, 100 when the landscape is one class.
    """
    classes = np.asarray(classes)
    valid = np.asarray(valid, dtype=bool)
    if values is None:
        values = np.unique(classes[valid])
    m = len(values)
    if m < 2:
        return None
    index = {v.item() if hasattr(v, "item") else v: i for i, v in enumerate(values)}
    a, b, both = _shift_pairs(classes, valid)
    ia = np.asarray([index[x.item() if hasattr(x, "item") else x] for x in a[both]])
    ib = np.asarray([index[x.item() if hasattr(x, "item") else x] for x in b[both]])
    g = np.zeros((m, m))
    np.add.at(g, (ia, ib), 1.0)
    g = g + g.T          # double count: each pair seen from both cells
    counts = np.asarray([np.sum(valid & (classes == v)) for v in values], dtype=np.float64)
    P = counts / counts.sum()
    row = g.sum(axis=1)
    total = 0.0
    for i in range(m):
        if row[i] <= 0:
            continue
        for k in range(m):
            if g[i, k] <= 0:
                continue
            q = P[i] * g[i, k] / row[i]
            total += q * math.log(q)
    return 100.0 * (1.0 + total / (2.0 * math.log(m)))
