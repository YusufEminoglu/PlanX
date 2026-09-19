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
per node. Nearest-facility routes and OD routes rebuild the actual path
geometry from predecessor-tracking Dijkstra trees (node and edge ids
walked back to the source, oriented in travel order), with k-nearest
destination limits and cost cutoffs. Link criticality screens
road-network vulnerability (Network Robustness Index; Scott et al. 2006 /
Jenelius et al. 2006): over a fixed origin-destination demand it routes the
intact network, then removes each segment and re-routes, reporting
`extra_cost` (the rise in total OD travel cost, clipped at zero since a
removal can only lengthen a path), `criticality = extra_cost / base_total`
(that rise relative to the whole demand's baseline cost) and
`n_disconnected` (OD pairs a removal severs). Only segments on at least one
shortest path are re-tested — an edge on none cannot change any shortest
cost — which both prunes the work and gives `used_by` (shortest paths over
each segment); edge removal is a CSR adjacency mask, no graph rebuild.

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
Street Network Morphology reports `total_length_km`, `avg_segment_length_m`
and `intersection_density_km2` in ground metres too, converted from the
layer's own units through `algorithms/_units.py`: the graph's edge lengths
and the network hull are in coordinate units, and a foot layer or an
EPSG:3857 layer at 41°N would otherwise report a length wrong by 3.28 or
1.33 and an area wrong by 10.76 or 1.76.

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
low-score share of the route. Walking slope comfort samples a DEM along
each segment and reports length-weighted mean and maximum grades, climb
and descent, comfort classes and direction-aware travel times from
Tobler's hiking function `speed = 6·e^(−3.5·|m+0.05|)` km/h (`m` = signed
grade, fastest slightly downhill); the per-segment effective speed is the
time-based harmonic aggregation `length / walking time`, not the mean of
interval speeds. Street environment comfort turns weighted asset and
barrier points into per-segment kernel densities with `u = d/h`: uniform
`1`, triangular `1 − u`, Epanechnikov `1 − u²`, Gaussian `e^(−4.5·u²)`,
all truncated at the bandwidth `h`; optional rasters join as segment
means and the components combine min-max normalised, orientation-flipped,
into `index = 100 · Σ w·oriented_norm / Σ w`.

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
insertion loss behind buildings — screening, not compliance. Road emissions:
segment emissions `E = AADT * EF` (g/km/day). Air quality screening: dispersion index grid,
receivers and exposure bands. Dispersion modeled as line-calibrated point samples
where index `C = Σ strength / (u * (d + d0)^alpha)`. Calibration ensures that at 25 m, an
infinite line source under `alpha = 2` and wind speed `u` has concentration index equal
to the emission rate `E` (`strength = E * 25 * ℓ / π`). If buildings are present on both
sides perpendicular to the receiver, a canyon factor `1 + min(2, H/W)` is applied.

## Hazard Screening

Wang & Liu (2006) deterministic priority-flood depression filling using a priority queue. D8 flow direction: steepest-descent slope `(drop / distance)` to 8 neighbors with a fixed tie-break order. Flow accumulation: Kahn's topological sorting. Height Above Nearest Drainage (HAND): downstream elevation difference `dem[r, c] - dem[dr, dc]` relative to drainage cells (where flow accumulation >= threshold). Inundation mask: binary mask where `HAND <= depth`. Flood exposure: intersects inundation mask with building footprint centroids and population points to calculate exposed counts and percentage shares.


## Travel Demand

