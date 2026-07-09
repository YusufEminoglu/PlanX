# -*- coding: utf-8 -*-
"""Visibility kernels: DSM viewsheds and 2-D isovists.

Pure NumPy. Two families:

* :func:`viewshed` - radial line-of-sight sweep over a surface model
  (DSM), the same ray idiom as the shadow/SVF sweeps in ``solar.py``:
  march every azimuth outward, keep the running horizon angle, and mark a
  cell visible when the angle to its (surface + target height) clears the
  horizon accumulated before it. Rays are capped at the raster diagonal
  (the low-angle lesson of the shadow sweep).
* :func:`isovist` / :func:`isovist_field` - 2-D visibility polygons over
  an obstacle mask (buildings rasterised to cells), the VGA companion:
  radial distances until the first blocked cell, summarised into the
  classic isovist measures (Benedikt 1979): area, perimeter, min/max/mean
  radial, circularity and occlusivity.
"""
from __future__ import annotations

import math

import numpy as np


def _ray_steps(pixel: float, max_dist: float):
    step = pixel / 2.0
    return np.arange(step, max_dist + step, step)


def viewshed(dsm, pixel, observer_rc, observer_h=1.6, target_h=0.0,
             radius=None, n_dirs=720, out=None, cancel=None):
    """Boolean visibility grid from one observer over a DSM.

    ``observer_rc`` is the (row, col) cell; the eye sits at the DSM surface
    plus ``observer_h``. A cell is visible when the sight line to its
    surface + ``target_h`` clears every surface between. ``radius`` in map
    units (None = raster diagonal). ``out`` (uint8) accumulates with
    maximum, so multiple observers can share one grid. NaN cells never
    block and are never visible.
    """
    dsm = np.asarray(dsm, dtype=float)
    rows, cols = dsm.shape
    r0, c0 = int(observer_rc[0]), int(observer_rc[1])
    if not (0 <= r0 < rows and 0 <= c0 < cols):
        raise ValueError("observer lies outside the raster")
    z0 = dsm[r0, c0]
    if not np.isfinite(z0):
        z0 = 0.0
    z_eye = z0 + float(observer_h)
    diag = math.hypot(rows, cols) * pixel
    max_dist = diag if radius is None or radius <= 0 else min(radius, diag)
    vis = out if out is not None else np.zeros((rows, cols), dtype=np.uint8)
    if vis[r0, c0] < 1:
        vis[r0, c0] = 1

    t = _ray_steps(pixel, max_dist)
    for k in range(int(n_dirs)):
        if cancel is not None and k % 90 == 0 and cancel():
            break
        az = 2.0 * math.pi * k / n_dirs
        dc = math.sin(az) / pixel
        dr = -math.cos(az) / pixel
        rr = np.rint(r0 + t * dr).astype(np.int64)
        cc = np.rint(c0 + t * dc).astype(np.int64)
        inside = (rr >= 0) & (rr < rows) & (cc >= 0) & (cc < cols)
        if not inside.any():
            continue
        rr, cc, tt = rr[inside], cc[inside], t[inside]
        z = dsm[rr, cc]
        finite = np.isfinite(z)
        z_safe = np.where(finite, z, -np.inf)
        ang_surf = np.where(finite, (z_safe - z_eye) / tt, -np.inf)
        ang_tgt = (z_safe + float(target_h) - z_eye) / tt
        horizon = np.concatenate(
            ([-np.inf], np.maximum.accumulate(ang_surf)[:-1]))
        visible = finite & (ang_tgt >= horizon - 1e-12)
        if visible.any():
            vis[rr[visible], cc[visible]] = 1
    return vis


