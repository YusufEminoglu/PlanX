# -*- coding: utf-8 -*-
"""Engine correctness tests against hand-computed graphs.

Run with any Python that has NumPy (e.g. OSGeo4W):
    C:/OSGeo4W/bin/python-qgis-ltr.bat planx/tests/test_engine.py
No qgis imports - pure engine.
"""
from __future__ import annotations

import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from planx.engine import (  # noqa: E402
    HAS_SCIPY, air, allocate, centrality, cycling, comfort, demand, demo, equity, gmpe, graphs, hydro, impact, isochrone, landslide as lsl, liquefaction as liq, morphology,
    optimize, parking, paths, provenance, report, robustness, scenario, seismic, solar,
    standards, syntax, transit, uncertainty, walkability, weather,
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
check("demo buildings count", len(res_demo["buildings"]) == 8)
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
_expected_demo = f"14 8 {float(res_demo['dsm'].sum())}\n"
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
# Travel Demand (v4.4)
# --------------------------------------------------------------------------- #
# Trip Generation
P_gen, A_gen = demand.trip_generation(np.array([100.0, 200.0]), np.array([50.0, 150.0]), 1.5, 2.0)
check("demand: trip generation productions", P_gen.tolist() == [150.0, 300.0])
check("demand: trip generation attractions", A_gen.tolist() == [100.0, 300.0])

# 2x2 Furness gravity model balance
P_grav = np.array([100.0, 100.0])
A_grav = np.array([100.0, 100.0])
cost_grav = np.array([[10.0, 20.0], [20.0, 10.0]])
T_grav, iters_grav, err_grav = demand.gravity(P_grav, A_grav, cost_grav, beta=0.1, kind="exp", max_iter=200, tol=1e-10)

e = math.exp(1.0)
expected_T = np.array([
    [100.0 * e / (e + 1.0), 100.0 / (e + 1.0)],
    [100.0 / (e + 1.0), 100.0 * e / (e + 1.0)]
])
check("demand: 2x2 Furness balances to known closed-form solution",
      close(T_grav[0, 0], expected_T[0, 0]) and close(T_grav[0, 1], expected_T[0, 1])
      and close(T_grav[1, 0], expected_T[1, 0]) and close(T_grav[1, 1], expected_T[1, 1]))

check("demand: gravity totals conserved to 1e-9",
      abs(T_grav.sum(axis=1) - P_grav).max() < 1e-9 and abs(T_grav.sum(axis=0) - A_grav).max() < 1e-9)

# Beta = 0 gravity model
T_beta0, _, _ = demand.gravity(np.array([100.0, 200.0]), np.array([150.0, 150.0]), cost_grav, beta=0.0)
check("demand: beta=0 gives cost-independent proportionality",
      T_beta0.tolist() == [[50.0, 50.0], [100.0, 100.0]])

# Logit mode split
times_split = [np.array([[15.0]]), np.array([[25.0]])]
shares_split = demand.mode_split(times_split, betas=[-0.1, -0.1], asc=[0.0, 0.0])
check("demand: logit shares for two modes with a 10-minute gap match the hand value",
      close(shares_split[0][0, 0], e / (e + 1.0)) and close(shares_split[1][0, 0], 1.0 / (e + 1.0)))

# --------------------------------------------------------------------------- #
# Scenario Pipeline (v4.5)
# --------------------------------------------------------------------------- #
alloc_1 = population.allocate_growth(5, np.array([1.0, 1.0, 1.0]))
check("population: allocate_growth exactness and tie-breaking",
      alloc_1.tolist() == [2, 2, 1])

alloc_2 = population.allocate_growth(10, np.array([1.2, 2.5, 0.3, 0.0]))
check("population: allocate_growth with varying weights",
      alloc_2.tolist() == [3, 6, 1, 0])

alloc_3 = population.allocate_growth(2, np.array([0.0, 0.0, 0.0]))
check("population: allocate_growth uniform fallback for zero weights",
      alloc_3.tolist() == [1, 1, 0])

# --------------------------------------------------------------------------- #
# Ground motion (ASB2014)
# --------------------------------------------------------------------------- #
def _one(value):
    return np.array([float(value)])


def _mech(code):
    return np.array([code])


def _gmpe_at(mag, distance_km, vs30, mechanism="SS", metric="RJB"):
    """One scenario, one receiver - the shape every check below needs."""
    return gmpe.predict(metric, _one(mag), _one(distance_km), _one(vs30),
                        _mech(mechanism))


def _gmpe_raises(exc_type, func, *args):
    try:
        func(*args)
    except exc_type:
        return True
    except Exception:
        return False
    return False


check("gmpe: the table is 64 rows - PGA, PGV and 62 spectral periods",
      (gmpe.INDEX_PGA, gmpe.INDEX_PGV, gmpe.N_ROWS, len(gmpe.PERIODS)) == (0, 1, 64, 62))

# The load-bearing check. tests/data/asb14_pygmm_reference.json holds four
# scenarios evaluated by pyGMM, an independent implementation, in all three
# distance tables - 744 spectral values plus PGA and PGV. Both engines use the
# same coefficient table, so what this tests is the part written from the
# paper: the equations, the site-term branching, the per-metric wiring and the
# row indexing. A test built from this engine's own output would pass whatever
# the engine did, which is the failure mode this fixture exists to avoid.
_fixture_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "data", "asb14_pygmm_reference.json")
with open(_fixture_path, encoding="utf-8") as _handle:
    _reference = json.load(_handle)

_periods = list(_reference["periods"])
check("gmpe: the fixture's period grid is this engine's period grid",
      _periods == list(gmpe.PERIODS))

_worst_sa = 0.0
_worst_pga = 0.0
_worst_pgv = 0.0
_cases = 0
for _case in _reference["cases"]:
    for _metric, _expected in _case["metrics"].items():
        _out = _gmpe_at(
            _case["magnitude"], _case["distance_km"], _case["vs30"],
            _case["mechanism"], _metric)
        _cases += 1
        _worst_pga = max(_worst_pga, abs(float(_out["pga_g"][0]) - _expected["pga_g"])
                         / _expected["pga_g"])
        _worst_pgv = max(_worst_pgv, abs(float(_out["pgv_cms"][0]) - _expected["pgv_cms"])
                         / _expected["pgv_cms"])
        for _period, _value in zip(_periods, _expected["sa_g"]):
            _mine = float(_out["im"][0, gmpe.period_index(_period)])
            _worst_sa = max(_worst_sa, abs(_mine - _value) / _value)

check("gmpe: all 12 pyGMM scenario-metric cases were exercised", _cases == 12)
check(f"gmpe: PGA reproduces pyGMM to 1e-9 relative (worst {_worst_pga:.2e})",
      _worst_pga < 1e-9)
check(f"gmpe: PGV reproduces pyGMM to 1e-9 relative (worst {_worst_pgv:.2e})",
      _worst_pgv < 1e-9)
check(f"gmpe: all 744 spectral values reproduce pyGMM to 1e-9 (worst {_worst_sa:.2e})",
      _worst_sa < 1e-9)

# A Vs30 of 1200 in the fixture exercises the cap: the fourth scenario sits
# above the model's 1000 m/s ceiling, and the reference agrees with this engine
# only if both evaluate it at the ceiling.
check("gmpe: the fixture covers a Vs30 above the model's ceiling",
      any(_case["vs30"] > gmpe.SITE_VS30_CAP for _case in _reference["cases"]))

_at_ref = gmpe.predict("RJB", _one(7.0), _one(20.0), _one(gmpe.V_REF), _mech("SS"))
check("gmpe: at the reference velocity the site term is exactly zero",
      float(_at_ref["pga_g"][0]) == float(_at_ref["rock_pga_g"][0]))

_cap_a = gmpe.predict("RJB", _one(7.0), _one(20.0), _one(1000.0), _mech("SS"))
_cap_b = gmpe.predict("RJB", _one(7.0), _one(20.0), _one(1200.0), _mech("SS"))
check("gmpe: Vs30 above the ceiling is evaluated at the ceiling, bit for bit",
      np.array_equal(_cap_a["pga_g"], _cap_b["pga_g"])
      and not bool(_cap_a["vs30_capped"][0]) and bool(_cap_b["vs30_capped"][0]))

_mech_pga = {}
for _code in gmpe.MECHANISMS:
    _mech_pga[_code] = float(_gmpe_at(7.0, 20.0, 750.0, _code)["pga_g"][0])
check("gmpe: fault mechanism moves the median, strike-slip in the middle",
      _mech_pga["NS"] < _mech_pga["SS"] < _mech_pga["RS"])
check("gmpe: strike-slip is the reference, so a solid-rock site reproduces "
      "the measured Mw 7 / 20 km value",
      close(_mech_pga["SS"], 0.1461, tol=5e-5))

# Short-period site response is NOT monotone in Vs30: the measured sweep at
# Mw 7 / 20 km peaks at 400 m/s and falls away on both sides, because the
# nonlinear term is conditioned on rock PGA. Long periods are monotone over the
# same sweep. Both halves are asserted, because the first is the surprising one
# and a later "fix" that made it monotone would be a regression, not a repair.
_sweep = [150.0, 200.0, 400.0, 750.0, 1000.0]
_sa1_row = gmpe.period_index(1.0)
_pga_sweep = [float(_gmpe_at(7.0, 20.0, v)["pga_g"][0]) for v in _sweep]
_sa1_sweep = [float(_gmpe_at(7.0, 20.0, v)["im"][0, _sa1_row]) for v in _sweep]
check("gmpe: short-period amplification peaks at 400 m/s, so it is not monotone",
      _pga_sweep[2] == max(_pga_sweep) and not all(
          _pga_sweep[i] <= _pga_sweep[i + 1] for i in range(len(_pga_sweep) - 1)))
check("gmpe: Sa(1.0 s) is monotone decreasing over the same site sweep",
      all(_sa1_sweep[i] > _sa1_sweep[i + 1] for i in range(len(_sa1_sweep) - 1)))

# The dispersion the tool reports is a total. The paper gives within- and
# between-event terms per period; the total must be their quadrature sum.
check("gmpe: sigma_total is the quadrature sum of the two event terms",
      all(gmpe.sigma_invariant_worst(metric) < 1e-4
          for metric in gmpe.DISTANCE_METRICS))

_parsed = gmpe.parse_periods(" 1.0 , 0.3,1.0 , 0.3 ")
check("gmpe: requested periods are de-duplicated and sorted", _parsed == [0.3, 1.0])
check("gmpe: an empty period request asks for no spectral columns",
      gmpe.parse_periods("") == [] and gmpe.parse_periods("  ") == [])
check("gmpe: a non-numeric period is refused",
      _gmpe_raises(ValueError, gmpe.parse_periods, "0.3,soon"))
check("gmpe: a period the paper does not tabulate is refused, not interpolated",
      _gmpe_raises(ValueError, gmpe.parse_periods, "0.33"))
try:
    gmpe.parse_periods("0.33")
    _offgrid_message = ""
except ValueError as _exc:
    _offgrid_message = str(_exc)
check("gmpe: the refusal names the nearest published periods",
      "0.32" in _offgrid_message and "0.34" in _offgrid_message)

check("gmpe: a fault scenario offers Joyner-Boore only",
      gmpe.check_metric("RJB", "fault") is None
      and "epicentre" in (gmpe.check_metric("Repi", "fault") or "")
      and "epicentre" in (gmpe.check_metric("Rhypo", "fault") or ""))
check("gmpe: a point source supports all three distances",
      all(gmpe.check_metric(metric, "point") is None
          for metric in gmpe.DISTANCE_METRICS))

#: Receivers in a metre-based projection, which is the normal case: the
#: engine works in kilometres, so every call states the factor. Testing this
#: with metre-scale coordinates is the point - synthetic coordinates small
#: enough to pass as either unit are how a 1000x distance error once shipped.
_UNITS_PER_KM = 1000.0
_site = np.array([[0.0, 0.0], [30_000.0, 0.0]])
_point = gmpe.distances(
    "point", _site, _UNITS_PER_KM,
    epicentre_xy=np.array([30_000.0, 40_000.0]), depth_km=10.0)
check("gmpe: a point source measures Repi on the surface and Rhypo through the depth",
      close(float(_point["Repi"][0]), 50.0, tol=1e-9)
      and close(float(_point["Rhypo"][0]), math.sqrt(50.0 ** 2 + 10.0 ** 2), tol=1e-9))
check("gmpe: a point source's Joyner-Boore distance is its epicentral distance",
      np.array_equal(_point["RJB"], _point["Repi"]))
check("gmpe: the focal depth is in kilometres, so it is commensurate with the "
      "horizontal term rather than lost beneath it",
      close(float(_point["Rhypo"][1]), math.sqrt(40.0 ** 2 + 10.0 ** 2), tol=1e-9))

_metre_call = gmpe.point_distances(_site, np.array([30_000.0, 40_000.0]), _UNITS_PER_KM)
_kilometre_call = gmpe.point_distances(_site / 1000.0, np.array([30.0, 40.0]), 1.0)
check("gmpe: the same ground expressed at two unit scales gives the same km",
      all(np.allclose(_metre_call[key], _kilometre_call[key], rtol=0, atol=1e-12)
          for key in gmpe.DISTANCE_METRICS))

try:
    gmpe.point_distances(_site, np.array([30_000.0, 40_000.0]))
    _scale_message = ""
except TypeError as _exc:
    _scale_message = str(_exc)
check("gmpe: the distance functions refuse to assume a unit scale",
      "units_per_km" in _scale_message)

_trace_polyline = np.array([[0.0, 0.0], [0.0, 100_000.0]])
_trace = gmpe.distances("fault", _site, _UNITS_PER_KM, polylines=[_trace_polyline])
check("gmpe: RJB is measured to the trace, and a site on the trace reads zero",
      close(float(_trace["RJB"][0]), 0.0, tol=1e-9)
      and close(float(_trace["RJB"][1]), 30.0, tol=1e-9))

_far = gmpe.envelope_flags(_one(9.0), _one(500.0), _one(50.0))
check("gmpe: a scenario outside every published limit is flagged on all three",
      _far == [["mag_above", "dist_above", "vs30_below"]])
_near = gmpe.envelope_flags(_one(7.0), _one(20.0), _one(750.0))
check("gmpe: a scenario inside the envelope carries no flags", _near == [[]])
_deep = gmpe.envelope_flags(
    _one(7.0), _one(20.0), _one(750.0), depth_km=gmpe.SHALLOW_DEPTH_KM + 1.0)
check("gmpe: the depth flag is raised above the shallow-crustal limit",
      _deep == [["depth_above"]])
check("gmpe: envelope_report and envelope_flags cannot disagree",
      len(gmpe.envelope_report(_one(9.0), _one(500.0), _one(50.0))) == 3)

