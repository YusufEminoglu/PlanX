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
    HAS_SCIPY, allocate, centrality, equity, graphs, morphology, optimize,
    paths, report, solar, standards, syntax,
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
rot = np.array([[math.cos(theta), -math.sin(theta)],
                [math.sin(theta), math.cos(theta)]])
mrot = morphology.shape_metrics(rect @ rot.T)
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
fails = [label for label, ok in CHECKS if not ok]
print(f"\n{len(CHECKS) - len(fails)}/{len(CHECKS)} checks passed")
if fails:
    print("FAILED:", *fails, sep="\n  - ")
sys.exit(1 if fails else 0)
