# -*- coding: utf-8 -*-
"""Engine correctness tests against hand-computed graphs.

Run with any Python that has NumPy (e.g. OSGeo4W):
    C:/OSGeo4W/bin/python-qgis-ltr.bat planx/tests/test_engine.py
No qgis imports - pure engine.
"""
from __future__ import annotations

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from planx.engine import (  # noqa: E402
    HAS_SCIPY, air, allocate, centrality, cycling, demo, equity, graphs, hydro, morphology, optimize,
    paths, report, scenario, solar, standards, syntax, walkability,
)

CHECKS = []


def check(label, cond):
    CHECKS.append((label, bool(cond)))
    print(("PASS " if cond else "FAIL ") + label)


def close(a, b, tol=1e-9):
    return abs(a - b) <= tol


# --------------------------------------------------------------------------- #
# 1. Node graph topology
# --------------------------------------------------------------------------- #
# Path A(0,0) - B(1,0) - C(2,0), two unit polylines.
path_lines = [np.array([[0.0, 0.0], [1.0, 0.0]]),
              np.array([[1.0, 0.0], [2.0, 0.0]])]
g = graphs.build_node_graph(path_lines)
check("path graph: 3 nodes, 2 edges", g.num_nodes == 3 and g.num_edges == 2)
check("path graph: degrees [1,2,1]", sorted(g.degrees().tolist()) == [1, 1, 2])

# 2. Dijkstra exactness + scipy/fallback agreement
dist = paths.many_to_many(g.indptr, g.adj_node, g.adj_cost, g.num_nodes, [0])
check("dijkstra path: dist A->C == 2", close(dist[0][2], 2.0) or close(dist[0][1], 2.0))

# build a 5x5 grid with random-ish weights to compare scipy vs heapq
rng = np.random.default_rng(42)
grid_lines = []
for i in range(5):
    for j in range(5):
        if i < 4:
            grid_lines.append(np.array([[i, j], [i + 1, j]], dtype=float))
        if j < 4:
            grid_lines.append(np.array([[i, j], [i, j + 1]], dtype=float))
gw = graphs.build_node_graph(grid_lines, costs=rng.uniform(0.5, 2.0, len(grid_lines)))
src = [0, 7, 13]
d_fast = paths.many_to_many(gw.indptr, gw.adj_node, gw.adj_cost, gw.num_nodes, src)
ms_fast = paths.multi_source(gw.indptr, gw.adj_node, gw.adj_cost, gw.num_nodes, src)
_orig = paths.HAS_SCIPY
paths.HAS_SCIPY = False
d_slow = paths.many_to_many(gw.indptr, gw.adj_node, gw.adj_cost, gw.num_nodes, src)
ms_slow = paths.multi_source(gw.indptr, gw.adj_node, gw.adj_cost, gw.num_nodes, src)
paths.HAS_SCIPY = _orig
check("scipy availability detected", HAS_SCIPY)
check("many_to_many: scipy == pure fallback", np.allclose(d_fast, d_slow))
check("multi_source dist: scipy == pure fallback", np.allclose(ms_fast[0], ms_slow[0]))
check("multi_source labels agree (same nearest source)",
      np.array_equal(
          np.where(np.isfinite(ms_fast[0]), ms_fast[1], -1),
          np.where(np.isfinite(ms_slow[0]), ms_slow[1], -1)))

# --------------------------------------------------------------------------- #
# 3. Betweenness on hand-computed graphs
# --------------------------------------------------------------------------- #
node_bc, edge_bc, _ = centrality.brandes_betweenness(
    g.indptr, g.adj_node, g.adj_cost, g.num_nodes,
    adj_edge=g.adj_edge, num_edges=g.num_edges)
# Pair convention: divide raw by 2. Only pair (A, C) crosses B.
b_node = int(np.argmax(g.degrees()))
check("path graph: betweenness(B) == 1 pair", close(node_bc[b_node] / 2.0, 1.0))
check("path graph: endpoints betweenness == 0",
      close(sum(node_bc) - node_bc[b_node], 0.0))
check("path graph: each edge lies on 2 pairs", np.allclose(edge_bc / 2.0, [2.0, 2.0]))

# Star: center + 4 leaves -> 6 leaf pairs through center.
star_lines = [np.array([[0.0, 0.0], [math.cos(a), math.sin(a)]])
              for a in (0.0, 1.5, 3.0, 4.5)]
gs = graphs.build_node_graph(star_lines)
nbc, _, _ = centrality.brandes_betweenness(gs.indptr, gs.adj_node, gs.adj_cost, gs.num_nodes)
center = int(np.argmax(gs.degrees()))
check("star graph: betweenness(center) == 6 pairs", close(nbc[center] / 2.0, 6.0))

# Closeness on the star (unit edges): center farness = 4 -> WF closeness:
clo = centrality.closeness_straightness(gs.indptr, gs.adj_node, gs.adj_cost,
                                        gs.num_nodes, node_xy=gs.node_xy)
check("star: center reach == 4", close(clo["reach"][center], 4.0))
check("star: center closeness == 1.0 (WF)", close(clo["closeness"][center], 1.0))
check("star: leaf farness == 1 + 3*2 == 7",
      close(clo["farness"][1 - (center == 1)], 7.0))
check("star: center harmonic == 4", close(clo["harmonic"][center], 4.0))
check("star: center straightness == 1 (radial lines)",
      close(clo["straightness"][center], 1.0, 1e-6))

# Radius-limited closeness: on the path graph radius 1 sees only neighbours.
clo_r = centrality.closeness_straightness(g.indptr, g.adj_node, g.adj_cost,
                                          g.num_nodes, radius=1.0)
check("path radius=1: B reaches exactly 2", close(clo_r["reach"][b_node], 2.0))

# Sampling scales to ~exact on a symmetric graph (all sources = exact).
nbc_s, _, _ = centrality.brandes_betweenness(
    gs.indptr, gs.adj_node, gs.adj_cost, gs.num_nodes,
    sources=list(range(gs.num_nodes)))
check("sampling with all sources == exact", np.allclose(nbc_s, nbc))

# --------------------------------------------------------------------------- #
# 4. Segment graph / space syntax
# --------------------------------------------------------------------------- #
# Three collinear unit segments: all angular costs 0.
coll = [np.array([[0.0, 0.0], [1.0, 0.0]]),
        np.array([[1.0, 0.0], [2.0, 0.0]]),
        np.array([[2.0, 0.0], [3.0, 0.0]])]
sg = graphs.build_segment_graph(coll)
check("collinear: connectivity [1,2,1]", sorted(sg.connectivity.tolist()) == [1, 1, 2])
res = syntax.segment_angular_analysis(sg)
mid = int(np.argmax(sg.connectivity))
check("collinear: NC == 3 everywhere", np.allclose(res["nc"], 3.0))
check("collinear: TD == 0 (no turns)", np.allclose(res["td"], 0.0))
check("collinear: choice(mid) == 1 pair", close(res["choice"][mid], 1.0))
check("collinear: NACH(mid) == log10(2)/log10(3)",
      close(res["nach"][mid], math.log10(2.0) / math.log10(3.0), 1e-9))
check("collinear: NAIN == 5^1.2 / 2", np.allclose(res["nain"], (5.0 ** 1.2) / 2.0))

# Right angle: two segments meeting at 90 degrees -> angular cost 1.
corner = [np.array([[0.0, 0.0], [1.0, 0.0]]),
          np.array([[1.0, 0.0], [1.0, 1.0]])]
sgc = graphs.build_segment_graph(corner)
resc = syntax.segment_angular_analysis(sgc)
check("right angle: TD == 1 for both segments", np.allclose(resc["td"], 1.0))

# Straight continuation through a junction costs 0 even with a third arm.
tee = [np.array([[0.0, 0.0], [1.0, 0.0]]),
       np.array([[1.0, 0.0], [2.0, 0.0]]),
       np.array([[1.0, 0.0], [1.0, 1.0]])]
sgt = graphs.build_segment_graph(tee)
rest = syntax.segment_angular_analysis(sgt)
# segment 0: depth to 1 = 0 (straight), to 2 = 1 (turn) -> TD = 1
check("tee: TD(west arm) == 1", close(rest["td"][0], 1.0))
check("tee: TD(north arm) == 2 (two turns)", close(rest["td"][2], 2.0))

# Metric radius pruning: with radius 1 the collinear ends see only the middle.
res_r = syntax.segment_angular_analysis(sg, radius=1.0)
check("collinear radius=1: NC(end) == 2", close(res_r["nc"][0], 2.0))
check("collinear radius=1: NC(mid) == 3", close(res_r["nc"][mid], 3.0))

# Internal curvature: an L-shaped *single* polyline carries its bend.
bent = [np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]),
        np.array([[1.0, 1.0], [1.0, 2.0]])]
sgb = graphs.build_segment_graph(bent)
check("internal curvature counted (90 deg == 1.0)",
      close(sgb.seg_curve[0], 1.0) and close(sgb.seg_curve[1], 0.0))
# Edge cost = junction turn (0, straight) + half curvatures = 0.5
resb = syntax.segment_angular_analysis(sgb)
check("bent polyline: TD includes half-curvature convention",
      np.allclose(resb["td"], 0.5))

# parse_radii
check("parse_radii('400, 800, n')", syntax.parse_radii("400, 800, n") == [400.0, 800.0, None])

# --------------------------------------------------------------------------- #
# 5. Morphology
# --------------------------------------------------------------------------- #
square = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=float)
m = morphology.shape_metrics(square)
check("square: area 1, perimeter 4", close(m["area"], 1.0) and close(m["perimeter"], 4.0))
check("square: IPQ == pi/4", close(m["ipq"], math.pi / 4.0, 1e-9))
check("square: convexity == 1", close(m["convexity"], 1.0, 1e-9))
check("square: rectangularity == 1", close(m["rectangularity"], 1.0, 1e-9))
check("square: elongation == 0", close(m["elongation"], 0.0, 1e-9))
check("square: 4 corners", m["corners"] == 4)

rect = np.array([[0, 0], [4, 0], [4, 1], [0, 1]], dtype=float)
mr = morphology.shape_metrics(rect)
check("4x1 rect: elongation == 0.75", close(mr["elongation"], 0.75, 1e-9))
check("4x1 rect: orientation == 0", close(mr["orientation"], 0.0, 1e-6))

theta = math.radians(30.0)
c, s = math.cos(theta), math.sin(theta)
rect_rot = np.column_stack([
    rect[:, 0] * c - rect[:, 1] * s,
    rect[:, 0] * s + rect[:, 1] * c
])
mrot = morphology.shape_metrics(rect_rot)
check("rotated rect: orientation == 30", close(mrot["orientation"], 30.0, 1e-6))

# L-shape: concave -> convexity < 1
lshape = np.array([[0, 0], [2, 0], [2, 1], [1, 1], [1, 2], [0, 2]], dtype=float)
ml = morphology.shape_metrics(lshape)
check("L-shape: area == 3", close(ml["area"], 3.0))
check("L-shape: convexity == 3/3.5", close(ml["convexity"], 3.0 / 3.5, 1e-9))

# Courtyard: 4x4 square with 2x2 hole
outer = np.array([[0, 0], [4, 0], [4, 4], [0, 4]], dtype=float)
hole = np.array([[1, 1], [3, 1], [3, 3], [1, 3]], dtype=float)
mc = morphology.shape_metrics(outer, [hole])
check("courtyard: net area 12", close(mc["area"], 12.0))
check("courtyard index == 4/16", close(mc["courtyard_index"], 0.25))

# Orientation entropy: perfect grid -> order ~1; uniform -> order ~0
bearings_grid = np.array([0.0, 90.0] * 50)
h_g, order_g = morphology.orientation_entropy(bearings_grid)
check("grid bearings: entropy == ln 4", close(h_g, math.log(4.0), 1e-9))
check("grid bearings: orientation order == 1", close(order_g, 1.0, 1e-9))
bearings_uniform = np.arange(0.0, 180.0, 5.0)
h_u, order_u = morphology.orientation_entropy(bearings_uniform)
check("uniform bearings: entropy == ln 36", close(h_u, math.log(36.0), 1e-9))
check("uniform bearings: orientation order == 0", close(order_u, 0.0, 1e-9))