# --------------------------------------------------------------------------- #
# Seismic collapse and debris spread (Monte Carlo)
# --------------------------------------------------------------------------- #
def _seismic_raises(exc_type, func, *args):
    try:
        func(*args)
    except exc_type:
        return True
    except Exception:
        return False
    return False


years = np.array([1980.0, 1990.0, 2010.0, 2020.0])
levels = seismic.design_level(years)
check("seismic: construction year maps to a Hazus design level",
      levels.tolist() == ["pre", "low", "moderate", "high"])

check("seismic: magnitude factor is 1.0 at the Mw=7.0 reference point",
      close(seismic.magnitude_factor(7.0), 1.0))
check("seismic: magnitude factor matches the exponential formula off-reference",
      close(seismic.magnitude_factor(7.8), math.exp(0.8 * 0.8)))
check("seismic: nominal PGA is the reference PGA at Mw 7.0",
      close(seismic.effective_pga(7.0, 0.4), 0.4)
      and close(seismic.effective_pga(7.8, 0.4), 0.4 * math.exp(0.64)))

# The fragility table is transcribed from the manual; lock its shape so a
# partial re-transcription cannot pass silently.
table_levels = set(seismic.HAZUS_EQUIVALENT_PGA_FRAGILITY)
check("seismic: fragility table covers all four Hazus design levels",
      table_levels == {"pre", "low", "moderate", "high"})
check("seismic: every design level tabulates the same 36 building types",
      {len(seismic.HAZUS_EQUIVALENT_PGA_FRAGILITY[lv]) for lv in table_levels} == {36})
check("seismic: the tabulated dispersion is the 0.64 Hazus value",
      close(seismic.HAZUS_PGA_BETA, 0.64))
check("seismic: C1M medians match the manual row (high and pre code)",
      seismic.HAZUS_EQUIVALENT_PGA_FRAGILITY["high"]["C1M"] == (0.15, 0.27, 0.73, 1.61)
      and seismic.HAZUS_EQUIVALENT_PGA_FRAGILITY["pre"]["C1M"] == (0.09, 0.13, 0.26, 0.43))
check("seismic: a type the manual does not tabulate there is rejected",
      _seismic_raises(ValueError, seismic.damage_medians,
                      np.array(["high"]), np.array(["C3L"])))

# normal_cdf must agree whichever branch runs: SciPy when installed, math.erf
# otherwise. Testing only the installed branch would leave the fallback free
# to drift (it would catch a missing 1/sqrt(2) factor).
_z = np.array([-3.0, -0.5, 0.0, 1.25, 4.0, 0.0])
_reference = np.array([0.0013498980316300946, 0.3085375387259869, 0.5,
                       0.8943502263331446, 0.9999683287581669, 0.5])
check("seismic: normal_cdf matches the standard normal table",
      np.allclose(seismic.normal_cdf(_z), _reference, atol=1e-9))
_saved_ndtr = seismic._ndtr
seismic._ndtr = None
_fallback = seismic.normal_cdf(_z)
seismic._ndtr = _saved_ndtr
check("seismic: normal_cdf erf fallback agrees with the SciPy path",
      np.allclose(_fallback, seismic.normal_cdf(_z), atol=1e-12))

# Damage states form a simplex and rise monotonically with ground motion.
_im = np.array([0.02, 0.1, 0.3, 0.6, 1.2])
_probs = seismic.damage_probabilities(_im, np.array(["pre"] * 5), np.array(["C1M"] * 5))
check("seismic: damage-state probabilities sum to 1 at every intensity",
      np.allclose(sum(_probs[state] for state in seismic.DAMAGE_STATES), 1.0))
check("seismic: every damage-state probability stays within [0, 1]",
      all(np.all((_probs[state] >= 0.0) & (_probs[state] <= 1.0))
          for state in seismic.DAMAGE_STATES))
check("seismic: P(complete) increases with ground motion",
      bool(np.all(np.diff(_probs["complete"]) > 0.0)))
check("seismic: newer design levels are safer at the same shaking",
      float(seismic.damage_probabilities(0.5, "pre", "C1M")["complete"].ravel()[0])
      > float(seismic.damage_probabilities(0.5, "low", "C1M")["complete"].ravel()[0])
      > float(seismic.damage_probabilities(0.5, "moderate", "C1M")["complete"].ravel()[0])
      > float(seismic.damage_probabilities(0.5, "high", "C1M")["complete"].ravel()[0]))
check("seismic: zero and null ground motion mean no damage",
      close(float(seismic.damage_probabilities(0.0, "pre", "C1M")["none"].ravel()[0]), 1.0)
      and close(float(seismic.damage_probabilities(float("nan"), "pre", "C1M")["none"].ravel()[0]), 1.0))

# Regression for the saturation defect this rework removed. The old model
# multiplied a per-tier probability by exp(0.8*(Mw-7)), so every building
# built before 1985 pinned to P(collapse) = 1.0 from about Mw 7.2 upward and
# the scenario magnitude stopped carrying information for the most
# vulnerable stock - exactly the band a Marmara scenario sits in.
_sat = [float(seismic.collapse_probability(np.array([1980.0]), mw, "C1")[0])
        for mw in (6.5, 7.0, 7.5)]
check("seismic: P(complete) is distinct and rising across Mw 6.5 / 7.0 / 7.5",
      _sat[0] < _sat[1] < _sat[2] and len({round(v, 9) for v in _sat}) == 3)
check("seismic: P(complete) no longer saturates at the pre-1985 top tier by Mw 7.5",
      _sat[2] < 0.999)
check("seismic: P(complete) still rises with magnitude at the top tier",
      float(seismic.collapse_probability(np.array([1980.0]), 8.5, "C1")[0]) > _sat[2])
check("seismic: P(complete) stays within [0, 1] for a mild low scenario",
      0.0 <= float(seismic.collapse_probability(np.array([2020.0]), 4.0, "C1")[0]) <= 1.0)

_states = seismic.sample_damage_state(42, _probs)
check("seismic: sampled damage states are valid ladder indices",
      _states.min() >= 0 and _states.max() < len(seismic.DAMAGE_STATES))
check("seismic: same seed reproduces the identical damage draw",
      seismic.sample_damage_state(42, _probs).tolist() == _states.tolist())
check("seismic: material factor is monotone up the damage ladder",
      [seismic.material_factor(np.array([i]))[0] for i in range(5)]
      == sorted(seismic.material_factor(np.array([i]))[0] for i in range(5)))
check("seismic: material factor is 1.0 only for complete damage",
      close(seismic.material_factor(np.array([4]))[0], 1.0)
      and seismic.material_factor(np.array([0]))[0] == 0.0)

edge_draw = seismic.simulate_collapse(1, np.array([0.0, 1.0]))
check("seismic: p=0 never collapses and p=1 always collapses",
      edge_draw.tolist() == [False, True])

# A 200-building coin-flip vector: a five-building ladder of near-certain or
# near-impossible probabilities can legitimately come out identical under two
# seeds, which would make "a different seed differs" flaky rather than wrong.
_p_series = np.full(200, 0.5)
draw_a = seismic.simulate_collapse(42, _p_series)
draw_b = seismic.simulate_collapse(42, _p_series)
draw_c = seismic.simulate_collapse(7, _p_series)
check("seismic: same seed reproduces the identical collapse draw",
      draw_a.tolist() == draw_b.tolist())
check("seismic: a different seed can sample a different draw",
      draw_a.tolist() != draw_c.tolist())

heights = np.array([10.0, 20.0, 12.0])
areas = np.array([100.0, 200.0, 50.0])
factors = np.array([1.0, 0.0, 0.5])
radius, solid, pile, mass = seismic.debris_extent(
    heights, areas, factors, debris_factor=0.4, solid_volume_ratio=0.3,
    void_ratio=0.35, density=1.8)
check("seismic: debris radius is height x k x released fraction, 0 when nothing is released",
      np.allclose(radius, [4.0, 0.0, 2.4]))
check("seismic: complete damage reproduces the original radius formula (height x k)",
      close(float(seismic.debris_extent(np.array([10.0]), np.array([100.0]), np.array([1.0]),
                                        debris_factor=0.4, solid_volume_ratio=0.3)[0][0]), 4.0))
check("seismic: solid volume is area x height x solid ratio x released fraction",
      np.allclose(solid, [300.0, 0.0, 90.0]))
check("seismic: pile volume is the solid volume divided by the void-free fraction",
      np.allclose(pile, solid / (1.0 - 0.35)))
check("seismic: debris mass is the solid volume times the material density",
      np.allclose(mass, solid * 1.8))

check("seismic: height class follows the Hazus storey bands",
      seismic.resolve_building_type("C1", np.array([2.0, 5.0, 12.0])).tolist()
      == ["C1L", "C1M", "C1H"])
check("seismic: a type Hazus does not split by height is left unsplit",
      seismic.resolve_building_type("W1", np.array([5.0])).tolist() == ["W1"]
      and seismic.resolve_building_type("S3", np.array([12.0])).tolist() == ["S3"])
check("seismic: RM1 has no high-rise class, so tall ones stay mid-rise",
      seismic.resolve_building_type("RM1", np.array([12.0])).tolist() == ["RM1M"])
check("seismic: missing floor counts fall back to the mid-rise class",
      np.atleast_1d(seismic.resolve_building_type("C1", None)).tolist() == ["C1M"])

# Street-space width helpers (network sources B/C of the debris algorithm).
check("seismic: OSM width - primary class maps to 18 m",
      close(seismic.highway_width_m("primary", 8.0), 18.0))
check("seismic: OSM width - motorway and trunk share 25 m",
      close(seismic.highway_width_m("motorway", 8.0), 25.0)
      and close(seismic.highway_width_m("trunk", 8.0), 25.0))
check("seismic: OSM width - matching is case and whitespace tolerant",
      close(seismic.highway_width_m("  Primary ", 8.0), 18.0))
check("seismic: OSM width - '_link' ramps inherit the parent class width",
      close(seismic.highway_width_m("primary_link", 8.0), 18.0)
      and close(seismic.highway_width_m("MOTORWAY_LINK", 8.0), 25.0))
check("seismic: OSM width - unknown class and None fall back",
      close(seismic.highway_width_m("busway", 6.0), 6.0)
      and close(seismic.highway_width_m(None, 6.0), 6.0)
      and close(seismic.highway_width_m("", 6.0), 6.0))
check("seismic: width parse - plain numbers pass through",
      close(seismic.parse_width_m(7.5), 7.5) and close(seismic.parse_width_m(7), 7.0))
check("seismic: width parse - numeric strings accepted",
      close(seismic.parse_width_m("6.5"), 6.5))
check("seismic: width parse - decimal comma and unit suffixes accepted",
      close(seismic.parse_width_m("6,5 m"), 6.5)
      and close(seismic.parse_width_m("12 metres"), 12.0))
check("seismic: width parse - rubbish, empty, None and non-positive rejected",
      seismic.parse_width_m("wide") is None and seismic.parse_width_m("") is None
      and seismic.parse_width_m(None) is None and seismic.parse_width_m(0) is None
      and seismic.parse_width_m(-3.0) is None and seismic.parse_width_m("5 km") is None
      and seismic.parse_width_m(float("nan")) is None)

# --------------------------------------------------------------------------- #
# Seismic human impact - casualties and shelter (Hazus 6.1 Sections 12-13)
# --------------------------------------------------------------------------- #
# The Section 12 tables are the whole model's input, so their shape is locked
# first. A partial or mis-aligned re-transcription is the one failure that
# would produce plausible-looking casualty numbers for every building type at
# once, and nothing downstream could tell.
_IMPACT_TABLES = {
    "Table 12-3 (slight, indoor)": impact.INDOOR_CASUALTY_RATES,
    "Table 12-4 (moderate, indoor)": impact.INDOOR_CASUALTY_RATES_MODERATE,
    "Table 12-5 (extensive, indoor)": impact.INDOOR_CASUALTY_RATES_EXTENSIVE,
    "Table 12-6 (complete, no collapse)": impact.INDOOR_CASUALTY_RATES_COMPLETE_INTACT,
    "Table 12-7 (complete, collapse)": impact.INDOOR_CASUALTY_RATES_COMPLETE_COLLAPSED,
    "Table 12-8 (collapse given complete)": impact.COLLAPSE_RATE_GIVEN_COMPLETE,
    "Table 12-9 (moderate, outdoor)": impact.OUTDOOR_CASUALTY_RATES_MODERATE,
    "Table 12-10 (extensive, outdoor)": impact.OUTDOOR_CASUALTY_RATES_EXTENSIVE,
    "Table 12-11 (complete, outdoor)": impact.OUTDOOR_CASUALTY_RATES_COMPLETE,
}
check("impact: the 36-type casualty tables all share one key set",
      all(set(table) == set(impact.CASUALTY_BUILDING_TYPES)
          for table in _IMPACT_TABLES.values()))
check("impact: every table is keyed by the manual's own type order",
      all(tuple(table) == impact.CASUALTY_BUILDING_TYPES
          for table in _IMPACT_TABLES.values()))
# Every label engine.seismic can resolve ("C1M", "RM2H", ...) must have a
# casualty row, or a real run would raise KeyError on exactly the types the
# damage model offers the user.
_seismic_labels = set()
for _base, _floors in ((code, floors) for code, _label in seismic.BUILDING_TYPES
                       for floors in (1.0, 5.0, 12.0)):
    _seismic_labels.update(np.atleast_1d(
        seismic.resolve_building_type(_base, np.array([_floors]))).tolist())
check("impact: the casualty tables cover every label the damage model can emit",
      _seismic_labels <= set(impact.CASUALTY_BUILDING_TYPES)
      and len(_seismic_labels) >= 20)

# Table 12-3 is uniformly 0.05 / 0 / 0 / 0 in the manual - slight damage hurts
# 5% of occupants, mildly, and kills nobody. A near-uniform table is exactly
# the kind that invites a plausible-looking edit.
check("impact: Table 12-3 is uniformly 5% severity-1 injuries and no deaths",
      all(value == (0.05, 0.0, 0.0, 0.0)
          for value in impact.INDOOR_CASUALTY_RATES.values()))
check("impact: Table 12-3 carries a row for every one of the 36 types",
      len(impact.INDOOR_CASUALTY_RATES) == 36)
# URML/URMM are the outliers that make a shuffled transcription visible.
check("impact: unreinforced masonry carries the manual's outlier rates",
      impact.INDOOR_CASUALTY_RATES_MODERATE["URML"] == (0.35, 0.4, 0.001, 0.001)
      and impact.INDOOR_CASUALTY_RATES_EXTENSIVE["URML"] == (2.0, 0.2, 0.002, 0.002))
