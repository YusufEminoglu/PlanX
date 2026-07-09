# Changelog

All notable changes to PlanX are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [4.4.0] - 2026-07-10

Travel Demand: trip generation, gravity distribution, and mode split modeling (61 algorithms, 18 groups).

### Added
- **Trip Generation** (new Travel Demand group) - calculates zone production and attraction trip rates from population and jobs.
- **Gravity Distribution** (Travel Demand group) - computes doubly constrained zone-to-zone flow balancing (Furness/IPF) with exponential or power deterrence over street network costs.
- **Mode Split** (Travel Demand group) - splits OD flows into multiple mode shares and flows using a multinomial logit model.
- Pure-NumPy `engine/demand.py` with trip generation, Furness gravity balancing, and logit mode split calculations.

### Tested
- 384 engine unit checks and 310 real-QGIS e2e assertions on QGIS 3 LTR and QGIS 4.

## [4.3.0] - 2026-07-10

Hazard Screening: flow accumulation, HAND, and flood exposure mapping (58 algorithms, 17 groups).

### Added
- **Flow Accumulation** (new Hazard Screening group) - fills DEM depressions, computes D8 flow directions, and calculates topological flow accumulation.
- **HAND and Inundation** (Hazard Screening group) - calculates Height Above Nearest Drainage by tracing D8 paths, and generates a binary inundation mask.
- **Flood Exposure** (Hazard Screening group) - intersects the inundation mask with building footprint centroids and population points to calculate exposed counts and percentage shares, and annotates receiver features.
- Pure-NumPy `engine/hydro.py` with priority-flood filling, D8 steepest-descent direction, topological flow accumulation, HAND, inundation, and building/population exposure calculations.

### Tested
- 378 engine unit checks and 300 real-QGIS e2e assertions on QGIS 3 LTR and QGIS 4.

## [4.2.0] - 2026-07-10

Air Quality Screening: road emissions calculation and air dispersion modeling (55 algorithms, 16 groups).

### Added
- **Road Emissions** (Microclimate group) - calculates segment emissions (g/km/day) from a traffic volume field and a documented generic NOx-proxy emission factor.
- **Air Quality Screening** (Microclimate group) - generates a unitless pollution dispersion index grid and calculates receiver levels and exposure bands, accounting for wind speed, decay exponent alpha, and street canyon effects.
- Pure-NumPy `engine/air.py` with emissions, sample strength, concentration, canyon factor, and exposure bands.

### Tested
- 372 engine unit checks and 294 real-QGIS e2e assertions on QGIS 3 LTR and QGIS 4.

## [4.1.0] - 2026-07-10

Cycling and LTS: cycling stress classification and low-stress connectivity (53 algorithms, 16 groups).

### Added
- **Cycling Stress (LTS)** (new Cycling group) - classifies street segments into LTS 1-4 from speed, lanes, AADT and cycling infrastructure fields, with editable threshold rules and a length-share table.
- **Low-Stress Connectivity** (Cycling group) - filters the network by an LTS threshold, labels connected cycling islands, reports low-stress network length share and optional destination-reach population.
- Pure-NumPy `engine/cycling.py` with threshold parsing, vectorized LTS classification and LTS-filtered primal graph components.

### Tested
- 367 engine unit checks and 288 real-QGIS e2e assertions on QGIS 3 LTR and QGIS 4.

## [4.0.0] - 2026-07-09

Demo City & Speed: synthetic city generator and hot-loop vectorisation (51 algorithms).

### Added
- **Generate Demo City** (Reporting group) — deterministic synthetic town generator: streets, buildings, land use, POIs, facilities, demand, green, and a DSM raster, allowing all tools to be tried in one click.

### Optimized
- **Speed optimization in visibility.isovist_field** — precomputes direction offsets once per field execution, speeding up the loop.
- **Speed optimization in noise screening grid** — broadcasts distance calculations per row-chunk to avoid cell-by-cell loops.

