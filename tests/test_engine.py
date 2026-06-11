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

from planx.engine import HAS_SCIPY, centrality, graphs, morphology, paths, solar, standards, syntax  # noqa: E402

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
fails = [label for label, ok in CHECKS if not ok]
print(f"\n{len(CHECKS) - len(fails)}/{len(CHECKS)} checks passed")
if fails:
    print("FAILED:", *fails, sep="\n  - ")
sys.exit(1 if fails else 0)
