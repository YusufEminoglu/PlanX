# PlanX v4 Enhancement Plan — "From Analysis to Decision"

> Implementation plan for taking PlanX from v3.6.0 (50 algorithms, 15 groups)
> to a v4-series suite of ~64 algorithms across ~18 groups. Written to be
> executed phase-by-phase by an AI coding agent, one phase = one releasable
> version. **Do not start a phase before the previous one's quality gates
> pass. STATUS: DORMANT — no phase scheduled yet.**

---

## 0. Ground rules (READ FIRST — hard constraints, non-negotiable)

### Architecture invariants
- **`engine/` is pure Python + NumPy. NO `qgis` imports there, ever.** SciPy
  only behind try/except with an identical pure-Python fallback (pattern in
  `engine/paths.py`). No new pip dependencies — stock QGIS 3.22 → 4.x on
  Windows/macOS/Linux.
- **`algorithms/` are thin `QgsProcessingAlgorithm` wrappers.** Copy the
  style of an existing algorithm of the same shape: vector-table tools →
  `alg_equity_crosstab.py`; network tools → `alg_green_access.py`; raster
  sweeps → `alg_viewshed.py` (uses `algorithms/_raster.py`); chained/child
  algorithms → `alg_plan_audit.py` (`processing.run(...,
  is_child_algorithm=True)` + `QgsProcessingMultiStepFeedback` +
  `QgsProcessingUtils.mapLayerFromString`).
- **Determinism**: any stochastic step uses `numpy.random.default_rng(seed)`
  with a user-visible seed parameter. **Never seed from `hash()`** (Python
  randomises str hashes per process). Cross-process identity must be a unit
  test (pattern: test block 31 in `tests/test_engine.py` runs a fresh
  interpreter via `subprocess` + `sys.executable`).
- **English-only UI.** Standards/thresholds are parameters with documented
  defaults, never locale assumptions. **Never write "elite", "best",
  "ultimate"** or similar self-praise anywhere user-facing.
- Screening tools must say so loudly in the help text (the noise tool is the
  template: "screening quality, not compliance modelling").
- Heavy loops honour `feedback.isCanceled()` and `feedback.setProgress`;
  grids have a hard cell cap with a clear error (noise: 300k, isovist: 400k).

### Registration checklist (EVERY new algorithm — v3 audits caught misses)
1. `provider.py` — import + `addAlgorithm` under its group comment.
2. `metadata.txt` — description, about, changelog entry (newest on top,
   indented block, **no bare `%` anywhere**), version pre-bump.
3. `README.md` — feature bullet (if a new family) + tool table row.
4. `docs/ROADMAP.md` — inventory row + release note.
5. Icon: add a glyph to `scratch/make_planx_tool_icons.ps1` (group colour,
   **inline point arrays only** — helper functions returning arrays inside
   the scriptblock crash GDI+ with "Parameter is not valid"), regenerate
   (existing PNGs stay byte-identical), eyeball the new PNGs.
6. **The three pin scripts** (Gemini forgot these in Phase A of v3):
   - `scratch/planx_e2e_qgis.py`: "N algorithms registered" + icon count.
   - `scratch/planx_import_check.py`: algorithm count + sorted group list.
   - `scratch/planx_zip_audit.py`: `version=` pin + new-file asserts.
7. `studio_dock.py` needs **no edit** — it reads `provider.algorithms()`
   dynamically.

### Quality gates (every phase, before release)
- `tests/test_engine.py`: hand-computed cases for every new engine function
  (each phase section below names the required scenarios). Runs on plain
  Python. New module → add to the `from planx.engine import (...)` list.
- `scratch/planx_e2e_qgis.py`: real-QGIS assertions for every new algorithm,
  run on **BOTH** interpreters and both must pass:
  - `C:\OSGeo4W\bin\python-qgis-ltr.bat scratch\planx_e2e_qgis.py` (3.44 LTR)
  - `C:\OSGeo4W\bin\python-qgis.bat scratch\planx_e2e_qgis.py` (QGIS 4)
  Script files only — multiline `python -c` silently fails on Windows.
  **If you cannot execute these, say so explicitly — never claim tests
  passed without running them.**