check("impact: Table 12-8 collapse fractions match the manual rows",
      close(impact.COLLAPSE_RATE_GIVEN_COMPLETE["W1"], 0.03)
      and close(impact.COLLAPSE_RATE_GIVEN_COMPLETE["S1L"], 0.08)
      and close(impact.COLLAPSE_RATE_GIVEN_COMPLETE["C1L"], 0.13)
      and close(impact.COLLAPSE_RATE_GIVEN_COMPLETE["C3L"], 0.15)
      and close(impact.COLLAPSE_RATE_GIVEN_COMPLETE["PC1"], 0.15)
      and close(impact.COLLAPSE_RATE_GIVEN_COMPLETE["URML"], 0.15)
      and close(impact.COLLAPSE_RATE_GIVEN_COMPLETE["MH"], 0.03))
check("impact: every collapse fraction is a probability",
      all(0.0 <= value <= 1.0
          for value in impact.COLLAPSE_RATE_GIVEN_COMPLETE.values()))
# Collapsing can only hurt more people, so the collapsed row of a Complete
# building dominates the intact row, severity by severity.
check("impact: Table 12-7 never rates below Table 12-6 for the same severity",
      all(all(collapsed >= intact
              for collapsed, intact in zip(impact.INDOOR_CASUALTY_RATES_COMPLETE_COLLAPSED[code],
                                           impact.INDOOR_CASUALTY_RATES_COMPLETE_INTACT[code]))
          for code in impact.CASUALTY_BUILDING_TYPES))

# Table 12-2: the manual's own shares, with the products written out.
check("impact: residential is nearly full at 2 a.m. and half full at 5 p.m.",
      close(impact.POPULATION_DISTRIBUTION["Residential"]["2am"][0], 0.999 * 0.99)
      and close(impact.POPULATION_DISTRIBUTION["Residential"]["5pm"][0], 0.70 * 0.50))
check("impact: a school holds nobody at 2 a.m. and a hotel a fifth at 2 p.m.",
      impact.POPULATION_DISTRIBUTION["Educational"]["2am"] == (0.0, 0.0)
      and close(impact.POPULATION_DISTRIBUTION["Hotels"]["2pm"][0], 0.19))
check("impact: population_distribution rejects an unknown occupancy or time",
      _seismic_raises(KeyError, impact.population_distribution, "Museum", "2am")
      and _seismic_raises(KeyError, impact.population_distribution, "Residential", "noon"))
check("impact: occupancy text resolves to the Hazus class, longest token first",
      impact.occupancy_class("Primary school") == "Educational"
      and impact.occupancy_class("kindergarten") == "Educational"
      and impact.occupancy_class("RESIDENTIAL") == "Residential"
      and impact.occupancy_class("Retail unit") == "Commercial"
      and impact.occupancy_class("Hotel") == "Hotels")
check("impact: an unrecognised occupancy returns None rather than guessing",
      impact.occupancy_class("zzz") is None and impact.occupancy_class(None) is None
      and impact.occupancy_class("") is None)

# The event tree, checked against its own algebra on a hand-built distribution.
_one = {state: np.array([0.0]) for state in seismic.DAMAGE_STATES}
_one["complete"] = np.array([1.0])
_intact = impact.indoor_rates(_one, np.array(["C1L"]))[0]
check("impact: a certainly-Complete building is rated at the collapse-weighted mean",
      all(close(_intact[s],
                (1.0 - impact.COLLAPSE_RATE_GIVEN_COMPLETE["C1L"])
                * impact.INDOOR_CASUALTY_RATES_COMPLETE_INTACT["C1L"][s] / 100.0
                + impact.COLLAPSE_RATE_GIVEN_COMPLETE["C1L"]
                * impact.INDOOR_CASUALTY_RATES_COMPLETE_COLLAPSED["C1L"][s] / 100.0)
          for s in range(4)))
_one_none = {state: np.array([0.0]) for state in seismic.DAMAGE_STATES}
_one_none["none"] = np.array([1.0])
check("impact: no damage means no indoor and no outdoor casualties",
      np.allclose(impact.indoor_rates(_one_none, np.array(["C1L"])), 0.0)
      and np.allclose(impact.outdoor_rates(_one_none, np.array(["C1L"])), 0.0))
check("impact: outdoor rates are zero at slight damage and above C3's slight row",
      np.allclose(impact.outdoor_rates(
          {"none": np.array([0.0]), "slight": np.array([1.0]),
           "moderate": np.array([0.0]), "extensive": np.array([0.0]),
           "complete": np.array([0.0])}, np.array(["C1L"])), 0.0))
# Fatalities must rise with the probability of Complete damage: the model's
# one orientation that a sign error would invert invisibly.
_fatal = []
for _p in (0.0, 0.25, 0.5, 0.75, 1.0):
    _dist = {"none": np.array([1.0 - _p]), "slight": np.array([0.0]),
             "moderate": np.array([0.0]), "extensive": np.array([0.0]),
             "complete": np.array([_p])}
    _fatal.append(float(impact.casualties(_dist, np.array(["C1L"]),
                                          np.array([100.0]), ["Residential"], "2am")["total"][0][3]))
check("impact: fatalities rise monotonically with P(complete)",
      all(later > earlier for earlier, later in zip(_fatal, _fatal[1:])))
check("impact: a certainly-Complete C1L home kills only a fraction of 100 residents",
      0.0 < _fatal[-1] < 100.0)

# Conservation: the severities are shares of the people the scenario time
# actually puts in the building, so their sum cannot exceed that count.
_conservation = impact.casualties(_probs, np.array(["C1M"] * 5), np.array([250.0] * 5),
                                  ["Residential"] * 5, "2am")
_present = 250.0 * impact.POPULATION_DISTRIBUTION["Residential"]["2am"][0]
check("impact: casualties are bounded by the people the scenario time puts indoors",
      bool(np.all(_conservation["indoor"].sum(axis=1) <= _present + 1e-9)))
check("impact: indoor and outdoor casualties add to the reported total",
      np.allclose(_conservation["total"], _conservation["indoor"] + _conservation["outdoor"]))
check("impact: a school at 2 a.m. has no casualties whatever its damage",
      np.allclose(impact.casualties(_probs, np.array(["S1M"] * 5), np.array([500.0] * 5),
                                    ["Educational"] * 5, "2am")["total"], 0.0))
check("impact: doubling the occupants doubles the casualties",
      np.allclose(impact.casualties(_probs, np.array(["C1M"] * 5), np.array([500.0] * 5),
                                    ["Residential"] * 5, "2am")["total"],
                  2.0 * impact.casualties(_probs, np.array(["C1M"] * 5), np.array([250.0] * 5),
                                          ["Residential"] * 5, "2am")["total"]))

check("impact: occupants from floor area is footprint x storeys / density",
      np.allclose(impact.occupants_from_floor_area(np.array([100.0]), np.array([3.0]), 30.0),
                  [10.0]))
check("impact: a non-positive area per occupant is rejected, not divided by",
      _seismic_raises(ValueError, impact.occupants_from_floor_area,
                      np.array([100.0]), np.array([3.0]), 0.0))

# Shelter. Equation 13-1 and 13-2 with everything in Complete damage: a
# single-family dwelling is 100% uninhabitable, a multi-family block 100% too,
# so Equation 13-3 makes displaced households equal the dwelling units.
check("impact: a certainly-Complete home displaces its household",
      close(float(impact.displaced_households(_one, np.array([1.0]))[0]), 1.0)
      and close(float(impact.displaced_households(_one, np.array([12.0]))[0]), 12.0))
check("impact: Table 13-1 makes an extensively damaged single-family home habitable",
      close(float(impact.displaced_households(
          {"none": np.array([0.0]), "slight": np.array([0.0]), "moderate": np.array([0.0]),
           "extensive": np.array([1.0]), "complete": np.array([0.0])},
          np.array([1.0]))[0]), 0.0))
check("impact: but the same damage displaces 90% of a multi-family block",
      close(float(impact.displaced_households(
          {"none": np.array([0.0]), "slight": np.array([0.0]), "moderate": np.array([0.0]),
           "extensive": np.array([1.0]), "complete": np.array([0.0])},
          np.array([10.0]))[0]), 9.0))
check("impact: a non-residential building has no dwelling units to displace",
      close(float(impact.displaced_households(_one, np.array([0.0]))[0]), 0.0)
      and close(float(impact.shelter(_one, np.array([500.0]), np.array([0.0]))["public_shelter"][0]), 0.0))
check("impact: the occupancy rate scales displaced households",
      close(float(impact.displaced_households(_one, np.array([10.0]), 0.5)[0]), 5.0))
check("impact: HAZUS_SHELTER weights and the neutral modifier give alpha exactly 1.0",
      close(impact.shelter_alpha(), 1.0, 1e-15)
      and close(sum(impact.SHELTER_CATEGORY_WEIGHTS.values()), 1.0, 1e-15))
check("impact: the default modifier vector is exactly all-ones",
      all(value == impact.NEUTRAL_SHELTER_MODIFIER
          for value in (impact.NEUTRAL_SHELTER_MODIFIER,) * 4)
      and close(impact.shelter_alpha(), 1.0, 1e-15)
      and close(impact.shelter_alpha((0.73, 0.27, 0.0, 0.0)),
                impact.shelter_alpha(), 1e-15))
# Hazus's own Table 13-3 factors pull the answer well below the neutral bound,
# which is the point the help text makes; a 1.0-uniform default is not a
# calibrated US answer in disguise.
_income_mean = sum(impact.SHELTER_MODIFICATION_FACTORS["income"].values()) / 5.0
check("impact: a real Table 13-3 income mean reduces the shelter need",
      0.0 < _income_mean < 1.0
      and close(impact.shelter_alpha((1.0, 0.0, 0.0, 0.0), (_income_mean,) * 4), _income_mean))
check("impact: shelter need is displaced households times people per household",
      close(float(impact.shelter(_one, np.array([300.0]), np.array([10.0]))["public_shelter"][0]),
            10.0 * 30.0)
      and close(float(impact.shelter_need(np.array([4.0]), np.array([80.0]),
                                          np.array([2.0]))[0]), 160.0))
check("impact: alpha scales the public shelter count and nothing else",
      close(float(impact.shelter_need(np.array([4.0]), np.array([80.0]),
                                      np.array([2.0]), alpha=0.5)[0]), 80.0)
      and close(float(impact.displaced_households(_one, np.array([2.0]))[0]), 2.0))
check("impact: a building with no damage needs no shelter",
      close(float(impact.shelter(_one_none, np.array([300.0]), np.array([10.0]))["displaced_households"][0]), 0.0)
      and close(float(impact.shelter(_one_none, np.array([300.0]), np.array([10.0]))["public_shelter"][0]), 0.0))

# One end-to-end worked example, derived by hand from the manual's tables so
# the number is a real prediction rather than whatever the code last printed.
# 100 residents, a C1L home, 2 a.m., damage distribution 0.2/0.3/0.25/0.25:
#   indoors = 100 x 0.999 x 0.99 = 98.901 people (Table 12-2)
#   severity-1 rate, per cent
#     = 0.2*0.05 (T12-3) + 0.3*0.25 (T12-4) + 0.25*1.0 (T12-5)
#     + 0.25*(0.87*5.0 (T12-6) + 0.13*40.0 (T12-7))
#     = 0.01 + 0.075 + 0.25 + 1.0875 + 1.3 = 2.7225
#   severity-1 injuries = 98.901 x 0.027225 = 2.6925797
# and similarly 0.8915925, 0.1631124, 0.3238266 up the severities.
_mix = {"none": np.array([0.0]), "slight": np.array([0.2]),
        "moderate": np.array([0.3]), "extensive": np.array([0.25]),
        "complete": np.array([0.25])}
_worked = impact.casualties(_mix, np.array(["C1L"]), np.array([100.0]),
                            ["Residential"], "2am")
check("impact: the worked C1L example reproduces the hand-derived indoor counts",
      np.allclose(_worked["indoor"][0],
                  [2.6925797, 0.8915925, 0.1631124, 0.3238266], atol=1e-6))
check("impact: almost nobody is outside a home at 2 a.m.",
      float(_worked["outdoor"].sum()) < 0.01 * float(_worked["indoor"].sum()))

# The four damage-state columns a fragility run writes carry no 'none': the
# undamaged share is the complement. Handing only the four to the event tree
# raised KeyError('none') in the tool - the matrix caught it on the chained
# run, where every engine check above had passed because every one of them
# supplied the five states by hand.
_four = {"slight": np.array([0.2]), "moderate": np.array([0.3]),
         "extensive": np.array([0.25]), "complete": np.array([0.25])}
_filled = impact.fill_undamaged(_four)
check("impact: fill_undamaged completes the four damaged states with the complement",
      close(float(_filled["none"][0]), 0.0)
      and close(float(impact.fill_undamaged(
          {"slight": _four["slight"]})["none"][0]), 0.8))
check("impact: fill_undamaged leaves the states it was given alone",
      set(_four) == {"slight", "moderate", "extensive", "complete"}
      and all(close(float(_filled[key][0]), float(_four[key][0]))
              for key in _four))
check("impact: fill_undamaged returns an already-complete distribution as it is",
      close(float(impact.fill_undamaged(_mix)["none"][0]), 0.0)
      and set(impact.fill_undamaged(_mix)) == set(_mix))
check("impact: fill_undamaged clips a row summing above 1 rather than going negative",
      close(float(impact.fill_undamaged(
          {"complete": np.array([1.2])})["none"][0]), 0.0))
check("impact: the filled four-state distribution gives the hand-derived counts",
      np.allclose(impact.casualties(impact.fill_undamaged(
          {"slight": np.array([0.2]), "moderate": np.array([0.3]),
           "extensive": np.array([0.25]), "complete": np.array([0.25])}),
          np.array(["C1L"]), np.array([100.0]), ["Residential"], "2am")["indoor"][0],
          _worked["indoor"][0], atol=1e-12))

# --------------------------------------------------------------------------- #
# Exact isochrones (v4.7 Service Areas rebuild)
# --------------------------------------------------------------------------- #
# Path A(0,0)-B(100,0)-C(200,0), two 100 m edges, source at node A, cutoff 150:
# edge AB fully reached, edge BC reached to its midpoint only.
iso_lines = [np.array([[0.0, 0.0], [100.0, 0.0]]),
             np.array([[100.0, 0.0], [200.0, 0.0]])]
gi = graphs.build_node_graph(iso_lines)
a_node = int(np.argmin(np.abs(gi.node_xy[:, 0] - 0.0)))
d_iso = paths.many_to_many(gi.indptr, gi.adj_node, gi.adj_cost,
                           gi.num_nodes, [a_node])[0]
full_i, fa_i, fb_i = isochrone.reach_fractions(
    d_iso[gi.edge_from], d_iso[gi.edge_to], gi.edge_cost, 150.0)
