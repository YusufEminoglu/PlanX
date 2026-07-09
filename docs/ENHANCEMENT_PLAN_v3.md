# PlanX v3 Enhancement Plan — "Urban Analytics Studio, Complete"

> Implementation plan for taking PlanX from v2.11.0 (28 algorithms, 9 groups)
> to a v3-series suite of ~45 algorithms plus a scenario-aware dashboard.
> Written to be executed phase-by-phase by an AI coding agent. Each phase is
> an independent, releasable version. **Do not start a phase before the
> previous one's quality gates pass.**
>
> **STATUS 2026-07-09: ALL PHASES A-I SHIPPED** (v2.12, v2.13, v3.0-v3.6).

---

## 0. Ground rules (READ FIRST — these are hard constraints)

### Architecture invariants
- **`engine/` is pure Python + NumPy. NO `qgis` imports there, ever.**
  SciPy may be used only behind a try/except with an identical pure-Python
  fallback (see `engine/paths.py` for the pattern). No new pip dependencies —
  the plugin must run on a stock QGIS install (Windows/macOS/Linux),
  QGIS 3.22 → 4.x.
- **`algorithms/` are thin `QgsProcessingAlgorithm` wrappers** over engine
  functions. Follow `algorithms/base.py` and any existing algorithm
  (e.g. `alg_inequality_curves.py`) as the template: same param style, same
  feedback/progress/cancel idiom, same output-layer styling approach.
- Every new algorithm must be registered in **all** of:
  1. `provider.py` (import + `addAlgorithm`)
  2. `studio_dock.py` tool list (with its group)
  3. `metadata.txt` description/about/tags/changelog
  4. `README.md` tool table and `docs/ROADMAP.md`
  5. its own group-coloured icon in `icons/` (copy the generation pattern
     used by existing per-tool icons; reuse the group colour).
- **English-only UI.** All standards/thresholds are user parameters with
  sensible defaults, never hard-coded locale values.
- **Never use the words "elite", "best", "ultimate"** or similar self-praise
  in any user-facing copy (metadata, README, changelog, tooltips).
- Radius/extent-limited analysis is the default idiom; global runs must warn
  in the log and honour `feedback.isCanceled()` inside every heavy loop.

### Quality gates (every phase, before release)
- Extend `tests/test_engine.py` with hand-computed cases for every new engine
  function (both SciPy and fallback paths where relevant must agree exactly).
  Run with plain Python (qgis not needed for engine tests).
- Extend the headless e2e script `scratch/planx_e2e_qgis.py` (repo-root
  `scratch/`) with real-QGIS assertions for every new algorithm; run it on
  **both** QGIS 3.44 LTR and QGIS 4 via OSGeo4W:
  `C:\OSGeo4W\bin\python-qgis-ltr.bat scratch\planx_e2e_qgis.py` (and the
  qgis4 equivalent). **Script files only — multiline `-c` silently fails.**
- `flake8 --max-line-length=127` clean; `bandit -r planx` 0 High / 0 Medium;
  `python -m py_compile` on every touched file.
- Zip audit: single root folder, **no bare `%` anywhere in metadata.txt**
  (the Hub changelog parser chokes on it — write "percent" or escape).

### Release ritual (per phase)
1. Pre-bump `metadata.txt` version + changelog AND `CHANGELOG.md` yourself
   (do **not** run any release script that prepends a duplicate stub).
2. Run validate + `Build-PluginZip` (see `packaging/`) + zip audit.
3. Manual git: `git add -A && git commit` — **no Co-Authored-By line**,
   plain descriptive message — tag `vX.Y.0`. **Ask the user before pushing**
   unless they said "push et". Hub upload is always manual by the user.

---

## 1. Where PlanX stands (context for the agent)

- 28 Processing algorithms in 9 groups: Network Analysis, Centrality & Space
  Syntax, Urban Morphology, Accessibility, Microclimate, Plan Standards,
  Reporting, Optimization, Equity.