### Testing
- Engine unit checks grown to **360** (including exact feature counts for demo city, DSM elevation validation, cross-process determinism, and isovist_field bit-identity regression checks); end-to-end assertions at **282** on QGIS 3.44 LTR and QGIS 4.0.2.

## [3.6.0] - 2026-07-09

The Batch Plan Auditor closes the loop (50 algorithms, 15 groups).

### Added
- **Batch Plan Auditor** (Reporting group) — the whole standard battery in one run: network + demand + amenities + land use + facilities + greens in, and it chains the 15-minute access score, walkability audit, land-use balance, facility adequacy, green-space access and access equity; every score lands in one scenario snapshot JSON (ready for Scenario Compare A/B) plus an optional one-file Plan Performance Report. Each part optional; fully headless and model-designer friendly.
- **Plan Dashboard**: Plan Performance Index **history sparkline** (grows with every saved snapshot) and an **Audit…** button opening the Batch Plan Auditor.
- Scenario metric registry gains the auditor keys (walkability mean, low-walk share, weakest green coverage, access Gini) — direction-aware in comparisons.
- `docs/METHODS.md` — the method, formula and primary source of every tool group.

### Testing
- Engine unit checks grown to **350**; end-to-end assertions to **274**; dashboard harness to **24 checks** — on QGIS 3.44 LTR and QGIS 4.0.2.

## [3.5.0] - 2026-07-09

Urban Growth: change accounting, growth simulation and the sprawl scorecard (49 algorithms).

### Added
- **NEW GROUP: Urban Growth.**
- **Land-Cover Change Analysis** — the transition matrix of two class rasters: from/to pairs with cells + hectares, per-class gains/losses/persistence/net, optional class labels; the largest conversion named in the log.
- **Urban Growth Simulation (CA)** — constrained cellular automaton (SLEUTH tradition): score = suitability × (base + weight × urban neighbourhood share); top scorers convert per step until the land demand is met; never-build constraints; deterministic for a given seed **across processes** (unit-tested). Output: year-of-conversion raster.
- **Urban Sprawl Metrics** — SDG 11.3.1 LCRPGR (land consumption vs population growth) + patch count, largest-patch share, edge density.
- Engine: pure-NumPy `engine/growth.py`; three new group-coloured tool icons.

### Testing
- Engine unit checks grown to **345** (hand-counted transition matrices, gradient-following CA, constraint masks, cross-process determinism, hand-computed LCRPGR and edge lengths); end-to-end assertions to **266** on QGIS 3.44 LTR and QGIS 4.0.2.

## [3.4.0] - 2026-07-09

Environment Screening: road noise and green infrastructure (46 algorithms).

### Added
- **Road Noise Screening** (Microclimate group) — screening-quality dB(A) grid: RLS-90-style emission from traffic volumes (hourly factor for AADT) and heavy shares; roads as line-calibrated point sources; energetic sum with 20 lg r spreading; fixed insertion loss behind buildings. Optional receivers report levels + a population exposure table (5 dB bands). Documented as screening, not compliance.
- **NEW GROUP: Green Infrastructure.**
- **Green Space Access** — the park-hierarchy standard (`min_ha=max_dist` ladder) on real network distances: per-demand pass/fail per class, classes met, per-class covered population, citywide m²/capita.
- **Urban Green Connectivity** — crossable-gap patch graph: components, binary Probability-of-Connectivity index, per-patch dPC importance (the stepping-stone argument, quantified).
- Engine: pure-NumPy `engine/noise.py` (the infinite-line calibration is a unit test) and `engine/green.py`; three new group-coloured tool icons.

### Testing
- Engine unit checks grown to **331**; end-to-end assertions to **256** on QGIS 3.44 LTR and QGIS 4.0.2.

## [3.3.0] - 2026-07-09

Population & Housing: the demographic backbone of plan-making (43 algorithms).

