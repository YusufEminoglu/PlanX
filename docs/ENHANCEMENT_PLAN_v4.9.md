# PlanX Enhancement Plan v4.9 — Network Routing UX & Walking Comfort

**Target release: 4.9.0** (the release itself is NOT your job — see §0.14).
**Baseline: v4.8.0, commit `f3d2b20`** — 65 algorithms, 19 groups, 457 engine
unit checks, 384 e2e assertions (both QGIS), 26 dashboard checks. Your work
must only ADD to these numbers; every existing check must still pass.

**One paragraph:** Five features in one phase. (A) `Prepare Network` gains an
optional output reprojection and a create-spatial-index switch, so its result
is immediately usable everywhere. (B) `Nearest Facility Allocation` gains an
optional REAL route output — the actual network path each demand point takes
to its assigned facility, not just a straight spider line. (C) A NEW
`planx:odroutes` algorithm outputs origin–destination shortest paths as real
route geometry (plus optional straight desire lines) — the embedded-engine
replacement for the QNEAT3 OD workflow, with k-nearest and cutoff controls.
(D) A NEW `planx:walkingslope` walkability tool profiles every street segment
against a DEM: length-weighted slope statistics, comfort classes and
direction-aware Tobler walking speeds/times. (E) A NEW `planx:streetcomfort`
walkability tool scores street segments 0–100 from kernel densities of
comfort assets (trees, lamps...) and barriers (potholes, obstacles...) plus
optional raster factors (sun hours, heat risk...).

---

## 0. Ground rules (hard requirements — each one has burned us before)

1. **Read this whole file first. Touch ONLY the files listed in §9.** Do not
   refactor, reformat, or "improve" anything outside scope. Existing
   algorithm ids, parameter names, output names/fields and engine function
   signatures must not change. The two EXTENDED algorithms (§3, §4) must be
   byte-for-byte behaviour-compatible when the new parameters are left at
   defaults that preserve the old behaviour (stated per feature).
2. **100% English** in all code, help, docs. Never use the words "elite",
   "best-in-class", "ultimate" or similar self-praise in any copy.
3. Every algorithm help string ends with a **"How to read the results"**
   section followed by a **"Using the results"** passage.
   `scratch/planx_import_check.py` asserts the former's presence on ALL
   algorithms. The two extended algorithms must have their help TEXT updated
   to cover the new parameters/outputs inside their existing sections.
4. **No dead knobs**: every parameter you declare must change the output.
   Every parameter you read must be used in the computation.
5. **Determinism**: no unseeded randomness, no `hash()`, no set/dict
   iteration order affecting results. Tie-breaks must be explicit (§2 states
   them where they matter).
6. **Copy the sibling patterns.** `alg_od_routes.py` imitates
   `alg_od_matrix.py` + the `route_geometry` inner function of
   `alg_route_quality.py`; `alg_walking_slope.py` and
   `alg_street_comfort.py` imitate `alg_walkability.py` (DEM
   `provider.sample` idiom, `opt()` NULL idiom, weights free-text idiom).
   When in doubt, do what the neighbours do.
7. **Pure engine**: nothing under `engine/` may import qgis. The new
   `engine/comfort.py` is numpy-only; the two `engine/paths.py` additions
   follow that module's existing style (heapq + numpy).
8. **Pin scripts move UP, never sideways or down** (a past agent weakened
   one to make its shortcut pass — instant rejection):
   - `scratch/planx_import_check.py`: `len(algs) == 65` → `== 68`.
   - `scratch/planx_e2e_qgis.py`: `"65 algorithms registered"` check → 68;
     the distinct-icon invariant `== 65` → `== 68`.
   - `scratch/planx_zip_audit.py`: ADD file asserts for
     `planx/engine/comfort.py`, `planx/algorithms/alg_od_routes.py`,
     `planx/algorithms/alg_walking_slope.py`,
     `planx/algorithms/alg_street_comfort.py`,
     `planx/icons/tool_odroutes.png`, `planx/icons/tool_walkingslope.png`,
     `planx/icons/tool_streetcomfort.png`. Do **NOT** touch its `version=`
     pin or changelog-count pins — the release owner bumps those.
9. **e2e discipline**: new block labels are **[62] [63] [64] [65] [66]**
   (labels currently end at [61]; grep first and keep labels unique). Keep
   the `os._exit(...)` tail intact. Run from the monorepo root
   (`C:\Users\YE\PyCharmMiscProject\qgis_plugins`) — running with CWD inside
   `planx/` makes `planx.py` shadow the package. Script files only
   (multiline `-c` silently fails on OSGeo4W). Set `PYTHONUNBUFFERED=1`.
   Run BOTH runners: `C:\OSGeo4W\bin\python-qgis-ltr.bat` (QGIS 3 LTR) and
   `C:\OSGeo4W\bin\python-qgis.bat` (QGIS 4). **Never claim a run you did
   not execute; paste the exact printed totals into your report (§10).**