# Edge ids follow polyline order: edge 0 = AB, edge 1 = BC.
check("iso: first edge fully reached, second is not",
      bool(full_i[0]) and not bool(full_i[1]))
check("iso: second edge trimmed at exactly half",
      close(fa_i[1], 0.5) and close(fb_i[1], 0.0))

# Meet-in-the-middle: one 100 m edge, both ends at cost 0, cutoff 60 covers
# 0.6 from each side -> the whole edge; cutoff 40 leaves a 0.2 gap.
full_m, fa_m, fb_m = isochrone.reach_fractions([0.0], [0.0], [100.0], 60.0)
check("iso: 60+60 on a 100 m edge meets in the middle", bool(full_m[0]))
full_g, fa_g, fb_g = isochrone.reach_fractions([0.0], [0.0], [100.0], 40.0)
check("iso: 40+40 leaves a gap - two pieces",
      not bool(full_g[0])
      and isochrone.edge_intervals(False, float(fa_g[0]), float(fb_g[0]))
      == [(0.0, 0.4), (0.6, 1.0)])

# Interval algebra
check("iso: merge_intervals unions overlaps",
      isochrone.merge_intervals([(0.0, 0.3), (0.2, 0.5), (0.8, 0.9)])
      == [(0.0, 0.5), (0.8, 0.9)])
check("iso: subtract_intervals cuts a hole",
      isochrone.subtract_intervals([(0.0, 1.0)], [(0.3, 0.6)])
      == [(0.0, 0.3), (0.6, 1.0)])
check("iso: subtracting a cover leaves nothing",
      isochrone.subtract_intervals([(0.2, 0.8)], [(0.0, 1.0)]) == [])
check("iso: interval_length sums the pieces",
      close(isochrone.interval_length([(0.0, 0.4), (0.6, 1.0)]), 0.8))

# Polyline cutting on an L: (0,0)-(10,0)-(10,10), total length 20.
ell = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]])
cut = isochrone.cut_polyline(ell, 0.25, 0.75)
check("iso: cut keeps the interior corner vertex",
      cut is not None and np.allclose(cut, [[5.0, 0.0], [10.0, 0.0], [10.0, 5.0]]))
check("iso: point_at the halfway mark is the corner",
      np.allclose(isochrone.point_at(ell, 0.5), [10.0, 0.0]))
check("iso: degenerate cut returns None",
      isochrone.cut_polyline(ell, 0.5, 0.5) is None)
full_cut = isochrone.cut_polyline(ell, 0.0, 1.0)
check("iso: full-range cut reproduces the polyline",
      full_cut is not None and np.allclose(full_cut, ell))

# Mid-edge facility entry: 100 m edge, entry at t=0.5.
check("iso: entry interval 30 m budget spans 0.2-0.8",
      isochrone.entry_interval(0.5, 0.0, 100.0, 30.0) == (0.2, 0.8))
check("iso: snap cost eats the whole budget -> no piece",
      isochrone.entry_interval(0.5, 30.0, 100.0, 30.0) is None)
check("iso: generous budget clips to the full edge",
      isochrone.entry_interval(0.5, 0.0, 100.0, 200.0) == (0.0, 1.0))

# End-to-end: path graph again, plus a second entry mid-way on edge BC.
riv = isochrone.reach_intervals(
    d_iso, gi.edge_from, gi.edge_to, gi.edge_cost, 150.0)
check("iso: reach_intervals full edge + half edge",
      riv.get(0) == [(0.0, 1.0)] and riv.get(1) == [(0.0, 0.5)])
# Entry at t=0.9 with 100 already spent: budget 50 -> piece (0.4, 1.0),
# which overlaps the node piece (0, 0.5) -> the whole edge is reached.
riv2 = isochrone.reach_intervals(
    d_iso, gi.edge_from, gi.edge_to, gi.edge_cost, 150.0,
    entries=[(1, 0.9, 100.0)])
check("iso: a mid-edge entry merges into the node reach",
      riv2.get(1) == [(0.0, 1.0)])

# Band splitting: isolated 100 m edge, facility at its midpoint, breaks 30/60.
d_inf = np.array([np.inf, np.inf])
iv30 = isochrone.reach_intervals(
    d_inf, np.array([0]), np.array([1]), np.array([100.0]), 30.0,
    entries=[(0, 0.5, 0.0)])
iv60 = isochrone.reach_intervals(
    d_inf, np.array([0]), np.array([1]), np.array([100.0]), 60.0,
    entries=[(0, 0.5, 0.0)])
band2 = isochrone.subtract_intervals(iv60.get(0, []), iv30.get(0, []))
check("iso: inner band is the 0.2-0.8 window around the entry",
      iv30.get(0) == [(0.2, 0.8)])
check("iso: outer band is the two leftover tips",
      band2 == [(0.0, 0.2), (0.8, 1.0)]
      and close(isochrone.interval_length(band2), 0.4))

# --------------------------------------------------------------------------- #
# Scenario ranking (v4.8 Phase G)
# --------------------------------------------------------------------------- #
# parse_weights checks
w1, u1 = scenario.parse_weights("walk_score_mean=3")
check("parse_weights happy path", w1 == {"walk_score_mean": 3.0} and u1 == [])

w2, u2 = scenario.parse_weights("access_gini=2, made_up=1")
check("parse_weights unknown list", w2 == {"access_gini": 2.0, "made_up": 1.0} and u2 == ["made_up"])

w3, u3 = scenario.parse_weights("")
check("parse_weights empty text", w3 == {} and u3 == [])

try:
    scenario.parse_weights("walk_score_mean=0")
    pw_zero = False
except ValueError:
    pw_zero = True
check("parse_weights <=0 ValueError", pw_zero)

try:
    scenario.parse_weights("banana")
    pw_malformed = False
except ValueError:
    pw_malformed = True
check("parse_weights malformed ValueError", pw_malformed)

# rank checks
snapA = scenario.snapshot("Alpha", {"walk_score_mean": 60.0, "access_gini": 0.20,
                                    "walk_low_share": 30.0, "units_total": 100.0})
snapB = scenario.snapshot("Beta",  {"walk_score_mean": 80.0, "access_gini": 0.40,
                                    "walk_low_share": 30.0, "units_total": 200.0})
snapC = scenario.snapshot("Gamma", {"walk_score_mean": 70.0, "access_gini": 0.25,
                                    "walk_low_share": 30.0, "units_total": 300.0})

# ValueError on 1 snapshot
try:
    scenario.rank([snapA])
    rank_one = False
except ValueError:
    rank_one = True
check("rank ValueError on 1 snapshot", rank_one)

# ValueError on duplicate names
try:
    scenario.rank([snapA, snapA])
    rank_dup = False
except ValueError:
    rank_dup = True
check("rank ValueError on duplicate names", rank_dup)

res = scenario.rank([snapA, snapB, snapC])

# scores / ranks
sc_map = {sc["name"]: sc for sc in res["scenarios"]}
check("rank: Gamma score 62.5", close(sc_map["Gamma"]["score"], 62.5))
check("rank: Alpha score 50.0", close(sc_map["Alpha"]["score"], 50.0))
check("rank: Beta score 50.0", close(sc_map["Beta"]["score"], 50.0))

check("rank: Gamma rank 1", sc_map["Gamma"]["rank"] == 1)
check("rank: Alpha rank 2", sc_map["Alpha"]["rank"] == 2)
check("rank: Beta rank 2", sc_map["Beta"]["rank"] == 2)

# scenario sorting order: by (rank, name) -> Gamma, Alpha, Beta
check("rank: scenarios order", [sc["name"] for sc in res["scenarios"]] == ["Gamma", "Alpha", "Beta"])

# n_metrics
check("rank: n_metrics == 2", all(sc["n_metrics"] == 2 for sc in res["scenarios"]))
check("rank: metrics length == 2", len(res["metrics"]) == 2)

# norms
metrics_map = {m["key"]: m for m in res["metrics"]}
check("rank: walk_score_mean norm Alpha == 0", close(metrics_map["walk_score_mean"]["norms"]["Alpha"], 0.0))
check("rank: walk_score_mean norm Beta == 1", close(metrics_map["walk_score_mean"]["norms"]["Beta"], 1.0))
check("rank: walk_score_mean norm Gamma == 0.5", close(metrics_map["walk_score_mean"]["norms"]["Gamma"], 0.5))

check("rank: access_gini norm Alpha == 1", close(metrics_map["access_gini"]["norms"]["Alpha"], 1.0))
check("rank: access_gini norm Beta == 0", close(metrics_map["access_gini"]["norms"]["Beta"], 0.0))
check("rank: access_gini norm Gamma == 0.75", close(metrics_map["access_gini"]["norms"]["Gamma"], 0.75))

# wins
check("rank: Alpha wins == 1", sc_map["Alpha"]["wins"] == 1)
check("rank: Beta wins == 1", sc_map["Beta"]["wins"] == 1)
check("rank: Gamma wins == 0", sc_map["Gamma"]["wins"] == 0)

# skipped reasons
skipped_map = {item["key"]: item["reason"] for item in res["skipped"]}
check("rank: walk_low_share constant", skipped_map.get("walk_low_share") == "constant")
check("rank: units_total neutral", skipped_map.get("units_total") == "neutral")

# Delta variant (not-shared)
snapD = scenario.snapshot("Delta", {"walk_score_mean": 90.0})
res_delta = scenario.rank([snapA, snapB, snapD])
skipped_delta_map = {item["key"]: item["reason"] for item in res_delta["skipped"]}
check("rank: access_gini not-shared with Delta", skipped_delta_map.get("access_gini") == "not-shared")

# weighted rerun
res_weighted = scenario.rank([snapA, snapB, snapC], weights={"walk_score_mean": 3.0})
sc_w_map = {sc["name"]: sc for sc in res_weighted["scenarios"]}
check("weighted rank: Alpha score 25.0", close(sc_w_map["Alpha"]["score"], 25.0))
check("weighted rank: Beta score 75.0", close(sc_w_map["Beta"]["score"], 75.0))
check("weighted rank: Gamma score 56.25", close(sc_w_map["Gamma"]["score"], 56.25))
check("weighted rank: scenarios order (Beta, Gamma, Alpha)",
      [sc["name"] for sc in res_weighted["scenarios"]] == ["Beta", "Gamma", "Alpha"])

# --------------------------------------------------------------------------- #
# Paths: multi-source predecessor tree (v4.9)
# --------------------------------------------------------------------------- #
# Hand fixture: path graph 0-1-2-3-4, four edges e0=(0,1) e1=(1,2) e2=(2,3) e3=(3,4), all weights 1, sources=[0, 4]
indptr_fixture = np.array([0, 1, 3, 5, 7, 8], dtype=np.int64)
adj_node_fixture = np.array([1, 0, 2, 1, 3, 2, 4, 3], dtype=np.int32)
adj_edge_fixture = np.array([0, 0, 1, 1, 2, 2, 3, 3], dtype=np.int32)
weights_fixture = np.array([1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0], dtype=np.float64)
sources_fixture = [0, 4]

dist_tree, label_tree, pred_node, pred_edge = paths.multi_source_tree(
    indptr_fixture, adj_node_fixture, adj_edge_fixture, weights_fixture, 5, sources_fixture
)
check("multi_source_tree: dist == [0, 1, 2, 1, 0]", np.allclose(dist_tree, [0.0, 1.0, 2.0, 1.0, 0.0]))
check("multi_source_tree: label == [0, 0, 0, 1, 1]", np.all(label_tree == [0, 0, 0, 1, 1]))
check("multi_source_tree: pred_node == [-1, 0, 1, 4, -1]", np.all(pred_node == [-1, 0, 1, 4, -1]))
check("multi_source_tree: pred_edge == [-1, 0, 1, 3, -1]", np.all(pred_edge == [-1, 0, 1, 3, -1]))

nodes_tree, edges_tree = paths.path_to_root(pred_node, pred_edge, 2)
check("path_to_root: 2 -> ([0, 1, 2], [0, 1])", nodes_tree == [0, 1, 2] and edges_tree == [0, 1])

# dist/label equal multi_source's output element-wise on this graph
_orig_scipy_test = paths.HAS_SCIPY
paths.HAS_SCIPY = False
dist_ms, label_ms = paths.multi_source(indptr_fixture, adj_node_fixture, weights_fixture, 5, sources_fixture)
paths.HAS_SCIPY = _orig_scipy_test
check("multi_source_tree equal multi_source: dist", np.allclose(dist_tree, dist_ms))
check("multi_source_tree equal multi_source: label", np.all(label_tree == label_ms))

# AND on one irregular graph reused from the existing paths tests
dist_tree_gw, label_tree_gw, _, _ = paths.multi_source_tree(
    gw.indptr, gw.adj_node, gw.adj_edge, gw.adj_cost, gw.num_nodes, [0, 7, 13]
)
dist_ms_gw, label_ms_gw = paths.multi_source(gw.indptr, gw.adj_node, gw.adj_cost, gw.num_nodes, [0, 7, 13])
check("multi_source_tree equal multi_source on irregular graph: dist", np.allclose(dist_tree_gw, dist_ms_gw))
check("multi_source_tree equal multi_source on irregular graph: label", np.all(label_tree_gw == label_ms_gw))

# With cutoff=1.5: node 2 unreachable (dist inf, preds -1)
dist_cut, label_cut, pred_node_cut, pred_edge_cut = paths.multi_source_tree(
    indptr_fixture, adj_node_fixture, adj_edge_fixture, weights_fixture, 5, sources_fixture, cutoff=1.5
)
check("multi_source_tree cutoff: dist[2] == inf", not np.isfinite(dist_cut[2]))
check("multi_source_tree cutoff: pred_node[2] == -1", pred_node_cut[2] == -1)
check("multi_source_tree cutoff: pred_edge[2] == -1", pred_edge_cut[2] == -1)

# Check with target is itself a root
nodes_root, edges_root = paths.path_to_root(pred_node, pred_edge, 0)
check("path_to_root: 0 -> ([0], [])", nodes_root == [0] and edges_root == [])

# check cyclic guard
nodes_cycle, edges_cycle = paths.path_to_root(np.array([1, 0]), np.array([0, 0]), 0)
check("path_to_root cyclic guard", nodes_cycle == [] and edges_cycle == [])

# --------------------------------------------------------------------------- #
# Walking comfort engine (v4.9)
# --------------------------------------------------------------------------- #
# grade_stats fixtures
mean_abs, max_abs, climb, descent = comfort.grade_stats([0, 1, 3], [0, 10, 20])
check("grade_stats: ascending profile",
      close(mean_abs, 0.15) and close(max_abs, 0.2) and close(climb, 3.0) and close(descent, 0.0))

mean_abs_2, max_abs_2, climb_2, descent_2 = comfort.grade_stats([5, 4, 4.5], [0, 10, 20])
check("grade_stats: mixed profile",
      close(mean_abs_2, 0.075) and close(max_abs_2, 0.1) and close(climb_2, 0.5) and close(descent_2, 1.0))