### Added
- **NEW GROUP: Population and Housing.**
- **Population Projection (Cohort-Component)** — a Leslie-matrix projection from a plain age-group table: per-step survival, fertility and optional net migration as fields, any number of steps. Outputs step × age-group rows and per-step totals. Single-sex screening form; rates constant over the horizon.
- **Housing Needs Assessment** — the standard needs identity, batchable: future households, vacancy allowance, replacement losses, backlog; every intermediate in a metric/value table. Negative need = surplus.
- **Residential Capacity** — per-parcel buildable floorspace from FAR − existing floorspace → whole dwelling units (unit size, net-to-gross efficiency), with a district roll-up. The reality check against the housing need; feeds the Land-Use Allocation Optimizer.
- Engine: pure-NumPy `engine/population.py` (`leslie_matrix`, `cohort_projection`, `housing_needs`, `residential_capacity`); `report.svg_pyramid` age-structure chart; three new group-coloured tool icons.

### Testing
- Engine unit checks grown to **316** (hand-computed two-step Leslie projection, migration floors, needs identity, capacity clamps); end-to-end assertions to **242** on QGIS 3.44 LTR and QGIS 4.0.2.

## [3.2.0] - 2026-07-09

Visibility: viewsheds, isovists and landmark exposure (40 algorithms).

### Added
- **NEW GROUP: Visibility.**
- **Viewshed (DSM)** — line-of-sight sweep from observer points: observer/target heights, view radius, direction count; visibility-count raster output. Radial sweep with a running horizon angle, rays capped at the raster diagonal.
- **Isovist Field** — Benedikt's 2-D visibility measures sampled on a point grid between buildings: visible area/perimeter, min/max/mean radial, circularity, occlusivity. The VGA companion to the space-syntax tools.
- **Visual Exposure of Landmarks** — the inverse viewshed: outline samples (optional extra height for spires), per-cell count of visible outline points; difference before/after DSMs for skyline & heritage impact.
- Engine: pure-NumPy `engine/visibility.py`; three new group-coloured tool icons.

### Testing
- Engine unit checks grown to **304** (wall shadows, tall-target pokes, radius caps, corridor vs plaza isovists); end-to-end assertions to **233** on QGIS 3.44 LTR and QGIS 4.0.2.

## [3.1.0] - 2026-07-09

Transit: GTFS feeds become first-class citizens (37 algorithms).

### Added
- **NEW GROUP: Transit.**
- **GTFS Import and Service Stats** — loads a GTFS zip into QGIS with validation on the way in (named errors for missing files / malformed times). Stops as WGS84 points with daily departures + route counts; a route summary table (mode, trips, service span, longest stop sequence). Service day defaults to the feed's first active day.
- **Transit Frequency Map** — departures per stop within a time window: departures/hour, mean headway minutes, distinct routes (the frequent-network map), plus per-route trips in the window.
- **Transit Travel-Time Access** — door-to-door with public transport: walk to a stop on the street network, ride a RAPTOR-style timetable with up to N transfers, walk to each destination. Reports walk-only vs transit minutes, winning mode and minutes saved per destination. Overtaking trips treated FIFO (screening simplification, documented).
- Engine: pure-stdlib+NumPy `engine/transit.py` — GTFS zip reader (utf-8-sig, past-midnight times as plain seconds, never datetimes), `calendar`/`calendar_dates` service resolution, `stop_frequencies`, RAPTOR `compile_day` (pattern grouping by route + stop sequence) and `earliest_arrival`; `paths.multi_source_offset` (egress Dijkstra whose sources start at their own arrival offsets); three new group-coloured tool icons.

### Testing
- Engine unit checks grown to **287** (synthetic in-code GTFS: transfer chains, no-transfer cutoffs, late boarding, cancelled service days); end-to-end assertions to **221** on QGIS 3.44 LTR and QGIS 4.0.2.

## [3.0.0] - 2026-07-09

Scenarios & Walkability: the plan-evaluation loop closes and a tenth tool
group opens (34 algorithms).

### Added
- **Scenario Snapshot** (Reporting group) — captures the plan score metrics of the current project into a snapshot JSON.
  - PlanX output layers auto-detected by field signatures (access score, balance table, facility adequacy, demand coverage, density grid) or pinned explicitly.
  - Model-designer friendly: run the tools for alternative A, snapshot, rerun for B, snapshot, feed both files to Scenario Compare (A/B).
