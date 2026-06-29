# Changelog

All notable changes to PlanX are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [2.6.0] - 2026-06-29

Equity & Allocation release: two new tools — 24 algorithms total.

### Added
- **Accessibility Equity (Gini / Theil)** (new "Equity" group): measures
  how *fairly* a value is distributed across the population — the
  spatial-equity / environmental-justice view the level-of-access tools
  do not give. Feed it any per-unit value (an Access Score, a travel
  time, a distance to the nearest facility). Population-weighted
  indices: **Gini** coefficient, **Theil's T** additively decomposed
  into **between-group** and **within-group** inequality (give a group
  field — district, income class, tenure — and the between share is the
  environmental-justice headline), **P90/P10** ratio, coefficient of
  variation and an **access-poverty share** (population beyond a
  threshold). Outputs the input units enriched with their weighted
  percentile rank, deviation from the mean and a poverty flag, plus a
  summary table — one row for the study area and one per group.
- **Capacitated Allocation (Nearest with Capacity)** (Optimization
  group): allocates demand to fixed facilities while **respecting
  capacity** — the realistic companion to Facility Adequacy (which
  assigns everyone to the nearest facility and only flags the overload
  afterwards). Each demand point is sent in full to the nearest facility
  with room and **spills** to the next-nearest when its nearest is full;
  points that fit nowhere in reach are left **uncovered**. Outputs the
  demand (assigned facility, network cost, status Assigned / Spilled /
  Uncovered, nearest facility) and the facilities (assigned load,
  remaining capacity, utilization, status Full / Has space / Unused).
- `engine/equity.py` (Gini, Theil T and decomposition, weighted
  quantiles, percentile ratio/rank, CV, poverty shares) and
  `engine/optimize.capacitated_assign` — pure NumPy, unit-tested; two
  new group-coloured tool icons.

### Tests
- Engine suite 131 → 156 checks (incl. the weighted Gini against the
  O(n²) mean-difference definition and the Theil between+within
  identity); e2e harness 109 → 126 assertions with hand-computed equity
  indices and a capacity-denial/spill scenario — verified on QGIS 3.44
  LTR and QGIS 4.0.2.

## [2.5.1] - 2026-06-18

- docs: add CITATION.cff for Zenodo DOI integration

## [2.5.0] - 2026-06-11

Microclimate II + per-tool icons: three new tools — 22 algorithms total.

### Added
- **Sun Hours (DSM)** (Microclimate): hours of direct sunlight per cell
  over one full day in a single run — the day is swept at a configurable
  interval (default 30 min), each step casts the DSM shadow mask with the
  embedded NOAA sun position. Replaces the old "run Shadow Casting in
  Batch mode" workaround. Right-to-light checks, courtyard/playground sun
  audits; the log reports the site's potential daylight.
- **Solar Irradiation (DSM)** (Microclimate): clear-sky daily global
  irradiation per cell (kWh/m²) — ASHRAE-style beam (Masters 2004) blocked
  by cast shadows + isotropic diffuse weighted per cell by the sky view
  factor. Quick screening of roofs and open spaces for solar potential or
  summer heat exposure; flat-ground reference reported for comparison.
- **Heat Island Risk Grid** (Microclimate): vector UHI screening from the
  layers every plan already has — building footprints (with optional
  height field), green areas and water polygons. Per cell: built fraction,
  area-weighted mean height, green/water fractions and a **fixed-scale
  0–100 risk score** (weights are parameters; the scale is set by the
  weights, not stretched to the data, so scenarios stay comparable) with
  Low/Moderate/High/Very High classes.
- **Eigenvector centrality** in Network Centrality (Bonacich power
  iteration on A + I — the shift makes it converge on bipartite street
  graphs; max-normalized to 1), new `eigen` field on junction output.
- **Population-weighted summary** in Multi-Amenity Access Score: optional
  population field on origins reports total population, weighted mean
  score, share with full access and share with no category reachable.
- **Per-tool icons**: all 22 algorithms now carry their own meaningful
  icon (colour-coded by group) in the Processing toolbox and the PlanX
  Studio dock; the Plan Dashboard menu action got the report icon.
  Generator: `scratch/make_planx_tool_icons.ps1` (GDI+, 256 px PNG).