check("grade_stats: short profile", comfort.grade_stats([1.0], [0.0]) == (0.0, 0.0, 0.0, 0.0))

# tobler_speed fixtures
check("tobler_speed: -0.05", close(comfort.tobler_speed(-0.05), 6.0))
check("tobler_speed: 0.0", close(comfort.tobler_speed(0.0), 5.036744, 1e-5))
check("tobler_speed: 0.10", close(comfort.tobler_speed(0.10), 3.549335, 1e-5))

# profile_time_min
check("profile_time_min: Mixed 10m segments",
      close(comfort.profile_time_min([0.1, -0.1], [10, 10]), 0.288170, 1e-5))

# class_of
breaks = (5.0, 8.0, 12.0)
check("class_of: 4.9 -> 1", comfort.class_of(4.9, breaks) == 1)
check("class_of: 5.0 -> 1", comfort.class_of(5.0, breaks) == 1)
check("class_of: 7.2 -> 2", comfort.class_of(7.2, breaks) == 2)
check("class_of: 12.0 -> 3", comfort.class_of(12.0, breaks) == 3)
check("class_of: 12.1 -> 4", comfort.class_of(12.1, breaks) == 4)

# parse_breaks
check("parse_breaks: default", comfort.parse_breaks("") == (5.0, 8.0, 12.0))
check("parse_breaks: custom", comfort.parse_breaks("3,6") == (3.0, 6.0))
try:
    comfort.parse_breaks("6,3")
    pb_desc = False
except ValueError:
    pb_desc = True
check("parse_breaks: ValueError non-ascending", pb_desc)
try:
    comfort.parse_breaks("a,b")
    pb_nan = False
except ValueError:
    pb_nan = True
check("parse_breaks: ValueError non-numeric", pb_nan)

# kernel_weight
h = 100.0
dists_k = np.array([50.0])
check("kernel_weight: uniform", close(comfort.kernel_weight(dists_k, h, "uniform")[0], 1.0))
check("kernel_weight: triangular", close(comfort.kernel_weight(dists_k, h, "triangular")[0], 0.5))
check("kernel_weight: epanechnikov", close(comfort.kernel_weight(dists_k, h, "epanechnikov")[0], 0.75))
check("kernel_weight: gaussian", close(comfort.kernel_weight(dists_k, h, "gaussian")[0], 0.324652, 1e-5))
check("kernel_weight: beyond h", np.all(comfort.kernel_weight(np.array([150.0]), h, "epanechnikov") == 0.0))

# segment_density
samples = np.array([[0.0, 0.0], [10.0, 0.0]])
pts = np.array([[5.0, 40.0]])
w = np.array([1.0])
check("segment_density: exact 0.8375", close(comfort.segment_density(samples, pts, w, 100.0, "epanechnikov"), 0.8375))
check("segment_density: empty points",
      comfort.segment_density(samples, np.empty((0, 2)), np.empty(0), 100.0, "epanechnikov") == 0.0)

# combine_components
idx, used, dropped = comfort.combine_components(
    {"positive": np.array([2.0, 0.0, 1.0]), "negative": np.array([0.0, 4.0, 4.0])},
    {"positive": +1, "negative": -1}
)
check("combine_components: exact [100, 0, 25]", np.allclose(idx, [100.0, 0.0, 25.0]))
check("combine_components: used positive, negative", used == ["positive", "negative"])
check("combine_components: dropped none", len(dropped) == 0)

idx_w, _, _ = comfort.combine_components(
    {"positive": np.array([2.0, 0.0, 1.0]), "negative": np.array([0.0, 4.0, 4.0])},
    {"positive": +1, "negative": -1},
    weights={"positive": 3.0}
)
check("combine_components: weighted [100, 0, 37.5]", np.allclose(idx_w, [100.0, 0.0, 37.5]))

idx_drop, used_drop, dropped_drop = comfort.combine_components(
    {"positive": np.array([2.0, 0.0, 1.0]), "negative": np.array([0.0, 4.0, 4.0]), "raster_plus": np.array([7.0, 7.0, 7.0])},
    {"positive": +1, "negative": -1, "raster_plus": +1}
)
check("combine_components: constant dropped", np.allclose(idx_drop, [100.0, 0.0, 25.0]) and dropped_drop == ["raster_plus"])

idx_none, used_none, dropped_none = comfort.combine_components(
    {"positive": np.array([2.0, 0.0, 1.0]), "negative": None},
    {"positive": +1, "negative": -1}
)
check("combine_components: absent None ignored",
      np.allclose(idx_none, [100.0, 0.0, 50.0]) and used_none == ["positive"] and dropped_none == [])

try:
    comfort.combine_components({"positive": None, "negative": None}, {"positive": 1, "negative": -1})
    cc_all_none = False
except ValueError:
    cc_all_none = True
check("combine_components: ValueError all None", cc_all_none)

# ValueError checks
try:
    comfort.combine_components({"positive": np.array([5.0, 5.0, 5.0])}, {"positive": 1})
    cc_const_only = False
except ValueError:
    cc_const_only = True
check("combine_components: ValueError all constant", cc_const_only)

try:
    comfort.combine_components({}, {})
    cc_empty = False
except ValueError:
    cc_empty = True
check("combine_components: ValueError empty dict", cc_empty)

# --------------------------------------------------------------------------- #
# Link criticality (network robustness)
# --------------------------------------------------------------------------- #
# Diamond + tail with integer costs (costs override lengths):
#   A-B(e0,1) B-D(e1,1) | A-C(e2,1) C-D(e3,2) | D-E(e4,1)
# Shortest A->D uses the B route (2 < 3); E hangs off D by the lone edge e4.
_rob_lines = [np.array([[0.0, 0.0], [10.0, 0.0]]),      # e0 A-B
              np.array([[10.0, 0.0], [20.0, 0.0]]),     # e1 B-D
              np.array([[0.0, 0.0], [10.0, -10.0]]),    # e2 A-C
              np.array([[10.0, -10.0], [20.0, 0.0]]),   # e3 C-D
              np.array([[20.0, 0.0], [30.0, 0.0]])]     # e4 D-E
_rg = graphs.build_node_graph(_rob_lines, costs=[1.0, 1.0, 1.0, 2.0, 1.0])


def _rn(xy):
    return int(graphs.nearest_nodes(_rg, np.array([xy]))[0])


_A, _D, _E = _rn([0, 0]), _rn([20, 0]), _rn([30, 0])


def _crit(o, d, same):
    return robustness.edge_criticality(
        _rg.indptr, _rg.adj_node, _rg.adj_edge, _rg.adj_cost,
        _rg.num_nodes, _rg.num_edges, o, d, same_layer=same)


# One origin A to destinations {D, E}: base A->D=2, A->E=3 (total 5).
_r1 = _crit([_A], [_D, _E], False)
check("linkcriticality: base_total == 5 over 2 reachable pairs",
      close(_r1["base_total"], 5.0) and _r1["n_pairs"] == 2 and _r1["n_reachable"] == 2)
# Losing e0 or e1 forces the C route (+1 on each pair) -> extra 2, criticality 2/5.
check("linkcriticality: bridge e0/e1 extra_cost == 2, criticality == 0.4",
      close(_r1["extra_cost"][0], 2.0) and close(_r1["extra_cost"][1], 2.0)
      and close(_r1["criticality"][0], 0.4) and close(_r1["criticality"][1], 0.4))
# e4 is the only link to E: removing it disconnects the A->E pair, no detour cost.
check("linkcriticality: cut edge e4 disconnects 1 pair, zero extra cost",
      _r1["n_disconnected"][4] == 1 and close(_r1["extra_cost"][4], 0.0)
      and close(_r1["criticality"][4], 0.0))
# Edges on no shortest path (e2, e3) are never critical.
check("linkcriticality: off-path edges e2/e3 score zero",
      close(_r1["criticality"][2], 0.0) and _r1["used_by"][2] == 0
      and close(_r1["criticality"][3], 0.0) and _r1["used_by"][3] == 0)
check("linkcriticality: used_by counts shortest paths (e0/e1 == 2, e4 == 1)",
      _r1["used_by"][0] == 2 and _r1["used_by"][1] == 2 and _r1["used_by"][4] == 1)

# All-pairs among {A, D, E} (same_layer): 6 ordered pairs, base cost 12.
_r2 = _crit([_A, _D, _E], [_A, _D, _E], True)
check("linkcriticality: same_layer 6 pairs, base_total == 12",
      _r2["n_pairs"] == 6 and _r2["n_reachable"] == 6 and close(_r2["base_total"], 12.0))
check("linkcriticality: same_layer bridge criticality == 4/12",
      close(_r2["criticality"][0], 4.0 / 12.0) and close(_r2["extra_cost"][0], 4.0))
check("linkcriticality: same_layer cut edge severs 4 pairs (all with E)",
      _r2["n_disconnected"][4] == 4 and close(_r2["extra_cost"][4], 0.0))

# SciPy fast path and pure-Python fallback must agree exactly.
_orig_scipy = paths.HAS_SCIPY
paths.HAS_SCIPY = False
_r3 = _crit([_A], [_D, _E], False)
paths.HAS_SCIPY = _orig_scipy
check("linkcriticality: scipy == pure fallback",
      np.allclose(_r1["criticality"], _r3["criticality"])
      and np.allclose(_r1["extra_cost"], _r3["extra_cost"])
      and _r1["n_disconnected"].tolist() == _r3["n_disconnected"].tolist()
      and _r1["used_by"].tolist() == _r3["used_by"].tolist())

# --------------------------------------------------------------------------- #
# Platform advances: directed routing, exact audit, provenance, uncertainty,
# transfer walking and climate calibration.
# --------------------------------------------------------------------------- #
_directed = graphs.build_node_graph(path_lines, directions=[1, 1])
_forward = paths.many_to_many(
    _directed.indptr, _directed.adj_node, _directed.adj_cost,
    _directed.num_nodes, [0])[0]
_backward = paths.many_to_many(
    _directed.indptr, _directed.adj_node, _directed.adj_cost,
    _directed.num_nodes, [2])[0]
check("directed graph: forward route exists and reverse route is blocked",
      close(_forward[2], 2.0) and not np.isfinite(_backward[0]))

_asymmetric = graphs.build_node_graph(
    [path_lines[0]], costs=[2.0], reverse_costs=[7.0])
check("directed graph: asymmetric forward/reverse costs",
      close(_asymmetric.adj_cost[0], 2.0)
      and close(_asymmetric.adj_cost[1], 7.0))
_labels, _component_count = graphs.weak_components(_directed)
check("directed graph: weak components ignore travel direction",
      _component_count == 1 and len(set(_labels.tolist())) == 1)
_directed_reach = isochrone.reach_intervals(
    np.array([0.0, np.inf]), np.array([0]), np.array([1]),
    np.array([1.0]), 0.5, reverse_cost=np.array([1.0]),
    directions=np.array([1]))
check("directed isochrone: reach only follows the allowed edge direction",
      _directed_reach[0] == [(0.0, 0.5)])
check("directed isochrone: mid-edge entry is one-sided",
      isochrone.entry_interval(0.5, 0.0, 1.0, 0.2,
                               reverse_cost=1.0, direction=1) == (0.5, 0.7))

_audit_D = np.array([[1.0, 9.0], [4.0, 4.0], [9.0, 1.0]])
_audit = optimize.exact_location_audit(
    _audit_D, np.ones(2), 1, method="pmedian")
check("optimization audit: exact p-median finds balanced site",
      _audit["audited"] and _audit["selected"] == [1]
      and close(_audit["objective"], 8.0))
_budgeted = optimize.greedy_max_coverage(
    _audit_D, np.ones(2), 2, 5.0,
    candidate_costs=[6.0, 4.0, 6.0], budget=4.0)
check("optimization constraints: coverage respects implementation budget",
      _budgeted["selected"] == [1] and close(_budgeted["budget_used"], 4.0))
_budget_audit = optimize.exact_location_audit(
    _audit_D, np.ones(2), 2, method="pmedian",
    candidate_costs=[6.0, 4.0, 6.0], budget=4.0)
check("optimization audit: exact search respects implementation budget",
      _budget_audit["audited"] and _budget_audit["selected"] == [1])

_manifest = provenance.build_manifest(
    "planx:test", {"radius": 500}, [{"source": "streets"}], "1.0")
check("provenance: manifest validates and has stable fingerprint",
      provenance.validate_manifest(_manifest)
      and _manifest["analysis_fingerprint"] == provenance.build_manifest(
          "planx:test", {"radius": 500}, [{"source": "streets"}], "1.0")[
              "analysis_fingerprint"])
_snap = scenario.snapshot("Audit", {"access_mean": 75},
                          provenance=[{"manifest": _manifest}])
check("scenario: provenance survives JSON round trip",
      scenario.from_json(scenario.to_json(_snap))["provenance"][0][
          "manifest"]["analysis_fingerprint"] == _manifest["analysis_fingerprint"])

_validation = uncertainty.validation_metrics([1, 2, 3], [1, 2, 4])
check("calibration diagnostics: MAE/RMSE are correct",
      close(_validation["mae"], 1.0 / 3.0)
      and close(_validation["rmse"], math.sqrt(1.0 / 3.0)))
_rank_snaps = [
    scenario.snapshot("A", {"access_mean": 10, "access_gini": 0.2}),
    scenario.snapshot("B", {"access_mean": 20, "access_gini": 0.4}),
]
_stability_a = uncertainty.rank_stability(
    scenario.rank, _rank_snaps, {}, simulations=20, seed=7)
_stability_b = uncertainty.rank_stability(
    scenario.rank, _rank_snaps, {}, simulations=20, seed=7)
check("scenario uncertainty: seeded rank stability is reproducible",
      _stability_a == _stability_b)
_rank_report = scenario.rank(_rank_snaps)
_rank_report["stability"] = _stability_a
_rank_html = report.build_rank_html("Stability", _rank_report)
check("scenario uncertainty: HTML board includes sensitivity results",
      "Weight Sensitivity" in _rank_html and "Probability first" in _rank_html)

_transfer_graph = transit.walking_transfers(
    np.array([[0.0, 0.0], [90.0, 0.0], [500.0, 0.0]]), 100.0, 1.0)
check("transit: walking transfer graph respects radius",
      _transfer_graph[0] == [(1, 90.0)] and _transfer_graph[2] == [])
_walk_pattern = [{
    "route": "R", "stops": (1, 2),
    "arr": np.array([[100.0, 200.0]]),
    "dep": np.array([[100.0, 200.0]]),
}]
_walk_arrival = transit.earliest_arrival(
    _walk_pattern, {1: [(0, 0)], 2: [(0, 1)]}, 3, {0: 0.0},
    max_transfers=0, transfers={0: [(1, 50.0)]})