- Engine modules: `graphs` (CSR primal/dual graphs), `paths` (Dijkstra),
  `centrality`, `syntax`, `morphology`, `solar` (NOAA position + clear-sky
  kernels), `standards`, `report` (stdlib HTML report), `optimize`
  (maximal coverage / p-median / capacitated assign), `allocate`
  (multi-objective land-use allocation + Pareto front), `equity`
  (Gini/Theil/Atkinson/Lorenz).
- Two docks: **PlanX Studio** (tool launcher) and **Plan Dashboard**
  (live score cards from field-signature-detected output layers + one-click
  HTML report, `engine/report.py`).
- 216 unit checks, 166 e2e assertions currently passing.

The v3 direction: fill the four queued roadmap items, then add the analysis
families a planning office still needs external tools for — **transit &
GTFS accessibility, urban growth simulation, population & housing analytics,
visibility/isovist analysis, walkability audit, noise & air screening,
green infrastructure, and a scenario system** that ties the whole suite
together in the dashboard.

---

## 2. Phase plan overview

| Phase | Version | Theme | New algorithms | New engine modules |
|---|---|---|---|---|
| A | v2.12 | Roadmap queue, part 1 | Capacitated Facility Siting; Contiguous Land-Use Allocation (hard contiguity) | extend `optimize.py`, `allocate.py` |
| B | v2.13 | Roadmap queue, part 2 | Demographic Equity Cross-Tabs; Scenario Compare (A/B) in dashboard + `planx:scenariocompare` | extend `equity.py`, `report.py`, new `scenario.py` |
| C | v3.0 | Scenario system + walkability | Scenario Snapshot; Walkability Audit; Pedestrian Route Quality | `scenario.py`, `walkability.py` |
| D | v3.1 | Transit (GTFS-lite) | GTFS Import & Stats; Transit Frequency Map; Transit Travel-Time Access | `transit.py` |
| E | v3.2 | Visibility | Isovist Fields; Viewshed on DSM; Visual Exposure of Landmarks | `visibility.py` |
| F | v3.3 | Population & housing | Population Projection (cohort-lite); Housing Needs Assessment; Residential Capacity | `population.py` |
| G | v3.4 | Environment screening | Road Noise Screening (CNOSSOS-lite); Green Space Access & Provision; Urban Green Connectivity | `noise.py`, `green.py` |
| H | v3.5 | Urban growth | Land-Cover Change Analysis; Urban Growth Simulation (CA); Sprawl Metrics | `growth.py` |
| I | v3.6 | Suite polish | Batch Plan Auditor (run-everything pipeline); dashboard upgrade; docs site | extend `report.py` |

Phases A and B are small and de-risk the queue the user already approved.
v3.0 is the headline release. Order within phases C–H may be swapped if the
user asks, but keep one theme per release.

---

## 3. Phase A — v2.12 "Siting & Contiguity" (roadmap queue 1)

### A1. Capacitated Facility Siting (Optimization group)
Choose **where to build** p facilities while respecting per-site capacities —
the siting counterpart of the shipped Capacitated Allocation.

- **Engine** `optimize.capacitated_siting(dist, demand_w, capacities, p, existing_idx, max_cost)`:
  greedy construction (each step: open the candidate that maximises newly
  served demand under a capacity-respecting assignment, reusing
  `capacitated_assign`) followed by Teitz–Bart-style swap improvement where a
  swap is accepted only if the capacitated assignment objective (total served
  demand, tiebreak lower total cost) improves. Existing facilities enter as
  fixed-open. Returns selected indices, per-site load/utilization, assignment
  array, uncovered mask, objective history.
- **Algorithm** `alg_capacitated_siting.py` (`planx:capacitatedsiting`):
  params network layer, demand points (+weight field), candidate sites
  (+capacity field), existing facilities (optional, + capacity field),
  number to open, max travel cost, cost field. Outputs: selected sites layer
  (rank, load, utilization, marginal demand), allocation lines layer
  (demand→site, cost), uncovered demand layer. Log: coverage %, mean cost,
  capacity slack.
- **Tests**: hand-built 6-node network where uncapacitated p-median picks
  site X but capacity forces site Y; assert greedy+swap finds Y. E2E: run on
  the existing e2e network fixture, assert counts/fields and that
  Σload ≤ Σcapacity.

