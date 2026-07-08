# PlanX 2.0 — Urban Analytics Studio: Architecture & Roadmap

> PlanX is the flagship of the PlanX QGIS plugin ecosystem: an **embedded urban
> analytics engine**. Space syntax, every major centrality measure, urban
> morphology, and network accessibility — all computed *inside* the plugin,
> with no external services, no third-party plugins (no QNEAT3, no GRASS
> requirement beyond stock QGIS), and no pip installs.

## Design principles

1. **Real computation, embedded.** Every metric is implemented from the
   primary literature (Brandes 2001; Hillier & Iida 2005; Turner 2001;
   Berghauser Pont & Haupt Spacematrix; Boeing 2019). No `networkx`,
   `momepy`, `osmnx`, or server calls.
2. **Fast path + safe fallback.** NumPy is the floor (ships with QGIS).
   When SciPy is present (all official Windows/macOS builds), shortest paths
   run through `scipy.sparse.csgraph` at C speed; otherwise a pure-Python
   `heapq` Dijkstra produces *identical* results.
3. **Processing-first.** Every tool is a `QgsProcessingAlgorithm`: usable in
   the toolbox, the model designer, batch mode, and headless e2e tests.
4. **English-only UI.** Standards/regulation values are parameters, never
   hard-coded locale assumptions.
5. **Honest performance.** Radius-limited analysis is the default idiom
   (as in space syntax practice); global runs warn and stay cancellable.

## Package layout

```text
planx/
  __init__.py          # classFactory
  planx.py             # plugin shell: provider registration + PlanX menu + Studio dock
  provider.py          # QgsProcessingProvider (id: "planx")
  engine/              # pure numpy/scipy analytics core — NO qgis imports
    graphs.py          #   polyline set -> primal node graph (CSR) + dual segment graph
    paths.py           #   Dijkstra: csgraph fast path / heapq fallback (identical output)
    centrality.py      #   closeness, straightness, Brandes betweenness (radius/sampled)
    syntax.py          #   segment angular analysis: integration, choice, NAIN, NACH
    morphology.py      #   pure-geometry shape metrics + orientation entropy
  algorithms/          # thin QgsProcessingAlgorithm wrappers over engine/
  tests/               # engine unit tests vs hand-computed graphs (run under OSGeo4W python)
  docs/                # this roadmap + methods notes
```

## v2.0.0 tool inventory (shipped)

| Group | Algorithm | Core method |
|---|---|---|
| Network Analysis | Prepare Network | node lines at intersections, drop duplicates/zero-length |
| Network Analysis | OD Cost Matrix | many-to-many network Dijkstra, detour ratio, desire lines |
| Network Analysis | Service Areas (Isochrones) | multi-source min-cost bands, edge classes + band polygons |
| Network Analysis | Nearest Facility Allocation | multi-source Dijkstra with source tracking + facility load |
| Centrality & Space Syntax | Network Centrality | degree, closeness, straightness, Brandes betweenness (node + edge), radius-limited |
| Centrality & Space Syntax | Space Syntax (Segment Angular) | angular cost dual graph, integration/choice, NACH/NAIN per radius |
| Urban Morphology | Building Form Metrics | area/perimeter/IPQ/convexity/rectangularity/elongation/orientation/courtyards/fractal dim/shared walls |
| Urban Morphology | Morphological Tessellation | densified building boundaries -> Voronoi -> dissolve per building |
| Urban Morphology | Spacematrix Density | GSI/FSI/OSR/L per block + Spacematrix class |
| Urban Morphology | Street Network Morphology | orientation entropy & order (Boeing), meshedness, node typology |
| Accessibility | Multi-Amenity Access Score | 15-minute-city composite: per-category nearest times + coverage score |
| Microclimate (v2.1) | Shadow Casting (DSM) | NOAA sun position + UMEP-style iterative DSM sweep |
| Microclimate (v2.1) | Sky View Factor (DSM) | N-direction horizon scan, SVF = 1 - mean sin² horizon |
| Microclimate (v2.1) | Frontal Area Index | λf/λp roughness grid, footprint-share distribution |
| Microclimate (v2.5) | Sun Hours | whole-day shadow sweep -> direct-sun hours per cell |
| Microclimate (v2.5) | Solar Irradiation | ASHRAE clear-sky beam (shadow-aware) + SVF-weighted diffuse, kWh/m2/day |
| Microclimate (v2.9) | Annual Solar Potential | year-long clear-sky kWh/m2/yr from twelve representative average-day sweeps (Klein 1977; Duffie & Beckman), optional 12-band monthly raster |
| Microclimate (v2.5) | Heat Island Risk Grid | built/green/water/height composite, fixed-scale 0-100 risk |
| Plan Standards (v2.2) | Land-Use Balance | per-capita areas vs configurable standards, surplus/deficit |
| Plan Standards (v2.2) | Facility Adequacy | capacity + catchment distance, utilization & coverage |
| Plan Standards (v2.2) | Density Grid | area-share dasymetric disaggregation, density/ha |
| Reporting (v2.3) | Plan Performance Report (HTML) | one-file scorecard report: inline-SVG charts, balance bars, score map |
| Optimization (v2.4) | Facility Location Optimizer | greedy maximal coverage (Church & ReVelle) / p-median (Teitz-Bart), candidate screening |
| Optimization (v2.6) | Capacitated Allocation | nearest facility with free capacity, spill when full, uncovered when none in reach |
| Equity (v2.6) | Accessibility Equity | population-weighted Gini, Theil between/within decomposition, P90/P10, access-poverty share |
| Equity (v2.11) | Inequality Curves (Lorenz & Atkinson) | exportable Lorenz/concentration curve + Gini + Atkinson index at a chosen inequality aversion |
| Optimization (v2.7–2.8) | Land-Use Allocation Optimizer | assign parcels to uses maximising suitability + compactness + adjacency under per-use area targets (greedy + capacity-respecting swaps) |
| Optimization (v2.10) | Land-Use Pareto Front | sweep compactness weights → non-dominated suitability-vs-compactness trade-off + knee + chosen parcel plan |
| Optimization (v2.12) | Capacitated Facility Siting | greedy construction + capacity-aware Teitz-Bart swap improvement |
| Optimization (v2.12) | Land-Use Allocation Optimizer | gains a Hard Contiguity mode (single connected zone per use via region-growing + boundary swaps) |