# Meshedness: a tree has alpha == 0
mesh_tree = morphology.meshedness(10, 9, 1)
check("tree: alpha == 0", close(mesh_tree["alpha"], 0.0))
mesh_grid = morphology.meshedness(25, 40, 1)
check("5x5 grid: alpha == 16/45", close(mesh_grid["alpha"], 16.0 / 45.0, 1e-9))

# Convex hull + min rect basics
hull = morphology.convex_hull(np.array([[0, 0], [1, 0], [1, 1], [0, 1], [0.5, 0.5]]))
check("convex hull drops interior point", len(hull) == 4)

# --------------------------------------------------------------------------- #
# 6. Solar / microclimate
# --------------------------------------------------------------------------- #
# Equator, March equinox, solar noon -> sun nearly overhead.
alt, az = solar.sun_position(2026, 3, 20, 12.0, 0.0, 0.0)
check("equinox equator noon: altitude > 87", alt > 87.0)

# London (51.5N, 0E), June solstice noon UTC: altitude ~ 90-51.5+23.44 = 61.9
alt, az = solar.sun_position(2026, 6, 21, 12.0, 51.5, 0.0)
check("london solstice noon: altitude ~ 61.9", abs(alt - 61.9) < 1.0)
check("london solstice noon: azimuth ~ 180", abs(az - 180.0) < 4.0)

# Izmir (38.42N, 27.14E), winter solstice noon local solar time
# (UTC ~ 10.2h): altitude ~ 90-38.42-23.44 = 28.1
alt, az = solar.sun_position(2026, 12, 21, 12.0 - 27.14 / 15.0, 38.42, 27.14)
check("izmir winter noon: altitude ~ 28.1", abs(alt - 28.1) < 1.0)

# Morning sun rises in the east.
alt, az = solar.sun_position(2026, 6, 21, 5.0, 51.5, 0.0)
check("london solstice morning: azimuth < 120 (east)", 0.0 < az < 120.0)

# Shadow casting: 10 m tower on a flat plane, sun from the south at 45 deg
# -> shadow extends exactly 10 m (10 px at 1 m pixels) due north.
dsm = np.zeros((40, 40))
dsm[20, 20] = 10.0
sh = solar.shadow_mask(dsm, 45.0, 180.0, pixel_size=1.0)
check("tower shadow: 10 cells north shadowed",
      all(sh[20 - i, 20] for i in range(1, 10)))
check("tower shadow: 12 m north is lit", not sh[8, 20])
check("tower shadow: nothing south/east/west",
      not sh[21, 20] and not sh[20, 21] and not sh[20, 19] and not sh[25, 25])
sh_low = solar.shadow_mask(dsm, 26.5651, 180.0, pixel_size=1.0)  # tan = 0.5
check("low sun: shadow reaches ~20 m", sh_low[2, 20] and not sh_low[20, 25])
check("sun below horizon: everything shadowed",
      solar.shadow_mask(dsm, -5.0, 180.0, 1.0).all())
sh_west = solar.shadow_mask(dsm, 45.0, 270.0, pixel_size=1.0)
check("western sun: shadow points east", sh_west[20, 25] and not sh_west[20, 15])

# SVF: flat plane -> 1 everywhere; foot of a long wall -> about 0.5.
flat = np.zeros((30, 30))
svf_flat = solar.sky_view_factor(flat, 1.0, directions=8, max_radius=10.0)
check("SVF flat == 1", np.allclose(svf_flat, 1.0))
wall = np.zeros((40, 40))
wall[:, 20] = 200.0  # very tall north-south wall
svf_wall = solar.sky_view_factor(wall, 1.0, directions=16, max_radius=15.0)
check("SVF at the foot of a tall wall ~ 0.5", abs(svf_wall[20, 21] - 0.5) < 0.08)
check("SVF far from wall ~ 1", svf_wall[20, 38] > 0.9)

# Frontal width: 10x20 rectangle, wind from north -> width 10; from west -> 20.
rect_fp = np.array([[0, 0], [10, 0], [10, 20], [0, 20]], dtype=float)
check("frontal width, north wind == 10",
      close(solar.projected_width(rect_fp, 0.0), 10.0, 1e-9))
check("frontal width, west wind == 20",
      close(solar.projected_width(rect_fp, 270.0), 20.0, 1e-9))
check("frontal width, 45 deg wind == (10+20)/sqrt(2)",
      close(solar.projected_width(rect_fp, 45.0), 30.0 / math.sqrt(2.0), 1e-9))

# --------------------------------------------------------------------------- #
# 7. Plan standards
# --------------------------------------------------------------------------- #
stds = standards.parse_standards("green=10, Education = 4; health=1.5")
check("parse_standards: 3 entries", stds == [("green", 10.0), ("education", 4.0), ("health", 1.5)])
check("match contains, case-insensitive",
      standards.match_standard("Urban GREEN Area", stds) == ("green", 10.0))
check("no match -> None", standards.match_standard("Industry", stds) == (None, None))
try:
    standards.parse_standards("green:10")
    check("malformed standards raise", False)
except ValueError:
    check("malformed standards raise", True)

rows = standards.balance_rows(
    {"Green Area": 2000.0, "School Site": 1000.0, "Industry": 500.0},
    population=100.0, standards=standards.parse_standards("green=10, school=4"))
by_cat = {r["category"]: r for r in rows}
check("balance: green surplus 1000",
      close(by_cat["Green Area"]["balance_m2"], 1000.0)
      and by_cat["Green Area"]["status"] == "Meets standard")
check("balance: per-capita actual 20", close(by_cat["Green Area"]["m2_per_capita"], 20.0))
check("balance: no standard for industry", by_cat["Industry"]["status"] == "No standard")
rows_deficit = standards.balance_rows(
    {"Green Area": 2000.0}, population=1000.0,
    standards=standards.parse_standards("green=10"))
check("balance: deficit -8000",
      close(rows_deficit[0]["balance_m2"], -8000.0)
      and rows_deficit[0]["status"] == "Deficit")

# --------------------------------------------------------------------------- #
# 8. Performance report
# --------------------------------------------------------------------------- #
a_sum = report.access_summary([100.0, 50.0, 0.0, 100.0])
check("access summary: mean 62.5, median 75",
      close(a_sum["mean"], 62.5) and close(a_sum["median"], 75.0))
check("access summary: 50% full, 25% low",
      close(a_sum["share_full"], 50.0) and close(a_sum["share_low"], 25.0))

bal_rows = [
    {"category": "Green", "status": "Meets standard", "balance_m2": 500.0,
     "area_m2": 2500.0, "m2_per_capita": 12.5, "required_m2": 2000.0},
    {"category": "School", "status": "Deficit", "balance_m2": -800.0,
     "area_m2": 0.0, "m2_per_capita": 0.0, "required_m2": 800.0},
    {"category": "Industry", "status": "No standard", "balance_m2": 0.0,
     "area_m2": 900.0, "m2_per_capita": 4.5, "required_m2": 0.0},
]
b_sum = report.balance_summary(bal_rows)
check("balance summary: 2 with std, 1 deficit, 50% compliance",
      b_sum["n_with_standard"] == 2 and b_sum["n_deficit"] == 1
      and close(b_sum["compliance_pct"], 50.0))
check("balance summary: worst is School -800",
      b_sum["worst_category"] == "School" and close(b_sum["worst_deficit_m2"], -800.0))
check("balance summary: no standards -> compliance None",
      report.balance_summary([bal_rows[2]])["compliance_pct"] is None)

q_sum = report.adequacy_summary(
    [{"facility": "West", "capacity": 60.0, "assigned": 80.0,
      "utilization": 1.333, "status": "Overloaded"},
     {"facility": "East", "capacity": 100.0, "assigned": 40.0,
      "utilization": 0.4, "status": "Adequate"},
     {"facility": "Spare", "capacity": 50.0, "assigned": 0.0,
      "utilization": 0.0, "status": "Unused"}],
    [{"covered": 1, "pop": 30.0}, {"covered": 1, "pop": 50.0},
     {"covered": 0, "pop": 20.0}])
check("adequacy summary: covered 80%",
      close(q_sum["covered_share"], 80.0) and close(q_sum["covered_pop"], 80.0))
check("adequacy summary: 1 overloaded 1 unused, mean util of used",
      q_sum["n_overloaded"] == 1 and q_sum["n_unused"] == 1
      and close(q_sum["mean_utilization"], (1.333 + 0.4) / 2.0, 1e-9))
check("adequacy summary: pop defaults to 1",
      close(report.adequacy_summary([], [{"covered": 1}, {"covered": 0}])
            ["covered_share"], 50.0))

d_sum = report.density_summary([10.0, 30.0, 20.0])
check("density summary: mean 20 max 30",
      close(d_sum["mean"], 20.0) and close(d_sum["max"], 30.0))

check("overall score == mean of components",
      close(report.overall_score(a_sum, b_sum, q_sum), (62.5 + 50.0 + 80.0) / 3.0))
check("overall score None when nothing", report.overall_score() is None)

check("ramp endpoints red->green",
      report.ramp_color(0.0) == "#d64541" and report.ramp_color(1.0) == "#27ae60"
      and report.ramp_color(0.5) == "#f5b041")

cards = report.report_cards(a_sum, b_sum, q_sum, d_sum)
check("5 cards with index first",
      len(cards) == 5 and cards[0]["label"] == "Plan Performance Index"
      and cards[0]["value"] == "64")
check("compliance card flags worst deficit",
      "School" in cards[2]["sub"] and cards[2]["tone"] == "bad")

html_doc = report.build_html(
    "Test <Plan>", population=2000.0,
    access={"scores": [100.0, 50.0, 0.0, 100.0],
            "points": [(0, 0), (100, 0), (0, 100), (100, 100)]},
    balance=bal_rows,
    adequacy={"facilities": [{"facility": "West", "capacity": 60.0,
                              "assigned": 80.0, "utilization": 1.333,
                              "status": "Overloaded"}],
              "demand": [{"covered": 1, "pop": 10.0}]},
    density={"values": [10.0, 30.0]}, plugin_version="v9.9.9")
check("html: escaped title + all sections",
      "Test &lt;Plan&gt;" in html_doc
      and "Accessibility - 15-Minute City" in html_doc
      and "Land-Use Balance vs Standards" in html_doc
      and "Facility Adequacy" in html_doc
      and "<h2>Density</h2>" in html_doc)
check("html: charts inline (3+ svg) and self-contained",
      html_doc.count("<svg") >= 3 and "http" not in html_doc.split("xmlns")[0]
      and "v9.9.9" in html_doc)
check("html: badges for statuses",
      "Overloaded" in html_doc and "Deficit" in html_doc)

check("svg map empty for no points", report.svg_point_map([], []) == "")
svg_map = report.svg_point_map([(0, 0), (10, 10)], [0.0, 100.0])
check("svg map: 2 circles, red and green",
      svg_map.count("<circle") == 2 and "#d64541" in svg_map and "#27ae60" in svg_map)
check("svg map thins to max_points",
      report.svg_point_map([(i, i) for i in range(50)], [50.0] * 50,
                           max_points=10).count("<circle") == 10)
check("balance bars skip no-standard rows",
      report.svg_balance_bars(bal_rows).count("<text x=\"0\"") == 2)

# --------------------------------------------------------------------------- #
# 9. Facility-location optimization
# --------------------------------------------------------------------------- #
# Demand at positions 0..4 on a line; candidates at the same positions.
LINE = np.abs(np.arange(5)[:, None] - np.arange(5)[None, :]).astype(float)
ones = np.ones(5)

cw = optimize.coverage_weights(LINE, ones, radius=1.0)
check("screening weights on line == [2,3,3,3,2]",
      cw.tolist() == [2.0, 3.0, 3.0, 3.0, 2.0])

mc = optimize.greedy_max_coverage(LINE, ones, p=2, radius=1.0)
check("greedy coverage picks [1, 3] with gains [3, 2]",
      mc["selected"] == [1, 3] and mc["gains"] == [3.0, 2.0])
check("greedy coverage covers everything", mc["covered"].all()
      and close(mc["covered_weight"], 5.0) and close(mc["total_weight"], 5.0))
check("greedy coverage stops early when saturated",
      optimize.greedy_max_coverage(LINE, ones, p=5, radius=1.0)["selected"] == [1, 3])