- **NEW GROUP: Walkability.**
- **Walkability Audit** — scores every street segment 0–100 from the classic walkability-index ingredients (Frank et al. 2010): intersection density, land-use mix entropy, destination counts, block length, slope. Editable weights and breakpoints; sub-scores + raw ingredients on every segment; missing inputs renormalised away.
- **Pedestrian Route Quality** — routes over quality-weighted streets (weight = length × (1 + penalty × (100 − score)/100)); reports detour ratio vs the plain shortest path, length-weighted mean walk score and the share of the route on low-scoring segments. Nearest-destination or all-pairs.
- Engine: pure-NumPy `engine/walkability.py`; `paths.shortest_path_tree` / `reconstruct_path` (predecessor Dijkstra that names the parallel edge taken); shared collector `planx/collect.py` feeding both the dashboard dock and the snapshot algorithm; three new group-coloured tool icons.

### Testing
- Engine unit checks grown to **265**; end-to-end assertions to **205** on QGIS 3.44 LTR and QGIS 4.0.2.

## [2.13.0] - 2026-07-08

Equity Cross-Tabs & Scenario Compare: who holds the low values, and which
plan alternative wins (31 algorithms).

### Added
- **Demographic Equity Cross-Tabs** (Equity group) — cross-tabulates any per-unit value by population subgroup.
  - Population-weighted quantile classes (quintiles by default) or fixed breaks.
  - Representation ratio per group × class cell (1 = proportional; over-representation in the lowest class flags a disadvantaged group).
  - Per-group population/value shares, weighted mean/P10/median/P90, internal Gini, and the Duncan & Duncan dissimilarity index vs the rest.
  - Optional second group field crosses two demographics; the input comes back annotated with its value class and cell representation ratio for mapping.
- **Scenario Compare (A/B)** (Reporting group) — the A/B view of the Plan Dashboard.
  - The dashboard dock gains **Save A / Save B** scenario snapshots (score metrics to JSON next to the project) and an in-dock comparison panel with direction-aware winners and coloured deltas.
  - Headless too: `planx:scenariocompare` diffs two snapshot JSON files into a comparison table and an optional one-file HTML comparison report.
- Engine: pure-NumPy `equity.crosstab` / `equity.value_classes`; new pure-stdlib `engine/scenario.py` (snapshot / compare / verdict, direction registry); `report.compare_section` / `build_compare_html`; two new group-coloured tool icons.

### Testing
- Engine unit checks grown to **250**; end-to-end assertions to **188** on QGIS 3.44 LTR and QGIS 4.0.2.

## [2.12.0] - 2026-07-08

Siting & Contiguity: Capacitated Facility Siting and Contiguous Land-Use Allocation (29 algorithms).

### Added
- **Capacitated Facility Siting** (Optimization group) — chooses where to build p new facilities respecting per-site capacity constraints and travel limits.
  - First, a greedy construction phase selects sites that maximize newly served demand under a capacity-respecting allocation.
  - Then, a Teitz-Bart vertex substitution phase optimizes the locations by swapping sites to maximize total served demand (with total travel cost as a tiebreaker).
  - Existing facilities enter as fixed-open.
  - Outputs selected sites (with rank, load, utilization, marginal demand gain), allocation lines (demand to site connection with cost), and uncovered demand.
- **Contiguous Land-Use Allocation** (Optimization group) — optional Hard Contiguity mode on the Land-Use Allocation algorithm to assign parcels to uses forming a single connected component per use.
  - Seed-based concurrent region-growing followed by boundary-swap local search preserving subgraph connectivity of affected uses.
  - Default is Soft (existing behaviour unchanged).
- `engine/optimize.capacitated_siting` and `engine/allocate.allocate_contiguous` — pure NumPy.
- A new group-coloured tool icon for Capacitated Facility Siting.

### Testing
- Engine unit checks grown to **225**; end-to-end assertions to **174** on QGIS 3.44 LTR and QGIS 4.0.2.

