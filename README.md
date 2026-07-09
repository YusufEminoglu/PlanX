<div align="center">

<img src="icons/icon.png" width="96" alt="PlanX icon"/>

# PlanX

**Embedded urban analytics engine for QGIS: space syntax, centrality, urban morphology, OD matrices, isochrones and 15-minute-city scores — no external plugins or services.**

[![QGIS](https://img.shields.io/badge/QGIS-3.22%2B-93b023?logo=qgis&logoColor=white)](https://plugins.qgis.org/plugins/planx/)
[![Version](https://img.shields.io/github/v/tag/YusufEminoglu/PlanX?label=version&color=blue)](https://github.com/YusufEminoglu/PlanX/releases)
[![License](https://img.shields.io/badge/license-GPL--3.0-orange)](LICENSE)
[![QGIS Plugin Hub](https://img.shields.io/badge/QGIS%20Hub-install-589632?logo=qgis&logoColor=white)](https://plugins.qgis.org/plugins/planx/)

<img src="docs/hero.png" width="800" alt="PlanX in action"/>

</div>

---

## Why PlanX?

Urban analysts usually need four or five separate tools — depthmapX for space syntax, a routing plugin for isochrones, momepy for morphology, UMEP for shadows, a server for OD matrices. PlanX embeds real implementations of all of them directly inside QGIS: a NumPy/SciPy analytics engine (with an identical pure-Python fallback) drives fifty Processing algorithms that run locally, batch cleanly, and chain in the model designer. It is the flagship of the 15-plugin PlanX ecosystem.

## ✨ Features

- **Space syntax, embedded** — segment angular analysis (Hillier & Iida): integration, choice, **NACH/NAIN** at any metric radius. No depthmapX, no axial map.
- **The full centrality family** — degree, closeness (Wasserman–Faust + harmonic), straightness, **eigenvector** and exact **Brandes betweenness** on junctions *and* street segments, radius-limited or sampled for big networks.
- **Real network accessibility** — OD cost matrices with detour ratios, multi-facility **service-area isochrones**, nearest-facility allocation with load summaries.
- **15-minute city scores** — walking time to the nearest amenity of every category plus a 0–100 composite, straight from your own layers.
- **Urban morphology** — momepy-style building form metrics, **morphological tessellation**, Spacematrix **GSI/FSI/OSR/L** with readable class labels, street orientation entropy & meshedness (Boeing).
- **Microclimate screening** — UMEP-style **shadow casting** for any date/time (embedded NOAA solar position), **Sun Hours** (whole-day direct-sun maps), clear-sky **Solar Irradiation** (shadow-aware beam + SVF-weighted diffuse, kWh/m²), **Annual Solar Potential** (year-long clear-sky irradiation from twelve representative-day sweeps, kWh/m²/yr, with an optional monthly raster), **Sky View Factor**, frontal-area wind-roughness grids, and a vector **Heat Island Risk Grid** from the layers every plan already has.
- **Plan standards QA** — land-use balance against **configurable per-capita standards** (surplus/deficit per category), facility adequacy checking **capacity and distance together**, and dasymetric density grids.
- **Plan dashboard & report** — live score cards over your analysis layers (**Plan Dashboard** dock) and a one-click, single-file **HTML Plan Performance Report** with inline SVG charts — shareable with stakeholders, no services involved.
- **Location-allocation optimization** — site new schools/clinics/parks among your candidates with the classic models: greedy **maximal coverage** (Church & ReVelle) and **p-median** with Teitz–Bart vertex substitution, on real network distances, existing facilities respected; plus **Capacitated Allocation** that sends demand to the nearest facility *with free capacity*, spilling to the next when full; and land-use allocation — assign parcels to uses to maximise suitability under per-use area targets, with optional **compactness/adjacency** objectives and a **Pareto-front** sweep that maps the suitability-versus-compactness trade-off and its knee — no external solver.
- **Multi-objective land-use allocation** — assign a land use to every parcel to **maximize suitability** while meeting a target area for each use (the spatial-allocation problem of plan-making): feed one suitability field per use (e.g. from Suitability Lab) and per-use area targets. Add a **compactness** weight so each use forms contiguous zones, and **adjacency rules** (`residential|industry=-2`) to keep incompatible uses apart, and get a styled land-use map plus a target-vs-allocated summary — greedy + capacity-respecting swap heuristic, no solver.
- **Accessibility equity** — measure how *fairly* access is shared, not just how much there is: population-weighted **Gini**, a **Theil index** split into between- and within-group inequality (the environmental-justice number), **P90/P10**, coefficient of variation and an **access-poverty share**, on any value (access score, travel time, distance); plus **Inequality Curves** — an exportable **Lorenz / concentration curve** and the **Atkinson index** at your chosen inequality aversion; and **Demographic Equity Cross-Tabs** — who actually holds the low values: representation ratios per subgroup × value class and the Duncan dissimilarity index.
- **Scenario A/B comparison** — snapshot the score cards for two plan alternatives (dashboard buttons or the batchable Scenario Snapshot algorithm) and diff them metric by metric with direction-aware winners, in the dock or as a one-file HTML comparison report.
- **Zero dependencies** — stock QGIS only: no QNEAT3, no GRASS modules, no servers, no pip installs. SciPy (bundled with official builds) accelerates automatically.
- **Transit from GTFS** — load and validate any GTFS feed (stops with departures, route service stats), map **stop frequencies and headways** for a time window, and compute **door-to-door walk+transit travel times** (RAPTOR-style earliest arrival with transfers, access/egress on the street network, always compared against walking).
- **Walkability studio** — a **Walkability Audit** scoring every street segment 0-100 from intersection density, land-use mix entropy, destinations, block length and slope (editable weights/breakpoints), and **Pedestrian Route Quality** routing over quality-weighted streets: the detour ratio, the mean walk score along the route, the share on low-scoring segments.
- **Visibility** — DSM **viewsheds** (observer/target heights, radius), an **isovist field** (visible area, radials, circularity, occlusivity on a point grid — the VGA view) and **landmark visual exposure** (from where can it be seen — skyline and heritage screening).
- **Population & housing** — a **cohort-component projection** (Leslie matrix from a plain age-group rate table), a **housing needs assessment** (households, vacancy, losses, backlog) and **residential capacity** (FAR arithmetic per parcel, district roll-up) — projection feeds needs, capacity tests the zoning.
- **Environment screening** — a **road noise grid** (RLS-90-style emission, line-calibrated sampling, building screening, population exposure bands — screening, not compliance) and **green infrastructure**: park-hierarchy access on network distances and patch connectivity with per-patch dPC importance.
- **Urban growth** — **land-cover change** transition matrices, a deterministic **CA growth simulation** (year-of-conversion raster from a suitability surface, land demand and never-build constraints) and **sprawl metrics** around the SDG 11.3.1 LCRPGR ratio.
- **Batch Plan Auditor** — the whole battery in one run: access, walkability, balance, adequacy, green access and equity chained into a single scenario snapshot + report.
- **Verified math** — 350 engine unit checks against hand-computed values + 274 end-to-end assertions on real QGIS 3 LTR and QGIS 4. Methods and sources: [docs/METHODS.md](docs/METHODS.md).
- **PlanX Studio dock** — browse and launch the whole toolset from one panel, every tool with its own icon.

## 🚀 Installation

**From the QGIS Plugin Hub (recommended):** `Plugins → Manage and Install Plugins…` → search for **"PlanX"** → *Install*.

**From a release zip:** download the latest zip from [Releases](https://github.com/YusufEminoglu/PlanX/releases) → `Plugins → Install from ZIP`.

Requires QGIS 3.22 or newer. No external Python dependencies.

## 📖 Quick start

1. Load a street network (OSM export, plan centerlines…) in a **projected CRS** and run **Prepare Network** to node it.
2. Run **Space Syntax (Segment Angular Analysis)** with radii `800, n` and style the output by `NACH_800` — your first integration/choice map.
3. Add facility points and run **Service Areas (Isochrones)** with breaks `250, 500, 1000` for catchment bands.
4. Drop building footprints in and run **Building Form Metrics** or **Morphological Tessellation → Spacematrix Density** for a density portrait.
5. Pick amenity layers and run **Multi-Amenity Access Score** for a 15-minute-city map.
6. Open **PlanX → Plan Dashboard** for live score cards over your outputs, then **Save HTML Report…** (or run **Plan Performance Report (HTML)** in Processing) for a shareable one-file report.

## ⚙️ Reference

| Group | Tool | What it does |
|-------|------|--------------|
| Network Analysis | Prepare Network | Explode, node at intersections, dedupe, drop slivers |
| Network Analysis | OD Cost Matrix | Many-to-many network costs, detour ratio, desire lines |
| Network Analysis | Service Areas (Isochrones) | Multi-facility cost bands as edges + dissolved polygons |
| Network Analysis | Nearest Facility Allocation | Demand→facility assignment + facility load summary |
| Centrality & Space Syntax | Network Centrality | Degree, closeness, harmonic, straightness, eigenvector, Brandes betweenness (nodes + edges) |
| Centrality & Space Syntax | Space Syntax (Segment Angular) | Angular integration & choice, NACH/NAIN per metric radius |
| Urban Morphology | Building Form Metrics | Area, IPQ, convexity, elongation, orientation, courtyards, shared walls… |
| Urban Morphology | Morphological Tessellation | Voronoi plot proxies around buildings (Fleischmann method) |
| Urban Morphology | Spacematrix Density | GSI / FSI / OSR / L per block + Spacematrix class |
| Urban Morphology | Street Network Morphology | Orientation entropy & order, meshedness, junction typology |
| Accessibility | Multi-Amenity Access Score | 15-minute-city composite over any amenity layers |
| Microclimate | Shadow Casting (DSM) | Building/terrain shadows for any date & time, embedded sun position |
| Microclimate | Sun Hours (DSM) | Hours of direct sun per cell over one day — right-to-light & sun audits |
| Microclimate | Solar Irradiation (DSM) | Clear-sky daily kWh/m²: shadow-aware beam + SVF-weighted diffuse |
| Microclimate | Annual Solar Potential (DSM) | Year-long clear-sky kWh/m²/yr from twelve representative-day sweeps, optional monthly raster — rooftop-PV & solar-access screening |
| Microclimate | Sky View Factor (DSM) | Visible-sky fraction per cell — heat island & canyon studies |
| Microclimate | Frontal Area Index | λf / λp wind-roughness grid (Grimmond & Oke) |
| Microclimate | Heat Island Risk Grid | Fixed-scale 0–100 UHI screening from buildings, green & water polygons |
| Plan Standards & QA | Land-Use Balance | Per-capita areas vs configurable standards, surplus/deficit |
| Plan Standards & QA | Facility Adequacy | Capacity + network distance in one check, utilization & coverage |
| Plan Standards & QA | Density Grid | Area-share value disaggregation to a grid, density per hectare |
| Reporting & Dashboard | Plan Performance Report (HTML) | One-file scorecard report: charts, balance bars, score map — inline SVG |
| Reporting & Dashboard | Scenario Compare (A/B) | Metric-by-metric diff of two plan snapshots with direction-aware winners + HTML report |
| Reporting & Dashboard | Scenario Snapshot | Auto-detects PlanX output layers and captures the plan score metrics to a snapshot JSON |
| Walkability | Walkability Audit | Street-segment walk scores 0-100: intersections, mix, destinations, block length, slope |
| Walkability | Pedestrian Route Quality | Quality-weighted routes vs plain shortest: detour ratio, mean walk score, low-quality share |
| Transit | GTFS Import and Service Stats | Validated feed import: stops with departures/routes + route service summary |
| Transit | Transit Frequency Map | Departures per hour, mean headway and route counts per stop for a time window |
| Transit | Transit Travel-Time Access | Door-to-door walk+transit vs walk-only minutes per destination (RAPTOR, transfers) |
| Visibility | Viewshed (DSM) | Line-of-sight sweep from observers: visibility count raster, heights + radius |
| Visibility | Isovist Field | Benedikt isovist measures on a point grid: area, radials, circularity, occlusivity |
| Visibility | Visual Exposure of Landmarks | Inverse viewshed of a landmark outline: who can see it, cell by cell |
| Population & Housing | Population Projection (Cohort-Component) | Leslie-matrix projection from an age-group rate table, per-step totals |
| Population & Housing | Housing Needs Assessment | Households + vacancy + losses + backlog → dwellings to deliver |
| Population & Housing | Residential Capacity | Parcel FAR arithmetic → buildable floorspace and dwelling units, district roll-up |
| Microclimate | Road Noise Screening | RLS-90-style emission + spreading + building screening → dB(A) grid, exposure bands |
| Green Infrastructure | Green Space Access | Park hierarchy (size-within-distance ladder) on network distances, coverage per class |
| Green Infrastructure | Urban Green Connectivity | Patch components, Probability-of-Connectivity index, per-patch dPC importance |
| Urban Growth | Land-Cover Change Analysis | Transition matrix + per-class gains/losses/persistence in hectares |
| Urban Growth | Urban Growth Simulation (CA) | Deterministic constrained cellular automaton → year-of-conversion raster |
| Urban Growth | Urban Sprawl Metrics | SDG 11.3.1 LCRPGR + patches, largest-patch share, edge density |
| Reporting & Dashboard | Batch Plan Auditor | One run chains the standard battery into a scenario snapshot + HTML report |
| Optimization | Facility Location Optimizer | Maximal coverage / p-median siting on the network + candidate screening |
| Optimization | Capacitated Facility Siting | Choose where to build facilities under capacity constraints and travel limits |
| Optimization | Capacitated Allocation | Nearest facility with free capacity, spill when full, uncovered when none in reach |
| Optimization | Land-Use Allocation Optimizer | Assign parcels to uses maximising suitability + compactness + adjacency under per-use area targets |
| Optimization | Land-Use Pareto Front | Sweep compactness weights → the non-dominated suitability-vs-compactness trade-off, its knee, and the chosen plan |
| Equity | Accessibility Equity | Population-weighted Gini, Theil between/within decomposition, P90/P10, access-poverty share |
| Equity | Inequality Curves (Lorenz & Atkinson) | Exportable Lorenz/concentration curve + Gini + Atkinson index at chosen inequality aversion |
| Equity | Demographic Equity Cross-Tabs | Value classes × subgroup representation ratios, per-group stats + Duncan dissimilarity |

Methodology notes and the release roadmap live in [`docs/ROADMAP.md`](docs/ROADMAP.md).

## 🧩 Part of the PlanX ecosystem

PlanX is one of 15 open-source QGIS plugins for urban planning by the same author:

| Planning & analysis | CAD & production | 3D & visualization |
|---|---|---|
| [PlanX](https://github.com/YusufEminoglu/PlanX) — spatial-planning suite | [PlanX CAD Toolset](https://github.com/YusufEminoglu/PlanX-CAD) — drafting-grade CAD | [PlanX 3D City](https://github.com/YusufEminoglu/planx_3d_city) — Three.js city viewer |
| [GeoStats Lab](https://github.com/YusufEminoglu/planx_geostats) — spatial statistics | [EasyFillet](https://github.com/YusufEminoglu/EasyFillet) — tangent-arc fillet | [3D OSM Model](https://github.com/YusufEminoglu/osm_3d_model) — OSM → 3D city in browser |
| [Suitability Lab](https://github.com/YusufEminoglu/planx_suitability_lab) — raster MCDA | [Settlement Toolset](https://github.com/YusufEminoglu/PlanX-Settlement) — 9-stage settlement plans | [OSM Quick 3D](https://github.com/YusufEminoglu/osm_quick_3d) — OSM → native QGIS 3D |
| [DataCube Lab](https://github.com/YusufEminoglu/planx_datacube) — spatiotemporal cubes | [UIP Toolset](https://github.com/YusufEminoglu/PlanX-UIP) — Turkish master-plan automation | [Urban Procedural 3D](https://github.com/YusufEminoglu/planx_urban_procedural_3d) — parametric zoning lab |
| [Urban Resilience](https://github.com/YusufEminoglu/planx_urban_resilience) — 28 resilience tools | [ParcelFlux](https://github.com/YusufEminoglu/parcelflux) — parcel subdivision | [CartoLab](https://github.com/YusufEminoglu/planx_cartolab) — publication cartography |

## 📜 License & author

GPL-3.0 © [Yusuf Eminoğlu](https://github.com/YusufEminoglu) — bug reports and feature requests welcome in [Issues](https://github.com/YusufEminoglu/PlanX/issues).
