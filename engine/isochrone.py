# -*- coding: utf-8 -*-
"""Exact network isochrones (service areas with partial-edge reach).

The classic error of buffer-based service areas is to include or exclude
*whole* street segments: reach actually ends mid-segment, so band polygons
overshoot by up to a full edge length. This module computes, for every edge
of a :class:`engine.graphs.NodeGraph`, exactly *which part* of the edge is
reachable within a cost budget, as intervals of the edge's arc-length
fraction ``t`` in [0, 1] (t = 0 at ``edge_from``, t = 1 at ``edge_to``).

Reach along an edge with endpoint entry costs ``dA``/``dB`` and traversal
cost ``c`` is the union of two linear pieces: ``[0, (cutoff-dA)/c]`` walked
in from the A end and ``[1-(cutoff-dB)/c, 1]`` walked in from the B end;
when the two pieces touch the edge is fully reached (meet-in-the-middle).
Facilities that enter the network mid-edge contribute a third, direct piece
``[t0 - s, t0 + s]`` around their entry point. Cost is assumed to accrue
uniformly along the geometry, so cost fractions equal arc-length fractions.

Everything here is pure NumPy / stdlib - no qgis imports.
"""
from __future__ import annotations

import numpy as np

EPS = 1e-9


# --------------------------------------------------------------------------- #
# Reach fractions per edge (vectorized)
# --------------------------------------------------------------------------- #
def reach_fractions(dist_a, dist_b, edge_cost, cutoff):
    """Per-edge reach from both ends within ``cutoff``.

    ``dist_a``/``dist_b`` are the network costs of ``edge_from``/``edge_to``
    (INF where unreachable), ``edge_cost`` the traversal cost of each edge.

    Returns ``(full, fa, fb)``: ``full`` bool mask (edge entirely covered,
    including meet-in-the-middle), ``fa``/``fb`` the reached arc-length
    fractions from the A / B end in [0, 1] (0 where that end contributes
    nothing). ``fa + fb >= 1`` implies ``full``.
    """
    dist_a = np.asarray(dist_a, dtype=np.float64)
    dist_b = np.asarray(dist_b, dtype=np.float64)
    cost = np.maximum(np.asarray(edge_cost, dtype=np.float64), EPS)
    with np.errstate(invalid="ignore"):
        fa = (cutoff - dist_a) / cost
        fb = (cutoff - dist_b) / cost
    fa = np.clip(np.nan_to_num(fa, nan=-1.0, posinf=-1.0, neginf=-1.0), 0.0, 1.0)
    fb = np.clip(np.nan_to_num(fb, nan=-1.0, posinf=-1.0, neginf=-1.0), 0.0, 1.0)
    full = fa + fb >= 1.0 - EPS
    return full, fa, fb


def edge_intervals(full, fa, fb):
    """Reach intervals of ONE edge from its (full, fa, fb) triple."""
    if full:
        return [(0.0, 1.0)]
    iv = []
    if fa > EPS:
        iv.append((0.0, float(fa)))
    if fb > EPS:
        iv.append((1.0 - float(fb), 1.0))
    return iv


# --------------------------------------------------------------------------- #
# Interval algebra on [0, 1]
# --------------------------------------------------------------------------- #
def merge_intervals(intervals):
    """Union of (lo, hi) pairs, clipped to [0, 1], sorted and merged."""
    clean = []
    for lo, hi in intervals:
        lo, hi = max(0.0, float(lo)), min(1.0, float(hi))
        if hi - lo > EPS:
            clean.append((lo, hi))
    if not clean:
        return []
    clean.sort()
    out = [list(clean[0])]
    for lo, hi in clean[1:]:
        if lo <= out[-1][1] + EPS:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    return [(lo, hi) for lo, hi in out]


def subtract_intervals(a, b):
    """Set difference ``a - b`` of two merged interval lists."""
    if not a:
        return []
    if not b:
        return list(a)
    out = []
    for lo, hi in a:
        pieces = [(lo, hi)]
        for blo, bhi in b:
            nxt = []
            for plo, phi in pieces:
                if bhi <= plo + EPS or blo >= phi - EPS:
                    nxt.append((plo, phi))
                    continue
                if blo > plo + EPS:
                    nxt.append((plo, min(blo, phi)))
                if bhi < phi - EPS:
                    nxt.append((max(bhi, plo), phi))
            pieces = nxt
            if not pieces:
                break
        out.extend(p for p in pieces if p[1] - p[0] > EPS)
    return out