def isovist(mask, origin_rc, pixel=1.0, n_rays=360, max_dist=None):
    """Isovist measures at one point of a 2-D obstacle mask.

    ``mask`` is boolean (True = blocked). Rays march from the origin cell
    centre until the first blocked cell, the raster edge or ``max_dist``.
    Returns a dict: ``area`` (shoelace over the ray endpoints, map units
    squared), ``perimeter``, ``min_rad`` / ``max_rad`` / ``mean_rad``,
    ``circularity`` (4 pi A / P^2 - 1.0 for a circle), ``occlusivity``
    (share of rays stopped by an obstacle rather than range or edge) and
    the raw ``radials`` array.
    """
    mask = np.asarray(mask, dtype=bool)
    rows, cols = mask.shape
    r0, c0 = int(origin_rc[0]), int(origin_rc[1])
    if not (0 <= r0 < rows and 0 <= c0 < cols):
        raise ValueError("origin lies outside the mask")
    if mask[r0, c0]:
        return {"area": 0.0, "perimeter": 0.0, "min_rad": 0.0,
                "max_rad": 0.0, "mean_rad": 0.0, "circularity": 0.0,
                "occlusivity": 1.0,
                "radials": np.zeros(int(n_rays))}
    diag = math.hypot(rows, cols) * pixel
    reach = diag if max_dist is None or max_dist <= 0 else min(max_dist, diag)
    t = _ray_steps(pixel, reach)
    radials = np.empty(int(n_rays))
    occluded = 0
    end_x = np.empty(int(n_rays))
    end_y = np.empty(int(n_rays))
    for k in range(int(n_rays)):
        az = 2.0 * math.pi * k / n_rays
        dc = math.sin(az) / pixel
        dr = -math.cos(az) / pixel
        rr = np.rint(r0 + t * dr).astype(np.int64)
        cc = np.rint(c0 + t * dc).astype(np.int64)
        inside = (rr >= 0) & (rr < rows) & (cc >= 0) & (cc < cols)
        stop = len(t)
        hit = False
        if not inside.all():
            stop = int(np.argmin(inside))  # first step outside
        blocked = mask[rr[:stop], cc[:stop]]
        if blocked.any():
            stop = int(np.argmax(blocked))
            hit = True
        dist = t[stop - 1] if stop > 0 else 0.0
        if not hit and max_dist is not None and max_dist > 0:
            dist = min(dist, max_dist)
        radials[k] = dist
        occluded += 1 if hit else 0
        end_x[k] = dist * math.sin(az)
        end_y[k] = dist * math.cos(az)
    x2 = np.roll(end_x, -1)
    y2 = np.roll(end_y, -1)
    area = 0.5 * abs(float(np.sum(end_x * y2 - x2 * end_y)))
    perimeter = float(np.sum(np.hypot(x2 - end_x, y2 - end_y)))
    circ = 4.0 * math.pi * area / (perimeter ** 2) if perimeter > 0 else 0.0
    return {
        "area": area,
        "perimeter": perimeter,
        "min_rad": float(radials.min()),
        "max_rad": float(radials.max()),
        "mean_rad": float(radials.mean()),
        "circularity": float(min(1.0, circ)),
        "occlusivity": occluded / float(n_rays),
        "radials": radials,
    }


def isovist_field(mask, points_rc, pixel=1.0, n_rays=180, max_dist=None,
                  cancel=None):
    """Isovist measures sampled at many points; returns arrays per metric.

    Optimized by precomputing direction offsets and ray steps.
    """
    keys = ("area", "perimeter", "min_rad", "max_rad", "mean_rad",
            "circularity", "occlusivity")
    out = {k: np.zeros(len(points_rc)) for k in keys}

    mask = np.asarray(mask, dtype=bool)
    rows, cols = mask.shape

    diag = math.hypot(rows, cols) * pixel
    reach = diag if max_dist is None or max_dist <= 0 else min(max_dist, diag)
    t = _ray_steps(pixel, reach)
    n_steps = len(t)

    # Precompute direction vectors and t_dr / t_dc float arrays
    t_dr = []
    t_dc = []
    cos_angles = []
    sin_angles = []
    for k in range(int(n_rays)):
        az = 2.0 * math.pi * k / n_rays
        dc = math.sin(az) / pixel
        dr = -math.cos(az) / pixel
        t_dr.append(t * dr)
        t_dc.append(t * dc)
        cos_angles.append(math.cos(az))
        sin_angles.append(math.sin(az))

    for i, rc in enumerate(points_rc):
        if cancel is not None and i % 50 == 0 and cancel():
            break
        r0, c0 = int(rc[0]), int(rc[1])
        if not (0 <= r0 < rows and 0 <= c0 < cols):
            raise ValueError("origin lies outside the mask")
        if mask[r0, c0]:
            out["area"][i] = 0.0
            out["perimeter"][i] = 0.0
            out["min_rad"][i] = 0.0
            out["max_rad"][i] = 0.0
            out["mean_rad"][i] = 0.0
            out["circularity"][i] = 0.0
            out["occlusivity"][i] = 1.0
            continue

        radials = np.empty(int(n_rays))
        occluded = 0
        end_x = np.empty(int(n_rays))
        end_y = np.empty(int(n_rays))

        for k in range(int(n_rays)):
            rr = np.rint(r0 + t_dr[k]).astype(np.int64)
            cc = np.rint(c0 + t_dc[k]).astype(np.int64)

            inside = (rr >= 0) & (rr < rows) & (cc >= 0) & (cc < cols)
            stop = n_steps
            hit = False
            if not inside.all():
                stop = int(np.argmin(inside))

            blocked = mask[rr[:stop], cc[:stop]]
            if blocked.any():
                stop = int(np.argmax(blocked))
                hit = True

            dist = t[stop - 1] if stop > 0 else 0.0
            if not hit and max_dist is not None and max_dist > 0:
                dist = min(dist, max_dist)

            radials[k] = dist
            occluded += 1 if hit else 0
            end_x[k] = dist * sin_angles[k]
            end_y[k] = dist * cos_angles[k]

        x2 = np.roll(end_x, -1)
        y2 = np.roll(end_y, -1)
        area = 0.5 * abs(float(np.sum(end_x * y2 - x2 * end_y)))
        perimeter = float(np.sum(np.hypot(x2 - end_x, y2 - end_y)))
        circ = 4.0 * math.pi * area / (perimeter ** 2) if perimeter > 0 else 0.0

        out["area"][i] = area
        out["perimeter"][i] = perimeter
        out["min_rad"][i] = float(radials.min())
        out["max_rad"][i] = float(radials.max())
        out["mean_rad"][i] = float(radials.mean())
        out["circularity"][i] = float(min(1.0, circ))
        out["occlusivity"][i] = occluded / float(n_rays)

    return out
