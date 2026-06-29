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
| Microclimate (v2.5) | Heat Island Risk Grid | built/green/water/height composite, fixed-scale 0-100 risk |
| Plan Standards (v2.2) | Land-Use Balance | per-capita areas vs configurable standards, surplus/deficit |
| Plan Standards (v2.2) | Facility Adequacy | capacity + catchment distance, utilization & coverage |
| Plan Standards (v2.2) | Density Grid | area-share dasymetric disaggregation, density/ha |
| Reporting (v2.3) | Plan Performance Report (HTML) | one-file scorecard report: inline-SVG charts, balance bars, score map |
| Optimization (v2.4) | Facility Location Optimizer | greedy maximal coverage (Church & ReVelle) / p-median (Teitz-Bart), candidate screening |
| Optimization (v2.6) | Capacitated Allocation | nearest facility with free capacity, spill when full, uncovered when none in reach |
| Equity (v2.6) | Accessibility Equity | population-weighted Gini, Theil between/within decomposition, P90/P10, access-poverty share |

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

### Future ideas (post-2.6, unscheduled)

- Capacitated facility *siting* (choose where to build while respecting
  capacities — siting + the capacitated allocation now shipped, together).
- Land-use allocation optimizer (multi-objective parcel assignment).
- Scenario comparison in the dashboard (A/B plan score cards side by side).
- Annual/monthly solar aggregation (multi-day irradiation sweeps).
- More equity lenses (Atkinson index, concentration/Lorenz export,
  demographic cross-tabs).

## Quality gates (every release)

- Engine unit tests vs hand-computed graphs (betweenness/closeness/NACH on
  known topologies; scipy and fallback paths must agree exactly).
- Headless e2e on real QGIS 3 LTR **and** QGIS 4 (`scratch/planx_e2e_qgis.py`).
- flake8 clean; bandit 0 High/Medium; zip audit (single root, no bare `%`).