10. **Icons**: extend `scratch/make_planx_tool_icons.ps1` with THREE entries
    using **inline point arrays** (helper functions returning arrays inside
    the scriptblock crash GDI+ — known trap). Palettes: `tool_odroutes` uses
    the NETWORK palette (copy the colour pair from `tool_odmatrix`);
    `tool_walkingslope` and `tool_streetcomfort` use the WALKABILITY palette
    (copy from `tool_walkability`). Glyph suggestions: odroutes = two dots
    joined by an L/staircase polyline (a routed path, not a straight line);
    walkingslope = an ascending slope wedge with a small gradient arrow;
    streetcomfort = a street line flanked by three radiating dots. Keep them
    readable at 24 px. Regenerate, then verify with `git status` that ONLY
    the three new PNGs are new and every existing PNG is byte-identical (the
    generator is deterministic; if others changed, you broke it).
11. **Lint/security**: `py -m flake8 --max-line-length=127 planx` must be
    clean; `py -m bandit -r planx -q` must add nothing above Low severity.
12. **Standing geometry rule (THIS TIME IT IS THE HEART OF THE PHASE):**
    never copy an input `QgsFeature`'s geometry into a sink with a different
    CRS or geometry type; rebuild geometry from coordinates. Route outputs
    are rebuilt from graph polylines (the `route_geometry` idiom); the
    reprojected Prepare Network output is transformed with
    `QgsCoordinateTransform`, never by just relabelling the CRS.
13. **`docs/METHODS.md` style**: inline-backtick prose formulas only
    (`speed = 6·e^(−3.5·|m+0.05|)`), matching the rest of the file. Do NOT
    use `$$`/LaTeX display math (a past agent did; it had to be rewritten).
    Do NOT touch the README "Verified math" bullet — the release owner
    updates its counts at release time.
14. **STOP BEFORE RELEASE.** Do NOT bump the version in `metadata.txt`, do
    NOT build a zip, do NOT `git add/commit/tag/push`. Leave the working
    tree dirty for review. The CHANGELOG heading must read exactly
    `## [4.9.0] - UNRELEASED`.
15. Deliver a report file (§10). Deviations from this plan require a written
    justification there — the default expectation is zero deviations.

---

## 1. Scope

**Extended (in place, back-compatible):**
- `algorithms/alg_prepare_network.py` — §3 (TARGET_CRS + CREATE_INDEX).
- `algorithms/alg_nearest_facility.py` — §4 (OUT_ROUTES real paths).

**New:**
- `engine/paths.py`: `multi_source_tree(...)` + `path_to_root(...)`
  (append; do not reorganise the module).
- `engine/comfort.py`: NEW pure-numpy module — §2.2.
- `algorithms/alg_od_routes.py`: `ODRoutesAlgorithm` (`planx:odroutes`,
  `GROUP_NETWORK`, icon `tool_odroutes.png`) — §5.
- `algorithms/alg_walking_slope.py`: `WalkingSlopeAlgorithm`
  (`planx:walkingslope`, `GROUP_WALK`, icon `tool_walkingslope.png`) — §6.
- `algorithms/alg_street_comfort.py`: `StreetComfortAlgorithm`
  (`planx:streetcomfort`, `GROUP_WALK`, icon `tool_streetcomfort.png`) — §7.
- 3 icons via the generator script.
- Tests: engine unit sections + e2e blocks [62]–[66].
- Docs: README, metadata description/tags, CHANGELOG, `docs/METHODS.md`.

**Explicitly out of scope:** everything else. No changes to `odmatrix`
itself, `route_quality`, `walkability`, the dashboard, or any other
algorithm. 65 + 3 = **68 algorithms**; groups stay **19**.

---

## 2. Engine contracts

### 2.1 `engine/paths.py` — append two functions

```python
def multi_source_tree(indptr, adj_node, adj_edge, weights, n, sources,
                      cutoff=None):
    """Multi-source Dijkstra with predecessor tracking.

    Same relaxation and tie behaviour as ``multi_source`` (labels win by
    strict improvement only, so on an exact tie the earlier-settled source
    keeps the node), but additionally records for every node the previous
    node and the edge id used to arrive. Returns
    ``(dist, label, pred_node, pred_edge)``; ``label`` indexes into
    ``sources``; ``pred_node``/``pred_edge`` are -1 at the sources and at
    unreachable nodes. ``dist`` and ``label`` must be numerically IDENTICAL
    to ``multi_source`` for the same inputs (unit-tested).
    """

def path_to_root(pred_node, pred_edge, target):
    """Walk predecessors from ``target`` back to its source root.

    Returns ``(nodes, edges)`` in ROOT->TARGET travel order (nodes has one
    more entry than edges). ``([target], [])`` when target is itself a root
    (pred -1 but finite dist is the caller's check); ``([], [])`` when the
    walk exceeds len(pred_node) (corrupt input guard, same as
    reconstruct_path).
    """
```

**Hand fixture (copy into unit tests):** path graph `0-1-2-3-4`, four edges
`e0=(0,1) e1=(1,2) e2=(2,3) e3=(3,4)`, all weights 1, `sources=[0, 4]`:
- `dist == [0, 1, 2, 1, 0]`, `label == [0, 0, 0, 1, 1]` (node 2 ties at
  cost 2 and stays with source 0 — the strict `<` rule; assert exactly).
