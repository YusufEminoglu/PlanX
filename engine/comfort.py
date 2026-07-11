# -*- coding: utf-8 -*-
"""Walking comfort engine: slope profiles, Tobler speeds, kernel densities."""
from __future__ import annotations

import numpy as np


def parse_breaks(text, default=(5.0, 8.0, 12.0)):
    """Parse 'a,b,c' into a strictly ascending tuple of floats.

    Empty/whitespace -> default. Non-numeric token or a non-ascending
    sequence raises ValueError naming the offending text. Any length >= 1
    is allowed (k breakpoints -> k+1 classes).
    """
    if not text or not text.strip():
        return default
    tokens = [t.strip() for t in text.split(',')]
    vals = []
    for tok in tokens:
        try:
            vals.append(float(tok))
        except ValueError:
            raise ValueError(f"Non-numeric breakpoint: '{tok}'")
    if not vals:
        return default
    for i in range(len(vals) - 1):
        if vals[i] >= vals[i + 1]:
            raise ValueError(f"Breakpoints must be strictly ascending, got: '{text}'")
    return tuple(vals)


def grade_stats(z, d):
    """Length-weighted grade statistics along a sampled profile.

    ``z``: elevations at the samples; ``d``: cumulative distances (same
    length, d[0] == 0, strictly increasing). Per interval i the signed
    grade is (z[i+1]-z[i]) / (d[i+1]-d[i]). Returns
    ``(mean_abs, max_abs, climb, descent)`` where mean_abs is the
    length-weighted mean of |grade| (weights = interval lengths), max_abs
    the maximum |grade|, climb the sum of positive dz in metres, descent
    the sum of |negative dz|. Grades are FRACTIONS (0.1 = 10%). Fewer than
    2 samples -> (0.0, 0.0, 0.0, 0.0).
    """
    z = np.asarray(z, dtype=np.float64)
    d = np.asarray(d, dtype=np.float64)
    if len(z) < 2 or len(d) < 2:
        return 0.0, 0.0, 0.0, 0.0
    dz = z[1:] - z[:-1]
    dd = d[1:] - d[:-1]

    # Avoid division by zero, but cumulative distance d is strictly increasing
    # meaning dd is positive. Just in case, guard dd <= 0.
    dd_mask = dd > 0
    if not np.any(dd_mask):
        return 0.0, 0.0, 0.0, 0.0

    grades = np.zeros_like(dz)
    grades[dd_mask] = dz[dd_mask] / dd[dd_mask]
    abs_grades = np.abs(grades)

    sum_dd = np.sum(dd[dd_mask])
    if sum_dd > 0:
        mean_abs = np.sum(abs_grades[dd_mask] * dd[dd_mask]) / sum_dd
    else:
        mean_abs = 0.0

    max_abs = np.max(abs_grades) if len(abs_grades) > 0 else 0.0

    climb = np.sum(dz[dz > 0])
    descent = np.sum(np.abs(dz[dz < 0]))

    return float(mean_abs), float(max_abs), float(climb), float(descent)


def tobler_speed(m):
    """Tobler's hiking function: speed = 6 * exp(-3.5 * |m + 0.05|) km/h.

    ``m`` is the signed grade (dz/dx fraction) in the direction of travel;
    scalar or ndarray in, same shape out. Maximum 6.0 km/h at m == -0.05.
    """
    is_scalar = np.isscalar(m) or isinstance(m, (int, float))
    m_arr = np.asarray(m, dtype=np.float64)
    res = 6.0 * np.exp(-3.5 * np.abs(m_arr + 0.05))
    if is_scalar:
        return float(res.item() if hasattr(res, 'item') else res)
    return res


def profile_time_min(grades, lengths):
    """Walking time in minutes over per-interval signed grades and lengths
    (metres): sum(len_i / 1000 / tobler_speed(m_i)) * 60. Empty -> 0.0."""
    grades = np.asarray(grades, dtype=np.float64)
    lengths = np.asarray(lengths, dtype=np.float64)
    if len(grades) == 0:
        return 0.0
    speeds = tobler_speed(grades)
    # len_i in meters, speed in km/h. Time in min is (len_i/1000)/speed * 60 = len_i * 0.06 / speed.
    times = (lengths / 1000.0) / speeds * 60.0
    return float(np.sum(times))


def class_of(value, breaks):
    """Competition-free class index 1..len(breaks)+1: 1 while
    value <= breaks[0], 2 while <= breaks[1], ..., len+1 above the last.
    Scalar or ndarray."""
    is_scalar = np.isscalar(value) or isinstance(value, (int, float))
    breaks = np.asarray(breaks, dtype=np.float64)
    res = np.searchsorted(breaks, value, side='left') + 1
    if is_scalar:
        return int(res)
    return res