- e2e traps already learned: the harness `run()` helper does NOT put sink
  outputs into `QgsProject` — auto-detect tools need earlier outputs
  `addMapLayer`-ed first (see block [35]); the tail uses `os._exit`
  (exitQgis segfaults after raster-heavy runs) — do not revert; write files
  with `newline="\n"`.
- `flake8 --max-line-length=127` clean (tests may `# noqa: E402` late
  imports); `bandit -r planx` 0 High / 0 Medium (`# nosec` only with a
  written justification); `python -m py_compile` on every touched file.
- Update the test counts quoted in README / CHANGELOG / ROADMAP to the
  numbers actually observed after the runs.

### Release ritual (owner does this, not the agent)
The agent **stops after all gates pass** and reports: files changed, unit +
e2e counts (both QGIS versions, with the actual output lines), lint/bandit
results, and any open questions. **NO git commit/tag/push, NO zip build** —
review and release are manual (pre-bumped metadata/CHANGELOG are fine; the
owner runs validate + Build-PluginZip + zip audit + git).

---

## 1. Where PlanX stands (context)

- 50 algorithms / 15 groups: Network Analysis; Centrality & Space Syntax;
  Urban Morphology; Accessibility; Transit; Walkability; Visibility;
  Microclimate (incl. Road Noise Screening); Plan Standards & QA; Population
  and Housing; Green Infrastructure; Urban Growth; Equity; Optimization;
  Reporting & Dashboard (incl. Scenario Snapshot/Compare + Batch Plan
  Auditor).
- Engine modules: `graphs`, `paths` (incl. `shortest_path_tree`,
  `multi_source_offset`), `centrality`, `syntax`, `morphology`, `solar`,
  `standards`, `report` (stdlib HTML + compare + pyramid), `optimize`,
  `allocate`, `equity` (incl. crosstab), `scenario` (direction registry),
  `walkability`, `transit` (GTFS + RAPTOR), `visibility`, `population`,
  `noise`, `green`, `growth`. Shared layer collector: `planx/collect.py`.
- 350 unit / 274 e2e / 24 dashboard checks green on QGIS 3.44.10 and 4.0.2.
- Methods reference: `docs/METHODS.md` (extend it every phase).

The v4 direction: consolidate (a demo city + speed), then the analysis
families still missing — cycling stress, air screening, flood exposure,
travel demand — and finally weld growth, demand and scenarios into one
decision pipeline with a multi-scenario board.

---

## 2. Phase plan overview

| Phase | Version | Theme | New algorithms | Engine work |
|---|---|---|---|---|
| A | v4.0 | Consolidation: Demo City & speed | Generate Demo City | new `demo.py`; vectorise `visibility.isovist_field` + noise grid (bit-identical) |
| B | v4.1 | Cycling (new group) | Cycling Stress (LTS); Low-Stress Connectivity | new `cycling.py` |
| C | v4.2 | Air quality screening (Microclimate) | Road Emissions; Air Pollution Screening | new `air.py` |
| D | v4.3 | Hazard Screening (new group) | Flow Accumulation; HAND & Inundation; Flood Exposure | new `hydro.py` |
| E | v4.4 | Travel Demand (new group) | Trip Generation; Gravity Distribution; Mode Split | new `demand.py` |
| F | v4.5 | LUTI-lite pipeline | Population Allocation; Scenario Pipeline | extend `population.py`; orchestration |
| G | v4.6 | Multi-scenario board | Scenario Ranking | extend `scenario.py`, `report.py`; dock button |

---

## 3. Phase A — v4.0 "Demo City & Speed"

### A1. Generate Demo City (`planx:democity`, Reporting group)
Deterministic synthetic town so every tool is try-able in one click and the
e2e fixtures get richer. Parameters: seed, blocks-x, blocks-y, block size,
CRS (default a projected metric CRS). Outputs (all sinks + one raster):
street network (grid + one diagonal avenue), buildings (rect footprints,
heights 3–40 m, `height` field), land-use polygons (cycling categories
residential/commercial/green/school with a `use` field), POIs, facilities
with `name`/`cap`, demand points with `pop`, green polygons, and a DSM
GeoTIFF (flat ground + building heights).
- **Engine** `demo.py`: pure functions producing coordinate/attribute
  arrays from `default_rng(seed)`; the wrapper only builds features/raster.