## [2.11.0] - 2026-06-30

Inequality Curves: Lorenz / concentration curves and the Atkinson index
(28 algorithms).

### Added
- **Inequality Curves (Lorenz & Atkinson)** (Equity group) — the
  distributional view of any per-unit good (access score, green space per
  capita, income…), with an exportable curve to chart and a measure that lets
  you set how much you weight the worst-off.
  - Outputs the **Lorenz curve** as a table — cumulative population share vs
    cumulative value share, bowing below the 45° line of equality — and the
    **Gini** coefficient (twice the area between them).
  - Reports the **Atkinson index** at low/medium/high inequality aversion
    (ε = 0.5, 1, 2) and at your own ε: higher ε weights the lower tail more,
    so the index reads as the share of total value society would trade to
    equalise the distribution.
  - A **rank field** (deprivation, income…) switches it to a **concentration
    curve and index**, revealing whether the value concentrates on the
    advantaged or disadvantaged end (negative when it falls as rank rises).
- `engine/equity.atkinson_index`, `lorenz_points`, `gini_from_lorenz` and
  `concentration_index` — pure NumPy, population-weighted; a new
  group-coloured tool icon.

### Testing
- Engine unit checks grown to **216**; end-to-end assertions to **166** on
  QGIS 3.44 LTR and QGIS 4.0.2. The trapezoidal Gini is asserted equal to the
  mean-difference Gini, and Atkinson against hand-computed geometric/harmonic
  means.

## [2.10.0] - 2026-06-30

Land-Use Pareto Front: the suitability vs compactness trade-off (27 algorithms).

### Added
- **Land-Use Pareto Front** (Optimization group) — maps the **trade-off**
  between per-parcel suitability and compact zoning instead of committing to
  a single weighted run. There is rarely one best plan: clustering a use into
  compact zones usually costs some suitability, and vice versa.
  - Solves the Land-Use Allocation Optimizer across a **sweep of compactness
    weights** (auto-scaled to the data, or capped by an upper weight) and
    records two higher-is-better scores per result: area-weighted
    **suitability** and the shared boundary between adjacent same-use parcels
    (**compactness**).
  - Reports the **non-dominated set** (the Pareto front) and its **knee** —
    the point furthest from the chord joining the front's extremes, i.e. the
    best-balanced compromise.
  - Outputs a **front table** (one row per weight: both scores raw and 0–1
    normalised, plus on-front / knee / selected flags) to plot, and the
    **parcel map** of one chosen solution — the knee by default, or the
    maximum-suitability or maximum-compactness end.
- `engine/allocate.pareto_front`, `pareto_mask` and a knee detector — pure
  NumPy, reusing the existing multi-objective allocation core
  (`allocate_multi`); a new group-coloured tool icon.

### Testing
- Engine unit checks grown to **202**; end-to-end assertions to **158** on
  QGIS 3.44 LTR and QGIS 4.0.2. The high-weight runs are asserted to reach the
  blocked (compact) allocation and the front extremes to be non-dominated.

## [2.9.0] - 2026-06-29

Annual Solar Potential: year-long clear-sky irradiation (26 algorithms).

### Added
- **Annual Solar Potential (DSM)** (Microclimate group) — clear-sky global
  solar irradiation **summed over a whole year** (kWh/m²/yr): rooftop-PV
  screening, annual solar access and year-round heat exposure, with no
  external solver or atmospheric dataset.
  - Instead of sweeping all 365 days, one representative **average day per
    month** (Klein 1977; Duffie & Beckman, *Solar Engineering of Thermal
    Processes*) is computed with the same shadow-aware beam +
    sky-view-weighted diffuse model as the single-day Solar Irradiation
    tool, scaled by the number of days in that month and summed. Twelve
    day-sweeps stand in for the year — accurate for screening, far faster
    than a full daily run.
  - Outputs the **annual irradiation raster**; optionally a **12-band
    monthly raster** (one named band per month) for seasonal analysis. The
    log reports the unobstructed flat-ground annual reference, scene
    statistics and the **peak month**.