def kernel_weight(dist, bandwidth, kind):
    """Kernel value for distances (ndarray) against one bandwidth h > 0.

    u = dist / h, clipped contributions to 0 where dist > h. kinds:
    'uniform' -> 1; 'triangular' -> 1 - u; 'epanechnikov' -> 1 - u**2;
    'gaussian' -> exp(-(u**2) * 4.5)  (i.e. sigma = h/3), truncated at h.
    Unknown kind raises ValueError.
    """
    dist = np.asarray(dist, dtype=np.float64)
    h = float(bandwidth)
    if h <= 0:
        raise ValueError("Bandwidth must be greater than 0")

    kind_lower = kind.lower()
    valid_kinds = {'uniform', 'triangular', 'epanechnikov', 'gaussian'}
    if kind_lower not in valid_kinds:
        raise ValueError(f"Unknown kernel kind: '{kind}'")

    u = dist / h
    if kind_lower == 'uniform':
        w = np.ones_like(u)
    elif kind_lower == 'triangular':
        w = 1.0 - u
    elif kind_lower == 'epanechnikov':
        w = 1.0 - u**2
    elif kind_lower == 'gaussian':
        w = np.exp(-(u**2) * 4.5)

    w = np.where(u > 1.0, 0.0, w)
    w = np.clip(w, 0.0, None)
    return w


def segment_density(samples_xy, pts_xy, pt_w, bandwidth, kind):
    """Mean kernel density of weighted points as seen from one segment.

    ``samples_xy`` (s,2): the segment's sample points; ``pts_xy`` (p,2) and
    ``pt_w`` (p,): candidate features (the caller pre-filters by a spatial
    index). Per sample: sum_i pt_w[i] * kernel_weight(dist_i, h, kind);
    returns the MEAN over the samples (0.0 when p == 0). Not normalised by
    area on purpose - it is a comparative index, not a probability density.
    """
    samples_xy = np.asarray(samples_xy, dtype=np.float64)
    pts_xy = np.asarray(pts_xy, dtype=np.float64)
    pt_w = np.asarray(pt_w, dtype=np.float64)

    if len(pts_xy) == 0 or len(samples_xy) == 0:
        return 0.0

    # samples_xy shape (s, 2), pts_xy shape (p, 2)
    diff = samples_xy[:, np.newaxis, :] - pts_xy[np.newaxis, :, :]
    dists = np.sqrt(np.sum(diff**2, axis=-1))  # dists shape (s, p)

    kw = kernel_weight(dists, bandwidth, kind)  # (s, p)
    weighted_kw = kw * pt_w[np.newaxis, :]  # (s, p)
    sample_sums = np.sum(weighted_kw, axis=1)  # (s,)

    return float(np.mean(sample_sums))


def combine_components(components, directions, weights=None):
    """Weighted 0-100 comfort index over min-max-normalised components.

    ``components``: dict name -> ndarray (n,) or None (absent);
    ``directions``: dict name -> +1 (higher is more comfortable) or -1;
    ``weights``: optional dict name -> float > 0, default 1.0 each.
    Absent (None) components are ignored. Components that are CONSTANT
    across segments (max == min) are dropped and reported. Each remaining
    component is min-max normalised to [0,1], flipped to comfort
    orientation (direction -1 -> 1 - norm), then
    index = 100 * sum(w * oriented) / sum(w) — the scenario.rank /
    walk_scores weighted-mean family. Returns ``(index, used, dropped)``
    where used/dropped are name lists in the input dict's key order (pass a
    plain dict built in a fixed literal order). Raises ValueError when no
    component is present and non-constant.
    """
    if weights is None:
        weights = {}

    used = []
    dropped = []

    # Let's find array length n
    n = None
    for name, val in components.items():
        if val is not None:
            val = np.asarray(val, dtype=np.float64)
            n = len(val)
            break

    if n is None:
        raise ValueError("No components provided or all are None")

    oriented_components = {}

    for name, val in components.items():
        if val is None:
            continue
        val = np.asarray(val, dtype=np.float64)
        if len(val) != n:
            raise ValueError(f"Component '{name}' has length {len(val)}, expected {n}")

        clean = val[~np.isnan(val)]
        if len(clean) == 0:
            # All NaN is constant
            dropped.append(name)
            continue

        v_min = np.nanmin(val)
        v_max = np.nanmax(val)

        if v_min == v_max:
            dropped.append(name)
            continue

        # Normalise
        norm = (val - v_min) / (v_max - v_min)
        norm = np.where(np.isnan(norm), 0.5, norm)

        direction = directions.get(name, 1)
        if direction == -1:
            oriented = 1.0 - norm
        else:
            oriented = norm

        oriented_components[name] = oriented
        used.append(name)

    if not used:
        raise ValueError("No valid non-constant comfort components to combine")

    # Calculate weighted index
    weighted_sum = np.zeros(n, dtype=np.float64)
    total_w = 0.0

    for name in used:
        w = float(weights.get(name, 1.0))
        if w <= 0:
            raise ValueError(f"Weight for component '{name}' must be greater than 0, got {w}")
        weighted_sum += w * oriented_components[name]
        total_w += w

    if total_w <= 0:
        raise ValueError("Sum of component weights must be greater than 0")

    index = 100.0 * weighted_sum / total_w
    return index, used, dropped
