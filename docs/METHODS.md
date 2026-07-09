# PlanX Methods Reference

One page per tool group: the method, its formula and its primary source.
Everything below is implemented inside the plugin (NumPy, optional SciPy
fast path with an identical fallback) — no external solvers or services.

## Network Analysis

Streets become an undirected primal graph: junction nodes, polyline edges
weighted by length (or a cost field). Shortest paths run Dijkstra —
`scipy.sparse.csgraph` when present, a pure-`heapq` kernel otherwise, with
identical results (unit-asserted). OD matrices report cost and the detour
ratio `network / euclidean`; service areas are min-cost bands from
multiple sources; nearest-facility allocation tracks the winning source
per node.

## Centrality & Space Syntax

Closeness (Wasserman–Faust normalisation), straightness (euclidean /
network per pair), betweenness via Brandes (2001) with radius limiting
and optional source sampling, eigenvector centrality by power iteration
on `A + I` (plain `A` oscillates on bipartite graphs). Space syntax uses
the segment dual graph with angular costs (turn degrees / 90; Hillier &
Iida 2005; Turner 2001): integration = angular closeness, choice =
angular betweenness, plus NACH `log(CH+1)/log(TD+3)` and NAIN
`(NC+2)^1.2 / (TD+2)` per radius.

## Urban Morphology

Shape metrics from pure geometry: isoperimetric quotient `4πA/P²`,
convexity (area / hull area), rectangularity (area / oriented bounding
box via rotating calipers), elongation, orientation, courtyards, fractal
dimension `2 ln(P/4) / ln A`, shared walls. Morphological tessellation
follows Fleischmann's momepy recipe: densified boundaries → Voronoi →
dissolve per building. Spacematrix classifies GSI/FSI/OSR/L (Berghauser
Pont & Haupt). Street orientation entropy and order follow Boeing (2019).

## Accessibility

Multi-amenity 15-minute scores: per category the nearest network time
from every origin; the score is the share of categories within the
threshold (0–100), population-weighted summaries optional.

## Transit (GTFS)

Feeds are read from the zip with the stdlib (`utf-8-sig`, times as plain
seconds so 25:10:00 works). Service days resolve `calendar` +
`calendar_dates`. Frequencies count departures in a window (final
arrivals excluded); headway = window / departures. Door-to-door times
run RAPTOR (Delling et al. 2012) rounds over patterns grouped by route
and stop sequence — board the earliest catchable trip, up to N
re-boardings; walking legs use the street network before and after
(offset multi-source Dijkstra for the egress). Overtaking trips are
treated FIFO — the screening simplification.

## Walkability

Frank et al. (2010) ingredients per street segment: junction density
(3+ legs, per km²), land-use mix (normalised Shannon entropy of buffer
areas), destination counts, mean street length (block proxy), slope from
a DEM. Each is normalised 0–100 with documented breakpoints and combined
with editable weights (missing components renormalise away). Route
quality reroutes over `length × (1 + penalty × (100 − score)/100)` and
reports the detour ratio, the length-weighted mean score and the
low-score share of the route.

## Visibility

Viewsheds sweep azimuth rays over the DSM with a running horizon angle
(rays capped at the raster diagonal); a cell is visible when the line to
its surface + target height clears the horizon before it. Isovists
(Benedikt 1979) march rays over the rasterised building mask: area
(shoelace over ray endpoints), perimeter, radials, circularity
`4πA/P²`, occlusivity (rays stopped by obstacles). Landmark exposure
sums inverse viewsheds from outline samples.

## Microclimate

NOAA solar position (±0.5°), UMEP-style shadow sweeps by array
shifting, sky view factor `1 − mean sin²(horizon)` over azimuth scans,
frontal area index λf/λp, clear-sky irradiation = ASHRAE beam
(shadow-aware) + SVF-weighted isotropic diffuse (Masters 2004), annual
potential from twelve representative average days (Klein 1977; Duffie &
Beckman). Heat risk composes built/green/water fractions and heights on
a fixed 0–100 scale. Road noise screening: RLS-90-style emission
`37.3 + 10 lg(M(1+0.082p))`, roads as point samples calibrated so an
infinite line reproduces the 25 m reference (`L_s = L_m25 +
10 lg(25ℓ/π)`), energetic summing with `20 lg r` spreading and a fixed
insertion loss behind buildings — screening, not compliance.

## Plan Standards & QA

Land-use balance against free-text per-capita standards (`green=10`),
facility adequacy = capacity vs assigned demand within a network
catchment, dasymetric density grids by area share.

## Population & Housing

Cohort-component projection as a Leslie (1945) matrix: first row
fertility, subdiagonal survival, the last diagonal keeps the open-ended
group; net migration adds after each step. Housing needs: `households ×
(1 + vacancy) − stock + losses + backlog`. Residential capacity:
`max(0, area × FAR − existing) × efficiency / unit size`, floored.

## Green Infrastructure

Park hierarchies as a `min_ha = max_dist` ladder tested on network
distances (green snap offsets ride as initial Dijkstra costs).
Connectivity: patches linked within a crossable gap; the binary
Probability of Connectivity `PC = Σ_c (Σa_c)² / A²` (Saura &
Pascual-Hortal 2007) and per-patch `dPC` — the share of PC lost when
the patch is removed.

## Equity

Population-weighted Gini (O(n log n) sorted mean-difference form),
Theil T with the additive between/within decomposition (Shorrocks 1980),
P90/P10, access-poverty shares, Lorenz and concentration curves with
the trapezoidal Gini, the Atkinson index (`1 − EDE/mean`, power mean of
order `1−ε`), and demographic cross-tabs: weighted quantile classes,
representation ratios per group × class, Duncan & Duncan dissimilarity.

## Optimization

Maximal coverage (Church & ReVelle 1974) and p-median (greedy + Teitz &
Bart 1968 substitution) on network distances; capacitated allocation
(whole demand to the nearest facility with room, spill when full);
capacitated siting (greedy + capacity-aware swaps); multi-objective
land-use allocation `w·Σ(area·suit) + Σ L·C[u,u']` over the parcel
adjacency graph with compactness/adjacency terms, hard-contiguity
region growing, and the Pareto front over compactness weights with its
knee (max chord distance).

## Urban Growth

Transition matrices with per-class accounting; a constrained cellular
automaton (`suitability × (base + w × urban neighbour share)`, top-k
conversions per step, deterministic `default_rng` tie-breaks — the
cross-process identity is a unit test); sprawl metrics around SDG
11.3.1 `LCRPGR = ln(U₂/U₁) / ln(P₂/P₁)` plus patch structure and edge
density.

## Reporting & Scenarios

Score cards and the one-file HTML report are pure stdlib (inline SVG).
Scenario snapshots capture the metrics as JSON; comparisons are
direction-aware (the registry knows that a higher access score is good
and more deficits are bad). The Batch Plan Auditor chains the standard
battery and snapshots the result in one run.
