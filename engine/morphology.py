# -*- coding: utf-8 -*-
"""Pure-geometry urban morphology metrics.

All functions operate on plain coordinate arrays (no qgis imports), so they
are unit-testable anywhere. Polygon rings are (k, 2) arrays; closed or open
rings are both accepted (closure is normalized internally).
"""
from __future__ import annotations

import math

import numpy as np


def _closed(ring: np.ndarray) -> np.ndarray:
    ring = np.asarray(ring, dtype=np.float64)
    if not np.array_equal(ring[0], ring[-1]):
        ring = np.vstack([ring, ring[0]])
    return ring


def ring_area(ring: np.ndarray) -> float:
    """Unsigned shoelace area."""
    r = _closed(ring)
    x, y = r[:, 0], r[:, 1]
    return abs(float(np.dot(x[:-1], y[1:]) - np.dot(x[1:], y[:-1]))) / 2.0


def ring_perimeter(ring: np.ndarray) -> float:
    r = _closed(ring)
    d = np.diff(r, axis=0)
    return float(np.hypot(d[:, 0], d[:, 1]).sum())


def convex_hull(points: np.ndarray) -> np.ndarray:
    """Andrew's monotone chain. Returns hull vertices CCW (open ring)."""
    pts = np.unique(np.asarray(points, dtype=np.float64), axis=0)
    if len(pts) <= 2:
        return pts
    pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(tuple(p))
    for p in pts[::-1]:
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(tuple(p))
    return np.asarray(lower[:-1] + upper[:-1], dtype=np.float64)


def min_rotated_rect(points: np.ndarray):
    """Minimum-area rotated rectangle via rotating calipers on the hull.

    Returns (length, width, orientation_deg) with length >= width and
    orientation in [0, 180) measured from the +x axis of the long side.
    """
    hull = convex_hull(points)
    if len(hull) == 1:
        return 0.0, 0.0, 0.0
    if len(hull) == 2:
        d = hull[1] - hull[0]
        return float(np.hypot(*d)), 0.0, math.degrees(math.atan2(d[1], d[0])) % 180.0
    best = (math.inf, 0.0, 0.0, 0.0)  # area, len, wid, angle
    edges = np.diff(np.vstack([hull, hull[0]]), axis=0)
    for ex, ey in edges:
        norm = math.hypot(ex, ey)
        if norm == 0:
            continue
        ux, uy = ex / norm, ey / norm
        # element-wise rotation; avoids BLAS-backed @ for portability
        rot = np.empty_like(hull)
        rot[:, 0] = hull[:, 0] * ux + hull[:, 1] * uy
        rot[:, 1] = -hull[:, 0] * uy + hull[:, 1] * ux
        w = rot[:, 0].max() - rot[:, 0].min()
        h = rot[:, 1].max() - rot[:, 1].min()
        area = w * h
        if area < best[0]:
            ang = math.degrees(math.atan2(uy, ux))
            if w >= h:
                best = (area, w, h, ang % 180.0)
            else:
                best = (area, h, w, (ang + 90.0) % 180.0)
    return best[1], best[2], best[3]


