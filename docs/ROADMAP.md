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
| Plan Standards (v2.2) | Land-Use Balance | per-capita areas vs configurable standards, surplus/deficit |
| Plan Standards (v2.2) | Facility Adequacy | capacity + catchment distance, utilization & coverage |
| Plan Standards (v2.2) | Density Grid | area-share dasymetric disaggregation, density/ha |

## Release roadmap

- **v2.1 — Microclimate (UMEP-lite):** SHIPPED 2026-06-11 — DSM shadow
  casting (embedded NOAA sun position), Sky View Factor, frontal area index.
- **v2.2 — Plan Standards & QA:** SHIPPED 2026-06-11 — land-use balance vs
  configurable per-capita standards, facility adequacy (capacity +
  distance), dasymetric density grids.
- **v2.3 — Performance Dashboard:** dock with score cards + one-click HTML
  "Plan Performance Report" (accessibility maps + standards compliance).
- **v2.4 — Optimization:** facility location (greedy maximal coverage /
  p-median heuristic), network-aware site screening.

## Quality gates (every release)

- Engine unit tests vs hand-computed graphs (betweenness/closeness/NACH on
  known topologies; scipy and fallback paths must agree exactly).
- Headless e2e on real QGIS 3 LTR **and** QGIS 4 (`scratch/planx_e2e_qgis.py`).
- flake8 clean; bandit 0 High/Medium; zip audit (single root, no bare `%`).