- `engine/solar.annual_irradiation` — pure-NumPy aggregation that reuses the
  daily irradiation kernel; `_raster.write_raster_multiband` for the monthly
  output; a new group-coloured tool icon.

### Testing
- Engine unit checks grown to **191**; end-to-end assertions to **150** on
  QGIS 3.44 LTR and QGIS 4.0.2. The monthly bands are asserted to sum back
  to the annual raster.

## [2.8.0] - 2026-06-29

Multi-objective land-use allocation: compactness & adjacency.

### Added
- The **Land-Use Allocation Optimizer is now multi-objective** — beyond
  per-parcel suitability it can shape the *spatial pattern* of the plan,
  maximizing `w_suit · Σ(area · suitability) + Σ_adjacent L · C[use, use]`
  over the parcel adjacency graph (`L` = shared boundary length):
  - **Compactness weight**: rewards same-use parcels that share a
    boundary, so each land use forms compact contiguous zones instead of
    scattering (reward per map unit of shared boundary; `0` = off).
  - **Adjacency rules**: free text `residential|industry=-2,
    residential|green=1` rewards (+) or penalises (-) specific use pairs
    being neighbours, per unit of shared boundary — keep incompatible uses
    apart and compatible ones together.
  - **Suitability weight** (advanced) balances suitability against the
    spatial terms.
  Parcel adjacency and shared-boundary lengths are computed with a spatial
  index; the run reports the spatial score and the share of shared
  boundary that is between same-use parcels (a compactness indicator).
  With compactness `0` and no rules the result is **identical** to the
  pure-suitability allocation of 2.7.0.
- `engine/allocate.allocate_multi` and a shared `_allocate_core`: the
  spatial term is a symmetric use-compatibility matrix over the adjacency
  graph; greedy construction + reassignment + capacity-respecting pairwise
  swaps now optimise the full objective (pure NumPy, unit-tested).

### Tests
- Engine suite 168 → 175 checks (compactness clustering and an adjacency
  penalty that relocates a repelled use, with hand-computed objectives);
  e2e harness 137 → 141 assertions (a 2×2 checkerboard that stays
  fragmented without compactness and forms blocks with it / a repel rule)
  — verified on QGIS 3.44 LTR and QGIS 4.0.2.

## [2.7.0] - 2026-06-29

Land-Use Allocation Optimizer — 25 algorithms total.

### Added
- **Land-Use Allocation Optimizer** (Optimization group): assigns a land
  use to each parcel to **maximize total suitability** while meeting a
  **target area** for each use — the spatial-allocation problem at the
  heart of plan-making, solved natively with no external solver. You
  supply, on the parcel layer, one **suitability field per land use**
  (0–1 or 0–100 — e.g. straight from Suitability Lab) and a target area
  per use; each parcel is assigned in full to at most one use so the area
  given to a use stays within its target and the **area-weighted
  suitability** is as high as possible. Parcels not needed to meet the
  targets are left **unassigned**; a use that cannot be filled reports a
  **shortfall**. An optional **lock field** fixes already-zoned parcels to
  a use (consuming that use's target). Method: greedy construction (best
  suitability first) plus a local search of single-parcel reassignments
  and **capacity-respecting pairwise swaps** — a fast heuristic, not a
  guaranteed global optimum. Outputs the parcels with their assigned use,
  its suitability, the parcel area and a locked flag (style by
  `alloc_use` for a land-use map), and a per-use summary table (target vs
  allocated area, shortfall, parcel count and mean suitability achieved).
- `engine/allocate.py` (`parse_targets`, `allocate_land_use`) — pure
  NumPy, unit-tested; new group-coloured tool icon.

### Tests
- Engine suite 156 → 168 checks (incl. a greedy-trap case the swap phase
  must escape to reach the optimum); e2e harness 126 → 137 assertions with
  a hand-computed allocation and a locked-parcel scenario — verified on
  QGIS 3.44 LTR and QGIS 4.0.2.

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