w_heavy = np.array([10.0, 1.0, 1.0, 1.0, 1.0])
check("weighted coverage chases the heavy demand",
      optimize.greedy_max_coverage(LINE, w_heavy, p=1, radius=1.0)["selected"] == [1])

mc_fixed = optimize.greedy_max_coverage(LINE, ones, p=1, radius=1.0, fixed=[1])
check("coverage with fixed=1 picks 3 (gain 2)",
      mc_fixed["selected"] == [3] and mc_fixed["gains"] == [2.0]
      and close(mc_fixed["covered_weight"], 5.0))

# p-median: weighted 1-median sits at the heavy end.
pm1 = optimize.p_median(LINE, np.array([1.0, 1.0, 1.0, 1.0, 10.0]), p=1)
check("1-median with heavy tail == node 4, objective 10",
      pm1["selected"] == [4] and close(pm1["objective"], 10.0))

# Greedy trap: greedy picks the middle first (objective 50); Teitz-Bart
# substitution must find the optimum {0, 20} (objective 40).
TRAP = np.abs(np.array([0.0, 10.0, 20.0])[:, None]
              - np.array([0.0, 10.0, 20.0])[None, :])
w_trap = np.array([5.0, 4.0, 5.0])
pm2 = optimize.p_median(TRAP, w_trap, p=2)
check("Teitz-Bart escapes the greedy trap (objective 40, swaps >= 1)",
      sorted(pm2["selected"]) == [0, 2] and close(pm2["objective"], 40.0)
      and pm2["swaps"] >= 1)

pm_fixed = optimize.p_median(LINE, ones, p=1, fixed=[0])
check("p-median with existing at 0 adds node 3",
      pm_fixed["selected"] == [3] and close(pm_fixed["objective"], 3.0))

# Unreachable demand: penalty applied, assignment flags it.
D_INF = np.array([[0.0, 5.0, np.inf], [5.0, 0.0, np.inf]])
pm_inf = optimize.p_median(D_INF, np.array([1.0, 1.0, 4.0]), p=1)
check("p-median penalty = 1.5 x max finite", close(pm_inf["penalty"], 7.5))
assign, cost = optimize.assign_to_nearest(D_INF, [0, 1])
check("assignment flags unreachable as -1",
      assign.tolist() == [0, 1, -1] and cost.tolist() == [0.0, 0.0, -1.0])
assign2, cost2 = optimize.assign_to_nearest(LINE, [1, 3])
check("assignment to nearest of {1,3}",
      assign2.tolist() == [0, 0, 0, 1, 1] and cost2.tolist() == [1.0, 0.0, 1.0, 0.0, 1.0])

try:
    optimize.greedy_max_coverage(np.empty((0, 3)), np.ones(3), p=1, radius=1.0)
    check("empty candidates raise", False)
except ValueError:
    check("empty candidates raise", True)

# --------------------------------------------------------------------------- #
# 10. Eigenvector centrality (v2.5)
# --------------------------------------------------------------------------- #
# Path A-B-C: eigen of P3 -> center 1, ends 1/sqrt(2).
eig_path = centrality.eigenvector(g.indptr, g.adj_node, g.num_nodes)
deg_path = g.degrees()
mid = int(np.argmax(deg_path))
ends = [i for i in range(3) if i != mid]
check("eigenvector P3: center == 1", close(eig_path[mid], 1.0, 1e-6))
check("eigenvector P3: ends == 1/sqrt(2)",
      close(eig_path[ends[0]], 1.0 / math.sqrt(2.0), 1e-6)
      and close(eig_path[ends[1]], 1.0 / math.sqrt(2.0), 1e-6))

# Star K1,4: center 1, leaves 0.5 (lambda = 2).
star_lines = [np.array([[0.0, 0.0], [1.0, 0.0]]),
              np.array([[0.0, 0.0], [-1.0, 0.0]]),
              np.array([[0.0, 0.0], [0.0, 1.0]]),
              np.array([[0.0, 0.0], [0.0, -1.0]])]
gs = graphs.build_node_graph(star_lines)
eig_star = centrality.eigenvector(gs.indptr, gs.adj_node, gs.num_nodes)
hub = int(np.argmax(gs.degrees()))
check("eigenvector star: hub == 1", close(eig_star[hub], 1.0, 1e-6))
leaf_vals = [eig_star[i] for i in range(gs.num_nodes) if i != hub]
check("eigenvector star: leaves == 0.5",
      all(close(v, 0.5, 1e-6) for v in leaf_vals))
check("eigenvector empty graph", centrality.eigenvector(
    np.zeros(1, dtype=np.int64), np.zeros(0, dtype=np.int64), 0).size == 0)

# --------------------------------------------------------------------------- #
# 11. Sun hours and clear-sky irradiation (v2.5)
# --------------------------------------------------------------------------- #
flat10 = np.zeros((10, 10))
hrs_flat, daylight = solar.sun_hours(flat10, 1.0, 2026, 6, 21, 0.0, 0.0, 0.0,
                                     interval_min=60.0)
check("sun hours flat: every cell == site daylight",
      np.allclose(hrs_flat, daylight))
check("sun hours equator June: ~12 h daylight", 10.0 <= daylight <= 14.0)

tower_dsm = np.zeros((30, 30))
tower_dsm[15, 15] = 30.0
hrs_t, day_t = solar.sun_hours(tower_dsm, 1.0, 2026, 6, 21, 0.0, 40.0, 0.0,
                               interval_min=60.0)
check("sun hours: cells beside the tower lose sun vs far corner (lat 40N)",
      hrs_t[14, 15] < hrs_t[2, 2] and hrs_t[15, 17] < hrs_t[2, 2])
check("sun hours: tower top keeps full daylight",
      close(hrs_t[15, 15], day_t, 1e-9))

b0, d0 = solar.clear_sky_irradiance(-5.0, 172)
check("clear sky: sun below horizon -> 0", b0 == 0.0 and d0 == 0.0)
b90, d90 = solar.clear_sky_irradiance(90.0, 172)
check("clear sky zenith: beam 800-1100 W/m2, diffuse smaller",
      800.0 <= b90 <= 1100.0 and 0.0 < d90 < b90)
b30, _ = solar.clear_sky_irradiance(30.0, 172)
check("clear sky: beam grows with altitude", b30 < b90)

kwh_flat, kwh_ref = solar.daily_irradiation(flat10, 1.0, 2026, 6, 21, 0.0,
                                            38.0, 27.0, interval_min=60.0)
check("irradiation flat: all cells == flat reference",
      np.allclose(kwh_flat, kwh_ref) and kwh_ref > 3.0)
kwh_dec, kwh_dec_ref = solar.daily_irradiation(flat10, 1.0, 2026, 12, 21, 0.0,
                                               38.0, 27.0, interval_min=60.0)
check("irradiation: June > December at 38N", kwh_ref > kwh_dec_ref > 0.0)
svf_half = np.full((10, 10), 0.5)
kwh_svf, _ = solar.daily_irradiation(flat10, 1.0, 2026, 6, 21, 0.0, 38.0, 27.0,
                                     interval_min=60.0, svf=svf_half)
check("irradiation: SVF 0.5 cuts the diffuse share",
      float(kwh_svf.mean()) < float(kwh_flat.mean()))

# --------------------------------------------------------------------------- #
# 12. Heat island risk index (v2.5)
# --------------------------------------------------------------------------- #
r_hot = solar.heat_risk_index(1.0, 0.0, 0.0, 20.0)
r_cool = solar.heat_risk_index(0.0, 1.0, 0.0, 0.0)
check("heat risk: fully built at h_ref == 100", close(float(r_hot), 100.0))
check("heat risk: fully green == 0", close(float(r_cool), 0.0))
check("heat risk: empty flat cell == 100/3 (default weights)",
      close(float(solar.heat_risk_index(0.0, 0.0, 0.0, 0.0)), 100.0 / 3.0, 1e-9))
r_arr = solar.heat_risk_index(np.array([0.8, 0.8]), np.array([0.0, 0.5]),
                              np.zeros(2), np.array([10.0, 10.0]))
check("heat risk: green cover lowers the score", r_arr[1] < r_arr[0])
check("heat risk: height capped at h_ref",
      close(float(solar.heat_risk_index(1.0, 0.0, 0.0, 60.0)), 100.0))

# --------------------------------------------------------------------------- #
# 13. Distributional equity (v2.6)
# --------------------------------------------------------------------------- #
check("gini [1,2,3,4] == 0.25", close(equity.gini([1, 2, 3, 4]), 0.25))
check("gini all-equal == 0", close(equity.gini([5, 5, 5, 5]), 0.0))
check("gini [20,20,80,80] == 0.3", close(equity.gini([20, 20, 80, 80]), 0.3))
check("gini weighted == unweighted when weights equal",
      close(equity.gini([20, 20, 80, 80]),
            equity.gini([20, 20, 80, 80], [3, 3, 3, 3])))
# weighted Gini must equal the O(n^2) mean-difference definition exactly
rng_eq = np.random.default_rng(7)
xx = rng_eq.uniform(0.0, 100.0, 40)
ww = rng_eq.uniform(1.0, 50.0, 40)
mu_w = (ww * xx).sum() / ww.sum()
md = (ww[:, None] * ww[None, :] * np.abs(xx[:, None] - xx[None, :])).sum() / ww.sum() ** 2
check("weighted gini == mean-difference / (2*mu)",
      close(equity.gini(xx, ww), md / (2.0 * mu_w), 1e-9))
check("theil all-equal == 0", close(equity.theil_t([4, 4, 4]), 0.0))
check("theil [0,2] == ln 2", close(equity.theil_t([0, 2]), math.log(2.0)))
# Theil additive decomposition: T = T_between + T_within
g_lab = np.array(["N", "N", "S", "S"])
t_tot, t_btw, t_wth, per_g = equity.theil_decomposition(
    [20, 20, 80, 80], [100, 100, 100, 100], g_lab)
check("theil decomposition adds up (T = between + within)",
      close(t_tot, t_btw + t_wth, 1e-9))
check("theil fully between when groups are homogeneous",
      close(t_wth, 0.0) and t_btw > 0.0)
check("theil per-group means 20 and 80",
      close(per_g["N"]["mean"], 20.0) and close(per_g["S"]["mean"], 80.0))
check("weighted median of [20,20,80,80] in range",
      20.0 <= equity.weighted_quantile([20, 20, 80, 80], 0.5) <= 80.0)
check("p90/p10 of [20,20,80,80] == 4",
      close(equity.percentile_ratio([20, 20, 80, 80]), 4.0))
pr = equity.percentile_rank([20, 20, 80, 80])
check("percentile rank mid-rank for ties (lows 0.25, highs 0.75)",
      close(float(pr[0]), 0.25) and close(float(pr[2]), 0.75))
check("cv all-equal == 0", close(equity.coefficient_of_variation([7, 7, 7]), 0.0))
check("share_below 50 of [20,20,80,80] == 0.5",
      close(equity.share_below([20, 20, 80, 80], 50.0), 0.5))
check("share_above 50 of [20,20,80,80] == 0.5",
      close(equity.share_above([20, 20, 80, 80], 50.0), 0.5))
check("equity handles empty weights gracefully",
      close(equity.gini([1, 2, 3], [0, 0, 0]), 0.0))

# --------------------------------------------------------------------------- #
# 14. Capacitated allocation (v2.6)
# --------------------------------------------------------------------------- #
D_cap = np.array([[1.0, 2.0, 3.0], [5.0, 6.0, 7.0]])
rc = optimize.capacitated_assign(D_cap, [10, 10, 10], [15, 100])
check("capacitated: p0->F0, p1/p2 spill to F1 (F0 full)",
      rc["assign"].tolist() == [0, 1, 1])
check("capacitated: spill flags [F,T,T]",
      rc["spilled"].tolist() == [False, True, True])
check("capacitated: nearest is F0 for all", rc["nearest"].tolist() == [0, 0, 0])
check("capacitated: loads [10, 20]",
      close(float(rc["load"][0]), 10.0) and close(float(rc["load"][1]), 20.0))
check("capacitated: remaining [5, 80]",
      close(float(rc["remaining"][0]), 5.0) and close(float(rc["remaining"][1]), 80.0))
rc2 = optimize.capacitated_assign(D_cap, [10, 10, 10], [15, 100], max_cost=4.0)
check("capacitated max_cost: only p0 served (F1 out of reach)",
      rc2["assign"].tolist() == [0, -1, -1])