- `pred_node == [-1, 0, 1, 4, -1]`, `pred_edge == [-1, 0, 1, 3, -1]`.
- `path_to_root(pred_node, pred_edge, 2) == ([0, 1, 2], [0, 1])`.
- `dist`/`label` equal `multi_source`'s output element-wise on this graph
  AND on one irregular graph reused from the existing paths tests.
- With `cutoff=1.5`: node 2 unreachable (`dist inf`, preds -1).

### 2.2 `engine/comfort.py` — NEW module (pure numpy, no qgis)

```python
"""Walking comfort engine: slope profiles, Tobler speeds, kernel densities."""

def parse_breaks(text, default=(5.0, 8.0, 12.0)):
    """Parse 'a,b,c' into a strictly ascending tuple of floats.

    Empty/whitespace -> default. Non-numeric token or a non-ascending
    sequence raises ValueError naming the offending text. Any length >= 1
    is allowed (k breakpoints -> k+1 classes).
    """

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

def tobler_speed(m):
    """Tobler's hiking function: speed = 6 * exp(-3.5 * |m + 0.05|) km/h.

    ``m`` is the signed grade (dz/dx fraction) in the direction of travel;
    scalar or ndarray in, same shape out. Maximum 6.0 km/h at m == -0.05.
    """

def profile_time_min(grades, lengths):
    """Walking time in minutes over per-interval signed grades and lengths
    (metres): sum(len_i / 1000 / tobler_speed(m_i)) * 60. Empty -> 0.0."""

def class_of(value, breaks):
    """Competition-free class index 1..len(breaks)+1: 1 while
    value <= breaks[0], 2 while <= breaks[1], ..., len+1 above the last.
    Scalar or ndarray."""

def kernel_weight(dist, bandwidth, kind):
    """Kernel value for distances (ndarray) against one bandwidth h > 0.

    u = dist / h, clipped contributions to 0 where dist > h. kinds:
    'uniform' -> 1; 'triangular' -> 1 - u; 'epanechnikov' -> 1 - u**2;
    'gaussian' -> exp(-(u**2) * 4.5)  (i.e. sigma = h/3), truncated at h.
    Unknown kind raises ValueError.
    """

def segment_density(samples_xy, pts_xy, pt_w, bandwidth, kind):
    """Mean kernel density of weighted points as seen from one segment.

    ``samples_xy`` (s,2): the segment's sample points; ``pts_xy`` (p,2) and
    ``pt_w`` (p,): candidate features (the caller pre-filters by a spatial
    index). Per sample: sum_i pt_w[i] * kernel_weight(dist_i, h, kind);
    returns the MEAN over the samples (0.0 when p == 0). Not normalised by
    area on purpose - it is a comparative index, not a probability density.
    """

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
```

**Hand fixtures (copy these EXACT numbers into the unit tests):**
- `grade_stats([0, 1, 3], [0, 10, 20])` → grades `[0.1, 0.2]` →
  `(0.15, 0.2, 3.0, 0.0)`.
- `grade_stats([5, 4, 4.5], [0, 10, 20])` → `(0.075, 0.1, 0.5, 1.0)`.
- `tobler_speed(-0.05) == 6.0` exactly; `tobler_speed(0.0)` ≈ **5.036744**;
  `tobler_speed(0.10)` ≈ **3.549335** (tol 1e-5).
- `profile_time_min([0.1, -0.1], [10, 10])` ≈ **0.288170** min
  (= 0.6/3.549335 + 0.6/5.036744).
- `class_of` with breaks (5, 8, 12): 4.9→1, 5.0→1, 7.2→2, 12.0→3, 12.1→4.
- `parse_breaks("")` → (5.0, 8.0, 12.0); `parse_breaks("3,6")` → (3.0, 6.0);
  `parse_breaks("6,3")` and `parse_breaks("a,b")` → ValueError.
- Kernel at `dist = [50], h = 100`: uniform 1.0, triangular 0.5,
  epanechnikov 0.75, gaussian `exp(-1.125)` ≈ **0.324652**; at
  `dist = [150], h = 100` all → 0.0.
- `segment_density(samples=[(0,0),(10,0)], pts=[(5,40)], w=[1], h=100,
  'epanechnikov')`: both sample distances² = 25+1600 = 1625, u² = 0.1625 →
  kernel **0.8375** at each sample → density **0.8375** EXACTLY.
- `combine_components({"positive": [2,0,1], "negative": [0,4,4]},
  {"positive": +1, "negative": -1})` → norms pos `[1,0,0.5]`, neg oriented
  `[1,0,0]` → index **[100.0, 0.0, 25.0]** exactly.
  With `weights={"positive": 3.0}` → **[100.0, 0.0, 37.5]**.
  Adding `"raster_plus": [7,7,7]` (constant) → same index, `dropped ==
  ["raster_plus"]`. All-None/all-constant → ValueError.

---

## 3. Extended algorithm — `planx:preparenetwork`

Add TWO parameters (after MIN_LENGTH, before OUTPUT):
- `TARGET_CRS` — `QgsProcessingParameterCrs`, label
  `"Reproject result to (empty = keep network CRS)"`, `optional=True`.
