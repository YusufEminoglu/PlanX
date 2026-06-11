# Changelog

All notable changes to PlanX are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