check("capacitated max_cost: p1/p2 still report nearest F0",
      rc2["nearest"].tolist() == [0, 0, 0])
rc3 = optimize.capacitated_assign(D_cap, [10, 10, 10], [0, 0])
check("capacitated: zero capacity -> all uncovered",
      rc3["assign"].tolist() == [-1, -1, -1])

# --------------------------------------------------------------------------- #
# 15. Land-use allocation (v2.7)
# --------------------------------------------------------------------------- #
check("parse_targets basic",
      allocate.parse_targets("A=10, b=20.5") == [("a", 10.0), ("b", 20.5)])
suit_a = np.array([[9.0, 1.0], [8.0, 2.0], [2.0, 8.0], [1.0, 9.0]])
area_a = np.array([100.0, 100.0, 100.0, 100.0])
res_a = allocate.allocate_land_use(suit_a, area_a, [200.0, 100.0])
# best 2 for use 0 = parcels 0,1; best 1 for use 1 = parcel 3; parcel 2 left over
check("allocate basic: assign [0,0,-1,1]", res_a["assign"].tolist() == [0, 0, -1, 1])
check("allocate basic: objective 2600", close(res_a["objective"], 2600.0))
check("allocate basic: allocated [200,100]",
      close(float(res_a["allocated"][0]), 200.0)
      and close(float(res_a["allocated"][1]), 100.0))
check("allocate basic: counts [2,1]", res_a["n_parcels"].tolist() == [2, 1])
# greedy trap: reassignment alone is stuck (no room), a SWAP reaches optimum
suit_t = np.array([[10.0, 8.0], [9.0, 1.0]])
res_t = allocate.allocate_land_use(suit_t, np.array([10.0, 10.0]), [10.0, 10.0])
check("allocate swap-trap: optimal assign [1,0]", res_t["assign"].tolist() == [1, 0])
check("allocate swap-trap: objective 170", close(res_t["objective"], 170.0))
check("allocate swap-trap: a swap was applied", res_t["swaps"] >= 1)
# locked parcel is fixed and consumes its use's target
res_l = allocate.allocate_land_use(suit_a, area_a, [200.0, 100.0],
                                   locked=np.array([-1, -1, 1, -1]))
check("allocate locked: p2 fixed to use 1, p0/p1 -> use 0, p3 left over",
      res_l["assign"].tolist() == [0, 0, 1, -1])
check("allocate locked: objective 2500", close(res_l["objective"], 2500.0))
# shortfall: a target larger than the available area soaks every parcel
res_s = allocate.allocate_land_use(suit_a, area_a, [1000.0, 0.0])
check("allocate shortfall: use 0 takes all 400 (< 1000 target)",
      close(float(res_s["allocated"][0]), 400.0) and (res_s["assign"] >= 0).all())
# non-negative good: negative suitability is clipped to 0
res_n = allocate.allocate_land_use(np.array([[-5.0]]), np.array([10.0]), [10.0])
check("allocate clips negative suitability to 0", close(res_n["objective"], 0.0))

# --------------------------------------------------------------------------- #
# 16. Multi-objective land-use allocation (v2.8)
# --------------------------------------------------------------------------- #
# two adjacent parcels (shared edge L=10); each slightly prefers a different
# use by suitability, but compactness can make them cluster.
suit_m = np.array([[10.0, 9.0], [9.0, 10.0]])
area_m = np.array([1.0, 1.0])
edges_m = [(0, 1, 10.0)]
res_m0 = allocate.allocate_multi(suit_m, area_m, [2.0, 2.0], edges_m, np.zeros((2, 2)))
check("multi no-spatial == pure suitability split [0,1]",
      res_m0["assign"].tolist() == [0, 1]
      and res_m0["assign"].tolist()
      == allocate.allocate_land_use(suit_m, area_m, [2.0, 2.0])["assign"].tolist())
check("multi no-spatial: spatial_score 0", close(res_m0["spatial_score"], 0.0))
res_mc = allocate.allocate_multi(suit_m, area_m, [2.0, 2.0], edges_m,
                                 np.array([[5.0, 0.0], [0.0, 5.0]]))
check("multi compactness: adjacent parcels cluster into one use",
      res_mc["assign"][0] == res_mc["assign"][1])
check("multi compactness: objective 69 (suit 19 + spatial 50)",
      close(res_mc["objective"], 69.0) and close(res_mc["spatial_score"], 50.0))
# three parcels in a row; use 1 fits once. An adjacency penalty between the
# two uses should push use 1 to an END (one border) not the MIDDLE (two).
suit_r = np.array([[5.0, 5.0], [5.0, 6.0], [5.0, 5.0]])
area_r = np.array([1.0, 1.0, 1.0])
edges_r = [(0, 1, 10.0), (1, 2, 10.0)]
res_r0 = allocate.allocate_multi(suit_r, area_r, [2.0, 1.0], edges_r, np.zeros((2, 2)))
check("multi no rule: use 1 sits in the middle (suitability greedy)",
      res_r0["assign"].tolist() == [0, 1, 0])
res_r = allocate.allocate_multi(suit_r, area_r, [2.0, 1.0], edges_r,
                                np.array([[0.0, -1.0], [-1.0, 0.0]]))
check("multi adjacency penalty: use 1 pushed to an end, not the middle",
      res_r["assign"][1] == 0 and list(res_r["assign"]).count(1) == 1)
check("multi adjacency: objective 5 (suit 15 - one penalised 10 m border)",
      close(res_r["objective"], 5.0))

# --------------------------------------------------------------------------- #
# 17. Annual solar potential (v2.9)
# --------------------------------------------------------------------------- #
ann = solar.annual_irradiation(flat10, 1.0, 2026, 0.0, 38.0, 27.0,
                               interval_min=60.0)
check("annual: 12 months swept", ann["months"] == list(range(1, 13)))
check("annual: 12 monthly maps + 12 means",
      len(ann["monthly"]) == 12 and len(ann["month_mean"]) == 12)
check("annual flat: every cell == flat-ground annual reference",
      np.allclose(ann["annual"], ann["flat_annual"]))
check("annual == sum of the 12 monthly maps",
      np.allclose(ann["annual"], sum(ann["monthly"])))
check("annual flat == sum of the 12 flat-month totals",
      close(ann["flat_annual"], sum(ann["flat_monthly"]), 1e-6))
check("annual flat at 38N is physically plausible (kWh/m2/yr)",
      800.0 < ann["flat_annual"] < 4000.0)
check("annual: June outshines December at 38N",
      ann["month_mean"][5] > ann["month_mean"][11] > 0.0)
# keep_monthly=False drops the arrays but still returns the means
ann_nm = solar.annual_irradiation(flat10, 1.0, 2026, 0.0, 38.0, 27.0,
                                  interval_min=60.0, keep_monthly=False)
check("annual keep_monthly=False: maps dropped, means kept, totals match",
      ann_nm["monthly"] is None and len(ann_nm["month_mean"]) == 12
      and close(ann_nm["flat_annual"], ann["flat_annual"], 1e-9))
# a single-month subset equals that month's contribution
ann_jun = solar.annual_irradiation(flat10, 1.0, 2026, 0.0, 38.0, 27.0,
                                   interval_min=60.0, months=[6])
check("annual months=[6]: only June swept",
      ann_jun["months"] == [6] and len(ann_jun["monthly"]) == 1)
check("annual months=[6] == June slice of the full run",
      close(ann_jun["flat_annual"], ann["flat_monthly"][5], 1e-6)
      and np.allclose(ann_jun["annual"], ann["monthly"][5]))
# a half-open sky cuts the diffuse share of the annual total
ann_svf = solar.annual_irradiation(flat10, 1.0, 2026, 0.0, 38.0, 27.0,
                                   interval_min=60.0, svf=np.full((10, 10), 0.5))
check("annual: SVF 0.5 lowers the scene total vs full sky",
      float(ann_svf["annual"].mean()) < float(ann["annual"].mean()))
# shadowing: at 40N the noon sun is due south, so the tower's shadow falls on
# its NORTH side (smaller rows) - those cells lose annual sun vs the far field.
ann_t = solar.annual_irradiation(tower_dsm, 1.0, 2026, 0.0, 40.0, 0.0,
                                 interval_min=60.0)
check("annual: shaded cell north of tower < open far field",
      ann_t["annual"][14, 15] < ann_t["annual"][2, 2])
check("annual: tower top reaches the scene maximum",
      close(float(ann_t["annual"][15, 15]),
            float(np.nanmax(ann_t["annual"])), 1e-6))
# NaN DSM cells stay NaN while valid cells are computed
dsm_nan = np.array([[0.0, 0.0, np.nan], [0.0, 5.0, 0.0], [0.0, 0.0, 0.0]])
ann_nan = solar.annual_irradiation(dsm_nan, 1.0, 2026, 0.0, 38.0, 27.0,
                                   interval_min=120.0)["annual"]
check("annual: NaN DSM cell stays NaN, valid cells finite & positive",
      np.isnan(ann_nan[0, 2]) and np.isfinite(ann_nan[1, 1])
      and ann_nan[1, 1] > 0.0)
# days-in-month respects leap years
check("days in month: 2024 Feb == 29 (leap), 2026 Feb == 28",
      solar._days_in_month(2024, 2) == 29 and solar._days_in_month(2026, 2) == 28)
check("days in month: Apr 30, Jul 31, 2000 Feb 29, 1900 Feb 28",
      solar._days_in_month(2026, 4) == 30 and solar._days_in_month(2026, 7) == 31
      and solar._days_in_month(2000, 2) == 29 and solar._days_in_month(1900, 2) == 28)

# --------------------------------------------------------------------------- #
# 18. Land-use Pareto front (v2.10)
# --------------------------------------------------------------------------- #
# pure-objective helpers on hand-built arrays (both objectives maximised)
pm = allocate.pareto_mask([40.0, 25.0, 20.0, 38.0], [0.0, 1.0, 2.0, 1.0])
check("pareto_mask: (25,1) is dominated by (38,1); the other three survive",
      pm.tolist() == [True, False, True, True])
pm2 = allocate.pareto_mask([40.0, 38.0, 20.0], [0.0, 1.0, 2.0])
check("pareto_mask: a concave trade-off keeps all three points",
      pm2.tolist() == [True, True, True])
check("knee: the bulging middle point (38,1) is the knee",
      allocate._knee_index([40.0, 38.0, 20.0], [0.0, 1.0, 2.0], pm2) == 1)
check("knee: a two-point front has no knee (-1)",
      allocate._knee_index([40.0, 20.0], [0.0, 2.0],
                           np.array([True, True])) == -1)
check("same-use boundary: blocked A,A,B,B counts both inner edges, interleave 0",
      close(allocate._same_use_boundary(
            [0, 0, 1, 1], [(0, 1, 1.0), (1, 2, 1.0), (2, 3, 1.0)]), 2.0)
      and close(allocate._same_use_boundary(
            [0, 1, 0, 1], [(0, 1, 1.0), (1, 2, 1.0), (2, 3, 1.0)]), 0.0))

# a 4-parcel line: pure suitability wants the interleaved A,B,A,B (suit 40,
# compactness 0); compactness wants the blocked A,A,B,B (suit 20, compactness
# 2) - a genuine trade-off the sweep must trace.
psuit = np.array([[10.0, 0.0], [0.0, 10.0], [10.0, 0.0], [0.0, 10.0]])
pedges = [(0, 1, 1.0), (1, 2, 1.0), (2, 3, 1.0)]
pf = allocate.pareto_front(psuit, [1.0, 1.0, 1.0, 1.0], [2.0, 2.0], pedges,
                           weights=[0.0, 5.0, 12.0, 20.0])
check("pareto front: zero weight gives the max-suitability interleaving (40, 0)",
      close(pf["suit"][0], 40.0) and close(pf["compact"][0], 0.0))
check("pareto front: a high weight trades suitability for compactness (20, 2)",
      close(pf["suit"][-1], 20.0) and close(pf["compact"][-1], 2.0))
check("pareto front: suitability never beats the unconstrained best (40)",
      float(pf["suit"].max()) <= 40.0 + 1e-9)
check("pareto front: both extremes lie on the non-dominated front",
      bool(pf["on_front"][0]) and bool(pf["on_front"][-1]))