Linear trip generation: `P = pop * p_rate` and `A = jobs * a_rate`. Doubly constrained gravity distribution using Furness/IPF balancing with exponential `exp(-beta * cost)` or power `cost^-beta` deterrence functions over network costs computed via Dijkstra many-to-many shortest paths. Mode split: multinomial logit shares `P_k = exp(U_k) / sum(exp(U_m))` and split flows based on mode travel times, time coefficients (betas), and constants (ASCs). Parking demand: a zone takes the first rate row whose category keyword it contains, and its size column is read in that row's own basis — `unit` = spaces per dwelling unit, `sqm` = `rate · size / 1000` (per 1000 m² gross floor area), `seat` = spaces per seat. A zone whose category matches no row demands zero and is reported as an uncovered category instead of being folded into the total, so a rate table that does not reach a category reads as a coverage gap and not as a zone with no parking problem. Parking balance: supply is the spaces of every inventory feature at or below the radius from the zone — street-network distance when a network is given, straight-line otherwise — and `balance_spaces = supply − demand`, which is NULL rather than negative where the inventory never surveyed the zone: `supply_status` is `counted`, `zero supply found` (surveyed, nothing in range — a real deficit) or `supply data absent` (not surveyed at all), in that precedence order.


## Scenario Pipeline & Population Allocation

Population growth allocation uses largest-remainder apportionment (Hare-Niemeyer method). Quotas are calculated as `total * weight_i / sum(weights)`. Integer allocations are assigned as the floor of the quotas, and remaining fractional deficits are satisfied by distributing units one-by-one to elements with the largest fractional parts, tie-breaking by index ascending. Scenario Pipeline implements a Land-Use/Transport Interaction (LUTI) loop: runs cellular-automaton urban growth simulation, extracts developed cells, allocates population growth to cell centroids proportional to development suitability using largest-remainder allocation, and evaluates walkability and network accessibility.




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

## Cycling

Cycling Stress is a screening Level of Traffic Stress classifier after the
Mekuria/Furth family of methods, simplified to four transparent rule rows:
separated paths are LTS 1; painted lanes are LTS 2 when speed <= 50 and
lanes <= 3, otherwise LTS 3; mixed traffic is LTS 1 when speed <= 30,
lanes <= 2 and AADT < 1000, LTS 2 when speed <= 30 and lanes <= 2,
LTS 3 when speed <= 50, otherwise LTS 4. All thresholds are parsed from
an editable `key=value` table. Low-Stress Connectivity filters the primal
street graph to edges with `LTS <= threshold`, labels connected components
as cycling islands, sums island length, and optionally counts origin
population whose snapped node lies in a destination island.
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
battery and snapshots the result in one run. Demo City generates a
deterministic, synthetic town using block-subdivided geometries and
ray-intersection street noding.

Multi-scenario ranking scores any number of snapshots with a weighted
composite: every scored metric is min-max normalised direction-aware so
that 1 is always best (`norm = (v − min) / (max − min)` when higher is
better, `norm = (max − v) / (max − min)` when lower is better), then
`score = 100 · Σ w·norm / Σ w` with a default weight of 1. Ranks use
competition ranking on descending score (equal scores share a rank and
the next rank is skipped: 1, 2, 2, 4); wins count the metrics where a
scenario holds the strictly best norm, so a balanced alternative can
rank first with zero wins. Metrics are skipped as `neutral` (direction
0 or unknown), `not-shared` (missing in at least one snapshot) or
`constant` (max equals min), with reason precedence
neutral > not-shared > constant.

## Seismic Risk