def shape_metrics(exterior: np.ndarray, interiors=()) -> dict:
    """Standard building-form metrics for one polygon.

    ``exterior``: outer ring; ``interiors``: iterable of inner rings.
    Returns area (net of courtyards), perimeter (exterior), IPQ compactness,
    convexity, rectangularity, elongation, orientation, courtyard area and
    index, fractal dimension and corner count.
    """
    ext_area = ring_area(exterior)
    court = float(sum(ring_area(r) for r in interiors))
    area = max(ext_area - court, 0.0)
    perim = ring_perimeter(exterior)
    hull = convex_hull(exterior)
    hull_area = ring_area(hull) if len(hull) >= 3 else 0.0
    length, width, orientation = min_rotated_rect(exterior)
    mrr_area = length * width

    ipq = 4.0 * math.pi * area / (perim * perim) if perim > 0 else 0.0
    convexity = ext_area / hull_area if hull_area > 0 else 0.0
    rectangularity = ext_area / mrr_area if mrr_area > 0 else 0.0
    elongation = 1.0 - (width / length) if length > 0 else 0.0
    fractal = (2.0 * math.log(perim / 4.0) / math.log(ext_area)
               if perim > 4.0 and ext_area > 1.0 else 0.0)

    return {
        "area": area,
        "perimeter": perim,
        "ipq": ipq,
        "convexity": convexity,
        "rectangularity": rectangularity,
        "elongation": elongation,
        "orientation": orientation,
        "mrr_length": length,
        "mrr_width": width,
        "courtyard_area": court,
        "courtyard_index": court / ext_area if ext_area > 0 else 0.0,
        "fractal_dimension": fractal,
        "corners": corner_count(exterior),
    }


def corner_count(ring: np.ndarray, min_deflection_deg: float = 10.0) -> int:
    """Vertices whose direction change exceeds the threshold."""
    r = _closed(ring)[:-1]
    k = len(r)
    if k < 3:
        return 0
    count = 0
    for i in range(k):
        a, b, c = r[i - 1], r[i], r[(i + 1) % k]
        v1 = b - a
        v2 = c - b
        n1, n2 = np.hypot(*v1), np.hypot(*v2)
        if n1 == 0 or n2 == 0:
            continue
        ang = math.degrees(abs(math.atan2(v1[0] * v2[1] - v1[1] * v2[0],
                                          float(np.dot(v1, v2)))))
        if ang >= min_deflection_deg:
            count += 1
    return count


# --------------------------------------------------------------------------- #
# Street-network morphology (Boeing 2019)
# --------------------------------------------------------------------------- #
def orientation_entropy(bearings_deg, lengths=None, bins: int = 36):
    """Length-weighted street-orientation entropy and orientation order.

    Bearings are made bidirectional (theta and theta+180). Returns
    (entropy_nats, orientation_order) where order follows Boeing (2019):
    ``phi = 1 - ((H - Hg) / (Hmax - Hg)) ** 2`` with Hg = ln(4) for a perfect
    grid and Hmax = ln(bins); phi is clamped to [0, 1].
    """
    b = np.asarray(bearings_deg, dtype=np.float64) % 360.0
    w = np.ones_like(b) if lengths is None else np.asarray(lengths, dtype=np.float64)
    both = np.concatenate([b, (b + 180.0) % 360.0])
    weights = np.concatenate([w, w])
    # Center the first bin on 0 degrees, as in Boeing (2019).
    half = 360.0 / bins / 2.0
    shifted = (both + half) % 360.0
    hist, _ = np.histogram(shifted, bins=bins, range=(0.0, 360.0), weights=weights)
    total = hist.sum()
    if total <= 0:
        return 0.0, 0.0
    p = hist / total
    p = p[p > 0]
    entropy = float(-(p * np.log(p)).sum())
    h_max = math.log(bins)
    h_grid = math.log(4)
    if h_max <= h_grid:
        return entropy, 0.0
    phi = 1.0 - ((entropy - h_grid) / (h_max - h_grid)) ** 2
    return entropy, float(min(1.0, max(0.0, phi)))


def meshedness(num_nodes: int, num_edges: int, num_components: int = 1) -> dict:
    """Classic planar-graph connectivity indices (alpha, beta, gamma)."""
    n, e, p = num_nodes, num_edges, max(1, num_components)
    alpha = (e - n + p) / (2 * n - 5) if n >= 3 and (2 * n - 5) > 0 else 0.0
    beta = e / n if n > 0 else 0.0
    gamma = e / (3 * (n - 2)) if n > 2 else 0.0
    return {"alpha": max(0.0, alpha), "beta": beta, "gamma": max(0.0, gamma)}
