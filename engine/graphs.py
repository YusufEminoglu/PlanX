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
    """Weighted graph over polyline endpoints; optionally directed."""

    __slots__ = ("node_xy", "edge_from", "edge_to", "edge_cost", "edge_rev_cost", "edge_direction", "edge_len",
                 "indptr", "adj_node", "adj_edge", "adj_cost")

    def __init__(self, node_xy, edge_from, edge_to, edge_cost, edge_len,
                 reverse_cost=None, directions=None):
        self.node_xy = node_xy          # (N, 2) float64
        self.edge_from = edge_from      # (E,) int32 - aligned with input polylines
        self.edge_to = edge_to          # (E,) int32
        self.edge_cost = edge_cost      # (E,) float64 (routing cost)
        self.edge_rev_cost = np.asarray(reverse_cost if reverse_cost is not None else edge_cost, dtype=np.float64)
        self.edge_direction = np.asarray(directions if directions is not None else np.zeros(len(edge_from)), dtype=np.int8)
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
        forward = self.edge_direction >= 0
        reverse = self.edge_direction <= 0
        src = np.concatenate([self.edge_from[forward], self.edge_to[reverse]])
        dst = np.concatenate([self.edge_to[forward], self.edge_from[reverse]])
        edge_ids = np.arange(self.num_edges)
        eid = np.concatenate([edge_ids[forward], edge_ids[reverse]])
        cost = np.concatenate([self.edge_cost[forward], self.edge_rev_cost[reverse]])
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