## Release roadmap

- **v2.1 — Microclimate (UMEP-lite):** SHIPPED 2026-06-11 — DSM shadow
  casting (embedded NOAA sun position), Sky View Factor, frontal area index.
- **v2.2 — Plan Standards & QA:** SHIPPED 2026-06-11 — land-use balance vs
  configurable per-capita standards, facility adequacy (capacity +
  distance), dasymetric density grids.
- **v2.3 — Performance Dashboard:** SHIPPED 2026-06-11 — "Plan Dashboard"
  dock with live score cards over the PlanX output layers (auto-detected by
  field signatures) + one-click single-file HTML "Plan Performance Report"
  (score histogram + SVG score map, standards balance bars, facility
  utilization, density summary), also available headless as the
  `planx:performancereport` algorithm. Pure-stdlib `engine/report.py`.
- **v2.4 — Optimization:** SHIPPED 2026-06-11 — Facility Location Optimizer
  (new "Optimization" group): greedy maximal coverage (Church & ReVelle
  1974) and p-median via greedy construction + Teitz & Bart (1968) vertex
  substitution in pure-NumPy `engine/optimize.py`, network distances from
  the embedded Dijkstra kernels; existing facilities enter the solution as
  fixed sites; every candidate gets a standalone screening score (demand
  within the catchment); outputs selected sites (rank + marginal gain) and
  demand allocation (facility, cost, covered).

- **v2.5 — Microclimate II + per-tool icons:** SHIPPED 2026-06-11 — Sun
  Hours (whole-day direct-sun maps), clear-sky Solar Irradiation
  (shadow-aware ASHRAE beam + SVF-weighted isotropic diffuse, kWh/m2/day),
  vector Heat Island Risk Grid (fixed-scale 0-100 from buildings/green/
  water), eigenvector centrality in Network Centrality,
  population-weighted 15-minute-city summary, and a distinct
  group-coloured icon for every algorithm (toolbox + Studio dock).
  Engine fix: shadow sweep capped at the raster diagonal (low-sun crash).

- **v2.6 — Equity & Allocation:** SHIPPED 2026-06-29 — **Accessibility
  Equity** (new "Equity" group): population-weighted Gini, Theil's T with
  an additive between/within-group decomposition (the environmental-justice
  view), P90/P10, coefficient of variation and an access-poverty share, on
  any per-unit value (access score, travel time, distance); per-unit
  percentile rank / deviation / poverty flag plus a per-study-area and
  per-group summary table. **Capacitated Allocation** (Optimization group):
  sends each demand point in full to the nearest facility with free
  capacity, spilling to the next when full and leaving the rest uncovered —
  the realistic companion to Facility Adequacy. New pure-NumPy
  `engine/equity.py` and `engine/optimize.capacitated_assign`; 156 unit +
  126 e2e checks on QGIS 3.44 LTR and QGIS 4.0.2.

- **v2.7 — Land-Use Allocation Optimizer:** SHIPPED 2026-06-29 — new
  Optimization tool that assigns a land use to each parcel to maximise
  total area-weighted suitability while meeting a target area for each use
  (capacitated generalized-assignment heuristic: greedy construction +
  reassignment + capacity-respecting pairwise swaps), with an optional
  lock field for already-zoned parcels and a per-use target-vs-allocated
  summary. Pure-NumPy `engine/allocate.py`; 168 unit + 137 e2e checks on
  QGIS 3.44 LTR and QGIS 4.0.2.