- **Tests**: exact feature counts for a given size; DSM max equals tallest
  building; cross-process determinism (subprocess pattern); e2e: generate,
  then run accessscore + walkability on it and assert non-trivial outputs.

### A2. Hot-loop vectorisation (no behaviour change)
- `visibility.isovist_field`: precompute per-direction ray index offsets
  once per (pixel, max_dist, n_rays) and reuse across points.
- `alg_noise_screen` grid: broadcast distances per row-chunk instead of the
  per-cell Python loop (LOS checks stay per-pair but only within cutoff).
- **Requirement**: outputs bit-identical to the current code on the existing
  unit fixtures — add regression tests comparing against a small naive
  reference implementation embedded in the test. Public signatures frozen.

### A3. Consistency sweep
Every one of the ~51 help strings names its outputs and units; `METHODS.md`
gains the demo-city line; README quickstart points at Demo City first.

---

## 4. Phase B — v4.1 "Cycling" (new group `GROUP_CYCLE = ("Cycling", "cycling")`)

### B1. Engine `cycling.py`
`lts_classify(speed, lanes, aadt, infra)` → Level of Traffic Stress 1–4
after Mekuria/Furth, deliberately simplified and fully documented:
- `infra == "path"` (separated) → LTS 1;
- `infra == "lane"`: LTS 2 if speed ≤ 50 and lanes ≤ 3, else LTS 3;
- mixed traffic: LTS 1 if speed ≤ 30 and lanes ≤ 2 and aadt < 1000;
  LTS 2 if speed ≤ 30 and lanes ≤ 2; LTS 3 if speed ≤ 50; else LTS 4.
Thresholds arrive as a parsed free-text table (pattern:
`green.parse_hierarchy`) so agencies can re-tune them.

### B2. `planx:cyclingstress` — classify segments (speed/lanes/AADT/infra
fields, all optional with defaults), output styled by LTS + a share table.

### B3. `planx:lowstressislands` — subnetwork with LTS ≤ threshold →
connected components (reuse `green.components` idiom on the primal graph):
island id/size per segment, % of network length low-stress, and — given
origins + population — the population whose island contains a chosen
destination layer's island (the "can you get there at low stress" number).
- **Tests**: one hand case per LTS rule row; a toy network where a single
  high-stress bridge splits the low-stress network into two islands and
  raising the threshold merges them.

---

## 5. Phase C — v4.2 "Air Quality Screening" (Microclimate group)

### C1. Engine `air.py` — SCREENING ONLY, said loudly (noise.py is the
tone template):
- `road_emission(aadt, ef_gkm)` → g/km/day per segment (EF is a parameter,
  default a documented generic NOx-proxy value);
- `sample_strength(emission, seg_len)` — line-calibrated point samples
  (same 25 m reference trick as noise, calibration is a unit test);
- `concentration(src_xy, strength, rx, ry, wind_speed, alpha)` — index ∝
  Σ strength / (u · (d + d0)^α), α default 1.0, d0 half a cell;
- `canyon_factor(height_mean, width)` = 1 + min(2, H/W) applied to
  receivers inside a street-canyon buffer (buildings on both sides).
Output is a unitless **pollution index** (honest naming), plus
population-exposure bands reusing the `noise.exposure_bands` pattern.