### A2. Hard contiguity in Land-Use Allocation (Optimization group)
Extend the Land-Use Allocation Optimizer with an optional **"require
contiguous zones"** mode: each use forms a single connected component over
the parcel adjacency graph.

- **Engine** `allocate.allocate_contiguous(...)`: region-growing construction
  — seed each use at its highest-suitability parcel (or user lock), grow by
  repeatedly adding the best-scoring frontier parcel (suitability +
  compactness gain) until the area target is met; then boundary-swap local
  search that only proposes moves preserving connectivity of both affected
  uses (check with a per-use BFS on the induced subgraph — parcels are small
  n, this is fine). Falls back with a clear log warning if targets are
  infeasible under contiguity.
- **Algorithm change**: add an enum param `CONTIGUITY` = ["Soft (compactness
  weight)", "Hard (single connected zone per use)"] to
  `alg_land_allocation.py`; default Soft (existing behaviour unchanged — this
  is critical, do not regress pure-suitability runs).
- **Tests**: 4×4 parcel grid where greedy non-contiguous allocation splits a
  use; assert hard mode yields exactly one component per use
  (verify via BFS in the test) and area targets within one parcel.

Release as **v2.12.0**; update ROADMAP (move both items from Future ideas to
shipped), ~+14 unit / +10 e2e checks.

---

## 4. Phase B — v2.13 "Equity Cross-Tabs & Scenario Compare" (roadmap queue 2)

### B1. Demographic Equity Cross-Tabs (Equity group)
Distribution of any per-unit value **by population subgroup** (e.g. access
score × income quintile, green space × age group).

- **Engine** `equity.crosstab(values, weights, group_a, group_b=None)`:
  weighted quantile breakdown per group (min/P10/median/mean/P90/max, share
  of total value vs share of population), per-group Gini, between-group
  dissimilarity index, and a representation ratio per (group, value-quintile)
  cell (share in cell ÷ population share; 1.0 = proportional).
- **Algorithm** `alg_equity_crosstab.py` (`planx:equitycrosstab`): input
  layer, value field, population weight field, group field, optional second
  group field, optional custom value-class breaks. Outputs: cross-tab table
  layer (one row per group×quintile with counts, shares, representation
  ratio), per-group summary table, and the input annotated with quintile +
  group rank fields. Log prints the headline: which group is most
  over/under-represented in the worst quintile.
- **Tests**: two-group synthetic where group A holds all low values; assert
  representation ratios and dissimilarity index against hand calc.

### B2. Scenario Compare in the dashboard + `planx:scenariocompare`
A/B plan score cards side by side.

- **Engine** `scenario.py` (new, pure stdlib+numpy):
  - `snapshot_from_summaries(name, cards: dict) -> dict` and
    `compare(snap_a, snap_b) -> list[delta rows]` (absolute + percent delta,
    direction goodness per metric — a registry says whether higher is better
    for each known card key).
  - JSON (de)serialisation of snapshots (`to_json`/`from_json`).
- **Dashboard dock**: add a "Scenario" row — buttons *Save snapshot A*,
  *Save snapshot B* (captures the currently detected score cards into JSON,
  file-persisted next to the project via `QgsProject` home path), and a
  compare panel rendering card / A / B / Δ with green/red arrows honouring
  the higher-is-better registry.
- **Algorithm** `alg_scenario_compare.py` (`planx:scenariocompare`): takes
  two snapshot JSON files (or two layer groups), writes a comparison table
  and an HTML section appended into the Plan Performance Report
  (`engine/report.py` gains a `compare_section(rows)` renderer).
- **Tests**: snapshot→compare round-trip; deltas and direction flags; report
  section renders and contains both scenario names.

Release as **v2.13.0**. After this, the Future-ideas queue is empty; the
ROADMAP gains the v3 series below.

---

## 5. Phase C — v3.0 "Scenarios & Walkability" (headline release)

### C1. Scenario Snapshot algorithm (Reporting group)
Generalise B2 into a first-class workflow: `planx:scenariosnapshot` walks the
project (or a selected layer group), detects every PlanX output layer by
field signature (reuse `dashboard_dock._SIGNATURES` — move that dict into
`engine/report.py` so both share it), computes all score cards, and writes
one snapshot JSON + a table layer. This makes scenarios batchable in the
model designer: run plan → snapshot → compare, fully headless.