- `engine/solar.py`: `sun_hours`, `clear_sky_irradiance`,
  `daily_irradiation`, `heat_risk_index`; `engine/centrality.py`:
  `eigenvector` (all pure NumPy, unit-tested).

### Fixed
- Shadow casting could crash (negative-slice broadcast in the array
  shifter) and wastefully over-scan at very low sun altitudes: shifts
  beyond the raster now short-circuit and the sweep is capped at the
  raster diagonal.

### Tests
- Engine suite 111 → 131 checks; e2e harness 90 → 109 assertions —
  verified on QGIS 3.44 LTR and QGIS 4.0.2 (including icon coverage).

## [2.4.0] - 2026-06-11

Optimization release: facility location on the network — 19 algorithms
total. The v2.x roadmap is complete.

### Added
- **Facility Location Optimizer (Coverage / P-Median)** (new
  "Optimization" group): chooses the best sites for new facilities among
  candidate locations on real network distances — no external solver.
  - *Maximize coverage* (Church & ReVelle 1974): greedy picks, each adding
    the most uncovered weighted demand within the catchment radius;
  - *Minimize total travel* (p-median): greedy construction + Teitz & Bart
    (1968) vertex substitution on the population-weighted travel cost;
  - existing facilities (optional) are kept in the solution as fixed
    sites — new picks complement them;
  - outputs: every candidate with its standalone **screening score**
    (demand within reach), selection flag, pick rank and marginal gain;
    plus the demand allocation (assigned facility, network cost, covered).
- `engine/optimize.py`: coverage weights, greedy maximal coverage,
  p-median with vertex substitution and penalty handling for unreachable
  demand, nearest-assignment helper (pure NumPy, unit-tested).
- Tests: engine suite 98 → 111 checks (incl. a greedy-trap case the
  substitution phase must escape); e2e harness 80 → 90 assertions with
  hand-computed selections, verified on QGIS 3.44 LTR and QGIS 4.0.2.

## [2.3.0] - 2026-06-11

Performance Dashboard release: live score cards + one-click HTML report —
18 algorithms total.

### Added
- **Plan Dashboard dock** (PlanX menu → Plan Dashboard): live score cards
  over the PlanX output layers — Plan Performance Index, accessibility
  score, standards compliance, covered-population share and density. The
  output layers of Multi-Amenity Access Score, Land-Use Balance, Facility
  Adequacy and Density Grid are auto-detected in the project by their field
  signatures; "Save HTML Report…" exports the report and opens it in the
  browser.
