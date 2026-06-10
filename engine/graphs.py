# -*- coding: utf-8 -*-
"""Graph construction from polyline geometry.

Two views of a street network:

* :class:`NodeGraph` (primal): junctions are nodes, each input polyline is an
  undirected edge weighted by its length (or a custom cost). Used for OD
  matrices, service areas, accessibility and node/edge centrality.
* :class:`SegmentGraph` (dual): each input polyline is a node; two polylines
  sharing a junction are connected with an *angular* turn cost (Hillier &
  Iida 2005; Turner 2001). Used for space syntax segment angular analysis.

Both are plain CSR-style NumPy arrays so the same code feeds either the
SciPy fast path or the pure-Python Dijkstra fallback.
"""
from __future__ import annotations

import math

import numpy as np


# --------------------------------------------------------------------------- #
# Primal graph
# --------------------------------------------------------------------------- #
class NodeGraph:
    """Undirected weighted graph over polyline endpoints (CSR adjacency)."""

    __slots__ = ("node_xy", "edge_from", "edge_to", "edge_cost", "edge_len",
                 "indptr", "adj_node", "adj_edge", "adj_cost")

    def __init__(self, node_xy, edge_from, edge_to, edge_cost, edge_len):
        self.node_xy = node_xy          # (N, 2) float64
        self.edge_from = edge_from      # (E,) int32 - aligned with input polylines
        self.edge_to = edge_to          # (E,) int32
        self.edge_cost = edge_cost      # (E,) float64 (routing cost)
        self.edge_len = edge_len        # (E,) float64 (metric length)
        self._build_csr()

    @property
    def num_nodes(self) -> int:
        return len(self.node_xy)

    @property
    def num_edges(self) -> int:
        return len(self.edge_from)

    def _build_csr(self):
        n = self.num_nodes
        src = np.concatenate([self.edge_from, self.edge_to])
        dst = np.concatenate([self.edge_to, self.edge_from])
        eid = np.concatenate([np.arange(self.num_edges), np.arange(self.num_edges)])
        cost = np.concatenate([self.edge_cost, self.edge_cost])
        order = np.argsort(src, kind="stable")
        src, dst, eid, cost = src[order], dst[order], eid[order], cost[order]
        counts = np.bincount(src, minlength=n)
        self.indptr = np.concatenate([[0], np.cumsum(counts)]).astype(np.int64)
        self.adj_node = dst.astype(np.int32)
        self.adj_edge = eid.astype(np.int32)
        self.adj_cost = cost.astype(np.float64)

    def degrees(self) -> np.ndarray:
        return np.diff(self.indptr).astype(np.int32)


def polyline_length(coords: np.ndarray) -> float:
    d = np.diff(coords, axis=0)
    return float(np.hypot(d[:, 0], d[:, 1]).sum())


def build_node_graph(polylines, tolerance: float = 0.01, costs=None) -> NodeGraph:
    """Build the primal graph from a list of (k_i, 2) coordinate arrays.

    Endpoints are snapped together when within ``tolerance`` (grid
    quantization). ``costs`` (optional, per polyline) overrides length as the
    routing cost; metric length is always kept for radii/statistics.
    """
    node_index = {}
    node_pts = []

    def node_id(pt):
        key = (round(pt[0] / tolerance), round(pt[1] / tolerance))
        idx = node_index.get(key)
        if idx is None:
            idx = len(node_pts)
            node_index[key] = idx
            node_pts.append((float(pt[0]), float(pt[1])))
        return idx

    e_from, e_to, e_len = [], [], []
    for coords in polylines:
        e_from.append(node_id(coords[0]))
        e_to.append(node_id(coords[-1]))
        e_len.append(polyline_length(coords))

    edge_len = np.asarray(e_len, dtype=np.float64)
    if costs is None:
        edge_cost = edge_len.copy()
    else:
        edge_cost = np.asarray(costs, dtype=np.float64)
        bad = ~np.isfinite(edge_cost) | (edge_cost <= 0)
        edge_cost[bad] = edge_len[bad]
    return NodeGraph(
        np.asarray(node_pts, dtype=np.float64),
        np.asarray(e_from, dtype=np.int32),
        np.asarray(e_to, dtype=np.int32),
        edge_cost,
        edge_len,
    )


def nearest_nodes(graph: NodeGraph, points: np.ndarray) -> np.ndarray:
    """Snap (M, 2) points to their nearest graph node. Returns int32 ids."""
    pts = np.asarray(points, dtype=np.float64)
    try:
        from scipy.spatial import cKDTree
        _, idx = cKDTree(graph.node_xy).query(pts)
        return idx.astype(np.int32)
    except Exception:
        out = np.empty(len(pts), dtype=np.int32)
        nodes = graph.node_xy
        for i, p in enumerate(pts):
            d2 = (nodes[:, 0] - p[0]) ** 2 + (nodes[:, 1] - p[1]) ** 2
            out[i] = int(np.argmin(d2))
        return out


