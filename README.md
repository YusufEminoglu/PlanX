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

Urban analysts usually need four or five separate tools — depthmapX for space syntax, a routing plugin for isochrones, momepy for morphology, UMEP for shadows, a server for OD matrices. PlanX embeds real implementations of all of them directly inside QGIS: a NumPy/SciPy analytics engine (with an identical pure-Python fallback) drives twenty-five Processing algorithms that run locally, batch cleanly, and chain in the model designer. It is the flagship of the 15-plugin PlanX ecosystem.

## ✨ Features

- **Space syntax, embedded** — segment angular analysis (Hillier & Iida): integration, choice, **NACH/NAIN** at any metric radius. No depthmapX, no axial map.
- **The full centrality family** — degree, closeness (Wasserman–Faust + harmonic), straightness, **eigenvector** and exact **Brandes betweenness** on junctions *and* street segments, radius-limited or sampled for big networks.
- **Real network accessibility** — OD cost matrices with detour ratios, multi-facility **service-area isochrones**, nearest-facility allocation with load summaries.
- **15-minute city scores** — walking time to the nearest amenity of every category plus a 0–100 composite, straight from your own layers.
- **Urban morphology** — momepy-style building form metrics, **morphological tessellation**, Spacematrix **GSI/FSI/OSR/L** with readable class labels, street orientation entropy & meshedness (Boeing).
- **Microclimate screening** — UMEP-style **shadow casting** for any date/time (embedded NOAA solar position), **Sun Hours** (whole-day direct-sun maps), clear-sky **Solar Irradiation** (shadow-aware beam + SVF-weighted diffuse, kWh/m²), **Sky View Factor**, frontal-area wind-roughness grids, and a vector **Heat Island Risk Grid** from the layers every plan already has.
- **Plan standards QA** — land-use balance against **configurable per-capita standards** (surplus/deficit per category), facility adequacy checking **capacity and distance together**, and dasymetric density grids.
- **Plan dashboard & report** — live score cards over your analysis layers (**Plan Dashboard** dock) and a one-click, single-file **HTML Plan Performance Report** with inline SVG charts — shareable with stakeholders, no services involved.
- **Location-allocation optimization** — site new schools/clinics/parks among your candidates with the classic models: greedy **maximal coverage** (Church & ReVelle) and **p-median** with Teitz–Bart vertex substitution, on real network distances, existing facilities respected; plus **Capacitated Allocation** that sends demand to the nearest facility *with free capacity*, spilling to the next when full — no external solver.
- **Multi-objective land-use allocation** — assign a land use to every parcel to **maximize suitability** while meeting a target area for each use (the spatial-allocation problem of plan-making): feed one suitability field per use (e.g. from Suitability Lab) and per-use area targets. Add a **compactness** weight so each use forms contiguous zones, and **adjacency rules** (`residential|industry=-2`) to keep incompatible uses apart, and get a styled land-use map plus a target-vs-allocated summary — greedy + capacity-respecting swap heuristic, no solver.
- **Accessibility equity** — measure how *fairly* access is shared, not just how much there is: population-weighted **Gini**, a **Theil index** split into between- and within-group inequality (the environmental-justice number), **P90/P10**, coefficient of variation and an **access-poverty share**, on any value (access score, travel time, distance).
- **Zero dependencies** — stock QGIS only: no QNEAT3, no GRASS modules, no servers, no pip installs. SciPy (bundled with official builds) accelerates automatically.
- **Verified math** — 175 engine unit checks against hand-computed values + 141 end-to-end assertions on real QGIS 3 LTR and QGIS 4.
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
| Microclimate | Sky View Factor (DSM) | Visible-sky fraction per cell — heat island & canyon studies |
| Microclimate | Frontal Area Index | λf / λp wind-roughness grid (Grimmond & Oke) |
| Microclimate | Heat Island Risk Grid | Fixed-scale 0–100 UHI screening from buildings, green & water polygons |
| Plan Standards & QA | Land-Use Balance | Per-capita areas vs configurable standards, surplus/deficit |
| Plan Standards & QA | Facility Adequacy | Capacity + network distance in one check, utilization & coverage |
| Plan Standards & QA | Density Grid | Area-share value disaggregation to a grid, density per hectare |
| Reporting & Dashboard | Plan Performance Report (HTML) | One-file scorecard report: charts, balance bars, score map — inline SVG |
| Optimization | Facility Location Optimizer | Maximal coverage / p-median siting on the network + candidate screening |
| Optimization | Capacitated Allocation | Nearest facility with free capacity, spill when full, uncovered when none in reach |
| Optimization | Land-Use Allocation Optimizer | Assign parcels to uses maximising suitability + compactness + adjacency under per-use area targets |
| Equity | Accessibility Equity | Population-weighted Gini, Theil between/within decomposition, P90/P10, access-poverty share |

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