- **Plan Performance Report (HTML)** algorithm (new "Reporting and
  Dashboard" group): builds the same single-file report headless / in the
  model designer — score cards, score histogram, SVG score map (red→green),
  provided-vs-required balance bars, facility utilization table and density
  summary. Everything is inline CSS/SVG drawn by the embedded engine: a
  shareable one-file report with no external assets or services.
- `engine/report.py`: summaries, score cards, colour ramp and the full
  HTML/SVG renderer (pure stdlib — not even NumPy — unit-tested anywhere).
- Tests: engine suite 77 → 98 checks; e2e harness 70 → 80 assertions, all
  verified on QGIS 3.44 LTR and QGIS 4.0.2; new headless dashboard-dock
  check (auto-detection + cards) on both.

## [2.2.0] - 2026-06-11

Plan Standards & QA release: three new tools in a new group — 17 algorithms
total.

### Added
- **Land-Use Balance (Per-Capita Standards)**: the classic balance table —
  area and m² per capita per category, required area from *configurable*
  per-capita standards ("green=10, education=4"...), surplus/deficit and
  status. Standards are free text, never hard-coded regulation values;
  keywords match category names by containment.
- **Facility Adequacy (Capacity + Distance)**: one multi-source network
  pass assigns population to its nearest facility within a catchment cost,
  then compares assigned load with capacity — outputs facility utilization
  (Adequate / Overloaded / Unused) and covered/uncovered demand, with the
  covered-population share in the log.
- **Density Grid**: distributes any numeric value (population, dwellings,
  GFA) from polygons or points onto a regular grid by area share (simple
  dasymetric disaggregation) and reports density per hectare.
- `engine/standards.py`: standards parser, category matcher and balance
  computation (pure Python, unit-tested).
- Tests: engine suite 69 → 77 checks; e2e harness 56 → 70 assertions, all
  verified on QGIS 3.44 LTR and QGIS 4.0.2.

## [2.1.0] - 2026-06-11

Microclimate (UMEP-lite) release: three new tools in a new "Microclimate"
group, all on the embedded engine — 14 algorithms total.

### Added
- **Shadow Casting (DSM)**: cast shadows for any date and local time with an
  embedded NOAA solar-position model (sun altitude/azimuth computed at the
  raster center); UMEP-style iterative DSM sweep; byte raster output
  (1 = shadow), batch-friendly for shadow-duration maps.
- **Sky View Factor (DSM)**: hemispheric SVF per cell from N-direction
  horizon scans (SVF = 1 - mean sin² horizon; flat = 1, foot of a long
  wall ≈ 0.5); configurable directions and search radius.
- **Frontal Area Index**: λf (wind-facing facade area / cell area) and λp
  (plan area ratio) on a grid, building frontal areas distributed by
  footprint overlap (Grimmond & Oke roughness indicators).
- `engine/solar.py`: solar position (NOAA simplified), shadow ray-march,
  SVF horizon scan, projected footprint width — pure NumPy, no qgis
  imports.
- Tests: engine suite 52 → 69 checks (solstice/equinox sun positions,
  closed-form shadow lengths, SVF flat/wall values, projected widths);
  e2e harness 43 → 56 assertions (synthetic DSM tower) on QGIS 3 LTR + 4.

## [2.0.0] - 2026-06-11

Complete rewrite: PlanX is now the **Urban Analytics Studio** — an embedded
analytics engine with eleven Processing algorithms, zero external
dependencies, English-only UI.

### Added
- **Engine** (`engine/`): NumPy core with SciPy `csgraph` fast path and an
  identical pure-Python Dijkstra fallback; CSR primal (junction) and dual
  (segment/angular) graph builders; Brandes (2001) betweenness with radius
  limiting, pruned dual-cost search and source sampling; closeness
  (Wasserman–Faust + harmonic) and straightness; pure-geometry morphology
  kernels (shoelace, monotone-chain hull, rotating-calipers MRR,
  orientation entropy, meshedness).
- **Network Analysis**: Prepare Network (noding/dedupe/sliver removal),
  OD Cost Matrix (detour ratio, desire lines), Service Areas / Isochrones
  (multi-source bands as edges + dissolved polygons), Nearest Facility
  Allocation (assignment, spider lines, facility load summary).
- **Centrality & Space Syntax**: Network Centrality (degree, closeness,
  harmonic, straightness, node+edge betweenness); Space Syntax segment
  angular analysis with metric radii — integration, choice, NACH, NAIN
  (Hillier & Iida 2005; Hillier, Yang & Turner 2012).
- **Urban Morphology**: Building Form Metrics (IPQ, convexity,
  rectangularity, elongation, orientation, courtyards, fractal dimension,
  shared-wall ratio); Morphological Tessellation (Fleischmann method on
  native GEOS Voronoi); Spacematrix Density (GSI/FSI/OSR/L + class);
  Street Network Morphology (orientation entropy/order after Boeing 2019,
  alpha/beta/gamma indices, junction typology).
- **Accessibility**: Multi-Amenity Access Score — 15-minute-city composite
  over any number of amenity layers.
- **PlanX Studio dock**: grouped launcher for the toolset.
- New brand icon and hero banner; ROADMAP with the v2.x plan.
- Test suite: 52 engine unit checks vs hand-computed graphs; 43-assert
  end-to-end harness verified on QGIS 3.44 LTR **and** QGIS 4.0.2.

### Changed
- `hasProcessingProvider=yes`; minimum QGIS raised to 3.22; metadata,
  tags and description rewritten for the analytics scope.

### Removed
- The legacy mixed script collection (16 tools): QNEAT3/GRASS-dependent
  ODQNet and NetCentral, duplicates of other PlanX plugins (parcelflux,
  coverage footprint, road platform), and assorted utilities. Their
  network use-cases return as embedded, dependency-free implementations.

## [1.0.9] and earlier

Legacy PlanX script suite (2025): dynamic script loader with 16 mixed
tools. See git history for details.