- `CREATE_INDEX` — `QgsProcessingParameterBoolean`, label
  `"Create spatial index on the result"`, `defaultValue=True`.

**Behaviour:**
- `seg_id` and `length_m` are computed EXACTLY as today, in the SOURCE CRS
  (so `length_m` stays true metres even after reprojection — document this
  in the help).
- When `TARGET_CRS` is valid and differs from the source CRS: the sink is
  created with the target CRS and every output geometry is transformed with
  `QgsCoordinateTransform(source_crs, target_crs,
  context.transformContext())` before writing. When the target CRS is
  GEOGRAPHIC, `feedback.pushWarning` that other PlanX tools require a
  projected CRS. When unset/invalid or equal to the source: behaviour is
  IDENTICAL to v4.8 (regression-tested).
- After all features are written and when `CREATE_INDEX` is true: fetch the
  output via `QgsProcessingUtils.mapLayerFromString(dest_id, context)`; if
  the provider reports the `CreateSpatialIndex` capability call
  `layer.dataProvider().createSpatialIndex()` and `pushInfo`
  `"Spatial index created."`; otherwise `pushWarning` that the format does
  not support it. When false: do nothing (matches v4.8).
- Help: extend the existing paragraphs to describe both options and their
  reading ("length_m is measured in the source CRS"; "the index makes the
  temporary layer immediately fast in spatial joins/snapping").

---

## 4. Extended algorithm — `planx:nearestfacility`

Add ONE output (after SPIDER, before SUMMARY):
- `ROUTES` — `QgsProcessingParameterFeatureSink`, `"Allocation routes
  (network paths)"`, `optional=True`, `createByDefault=False`. LineString,
  network CRS. Fields: `("demand_i", INT)` (0-based row number of the
  Allocated demand output), `("facility", STRING)`, `("net_cost", DOUBLE)`,
  `("length_m", DOUBLE)` (geometric length of the route in the network
  CRS — equals net_cost when cost is length, diverges when a cost field is
  used, which is itself a diagnostic).

**Behaviour:**
- When the ROUTES sink is NOT requested (`parameters.get(self.ROUTES) is
  None`): run EXACTLY the v4.8 code path (`paths.multi_source`) — zero
  behavioural risk.
- When requested: call `paths.multi_source_tree(graph.indptr,
  graph.adj_node, graph.adj_edge, graph.adj_cost, graph.num_nodes,
  unique_nodes, cutoff=cutoff)` instead; `dist`/`label` feed the existing
  logic UNCHANGED (they are identical by contract). For every ALLOCATED
  demand, `paths.path_to_root(pred_node, pred_edge, d_nodes[i])` gives the
  facility→demand node/edge walk; build the polyline with the
  `route_geometry` idiom from `alg_route_quality.py` (orient each edge
  polyline to the walk, drop repeated junction vertices). A demand whose
  node IS the facility node (empty edge list) gets NO route feature (there
  is no line to draw); unallocated demand gets none either. Route count is
  logged.
- Help: extend "Spider lines" reading with the routes ("routes show the
  real streets the trips use — bundle widths reveal which corridors carry
  each catchment; length_m vs net_cost differences flag time-weighted
  assignments").

---

## 5. New algorithm — `planx:odroutes`

File `planx/algorithms/alg_od_routes.py`, class `ODRoutesAlgorithm`,
`GROUP = GROUP_NETWORK`, `ICON = "tool_odroutes.png"`,
`name() = "odroutes"`, `displayName() = "OD Routes (Shortest Paths)"`.

This is the embedded-engine answer to the QNEAT3 OD workflow (straight
"cost lines" + real "route" outputs) — no external plugin.

**Parameters** (constants in this order; copy `alg_od_matrix.py` labels
where they repeat):
- `NETWORK`, `ORIGINS`, `ORIGIN_ID`, `DESTINATIONS` (optional, empty =
  origins), `DEST_ID` (optional), `COST_FIELD` (optional numeric),
  `CUTOFF` (double, default 0 = unlimited) — all EXACTLY as in
  `alg_od_matrix.py`.
- `K_NEAREST` — `QgsProcessingParameterNumber` Integer, label
  `"Keep only the k nearest destinations per origin (0 = all)"`,
  default 0, minValue 0.
- `OUT_ROUTES` — sink `"OD routes"`, LineString, network CRS. Fields:
  `("origin_id", STRING)`, `("dest_id", STRING)`, `("k", INT)` (1 = the
  origin's nearest included destination, by cost), `("net_cost", DOUBLE)`,
  `("euclid_m", DOUBLE)`, `("detour", DOUBLE)` (net/euclid, 0 when euclid
  is 0), `("n_edges", INT)`.
- `OUT_LINES` — sink `"Desire lines (straight)"`, LineString, optional,
  `createByDefault=False`, SAME fields; geometry = straight origin→
  destination segment (the QNEAT-style cost line, in one run with the
  routes).

**Behaviour:**
- Graph build, snapping, id handling, `same_layer` fallback and the i==j
  skip: copy `alg_od_matrix.py` verbatim.
- Per origin: ONE `paths.shortest_path_tree(graph.indptr, graph.adj_node,
  graph.adj_edge, weights, graph.num_nodes, o_node, cutoff=cutoff or
  None)` where `weights = graph.adj_cost` (it already carries the cost
  field when one was given to `build_node_graph`). Collect finite,
  non-self destinations sorted ascending by cost; keep all (K_NEAREST=0)
  or the first k; `k` field = 1-based position in that order (ties keep
  the destination-index order from the sort — `sorted` is stable, sort key
  is the cost only).
- Routes: `paths.reconstruct_path(pred_n, pred_e, src, tgt)` + the
  `route_geometry` idiom. `src == tgt` after snapping → skip (no route,
  consistent with odmatrix's self-skip note in the log).
- `pushWarning` when `len(origins) * len(dests) > 250000` and neither
  CUTOFF nor K_NEAREST limits the output ("this will be huge — set a
  cutoff or k").
- Log: totals per sink and the SciPy line like odmatrix.
- **Numerical invariant (e2e-checked): for identical inputs, every
  (origin_id, dest_id, net_cost) of this tool equals the `planx:odmatrix`
  row exactly** — both are Dijkstra over the same graph.
- Help: method description (per-origin shortest-path tree, reconstruction
  of the actually-used streets), "How to read the results" (net_cost = the
  operative distance/time; detour ≥ ~1.4 = barrier; ROUTE BUNDLES show
  which streets carry the flows — overlay many routes and the de-facto
  corridors emerge, the demand-side complement of betweenness; straight
  desire lines = the same table drawn as OD glyphs), "Using the results"
  (corridor identification for sidewalk/cycle investment; overlay with
  `Cycling Stress` / `Walkability Audit` scores; k=1 gives assignment-like
  nearest-service routes; feed net_cost into Gravity/Mode Split).

---

## 6. New algorithm — `planx:walkingslope`

File `planx/algorithms/alg_walking_slope.py`, class
`WalkingSlopeAlgorithm`, `GROUP = GROUP_WALK`,
`ICON = "tool_walkingslope.png"`, `name() = "walkingslope"`,
`displayName() = "Walking Slope Comfort"`.

**Parameters:**
- `NETWORK` — line source `"Street network (lines)"` (require_projected).
- `DEM` — `QgsProcessingParameterRasterLayer`, `"DEM (elevation)"`,
  REQUIRED (unlike the audit's optional endpoint sampling, this tool IS
  the slope profile).
- `SAMPLE_STEP` — Double, `"Profile sample spacing (m)"`, default 10.0,
  minValue 0.5.
- `BREAKS` — String, `"Comfort class breakpoints, mean |slope| %
  (ILLUSTRATIVE defaults)"`, default `"5,8,12"` → `comfort.parse_breaks`
  (ValueError → `QgsProcessingException`).
- `OUTPUT` — sink `"Slope-profiled segments"`, LineString, network CRS.

**Output fields** (`base=source.fields()` then): `("slope_pct", DOUBLE)`
(length-weighted mean |grade|·100), `("max_pct", DOUBLE)`,
`("climb_m", DOUBLE)`, `("descent_m", DOUBLE)` (both in DIGITISED
direction), `("tobler_fwd_kmh", DOUBLE)`, `("tobler_rev_kmh", DOUBLE)`
(effective speeds = length / walking time, i.e. the harmonic aggregation),
`("time_fwd_min", DOUBLE)`, `("time_rev_min", DOUBLE)`,
`("comfort_class", INT)`, `("class_label", STRING)` (labels for k=3
breaks: `Comfortable / Moderate / Steep / Severe`; for other k:
`Class 1..k+1`).

**Behaviour:**
- Per segment: sample the DEM with `provider.sample(QgsPointXY, 1)` at
  distances `0, step, 2*step, ..., length` along the geometry
  (`geometry().interpolate(dist)`), ALWAYS including both endpoints (the
  final sample is at `length` even when not a multiple of step). Segments
  shorter than step get exactly the two endpoint samples.
- Failed samples (`ok` False): drop that sample from the profile; if fewer
  than 2 valid samples remain, the segment is treated as FLAT (all grade
  stats 0, class 1) and counted into one summary
  `pushWarning: "N segment(s) with insufficient DEM coverage - treated as
  flat."` (the `alg_walkability.py` idiom). Distances `d` for
  `grade_stats` are the along-line distances of the KEPT samples.
- Forward stats from `comfort.grade_stats(z, d)`; forward time from
  `comfort.profile_time_min(grades, interval_lengths)`; reverse time with
  NEGATED grades in reversed order. `tobler_*_kmh = (length/1000) /
  (time_min/60)` (0-length guard → 0). Class from `comfort.class_of` on
  `slope_pct`.
- Log: mean slope_pct, share of class ≥ 3, worst segment.
- Help: Tobler formula inline (`speed = 6·e^(−3.5·|m+0.05|)` km/h, fastest
  slightly downhill at −5%), the ILLUSTRATIVE breakpoints note (5% ≈
  comfortable / accessible-route practice, 8% ≈ short-ramp territory, 12%+
  ≈ stairs-preferred; local standards should override), "How to read the
  results" (slope_pct is the comfort driver; time_fwd vs time_rev
  asymmetry = the uphill penalty pedestrians actually feel — route
  planning that ignores it overestimates uphill catchments; class ≥ 3
  segments break wheelchair/stroller continuity), "Using the results"
  (feed `time_fwd_min` as the cost field into OD/Nearest-Facility/15-min
  tools for slope-aware catchments — this is the built-in bridge; overlay
  class ≥ 3 with the Walkability Audit's s_slope for confirmation; rank
  candidate ramp/stair interventions by climb_m × pedestrian flow).

---

## 7. New algorithm — `planx:streetcomfort`

File `planx/algorithms/alg_street_comfort.py`, class
`StreetComfortAlgorithm`, `GROUP = GROUP_WALK`,
`ICON = "tool_streetcomfort.png"`, `name() = "streetcomfort"`,
`displayName() = "Street Environment Comfort"`.

A kernel-density comfort model collapsed onto street segments: assets
(street trees, lamps, benches, shade sails...) raise comfort, barriers
(potholes, obstacles, blank walls, narrow-sidewalk markers...) lower it,
and up to two rasters (e.g. summer sun hours, heat-risk, noise) join as
segment-mean factors.

**Parameters:**
- `NETWORK` — line source `"Street network (lines)"` (require_projected).
- `POSITIVE` — `QgsProcessingParameterMultipleLayers`,
  `layerType=QgsProcessing.TypeVectorPoint`, `"Comfort assets (point
  layers: trees, lamps, benches...)"`, `optional=True`.
- `NEGATIVE` — same type, `"Comfort barriers (point layers: obstacles,
  potholes...)"`, `optional=True`.
- `WEIGHT_FIELD` — String, `"Per-feature weight field name (used when a
  layer has it; empty or missing field = weight 1)"`, default `""`,
  optional.
- `RASTER_PLUS` — RasterLayer, `"Raster raising comfort (e.g. winter sun
  hours)"`, optional.
- `RASTER_MINUS` — RasterLayer, `"Raster lowering comfort (e.g. heat risk,
  noise)"`, optional.
- `BANDWIDTH` — Double, `"Kernel bandwidth (m)"`, default 50.0, min 1.0.
- `KERNEL` — Enum `["Uniform", "Triangular", "Epanechnikov", "Gaussian"]`,
  default 2 (Epanechnikov).
- `SAMPLE_STEP` — Double, `"Segment sample spacing (m)"`, default 10.0,
  minValue 1.0.
- `WEIGHTS` — String, `"Component weights 'positive=1, negative=1,
  raster_plus=1, raster_minus=1' (empty = equal)"`, default `""`,
  optional.
- `OUTPUT` — sink `"Comfort-scored segments"`, LineString, network CRS.

**Output fields** (`base=source.fields()`): `("pos_den", DOUBLE)`,
`("neg_den", DOUBLE)`, `("rplus_mean", DOUBLE)`, `("rminus_mean", DOUBLE)`
(NULL via the `opt()` idiom when the component is absent),
`("comfort", DOUBLE)` 0–100, `("n_samples", INT)`.

**Behaviour:**
- Validation first: at least ONE of POSITIVE/NEGATIVE/RASTER_PLUS/
  RASTER_MINUS must be given, else `QgsProcessingException` ("provide at
  least one comfort component"). WEIGHTS parsed with the same free-text
  rules as everywhere (`key=value`, `,`/`;`); keys MUST be within
  {positive, negative, raster_plus, raster_minus} else
  `QgsProcessingException`; values ≤ 0 → exception. A weight for an
  ABSENT component → `pushWarning` and ignore.
- Segment samples at distances `step/2, step/2 + step, ...` while
  `< length`; a segment shorter than step gets ONE sample at `length/2`
  (midpoint offsets avoid double-counting shared junction endpoints —
  state this in the help).
- Point components: merge all POSITIVE layers' features (reproject each
  layer's points to the network CRS via the `source_points` idiom
  per-layer); per feature weight = float(WEIGHT_FIELD value) when the
  layer has that field and the value is numeric-positive, else 1.0.
  Build ONE `QgsSpatialIndex` per side; per segment query
  `index.intersects(segment bbox grown by bandwidth)` and pass the
  candidates to `comfort.segment_density`. Same for NEGATIVE.
- Raster components: mean of valid `provider.sample` values at the SAME
  sample points; a segment with zero valid samples gets NaN → after
  min-max normalisation it is set to the NEUTRAL 0.5 and counted into one
  `pushWarning` ("N segment(s) outside <raster> coverage - neutral").
  NaN segments are EXCLUDED from the min-max fit.
- Combine: `comfort.combine_components({"positive": ..., "negative": ...,
  "raster_plus": ..., "raster_minus": ...}, {"positive": +1, "negative":
  -1, "raster_plus": +1, "raster_minus": -1}, weights)` — dict literal in
  exactly this order. Absent → None. Dropped-constant components →
  `pushWarning` naming them (mirrors scenario.rank's 'constant' skip).
  ValueError → `QgsProcessingException` (e.g. single component that is
  constant).
- Log: used components with their effective weights, mean comfort, the
  count of comfort < 25 segments.
- Help: formulas inline (kernel kinds with `u = d/h`; the index =
  `100 · Σ w·oriented_norm / Σ w`), "How to read the results" (comfort is
  RELATIVE within this run — min-max over the analysed network, so scores
  are for comparing streets in one study area, not across cities; pos_den/
  neg_den are the raw evidence — a low-comfort segment with high neg_den
  needs obstacle removal, one with low pos_den needs assets; bandwidth is
  the walking-perception radius: 50 m ≈ what a pedestrian senses along a
  block), "Using the results" (target tree-planting/lighting gaps on
  high-flow low-comfort segments — join with OD Routes bundles or
  Walkability; monitor before/after by rerunning with the same bandwidth
  and kernel; feed `comfort` into Pedestrian Route Quality as its score
  field for comfort-weighted routing — this is the built-in bridge).

---

## 8. Tests

### 8.1 Engine unit tests (`planx/tests/test_engine.py`)

Append a section `# Paths: multi-source predecessor tree (v4.9)` and a
section `# Walking comfort engine (v4.9)` before the summary block, using
the §2 fixtures verbatim. Required checks (~30): the §2.1 path-graph
fixture (dist, label, preds, path_to_root, cutoff, equality vs
multi_source ×2 graphs); grade_stats ×2 fixtures + short-profile zeros;
tobler ×3 values; profile_time ×1; class_of ×5 values; parse_breaks happy/
default/ValueError ×2; kernel_weight 4 kinds + beyond-h zero; 
segment_density exact 0.8375 + empty-points 0; combine_components exact
[100,0,25], weighted [100,0,37.5], constant-drop, absent-None, ValueError.

Run: `C:\OSGeo4W\bin\python-qgis-ltr.bat planx\tests\test_engine.py` from
the monorepo root. Expect **≥ 485 total, ALL passing**; report the exact
number.

### 8.2 e2e (`scratch/planx_e2e_qgis.py`, blocks [62]–[66])

Reuse the harness's existing projected grid-network fixture layers where
possible; create small dedicated fixtures where stated. Follow the
existing raster-fixture idiom (the DSM/solar blocks) for writing the DEM.

- **[62] preparenetwork options** (~9 asserts): default run → output CRS ==
  source CRS AND `hasSpatialIndex()` present (CREATE_INDEX defaults True);
  `CREATE_INDEX: False` run → index NOT present; `TARGET_CRS: "EPSG:4326"`
  run → output `crs().authid() == "EPSG:4326"`, first vertex ≈ the
  in-test `QgsCoordinateTransform` of the source vertex (tol 1e-9), and
  the `length_m` values EQUAL the default run's values (source-CRS
  metres). Resolve the presence enum with a
  `try: Qgis.SpatialIndexPresence... except AttributeError:
  QgsFeatureSource.SpatialIndexPresent` guard so BOTH runners pass.
- **[63] nearestfacility routes** (~7): rerun the existing nearest-facility
  fixture with `ROUTES: "TEMPORARY_OUTPUT"` → allocated demand/summary
  values IDENTICAL to the existing block's expectations (regression proof
  of the tree swap); route count == allocated count (minus any demand
  snapped onto a facility node — the fixture should have none); for a
  hand-picked demand the route `geometry().length()` == its `net_cost`
  (cost = length, tol 1e-6) and the route has ≥ 3 vertices (an L-shaped
  grid path, not a straight line).
- **[64] odroutes** (~11): grid fixture, 2 origins × 3 destinations →
  `OUT_ROUTES` row count 6; every route length == net_cost (tol 1e-6);
  every (origin_id, dest_id, net_cost) EQUALS the `planx:odmatrix` result
  on identical inputs (run both, compare maps); at least one detour > 1.2;
  `K_NEAREST: 1` → exactly 2 rows, each the true min-cost destination,
  `k == 1`; small CUTOFF → fewer rows; `OUT_LINES` requested → same
  row count as routes and straight geometry (2 vertices, length ==
  euclid_m tol 1e-6).
- **[65] walkingslope** (~9): DEM plane `z = 0.1 * x` (pixel 1 m, the
  harness raster idiom; sample step 10 stays pixel-aligned so grades are
  exact). Segment along +x, length 100 → `slope_pct == 10.0`,
  `climb_m == 10.0`, `descent_m == 0.0`, `time_fwd_min ≈ 1.690457`,
  `time_rev_min ≈ 1.191246`, `tobler_fwd_kmh ≈ 3.549335` (tol 1e-4),
  `comfort_class == 3` with default breaks; segment along +y →
  `slope_pct == 0.0`, class 1, `time_fwd == time_rev ≈ 0.952996` for
  80 m. Error path: `BREAKS: "6,3"` raises a clear error (the seismic
  error idiom).
- **[66] streetcomfort** (~9): three far-apart segments; segment A =
  (0,0)→(10,0) with ONE tree at (5,40), `BANDWIDTH: 100`,
  `SAMPLE_STEP: 10`, Epanechnikov → A's `pos_den == 0.8375` EXACTLY
  (single midpoint sample — the §2.2 fixture live); one obstacle near
  segment B (NEGATIVE) → comfort values `[100.0, 0.0, 50.0]` for A/B/C
  (tol 1e-6, per the §2.2 combine fixture logic: A best, B worst, C
  neutral); `n_samples == 1` for the 10 m segment; error path: NO
  components at all raises; `WEIGHTS: "banana=1"` raises.

Also bump the two count invariants to 68 (§0.8). Run the FULL harness on
BOTH runners; expect **≥ 420 passed / 0 failed on each**; report exact
totals.

### 8.3 Regression + dashboard

All pre-existing checks must pass untouched: 457 unit / 384 e2e / 26
dashboard are the floors. `scratch/planx_dashboard_check.py` is NOT
modified (no dashboard change) but must still print 26/26 on both
runners. `scratch/planx_import_check.py` (after 65→68) must print OK on
both runners.

---

## 9. Files you may touch (complete list)

| File | Change |
|---|---|
| `planx/engine/paths.py` | append `multi_source_tree`, `path_to_root` |
| `planx/engine/comfort.py` | NEW (§2.2) |
| `planx/algorithms/alg_prepare_network.py` | §3 |
| `planx/algorithms/alg_nearest_facility.py` | §4 |
| `planx/algorithms/alg_od_routes.py` | NEW (§5) |
| `planx/algorithms/alg_walking_slope.py` | NEW (§6) |
| `planx/algorithms/alg_street_comfort.py` | NEW (§7) |
| `planx/provider.py` | 3 imports + `addAlgorithm` ×3 (odroutes near its network siblings; the two walk algs near WalkabilityAlgorithm; match file style) |
| `planx/icons/tool_odroutes.png` | NEW, via generator |
| `planx/icons/tool_walkingslope.png` | NEW, via generator |
| `planx/icons/tool_streetcomfort.png` | NEW, via generator |
| `scratch/make_planx_tool_icons.ps1` | 3 inline-array entries |
| `planx/tests/test_engine.py` | §8.1 sections |
| `scratch/planx_e2e_qgis.py` | blocks [62]–[66] + both count invariants 65→68 |
| `scratch/planx_import_check.py` | 65 → 68 |
| `scratch/planx_zip_audit.py` | + 7 file asserts (§0.8; NOT the version pin) |
| `planx/README.md` | "sixty-five" → "sixty-eight" in BOTH places; extend the *Walkability studio* feature bullet with the two new tools; extend the network/OD wording in the *Why PlanX?* toolset sentence if it names counts; tool table: +3 rows (Network Analysis: OD Routes; Walkability: Walking Slope Comfort, Street Environment Comfort) AND update the existing Prepare Network / Nearest Facility / OD Cost Matrix row texts to mention reprojection+index, real allocation routes, and the routes sibling |
| `planx/metadata.txt` | description: extend the network clause with "OD shortest-path routes" and the walkability clause with "slope comfort profiling with Tobler walking times, and street environment comfort from kernel densities of assets and barriers"; tags: append `od routes`, `shortest path`, `slope`, `walking comfort`, `kernel density`. **No bare `%` anywhere.** Do NOT touch `version=` |
| `planx/CHANGELOG.md` | new top section `## [4.9.0] - UNRELEASED` (Added ×5 features, Tested: your exact counts) |
| `planx/docs/METHODS.md` | Walkability section additions: Tobler formula, profile aggregation (time-based harmonic), kernel formulas, the combine index — inline-backtick prose, NO LaTeX (§0.13) |
| `planx/docs/AGENT_REPORT_v4.9.md` | NEW — your report (§10) |

Anything not in this table is off-limits.

---

## 10. Definition of done + report

Done means ALL of:
1. §8 test targets met with the EXACT totals pasted into
   `planx/docs/AGENT_REPORT_v4.9.md` (unit; e2e LTR; e2e QGIS 4;
   dashboard LTR + QGIS 4; import_check both runners).
2. flake8 (127) clean; bandit nothing above Low; `git status` shows only
   the §9 files changed and only the three new PNGs.
3. Working tree left UNCOMMITTED (§0.14).
4. Report contains: file-by-file summary, any decisions the plan left
   open, deviations (expected: none), and the exact commands you ran.

## 11. What the reviewer will verify (deterrence disclosure)

The review re-runs everything independently: both e2e runners, the unit
suite and the pin scripts from a clean shell; the §2 fixtures recomputed
by hand (Tobler values, the 0.8375 kernel cell, the [100, 0, 25] combine,
the predecessor arrays); a byte-identity check of all 65 pre-existing
icons; a dead-knob scan of every new parameter; the odroutes-vs-odmatrix
cost equality on a fresh fixture; the Prepare Network default-run
regression against v4.8 outputs; the pin scripts diffed against §0.8 (any
weakened invariant = rejection); README/metadata/CHANGELOG/METHODS
cross-checked (including the no-LaTeX rule); help sections checked for
both required headings on all four touched/new algorithms; and
`git status` checked for out-of-scope touches. Shortcuts are cheaper to
skip than to attempt.