### C2. Walkability Audit (new group: **Walkability**)
Composite street-level walkability score per street segment — the audit
layer planners currently do in spreadsheets.

- **Engine** `walkability.py`:
  - `segment_scores(...)` combining, per network segment: intersection
    density within radius (from the primal graph), link-node ratio, average
    block length, land-use mix entropy within buffer (Shannon over category
    areas), destination density (POI count within buffer), and optional
    slope penalty from a DEM sample. Each sub-score normalised 0–100 with
    documented breakpoints; weighted sum with user weights (defaults from
    the walkability literature — cite Frank et al. 2010 in docstring).
- **Algorithm** `alg_walkability.py` (`planx:walkability`): network layer,
  land-use polygons (+category field), POI points, optional DEM, radius,
  weight table (like the standards param pattern in Land-Use Balance).
  Output: segments with sub-scores + total walk score, styled graduated.
  Log: city-wide mean, top/bottom 5% streets.
- **Tests**: 2-segment toy case with hand-computed mix entropy and density;
  e2e on the fixture network + synthetic land-use polygons.

### C3. Pedestrian Route Quality (Walkability group)
Shortest path A→B on the network, but reporting **quality along the route**:
length, turns, walk-score-weighted cost vs plain shortest, share of route on
low-walkability segments. Reuses `paths.py` Dijkstra with per-edge weights =
length × (1 + penalty·(100 − walkscore)/100).

- **Algorithm** `alg_route_quality.py` (`planx:routequality`): origins layer,
  destinations layer (pairing: nearest / all-pairs cap), the walkability
  output as edge attribute source. Outputs route lines with quality fields.
- **Tests**: grid network where scenic longer route beats short ugly one at
  high penalty; assert switch point.

Release as **v3.0.0** — the major-version story is "PlanX becomes
scenario-aware and gains a Walkability group". Rewrite the metadata `about`
paragraph accordingly (keep it one paragraph per theme, same tone as now).

---

## 6. Phase D — v3.1 "Transit" (new group: **Transit**)

Pure-stdlib GTFS reading (zip + csv modules — no pandas).

- **Engine** `transit.py`:
  - `read_gtfs(path)` → dict of arrays for stops, trips, stop_times, routes,
    calendar (validate required files; tolerate missing optional ones).
  - `stop_frequencies(gtfs, day, window)` → departures/hour + mean headway
    per stop for a service day and time window (resolve `calendar` +
    `calendar_dates`).
  - `timetable_access(gtfs, network, origins, departure, max_time)` → a
    simplified RAPTOR-style computation: earliest arrival per stop given a
    departure time, walk access/egress via the street network Dijkstra
    (walk speed param), max 2 transfers (param). This is the heavy piece —
    keep arrays flat (NumPy), pre-sort stop_times by trip, and honour cancel.
- **Algorithms**:
  1. `planx:gtfsimport` — load stops/routes as layers + service-summary
     table (routes, trips/day, span). Also the validation front door: clear
     errors for malformed feeds.
  2. `planx:transitfrequency` — stops layer with departures/hour, headway,
     styled by frequency class; optional route-level frequency lines.
  3. `planx:transitaccess` — travel-time raster or point layer: minutes to
     reach each demand point / grid cell from an origin (or to nearest N
     amenities) using walk+transit; the transit sibling of the 15-minute
     tool.
- **Tests**: bundle a tiny synthetic GTFS (6 stops, 2 routes, 1 transfer) as
  a test fixture built in-code (write the zip in the test, don't commit
  binaries); hand-compute earliest arrivals incl. one transfer; assert
  frequency counts. E2E: run all three on the synthetic feed.
- **Traps**: GTFS times can exceed 24:00:00 (parse as seconds, don't use
  datetime); stop_times is the big table — never build Python objects per
  row, parse straight into typed NumPy arrays.

---

## 7. Phase E — v3.2 "Visibility" (new group: **Visibility**)

Reuses the raster I/O helpers in `algorithms/_raster.py` and the DSM sweep
machinery style from `engine/solar.py`.