check("transit: walking transfer connects access stop to a route",
      close(_walk_arrival[2], 200.0))
check("weather: monthly measured-sky factors",
      weather.monthly_solar_factors(
          {"monthly_ghi": [50.0, 200.0]}, [100.0, 100.0]) == [0.5, 2.0])

# --------------------------------------------------------------------------- #
# Parking generation rates
# --------------------------------------------------------------------------- #
_pk_rates = parking.parse_rates(
    "residential=unit:1.5, office=sqm:2.5, assembly=seat:0.15")
check("parking: parse_rates yields (category, basis, rate) triples",
      _pk_rates == [("residential", "unit", 1.5),
                    ("office", "sqm", 2.5),
                    ("assembly", "seat", 0.15)])
check("parking: semicolons and padding are accepted",
      parking.parse_rates(" green = unit:10 ; park = sqm:2 ") ==
      [("green", "unit", 10.0), ("park", "sqm", 2.0)])


def _pk_raises(text):
    try:
        parking.parse_rates(text)
    except ValueError:
        return True
    return False


check("parking: a rate without a basis is rejected",
      _pk_raises("residential=1.5"))
check("parking: an unknown basis is rejected", _pk_raises("office=acre:2"))
check("parking: a non-numeric rate is rejected", _pk_raises("office=sqm:lots"))
check("parking: a negative rate is rejected", _pk_raises("office=sqm:-1"))
check("parking: an empty category keyword is rejected", _pk_raises("=unit:1"))
check("parking: an empty rate table is rejected", _pk_raises("   "))

# The three bases are not one denominator: unit and seat multiply, sqm is
# per 1000 m2 of gross floor area.
check("parking: unit basis multiplies",
      close(parking.demand_for_size("unit", 1.5, 120), 180.0))
check("parking: seat basis multiplies",
      close(parking.demand_for_size("seat", 0.15, 80), 12.0))
check("parking: sqm basis is per 1000 m2",
      close(parking.demand_for_size("sqm", 2.5, 4000.0), 10.0))
check("parking: sqm basis on exactly 1000 m2 equals the rate",
      close(parking.demand_for_size("sqm", 3.5, 1000.0), 3.5))

_pk_demand = parking.parking_demand(
    ["residential low-rise", "Office tower", "Assembly hall", "Vacant land"],
    np.array([120.0, 4000.0, 80.0, 999.0]), _pk_rates)
check("parking: worked example demands [180, 10, 12, 0] spaces",
      np.allclose(_pk_demand, [180.0, 10.0, 12.0, 0.0]))
check("parking: category matching is case-insensitive and by containment",
      parking.match_rate("HOTEL / OFFICE", _pk_rates)[0] == "office")
check("parking: the first matching rate row wins",
      parking.match_rate("retail office", parking.parse_rates(
          "retail=sqm:3.0, office=sqm:2.5"))[0] == "retail")
check("parking: a matched but zero-size zone demands zero",
      close(parking.parking_demand(["Office"], np.array([0.0]), _pk_rates)[0], 0.0))
check("parking: unmatched categories are reported, not silently dropped",
      parking.unmatched_categories(
          ["Office", "Vacant land", "Vacant land", "School"], _pk_rates) ==
      ["School", "Vacant land"])
check("parking: subtotals aggregate per category and sort",
      parking.category_subtotals(
          ["Office", "Office", "Vacant land"], np.array([10.0, 4.0, 0.0])) ==
      [("Office", 14.0), ("Vacant land", 0.0)])
check("parking: the demand total does not depend on feature order",
      close(parking.parking_demand(
                ["Office", "Office"], np.array([4000.0, 1000.0]), _pk_rates).sum(),
            parking.parking_demand(
                ["Office", "Office"], np.array([1000.0, 4000.0]), _pk_rates).sum()))

# --- supply balance (v4.12.0 phase 2) -------------------------------------- #
# Two zones against two inventory features holding 10 and 5 spaces. Zone 0 is
# 10 m from the first and 100 m from the second; zone 1 is 50 m and 200 m away.
_pk_costs = np.array([[10.0, 100.0], [50.0, 200.0]])
_pk_spaces = np.array([10.0, 5.0])

_pk_found, _pk_count = parking.supply_within(_pk_costs, _pk_spaces, 50.0)
check("parking: supply_within sums only features inside the radius",
      np.allclose(_pk_found, [10.0, 10.0]))
check("parking: supply_within counts the features it summed",
      np.array_equal(_pk_count, [1, 1]))
# The boundary is inclusive: a facility at exactly the radius is reachable.
_pk_at = parking.supply_within(_pk_costs, _pk_spaces, 50.0)
_pk_under = parking.supply_within(_pk_costs, _pk_spaces, 49.999)
check("parking: a feature exactly at the radius counts, just inside it does not",
      np.array_equal(_pk_at[1], [1, 1]) and np.array_equal(
          _pk_under[1], [1, 0]))
check("parking: supply_within ignores infinite costs",
      np.array_equal(
          parking.supply_within(
              np.array([[np.inf, 5.0]]), _pk_spaces, 10.0)[1], [1]))
_pk_empty = parking.supply_within(np.empty((2, 0)), np.empty(0), 50.0)
check("parking: an empty inventory yields zero spaces, not an error",
      np.allclose(_pk_empty[0], [0.0, 0.0]) and
      np.array_equal(_pk_empty[1], [0, 0]))

check("parking: nearest_supply_cost is the closest feature per zone",
      np.allclose(parking.nearest_supply_cost(_pk_costs), [10.0, 50.0]))
check("parking: nearest_supply_cost is inf where nothing is reachable",
      np.array_equal(parking.nearest_supply_cost(
          np.array([[np.inf, np.inf], [3.0, np.inf]])), [np.inf, 3.0]))
check("parking: nearest_supply_cost of an empty inventory is all inf",
      np.array_equal(parking.nearest_supply_cost(np.empty((2, 0))),
                     [np.inf, np.inf]))

# A 3-4-5 triangle, so the expected distance is exact rather than approximate.
check("parking: straight-line costs are Euclidean",
      np.allclose(parking.straight_line_costs(
          np.array([[0.0, 0.0], [6.0, 8.0]]), np.array([[3.0, 4.0]])),
          [[5.0], [5.0]]))
check("parking: straight-line costs of an empty inventory have width zero",
      parking.straight_line_costs(
          np.array([[1.0, 2.0], [3.0, 4.0]]), np.empty((0, 2))).shape == (2, 0))

_pk_status = parking.classify_supply([1, 0, 0, 2], [True, True, False, False])
check("parking: a zone with inventory in range is 'counted'",
      _pk_status[0] == parking.SUPPLY_COUNTED)
check("parking: surveyed ground with nothing in range is 'zero supply found'",
      _pk_status[1] == parking.SUPPLY_ZERO)
check("parking: unsurveyed ground is 'supply data absent', not a deficit",
      _pk_status[2] == parking.SUPPLY_ABSENT)
# The two are different findings, and keeping them apart is the point of S3:
# anything found in range is counted even if the coverage proxy missed it.
check("parking: inventory found in range outranks the coverage proxy",
      _pk_status[3] == parking.SUPPLY_COUNTED)

_pk_balance = parking.balance([10.0, 10.0, 10.0], [4.0, 0.0, 0.0], _pk_status[:3])
check("parking: balance is supply minus demand, signed",
      close(_pk_balance[0], -6.0) and close(_pk_balance[1], -10.0))
check("parking: an unsurveyed zone gets no balance at all",
      _pk_balance[2] is None)

_pk_summary = parking.balance_summary(
    [10.0, 10.0, 10.0], [4.0, 0.0, 0.0],
    [parking.SUPPLY_COUNTED, parking.SUPPLY_ZERO, parking.SUPPLY_ABSENT])
check("parking: balance_summary is sorted by label",
      [label for label, _ in _pk_summary] == sorted(
          label for label, _ in _pk_summary))
_pk_rows = dict(_pk_summary)
check("parking: the survey totals cover the surveyed zones only",
      close(_pk_rows["parking supply (surveyed zones, spaces)"], 4.0) and
      close(_pk_rows["surplus (+) or deficit (-), surveyed zones, spaces"], -16.0))
check("parking: the unsurveyed zone is counted but excluded from the balance",
      close(_pk_rows["zones supply data absent"], 1.0))
check("parking: deficit zones are counted for the reader",
      close(_pk_rows["surveyed zones in deficit"], 2.0))
_pk_all_absent = dict(parking.balance_summary(
    [5.0, 5.0], [0.0, 0.0], [parking.SUPPLY_ABSENT] * 2))
check("parking: with nothing surveyed no balance is reported at all",
      "parking supply (surveyed zones, spaces)" not in _pk_all_absent and
      "surplus (+) or deficit (-), surveyed zones, spaces" not in _pk_all_absent)
check("parking: balance_summary is deterministic across calls",
      parking.balance_summary(
          [10.0, 10.0, 10.0], [4.0, 0.0, 0.0],
          [parking.SUPPLY_COUNTED, parking.SUPPLY_ZERO,
           parking.SUPPLY_ABSENT]) == _pk_summary)
_pk_surplus = dict(parking.balance_summary(
    [10.0], [25.0], [parking.SUPPLY_COUNTED]))
check("parking: a surplus is reported as a positive balance and no deficit",
      close(_pk_surplus["surplus (+) or deficit (-), surveyed zones, spaces"],
            15.0) and close(_pk_surplus["surveyed zones in deficit"], 0.0))

# --------------------------------------------------------------------------- #
# Liquefaction screening - Zhu et al. (2015) and Hazus 6.1 Section 4.2.2.1
# --------------------------------------------------------------------------- #
# The reference point every sensitivity below is taken at. Nothing special
# about it except that it sits well inside every clip, so a derivative taken
# here is the model's own and not a clip's own.
_ZHU_REF = {"pga_g": 0.3, "magnitude": 7.0, "cti": 5.0, "vs30": 250.0}
_ZHU_STEP = 1e-7


def _zhu_at(**over):
    args = dict(_ZHU_REF)
    args.update(over)
    return liq.zhu_logit(**args)


def _elasticity(parameter):
    """d(logit) / d(ln x) about the reference point, by a right difference.

    PGA, Mw and Vs30 all enter the model *inside* a logarithm, so this
    difference returns their published coefficient directly rather than a
    number that depends on the units the reference point happens to be in.
    """
    moved = _zhu_at(**{parameter: _ZHU_REF[parameter] * math.exp(_ZHU_STEP)})
    return (moved - _zhu_at()) / _ZHU_STEP


def _slope(parameter):
    """d(logit) / d(x) about the reference point - for the linear terms.

    CTI enters the model as itself, not as a logarithm, so its coefficient is
    a slope and the log-space difference above would return ``CTI * c2``.
    """
    moved = _zhu_at(**{parameter: _ZHU_REF[parameter] + _ZHU_STEP})
    return (moved - _zhu_at()) / _ZHU_STEP


def _liq_raises(function, *args):
    try:
        function(*args)
    except (ValueError, ZeroDivisionError, OverflowError):
        return True
    return False


# ---- The exponent trap ---------------------------------------------------- #
# Zhu et al.'s seismic term is c1*ln(PGA * Mw^2.56 / 10^2.24) - the magnitude
# scaling is folded *inside* the logarithm. The obvious reading of the
# published form, c1*ln(PGA) + 2.56*ln(Mw) + ..., is monotone in every input,
# bounded in (0, 1) after the logistic, and wrong: it scales magnitude by 1
# where the model scales it by c1 = 2.067. The two forms agree exactly at
# Mw 7 and are the same shape everywhere, so "higher Mw gives a higher
# probability" passes on both. Only a derivative separates them, which is why
# this check is a derivative.
check("Zhu: magnitude sensitivity is c1 times the exponent, not the exponent alone",
      close(_elasticity("magnitude"), 5.29152, 1e-5)
      and not close(_elasticity("magnitude"), liq.ZHU["magnitude_exponent"], 1e-3))
check("Zhu: the PGA, CTI and Vs30 sensitivities are their own published coefficients",
      close(_elasticity("pga_g"), liq.ZHU["ln_pga_magnitude"], 1e-5)
      and close(_slope("cti"), liq.ZHU["cti"], 1e-6)
      and close(_elasticity("vs30"), liq.ZHU["ln_vs30"], 1e-5))

_zhu_pga_sweep = [_zhu_at(pga_g=p) for p in (0.05, 0.1, 0.2, 0.4, 0.8)]
_zhu_cti_sweep = [_zhu_at(cti=c) for c in (0.0, 3.0, 6.0, 9.0, 12.0)]
_zhu_vs30_sweep = [_zhu_at(vs30=v) for v in (120.0, 180.0, 260.0, 400.0, 760.0)]
check("Zhu: X rises with PGA and with CTI, and falls with Vs30",
      all(a < b for a, b in zip(_zhu_pga_sweep, _zhu_pga_sweep[1:]))
      and all(a < b for a, b in zip(_zhu_cti_sweep, _zhu_cti_sweep[1:]))
      and all(a > b for a, b in zip(_zhu_vs30_sweep, _zhu_vs30_sweep[1:])))

# The published logistic is written against a ShakeMap %g layer, so the USGS
# implementation divides by 100 before taking the logarithm. Our field is in g.
# Applying that division here would be a unit error of a fixed size, and a
# fixed size is exactly what a reader cannot see: every probability moves the
# same direction, every ranking survives, and the tool reports 0.9999 where
# the answer is 0.03.
_zhu_g = _zhu_at()
_zhu_pctg = _zhu_at(pga_g=_ZHU_REF["pga_g"] / 100.0)
check("Zhu: reading a g-valued PGA as %g would move the logit by c1*ln(100)",
      close(_zhu_g - _zhu_pctg, liq.ZHU["ln_pga_magnitude"] * math.log(100.0), 1e-9)
      and close(_zhu_g - _zhu_pctg, 9.5189, 1e-4))
check("Zhu: the PGA clip is the source's %g ceiling restated in g, not 270",
      close(liq.ZHU_PGA_CLIP_G[1], 270.0 / 100.0, 1e-12)
      and close(liq.ZHU_CTI_CLIP[1], 15.0, 1e-12))

# The reference logit written out longhand. The ZHU dict cannot vouch for
# itself: if a coefficient is edited in the engine and in no test, every
# probability in the tool moves and nothing fails.
_zhu_mid = liq.zhu_probability(_ZHU_REF["pga_g"], _ZHU_REF["magnitude"],
                               _ZHU_REF["cti"], _ZHU_REF["vs30"])
_zhu_hand = (24.10
             + 2.067 * math.log(0.3 * 7.0 ** 2.56 / 10.0 ** 2.24)
             + 0.355 * 5.0
             - 4.784 * math.log(250.0))