check("pareto front: one assignment per weight, all 4 parcels long",
      len(pf["assign"]) == 4 and all(len(a) == 4 for a in pf["assign"]))
check("pareto front: the high-weight run is the blocked (compact) allocation",
      close(allocate._same_use_boundary(pf["assign"][-1], pedges), 2.0))

# --------------------------------------------------------------------------- #
# 19. Atkinson index & Lorenz / concentration curves (v2.11)
# --------------------------------------------------------------------------- #
check("atkinson: perfect equality is 0 at any aversion",
      close(equity.atkinson_index([5, 5, 5, 5], epsilon=1.0), 0.0)
      and close(equity.atkinson_index([5, 5, 5, 5], epsilon=2.0), 0.0))
check("atkinson: zero aversion (epsilon 0) is always 0",
      close(equity.atkinson_index([1, 2, 3, 4], epsilon=0.0), 0.0))
check("atkinson: epsilon=1 is the geometric-mean gap (1-sqrt(2)/1.5)",
      close(equity.atkinson_index([1, 2], epsilon=1.0), 1 - (2 ** 0.5) / 1.5, 1e-6))
check("atkinson: epsilon=2 is the harmonic-mean gap (1-(4/3)/1.5)",
      close(equity.atkinson_index([1, 2], epsilon=2.0), 1 - (4 / 3) / 1.5, 1e-6))
check("atkinson: more aversion never lowers the index",
      equity.atkinson_index([1, 2], epsilon=2.0)
      > equity.atkinson_index([1, 2], epsilon=1.0) > 0.0)
check("atkinson: a zero value collapses the index to 1 when epsilon>=1",
      close(equity.atkinson_index([0, 1, 2], epsilon=1.0), 1.0)
      and close(equity.atkinson_index([0, 1, 2], epsilon=1.5), 1.0))
check("atkinson: a zero value is finite when epsilon<1",
      0.0 < equity.atkinson_index([0, 1, 2], epsilon=0.5) < 1.0)

pop_eq, val_eq = equity.lorenz_points([4, 4, 4, 4])
check("lorenz: equality lies on the diagonal (gini 0)",
      close(equity.gini_from_lorenz(pop_eq, val_eq), 0.0))
pp, ll = equity.lorenz_points([1, 2, 3, 4])
check("lorenz: curve runs from (0,0) to (1,1)",
      close(pp[0], 0.0) and close(ll[0], 0.0)
      and close(pp[-1], 1.0) and close(ll[-1], 1.0))
check("lorenz: an unequal curve sags below the line of equality",
      bool(np.all(ll <= pp + 1e-12)) and bool(np.all(np.diff(ll) >= -1e-12)))
check("lorenz: trapezoidal gini == the mean-difference gini (0.25)",
      close(equity.gini_from_lorenz(pp, ll), 0.25, 1e-9)
      and close(equity.gini_from_lorenz(pp, ll), equity.gini([1, 2, 3, 4]), 1e-9))
check("concentration: ordered by its own value, equals the Gini",
      close(equity.concentration_index([1, 2, 3, 4], rank=[1, 2, 3, 4]),
            equity.gini([1, 2, 3, 4]), 1e-9))
check("concentration: value falling with rank gives a negative index",
      equity.concentration_index([4, 3, 2, 1], rank=[1, 2, 3, 4]) < 0.0)
check("lorenz: population weights shift the curve (gini stays in [0,1))",
      0.0 <= equity.gini_from_lorenz(
          *equity.lorenz_points([1, 2, 3, 4], w=[10, 1, 1, 1])) < 1.0)


# --------------------------------------------------------------------------- #
# 20. Capacitated Facility Siting (Phase A1)
# --------------------------------------------------------------------------- #
# 6 nodes. Candidates: 0 (Site X), 1 (Site Y). Demand points at 2, 3, 4, 5.
# w = [10, 10, 10, 10].
# Site X is at dist 1 to all demand points.
# Site Y is at dist 2 to all demand points.
# Capacity of X = 20, Capacity of Y = 40.
dist_siting = np.array([
    [1.0, 1.0, 1.0, 1.0],  # Candidate 0 (Site X)
    [2.0, 2.0, 2.0, 2.0]   # Candidate 1 (Site Y)
])
demand_w = np.array([10.0, 10.0, 10.0, 10.0])
capacities = np.array([20.0, 40.0])

res_siting = optimize.capacitated_siting(dist_siting, demand_w, capacities, p=1)
check("capacitated siting: selected facility is Y (index 1)", res_siting["selected"] == [1])
check("capacitated siting: served demand is 40", close(res_siting["obj_history"][-1][0], 40.0))
check("capacitated siting: load of Y is 40", close(res_siting["load"][1], 40.0))
check("capacitated siting: load of X is 0", close(res_siting["load"][0], 0.0))


# --------------------------------------------------------------------------- #
# 21. Hard contiguity (Phase A2)
# --------------------------------------------------------------------------- #
# 4x4 parcel grid, indices 0..15.
# Suitability: Use 0 has high suitability at corners 0 and 15.
# Use 1 has moderate suitability elsewhere.
suit = np.zeros((16, 2))
# Use 0 suitability
suit[0, 0] = 10.0
suit[15, 0] = 10.0
# Use 1 suitability
for p in range(16):
    if p not in (0, 15):
        suit[p, 1] = 5.0
        suit[p, 0] = 1.0  # low suitability for Use 0
    else:
        suit[p, 1] = 1.0

# Parcel areas: all 10.0
area = np.full(16, 10.0)
# Targets: Use 0 = 20.0 (2 parcels), Use 1 = 140.0 (14 parcels)
targets = np.array([20.0, 140.0])

# Edges for 4x4 grid
edges = []
for r in range(4):
    for c in range(4):
        p = r * 4 + c
        if c < 3:
            edges.append((p, p + 1, 1.0))
        if r < 3:
            edges.append((p, p + 4, 1.0))

# Run standard non-contiguous allocation
res_soft = allocate.allocate_land_use(suit, area, targets)
adj = [[] for _ in range(16)]
for i, j, length in edges:
    adj[i].append((j, length))
    adj[j].append((i, length))

soft_connected = allocate.check_connectivity(0, res_soft["assign"], adj)
check("soft allocation splits Use 0", not soft_connected)

# Run contiguous allocation
res_hard = allocate.allocate_contiguous(suit, area, targets, edges)
hard_connected_0 = allocate.check_connectivity(0, res_hard["assign"], adj)
hard_connected_1 = allocate.check_connectivity(1, res_hard["assign"], adj)
check("hard allocation yields connected Use 0", hard_connected_0)
check("hard allocation yields connected Use 1", hard_connected_1)
check("hard allocation area target 0 met", close(res_hard["allocated"][0], 20.0))
check("hard allocation area target 1 met", close(res_hard["allocated"][1], 140.0))


# --------------------------------------------------------------------------- #
# 22. Equity cross-tabs (Phase B1)
# --------------------------------------------------------------------------- #
# Values 1,2,3,4; group A holds the two lowest, group B the two highest.
xt = equity.crosstab([1.0, 2.0, 3.0, 4.0], [0, 0, 1, 1], n_classes=2)
check("crosstab: halves edge at the weighted median 2.5",
      len(xt["edges"]) == 1 and close(xt["edges"][0], 2.5))
check("crosstab: classes are [0,0,1,1]",
      xt["class_of"].tolist() == [0, 0, 1, 1])
check("crosstab: cells put all of A low / all of B high",
      xt["cells"].tolist() == [[2.0, 0.0], [0.0, 2.0]])
check("crosstab: A is 2x over-represented in the low class",
      close(xt["rep_ratio"][0, 0], 2.0) and close(xt["rep_ratio"][0, 1], 0.0))
check("crosstab: complete separation -> dissimilarity 1 for both",
      close(xt["dissimilarity"][0], 1.0) and close(xt["dissimilarity"][1], 1.0))
check("crosstab: value shares 0.3 (A) / 0.7 (B)",
      close(xt["value_share"][0], 3.0 / 10.0)
      and close(xt["value_share"][1], 7.0 / 10.0))
check("crosstab: per-group gini matches equity.gini",
      close(xt["gini"][0], equity.gini([1.0, 2.0]))
      and close(xt["gini"][1], equity.gini([3.0, 4.0])))
check("crosstab: per-group means 1.5 / 3.5",
      close(xt["mean"][0], 1.5) and close(xt["mean"][1], 3.5))

# Identical distributions -> dissimilarity 0, rep ratios 1.
xt_same = equity.crosstab([1.0, 4.0, 1.0, 4.0], [0, 0, 1, 1], n_classes=2)
check("crosstab: identical group distributions -> dissimilarity 0",
      close(xt_same["dissimilarity"][0], 0.0)
      and close(xt_same["dissimilarity"][1], 0.0))
check("crosstab: identical distributions -> all rep ratios 1",
      np.allclose(xt_same["rep_ratio"], 1.0))

# Custom breaks + population weights: one heavy low-value unit dominates.
xt_brk = equity.crosstab([10.0, 90.0], [0, 1], w=[9.0, 1.0], breaks=[50.0])
check("crosstab: custom break keeps 2 classes",
      xt_brk["cells"].shape == (2, 2))
check("crosstab: weighted pop shares 0.9 / 0.1",
      close(xt_brk["pop_share"][0], 0.9) and close(xt_brk["pop_share"][1], 0.1))
check("crosstab: weighted value share of the heavy group 0.5",
      close(xt_brk["value_share"][0], 0.5))

# --------------------------------------------------------------------------- #
# 23. Scenario snapshots + comparison (Phase B2)
# --------------------------------------------------------------------------- #
m_a = scenario.metrics_from_summaries(
    access={"n": 4, "mean": 60.0, "median": 62.0, "share_full": 25.0,
            "share_low": 50.0},
    balance={"compliance_pct": 66.0, "n_deficit": 1, "n_with_standard": 3},
    adequacy={"covered_share": 80.0, "covered_pop": 80.0, "total_pop": 100.0,
              "n_facilities": 2, "n_overloaded": 1, "n_unused": 0,
              "mean_utilization": 0.9},
    overall=70.0)
check("scenario: summaries flatten to metric keys",
      close(m_a["access_mean"], 60.0)
      and close(m_a["standards_compliance_pct"], 66.0)
      and close(m_a["covered_share"], 80.0)
      and close(m_a["plan_performance_index"], 70.0))
check("scenario: missing density -> no density metrics",
      "density_mean" not in m_a)

m_b = dict(m_a)
m_b["access_mean"] = 75.0          # higher is better -> B wins
m_b["access_share_low"] = 20.0     # lower is better -> B wins
m_b["standards_deficits"] = 2.0    # lower is better -> A wins
snap_a = scenario.snapshot("Plan A", m_a, generated="t0")
snap_b = scenario.snapshot("Plan B", m_b, generated="t1")
round_trip = scenario.from_json(scenario.to_json(snap_a))
check("scenario: JSON round-trip keeps name and metrics",
      round_trip["name"] == "Plan A"
      and close(round_trip["metrics"]["access_mean"], 60.0))

rows = scenario.compare(snap_a, snap_b)
by_key = {r["key"]: r for r in rows}
check("scenario: higher-better improvement credited to B",
      by_key["access_mean"]["better"] == "B"
      and close(by_key["access_mean"]["delta"], 15.0)
      and close(by_key["access_mean"]["delta_pct"], 25.0))
check("scenario: lower-better improvement credited to B",
      by_key["access_share_low"]["better"] == "B"
      and close(by_key["access_share_low"]["delta"], -30.0))
check("scenario: lower-better worsening credited to A",
      by_key["standards_deficits"]["better"] == "A")
check("scenario: unchanged metric is a tie",
      by_key["covered_share"]["better"] == "tie")
check("scenario: neutral direction stays n/a",
      by_key["total_pop"]["better"] == "n/a")

only_a = scenario.snapshot("A", {"access_mean": 10.0})
only_b = scenario.snapshot("B", {"origins": 5.0})
part = {r["key"]: r for r in scenario.compare(only_a, only_b)}
check("scenario: one-sided metrics have no delta and stay n/a",
      part["access_mean"]["delta"] is None
      and part["access_mean"]["better"] == "n/a"
      and part["origins"]["a"] is None)

