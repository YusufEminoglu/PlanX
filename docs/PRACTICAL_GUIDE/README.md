# PlanX Practical Guide — applied workflows & screenshots

**Live page:** <https://yusufeminoglu.github.io/PlanX/PRACTICAL_GUIDE/>
**Theory companion:** <https://yusufeminoglu.github.io/PlanX/PLANX_REFERENCE_MANUAL.html>

The [Academic Reference Manual](../PLANX_REFERENCE_MANUAL.html) explains the *theory* —
formulas, 350 numbered equations, 410 academic references. This guide shows the
*practice*: a 4-panel screenshot of every algorithm running on **real open data**,
the parameters that were used, and a step-by-step workflow for each tool.

---

## What is inside

`practical_guide.html` is a **single self-contained file** (no server, no network):
open it in any browser and everything works, offline.

| Tab | Content |
|-----|---------|
| 📸 Screenshot | The 4-panel capture of the real run: input data, parameters used, raw output, styled output |
| 📖 Theory | The full algorithm help text, extracted from the plugin source |
| 📋 Parameters & Outputs | Every input parameter, every output, plus the values used in the recorded run |
| 🔧 Step-by-step | How to run it, what to read in the result, and the interpretation notes |

**75 of the 76 algorithms** are covered. The 76th (`Generate Demo City`) is the
synthetic data generator itself, so it has no screenshot in a real-data guide.

---

## The dataset — Utrecht, Netherlands (1,000 ha)

Every screenshot in this guide was produced by running the PlanX engine in
QGIS 3.44 LTR (headless) on **real open data**. No synthetic geometry, no
fabricated attributes.

| Layer | Source | Features |
|-------|--------|----------|
| Street network | OpenStreetMap (BBBike Utrecht extract) | 9,429 |
| Building footprints + **build year** | **BAG** — Dutch national building register (PDOK WFS) | 32,812 |
| Building heights | **AHN** 0.5 m DSM − DTM, cross-checked with OSM `height`/`building:levels` | 0 – 112.3 m |
| Land use | OpenStreetMap | 36,455 |
| Points of interest | OpenStreetMap | 7,894 |
| Facilities (schools, clinics, stations…) | OpenStreetMap | 944 |
| Green space | OpenStreetMap (dissolved for the connectivity tool) | 2,801 → 12 patches |
| Water | OpenStreetMap | 155 |
| **Demand points** | **BAG address points + CBS PC6 population** (allocated per postcode) | 51,000 / 99,830 residents |
| **Neighbourhoods** | **CBS wijk- en buurtgebied 2025** (PDOK WFS) + socio-economic indicators | 50 / 155,045 residents |
| Neighbourhood suitability | CBS **Bestand Bodemgebruik** 2010/2017 class shares | 7 land-use fields |
| DEM (4 m) / DSM (4 m) | **AHN** national height model, gaps filled with SRTM | 1,577 × 1,586 |
| Public transport | **GTFS NL** — full national feed (ovapi.nl) | 12 files |

Study area: the historic centre of Utrecht, roughly 3.2 × 3.2 km around the Dom
Tower, projected in **EPSG:28992 (RD New)**.

### How the data was obtained

```text
OSM        BBBike extract          → clip to bbox → reproject to EPSG:28992
BAG        PDOK WFS (paged)        → GeoJSON → GPKG in EPSG:28992
CBS buurten PDOK WFS                → GeoJSON → GPKG + indicator fields
CBS PC6    PDOK WFS                → population per postcode → BAG addresses
CBS BBG    PDOK WFS 2010 / 2017    → class rasters + neighbourhood suitability
AHN        PDOK WCS (tiled)        → 0.5 m DSM + DTM → 2 m / 4 m rasters
GTFS       ovapi.nl                → national feed
```

---

## Reproducing the guide

The runner executes all 76 algorithms in headless QGIS and writes the
4-panel PNGs plus a per-algorithm manifest.

```cmd
:: from an OSGeo4W shell
cd C:\Users\YE\PyCharmMiscProject\qgis_plugins\planx\docs\PRACTICAL_GUIDE
C:\OSGeo4W\bin\python-qgis-ltr.bat -u scripts\practical_guide_runner_real.py --all
```

Useful flags:

| Flag | Effect |
|------|--------|
| `--all` | run every algorithm |
| `--algo <id>` | run a single algorithm (e.g. `serviceareas`, `spacesyntax`) |
| *(none)* | the runner **resumes**: algorithms whose screenshot already exists are re-executed (so their output still feeds the downstream tools) but not re-captured |

Data preparation scripts live in [`scripts/`](scripts/):

| Script | Purpose |
|--------|---------|
| `pipeline_download.py` | WFS downloads with pagination → GeoPackage |
| `rebuild_wfs.py` | rebuilds the PDOK layers in EPSG:28992 (GeoJSON → GPKG) |
| `download_ahn.py` | tiles the AHN height model under the WCS `MAXSIZE` limit |
| `build_rasters_final.py` | DEM/DSM: AHN + SRTM gap filling at 2 m |
| `build_layers.py`, `build_pois.py`, `build_facilities.py` | thematic OSM layers |
| `build_nb.py`, `build_zones.py`, `build_parcels.py` | CBS neighbourhoods, zones, suitability |
| `land_cover.py` | CBS Bestand Bodemgebruik → class rasters |
| `build_final.py` | assembles this HTML (embeds the screenshots as base64) |

The scripts expect the data under `C:\Users\YE\Downloads\planx_nl_data\`
(WSL path: `/mnt/c/Users/YE/Downloads/planx_nl_data/`).

---

## Files

| Path | Purpose |
|------|---------|
| `practical_guide.html` | the guide (single file, images embedded) |
| `index.html` | redirect to the guide |
| `manifest/algorithms_detailed.json` | all 76 algorithms with parameters and outputs |
| `manifest/screenshots_all.json` | run summary: timing and status per algorithm |
| `manifest/screenshots_<algo>.json` | per-algorithm capture metadata |
| `scripts/` | the runner and the data pipeline |

The individual PNG/JPEG captures are **not** committed — they are regenerated
by the runner and embedded into `practical_guide.html` by `scripts/build_final.py`.

---

## Licence

Same as PlanX: **GPL-3.0** © Yusuf Eminoğlu.
Data: OpenStreetMap (ODbL), PDOK/Kadaster (open data), CBS (open data),
AHN (open data), GTFS NL (open data).