def interval_length(intervals):
    """Total covered fraction of a merged interval list."""
    return float(sum(hi - lo for lo, hi in intervals))


# --------------------------------------------------------------------------- #
# Polyline cutting
# --------------------------------------------------------------------------- #
def _cumlen(coords):
    seg = np.diff(coords, axis=0)
    return np.concatenate([[0.0], np.cumsum(np.hypot(seg[:, 0], seg[:, 1]))])


def point_at(coords, t):
    """Point at arc-length fraction ``t`` of a (k, 2) polyline."""
    coords = np.asarray(coords, dtype=np.float64)
    cum = _cumlen(coords)
    total = cum[-1]
    if total <= EPS:
        return coords[0].copy()
    s = min(max(float(t), 0.0), 1.0) * total
    i = int(np.searchsorted(cum, s, side="right")) - 1
    i = min(max(i, 0), len(coords) - 2)
    seg_len = cum[i + 1] - cum[i]
    u = 0.0 if seg_len <= EPS else (s - cum[i]) / seg_len
    return coords[i] + u * (coords[i + 1] - coords[i])


def cut_polyline(coords, t0, t1):
    """Sub-polyline between arc-length fractions ``t0 < t1``.

    Returns a (m, 2) float array, or ``None`` when the piece degenerates
    (zero length). Interior vertices are preserved.
    """
    coords = np.asarray(coords, dtype=np.float64)
    cum = _cumlen(coords)
    total = cum[-1]
    t0, t1 = max(0.0, float(t0)), min(1.0, float(t1))
    if total <= EPS or t1 - t0 <= EPS:
        return None
    s0, s1 = t0 * total, t1 * total
    pts = [point_at(coords, t0)]
    inside = (cum > s0 + EPS) & (cum < s1 - EPS)
    for i in np.nonzero(inside)[0]:
        pts.append(coords[i])
    pts.append(point_at(coords, t1))
    out = np.asarray(pts, dtype=np.float64)
    keep = [0]
    for i in range(1, len(out)):
        if np.hypot(*(out[i] - out[keep[-1]])) > EPS:
            keep.append(i)
    if len(keep) < 2:
        return None
    return out[keep]


# --------------------------------------------------------------------------- #
# Putting it together: reach of one scope (one facility or all merged)
# --------------------------------------------------------------------------- #
def entry_interval(t0, snap_cost, edge_cost, cutoff):
    """Direct reach piece around a mid-edge entry point.

    ``t0`` = entry fraction along the edge, ``snap_cost`` = cost already
    spent reaching the network (straight-line snap), ``edge_cost`` = the
    edge's traversal cost. Returns one (lo, hi) or None.
    """
    budget = float(cutoff) - float(snap_cost)
    if budget <= EPS:
        return None
    span = budget / max(float(edge_cost), EPS)
    lo, hi = max(0.0, t0 - span), min(1.0, t0 + span)
    if hi - lo <= EPS:
        return None
    return (lo, hi)


def reach_intervals(dist, edge_from, edge_to, edge_cost, cutoff, entries=None):
    """Reached intervals for every edge at one cutoff.

    ``dist``: per-node costs; ``entries``: optional list of
    ``(edge_id, t0, snap_cost)`` mid-edge entry points (facility snaps).
    Returns ``dict edge_id -> merged interval list`` holding only edges
    with any reach.
    """
    full, fa, fb = reach_fractions(
        dist[edge_from], dist[edge_to], edge_cost, cutoff)
    out = {}
    touched = np.nonzero(full | (fa > EPS) | (fb > EPS))[0]
    for e in touched:
        out[int(e)] = edge_intervals(bool(full[e]), float(fa[e]), float(fb[e]))
    if entries:
        extra = {}
        for e, t0, snap in entries:
            piece = entry_interval(t0, snap, edge_cost[e], cutoff)
            if piece is not None:
                extra.setdefault(int(e), []).append(piece)
        for e, pieces in extra.items():
            out[e] = merge_intervals(out.get(e, []) + pieces)
    return out