verdict = scenario.score_line(rows, "Plan A", "Plan B")
check("scenario: verdict counts B 2 wins / A 1 win",
      "Plan B" in verdict and "wins 2" in verdict and "wins 1" in verdict)

cmp_html = report.build_compare_html("Cmp", rows, "Plan A", "Plan B",
                                     verdict=verdict)
check("report: compare page carries both scenario names and the table",
      "Plan A" in cmp_html and "Plan B" in cmp_html
      and "Scenario Comparison" in cmp_html
      and "Accessibility score (mean)" in cmp_html)
check("report: compare page marks the B improvement green",
      "#27ae60" in cmp_html)

# --------------------------------------------------------------------------- #
# 24. Shortest-path tree + route reconstruction (Phase C)
# --------------------------------------------------------------------------- #
# Path A(0,0) - B(1,0) - C(2,0): tree from A must find dist [0,1,2] and the
# route A->C = both edges in order.
tree_g = graphs.build_node_graph(path_lines)
dist_t, pred_n, pred_e = paths.shortest_path_tree(
    tree_g.indptr, tree_g.adj_node, tree_g.adj_edge, tree_g.adj_cost,
    tree_g.num_nodes, 0)
check("path tree: distances match Dijkstra", dist_t.tolist() == [0.0, 1.0, 2.0])
nodes_t, edges_t = paths.reconstruct_path(pred_n, pred_e, 0, 2)
check("path tree: route A->C is node 0-1-2 via edges 0,1",
      nodes_t == [0, 1, 2] and edges_t == [0, 1])
check("path tree: source route is trivial",
      paths.reconstruct_path(pred_n, pred_e, 0, 0) == ([0], []))

# Parallel edges: two polylines both joining A(0,0)-B(1,0); the straight one
# (edge 0, len 1) wins on length, the detour (edge 1, len ~2.236) wins once
# custom weights make edge 0 expensive.
par_lines = [np.array([[0.0, 0.0], [1.0, 0.0]]),
             np.array([[0.0, 0.0], [0.5, 1.0], [1.0, 0.0]])]
par_g = graphs.build_node_graph(par_lines)
d0, pn0, pe0 = paths.shortest_path_tree(
    par_g.indptr, par_g.adj_node, par_g.adj_edge, par_g.adj_cost,
    par_g.num_nodes, 0)
check("parallel edges: straight edge chosen by length",
      paths.reconstruct_path(pn0, pe0, 0, 1)[1] == [0])
custom_edge_w = np.array([5.0, 0.5])
w_adj = custom_edge_w[par_g.adj_edge]
d1, pn1, pe1 = paths.shortest_path_tree(
    par_g.indptr, par_g.adj_node, par_g.adj_edge, w_adj,
    par_g.num_nodes, 0)
check("parallel edges: custom weights flip the chosen edge",
      paths.reconstruct_path(pn1, pe1, 0, 1)[1] == [1]
      and close(d1[1], 0.5))

# --------------------------------------------------------------------------- #
# 25. Walkability scoring (Phase C)
# --------------------------------------------------------------------------- #
check("linear_score: increasing maps midpoint to 50",
      close(float(walkability.linear_score([60.0], 0.0, 120.0)[0]), 50.0))
check("linear_score: clamps above full",
      close(float(walkability.linear_score([500.0], 0.0, 120.0)[0]), 100.0))
check("linear_score: decreasing direction (block length)",
      close(float(walkability.linear_score([80.0], 400.0, 80.0)[0]), 100.0)
      and close(float(walkability.linear_score([400.0], 400.0, 80.0)[0]), 0.0)
      and close(float(walkability.linear_score([240.0], 400.0, 80.0)[0]), 50.0))
check("shannon_mix: two equal uses -> 1", close(walkability.shannon_mix([5, 5]), 1.0))
check("shannon_mix: one use -> 0", close(walkability.shannon_mix([7.0]), 0.0))
check("shannon_mix: 3:1 split -> 0.8113",
      close(walkability.shannon_mix([3, 1]), 0.8112781245, 1e-9))

ws_only = walkability.walk_scores([60.0, 120.0])
check("walk_scores: single component -> total equals it",
      close(float(ws_only["total"][0]), 50.0)
      and close(float(ws_only["total"][1]), 100.0))
ws_full = walkability.walk_scores(
    [60.0], mix=[0.5], dest_count=[12.5], block_len=[240.0], slope_pct=[5.0])
check("walk_scores: all components at their midpoint -> 50",
      close(float(ws_full["total"][0]), 50.0))
ws_w = walkability.walk_scores(
    [120.0], mix=[0.0], weights={"intersections": 3.0, "mix": 1.0})
check("walk_scores: custom weights (3:1 of 100 and 0 -> 75)",
      close(float(ws_w["total"][0]), 75.0))
try:
    walkability.walk_scores([1.0], weights={"nope": 1.0})
    check("walk_scores: unknown component raises", False)
except ValueError:
    check("walk_scores: unknown component raises", True)

# --------------------------------------------------------------------------- #
# 26. GTFS transit kernels (Phase D)
# --------------------------------------------------------------------------- #
# Synthetic feed: R1 A->B->C every 30 min 07:00-09:30 (10 min per hop),
# R2 C->D at 08:25 and 09:25 (10 min ride). Weekday service Jan-Dec 2026,
# with 2026-07-07 cancelled by a calendar_dates exception.
import tempfile  # noqa: E402
import zipfile  # noqa: E402

from planx.engine import transit  # noqa: E402