- **Engine** `visibility.py`:
  - `viewshed(dsm, transform, observer_xy, observer_h, target_h, radius)` —
    line-of-sight over the DSM using ray casting per direction with the same
    horizon-scan pattern as SVF (N directions × radial step), boolean grid.
  - `isovist(obstacles_mask, origin, n_rays, max_dist)` — 2D isovist polygon
    from building footprints rasterised to a mask; returns area, perimeter,
    max/min radial, circularity, occlusivity.
  - `isovist_field(mask, grid_points, ...)` — isovist metrics sampled on a
    grid (vectorised ray march over the mask).
- **Algorithms**:
  1. `planx:viewshed` — DSM + observer points (+height fields) → visible
     raster (per observer + combined count band), % of study area visible.
  2. `planx:isovistfield` — buildings + study area + cell size → point grid
     with isovist area/circularity/occlusivity (the space-syntax VGA
     companion to the network tools), styled graduated.
  3. `planx:visualexposure` — landmark polygons + DSM → raster of "can see
     the landmark" (inverse viewshed from sampled landmark rim points),
     for skyline/heritage impact screening.
- **Tests**: flat DSM with one wall → viewshed shadow shape asserted
  cell-exact on a small grid; square room isovist area ≈ analytic value.
- **Trap**: cap rays at raster diagonal (same low-angle lesson as the shadow
  sweep fix in v2.5).

---

## 8. Phase F — v3.3 "Population & Housing" (new group: **Population & Housing**)

- **Engine** `population.py`:
  - `cohort_projection(pop_by_age, survival, fertility, migration, years, step=5)`
    — Leslie-matrix cohort-component projection (NumPy matrix power with
    per-step migration add); returns per-step age pyramid + totals.
  - `housing_needs(households, dwellings, vacancy_target, overcrowd, demolition_rate, projection)`
    — standard needs arithmetic → units needed per period.
  - `residential_capacity(parcels_area, zoning_far, existing_floorspace, unit_size, efficiency)`
    — buildable floorspace → dwelling capacity per parcel.
- **Algorithms**:
  1. `planx:populationprojection` — table/layer of age-group populations +
     rate params (defaults documented, all editable; optional rates table
     layer) → projection table + pyramid data (feeds the HTML report: add a
     pyramid SVG renderer to `engine/report.py`).
  2. `planx:housingneeds` — combines projection output (or direct inputs)
     with housing-stock params → needs table per period + headline log.
  3. `planx:residentialcapacity` — parcels + FAR/zoning fields → per-parcel
     capacity, remaining capacity vs existing, district roll-up; the bridge
     to Land-Use Allocation (its output can be the allocation's target
     source — mention in help text).
- **Tests**: 3-cohort hand-computed Leslie projection over 2 steps; capacity
  arithmetic edge cases (existing > buildable → 0, not negative).

---

## 9. Phase G — v3.4 "Environment Screening" (Microclimate group + new **Green Infrastructure** group)

- **Engine** `noise.py` — CNOSSOS-EU-lite road noise screening:
  `emission_level(aadt, speed, heavy_share)` per segment (use the CNOSSOS
  simplified emission formulas; cite them), then
  `propagate(sources, receivers_grid, buildings_mask)` with distance
  attenuation + fixed ground factor + first-order building screening
  (line-of-sight blocked → fixed insertion loss param, default 10 dB).
  Document loudly in help text: **screening quality, not compliance
  modelling.** Output Lden-style dB grid + facade values on buildings.
  - Algorithm `planx:noisescreen` — roads (+AADT/speed/heavy fields),
    buildings, cell size → noise raster + exposed-population estimate if a
    population field/layer given.
- **Engine** `green.py`:
  - `green_access(...)` — reuse network Dijkstra: nearest public green space
    within size classes (pocket/local/district park hierarchies — the
    "300 m to 0.5 ha" style standards as a param table), per-dwelling
    provision m²/capita in catchments.
  - `green_connectivity(patches, max_gap)` — patch adjacency graph within a
    gap distance; component sizes, Probability of Connectivity–style index
    (area-weighted), per-patch importance by removal (delta index).