### C2. `planx:roademissions` — per-segment emissions table/styled lines.
### C3. `planx:airscreen` — index grid + optional receivers with exposure
bands (mirror `alg_noise_screen`'s structure and caps).
- **Tests**: doubling distance halves the single-source index at α=1;
  canyon factor 2 when H=W; infinite-line calibration ±tolerance; band
  splitting; e2e mirrors the noise blocks with hand-computed ratios.

---

## 6. Phase D — v4.3 "Hazard Screening" (new group `GROUP_HAZARD`)

### D1. Engine `hydro.py` (all classic, hand-testable on 5×5 DEMs):
- `fill_depressions(dem)` — priority-flood with `heapq` (deterministic);
- `d8_flow(dem)` — steepest-descent direction per cell (ties: first of the
  fixed neighbour order — document it);
- `flow_accumulation(dirs)` — cells drained through each cell;
- `hand(dem, dirs, drainage_mask)` — height above the drainage cell reached
  by following D8; drainage = accumulation ≥ threshold;
- `inundation(hand, depth)` — mask of cells with HAND ≤ depth.

### D2. `planx:flowaccumulation` — filled DEM + D8 + accumulation rasters.
### D3. `planx:handindex` — HAND raster + inundation mask for a depth.
### D4. `planx:floodexposure` — inundation mask × buildings/population →
exposed counts/shares table (+ demand points annotated wet/dry).
- **Tests**: a pit DEM fills exactly to its pour point; a 1-D slope gives
  accumulation 1..n and HAND equal to elevation above the channel; a
  hand-built valley floods the right three cells at depth 1; exposure
  cross-tab equals hand counts.

---

## 7. Phase E — v4.4 "Travel Demand" (new group `GROUP_DEMAND`)

Four-step-lite, every kernel hand-computable:

### E1. Engine `demand.py`:
- `trip_generation(pop, jobs, p_rate, a_rate)` → productions/attractions;
- `gravity(P, A, cost, beta, kind="exp", max_iter, tol)` — doubly
  constrained Furness/IPF balancing with deterrence `exp(-βc)` or `c^-β`;
  returns flows + convergence info; row/column totals must match P/A;
- `mode_split(times, betas, asc)` — multinomial logit shares per OD pair.

### E2. `planx:tripgeneration` — zones + rate params → P/A table.
### E3. `planx:gravitymodel` — zones + network (costs via `many_to_many`)
→ OD flow table + desire lines styled by flow, top-N flows in the log.
### E4. `planx:modesplit` — OD flows + per-mode time fields → per-mode
flows and shares.
- **Tests**: 2×2 Furness balances to the known closed-form solution;
  logit shares for two modes with a 10-minute gap match the hand value;
  totals conserved to 1e-9; beta=0 gives cost-independent proportionality.

---

## 8. Phase F — v4.5 "LUTI-lite Scenario Pipeline"

### F1. `population.allocate_growth(total, weights)` — largest-remainder
apportionment (floor + biggest fractional parts, index tie-break):
deterministic, sums exactly to `total`. Wrapper `planx:popallocate`
distributes a population increment over parcels ∝ remaining capacity
(from Residential Capacity) or any weight field.

### F2. `planx:scenariopipeline` (Reporting) — the LUTI-lite loop as one
chained algorithm (child-algorithm pattern from `alg_plan_audit`):
growth CA (seed+suitability+demand) → new urban cells become demand points
carrying allocated population growth (`allocate_growth`) → re-run access
score and walkability on the grown city → Scenario Snapshot JSON named by
the scenario. Two runs with different growth assumptions → Scenario
Compare shows what the growth pattern does to access/walkability.
- **Tests**: apportionment exactness + determinism; e2e on the Demo City:
  pipeline produces a snapshot whose demand count grew by the expected
  number of cells and whose metrics parse.

---

## 9. Phase G — v4.6 "Multi-Scenario Board"

### G1. Engine `scenario.rank(snapshots, weights=None)`:
min–max normalise each metric across the N snapshots (direction-aware:
lower-better inverted; neutral metrics excluded unless explicitly
weighted); composite = weighted mean of available normalised metrics with
missing-metric renormalisation; returns per-scenario composite, rank and
per-metric contributions. `report.build_board_html(...)` renders the board
(bars per metric, one column per scenario — stdlib/inline-SVG like the
rest of report.py).

### G2. `planx:scenariorank` — N snapshot JSON files + optional
`key=weight` text → ranking table + optional HTML board.
Dashboard: a small "Rank scenarios..." button next to Compare A/B opening
a multi-file dialog and rendering the composite order into the dock label
(reuse the compare-panel idiom).
- **Tests**: two snapshots, two metrics, hand-computed composite; a
  lower-better metric flips correctly; a metric missing on one side
  renormalises; equal snapshots tie.

---

## 10. Definition of done (whole plan)

- ~64 algorithms across ~18 groups (adds Cycling, Hazard Screening,
  Travel Demand), every one icon-ed and in all seven registration points.
- Unit checks ≥ 450; e2e ≥ 340; dashboard harness extended for the new
  dock button — all green on QGIS 3.44 LTR **and** QGIS 4.
- `docs/METHODS.md` covers the new groups; README/ROADMAP tables complete.
- flake8/bandit/zip-audit clean at every tag; one phase = one version = one
  tag, never renumbered.