Ground motion: the Akkar, Sandıkkaya & Bommer (2014) shallow-crustal model
for Europe and the Middle East, one of the four models in the logic tree of
Turkey's 2018 national seismic hazard map, with the authors' published
coefficients. `ln IM = a₁ + a₃(8.5 − Mw)² + (a₄ + a₅(Mw − 6.75)) ln√(R² + a₆²)`,
plus a magnitude slope that changes from `a₂` to `a₇` at the reference
magnitude of 6.75 (the paper's saturation above it) and a mechanism offset
from strike-slip. A nonlinear site term is then added, conditioned on the
rock PGA of the same scenario: `b₁ ln(Vs30/750) + b₂ ln((PGA_rock + c(Vs30/750)ⁿ)/((PGA_rock + c)(Vs30/750)ⁿ))`
for soft sites, and the linear hard-rock branch `b₁ ln(min(Vs30, 1500)/750)`
above the reference velocity of 750 m/s, where the site term is exactly zero.
`ε` shifts the median by that many total standard deviations. A point source
and a fault trace differ only in the distance they produce — epicentral or
hypocentral from the focal depth for the point, Joyner–Boore and epicentral
as perpendicular distances to the trace for the rupture — and every distance
is converted into kilometres from whatever the layer's CRS uses.

Damage and debris: Hazus 6.1 equivalent-PGA structural fragility curves
(Tables 5-37 to 5-40) as `P(DS ≥ ds | PGA) = Φ(ln(PGA/θ_ds)/β)`, with
θ per building type, height class and seismic design level, and
β = 0.64 = √(0.4² + 0.5²) as tabulated. Discrete state probabilities are the
differences of the exceedance curve, so a building carries a full
five-state distribution rather than a collapse yes/no. The design level
comes from the construction year through a single mapping that is an
uncalibrated screening assumption, not a Turkish code classification.
Debris: `V_solid = A·H·η·f_state`, `V_pile = V_solid/(1 − void)` and
`mass = V_solid·ρ`, with `f_state` the released-material fraction of the
damage state (0 for slight and none, 1.0 for complete) and η the material
share of the gross volume; the pile radius is the debris factor times the
height, scaled by `f_state`. Passability is the street network minus the
blocked footprint, opened morphologically at the minimum clear width, so a
corridor with no navigable width left is not reported as open. The buildings
are written as centroid points, with the footprint area carried alongside as
a `footprint_area` column so the downstream casualty model still has one.
`A` is a **ground** area in square metres, measured on the layer's CRS
ellipsoid, and so are the street widths, the reach along the street axis and
the radius the morphological opening uses: a raw `QgsGeometry.area()` is
square metres only on a metre CRS, and not even there away from the equator —
EPSG:3857 at 41°N inflates area by 1.757 and a US survey foot layer by 10.76.
`planx/algorithms/_units.py` (`GroundUnits`) does the conversion for every one
of those quantities, and the same helper backs the length and area claims of
Street Network Morphology. The pile radius is unaffected because it is driven
by height alone.

Casualties: the Hazus Section 12 event tree, per building, as
`rate = Σ_ds p_ds·r_ds` with the Complete state split into collapsed and
intact by the probability of collapse given Complete (Table 12-8); the
outdoor tree omits the slight branch and does not split on collapse. Rates
are per injury severity (1 slight to 4 fatal, Table 12-1) and are applied
to the indoor and outdoor populations separately — the population shares
being the occupancy class crossed with the scenario time of day (Table 12-2,
2 a.m. / 2 p.m. / 5 p.m.). The occupant count comes from a population field
when the layer has one, and otherwise from floor area times storeys over an
area per occupant, so the footprint is either the building geometry or, for
point buildings — which is what the debris tool writes — a footprint column;
with no footprint at all the run stops rather than return a city of zero
casualties. The bridge commuter path and the street-population
parameters are deliberately not implemented, because both need an inventory
the plugin does not model.

Shelter: the Hazus Section 13 displacement model. A building of one dwelling
unit is treated as single-family and one of two or more as multi-family,
which is how Hazus splits its residential classes (RES1 against RES3), and
the uninhabitable fraction is `P(complete)` for single-family and
`0.9·P(extensive) + P(complete)` for multi-family. Displaced households are
`#DH = κ·u·%`, where `u` is the dwelling units and `κ` the occupancy rate
(households per dwelling unit), so total households are `#HH = κ·u`. Public
shelter demand is `#STP = #DH·(POP/#HH)·α`, with α the weighted sum of the
four shelter modifier groups across income, ethnicity, ownership and age.
The tool's modifiers are neutral, so α = 1.0 exactly and public shelter is an upper
bound rather than a forecast; Hazus's own Table 13-3 factors run from 0.13
to 0.62 and are quoted in the engine next to the neutral default.

Liquefaction: two models again, because the question is answered from two
different sets of inputs. The regression model is Zhu, Daley, Baise, Thompson,
Wald & Knudsen (2015), *Earthquake Spectra* 31(3), 1813-1837, Table 3 —
`X = 24.10 + 2.067·ln(PGA·Mw^2.56/10^2.24) + 0.355·CTI − 4.784·ln(Vs30)`,
`P = 1/(1 + e^−X)` — with PGA in `g` and Vs30 in m/s. **Magnitude enters
inside the logarithm**, raised to 2.56 and weighted by 2.067; the form that
writes `2.56·ln Mw` as a separate additive term scales magnitude by 1 instead
of 2.067, and looks entirely plausible in a result table. The published
expression divides by 100 because ShakeMap accelerations are in percent g,
and this tool's field is already in `g`, so it does not — which is also why
the clip ceiling is reported as 2.7 g rather than as the 270 the paper prints.
CTI is `ln(a/tanβ)` with `a` the D8 flow accumulation times the pixel size
**in metres**: the index is the log of a metric area, so a DEM in feet
inflates it by `ln(3.281)` = 1.19, which the CTI coefficient turns into 0.42
logit units of unit error. A cell with no downslope neighbour has `tanβ = 0`
and an index of `+inf` — not a missing value, which is what the index says
about flat or ponded ground — so the model's own ceiling of 15 is what
evaluates it, and the run reports those rows separately from cells that are
off the grid or on nodata, which stop the run. PGA and CTI are both clipped to
the ranges the coefficients were fitted on, and every row where a clip bit
says so in its own notes column. Vs30 comes from a field, a raster, a constant
or the topographic slope, in that order, and each row records which of the
four it took. The slope relation is the piecewise-linear table of Allen & Wald
(2007), USGS OFR 2007-1357 Table 2, interpolated along the subdivided NEHRP
boundaries and held flat outside the published nodes; its active-margin and
stable-continent columns diverge by up to 1.96 in velocity at one slope, which
the velocity coefficient turns into 3.2 logit units — which is why the
tectonic setting is an explicit choice with no default. The proportion of
*area* affected is published separately and is reported as its own column at
0.81 times the point probability, rather than folded into it.

The susceptibility model is the Hazus 6.1 Section 4.2.2.1 chain:
`P = P[LSC|PGA=a]/(K_M·K_W)·P_ml`, with `P[LSC|PGA=a]` the Table 4-11 line for
the unit's category clipped to [0, 1], `K_M = 0.0027·M³ − 0.0267·M² − 0.2055·M + 2.9188`
(Equation 4-10), `K_W = 0.022·d_w + 0.93` with `d_w` in **feet** (Equation
4-11) and `P_ml` the Table 4-10 proportion. Both correction polynomials are
applied exactly as printed, reference-value residual and all: neither passes
through unity at the conditions it was fitted to (`K_M(7.5) = 1.0147`,
`K_W(5 ft) = 1.04`), and renormalising would move every number about
5 percent away from the published method to fix a cosmetic inconsistency in
the source. Expected settlement is the probability times the Table 4-13
amplitude — the manual's own definition — and the amplitude's stated
one-half-to-two-times uncertainty is not propagated, so the column is a
midpoint with a range rather than a prediction.

Coseismic landslide: the Newmark sliding-block displacement in the
disposable-parameter form of Jibson (2007) Equation 8,
`log₁₀ D_N = −2.71 + log₁₀[(1 − a_c/a_max)^2.335 · (a_c/a_max)^−1.478] + 0.424·M`,
with `D_N` in **centimetres** and both accelerations in `g`. The reported 90th
percentile is a lognormal one: the regression's standard deviation is 0.454 in
log10 units, so `D₉₀ = D_N·10^1.2816σ` = 3.82·D_N. Two cases are reported as
what they are rather than clipped away. Where `a_c ≥ a_max` the block genuinely
does not move and the displacement is 0.0 with an empty log displacement and a
note saying so. Where the ratio falls below 0.05 the equation is extrapolating,
and the value is reported as the equation gives it with a note saying that
instead. A zero `a_c` is refused rather than substituted, because
`(a_c/a_max)^−1.478` diverges there: a material with no strength to mobilise is
not a slope with a displacement, it is a flow, which is the liquefaction
question rather than this one. The paper is paywalled and was **not** read; the
coefficients were transcribed from Yiğit (2026), *Pamukkale Üniversitesi
Mühendislik Bilimleri Dergisi* 32(1), 191-199, which prints Equation 8 beside
its own refit of the same data (exponent 1.3593 against the published 2.335)
and reproduces the Arias-intensity form digit-for-digit. The Arias models are
deliberately not implemented: Jibson Equation 9 —
`0.561·log₁₀ I_a − 3.8331·log₁₀(a_c/a_max) − 1.474` — and the regression of the
public-domain USGS Open-File Report 98-113 both carry Arias intensity, which
**Ground Motion Scenario** does not produce and no other tool in the plugin
does. Equation 8 is the one published form that takes only the ratio and the
magnitude.

The critical acceleration comes from one of three routes, and every row records
which. A field of `a_c` in `g` is a measurement and the best route when it
exists. The Hazus 6.1 Section 4.2.2.2 chain takes it from a geologic group and
a groundwater state: Table 4-14 maps `(group, moisture, slope band)` to a
susceptibility category, Table 4-15 bounds both the slope angle (15, 10, 5
degrees dry and 10, 5, 3 wet for groups A, B, C) and the critical acceleration
(0.20, 0.15, 0.10 dry and 0.15, 0.10, 0.05 wet), Table 4-16 maps the category
to 0.60 g down to 0.05 g, and Table 4-17 gives the fraction of the map unit
Hazus expects to be susceptible deposit. Below Table 4-15's slope bound no
susceptible deposit is established at all, and the tool reports an **empty**
`a_c` rather than a zero — zero is the value Equation 8 diverges on, so a
zeroed row would be the model's loudest answer arriving disguised as its
safest. The Table 4-15 acceleration floor is applied to the Table 4-16 value,
and across all 36 cells of the three-group by two-moisture by six-band table it
overrides exactly one: group B, wet, above 40 degrees, where the category is X
at 0.05 g and the bound is 0.10 g; the engine asserts which cell that is rather
than assuming it. The third route reads a susceptibility category somebody else
assigned, Roman numerals only, because a numeric column cannot say whether 1
means the least susceptible, as Hazus counts it, or the most. The groundwater
state has no default — dry and wet are up to four categories apart at one slope
and group, a factor of eight in the acceleration — and Table 4-17's area
fraction is reported as its own column and never multiplied into the
displacement, which is a property of the sliding block rather than of the map
unit.

The slope is the D8 steepest-descent gradient, `S = (1/p)·max_k(Δ_k/d_k)` over
the eight neighbours, sampled at one point per feature. The pixel `p` is left
in the DEM's own CRS units: a slope is a ratio of a vertical to a horizontal
difference, and converting one of the two alone would rescale every slope on a
DEM whose elevations are in feet. A cell with no strictly lower neighbour — a
pit, a flat or a nodata edge — gets `S = 0`, the same convention the flow and
wetness passes use, and the run log states the unit assumption rather than
hiding it. The point sample is a real limit: a parcel whose point-on-surface
lands on the flat bench above a scarp reads as not susceptible while the scarp
itself is the hazard.

Every Hazus part is transcribed from a United States federal publication and
is applied here uncalibrated to Turkish stock; the ground-motion model carries
no basin and no directivity term, the liquefaction regression is a United
States calibration with no Turkish liquefaction inventory behind it, and the
landslide displacement is a United States calibration with no Turkish landslide
inventory behind it — the Hazus category of a Turkish map unit is whoever
classified it. Every one of those limits is stated in the tool's own help text
and in the manual, beside the numbers it qualifies.