def build_node_graph(polylines, tolerance: float = 0.01, costs=None,
                     reverse_costs=None, directions=None) -> NodeGraph:
    """Build the primal graph from a list of (k_i, 2) coordinate arrays.

    Endpoints are snapped together when within ``tolerance`` (grid
    quantization). ``costs`` (optional, per polyline) overrides length as the
    routing cost; metric length is always kept for radii/statistics.
    ``directions`` uses 0=both, 1=coordinate order only, -1=reverse only.
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
    if reverse_costs is None:
        reverse_costs = edge_cost.copy()
    else:
        reverse_costs = np.asarray(reverse_costs, dtype=np.float64)
        bad = ~np.isfinite(reverse_costs) | (reverse_costs <= 0)
        reverse_costs[bad] = edge_len[bad]
    if directions is None:
        directions = np.zeros(len(edge_len), dtype=np.int8)
    directions = np.asarray(directions, dtype=np.int8)
    if len(directions) != len(edge_len) or np.any(~np.isin(directions, (-1, 0, 1))):
        raise ValueError("directions must contain one -1, 0, or 1 value per polyline")
    return NodeGraph(
        np.asarray(node_pts, dtype=np.float64),
        np.asarray(e_from, dtype=np.int32),
        np.asarray(e_to, dtype=np.int32),
        edge_cost,
        edge_len,
        reverse_costs,
        directions,
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


def weak_component_count(graph: NodeGraph) -> int:
    """How many weak components the graph has, SciPy when it is installed.

    One definition because two callers were building the same CSR by hand:
    the morphology tool inline, and this module's own pure-Python walk. The
    traversal cost is what decides - a 100k-node city is seconds in Python
    and milliseconds in SciPy - while the answer is identical either way, so
    the fast path is tried first and the walk is the fallback rather than a
    second implementation to keep in step.
    """
    try:
        from scipy.sparse import csgraph, csr_matrix
        matrix = csr_matrix((graph.adj_cost, graph.adj_node, graph.indptr),
                            shape=(graph.num_nodes, graph.num_nodes))
        return int(csgraph.connected_components(matrix, directed=False)[0])
    except Exception:
        return weak_components(graph)[1]


def dead_end_branches(graph: NodeGraph, min_length: float = 0.0) -> dict:
    """Label every dead-end branch: the chain hanging behind a degree-1 node.

    A dead-end is a *chain*, not a node. A cul-de-sac is the whole street
    from its junction out to the turning head, and it is that length - not
    the number of tips - that says how far a resident has to drive before
    reaching a through route, and how much of the network's total length is
    carriageway that only ever carries local traffic. Counting degree-1
    nodes sees the tip and misses the street, so the walk below starts at
    each tip and follows the unique continuation through degree-2 nodes
    until it reaches a junction (degree >= 3) or the far tip of a segment
    that touches nothing else.

    Self-loops are dropped from the adjacency: an edge that leaves and
    returns to the same node is not a way out of it, and counting it would
    hand a node a degree of 2 and hide a genuine dead end behind it.

    ``min_length`` is in the same units as the graph's ``edge_len`` - the
    caller's coordinate units, not metres. A branch shorter than it is
    flagged as a stub, which is how under-snapping is told apart from real
    cul-de-sac geometry: a 0.3 m "cul-de-sac" is a digitising gap, not a
    street. Stubs are flagged rather than dropped, so the caller reports
    both readings instead of silently choosing one.

    Returns parallel arrays:

    =============== ========= ==========================================
    ``edge_branch`` (E,) int  branch id, -1 when the edge is not a dead end
    ``edge_depth``  (E,) int  edges between the tip and this edge
    ``node_branch`` (N,) int  branch id for every node on a branch, else -1
    ``degree``      (N,) int  undirected degree
    ``branch_tip``  (B,) int  degree-1 node the walk started from
    ``branch_anchor`` (B,) int junction it ends at, -1 if there is none
    ``branch_length`` (B,) float ground-free length in the same units as edge_len
    ``branch_edges`` (B,) int segment count
    ``branch_stub`` (B,) bool shorter than ``min_length``
    =============== ========= ==========================================
    """
    node_count = graph.num_nodes
    edge_count = graph.num_edges

    adjacency: list[list[tuple[int, int]]] = [[] for _ in range(node_count)]
    for edge_id in range(edge_count):
        start = int(graph.edge_from[edge_id])
        end = int(graph.edge_to[edge_id])
        if start == end:
            continue
        adjacency[start].append((end, edge_id))
        adjacency[end].append((start, edge_id))
    degree = np.fromiter((len(row) for row in adjacency), dtype=np.int32, count=node_count)

    edge_branch = np.full(edge_count, -1, dtype=np.int32)
    edge_depth = np.zeros(edge_count, dtype=np.int32)
    node_branch = np.full(node_count, -1, dtype=np.int32)

    tips, anchors, lengths, counts, stubs = [], [], [], [], []
    for tip in range(node_count):
        if degree[tip] != 1:
            continue
        node, edge_id = adjacency[tip][0]
        if edge_branch[edge_id] >= 0:
            continue  # the far end of a chain another tip already walked
        branch = len(tips)
        node_branch[tip] = branch
        walked, depth = [], 0
        while edge_branch[edge_id] < 0:
            edge_branch[edge_id] = branch
            edge_depth[edge_id] = depth
            node_branch[node] = branch
            walked.append(edge_id)
            if degree[node] != 2:
                break  # a junction, or the tip at the other end of a lone segment
            onward = [item for item in adjacency[node] if item[1] != edge_id]
            if not onward:
                break
            node, edge_id = onward[0]
            depth += 1
        total = float(graph.edge_len[walked].sum())
        tips.append(tip)
        anchors.append(node if degree[node] >= 3 else -1)
        lengths.append(total)
        counts.append(len(walked))
        stubs.append(bool(min_length > 0.0 and total < min_length))

    return {
        "edge_branch": edge_branch,
        "edge_depth": edge_depth,
        "node_branch": node_branch,
        "degree": degree,
        "branch_tip": np.asarray(tips, dtype=np.int32),
        "branch_anchor": np.asarray(anchors, dtype=np.int32),
        "branch_length": np.asarray(lengths, dtype=np.float64),
        "branch_edges": np.asarray(counts, dtype=np.int32),
        "branch_stub": np.asarray(stubs, dtype=bool),
    }


def weak_components(graph: NodeGraph) -> tuple[np.ndarray, int]:
    """Return weak component id per node and the component count."""
    undirected = [[] for _ in range(graph.num_nodes)]
    for left, right in zip(graph.edge_from, graph.edge_to):
        undirected[int(left)].append(int(right))
        undirected[int(right)].append(int(left))
    labels = np.full(graph.num_nodes, -1, dtype=np.int32)
    component = 0
    for root in range(graph.num_nodes):
        if labels[root] >= 0:
            continue
        labels[root] = component
        stack = [root]
        while stack:
            node = stack.pop()
            for neighbor in undirected[node]:
                if labels[neighbor] < 0:
                    labels[neighbor] = component
                    stack.append(neighbor)
        component += 1
    return labels, component


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