def _write_gtfs_fixture(path):
    def csv_lines(header, rows):
        return "\n".join([header] + [",".join(str(c) for c in r)
                                     for r in rows]) + "\n"

    def hhmm(minutes):
        return f"{minutes // 60:02d}:{minutes % 60:02d}:00"

    r1_starts = [420, 450, 480, 510, 540, 570]  # 07:00 ... 09:30
    trips = [(f"t{i + 1}", "R1", "WK") for i in range(len(r1_starts))]
    trips += [("u1", "R2", "WK"), ("u2", "R2", "WK")]
    st_rows = []
    for i, m0 in enumerate(r1_starts):
        tid = f"t{i + 1}"
        st_rows += [(tid, hhmm(m0), hhmm(m0), "A", 1),
                    (tid, hhmm(m0 + 10), hhmm(m0 + 10), "B", 2),
                    (tid, hhmm(m0 + 20), hhmm(m0 + 20), "C", 3)]
    st_rows += [("u1", hhmm(505), hhmm(505), "C", 1),
                ("u1", hhmm(515), hhmm(515), "D", 2),
                ("u2", hhmm(565), hhmm(565), "C", 1),
                ("u2", hhmm(575), hhmm(575), "D", 2)]
    files = {
        "stops.txt": csv_lines(
            "stop_id,stop_name,stop_lat,stop_lon",
            [("A", "Stop A", 0.0, 0.0), ("B", "Stop B", 0.0, 0.01),
             ("C", "Stop C", 0.0, 0.02), ("D", "Stop D", 0.0, 0.04)]),
        "routes.txt": csv_lines(
            "route_id,route_short_name,route_long_name,route_type",
            [("R1", "1", "Mainline", 3), ("R2", "2", "Branch", 3)]),
        "trips.txt": csv_lines("trip_id,route_id,service_id",
                               [(t, r, s) for (t, r, s) in trips]),
        "stop_times.txt": csv_lines(
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence",
            st_rows),
        "calendar.txt": csv_lines(
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,"
            "sunday,start_date,end_date",
            [("WK", 1, 1, 1, 1, 1, 0, 0, "20260101", "20261231")]),
        "calendar_dates.txt": csv_lines(
            "service_id,date,exception_type", [("WK", "20260707", 2)]),
    }
    with zipfile.ZipFile(path, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return path


check("gtfs: parse_time plain", transit.parse_time("08:30:00") == 30600)
check("gtfs: parse_time past midnight", transit.parse_time("25:10:00") == 90600)
try:
    transit.parse_time("8h30")
    check("gtfs: malformed time raises", False)
except ValueError:
    check("gtfs: malformed time raises", True)

_gtfs_path = os.path.join(tempfile.gettempdir(), "planx_test_gtfs.zip")
_write_gtfs_fixture(_gtfs_path)
feed = transit.read_gtfs(_gtfs_path)
check("gtfs: 4 stops read", feed["stop_ids"] == ["A", "B", "C", "D"])
check("gtfs: 8 trips read", len(feed["trips"]) == 8)

_bad_path = os.path.join(tempfile.gettempdir(), "planx_test_gtfs_bad.zip")
with zipfile.ZipFile(_bad_path, "w") as zf:
    zf.writestr("stops.txt", "stop_id,stop_lat,stop_lon\nA,0,0\n")
try:
    transit.read_gtfs(_bad_path)
    check("gtfs: missing files raise a named error", False)
except ValueError as exc:
    check("gtfs: missing files raise a named error",
          "routes.txt" in str(exc) and "stop_times.txt" in str(exc))

check("gtfs: Monday runs", transit.active_services(feed, "20260706") == {"WK"})
check("gtfs: Sunday empty", transit.active_services(feed, "20260705") == set())
check("gtfs: exception removes 2026-07-07",
      transit.active_services(feed, "20260707") == set())
check("gtfs: first service day is 2026-01-01 (a Thursday)",
      transit.first_service_day(feed) == "20260101")

freq = transit.stop_frequencies(feed, "20260706", window=(7 * 3600, 9 * 3600))
check("gtfs: stop A has 4 departures 07-09",
      int(freq["departures"][0]) == 4)
check("gtfs: headway at A is 30 min", close(freq["headway_min"][0], 30.0))
check("gtfs: C departs only via R2 in the window",
      int(freq["departures"][2]) == 1 and int(freq["n_routes"][2]) == 1)
check("gtfs: terminus D never departs", int(freq["departures"][3]) == 0)

pats, stop_pats = transit.compile_day(feed, "20260706")
check("gtfs: two patterns compiled", len(pats) == 2)
check("gtfs: R1 pattern holds 6 trips",
      sorted(p["arr"].shape[0] for p in pats) == [2, 6])

arr = transit.earliest_arrival(pats, stop_pats, 4, {0: 8 * 3600},
                               max_transfers=1)
check("gtfs: RAPTOR reaches B 08:10", close(arr[1], 8 * 3600 + 600))
check("gtfs: RAPTOR reaches C 08:20", close(arr[2], 8 * 3600 + 1200))
check("gtfs: RAPTOR transfers to D 08:35", close(arr[3], 8 * 3600 + 2100))
arr0 = transit.earliest_arrival(pats, stop_pats, 4, {0: 8 * 3600},
                                max_transfers=0)
check("gtfs: without transfers D is unreachable", not np.isfinite(arr0[3]))
arr_late = transit.earliest_arrival(pats, stop_pats, 4, {0: 8 * 3600 + 300},
                                    max_transfers=2)
check("gtfs: five past eight -> next 08:30 trip -> C 08:50",
      close(arr_late[2], 8 * 3600 + 3000))
check("gtfs: late start still catches the 09:25 branch to D",
      close(arr_late[3], 9 * 3600 + 2100))

# --------------------------------------------------------------------------- #
# 27. Visibility: viewshed + isovists (Phase E)
# --------------------------------------------------------------------------- #
from planx.engine import visibility  # noqa: E402

# Flat 21x21 ground, observer in the middle: everything is visible.
flat = np.zeros((21, 21))
vs_flat = visibility.viewshed(flat, 1.0, (10, 10), observer_h=1.6,
                              target_h=0.0, n_dirs=720)
check("viewshed: flat ground fully visible", int(vs_flat.sum()) == 21 * 21)

# A 10 m wall across column 12 hides the ground behind it (east of it).
wall = np.zeros((21, 21))
wall[:, 12] = 10.0
vs_wall = visibility.viewshed(wall, 1.0, (10, 10), observer_h=1.6,
                              target_h=0.0, n_dirs=1440)
check("viewshed: cell before the wall visible", vs_wall[10, 11] == 1)
check("viewshed: wall crest itself visible", vs_wall[10, 12] == 1)
check("viewshed: ground right behind the wall hidden", vs_wall[10, 14] == 0)
check("viewshed: far ground behind the wall hidden", vs_wall[10, 19] == 0)
check("viewshed: west side unaffected", vs_wall[10, 2] == 1)

# A tall enough target pokes above the horizon: at (10,14) the wall horizon
# is (10-1.6)/2 = 4.2; a 20 m target gives (20-1.6)/4 = 4.6 > 4.2.
vs_tall = visibility.viewshed(wall, 1.0, (10, 10), observer_h=1.6,
                              target_h=20.0, n_dirs=1440)
check("viewshed: a 20 m mast behind the wall is visible", vs_tall[10, 14] == 1)

# Radius cap: nothing beyond 3 m from the observer.
vs_rad = visibility.viewshed(flat, 1.0, (10, 10), radius=3.0, n_dirs=720)
check("viewshed: radius caps the sweep",
      vs_rad[10, 13] == 1 and vs_rad[10, 15] == 0)

# Isovist in the open: a 10 m disc.
open_mask = np.zeros((41, 41), dtype=bool)
iso_open = visibility.isovist(open_mask, (20, 20), pixel=1.0, n_rays=360,
                              max_dist=10.0)
check("isovist: open disc area ~ pi r^2",
      abs(iso_open["area"] - math.pi * 100.0) < math.pi * 100.0 * 0.01)
check("isovist: open disc circularity ~ 1", iso_open["circularity"] > 0.99)
check("isovist: open disc radials all at range",
      close(iso_open["min_rad"], 10.0) and close(iso_open["max_rad"], 10.0))
check("isovist: nothing occluded in the open", iso_open["occlusivity"] == 0.0)

# A corridor: walls at rows 18 and 22 squeeze the isovist.
corridor = np.zeros((41, 41), dtype=bool)
corridor[18, :] = True
corridor[22, :] = True
iso_cor = visibility.isovist(corridor, (20, 20), pixel=1.0, n_rays=360,
                             max_dist=15.0)
check("isovist: corridor is far smaller than the open disc",
      iso_cor["area"] < iso_open["area"] / 3.0,
      )
check("isovist: corridor mostly occluded", iso_cor["occlusivity"] > 0.8)
check("isovist: corridor still reaches its full length sideways",
      close(iso_cor["max_rad"], 15.0))

iso_blocked = visibility.isovist(corridor, (18, 5), pixel=1.0, n_rays=90)
check("isovist: origin on an obstacle collapses to zero",
      iso_blocked["area"] == 0.0 and iso_blocked["occlusivity"] == 1.0)


def naive_isovist_field(mask, points_rc, pixel=1.0, n_rays=180, max_dist=None):
    keys = ("area", "perimeter", "min_rad", "max_rad", "mean_rad",
            "circularity", "occlusivity")
    out = {k: np.zeros(len(points_rc)) for k in keys}
    for i, rc in enumerate(points_rc):
        iso = visibility.isovist(mask, rc, pixel=pixel, n_rays=n_rays, max_dist=max_dist)
        for k in keys:
            out[k][i] = iso[k]
    return out


fld = visibility.isovist_field(corridor, [(20, 20), (5, 5)], pixel=1.0,
                               n_rays=90, max_dist=15.0)
fld_naive = naive_isovist_field(corridor, [(20, 20), (5, 5)], pixel=1.0,
                                n_rays=90, max_dist=15.0)
bit_identical_isovist = True
for k in fld:
    if not np.array_equal(fld[k], fld_naive[k]):
        bit_identical_isovist = False
check("isovist field: optimized is bit-identical to naive", bit_identical_isovist)
check("isovist field: per-point arrays align",
      len(fld["area"]) == 2 and fld["area"][1] > fld["area"][0])

# --------------------------------------------------------------------------- #
# 28. Population & housing (Phase F)
# --------------------------------------------------------------------------- #
from planx.engine import population  # noqa: E402

# Hand-computed Leslie projection, 3 groups over 2 steps:
# pop [100, 80, 60], survival [0.9, 0.8, 0.5], fertility [0, 0.4, 0.1].
proj = population.cohort_projection(
    [100.0, 80.0, 60.0], [0.9, 0.8, 0.5], [0.0, 0.4, 0.1], steps=2)
check("leslie: step 1 births 38, aged 90, elders 94",
      np.allclose(proj[1], [38.0, 90.0, 94.0]))
check("leslie: step 2 [45.4, 34.2, 119]",
      np.allclose(proj[2], [45.4, 34.2, 119.0]))
check("leslie: row 0 is the start population",
      np.allclose(proj[0], [100.0, 80.0, 60.0]))

proj_mig = population.cohort_projection(
    [100.0, 80.0, 60.0], [0.9, 0.8, 0.5], [0.0, 0.4, 0.1],
    migration=[10.0, 0.0, -5.0], steps=1)
check("leslie: migration lands after the update",
      np.allclose(proj_mig[1], [48.0, 90.0, 89.0]))

neg = population.cohort_projection(
    [1.0, 0.0], [0.0, 0.0], [0.0, 0.0], migration=[-50.0, 0.0], steps=1)
check("leslie: emigration never drives a group negative",
      float(neg[1, 0]) == 0.0)

hn = population.housing_needs(10000.0, 2.5, 3800.0, vacancy_target=0.05,
                              replacement_units=100.0, backlog_units=50.0)
check("housing: 4000 households -> target 4200",
      close(hn["households"], 4000.0) and close(hn["target_stock"], 4200.0))
check("housing: need = 4200 - 3800 + 100 + 50 = 550",
      close(hn["need"], 550.0))
hn_surplus = population.housing_needs(1000.0, 2.5, 900.0)
check("housing: oversupplied market reports a surplus",
      hn_surplus["need"] < 0)

build, units = population.residential_capacity(
    [1000.0, 500.0], [1.5, 2.0], existing_floor=[600.0, 2000.0],
    unit_size=90.0, efficiency=0.85)
check("capacity: 1000 m2 x 1.5 FAR - 600 = 900 buildable",
      close(build[0], 900.0))
check("capacity: 900 x 0.85 / 90 -> 8 whole units", int(units[0]) == 8)
check("capacity: overbuilt parcel clamps to zero, never negative",
      close(build[1], 0.0) and int(units[1]) == 0)

pyr = report.svg_pyramid(["0-14", "15-64", "65+"],
                         [100.0, 300.0, 80.0], [90.0, 310.0, 130.0])
check("pyramid: svg carries the labels and both series",
      pyr.startswith("<svg") and "0-14" in pyr and "65+" in pyr
      and "#27ae60" in pyr and "#d64541" in pyr)

# --------------------------------------------------------------------------- #
# 29. Road-noise screening (Phase G)
# --------------------------------------------------------------------------- #
from planx.engine import green, noise  # noqa: E402

check("noise: RLS emission 1000 veh/h at 10 percent heavy = 69.9 dB",
      close(float(noise.emission_rls(1000.0, 10.0)), 37.3 + 10 * math.log10(1820.0)))
check("noise: zero traffic is silent",
      np.isneginf(noise.emission_rls(0.0, 5.0)))

# Point-sample calibration: an effectively infinite straight road sampled
# every 10 m must reproduce the 25 m line level within a fraction of a dB.
lm25 = 70.0
xs = np.arange(-10000.0, 10000.0, 10.0)
src = np.column_stack([xs, np.zeros_like(xs)])
lvl = np.full(len(xs), float(noise.sample_level(lm25, 10.0)))
at25 = noise.receiver_level(src, lvl, 0.0, 25.0)
check("noise: infinite-line samples reproduce the 25 m reference",
      abs(at25 - lm25) < 0.3)
at50 = noise.receiver_level(src, lvl, 0.0, 50.0)
check("noise: line spreading loses ~3 dB per doubling",
      abs((at25 - at50) - 3.0) < 0.3)

one = np.asarray([[0.0, 0.0]])
one_lvl = np.asarray([noise.sample_level(lm25, 10.0)])
free = noise.receiver_level(one, one_lvl, 100.0, 0.0)
shadowed = noise.receiver_level(one, one_lvl, 100.0, 0.0,
                                blocked=np.asarray([True]), screen_db=10.0)
check("noise: screening subtracts exactly the insertion loss",
      close(free - shadowed, 10.0))
check("noise: cutoff silences distant sources",
      np.isneginf(noise.receiver_level(one, one_lvl, 1000.0, 0.0, cutoff=500.0)))

labels_b, totals_b = noise.exposure_bands(
    [44.0, 52.0, 66.0], weights=[10.0, 20.0, 5.0])
check("noise: exposure bands split the population",
      close(totals_b[0], 10.0) and close(totals_b[2], 20.0)
      and close(totals_b[5], 5.0) and close(sum(totals_b), 35.0))

# --------------------------------------------------------------------------- #
# 30. Green connectivity (Phase G)
# --------------------------------------------------------------------------- #
check("green: hierarchy parses and sorts",
      green.parse_hierarchy("2=800, 0.5=300") == [(0.5, 300.0), (2.0, 800.0)])
try:
    green.parse_hierarchy("banana")
    check("green: malformed hierarchy raises", False)
except ValueError:
    check("green: malformed hierarchy raises", True)

# Chain of three patches (1, 1, 2 ha): fully connected PC = 1; removing the
# middle stepping stone costs the most.
conn = green.connectivity([1.0, 1.0, 2.0], [(0, 1), (1, 2)])
check("green: one chained component", conn["n_components"] == 1)
check("green: fully connected PC = 1", close(conn["pc"], 1.0))
check("green: stepping stone loses 68.75 percent of PC",
      close(conn["dpc"][1], 68.75))
check("green: end patch 0 loses 43.75 percent",
      close(conn["dpc"][0], 43.75))
check("green: the large end patch matters most of the ends",
      conn["dpc"][2] > conn["dpc"][0])

iso = green.connectivity([1.0, 1.0], [])
check("green: two isolated equal patches -> PC 0.5",
      iso["n_components"] == 2 and close(iso["pc"], 0.5))

# --------------------------------------------------------------------------- #
# 31. Urban growth (Phase H)
# --------------------------------------------------------------------------- #
import subprocess  # noqa: E402  # nosec B404 - fixed argv, test-only

from planx.engine import growth  # noqa: E402

cm = growth.change_matrix([[1, 1], [2, 2]], [[1, 2], [2, 2]])
check("change: classes found", cm["classes"] == [1, 2])
check("change: matrix counts the single conversion",
      cm["matrix"].tolist() == [[1, 1], [0, 2]])
check("change: per-class gains/losses/persistence",
      cm["persisted"].tolist() == [1, 2] and cm["lost"].tolist() == [1, 0]
      and cm["gained"].tolist() == [0, 1] and cm["net"].tolist() == [-1, 1])
cm_nd = growth.change_matrix([[1, 0], [2, 2]], [[1, 0], [2, 1]], nodata=0)
check("change: nodata cells ignored", int(cm_nd["matrix"].sum()) == 3)

# CA on a 5x5: seed centre, suitability rising eastward -> growth goes east.
seed = np.zeros((5, 5), dtype=bool)
seed[2, 2] = True
suit_g = np.tile(np.arange(5, dtype=float), (5, 1))  # column index = pull
sim = growth.ca_simulate(seed, suit_g, demand_cells=4, iterations=2,
                         neigh_weight=1.0, base=0.1, rng_seed=42)
check("ca: start mask preserved", sim["masks"][0].sum() == 1)
check("ca: demand fully converted over the steps",
      sum(sim["converted"]) == 4 and sim["masks"][-1].sum() == 5)
check("ca: growth follows the suitability gradient east",
      bool(sim["masks"][-1][2, 3]) and bool(sim["masks"][-1][2, 4])
      and not bool(sim["masks"][-1][2, 0]))
check("ca: year-of-conversion is ordered",
      sim["year_of"][2, 2] == 0 and sim["year_of"][2, 3] >= 1)

blocked = np.zeros((5, 5), dtype=bool)
blocked[:, 3:] = True  # the attractive east is off limits
sim_b = growth.ca_simulate(seed, suit_g, demand_cells=4, iterations=2,
                           constraints=blocked, rng_seed=42)
check("ca: constraints keep the east untouched",
      not sim_b["masks"][-1][:, 3:].any()
      and sim_b["masks"][-1].sum() == 5)

sim_same = growth.ca_simulate(seed, suit_g, demand_cells=4, iterations=2,
                              neigh_weight=1.0, base=0.1, rng_seed=42)
check("ca: same seed reproduces the identical history",
      all(np.array_equal(a, b)
          for a, b in zip(sim["masks"], sim_same["masks"])))

# Cross-process determinism: a fresh interpreter must produce the same
# conversion order (the osm_3d_model hash() lesson).
_cross_script = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "_growth_cross_check.py")
with open(_cross_script, "w", encoding="utf-8") as fh:
    fh.write(
        "import sys\n"
        "sys.path.insert(0, r'" + os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))) + "')\n"
        "import numpy as np\n"
        "from planx.engine import growth\n"
        "seed = np.zeros((5, 5), dtype=bool); seed[2, 2] = True\n"
        "suit = np.tile(np.arange(5, dtype=float), (5, 1))\n"
        "sim = growth.ca_simulate(seed, suit, demand_cells=4, iterations=2,\n"
        "                         neigh_weight=1.0, base=0.1, rng_seed=42)\n"
        "print(''.join('1' if v else '0'\n"
        "              for v in sim['masks'][-1].ravel().tolist()))\n")