- **Algorithms** `planx:greenaccess`, `planx:greenconnectivity` in the new
  Green Infrastructure group.
- **Tests**: noise — single straight road, hand-computed dB at 3 distances,
  screened receiver behind a building loses exactly the insertion loss;
  green — 3-patch chain where removing the middle patch collapses the index.

---

## 10. Phase H — v3.5 "Urban Growth" (new group: **Urban Growth**)

- **Engine** `growth.py`:
  - `change_matrix(lc_t1, lc_t2)` — cross-tab of two land-cover rasters:
    transition matrix, gains/losses/persistence per class, annualised rate.
  - `ca_simulate(seed_urban, suitability, constraints, neighbors_weight, demand_cells, iterations, rng_seed)`
    — constrained cellular-automaton growth (SLEUTH-flavoured but simple):
    per-iteration transition probability = suitability × neighbourhood urban
    share, masked by constraints, top-k cells convert until the demand for
    that step is met. **Deterministic**: NumPy `default_rng(user_seed)`;
    never seed from `hash()` of anything (Python randomises str hash per
    process).
  - `sprawl_metrics(urban_mask, pop)` — urban expansion vs population growth
    ratio, largest-patch share, edge density, proximity-to-centre profile.
- **Algorithms** `planx:landcoverchange`, `planx:growthsim` (multi-step
  output: one band per horizon year + final vector hull),
  `planx:sprawlmetrics`.
- **Tests**: 2-class toy rasters with hand-counted transitions; CA with a
  suitability gradient must grow along the gradient, identical across two
  separate processes with the same seed (cross-process determinism test).

---

## 11. Phase I — v3.6 "Suite Polish"

1. **Batch Plan Auditor** (`planx:planaudit`, Reporting group): one
   algorithm that chains the suite over a project — given network, buildings,
   land use, facilities, population inputs, it runs the standard battery
   (access score, balance, adequacy, walkability, green access, equity) with
   default params, snapshots the results, and emits the full HTML report +
   snapshot JSON. Implement by invoking `processing.run()` on PlanX's own
   algorithm ids (this is allowed in the algorithms layer, not engine).
2. **Dashboard upgrade**: card sparkline history (append每-snapshot values),
   group filter, and a "run Plan Auditor" button.
3. **Docs**: `docs/` gains a methods page per group (formulas + literature
   refs + worked micro-example each) — publishable via GitHub Pages with a
   `.zipignore` entry so docs stay out of the plugin zip (pattern exists in
   planx_cartolab).
4. Sweep: help strings for all ~45 algorithms reviewed for consistency;
   README tool table regenerated; hero image updated.

---

## 12. Cross-cutting engineering notes for the agent

- **Fixtures**: extend the existing e2e fixture builders in
  `scratch/planx_e2e_qgis.py`; keep every fixture synthetic and generated
  in-code (no committed binary data).
- **Rasters**: use `algorithms/_raster.py` helpers for read/write; multiband
  writing pattern exists from Annual Solar (named bands).
- **Performance**: any O(cells × directions × steps) raster sweep must
  report progress via `feedback.setProgress` and check cancellation each
  direction; any O(n²) vector loop must use a `QgsSpatialIndex`.
- **Qt6/QGIS4**: use scoped enums (`Qt.PenStyle.SolidLine` style) in any new
  dock code; test dock rendering offscreen on both QGIS versions.
- **Icons**: one per algorithm, group-coloured; follow existing icon
  generation scripts in `scratch/` — do not hand-draw inconsistent icons.
- **Changelogs**: newest at top in both `metadata.txt` (indented block) and
  `CHANGELOG.md`; never a bare `%`.
- **Version discipline**: one phase = one minor version = one tag. Never
  reuse or renumber a released tag.

## 13. Definition of done (whole plan)

- ~45 algorithms across 14 groups, all icon-ed, all in Studio dock.
- Unit checks grown from 216 to ≥ 400; e2e assertions from 166 to ≥ 300,
  green on QGIS 3.44 LTR and QGIS 4.
- Dashboard: scenario A/B compare + sparklines + auditor button.
- flake8/bandit/zip-audit clean at every tag; ROADMAP reflects reality.