check("Zhu: the reference logit is the published terms written out longhand",
      close(_zhu_mid["logit"], _zhu_hand, 1e-12)
      and close(_zhu_mid["probability"], liq.logistic(_zhu_hand), 1e-15))

# The 0.81 in Zhu et al. (2017) is a proportion-of-*area* correction, and it is
# reported beside the point probability rather than multiplied into it. Folded
# in, it would be a 19 % error on the headline number that no user could detect
# - both columns would still be "a probability".
check("Zhu: the 0.81 coverage factor is its own column, not applied to the probability",
      close(_zhu_mid["coverage"], _zhu_mid["probability"] * 0.81, 1e-15)
      and _zhu_mid["coverage"] < _zhu_mid["probability"]
      and close(_zhu_mid["coverage"] / _zhu_mid["probability"],
                liq.ZHU_COVERAGE_FACTOR, 1e-15))

# Clipping happens *upstream* of the logit: an out-of-range row must give the
# same answer as the row clipped by hand, or the model was evaluated outside
# its calibration range and the clip is decoration.
_zhu_extreme = liq.zhu_probability(5.0, 9.5, 99.0, 120.0)
check("Zhu: an out-of-range input is clipped before the logit, and says so per row",
      _zhu_extreme["pga_g"] == liq.ZHU_PGA_CLIP_G[1]
      and _zhu_extreme["cti"] == liq.ZHU_CTI_CLIP[1]
      and _zhu_extreme["pga_clipped"] and _zhu_extreme["cti_clipped"]
      and len(_zhu_extreme["notes"]) == 2
      and close(_zhu_extreme["probability"],
                liq.zhu_probability(2.7, 9.5, 15.0, 120.0)["probability"], 1e-15))
check("Zhu: an unclipped row reports no note, so an empty report means something",
      _zhu_mid["notes"] == [] and not _zhu_mid["pga_clipped"]
      and not _zhu_mid["cti_clipped"])
check("Zhu: the probability stays strictly inside (0, 1) even at absurd inputs",
      0.0 < _zhu_extreme["probability"] < 1.0
      and 0.0 < liq.zhu_probability(0.001, 5.0, 0.0, 2000.0)["probability"] < 1.0
      and liq.logistic(1e9) == 1.0 and liq.logistic(-1e9) == 0.0)

# Rule R7 at the engine level. There is no reference shaking level the way
# there is a reference velocity: PGA enters the model as ln(PGA), and zero
# would come back as a clean "no liquefaction here" - the one answer this tool
# must not invent.
check("Zhu: a zero or negative PGA is refused, not read as no shaking",
      _liq_raises(liq.zhu_logit, 0.0, 7.0, 5.0, 250.0)
      and _liq_raises(liq.zhu_logit, -0.2, 7.0, 5.0, 250.0)
      and _liq_raises(liq.zhu_logit, 0.3, 7.0, 5.0, 0.0)
      and _liq_raises(liq.zhu_logit, 0.3, 0.0, 5.0, 250.0)
      and not _liq_raises(liq.zhu_logit, 0.3, 7.0, 5.0, 250.0))

# ---- CTI, and the unit it is measured in ---------------------------------- #
_cti_flat, _grad_flat = hydro.cti(np.full((3, 3), 50.0), 10.0)
check("CTI: a flat plane has no downslope neighbour, so it is +inf rather than an invented floor",
      bool(np.all(np.isinf(_cti_flat))) and bool(np.all(_grad_flat == 0.0)))
check("CTI: the model's own ceiling is what clips an undrained cell, not the caller",
      liq.clip_cti(float("inf")) == (liq.ZHU_CTI_CLIP[1], True)
      and close(liq.zhu_probability(0.3, 7.0, float("inf"), 250.0)["probability"],
                liq.zhu_probability(0.3, 7.0, liq.ZHU_CTI_CLIP[1], 250.0)["probability"],
                1e-15)
      and liq.zhu_probability(0.3, 7.0, float("inf"), 250.0)["cti_clipped"])

# A plane dropping 1 m per 10 m cell, eastward. Every cell but the last column
# drains east, so flow accumulation at column c is c+1 cells, the specific
# catchment area is (c+1)*pixel and the gradient is 1/pixel. CTI is therefore
# ln((c+1) * pixel^2 / 1) exactly - read off the definition, not off the code.
_PIXEL = 10.0
_plane = np.array([[float(-c) for c in range(5)] for _ in range(4)])
_cti_plane, _grad_plane = hydro.cti(_plane, _PIXEL)
check("CTI: a uniform plane reproduces the analytic wetness index on every draining cell",
      all(close(float(_cti_plane[r, c]),
                math.log((c + 1) * _PIXEL * _PIXEL), 1e-9)
          for r in range(4) for c in range(4))
      and bool(np.all(np.isinf(_cti_plane[:, 4])))
      and close(float(_grad_plane[0, 0]), 1.0 / _PIXEL, 1e-12))
# The same plane described along the other axis. Without it a row/column
# transposition inside the accumulation pass would leave the plane test green:
# the analytic value is symmetric, so only the axis it appears on is not.
_cti_ns, _ = hydro.cti(_plane.T, _PIXEL)
check("CTI: the same plane tilted north-south reproduces the index along rows",
      all(close(float(_cti_ns[r, c]),
                math.log((r + 1) * _PIXEL * _PIXEL), 1e-9)
          for r in range(4) for c in range(4))
      and bool(np.all(np.isinf(_cti_ns[4, :]))))

# The unit trap this phase adds to docs/TRAPS.md, and the reason the QGIS
# surface converts the pixel size to metres before cti() ever sees it. CTI is
# the log of a specific catchment area, so the *same terrain* described in feet
# raises the index by ln(3.28084) everywhere - which the CTI coefficient turns
# into 0.42 logit units of pure unit error. Nothing else in the run notices:
# the slopes agree, the flow directions agree, and the map looks identical.
_cti_metres, _ = hydro.cti(np.array([[-0.3048 * c for c in range(5)]
                                     for _ in range(4)]), 10.0)
_cti_feet, _ = hydro.cti(_plane, 10.0 * 3.28084)
_unit_shift = float(_cti_feet[0, 0] - _cti_metres[0, 0])
check("CTI: a DEM in feet raises the index by ln(3.28084) - the metric-area unit trap",
      close(_unit_shift, math.log(3.28084), 1e-6)
      and close(0.355 * _unit_shift, 0.4218, 1e-3))

# ---- Vs30 from slope - Allen & Wald (2007), Table 2 ----------------------- #
check("Vs30: the table's own nodes come back exactly and are not flagged as clamped",
      all(close(liq.vs30_from_slope(x, setting)[0], y, 1e-12)
          and liq.vs30_from_slope(x, setting)[1] is False
          for setting in liq.TECTONIC_SETTINGS
          for x, y in liq.SLOPE_VS30_NODES[setting]))
check("Vs30: between two nodes the value interpolates linearly between them",
      close(liq.vs30_from_slope(0.034, "active")[0],
            360.0 + (0.034 - 0.018) / (0.050 - 0.018) * (490.0 - 360.0), 1e-12)
      and liq.vs30_from_slope(0.034, "active")[1] is False)
check("Vs30: outside the published nodes the value is held at the endpoint and says so",
      liq.vs30_from_slope(1e-9, "active") == (180.0, True)
      and liq.vs30_from_slope(10.0, "active") == (760.0, True)
      and liq.vs30_from_slope(float("nan"), "active")[1] is True)
check("Vs30: an unknown tectonic setting is refused, not defaulted",
      _liq_raises(liq.vs30_from_slope, 0.01, "somewhere"))

# Why the tectonic setting is an explicit choice with no default (rule R3).
# At the slope where the two columns of the source table diverge hardest they
# differ by a factor of 1.96 in velocity, which the Vs30 coefficient turns into
# 3.2 logit units - the difference between a screening estimate and a different
# answer. Picking one silently would have been picking the answer.
_widest = max(liq.vs30_from_slope(s, "stable")[0]
              / liq.vs30_from_slope(s, "active")[0]
              for s in [i * 1e-5 for i in range(1, 3000)])
check("Vs30: the active and stable columns differ by more than 3 logit units at their widest",
      _widest > 1.9 and 4.784 * math.log(_widest) > 3.0)

# ---- Hazus 6.1 Section 4.2.2.1 -------------------------------------------- #
# Every category must have an entry in every one of the four tables. A partial
# re-transcription is the one failure that produces plausible numbers for some
# units and a crash or a silent zero for others - and if it landed in
# HAZUS_PROPORTION alone, the missing category would read as "no hazard".
check("Hazus: the four category tables describe exactly the same six categories",
      set(liq.HAZUS_PROPORTION) == set(liq.HAZUS_CATEGORIES)
      and set(liq.HAZUS_CONDITIONAL) == set(liq.HAZUS_CATEGORIES)
      and set(liq.HAZUS_SETTLEMENT_IN) == set(liq.HAZUS_CATEGORIES)
      and set(liq.HAZUS_PGA_THRESHOLD) == set(liq.HAZUS_CATEGORIES) - {"None"})

# Table 4-11's zero crossings are Table 4-12's thresholds. The two tables were
# read independently, and they agree to within the manual's own rounding. This
# is the check that catches a mistyped slope or intercept: a line shifted by
# 0.01 in intercept moves its crossing by 0.001-0.002 g.
check("Hazus: Table 4-11's zero crossings reproduce Table 4-12's thresholds",
      max(abs(-liq.HAZUS_CONDITIONAL[c][1] / liq.HAZUS_CONDITIONAL[c][0]
              - liq.HAZUS_PGA_THRESHOLD[c])
          for c in liq.HAZUS_PGA_THRESHOLD) < 0.002)

# The published polynomials do not pass exactly through unity at the conditions
# they are referenced to. Applying them as printed is a deliberate choice, so
# the residual is asserted rather than tolerated: a later "fix" that quietly
# renormalised them would move every number in the tool and fail here.
check("Hazus: Equations 4-10 and 4-11 are applied as printed, reference residual and all",
      close(liq.hazus_magnitude_factor(7.5), 1.0147375, 1e-12)
      and close(liq.hazus_groundwater_factor(1.524), 1.04, 1e-12)
      and not close(liq.hazus_magnitude_factor(7.5), 1.0, 1e-3)
      and not close(liq.hazus_groundwater_factor(1.524), 1.0, 1e-3))
check("Hazus: the water-table depth is converted from metres to feet inside Equation 4-11",
      close(liq.hazus_groundwater_factor(1.524),
            liq.hazus_groundwater_factor(5.0 * 0.3048), 1e-15)
      and close(liq.hazus_groundwater_factor(3.048), 0.022 * 10.0 + 0.93, 1e-12))

# One unit by hand, from the manual: Very High, PGA 0.3 g, Mw 7.5, and the
# manual's own 5 ft reference water table.
#   P[Liquefaction | PGA = 0.3] = 9.09*0.3 - 0.82 = 1.907, clipped to 1.0
#   P = P[Liquefaction | PGA = a] / (K_M * K_W) * P_ml = 1.0 / (1.0147375 * 1.04) * 0.25
_hazus = liq.hazus_probability("Very High", 0.3, 7.5, 1.524)
check("Hazus: Equation 4-9 reproduces the hand-computed unit probability",
      _hazus["conditional"] == 1.0
      and close(_hazus["proportion"], 0.25, 1e-12)
      and close(_hazus["probability"], 0.25 / (1.0147375 * 1.04), 1e-12)
      and close(_hazus["probability"], 0.23689339891806044, 1e-12))
check("Hazus: the expected settlement is the probability times the Table 4-13 amplitude",
      close(_hazus["settlement_in"], _hazus["probability"] * 12.0, 1e-12)
      and close(_hazus["pga_threshold"], 0.09, 1e-12))
check("Hazus: the Table 4-11 conditional probability is clipped at both ends",
      liq.hazus_conditional("Very High", 0.05) == 0.0
      and liq.hazus_conditional("Very High", 0.5) == 1.0
      and close(liq.hazus_conditional("Low", 0.30), 5.57 * 0.30 - 1.18, 1e-12))
# The sixth row of Table 4-11 is a constant, not a line. Left out of the table
# it would be a KeyError on a category the user did supply - a crash instead of
# the zero the manual defines.
check("Hazus: the 'None' category is a constant zero, not a missing line",
      liq.hazus_conditional("None", 0.9) == 0.0
      and liq.hazus_probability("None", 0.9, 7.5, 1.524)["probability"] == 0.0
      and liq.hazus_probability("None", 0.9, 7.5, 1.524)["settlement_in"] == 0.0
      and liq.hazus_probability("None", 0.9, 7.5, 1.524)["pga_threshold"] is None)

# The category ordering is the one thing a reader is entitled to assume, and
# nothing else in the model enforces it: two transposed proportions would give
# a plausible map with the colours in the wrong order.
_hazus_order = [liq.hazus_probability(c, 0.5, 7.5, 1.524)["probability"]
                for c in liq.HAZUS_CATEGORIES]
check("Hazus: at one shaking level the categories rank from Very High down to None",
      all(a > b for a, b in zip(_hazus_order, _hazus_order[1:]))
      and _hazus_order[-1] == 0.0)

check("Hazus: a category is matched on its name alone - case and separators, nothing else",
      liq.normalise_category(" very  high ") == "Very High"
      and liq.normalise_category("VERY-HIGH") == "Very High"
      and liq.normalise_category("very_low") == "Very Low"
      and liq.normalise_category("None") == "None")
check("Hazus: an unrecognised category returns None rather than a guess",
      liq.normalise_category("VH") is None
      and liq.normalise_category("1") is None
      and liq.normalise_category("medium") is None
      and liq.normalise_category(None) is None
      and liq.normalise_category("") is None)

# --------------------------------------------------------------------------- #
# Coseismic landslide screening
# Jibson (2007) Equation 8, on a critical acceleration from Hazus 6.1 4.2.2.2
# --------------------------------------------------------------------------- #
# The two halves of this model are published separately and were transcribed
# separately, so the checks below are mostly *cross*-checks: the tables say the
# same thing about the same ground in three different ways, and none of the
# three was derived from the others.

_LSL_SLOPES = (0.0, 2.5, 5.0, 7.5, 10.0, 12.5, 15.0, 17.5, 20.0, 25.0,
               30.0, 35.0, 40.0, 45.0, 60.0)
_LSL_ROWS = [(g, m) for g, _n, _s in lsl.HAZUS_LANDSLIDE_GROUPS
             for m in lsl.HAZUS_LANDSLIDE_MOISTURE]
_LSL_BANDS = range(len(lsl.HAZUS_LANDSLIDE_BANDS_DEG))