# --------------------------------------------------------------------------- #
# Dual (segment) graph for angular analysis
# --------------------------------------------------------------------------- #
class SegmentGraph:
    """Dual graph: polylines are nodes; shared junctions become edges.

    Edge weights carry **two** costs:

    * ``adj_ang``    - angular cost: junction turn (degrees / 90, so a right
      angle costs 1.0) plus half of each polyline's internal curvature, so a
      full path accumulates exactly the curvature of traversed segments
      (midpoint-to-midpoint convention).
    * ``adj_metric`` - metric cost: half-length of each polyline
      (midpoint-to-midpoint distance), used for radius pruning.
    """

    __slots__ = ("n", "seg_len", "seg_curve", "connectivity",
                 "indptr", "adj_seg", "adj_ang", "adj_metric")

    def __init__(self, n, seg_len, seg_curve, indptr, adj_seg, adj_ang, adj_metric):
        self.n = n
        self.seg_len = seg_len
        self.seg_curve = seg_curve
        self.indptr = indptr
        self.adj_seg = adj_seg
        self.adj_ang = adj_ang
        self.adj_metric = adj_metric
        counts = np.zeros(n, dtype=np.int32)
        # connectivity = number of distinct neighbouring segments
        for s in range(n):
            counts[s] = len(set(adj_seg[indptr[s]:indptr[s + 1]].tolist()))
        self.connectivity = counts


def _bearing(p0, p1) -> float:
    return math.degrees(math.atan2(p1[1] - p0[1], p1[0] - p0[0]))


def _ang_diff(a: float, b: float) -> float:
    """Absolute angular difference in degrees, in [0, 180]."""
    d = abs(a - b) % 360.0
    return 360.0 - d if d > 180.0 else d


def internal_curvature_deg(coords: np.ndarray) -> float:
    """Sum of absolute direction changes along a polyline (degrees)."""
    if len(coords) < 3:
        return 0.0
    total = 0.0
    prev = _bearing(coords[0], coords[1])
    for i in range(1, len(coords) - 1):
        cur = _bearing(coords[i], coords[i + 1])
        total += _ang_diff(prev, cur)
        prev = cur
    return total


def build_segment_graph(polylines, tolerance: float = 0.01) -> SegmentGraph:
    """Build the angular dual graph from a list of (k_i, 2) coordinate arrays."""
    def node_key(pt):
        return (round(pt[0] / tolerance), round(pt[1] / tolerance))

    # ends[node] -> list of (segment id, outward bearing)
    ends = {}
    n = len(polylines)
    seg_len = np.empty(n, dtype=np.float64)
    seg_curve = np.empty(n, dtype=np.float64)
    for s, coords in enumerate(polylines):
        seg_len[s] = polyline_length(coords)
        seg_curve[s] = internal_curvature_deg(coords) / 90.0
        for pt, nxt in ((coords[0], coords[1]), (coords[-1], coords[-2])):
            key = node_key(pt)
            ends.setdefault(key, []).append((s, _bearing(pt, nxt)))

    src, dst, ang, metric = [], [], [], []
    for incident in ends.values():
        m = len(incident)
        if m < 2:
            continue
        for i in range(m):
            s, bs = incident[i]
            for j in range(i + 1, m):
                t, bt = incident[j]
                if s == t:
                    continue  # self loop (closed ring) - no angular edge
                # Travelling through the junction: arrive opposite to one
                # outward bearing, leave along the other.
                turn = _ang_diff(bs + 180.0, bt) / 90.0
                cost_ang = turn + 0.5 * (seg_curve[s] + seg_curve[t])
                cost_met = 0.5 * (seg_len[s] + seg_len[t])
                src.extend((s, t))
                dst.extend((t, s))
                ang.extend((cost_ang, cost_ang))
                metric.extend((cost_met, cost_met))

    src = np.asarray(src, dtype=np.int64)
    order = np.argsort(src, kind="stable")
    counts = np.bincount(src, minlength=n)
    indptr = np.concatenate([[0], np.cumsum(counts)]).astype(np.int64)
    return SegmentGraph(
        n,
        seg_len,
        seg_curve,
        indptr,
        np.asarray(dst, dtype=np.int32)[order],
        np.asarray(ang, dtype=np.float64)[order],
        np.asarray(metric, dtype=np.float64)[order],
    )