- **v2.8 — Multi-objective land-use allocation:** SHIPPED 2026-06-29 — the
  Land-Use Allocation Optimizer gains spatial objectives beyond
  suitability: a **compactness** weight (reward same-use shared boundary →
  contiguous zones) and free-text **adjacency rules**
  (`residential|industry=-2`) that reward/penalise use pairs being
  neighbours, plus an advanced suitability weight to balance them. Objective
  `w_suit·Σ(area·suit) + Σ_adjacent L·C[use,use]` over the parcel adjacency
  graph (shared-boundary lengths via a spatial index); greedy + local
  search (reassignment + capacity-respecting swaps) on the full objective.
  New `engine/allocate.allocate_multi` (shared core with the 2.7
  single-objective function); 175 unit + 141 e2e checks on QGIS 3.44 LTR
  and QGIS 4.0.2. Pure-suitability runs are unchanged.

- **v2.9 — Annual Solar Potential:** SHIPPED 2026-06-29 — a new Microclimate
  tool that sums clear-sky global solar irradiation over a whole year
  (kWh/m2/yr) for rooftop-PV screening, annual solar access and year-round
  heat exposure. Rather than sweeping all 365 days, one representative
  average day per month (Klein 1977; Duffie & Beckman) is computed with the
  same shadow-aware beam + SVF-weighted diffuse kernel as the single-day
  Solar Irradiation tool, scaled by the days in that month and summed —
  twelve day-sweeps stand in for the year. Outputs the annual raster and an
  optional 12-band monthly raster (named bands); the log reports the
  flat-ground annual reference, scene statistics and the peak month. New
  pure-NumPy `engine/solar.annual_irradiation` (reuses the daily kernel) and
  a multi-band GeoTIFF writer; 191 unit + 150 e2e checks on QGIS 3.44 LTR
  and QGIS 4.0.2.

- **v2.10 — Land-Use Pareto Front:** SHIPPED 2026-06-30 — a new Optimization
  tool that maps the suitability vs compactness TRADE-OFF instead of one
  weighted run. It solves the Land-Use Allocation Optimizer across a sweep of
  compactness weights (auto-scaled to the data, or capped by an upper weight)
  and records two higher-is-better scores per result — area-weighted
  suitability and the shared boundary between adjacent same-use parcels
  (compactness) — then reports the non-dominated set (the Pareto front) and
  its knee (furthest from the chord joining the front's extremes, the
  best-balanced point). Outputs a front table to plot (both scores raw and
  normalised, on-front / knee / selected flags) and the parcel map of one
  chosen solution (knee by default, or the max-suitability / max-compactness
  end). New pure-NumPy `engine/allocate.pareto_front` + `pareto_mask` + knee
  detector reusing the multi-objective core; 202 unit + 158 e2e checks on
  QGIS 3.44 LTR and QGIS 4.0.2.

- **v2.11 — Inequality Curves (Lorenz & Atkinson):** SHIPPED 2026-06-30 — a
  new Equity tool for the distributional view of any per-unit good. Outputs
  the Lorenz curve as a table (cumulative population vs value share) with the
  Gini, and the Atkinson index at low/medium/high inequality aversion
  (ε = 0.5, 1, 2) plus the user's ε — higher ε weights the lower tail more. A
  rank field switches it to a concentration curve and index (whether the
  value leans to the advantaged or disadvantaged end). New pure-NumPy
  `engine/equity.atkinson_index` / `lorenz_points` / `gini_from_lorenz` /
  `concentration_index`; 216 unit + 166 e2e checks on QGIS 3.44 LTR and
  QGIS 4.0.2.

- **v2.12 — Siting & Contiguity:** SHIPPED 2026-07-08 — a new Capacitated
  Facility Siting tool (greedy construction + capacity-aware Teitz-Bart swap)
  in Optimization group, and a new Hard Contiguity mode (region growing +
  connectivity-preserving boundary swaps) on the Land-Use Allocation algorithm.
  New pure-NumPy `engine/optimize.capacitated_siting` and
  `engine/allocate.allocate_contiguous`; 225 unit + 174 e2e checks on
  QGIS 3.44 LTR and QGIS 4.0.2.

### Future ideas (post-2.12, unscheduled)

- Scenario comparison in the dashboard (A/B plan score cards side by side).
- Demographic equity cross-tabs (value distribution by population subgroup).

## Quality gates (every release)

- Engine unit tests vs hand-computed graphs (betweenness/closeness/NACH on
  known topologies; scipy and fallback paths must agree exactly).
- Headless e2e on real QGIS 3 LTR **and** QGIS 4 (`scratch/planx_e2e_qgis.py`).
- flake8 clean; bandit 0 High/Medium; zip audit (single root, no bare `%`).
