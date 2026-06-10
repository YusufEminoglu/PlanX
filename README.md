<div align="center">

<img src="planx.svg" width="96" alt="PlanX icon"/>

# PlanX

**Comprehensive spatial-planning suite for QGIS — data import, spatial statistics, zoning workflows and urban-design analysis in one toolbox.**

[![QGIS](https://img.shields.io/badge/QGIS-3.0%2B-93b023?logo=qgis&logoColor=white)](https://plugins.qgis.org/plugins/planx/)
[![Version](https://img.shields.io/github/v/tag/YusufEminoglu/PlanX?label=version&color=blue)](https://github.com/YusufEminoglu/PlanX/releases)
[![License](https://img.shields.io/badge/license-GPL--3.0-orange)](LICENSE)
[![QGIS Plugin Hub](https://img.shields.io/badge/QGIS%20Hub-install-589632?logo=qgis&logoColor=white)](https://plugins.qgis.org/plugins/planx/)

</div>

---

## Why PlanX?

PlanX is the core hub of a modular QGIS plugin ecosystem built for city planners and GIS professionals. It provides spatial statistics, zoning-rule workflows, urban-design analyses, and data utilities — all organized under a single PlanX menu with guided UI panels, robust error handling, and silent-mode batch capabilities for Turkish and international planning tasks.

## ✨ Features

- **Single PlanX menu** — every tool grouped in one place, with guided, icon-supported UI panels.
- **Spatial statistics** — zoning-rule analysis and urban-pattern diagnostics built for planning data.
- **Data import & export utilities** — move planning datasets in and out of QGIS without friction.
- **Silent-mode batch processing** — run repetitive workflows unattended.
- **Standards-aware** — compatible with Turkish and international planning conventions.

## 🚀 Installation

**From the QGIS Plugin Hub (recommended):** `Plugins → Manage and Install Plugins…` → search for **"PlanX"** → *Install*.

**From a release zip:** download the latest zip from [Releases](https://github.com/YusufEminoglu/PlanX/releases) → `Plugins → Install from ZIP`.

Requires QGIS 3.0 or newer. No external Python dependencies.

## 📖 Quick start

1. Install and activate **PlanX** — a *PlanX* menu appears in the QGIS menu bar.
2. Load your planning layers (zones, parcels, networks).
3. Pick a module from the PlanX menu and follow its guided panel.
4. For batch runs, enable silent mode in the module's dialog.

## ⚙️ Suite overview

PlanX is the umbrella plugin; these specialized siblings extend it:

| Plugin | Description |
|---|---|
| [PlanX CAD Toolset](https://github.com/YusufEminoglu/PlanX-CAD) | 25+ CAD drawing & editing tools with dockable panel |
| [PlanX UIP Toolset](https://github.com/YusufEminoglu/PlanX-UIP) | 8-stage automated Uygulama İmar Planı (Master Plan) workflow |
| [PlanX Settlement Toolset](https://github.com/YusufEminoglu/PlanX-Settlement) | 9-stage parametric settlement plan generation pipeline |
| [EasyFillet](https://github.com/YusufEminoglu/EasyFillet) | Standalone tangent-arc fillet tool |

Full version history: [CHANGELOG.md](CHANGELOG.md)

## 🧩 Part of the PlanX ecosystem

This plugin is one of 15 open-source QGIS plugins for urban planning by the same author:

| Planning & analysis | CAD & production | 3D & visualization |
|---|---|---|
| [PlanX](https://github.com/YusufEminoglu/PlanX) — spatial-planning suite | [PlanX CAD Toolset](https://github.com/YusufEminoglu/PlanX-CAD) — drafting-grade CAD | [PlanX 3D City](https://github.com/YusufEminoglu/planx_3d_city) — Three.js city viewer |
| [GeoStats Lab](https://github.com/YusufEminoglu/planx_geostats) — spatial statistics | [EasyFillet](https://github.com/YusufEminoglu/EasyFillet) — tangent-arc fillet | [3D OSM Model](https://github.com/YusufEminoglu/osm_3d_model) — OSM → 3D city in browser |
| [Suitability Lab](https://github.com/YusufEminoglu/planx_suitability_lab) — raster MCDA | [Settlement Toolset](https://github.com/YusufEminoglu/PlanX-Settlement) — 9-stage settlement plans | [OSM Quick 3D](https://github.com/YusufEminoglu/osm_quick_3d) — OSM → native QGIS 3D |
| [DataCube Lab](https://github.com/YusufEminoglu/planx_datacube) — spatiotemporal cubes | [UIP Toolset](https://github.com/YusufEminoglu/PlanX-UIP) — Turkish master-plan automation | [Urban Procedural 3D](https://github.com/YusufEminoglu/planx_urban_procedural_3d) — parametric zoning lab |
| [Urban Resilience](https://github.com/YusufEminoglu/planx_urban_resilience) — 28 resilience tools | [ParcelFlux](https://github.com/YusufEminoglu/parcelflux) — parcel subdivision | [CartoLab](https://github.com/YusufEminoglu/planx_cartolab) — publication cartography |

## 📜 License & author

GPL-3.0 © [Yusuf Eminoğlu](https://github.com/YusufEminoglu) — bug reports and feature requests welcome in [Issues](https://github.com/YusufEminoglu/PlanX/issues).