_out = subprocess.run(  # nosec B603 - own interpreter + file we just wrote
    [sys.executable, _cross_script], capture_output=True, text=True)
_expected = "".join("1" if v else "0"
                    for v in sim["masks"][-1].ravel().tolist())
check("ca: identical result from a separate process",
      _out.returncode == 0 and _out.stdout.strip() == _expected)
os.remove(_cross_script)

# Sprawl: 4 -> 8 urban cells while population grows 21 percent.
t1 = np.zeros((6, 6), dtype=bool)
t1[0:2, 0:2] = True
t2 = np.zeros((6, 6), dtype=bool)
t2[0:2, 0:3] = True          # main patch: 6 cells
t2[4, 4] = True
t2[4, 5] = True              # outlier: 2 cells
sm = growth.sprawl_metrics(t1, t2, 1000.0, 1210.0, pixel=1.0)
check("sprawl: LCRPGR = ln2 / ln1.21",
      close(sm["lcrpgr"], math.log(2.0) / math.log(1.21), 1e-9))
check("sprawl: two patches, largest holds 75 percent",
      sm["n_patches"] == 2 and close(sm["largest_share"], 0.75))
check("sprawl: edge length hand-count (2x3 block + 1x2 block)",
      close(sm["edge_length"], 10.0 + 6.0))

# --------------------------------------------------------------------------- #
# 32. Auditor metric registry (Phase I)
# --------------------------------------------------------------------------- #
check("registry: walkability mean is higher-better",
      scenario.direction_of("walk_score_mean") == 1)
check("registry: access Gini is lower-better",
      scenario.direction_of("access_gini") == -1)
aud_a = scenario.snapshot("A", {"access_gini": 0.30, "walk_low_share": 40.0})
aud_b = scenario.snapshot("B", {"access_gini": 0.22, "walk_low_share": 45.0})
aud = {r["key"]: r for r in scenario.compare(aud_a, aud_b)}
check("registry: falling Gini credited to B",
      aud["access_gini"]["better"] == "B")
check("registry: rising low-walk share credited to A",
      aud["walk_low_share"]["better"] == "A")
check("registry: labels resolve for the auditor keys",
      "Gini" in scenario.label_of("access_gini")
      and "Walkability" in scenario.label_of("walk_score_mean"))

# --------------------------------------------------------------------------- #
# 33. Generate Demo City (Phase A1)
# --------------------------------------------------------------------------- #
res_demo = demo.generate_demo_city(42, 2, 2, 100.0)
check("demo streets count", len(res_demo["streets"]) == 14)
check("demo buildings count", len(res_demo["buildings"]) == 12)
check("demo landuse count", len(res_demo["landuse"]) == 4)
check("demo pois count", len(res_demo["pois"]) == 2)
check("demo facilities count", len(res_demo["facilities"]) == 2)
check("demo demand count", len(res_demo["demand"]) == 2)
check("demo green count", len(res_demo["green"]) == 1)
check("demo DSM max == tallest building", close(res_demo["dsm"].max(), max(b[1] for b in res_demo["buildings"])))

# Cross-process identity for demo city
_cross_script_demo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_demo_cross_check.py")
with open(_cross_script_demo, "w", encoding="utf-8") as fh:
    fh.write(
        "import sys\n"
        "sys.path.insert(0, r'" + os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) + "')\n"
        "from planx.engine import demo\n"
        "res = demo.generate_demo_city(42, 2, 2, 100.0)\n"
        "print(len(res['streets']), len(res['buildings']), float(res['dsm'].sum()))\n"
    )
_out_demo = subprocess.run(  # nosec B603 - fixed args, test-only script
    [sys.executable, _cross_script_demo], capture_output=True, text=True)
_expected_demo = f"14 12 {float(res_demo['dsm'].sum())}\n"
check("demo: identical result from separate process",
      _out_demo.returncode == 0 and _out_demo.stdout.replace('\r', '') == _expected_demo)
if os.path.exists(_cross_script_demo):
    os.remove(_cross_script_demo)

# --------------------------------------------------------------------------- #
# 34. Cycling stress and low-stress islands (Phase B)
# --------------------------------------------------------------------------- #
check("cycling: default rule table parses",
      cycling.parse_lts_rules(cycling.DEFAULT_LTS_RULES_TEXT)["mixed_lts1_aadt"] == 1000.0)
try:
    cycling.parse_lts_rules("mixed_lts1_speed=slow")
    check("cycling: malformed rules raise", False)
except ValueError:
    check("cycling: malformed rules raise", True)

lts_rows = cycling.lts_classify(
    speed=[70.0, 40.0, 60.0, 25.0, 30.0, 45.0, 55.0],
    lanes=[4.0, 2.0, 4.0, 2.0, 2.0, 2.0, 2.0],
    aadt=[20000.0, 5000.0, 5000.0, 900.0, 5000.0, 5000.0, 5000.0],
    infra=["path", "lane", "lane", "mixed", "mixed", "mixed", "mixed"])
check("cycling: every LTS rule row hand case",
      lts_rows.tolist() == [1, 2, 3, 1, 2, 3, 4])

custom = cycling.lts_classify([35.0], [2.0], [800.0], ["mixed"],
                              cycling.parse_lts_rules("mixed_lts1_speed=35"))
check("cycling: agency threshold override changes classification", int(custom[0]) == 1)

edge_from = np.asarray([0, 1, 2], dtype=np.int64)
edge_to = np.asarray([1, 2, 3], dtype=np.int64)
edge_len = np.asarray([100.0, 100.0, 100.0])
bridge_lts = np.asarray([1, 3, 1])
isl2 = cycling.low_stress_islands(edge_from, edge_to, edge_len, bridge_lts, threshold=2)
check("cycling islands: high-stress bridge splits two low-stress islands",
      isl2["n_components"] == 2 and isl2["edge_labels"].tolist() == [0, -1, 1])
check("cycling islands: low-stress share excludes bridge",
      close(isl2["low_share"], 2.0 / 3.0))
isl3 = cycling.low_stress_islands(edge_from, edge_to, edge_len, bridge_lts, threshold=3)
check("cycling islands: raising threshold merges the network",
      isl3["n_components"] == 1 and isl3["edge_labels"].tolist() == [0, 0, 0]
      and close(float(isl3["component_length"][0]), 300.0))
# --------------------------------------------------------------------------- #
# 35. Air quality screening (Phase C)
# --------------------------------------------------------------------------- #
# doubling distance halves concentration index at alpha=1
c_50 = air.concentration([[0.0, 0.0]], [100.0], 0.0, 50.0, 1.0, alpha=1.0, d0=0.0)
c_100 = air.concentration([[0.0, 0.0]], [100.0], 0.0, 100.0, 1.0, alpha=1.0, d0=0.0)
check("air: doubling distance halves the single-source index at alpha=1",
      close(c_50, 2.0) and close(c_100, 1.0))

# canyon factor 2 when H=W
check("air: canyon factor 2 when H=W", close(air.canyon_factor(15.0, 15.0), 2.0))

# infinite-line calibration ±tolerance
xs_val = np.arange(-5000.0, 5001.0, 1.0)
src_xy_val = np.column_stack((xs_val, np.zeros_like(xs_val)))
strength_val = air.sample_strength(1000.0, 1.0)
strengths_val = np.full_like(xs_val, strength_val)
c_inf = air.concentration(src_xy_val, strengths_val, 0.0, 25.0, 1.0, alpha=2.0, d0=0.0)
check("air: infinite-line calibration within tolerance", abs(c_inf - 1000.0) < 10.0)

# band splitting
labels_val, counts_val = air.exposure_bands([15.0, 25.0, 35.0], weights=[2.0, 3.0, 5.0], breaks=[20.0, 30.0])
check("air: band splitting counts", counts_val.tolist() == [2.0, 3.0, 5.0])
check("air: band splitting labels", labels_val == ["< 20", "20 - 30", ">= 30"])

# --------------------------------------------------------------------------- #
# 36. Hydrology / Hazard screening (Phase D)
# --------------------------------------------------------------------------- #
# Pit DEM fills to pour point
dem_pit = np.array([
    [5.0, 5.0, 5.0],
    [5.0, 2.0, 5.0],
    [5.0, 5.0, 5.0]
])
filled_pit = hydro.fill_depressions(dem_pit)
check("hydro: a pit DEM fills exactly to its pour point",
      filled_pit[1, 1] == 5.0 and np.all(filled_pit[0, :] == 5.0) and np.all(filled_pit[2, :] == 5.0))

# 1-D slope gives accumulation 1..n and HAND equal to elevation above channel
dem_slope = np.array([
    [5.0, 4.0, 3.0, 2.0, 1.0]
])
dirs_slope = hydro.d8_flow(dem_slope)
check("hydro: 1-D slope D8 directions are all East (1) except sink",
      dirs_slope.tolist() == [[1, 1, 1, 1, 0]])

accum_slope = hydro.flow_accumulation(dirs_slope)
check("hydro: 1-D slope flow accumulation is 1..n",
      accum_slope.tolist() == [[1.0, 2.0, 3.0, 4.0, 5.0]])

# Let threshold = 3.0
drainage_slope = accum_slope >= 3.0
hand_slope = hydro.hand(dem_slope, dirs_slope, drainage_slope)
check("hydro: 1-D slope HAND is elevation above the channel",
      hand_slope.tolist() == [[2.0, 1.0, 0.0, 0.0, 0.0]])

# Valley floods correct three cells at depth 1
dem_valley = np.array([
    [3.0, 3.0, 3.0],
    [2.0, 1.0, 2.0],
    [3.0, 3.0, 3.0]
])
dirs_valley = hydro.d8_flow(dem_valley)
accum_valley = hydro.flow_accumulation(dirs_valley)
drainage_valley = accum_valley >= 5.0
hand_valley = hydro.hand(dem_valley, dirs_valley, drainage_valley)
inund_valley = hydro.inundation(hand_valley, depth=1.0)
check("hydro: a hand-built valley floods the right three cells at depth 1",
      inund_valley.tolist() == [
          [0.0, 0.0, 0.0],
          [1.0, 1.0, 1.0],
          [0.0, 0.0, 0.0]
      ])

# Exposure cross-tab check
inund_grid_test = np.array([
    [0.0, 0.0, 0.0],
    [1.0, 1.0, 1.0],
    [0.0, 0.0, 0.0]
])
bld_coords_test = [(1.5, -15.0), (1.5, -5.0)]
gt_test = (0.0, 1.0, 0.0, 0.0, 0.0, -10.0)
exp_res = hydro.exposure(inund_grid_test, bld_coords_test, [(1.5, -15.0), (1.5, -5.0)], [10.0, 20.0], gt_test)
check("hydro: exposure cross-tab equals hand counts",
      exp_res["exposed_bld"] == 1.0 and exp_res["total_bld"] == 2.0
      and close(exp_res["pct_bld"], 50.0)
      and exp_res["exposed_pop"] == 10.0 and exp_res["total_pop"] == 30.0
      and close(exp_res["pct_pop"], 100.0 / 3.0))

# --------------------------------------------------------------------------- #
fails = [label for label, ok in CHECKS if not ok]
print(f"\n{len(CHECKS) - len(fails)}/{len(CHECKS)} checks passed")
if fails:
    print("FAILED:", *fails, sep="\n  - ")
sys.exit(1 if fails else 0)