# Table 4-14 names a category; Table 4-16 gives it an acceleration; Table 4-17
# gives it an area share. A partial re-transcription is the failure that
# produces a plausible map for four groups and a crash or a silent zero for the
# other two, and if it landed in Table 4-17 the missing category would read as
# "no susceptible deposit here" - the safest answer in the tool.
check("Hazus: every Table 4-14 cell resolves through Table 4-16 and Table 4-17",
      {c for row in lsl.HAZUS_LANDSLIDE_CATEGORY.values() for c in row}
      - {"None"} == set(lsl.HAZUS_LANDSLIDE_AC_G)
      and set(lsl.HAZUS_LANDSLIDE_AREA_FRACTION)
      == set(lsl.HAZUS_LANDSLIDE_CATEGORIES)
      and set(lsl.HAZUS_LANDSLIDE_CATEGORY) == set(_LSL_ROWS))

# Ordering is the one thing a reader is entitled to assume and nothing in the
# arithmetic enforces it: two transposed proportions give a plausible map with
# the colours in the wrong order.
check("Hazus: susceptibility never decreases as the slope steepens",
      all(all(lsl.hazard_rank(row[i]) <= lsl.hazard_rank(row[i + 1])
              for i in range(len(row) - 1))
          for row in lsl.HAZUS_LANDSLIDE_CATEGORY.values()))
check("Hazus: a wet slope is never less susceptible than the same slope dry",
      all(lsl.hazard_rank(lsl.HAZUS_LANDSLIDE_CATEGORY[(g, "dry")][i])
          <= lsl.hazard_rank(lsl.HAZUS_LANDSLIDE_CATEGORY[(g, "wet")][i])
          for g in "ABC" for i in _LSL_BANDS))
check("Hazus: group C is never less susceptible than B, and B never less than A",
      all(lsl.hazard_rank(lsl.HAZUS_LANDSLIDE_CATEGORY[(firmer, m)][i])
          <= lsl.hazard_rank(lsl.HAZUS_LANDSLIDE_CATEGORY[(softer, m)][i])
          for m in lsl.HAZUS_LANDSLIDE_MOISTURE for i in _LSL_BANDS
          for firmer, softer in (("A", "B"), ("B", "C"))))
check("Hazus: the categories are ordered - acceleration strictly down, area share strictly up",
      all(a > b for a, b in zip(
          [lsl.HAZUS_LANDSLIDE_AC_G[c] for c in lsl.HAZUS_LANDSLIDE_CATEGORIES[1:]],
          [lsl.HAZUS_LANDSLIDE_AC_G[c] for c in lsl.HAZUS_LANDSLIDE_CATEGORIES[2:]]))
      and all(a < b for a, b in zip(
          [lsl.HAZUS_LANDSLIDE_AREA_FRACTION[c] for c in lsl.HAZUS_LANDSLIDE_CATEGORIES],
          [lsl.HAZUS_LANDSLIDE_AREA_FRACTION[c] for c in lsl.HAZUS_LANDSLIDE_CATEGORIES[1:]])))

# Table 4-15's slope bound and Table 4-14's six columns were read independently
# and answer the same question - "is this ground susceptible at all?" - so they
# are required to agree everywhere, not merely where the bound happens to fall
# on a column edge. Group C dry is the case that makes this bite: its bound
# (5 degrees) cuts inside the 0-10 column, and the category that column holds
# above the bound is not the category below it.
check("Hazus: Table 4-15's bound and Table 4-14's columns never disagree",
      all((lsl.hazus_susceptibility(g, m, s)["category"] == "None")
          == (s < lsl.HAZUS_LANDSLIDE_SLOPE_BOUND_DEG[(g, m)])
          for g, m in _LSL_ROWS for s in _LSL_SLOPES))

# The one place the two halves of Section 4.2.2.2 touch. Table 4-15's
# acceleration is applied as a floor on Table 4-16's value, and across the whole
# 3-by-2-by-6 table it changes exactly one cell. Asserting the list rather than
# its length means a single mistyped digit in either table fails here with the
# cell named.
check("Hazus: Table 4-15's floor bites exactly once in the whole table",
      lsl.ac_table_floor_conflicts() == [("B", "wet", 5, 0.05, 0.10)])
_bw = lsl.hazus_susceptibility("B", "wet", 45.0)
check("Hazus: the floored cell is raised to the bound, and the row says so",
      _bw["category"] == "X" and close(_bw["ac_g"], 0.10, 1e-12)
      and _bw["floor_applied"] and close(_bw["ac_floor_g"], 0.10, 1e-12)
      and _bw["band_label"] == ">40")
_bd = lsl.hazus_susceptibility("B", "dry", 45.0)
check("Hazus: a cell the floor does not reach is left at its Table 4-16 value",
      _bd["category"] == "VII" and close(_bd["ac_g"], 0.20, 1e-12)
      and not _bd["floor_applied"] and close(_bd["ac_floor_g"], 0.15, 1e-12))

# "None" is the word the manual prints in Table 4-16's value row, not a value,
# so it is absent from the table rather than mapped to zero - and it has to stay
# absent, because a zero reaching Equation 8 is an infinity, which would turn
# the model's safest answer into its loudest one.
_hi = lsl.hazus_susceptibility("B", "wet", 3.0)
check("Hazus: below the bound the answer is 'None' with no acceleration, not zero",
      _hi["category"] == "None" and _hi["ac_g"] is None
      and _hi["area_fraction"] == 0.0 and _hi["below_bound"]
      and _hi["slope_bound_deg"] == 5.0
      and _hi["band"] is None and _hi["band_label"] is None
      and not _hi["floor_applied"])
check("Hazus: no route through the tables ever returns a critical acceleration of zero",
      all(lsl.hazus_susceptibility(g, m, s)["ac_g"] in (None,) or
          lsl.hazus_susceptibility(g, m, s)["ac_g"] > 0.0
          for g, m in _LSL_ROWS for s in _LSL_SLOPES))
check("Hazus: a susceptibility answer carries the row it came from and the floor it met",
      set(lsl.hazus_susceptibility("C", "dry", 25.0))
      == {"category", "ac_g", "area_fraction", "band", "band_label",
          "slope_bound_deg", "below_bound", "floor_applied", "ac_floor_g"})
check("Hazus: the band edges are half-open, so 40 degrees belongs to the steepest band",
      lsl.slope_band(9.999) == 0 and lsl.slope_band(10.0) == 1
      and lsl.slope_band(39.999) == 4 and lsl.slope_band(40.0) == 5
      and lsl.slope_band(89.0) == 5 and lsl.slope_band(0.0) == 0)
check("Hazus: the hazard rank runs 0 for None up to 10 for X",
      lsl.hazard_rank("None") == 0 and lsl.hazard_rank("I") == 1
      and lsl.hazard_rank("X") == 10
      and lsl.hazard_rank("X") > lsl.hazard_rank("IX") > lsl.hazard_rank("I"))
try:
    lsl.hazus_susceptibility("D", "dry", 20.0)
    _lsl_missing_row = False
except KeyError:
    _lsl_missing_row = True
check("Hazus: a group the manual does not define raises rather than falling back",
      _lsl_missing_row)

check("Hazus: a geologic group is matched on its letter or the manual's own name",
      lsl.normalise_group("a") == "A" and lsl.normalise_group(" A ") == "A"
      and lsl.normalise_group("Argillaceous") == "C"
      and lsl.normalise_group("weakly cemented rocks and soils.") == "B")
check("Hazus: a group that is not A, B or C comes back None, not the nearest letter",
      lsl.normalise_group("D") is None and lsl.normalise_group("granite") is None
      and lsl.normalise_group("AB") is None and lsl.normalise_group(None) is None
      and lsl.normalise_group("") is None)
check("Hazus: a susceptibility category accepts the Roman numerals and the word None",
      lsl.normalise_susceptibility("vii") == "VII"
      and lsl.normalise_susceptibility(" VIII ") == "VIII"
      and lsl.normalise_susceptibility("None") == "None"
      and lsl.normalise_susceptibility("x") == "X")
# The refusal that matters. Hazus counts I as the *least* susceptible, while a
# GIS column of 1..10 is as likely to have been written the other way round;
# reading one as the other reverses the hazard, and nothing downstream would
# notice. So digits are refused outright rather than guessed at.
check("Hazus: a digit column is refused outright rather than read as a Roman numeral",
      lsl.normalise_susceptibility("1") is None
      and lsl.normalise_susceptibility(1) is None
      and lsl.normalise_susceptibility("10") is None
      and lsl.normalise_susceptibility("IV - high") is None
      and lsl.normalise_susceptibility("high") is None)
check("Hazus: moisture is dry or wet and nothing else",
      lsl.normalise_moisture("DRY") == "dry"
      and lsl.normalise_moisture(" wet ") == "wet"
      and lsl.normalise_moisture("moist") is None
      and lsl.normalise_moisture(None) is None)

# One site by hand. The arithmetic is written out with the published numbers
# rather than read from the module's own dict, so a change to either the
# coefficients or the equation's shape fails here: a_c/PGA = 0.5 at Mw 7.5.
#   log10 D_N = -2.71 + 2.335*log10(1 - 0.5) - 1.478*log10(0.5) + 0.424*7.5
_log10_hand = (-2.71 + 2.335 * math.log10(0.5) - 1.478 * math.log10(0.5)
               + 0.424 * 7.5)
_hand = lsl.jibson_displacement(0.5, 1.0, 7.5)
check("Jibson: Equation 8 reproduces the hand-computed median displacement",
      _hand["moving"] and close(_hand["ratio"], 0.5, 1e-15)
      and close(_hand["log10_disp"], _log10_hand, 1e-12)
      and close(_hand["disp_cm"], 10.0 ** _log10_hand, 1e-12)
      and abs(_hand["disp_cm"] - 1.6294) < 1e-3
      and not _hand["notes"])
# The regression predicts the mean of log10 D_N, so the median is its
# exponentiation and the published sigma is symmetric *in log10* - a 3.8-fold
# spread on the map, which is what the manual tells the user to expect.
check("Jibson: the 90th percentile is the published one-sigma spread above the median",
      close(_hand["p90_cm"], 10.0 ** (_log10_hand + 1.2815515655446004 * 0.454),
            1e-12)
      and close(_hand["p90_cm"] / _hand["disp_cm"],
                10.0 ** (1.2815515655446004 * 0.454), 1e-12)
      and abs(_hand["p90_cm"] / _hand["disp_cm"] - 3.8) < 0.05)

check("Jibson: the displacement falls to zero as the critical acceleration approaches the peak",
      lsl.jibson_displacement(0.9999, 1.0, 7.5)["disp_cm"] < 1e-4
      and lsl.jibson_displacement(0.9999, 1.0, 7.5)["disp_cm"] > 0.0
      and lsl.jibson_displacement(1.0, 1.0, 7.5)["disp_cm"] == 0.0)
# Above unity (1 - a_c/PGA) is negative and a fractional power of it is
# undefined, so the guard has to cover the whole half-line, not just the point.
_stop = lsl.jibson_displacement(1.5, 1.0, 7.5)
check("Jibson: a block whose strength meets the shaking has no displacement, and says why",
      _stop["disp_cm"] == 0.0 and _stop["p90_cm"] == 0.0
      and _stop["log10_disp"] is None and _stop["moving"] is False
      and len(_stop["notes"]) == 1 and "not missing data" in _stop["notes"][0])
_by_ac = [lsl.jibson_displacement(a, 0.6, 7.5)["disp_cm"]
          for a in (0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.59)]
check("Jibson: a stronger material slides less - strictly, at every step",
      all(a > b for a, b in zip(_by_ac, _by_ac[1:])))
_by_mw = [lsl.jibson_displacement(0.3, 0.6, m)["disp_cm"]
          for m in (5.5, 6.5, 7.0, 7.5, 8.0)]
check("Jibson: the same slope slides further in a larger earthquake",
      all(a < b for a, b in zip(_by_mw, _by_mw[1:])))

# The threshold is this tool's own, not a published one: it is the ratio a
# 1.0 g peak produces against Table 4-16's smallest acceleration. Below it the
# number is an extrapolation and the row says so; it is never clipped, because
# clipping it would be inventing a limit no paper states.
check("Jibson: the extrapolation past the tables' own ratio is reported, not clipped",
      lsl.JIBSON_LOW_RATIO == min(lsl.HAZUS_LANDSLIDE_AC_G.values())
      and lsl.jibson_displacement(lsl.JIBSON_LOW_RATIO, 1.0, 7.5)["moving"]
      and not lsl.jibson_displacement(lsl.JIBSON_LOW_RATIO, 1.0, 7.5)["notes"]
      and "extrapolation" in lsl.jibson_displacement(0.03, 1.0, 7.5)["notes"][0]
      and lsl.jibson_displacement(0.03, 1.0, 7.5)["disp_cm"] > 0.0)

# Rule R7: a missing input is not a missing hazard. Every one of these has a
# tempting substitute - zero displacement, the previous row, a clamp - and every
# substitute would put an invented number on the map.
_lsl_raises = []
for _args in ((0.3, 0.0, 7.5), (0.3, -0.2, 7.5), (0.3, None, 7.5),
              (0.0, 0.6, 7.5), (None, 0.6, 7.5), (-0.1, 0.6, 7.5)):
    try:
        lsl.jibson_displacement(*_args)
        _lsl_raises.append(False)
    except ValueError:
        _lsl_raises.append(True)
check("Jibson: an input the equation cannot be evaluated on is refused, not substituted",
      all(_lsl_raises) and len(_lsl_raises) == 6)
try:
    lsl.jibson_displacement(0.0, 0.6, 7.5)
except ValueError as _exc:
    _zero_message = str(_exc)
check("Jibson: the refusal for a zero critical acceleration names what diverges",
      "diverges" in _zero_message and "liquefaction" in _zero_message)

# --------------------------------------------------------------------------- #
def _failures():
    return [label for label, ok in CHECKS if not ok]


def _report():
    fails = _failures()
    print(f"\n{len(CHECKS) - len(fails)}/{len(CHECKS)} checks passed")
    if fails:
        print("FAILED:", *fails, sep="\n  - ")
    return 1 if fails else 0


def test_engine_checks():
    """Pytest entry point for the checks that ran at import time above.

    Every check in this module executes at module level, so by the time pytest
    calls this function the whole suite has already run and CHECKS is full -
    this assertion is only the verdict. It is what makes the 627 checks
    enforced by the monorepo's pure-test gate.

    Without it the module is invisible to pytest: it used to end in a bare
    sys.exit(), and sys.exit() during collection is an INTERNALERROR, not a
    test result. Filed under tests_pure in plugins.toml, the gate therefore
    could not run this suite at all - it exited 3 having asserted nothing.
    """
    fails = _failures()
    assert not fails, f"{len(fails)} engine check(s) failed: {fails}"


if __name__ == "__main__":
    sys.exit(_report())
