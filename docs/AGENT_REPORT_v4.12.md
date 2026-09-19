# PlanX Agent Report: Version 4.12.0 (Parking Demand & Supply Balance)

Parking Demand & Supply-Balance — execution of `docs/ENHANCEMENT_PLAN_v4.12.md`.

## 1. Phase status

Phase 1: DONE — Parking Demand Estimator (`planx:parkingdemand`) implemented, registered, tested and committed as `e741c47`. Its output sink was amended within that commit to preserve input geometry.
Phase 2: DONE — Parking Supply-Demand Balance (`planx:parkingsupplybalance`) implemented, registered, tested and committed as `719d4b7`. Purely additive.
Phase 3: DONE — both tools documented in the manual to the full eight-section-plus-references template, icons published, README/CHANGELOG/metadata/Studio counts refreshed, version bumped to 4.12.0. Committed as the `phase-3:` commit listed in §6, which is the commit that adds this report. Not tagged, not released, not pushed.

## 2. Shortcomings register outcomes

**S1 — mixed-use / shared-parking reductions deferred. DEFERRED, AND STATED.**
Not implemented, and not silently absent. The algorithm's `shortHelpString()` and the manual's §2.4 both say the tool reports the sum of single-use requirements, that real demand is lower where uses peak at different times, and that the discount has to be argued and applied outside the tool. The per-category subtotals in the log are documented as the quantity any reduction argument has to answer.

**S2 — defaults are illustrative; the help must say so as plainly as `alg_trip_generation.py`. DONE.**
The help text states: "The shipped rates are illustrative starting values written in the convention of the ITE Parking Generation manual (Institute of Transportation Engineers), not figures taken from it. They are not a substitute for a local standard: substitute your own municipal, campus or survey rates before quoting absolute space counts." The manual's §2.3 and §5 repeat it, and the source constant in `alg_parking_demand.py` carries the same caveat for maintainers.

**S3 — "zero supply found" vs "supply data not collected". DONE.**
The balance tool writes a three-state `supply_status`: `counted` (inventory found in range), `zero supply found` (the inventory reaches this zone and holds nothing in range — a real deficit), and `supply data absent` (the inventory does not reach this zone at all — a coverage gap). The third state gets a NULL `balance_spaces`, so summing the column cannot present unsurveyed ground as a shortfall, and precedence is explicit: a facility found in range outranks the coverage proxy. Covered by pure tests and by the one-off end-to-end check.

**S4 — state whether a network radius or a straight-line buffer was used. DONE.**
Both are available and the output says which one produced the figures: the `radius_method` column records `network` or `straight_line`. The manual's §2.3 states the choice, and also states the network mode's approximation plainly — a zone and a facility each attach to their nearest network node, so the measured distance is between nodes and can overstate by up to about one node spacing on a coarse network, which is why densifying is recommended before ranking near-equidistant facilities.

**S5 — confirm `scratch/planx_import_check.py` exists and still runs cleanly. DONE, WITH A CAVEAT WORTH ACTING ON.**
It exists, but not at the path the plan assumed: it is at the **monorepo root** (`qgis_plugins/scratch/planx_import_check.py`), not `planx/scratch/`. It runs clean (71 algorithms, 19 groups, `IMPORT CHECK OK`, exit 0) and it does assert the help-string section, so ground rule 3's assumption held. Two caveats: it must be run with the monorepo root as the working directory, and **it is outside the PlanX repository and untracked by git**, so it cannot serve as a gate for a reviewer or for CI. It also asserts only `"How to read the results"`, not `"Using the results"`, and its own docstring still says "53 algorithms". The versioned equivalent, `tests/smoke_provider_catalog.py::test_algorithm_help_strings_have_the_required_sections`, asserts **both** sections on every algorithm and is green.

### New shortcomings found during execution

**S6 — the standing runtime matrix never produces `supply data absent`.**
All 25 fixture zones fall inside the facilities extent, so the third state is never exercised end to end by the sweep. `S3`'s classification itself is permanently covered by the pure `classify_supply` tests, and the end-to-end wiring of the unsurveyed path is covered by the one-off `scratch/_verify_parking_balance.py`, which is not shipped. Making it standing would require adding a partial-extent inventory fixture to the matrix — a matrix extension, deliberately not smuggled into this phase.

**S7 — there is no dashboard test suite, so the plan's §4.4 has no artifact to report.**
`tests/` contains exactly four files (`test_engine.py`, `smoke_plugin.py`, `smoke_provider_catalog.py`, `qgis_runtime_algorithm_matrix.py`) and none of them touches the dashboard. Reported as PARTIAL below rather than filled with an approximation.

**S8 — on QGIS 3.44 LTR the runtime matrix cannot write its own report.**
The sweep completes every case and then parks in its final `shutil.rmtree(work_dir, ignore_errors=True)`: `ignore_errors` suppresses an exception, not a hang, and on Windows QGIS still holds handles to the hundreds of temporary Processing layers. Neither the JSON report nor the verdict line is produced. The harness already guards `_teardown` on Windows for exactly this class of hazard and does not guard its sibling `rmtree`. The LTR evidence below was therefore produced through `scratch/_run_matrix_diag.py`, which replaces that one call with a no-op and changes nothing else. This is a harness defect, not a v4.12 code defect, and it is specific to this runtime. On this machine it occurred on every LTR sweep that printed per-case lines — two full 71-case runs and one two-case run — while every LTR sweep that printed only a summary completed and passed (69/69, 70/70 and a single-case run). The 4.2.0 runtime is unaffected. The correlation with the per-case print path is an observation from four log files, not a diagnosis, and it is recorded as such so whoever fixes S8 has a starting point rather than a guess.

**S9 — the README's "448 end-to-end assertions" is unverifiable and was left alone.**
The claim appears once, in `README.md`, and no test, script or document in the tree produces or checks that number. Its companion claim ("503 engine unit checks") *is* verifiable and was corrected to 570. An unverifiable number was left as found rather than replaced with a guess.

**S10 — `planx_import_check.py` is stale in its own header and narrower than ground rule 3 assumed.**
Its docstring says "provider + 53 algorithms" against a registry of 71, and it checks one of the two required help sections. Both are consequences of it being unversioned (S5) and neither affected this release, but the script should not be relied on as a gate.

**S11 — a multi-phase release necessarily has red intermediate commits.**
Relevant to the maintainer's open question Q5. The catalog gates are release-level: registry ↔ manual anchor one-to-one, manual Processing-ID lines ↔ anchors, README counts ↔ manual contents, version literals. Phase 2 was therefore red on exactly two gates (`test_algorithm_ids_match_manual_anchors_one_to_one` and `test_manual_processing_id_lines_match_their_anchor`), both listing `['parkingdemand', 'parkingsupplybalance']` — the two anchors Phase 3 adds. If these gates are made to *block*, then any release split across phases will block on its own intermediate commits by construction. The choice is between blocking (and accepting red intermediate commits) and warning until the final phase.

## 3. New algorithm summary

| algorithm id | displayName | inputs | outputs | rate-source citation |
|---|---|---|---|---|
| `planx:parkingdemand` | Parking Demand Estimator | Zone layer (Polygon/Point); land-use category field (Text); size field (Numeric); rate table (`category=basis:rate`, basis ∈ `unit`/`sqm`/`seat`) | Zone layer in the input's geometry and CRS, all original attributes plus `parking_demand` (Double, spaces, 2 dp) | **No rates are taken from a source.** The defaults are illustrative values *written in the convention of* ITE (2019) *Parking Generation*, 5th ed. (ITE, Washington DC) — cited as the convention, never as the provenance of the numbers, and the help text says so. The requirement-versus-standard framing follows Shoup (1999), DOI `10.1016/S0965-8564(99)00007-5`. |
| `planx:parkingsupplybalance` | Parking Supply-Demand Balance | Zone layer (Polygon/Point) with demand field; demands (Numeric); parking inventory (Point/Polygon); spaces-per-facility field (Numeric); access radius (Double, map units); optional street network (Line) | Geometry-less table, one row per zone: all original attributes plus `demand_spaces`, `supply_spaces`, `balance_spaces`, `supply_status`, `nearest_supply_dist`, `radius_method` | **No rate source applies: supply is counted, never assumed.** The reach assumption is the user's radius and reach method, recorded per row. Supporting literature: Shoup (1999) `10.1016/S0965-8564(99)00007-5`; Davis et al. (2010) `10.1016/j.landusepol.2009.03.002`; van Ommeren et al. (2012) `10.1016/j.tra.2011.09.011`. |

Every DOI above was verified against Crossref during this phase rather than recalled; a sixth candidate (Mingardo et al.) failed to resolve and was dropped rather than guessed.

## 4. Test evidence

### 4.1 pure/engine unit checks (verbatim, complete)

`py -3 tests/test_engine.py` — complete output follows. Every check in this module executes at import time, so the count is the number of assertions actually run.

```
PASS path graph: 3 nodes, 2 edges
PASS path graph: degrees [1,2,1]
PASS dijkstra path: dist A->C == 2
PASS scipy availability detected
PASS many_to_many: scipy == pure fallback
PASS multi_source dist: scipy == pure fallback
PASS multi_source labels agree (same nearest source)
PASS path graph: betweenness(B) == 1 pair
PASS path graph: endpoints betweenness == 0
PASS path graph: each edge lies on 2 pairs
PASS star graph: betweenness(center) == 6 pairs
PASS star: center reach == 4
PASS star: center closeness == 1.0 (WF)
PASS star: leaf farness == 1 + 3*2 == 7
PASS star: center harmonic == 4
PASS star: center straightness == 1 (radial lines)
PASS path radius=1: B reaches exactly 2
PASS sampling with all sources == exact
PASS collinear: connectivity [1,2,1]
PASS collinear: NC == 3 everywhere
PASS collinear: TD == 0 (no turns)
PASS collinear: choice(mid) == 1 pair
PASS collinear: NACH(mid) == log10(2)/log10(3)
PASS collinear: NAIN == 5^1.2 / 2
PASS right angle: TD == 1 for both segments
PASS tee: TD(west arm) == 1
PASS tee: TD(north arm) == 2 (two turns)
PASS collinear radius=1: NC(end) == 2
PASS collinear radius=1: NC(mid) == 3
PASS internal curvature counted (90 deg == 1.0)
PASS bent polyline: TD includes half-curvature convention
PASS parse_radii('400, 800, n')
PASS square: area 1, perimeter 4
PASS square: IPQ == pi/4
PASS square: convexity == 1
PASS square: rectangularity == 1
PASS square: elongation == 0
PASS square: 4 corners
PASS 4x1 rect: elongation == 0.75
PASS 4x1 rect: orientation == 0
PASS rotated rect: orientation == 30
PASS L-shape: area == 3
PASS L-shape: convexity == 3/3.5
PASS courtyard: net area 12
PASS courtyard index == 4/16
PASS grid bearings: entropy == ln 4
PASS grid bearings: orientation order == 1
PASS uniform bearings: entropy == ln 36
PASS uniform bearings: orientation order == 0
PASS tree: alpha == 0
PASS 5x5 grid: alpha == 16/45
PASS convex hull drops interior point
PASS equinox equator noon: altitude > 87
PASS london solstice noon: altitude ~ 61.9
PASS london solstice noon: azimuth ~ 180
PASS izmir winter noon: altitude ~ 28.1
PASS london solstice morning: azimuth < 120 (east)
PASS tower shadow: 10 cells north shadowed
PASS tower shadow: 12 m north is lit
PASS tower shadow: nothing south/east/west
PASS low sun: shadow reaches ~20 m
PASS sun below horizon: everything shadowed
PASS western sun: shadow points east
PASS SVF flat == 1
PASS SVF at the foot of a tall wall ~ 0.5
PASS SVF far from wall ~ 1
PASS frontal width, north wind == 10
PASS frontal width, west wind == 20
PASS frontal width, 45 deg wind == (10+20)/sqrt(2)
PASS parse_standards: 3 entries
PASS match contains, case-insensitive
PASS no match -> None
PASS malformed standards raise
PASS balance: green surplus 1000
PASS balance: per-capita actual 20
PASS balance: no standard for industry
PASS balance: deficit -8000
PASS access summary: mean 62.5, median 75
PASS access summary: 50% full, 25% low
PASS balance summary: 2 with std, 1 deficit, 50% compliance
PASS balance summary: worst is School -800
PASS balance summary: no standards -> compliance None
PASS adequacy summary: covered 80%
PASS adequacy summary: 1 overloaded 1 unused, mean util of used
PASS adequacy summary: pop defaults to 1
PASS density summary: mean 20 max 30
PASS overall score == mean of components
PASS overall score None when nothing
PASS ramp endpoints red->green
PASS 5 cards with index first
PASS compliance card flags worst deficit
PASS html: escaped title + all sections
PASS html: charts inline (3+ svg) and self-contained
PASS html: badges for statuses
PASS svg map empty for no points
PASS svg map: 2 circles, red and green
PASS svg map thins to max_points
PASS balance bars skip no-standard rows
PASS screening weights on line == [2,3,3,3,2]
PASS greedy coverage picks [1, 3] with gains [3, 2]
PASS greedy coverage covers everything
PASS greedy coverage stops early when saturated
PASS weighted coverage chases the heavy demand
PASS coverage with fixed=1 picks 3 (gain 2)
PASS 1-median with heavy tail == node 4, objective 10
PASS Teitz-Bart escapes the greedy trap (objective 40, swaps >= 1)
PASS p-median with existing at 0 adds node 3
PASS p-median penalty = 1.5 x max finite
PASS assignment flags unreachable as -1
PASS assignment to nearest of {1,3}
PASS empty candidates raise
PASS eigenvector P3: center == 1
PASS eigenvector P3: ends == 1/sqrt(2)
PASS eigenvector star: hub == 1
PASS eigenvector star: leaves == 0.5
PASS eigenvector empty graph
PASS sun hours flat: every cell == site daylight
PASS sun hours equator June: ~12 h daylight
PASS sun hours: cells beside the tower lose sun vs far corner (lat 40N)
PASS sun hours: tower top keeps full daylight
PASS clear sky: sun below horizon -> 0
PASS clear sky zenith: beam 800-1100 W/m2, diffuse smaller
PASS clear sky: beam grows with altitude
PASS irradiation flat: all cells == flat reference
PASS irradiation: June > December at 38N
PASS irradiation: SVF 0.5 cuts the diffuse share
PASS heat risk: fully built at h_ref == 100
PASS heat risk: fully green == 0
PASS heat risk: empty flat cell == 100/3 (default weights)
PASS heat risk: green cover lowers the score
PASS heat risk: height capped at h_ref
PASS gini [1,2,3,4] == 0.25
PASS gini all-equal == 0
PASS gini [20,20,80,80] == 0.3
PASS gini weighted == unweighted when weights equal
PASS weighted gini == mean-difference / (2*mu)
PASS theil all-equal == 0
PASS theil [0,2] == ln 2
PASS theil decomposition adds up (T = between + within)
PASS theil fully between when groups are homogeneous
PASS theil per-group means 20 and 80
PASS weighted median of [20,20,80,80] in range
PASS p90/p10 of [20,20,80,80] == 4
PASS percentile rank mid-rank for ties (lows 0.25, highs 0.75)
PASS cv all-equal == 0
PASS share_below 50 of [20,20,80,80] == 0.5
PASS share_above 50 of [20,20,80,80] == 0.5
PASS equity handles empty weights gracefully
PASS capacitated: p0->F0, p1/p2 spill to F1 (F0 full)
PASS capacitated: spill flags [F,T,T]
PASS capacitated: nearest is F0 for all
PASS capacitated: loads [10, 20]
PASS capacitated: remaining [5, 80]
PASS capacitated max_cost: only p0 served (F1 out of reach)
PASS capacitated max_cost: p1/p2 still report nearest F0
PASS capacitated: zero capacity -> all uncovered
PASS parse_targets basic
PASS allocate basic: assign [0,0,-1,1]
PASS allocate basic: objective 2600
PASS allocate basic: allocated [200,100]
PASS allocate basic: counts [2,1]
PASS allocate swap-trap: optimal assign [1,0]
PASS allocate swap-trap: objective 170
PASS allocate swap-trap: a swap was applied
PASS allocate locked: p2 fixed to use 1, p0/p1 -> use 0, p3 left over
PASS allocate locked: objective 2500
PASS allocate shortfall: use 0 takes all 400 (< 1000 target)
PASS allocate clips negative suitability to 0
PASS multi no-spatial == pure suitability split [0,1]
PASS multi no-spatial: spatial_score 0
PASS multi compactness: adjacent parcels cluster into one use
PASS multi compactness: objective 69 (suit 19 + spatial 50)
PASS multi no rule: use 1 sits in the middle (suitability greedy)
PASS multi adjacency penalty: use 1 pushed to an end, not the middle
PASS multi adjacency: objective 5 (suit 15 - one penalised 10 m border)
PASS annual: 12 months swept
PASS annual: 12 monthly maps + 12 means
PASS annual flat: every cell == flat-ground annual reference
PASS annual == sum of the 12 monthly maps
PASS annual flat == sum of the 12 flat-month totals
PASS annual flat at 38N is physically plausible (kWh/m2/yr)
PASS annual: June outshines December at 38N
PASS annual keep_monthly=False: maps dropped, means kept, totals match
PASS annual months=[6]: only June swept
PASS annual months=[6] == June slice of the full run
PASS annual: SVF 0.5 lowers the scene total vs full sky
PASS annual: shaded cell north of tower < open far field
PASS annual: tower top reaches the scene maximum
PASS annual: NaN DSM cell stays NaN, valid cells finite & positive
PASS days in month: 2024 Feb == 29 (leap), 2026 Feb == 28
PASS days in month: Apr 30, Jul 31, 2000 Feb 29, 1900 Feb 28
PASS pareto_mask: (25,1) is dominated by (38,1); the other three survive
PASS pareto_mask: a concave trade-off keeps all three points
PASS knee: the bulging middle point (38,1) is the knee
PASS knee: a two-point front has no knee (-1)
PASS same-use boundary: blocked A,A,B,B counts both inner edges, interleave 0
PASS pareto front: zero weight gives the max-suitability interleaving (40, 0)
PASS pareto front: a high weight trades suitability for compactness (20, 2)
PASS pareto front: suitability never beats the unconstrained best (40)
PASS pareto front: both extremes lie on the non-dominated front
PASS pareto front: one assignment per weight, all 4 parcels long
PASS pareto front: the high-weight run is the blocked (compact) allocation
PASS atkinson: perfect equality is 0 at any aversion
PASS atkinson: zero aversion (epsilon 0) is always 0
PASS atkinson: epsilon=1 is the geometric-mean gap (1-sqrt(2)/1.5)
PASS atkinson: epsilon=2 is the harmonic-mean gap (1-(4/3)/1.5)
PASS atkinson: more aversion never lowers the index
PASS atkinson: a zero value collapses the index to 1 when epsilon>=1
PASS atkinson: a zero value is finite when epsilon<1
PASS lorenz: equality lies on the diagonal (gini 0)
PASS lorenz: curve runs from (0,0) to (1,1)
PASS lorenz: an unequal curve sags below the line of equality
PASS lorenz: trapezoidal gini == the mean-difference gini (0.25)
PASS concentration: ordered by its own value, equals the Gini
PASS concentration: value falling with rank gives a negative index
PASS lorenz: population weights shift the curve (gini stays in [0,1))
PASS capacitated siting: selected facility is Y (index 1)
PASS capacitated siting: served demand is 40
PASS capacitated siting: load of Y is 40
PASS capacitated siting: load of X is 0
PASS soft allocation splits Use 0
PASS hard allocation yields connected Use 0
PASS hard allocation yields connected Use 1
PASS hard allocation area target 0 met
PASS hard allocation area target 1 met
PASS crosstab: halves edge at the weighted median 2.5
PASS crosstab: classes are [0,0,1,1]
PASS crosstab: cells put all of A low / all of B high
PASS crosstab: A is 2x over-represented in the low class
PASS crosstab: complete separation -> dissimilarity 1 for both
PASS crosstab: value shares 0.3 (A) / 0.7 (B)
PASS crosstab: per-group gini matches equity.gini
PASS crosstab: per-group means 1.5 / 3.5
PASS crosstab: identical group distributions -> dissimilarity 0
PASS crosstab: identical distributions -> all rep ratios 1
PASS crosstab: custom break keeps 2 classes
PASS crosstab: weighted pop shares 0.9 / 0.1
PASS crosstab: weighted value share of the heavy group 0.5
PASS scenario: summaries flatten to metric keys
PASS scenario: missing density -> no density metrics
PASS scenario: JSON round-trip keeps name and metrics
PASS scenario: higher-better improvement credited to B
PASS scenario: lower-better improvement credited to B
PASS scenario: lower-better worsening credited to A
PASS scenario: unchanged metric is a tie
PASS scenario: neutral direction stays n/a
PASS scenario: one-sided metrics have no delta and stay n/a
PASS scenario: verdict counts B 2 wins / A 1 win
PASS report: compare page carries both scenario names and the table
PASS report: compare page marks the B improvement green
PASS path tree: distances match Dijkstra
PASS path tree: route A->C is node 0-1-2 via edges 0,1
PASS path tree: source route is trivial
PASS parallel edges: straight edge chosen by length
PASS parallel edges: custom weights flip the chosen edge
PASS linear_score: increasing maps midpoint to 50
PASS linear_score: clamps above full
PASS linear_score: decreasing direction (block length)
PASS shannon_mix: two equal uses -> 1
PASS shannon_mix: one use -> 0
PASS shannon_mix: 3:1 split -> 0.8113
PASS walk_scores: single component -> total equals it
PASS walk_scores: all components at their midpoint -> 50
PASS walk_scores: custom weights (3:1 of 100 and 0 -> 75)
PASS walk_scores: unknown component raises
PASS gtfs: parse_time plain
PASS gtfs: parse_time past midnight
PASS gtfs: malformed time raises
PASS gtfs: 4 stops read
PASS gtfs: 8 trips read
PASS gtfs: missing files raise a named error
PASS gtfs: Monday runs
PASS gtfs: Sunday empty
PASS gtfs: exception removes 2026-07-07
PASS gtfs: first service day is 2026-01-01 (a Thursday)
PASS gtfs: stop A has 4 departures 07-09
PASS gtfs: headway at A is 30 min
PASS gtfs: C departs only via R2 in the window
PASS gtfs: terminus D never departs
PASS gtfs: two patterns compiled
PASS gtfs: R1 pattern holds 6 trips
PASS gtfs: RAPTOR reaches B 08:10
PASS gtfs: RAPTOR reaches C 08:20
PASS gtfs: RAPTOR transfers to D 08:35
PASS gtfs: without transfers D is unreachable
PASS gtfs: five past eight -> next 08:30 trip -> C 08:50
PASS gtfs: late start still catches the 09:25 branch to D
PASS viewshed: flat ground fully visible
PASS viewshed: cell before the wall visible
PASS viewshed: wall crest itself visible
PASS viewshed: ground right behind the wall hidden
PASS viewshed: far ground behind the wall hidden
PASS viewshed: west side unaffected
PASS viewshed: a 20 m mast behind the wall is visible
PASS viewshed: radius caps the sweep
PASS isovist: open disc area ~ pi r^2
PASS isovist: open disc circularity ~ 1
PASS isovist: open disc radials all at range
PASS isovist: nothing occluded in the open
PASS isovist: corridor is far smaller than the open disc
PASS isovist: corridor mostly occluded
PASS isovist: corridor still reaches its full length sideways
PASS isovist: origin on an obstacle collapses to zero
PASS isovist field: optimized is bit-identical to naive
PASS isovist field: per-point arrays align
PASS leslie: step 1 births 38, aged 90, elders 94
PASS leslie: step 2 [45.4, 34.2, 119]
PASS leslie: row 0 is the start population
PASS leslie: migration lands after the update
PASS leslie: emigration never drives a group negative
PASS housing: 4000 households -> target 4200
PASS housing: need = 4200 - 3800 + 100 + 50 = 550
PASS housing: oversupplied market reports a surplus
PASS capacity: 1000 m2 x 1.5 FAR - 600 = 900 buildable
PASS capacity: 900 x 0.85 / 90 -> 8 whole units
PASS capacity: overbuilt parcel clamps to zero, never negative
PASS pyramid: svg carries the labels and both series
PASS noise: RLS emission 1000 veh/h at 10 percent heavy = 69.9 dB
PASS noise: zero traffic is silent
PASS noise: infinite-line samples reproduce the 25 m reference
PASS noise: line spreading loses ~3 dB per doubling
PASS noise: screening subtracts exactly the insertion loss
PASS noise: cutoff silences distant sources
PASS noise: exposure bands split the population
PASS green: hierarchy parses and sorts
PASS green: malformed hierarchy raises
PASS green: one chained component
PASS green: fully connected PC = 1
PASS green: stepping stone loses 68.75 percent of PC
PASS green: end patch 0 loses 43.75 percent
PASS green: the large end patch matters most of the ends
PASS green: two isolated equal patches -> PC 0.5
PASS change: classes found
PASS change: matrix counts the single conversion
PASS change: per-class gains/losses/persistence
PASS change: nodata cells ignored
PASS ca: start mask preserved
PASS ca: demand fully converted over the steps
PASS ca: growth follows the suitability gradient east
PASS ca: year-of-conversion is ordered
PASS ca: constraints keep the east untouched
PASS ca: same seed reproduces the identical history
PASS ca: identical result from a separate process
PASS sprawl: LCRPGR = ln2 / ln1.21
PASS sprawl: two patches, largest holds 75 percent
PASS sprawl: edge length hand-count (2x3 block + 1x2 block)
PASS registry: walkability mean is higher-better
PASS registry: access Gini is lower-better
PASS registry: falling Gini credited to B
PASS registry: rising low-walk share credited to A
PASS registry: labels resolve for the auditor keys
PASS demo streets count
PASS demo buildings count
PASS demo landuse count
PASS demo pois count
PASS demo facilities count
PASS demo demand count
PASS demo green count
PASS demo DSM max == tallest building
PASS demo: identical result from separate process
PASS cycling: default rule table parses
PASS cycling: malformed rules raise
PASS cycling: every LTS rule row hand case
PASS cycling: agency threshold override changes classification
PASS cycling islands: high-stress bridge splits two low-stress islands
PASS cycling islands: low-stress share excludes bridge
PASS cycling islands: raising threshold merges the network
PASS air: doubling distance halves the single-source index at alpha=1
PASS air: canyon factor 2 when H=W
PASS air: infinite-line calibration within tolerance
PASS air: band splitting counts
PASS air: band splitting labels
PASS hydro: a pit DEM fills exactly to its pour point
PASS hydro: 1-D slope D8 directions are all East (1) except sink
PASS hydro: 1-D slope flow accumulation is 1..n
PASS hydro: 1-D slope HAND is elevation above the channel
PASS hydro: a hand-built valley floods the right three cells at depth 1
PASS hydro: exposure cross-tab equals hand counts
PASS demand: trip generation productions
PASS demand: trip generation attractions
PASS demand: 2x2 Furness balances to known closed-form solution
PASS demand: gravity totals conserved to 1e-9
PASS demand: beta=0 gives cost-independent proportionality
PASS demand: logit shares for two modes with a 10-minute gap match the hand value
PASS population: allocate_growth exactness and tie-breaking
PASS population: allocate_growth with varying weights
PASS population: allocate_growth uniform fallback for zero weights
PASS seismic: base probability tiers by construction year
PASS seismic: magnitude factor is 1.0 at the Mw=7.0 reference point
PASS seismic: magnitude factor matches the exponential formula off-reference
PASS seismic: collapse probability is clamped to 1.0 for extreme magnitude
PASS seismic: collapse probability stays within [0, 1] for a mild low scenario
PASS seismic: p=0 never collapses and p=1 always collapses
PASS seismic: same seed reproduces the identical collapse draw
PASS seismic: a different seed can sample a different draw
PASS seismic: debris radius is height x k for collapsed buildings, 0 otherwise
PASS seismic: debris volume is area x height x solid ratio for collapsed buildings, 0 otherwise
PASS seismic: OSM width - primary class maps to 18 m
PASS seismic: OSM width - motorway and trunk share 25 m
PASS seismic: OSM width - matching is case and whitespace tolerant
PASS seismic: OSM width - '_link' ramps inherit the parent class width
PASS seismic: OSM width - unknown class and None fall back
PASS seismic: width parse - plain numbers pass through
PASS seismic: width parse - numeric strings accepted
PASS seismic: width parse - decimal comma and unit suffixes accepted
PASS seismic: width parse - rubbish, empty, None and non-positive rejected
PASS iso: first edge fully reached, second is not
PASS iso: second edge trimmed at exactly half
PASS iso: 60+60 on a 100 m edge meets in the middle
PASS iso: 40+40 leaves a gap - two pieces
PASS iso: merge_intervals unions overlaps
PASS iso: subtract_intervals cuts a hole
PASS iso: subtracting a cover leaves nothing
PASS iso: interval_length sums the pieces
PASS iso: cut keeps the interior corner vertex
PASS iso: point_at the halfway mark is the corner
PASS iso: degenerate cut returns None
PASS iso: full-range cut reproduces the polyline
PASS iso: entry interval 30 m budget spans 0.2-0.8
PASS iso: snap cost eats the whole budget -> no piece
PASS iso: generous budget clips to the full edge
PASS iso: reach_intervals full edge + half edge
PASS iso: a mid-edge entry merges into the node reach
PASS iso: inner band is the 0.2-0.8 window around the entry
PASS iso: outer band is the two leftover tips
PASS parse_weights happy path
PASS parse_weights unknown list
PASS parse_weights empty text
PASS parse_weights <=0 ValueError
PASS parse_weights malformed ValueError
PASS rank ValueError on 1 snapshot
PASS rank ValueError on duplicate names
PASS rank: Gamma score 62.5
PASS rank: Alpha score 50.0
PASS rank: Beta score 50.0
PASS rank: Gamma rank 1
PASS rank: Alpha rank 2
PASS rank: Beta rank 2
PASS rank: scenarios order
PASS rank: n_metrics == 2
PASS rank: metrics length == 2
PASS rank: walk_score_mean norm Alpha == 0
PASS rank: walk_score_mean norm Beta == 1
PASS rank: walk_score_mean norm Gamma == 0.5
PASS rank: access_gini norm Alpha == 1
PASS rank: access_gini norm Beta == 0
PASS rank: access_gini norm Gamma == 0.75
PASS rank: Alpha wins == 1
PASS rank: Beta wins == 1
PASS rank: Gamma wins == 0
PASS rank: walk_low_share constant
PASS rank: units_total neutral
PASS rank: access_gini not-shared with Delta
PASS weighted rank: Alpha score 25.0
PASS weighted rank: Beta score 75.0
PASS weighted rank: Gamma score 56.25
PASS weighted rank: scenarios order (Beta, Gamma, Alpha)
PASS multi_source_tree: dist == [0, 1, 2, 1, 0]
PASS multi_source_tree: label == [0, 0, 0, 1, 1]
PASS multi_source_tree: pred_node == [-1, 0, 1, 4, -1]
PASS multi_source_tree: pred_edge == [-1, 0, 1, 3, -1]
PASS path_to_root: 2 -> ([0, 1, 2], [0, 1])
PASS multi_source_tree equal multi_source: dist
PASS multi_source_tree equal multi_source: label
PASS multi_source_tree equal multi_source on irregular graph: dist
PASS multi_source_tree equal multi_source on irregular graph: label
PASS multi_source_tree cutoff: dist[2] == inf
PASS multi_source_tree cutoff: pred_node[2] == -1
PASS multi_source_tree cutoff: pred_edge[2] == -1
PASS path_to_root: 0 -> ([0], [])
PASS path_to_root cyclic guard
PASS grade_stats: ascending profile
PASS grade_stats: mixed profile
PASS grade_stats: short profile
PASS tobler_speed: -0.05
PASS tobler_speed: 0.0
PASS tobler_speed: 0.10
PASS profile_time_min: Mixed 10m segments
PASS class_of: 4.9 -> 1
PASS class_of: 5.0 -> 1
PASS class_of: 7.2 -> 2
PASS class_of: 12.0 -> 3
PASS class_of: 12.1 -> 4
PASS parse_breaks: default
PASS parse_breaks: custom
PASS parse_breaks: ValueError non-ascending
PASS parse_breaks: ValueError non-numeric
PASS kernel_weight: uniform
PASS kernel_weight: triangular
PASS kernel_weight: epanechnikov
PASS kernel_weight: gaussian
PASS kernel_weight: beyond h
PASS segment_density: exact 0.8375
PASS segment_density: empty points
PASS combine_components: exact [100, 0, 25]
PASS combine_components: used positive, negative
PASS combine_components: dropped none
PASS combine_components: weighted [100, 0, 37.5]
PASS combine_components: constant dropped
PASS combine_components: absent None ignored
PASS combine_components: ValueError all None
PASS combine_components: ValueError all constant
PASS combine_components: ValueError empty dict
PASS linkcriticality: base_total == 5 over 2 reachable pairs
PASS linkcriticality: bridge e0/e1 extra_cost == 2, criticality == 0.4
PASS linkcriticality: cut edge e4 disconnects 1 pair, zero extra cost
PASS linkcriticality: off-path edges e2/e3 score zero
PASS linkcriticality: used_by counts shortest paths (e0/e1 == 2, e4 == 1)
PASS linkcriticality: same_layer 6 pairs, base_total == 12
PASS linkcriticality: same_layer bridge criticality == 4/12
PASS linkcriticality: same_layer cut edge severs 4 pairs (all with E)
PASS linkcriticality: scipy == pure fallback
PASS directed graph: forward route exists and reverse route is blocked
PASS directed graph: asymmetric forward/reverse costs
PASS directed graph: weak components ignore travel direction
PASS directed isochrone: reach only follows the allowed edge direction
PASS directed isochrone: mid-edge entry is one-sided
PASS optimization audit: exact p-median finds balanced site
PASS optimization constraints: coverage respects implementation budget
PASS optimization audit: exact search respects implementation budget
PASS provenance: manifest validates and has stable fingerprint
PASS scenario: provenance survives JSON round trip
PASS calibration diagnostics: MAE/RMSE are correct
PASS scenario uncertainty: seeded rank stability is reproducible
PASS scenario uncertainty: HTML board includes sensitivity results
PASS transit: walking transfer graph respects radius
PASS transit: walking transfer connects access stop to a route
PASS weather: monthly measured-sky factors
PASS parking: parse_rates yields (category, basis, rate) triples
PASS parking: semicolons and padding are accepted
PASS parking: a rate without a basis is rejected
PASS parking: an unknown basis is rejected
PASS parking: a non-numeric rate is rejected
PASS parking: a negative rate is rejected
PASS parking: an empty category keyword is rejected
PASS parking: an empty rate table is rejected
PASS parking: unit basis multiplies
PASS parking: seat basis multiplies
PASS parking: sqm basis is per 1000 m2
PASS parking: sqm basis on exactly 1000 m2 equals the rate
PASS parking: worked example demands [180, 10, 12, 0] spaces
PASS parking: category matching is case-insensitive and by containment
PASS parking: the first matching rate row wins
PASS parking: a matched but zero-size zone demands zero
PASS parking: unmatched categories are reported, not silently dropped
PASS parking: subtotals aggregate per category and sort
PASS parking: the demand total does not depend on feature order
PASS parking: supply_within sums only features inside the radius
PASS parking: supply_within counts the features it summed
PASS parking: a feature exactly at the radius counts, just inside it does not
PASS parking: supply_within ignores infinite costs
PASS parking: an empty inventory yields zero spaces, not an error
PASS parking: nearest_supply_cost is the closest feature per zone
PASS parking: nearest_supply_cost is inf where nothing is reachable
PASS parking: nearest_supply_cost of an empty inventory is all inf
PASS parking: straight-line costs are Euclidean
PASS parking: straight-line costs of an empty inventory have width zero
PASS parking: a zone with inventory in range is 'counted'
PASS parking: surveyed ground with nothing in range is 'zero supply found'
PASS parking: unsurveyed ground is 'supply data absent', not a deficit
PASS parking: inventory found in range outranks the coverage proxy
PASS parking: balance is supply minus demand, signed
PASS parking: an unsurveyed zone gets no balance at all
PASS parking: balance_summary is sorted by label
PASS parking: the survey totals cover the surveyed zones only
PASS parking: the unsurveyed zone is counted but excluded from the balance
PASS parking: deficit zones are counted for the reader
PASS parking: with nothing surveyed no balance is reported at all
PASS parking: balance_summary is deterministic across calls
PASS parking: a surplus is reported as a positive balance and no deficit

570/570 checks passed
C:\Users\YE\PyCharmMiscProject\qgis_plugins\planx\engine\equity.py:143: RuntimeWarning: divide by zero encountered in log
  term = np.where(r > 0, r * np.log(r), 0.0)
C:\Users\YE\PyCharmMiscProject\qgis_plugins\planx\engine\equity.py:143: RuntimeWarning: invalid value encountered in multiply
  term = np.where(r > 0, r * np.log(r), 0.0)

Run as `py -3 tests/test_engine.py`: **exit 0**.
```

The three checks added by Phase 1 and the 23 added by Phase 2 are visible at the end of that output. The suite was 547 checks before Phase 2 and is 570 after.

### 4.2 e2e QGIS 3.44 output (verbatim, complete)

Runtime: **QGIS 3.44.12-Solothurn (LTR)**. Per-case result lines first, then what the run did at the end.

One point of provenance, stated rather than glossed because it bounds what this section proves: the stock invocation on this runtime prints all 71 per-case lines and then never returns — that is **S8**. To get the lines at all, this run was driven through `scratch/_run_matrix_diag.py`, which loads the matrix module unmodified by path and replaces its final `shutil.rmtree` with a no-op. Nothing else is changed: the fixtures, the cases, the assertions and the pass/fail decision are the matrix module's own.

```
  ok   planx:flowaccumulation                1.28s
  ok   planx:accessscore                     0.14s
  ok   planx:densitygrid                     0.03s
  ok   planx:landusebalance                  0.02s
  ok   planx:facilityadequacy                0.06s
  ok   planx:scenariosnapshot                0.17s
  ok   planx:parkingdemand                   0.04s
  ok   planx:accessequity                    0.06s
  ok   planx:airscreen                       0.65s
  ok   planx:annualsolar                    11.43s
  ok   planx:buildingmetrics                 0.05s
  ok   planx:capacitatedallocation           0.06s
  ok   planx:capacitatedsiting               0.10s
  ok   planx:cyclingstress                   0.06s
  ok   planx:democity                        0.08s
  ok   planx:equitycrosstab                  0.07s
  ok   planx:facilitylocation                0.07s
  ok   planx:floodexposure                   0.06s
  ok   planx:frontalarea                     0.03s
  ok   planx:gravitymodel                    0.07s
  ok   planx:greenaccess                     0.06s
  ok   planx:greenconnectivity               0.05s
  ok   planx:growthsim                       0.07s
  ok   planx:gtfsimport                      0.06s
  ok   planx:handindex                       0.32s
  ok   planx:heatriskgrid                    0.03s
  ok   planx:housingneeds                    0.02s
  ok   planx:inequalitycurves                0.04s
  ok   planx:isovistfield                    7.02s
  ok   planx:landallocation                  0.05s
  ok   planx:landcoverchange                 0.07s
  ok   planx:linkcriticality                 0.05s
  ok   planx:lowstressislands                0.06s
  ok   planx:modesplit                       0.03s
  ok   planx:nearestfacility                 0.09s
  ok   planx:networkcentrality               0.07s
  ok   planx:noisescreen                    19.62s
  ok   planx:odmatrix                        0.06s
  ok   planx:odroutes                        0.08s
  ok   planx:paretoallocation                0.05s
  ok   planx:parkingsupplybalance            0.05s
  ok   planx:performancereport               0.10s
  ok   planx:planaudit                       0.09s
  ok   planx:popallocate                     0.03s
  ok   planx:populationprojection            0.04s
  ok   planx:preparenetwork                  0.14s
  ok   planx:residentialcapacity             0.05s
  ok   planx:roademissions                   0.03s
  ok   planx:routequality                    0.04s
  ok   planx:scenariocompare                 0.02s
  ok   planx:scenariopipeline                6.68s
  ok   planx:scenariorank                    0.07s
  ok   planx:seismicdebris                   0.14s
  ok   planx:serviceareas                    0.19s
  ok   planx:shadowcasting                   0.02s
  ok   planx:skyviewfactor                   1.30s
  ok   planx:solarirradiation                3.02s
  ok   planx:spacematrix                     0.03s
  ok   planx:spacesyntax                     0.06s
  ok   planx:sprawlmetrics                   0.09s
  ok   planx:streetcomfort                   0.11s
  ok   planx:streetmorphology                0.05s
  ok   planx:sunhours                        1.65s
  ok   planx:tessellation                    0.43s
  ok   planx:transitaccess                   0.04s
  ok   planx:transitfrequency                0.05s
  ok   planx:tripgeneration                  0.02s
  ok   planx:viewshed                        0.81s
  ok   planx:visualexposure                  0.09s
  ok   planx:walkability                     0.07s
  ok   planx:walkingslope                    0.07s

Result lines kept: **71** `ok`/`FAIL` lines, of which **0** `FAIL`. Third-party GDAL/OSGeo4W diagnostic lines filtered out: **1042** (chiefly `RasterIO() ... Access window out of range` from the raster tools).
```

**The run did not finish.** It printed all 71 case lines above — every one `ok`, 0 `FAIL` — and then blocked: no verdict line and no JSON report were produced. That is **S8**, and it is why the case lines are quoted individually instead of a one-line verdict.

There is no 71-case LTR verdict line to quote, from this run or any earlier one, so none is claimed. What this runtime *has* produced, on the same harness, is a completed verdict at smaller case counts: the pre-release tree reported `PLANX_RUNTIME_MATRIX: PASS (69/69)` and the Phase 1 tree, with Parking Demand Estimator added, reported `PASS (70/70)` — both on QGIS 3.44.12-Solothurn with zero catalog problems. The 71-case LTR verdict for this release is therefore not on record; what is on record is that all 71 cases pass individually on this runtime, and that the 4.2.0 runtime passes them and reports 71/71.

### 4.3 e2e QGIS 4.x output (verbatim, complete)

Runtime: **QGIS 4.2.0-Belém do Pará**. Stock invocation, no driver, report and verdict written normally.

```
  ok   planx:flowaccumulation                1.32s
  ok   planx:accessscore                     0.11s
  ok   planx:densitygrid                     0.02s
  ok   planx:landusebalance                  0.02s
  ok   planx:facilityadequacy                0.04s
  ok   planx:scenariosnapshot                0.10s
  ok   planx:parkingdemand                   0.02s
  ok   planx:accessequity                    0.03s
  ok   planx:airscreen                       0.50s
  ok   planx:annualsolar                     6.39s
  ok   planx:buildingmetrics                 0.03s
  ok   planx:capacitatedallocation           0.05s
  ok   planx:capacitatedsiting               0.06s
  ok   planx:cyclingstress                   0.04s
  ok   planx:democity                        0.05s
  ok   planx:equitycrosstab                  0.06s
  ok   planx:facilitylocation                0.04s
  ok   planx:floodexposure                   0.04s
  ok   planx:frontalarea                     0.02s
  ok   planx:gravitymodel                    0.06s
  ok   planx:greenaccess                     0.04s
  ok   planx:greenconnectivity               0.03s
  ok   planx:growthsim                       0.06s
  ok   planx:gtfsimport                      0.04s
  ok   planx:handindex                       0.30s
  ok   planx:heatriskgrid                    0.03s
  ok   planx:housingneeds                    0.01s
  ok   planx:inequalitycurves                0.03s
  ok   planx:isovistfield                    6.68s
  ok   planx:landallocation                  0.03s
  ok   planx:landcoverchange                 0.05s
  ok   planx:linkcriticality                 0.03s
  ok   planx:lowstressislands                0.04s
  ok   planx:modesplit                       0.02s
  ok   planx:nearestfacility                 0.07s
  ok   planx:networkcentrality               0.05s
  ok   planx:noisescreen                    17.53s
  ok   planx:odmatrix                        0.05s
  ok   planx:odroutes                        0.07s
  ok   planx:paretoallocation                0.04s
  ok   planx:parkingsupplybalance            0.05s
  ok   planx:performancereport               0.08s
  ok   planx:planaudit                       0.08s
  ok   planx:popallocate                     0.03s
  ok   planx:populationprojection            0.04s
  ok   planx:preparenetwork                  0.13s
  ok   planx:residentialcapacity             0.04s
  ok   planx:roademissions                   0.02s
  ok   planx:routequality                    0.03s
  ok   planx:scenariocompare                 0.02s
  ok   planx:scenariopipeline                6.35s
  ok   planx:scenariorank                    0.05s
  ok   planx:seismicdebris                   0.11s
  ok   planx:serviceareas                    0.14s
  ok   planx:shadowcasting                   0.02s
  ok   planx:skyviewfactor                   1.37s
  ok   planx:solarirradiation                2.96s
  ok   planx:spacematrix                     0.03s
  ok   planx:spacesyntax                     0.09s
  ok   planx:sprawlmetrics                   0.09s
  ok   planx:streetcomfort                   0.12s
  ok   planx:streetmorphology                0.05s
  ok   planx:sunhours                        1.60s
  ok   planx:tessellation                    0.53s
  ok   planx:transitaccess                   0.09s
  ok   planx:transitfrequency                0.05s
  ok   planx:tripgeneration                  0.03s
  ok   planx:viewshed                        0.83s
  ok   planx:visualexposure                  0.10s
  ok   planx:walkability                     0.07s
  ok   planx:walkingslope                    0.08s
PLANX_RUNTIME_MATRIX_JSON={"case_count": 71, "cases": [{"algorithm": "planx:flowaccumulation", "choices": {"DEM": "name:DEM->dem", "OUTPUT_ACCUM": "destination", "OUTPUT_DIR": "destination", "OUTPUT_FILLED": "destination"}, "display_name": "Flow Accumulation", "error": "", "extra_info": {}, "info": ["Results: {'OUTPUT_ACCUM': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\flowaccumulation\\\\flowaccumulation_OUTPUT_ACCUM.gpkg', 'OUTPUT_DIR': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\flowaccumulation\\\\flowaccumulation_OUTPUT_DIR.gpkg', 'OUTPUT_FILLED': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\flowaccumulation\\\\flowaccumulation_OUTPUT_FILLED.gpkg'}"], "ok": true, "outputs": {"OUTPUT_ACCUM": "140625/140625 populated pixel(s)", "OUTPUT_DIR": "140625/140625 populated pixel(s)", "OUTPUT_FILLED": "140625/140625 populated pixel(s)"}, "seconds": 1.317, "warnings": []}, {"algorithm": "planx:accessscore", "choices": {"AMENITIES": "multi:pois,facilities,green", "DECAY": "default:2", "NETWORK": "name:NETWORK->network", "ORIGINS": "name:ORIGINS->demand", "OUTPUT": "destination", "POP_FIELD": "hint:pop@demand", "SPEED": "default:4.8", "THRESHOLD": "default:15", "THRESHOLDS": "default:'5,10,15,30'"}, "display_name": "Multi-Amenity Access Score (15-Minute City)", "error": "", "extra_info": {"access_b": ["Category 'pois': 16 amenities", "Category 'facilities': 7 amenities", "Category 'green': 5 amenities", "Population 10,965 | weighted mean score 51.4 | full access 34.2% | no category reachable 23.9%", "Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\accessscore\\\\extra_access_b\\\\accessscore_OUTPUT.gpkg'}"]}, "info": ["Category 'pois': 16 amenities", "Category 'facilities': 7 amenities", "Category 'green': 5 amenities", "Population 10,965 | weighted mean score 100.0 | full access 100.0% | no category reachable 0.0%", "Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\accessscore\\\\accessscore_OUTPUT.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "34 feature(s)"}, "seconds": 0.107, "warnings": []}, {"algorithm": "planx:densitygrid", "choices": {"CELL_SIZE": "default:100", "INPUT": "override:demand", "OUTPUT": "destination", "VALUE_FIELD": "hint:value@demand"}, "display_name": "Density Grid", "error": "", "extra_info": {}, "info": ["34 features; grid 8 x 8 cells of 100", "Wrote 26 occupied cells.", "Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\densitygrid\\\\densitygrid_OUTPUT.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "26 feature(s)"}, "seconds": 0.024, "warnings": []}, {"algorithm": "planx:landusebalance", "choices": {"CATEGORY_FIELD": "hint:category@landuse", "LANDUSE": "name:LANDUSE->landuse", "OUTPUT": "destination", "POPULATION": "default:10000", "STANDARDS": "default:'green=10, park=10, playground=1.5, education=4, school=4, health=1.5, social=1.5, sport=3.5, market=0.5'"}, "display_name": "Land-Use Balance (Per-Capita Standards)", "error": "", "extra_info": {}, "info": ["  commercial: 180000 m2 (18.00 m2/capita)", "  green: 112500 m2 (11.25 m2/capita)", "  residential: 225000 m2 (22.50 m2/capita)", "  school: 45000 m2 (4.50 m2/capita)", "4 categories, 0 in deficit for a population of 10000.", "Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\landusebalance\\\\landusebalance_OUTPUT.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "4 feature(s)"}, "seconds": 0.016, "warnings": []}, {"algorithm": "planx:facilityadequacy", "choices": {"CAPACITY_FIELD": "hint:capacity@facilities", "DEMAND": "name:DEMAND->demand", "FACILITIES": "name:FACILITIES->facilities", "FACILITY_ID": "hint:facility_id@facilities", "FCA_DECAY": "default:1", "MAX_COST": "default:500", "NETWORK": "name:NETWORK->network", "OUT_DEMAND": "destination", "OUT_FACILITIES": "destination", "POP_FIELD": "hint:pop@demand"}, "display_name": "Facility Adequacy (Capacity + Distance)", "error": "", "extra_info": {}, "info": ["Covered population: 10965 of 10965 (100.0%); 3 facility(ies) overloaded.", "Results: {'OUT_DEMAND': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\facilityadequacy\\\\facilityadequacy_OUT_DEMAND.gpkg', 'OUT_FACILITIES': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\facilityadequacy\\\\facilityadequacy_OUT_FACILITIES.gpkg'}"], "ok": true, "outputs": {"OUT_DEMAND": "34 feature(s)", "OUT_FACILITIES": "7 feature(s)"}, "seconds": 0.044, "warnings": []}, {"algorithm": "planx:scenariosnapshot", "choices": {"ACCESS": "override:art:planx:accessscore/OUTPUT", "BALANCE": "override:art:planx:landusebalance/OUTPUT", "DEMAND": "override:art:planx:facilityadequacy/OUT_DEMAND", "DENSITY": "override:art:planx:densitygrid/OUTPUT", "FACILITIES": "override:art:planx:facilityadequacy/OUT_FACILITIES", "NAME": "default:'Scenario A'", "OUTPUT_JSON": "destination", "OUT_METRICS": "destination"}, "display_name": "Scenario Snapshot", "error": "", "extra_info": {"scene_b": ["Reading access: accessscore_OUTPUT; balance: landusebalance_OUTPUT; facilities: facilityadequacy_OUT_FACILITIES; demand: facilityadequacy_OUT_DEMAND; density: densitygrid_OUTPUT", "Plan Performance Index 84.0 - snapshot 'Scenario B' with 19 metrics: C:\\Users\\YE\\AppData\\Local\\Temp\\planx_matrix_7qkk4jei\\outputs\\scenariosnapshot\\extra_scene_b\\scenariosnapshot_OUTPUT_JSON.json", "Results: {'OUTPUT_JSON': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\scenariosnapshot\\\\extra_scene_b\\\\scenariosnapshot_OUTPUT_JSON.json', 'OUT_METRICS': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\scenariosnapshot\\\\scenariosnapshot_OUT_METRICS.gpkg'}"]}, "info": ["Reading access: accessscore_OUTPUT; balance: landusebalance_OUTPUT; facilities: facilityadequacy_OUT_FACILITIES; demand: facilityadequacy_OUT_DEMAND; density: densitygrid_OUTPUT", "Plan Performance Index 100.0 - snapshot 'Scenario A' with 19 metrics: C:\\Users\\YE\\AppData\\Local\\Temp\\planx_matrix_7qkk4jei\\outputs\\scenariosnapshot\\scenariosnapshot_OUTPUT_JSON.json", "Results: {'OUTPUT_JSON': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\scenariosnapshot\\\\scenariosnapshot_OUTPUT_JSON.json', 'OUT_METRICS': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\scenariosnapshot\\\\scenariosnapshot_OUT_METRICS.gpkg'}"], "ok": true, "outputs": {"OUTPUT_JSON": "729 byte(s)", "OUT_METRICS": "19 feature(s)"}, "seconds": 0.105, "warnings": []}, {"algorithm": "planx:parkingdemand", "choices": {"CATEGORY_FIELD": "hint:category@landuse", "OUTPUT": "destination", "RATES": "default:'residential=unit:1.5, office=sqm:2.5, commercial=sqm:3.5, retail=sqm:3.0, restaurant=seat:0.2, assembly=seat:0.15, industrial=sqm:1.0, education=sqm:1.5, health=sqm:3.0'", "SIZE_FIELD": "hint:area_m2@landuse", "ZONES": "override:landuse"}, "display_name": "Parking Demand Estimator", "error": "", "extra_info": {}, "info": ["  commercial: 630.00 spaces", "  green: 0.00 spaces", "  residential: 337500.00 spaces", "  school: 0.00 spaces", "Parking demand: 338130.00 spaces over 25 zone(s), 4 category/ies", "Matched no rate row, so demand 0 (a coverage gap in the rate table, not a real zero): green, school", "Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\parkingdemand\\\\parkingdemand_OUTPUT.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "25 feature(s)"}, "seconds": 0.02, "warnings": []}, {"algorithm": "planx:accessequity", "choices": {"DIRECTION": "default:0", "GROUP_FIELD": "hint:category@demand", "INPUT": "override:demand", "OUT_POINTS": "destination", "OUT_SUMMARY": "destination", "POP_FIELD": "hint:pop@demand", "POVERTY": "default:0", "VALUE_FIELD": "hint:value@demand"}, "display_name": "Accessibility Equity (Gini / Theil)", "error": "", "extra_info": {}, "info": ["Population 10965 over 34 units. Mean value 385.842.", "Gini 0.160  |  Theil T 0.051  |  P90/P10 2.39  |  CV 0.295", "Theil split: 0.000 between groups (0 percent of total) + 0.051 within groups.", "Access poverty (value below 0): 0.0 percent of the population.", "Results: {'OUT_POINTS': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\accessequity\\\\accessequity_OUT_POINTS.gpkg', 'OUT_SUMMARY': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\accessequity\\\\accessequity_OUT_SUMMARY.gpkg'}"], "ok": true, "outputs": {"OUT_POINTS": "34 feature(s)", "OUT_SUMMARY": "2 feature(s)"}, "seconds": 0.034, "warnings": []}, {"algorithm": "planx:airscreen", "choices": {"ALPHA": "default:1", "BUILDINGS": "name:BUILDINGS->buildings", "CANYON_BUFFER": "default:15", "CANYON_SEARCH": "default:30", "CANYON_WIDTH": "default:20", "CELL": "default:10", "CUTOFF": "default:300", "DEFAULT_HEIGHT": "default:10", "EMISSION_FIELD": "hint:emission@network", "EXTENT": "skipped(optional)", "HEIGHT_FIELD": "hint:height@buildings", "OUTPUT": "destination", "OUT_RECEIVERS": "destination", "POP_FIELD": "hint:pop@demand", "RECEIVERS": "name:RECEIVERS->demand", "ROADS": "name:ROADS->network", "WIND_SPEED": "default:2"}, "display_name": "Air Quality Screening", "error": "", "extra_info": {}, "info": ["1005 source samples (every ~10 map units).", "Checking canyon effect with 70 building(s).", "Grid levels: mean 15.33, max 108.81.", "Receivers: 9594 people at >= 20 index, 0 at >= 50 index (of 10965).", "Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\airscreen\\\\airscreen_OUTPUT.gpkg', 'OUT_RECEIVERS': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\airscreen\\\\airscreen_OUT_RECEIVERS.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "18225/18225 populated pixel(s)", "OUT_RECEIVERS": "34 feature(s)"}, "seconds": 0.503, "warnings": []}, {"algorithm": "planx:annualsolar", "choices": {"DSM": "name:DSM->dsm", "EPW": "skipped(optional)", "INTERVAL": "default:60", "MAX_SEARCH": "default:0", "OUTPUT": "destination", "OUTPUT_MONTHLY": "destination", "SVF_RADIUS": "default:100", "USE_SVF": "default:True", "UTC_OFFSET": "default:0", "YEAR": "default:2026"}, "display_name": "Annual Solar Potential (DSM)", "error": "", "extra_info": {}, "info": ["Site 0.0034N 0.0034E | year 2026 | 12 monthly average-day sweeps every 60 min", "Sky view factor pass...", "Annual irradiation sweep (12 months)...", "Flat-ground clear-sky annual reference 2714 kWh/m2/yr | scene mean 2390, min 469, max 2714", "Scene monthly means (kWh/m2): Jan 205 Feb 197 Mar 225 Apr 202 May 188 Jun 171 Jul 180 Aug 196 Sep 208 Oct 217 Nov 200 Dec 200", "Peak month: March (225 kWh/m2)", "Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\annualsolar\\\\annualsolar_OUTPUT.gpkg', 'OUTPUT_MONTHLY': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\annualsolar\\\\annualsolar_OUTPUT_MONTHLY.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "140625/140625 populated pixel(s)", "OUTPUT_MONTHLY": "140625/140625 populated pixel(s)"}, "seconds": 6.394, "warnings": []}, {"algorithm": "planx:buildingmetrics", "choices": {"BUILDINGS": "name:BUILDINGS->buildings", "OUTPUT": "destination"}, "display_name": "Building Form Metrics", "error": "", "extra_info": {}, "info": ["Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\buildingmetrics\\\\buildingmetrics_OUTPUT.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "70 feature(s)"}, "seconds": 0.032, "warnings": []}, {"algorithm": "planx:capacitatedallocation", "choices": {"CAPACITY_FIELD": "hint:capacity@facilities", "DEMAND": "name:DEMAND->demand", "FACILITIES": "name:FACILITIES->facilities", "FACILITY_ID": "hint:facility_id@facilities", "MAX_COST": "default:500", "NETWORK": "name:NETWORK->network", "OUT_DEMAND": "destination", "OUT_FACILITIES": "destination", "POP_FIELD": "hint:pop@demand"}, "display_name": "Capacitated Allocation (Nearest with Capacity)", "error": "", "extra_info": {}, "info": ["Computing network distances: 7 facilities x 34 demand points (catchment 500)...", "Covered population: 4994 of 10965 (45.5%); 5 spilled to a farther facility, 15 point(s) uncovered (no facility with room in reach).", "Results: {'OUT_DEMAND': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\capacitatedallocation\\\\capacitatedallocation_OUT_DEMAND.gpkg', 'OUT_FACILITIES': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\capacitatedallocation\\\\capacitatedallocation_OUT_FACILITIES.gpkg'}"], "ok": true, "outputs": {"OUT_DEMAND": "34 feature(s)", "OUT_FACILITIES": "7 feature(s)"}, "seconds": 0.047, "warnings": []}, {"algorithm": "planx:capacitatedsiting", "choices": {"CANDIDATES": "name:CANDIDATES->facilities", "CANDIDATE_ID": "hint:facility_id@facilities", "CAPACITY_FIELD": "hint:capacity@facilities", "COST_FIELD": "hint:cost@network", "DEMAND": "name:DEMAND->demand", "EXISTING": "name:EXISTING->facilities", "EXISTING_CAP_FIELD": "hint:capacity@facilities", "EXISTING_ID": "hint:facility_id@facilities", "MAX_COST": "default:500", "NETWORK": "name:NETWORK->network", "OUT_ALLOCATION": "destination", "OUT_SITES": "destination", "OUT_UNCOVERED": "destination", "P": "default:3", "POP_FIELD": "hint:pop@demand"}, "display_name": "Capacitated Facility Siting", "error": "", "extra_info": {}, "info": ["Computing network distances: 14 sites x 34 demand points (catchment 500)...", "Coverage: 7500 of 10965 (68.4%); mean cost: 201.92; capacity slack: 1500.", "Results: {'OUT_ALLOCATION': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\capacitatedsiting\\\\capacitatedsiting_OUT_ALLOCATION.gpkg', 'OUT_SITES': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\capacitatedsiting\\\\capacitatedsiting_OUT_SITES.gpkg', 'OUT_UNCOVERED': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\capacitatedsiting\\\\capacitatedsiting_OUT_UNCOVERED.gpkg'}"], "ok": true, "outputs": {"OUT_ALLOCATION": "26 feature(s)", "OUT_SITES": "3 feature(s)", "OUT_UNCOVERED": "8 feature(s)"}, "seconds": 0.065, "warnings": []}, {"algorithm": "planx:cyclingstress", "choices": {"AADT_FIELD": "hint:aadt@network", "DEFAULT_AADT": "default:0", "DEFAULT_INFRA": "default:'mixed'", "DEFAULT_LANES": "default:2", "DEFAULT_SPEED": "default:50", "INFRA_FIELD": "hint:infra@network", "LANES_FIELD": "hint:lanes@network", "NETWORK": "name:NETWORK->network", "OUTPUT": "destination", "RULES": "default:'path_lts=1, lane_lts2_speed=50, lane_lts2_lanes=3, lane_lts_low=2, lane_lts_high=3, mixed_lts1_speed=30, mixed_lts1_lanes=2, mixed_lts1_aadt=1000, mixed_lts2_speed=30, mixed_lts2_lanes=2, mixed_lts3_speed=50'", "SPEED_FIELD": "hint:speed@network", "SUMMARY": "destination"}, "display_name": "Cycling Stress (LTS)", "error": "", "extra_info": {}, "info": ["65 segment(s) classified; 0.0 percent of network length is LTS 1-2.", "Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\cyclingstress\\\\cyclingstress_OUTPUT.gpkg', 'SUMMARY': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\cyclingstress\\\\cyclingstress_SUMMARY.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "65 feature(s)", "SUMMARY": "4 feature(s)"}, "seconds": 0.038, "warnings": []}, {"algorithm": "planx:democity", "choices": {}, "display_name": "Generate Demo City", "error": "", "extra_info": {}, "info": [], "ok": true, "outputs": {"OUTPUT_BUILDINGS": "70 feature(s)", "OUTPUT_DEMAND": "34 feature(s)", "OUTPUT_DSM": "140625/140625 populated pixel(s)", "OUTPUT_FACILITIES": "7 feature(s)", "OUTPUT_GREEN": "5 feature(s)", "OUTPUT_LANDUSE": "25 feature(s)", "OUTPUT_POIS": "16 feature(s)", "OUTPUT_STREETS": "65 feature(s)"}, "seconds": 0.053, "warnings": []}, {"algorithm": "planx:equitycrosstab", "choices": {"BREAKS": "skipped(optional)", "GROUP_FIELD": "hint:category@demand", "GROUP_FIELD_B": "hint:category@demand", "INPUT": "override:demand", "N_CLASSES": "default:5", "OUT_CELLS": "destination", "OUT_GROUPS": "destination", "OUT_UNITS": "destination", "POP_FIELD": "hint:pop@demand", "VALUE_FIELD": "hint:value@demand"}, "display_name": "Demographic Equity Cross-Tabs", "error": "", "extra_info": {}, "info": ["34 units in 1 group(s) across 5 value classes (population 10965).", "Most over-represented in the lowest class 'Q1 (lowest)': all | all (ratio 1.00); least: all | all (ratio 1.00).", "Highest dissimilarity vs the rest: all | all (0.000).", "Results: {'OUT_CELLS': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\equitycrosstab\\\\equitycrosstab_OUT_CELLS.gpkg', 'OUT_GROUPS': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\equitycrosstab\\\\equitycrosstab_OUT_GROUPS.gpkg', 'OUT_UNITS': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\equitycrosstab\\\\equitycrosstab_OUT_UNITS.gpkg'}"], "ok": true, "outputs": {"OUT_CELLS": "5 feature(s)", "OUT_GROUPS": "1 feature(s)", "OUT_UNITS": "34 feature(s)"}, "seconds": 0.059, "warnings": []}, {"algorithm": "planx:facilitylocation", "choices": {"BUDGET": "default:0", "CANDIDATES": "name:CANDIDATES->facilities", "CANDIDATE_ID": "hint:facility_id@facilities", "DEMAND": "name:DEMAND->demand", "EXACT_AUDIT": "default:True", "EXISTING": "name:EXISTING->facilities", "METHOD": "default:0", "NETWORK": "name:NETWORK->network", "OUT_ASSIGN": "destination", "OUT_SITES": "destination", "P": "default:3", "POP_FIELD": "hint:pop@demand", "RADIUS": "default:500", "SITE_COST": "hint:site_cost@facilities"}, "display_name": "Facility Location Optimizer (Coverage / P-Median)", "error": "", "extra_info": {}, "info": ["Computing network distances: 14 sites x 34 demand points...", "Covered demand: 10965 of 10965 (100.0 percent) within 500.", "Exact audit: 64 combinations, optimum 10965, heuristic gap 0.000 percent.", "Results: {'OUT_ASSIGN': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\facilitylocation\\\\facilitylocation_OUT_ASSIGN.gpkg', 'OUT_SITES': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\facilitylocation\\\\facilitylocation_OUT_SITES.gpkg'}"], "ok": true, "outputs": {"OUT_ASSIGN": "34 feature(s)", "OUT_SITES": "7 feature(s)"}, "seconds": 0.04, "warnings": []}, {"algorithm": "planx:floodexposure", "choices": {"BUILDINGS": "name:BUILDINGS->buildings", "DEMAND": "name:DEMAND->demand", "INUNDATION": "name:INUNDATION->inundation", "OUTPUT": "destination", "OUT_DEMAND": "destination", "POP_FIELD": "hint:pop@demand"}, "display_name": "Flood Exposure", "error": "", "extra_info": {}, "info": ["Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\floodexposure\\\\floodexposure_OUTPUT.gpkg', 'OUT_DEMAND': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\floodexposure\\\\floodexposure_OUT_DEMAND.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "1 feature(s)", "OUT_DEMAND": "34 feature(s)"}, "seconds": 0.035, "warnings": []}, {"algorithm": "planx:frontalarea", "choices": {"BUILDINGS": "name:BUILDINGS->buildings", "CELL_SIZE": "default:100", "DEFAULT_HEIGHT": "default:6", "HEIGHT_FIELD": "hint:height@buildings", "OUTPUT": "destination", "WIND_DIR": "default:0"}, "display_name": "Frontal Area Index", "error": "", "extra_info": {}, "info": ["70 buildings; grid 8 x 8 cells of 100", "Wrote 56 built grid cells.", "Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\frontalarea\\\\frontalarea_OUTPUT.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "56 feature(s)"}, "seconds": 0.022, "warnings": []}, {"algorithm": "planx:gravitymodel", "choices": {"ATTRACTION_FIELD": "hint:attraction@demand", "BETA": "default:0.1", "COST_FIELD": "hint:cost@network", "KIND": "default:0", "LINES": "destination", "MAX_ITER": "default:100", "NETWORK": "name:NETWORK->network", "OUTPUT": "destination", "PRODUCTION_FIELD": "hint:production@demand", "TOL": "default:0.0001", "ZONES": "name:ZONES->demand", "ZONE_ID": "hint:zone_id@demand"}, "display_name": "Gravity Distribution", "error": "", "extra_info": {}, "info": ["Graph: 36 nodes / 65 edges", "Gravity balancing: 100 iterations, max error: 0.001014", "Top 10 travel demand flows:", "  1. 4 -> 6: flow=313.67, cost=0.00", "  2. 6 -> 4: flow=313.67, cost=0.00", "  3. 5 -> 7: flow=299.25, cost=0.00", "  4. 7 -> 5: flow=299.25, cost=0.00", "  5. 15 -> 20: flow=249.86, cost=0.00", "  6. 20 -> 15: flow=249.86, cost=0.00", "  7. 8 -> 12: flow=230.84, cost=0.00", "  8. 12 -> 8: flow=230.84, cost=0.00", "  9. 9 -> 13: flow=200.70, cost=0.00", "  10. 13 -> 9: flow=200.70, cost=0.00", "Results: {'LINES': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\gravitymodel\\\\gravitymodel_LINES.gpkg', 'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\gravitymodel\\\\gravitymodel_OUTPUT.gpkg'}"], "ok": true, "outputs": {"LINES": "1122 feature(s)", "OUTPUT": "1122 feature(s)"}, "seconds": 0.056, "warnings": []}, {"algorithm": "planx:greenaccess", "choices": {"DEMAND": "name:DEMAND->demand", "GREENS": "name:GREENS->green", "HIERARCHY": "default:'0.5=300, 2=800, 10=2000'", "NETWORK": "name:NETWORK->network", "OUT_DEMAND": "destination", "OUT_SUMMARY": "destination", "POP_FIELD": "hint:pop@demand"}, "display_name": "Green Space Access", "error": "", "extra_info": {}, "info": ["5 greens against 3 classes for 34 demand points.", "Class 1 (0.5 ha within 300): 43.8 percent covered.", "Class 2 (2 ha within 800): 100.0 percent covered.", "Class 3 (10 ha within 2000): 0.0 percent covered.", "Citywide green provision: 10.3 m2 per capita.", "Results: {'OUT_DEMAND': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\greenaccess\\\\greenaccess_OUT_DEMAND.gpkg', 'OUT_SUMMARY': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\greenaccess\\\\greenaccess_OUT_SUMMARY.gpkg'}"], "ok": true, "outputs": {"OUT_DEMAND": "34 feature(s)", "OUT_SUMMARY": "3 feature(s)"}, "seconds": 0.038, "warnings": ["No green space reaches 10 ha - that class covers nobody."]}, {"algorithm": "planx:greenconnectivity", "choices": {"GREENS": "name:GREENS->green", "MAX_GAP": "default:100", "OUT_PATCHES": "destination", "OUT_SUMMARY": "destination"}, "display_name": "Urban Green Connectivity", "error": "", "extra_info": {}, "info": ["5 patches, 1 links within 100 map units.", "4 component(s); PC index 0.2800; most critical patch loses 42.9 percent of PC if removed.", "Results: {'OUT_PATCHES': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\greenconnectivity\\\\greenconnectivity_OUT_PATCHES.gpkg', 'OUT_SUMMARY': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\greenconnectivity\\\\greenconnectivity_OUT_SUMMARY.gpkg'}"], "ok": true, "outputs": {"OUT_PATCHES": "5 feature(s)", "OUT_SUMMARY": "6 feature(s)"}, "seconds": 0.031, "warnings": []}, {"algorithm": "planx:growthsim", "choices": {"BASE": "default:0.1", "CONSTRAINTS": "name:CONSTRAINTS->constraints", "DEMAND_HA": "default:50", "ITERATIONS": "default:5", "NEIGH_WEIGHT": "default:1", "OUTPUT": "destination", "RNG_SEED": "default:0", "SEED": "name:SEED->seed", "SUITABILITY": "name:SUITABILITY->suitability"}, "display_name": "Urban Growth Simulation (CA)", "error": "", "extra_info": {}, "info": ["Seed fabric 14.0 ha; demand 50 ha = 125000 cells over 5 step(s); weight 1, base 0.1, seed 0.", "Step 1: 25000 cell(s) converted (10.00 ha).", "Step 2: 25000 cell(s) converted (10.00 ha).", "Step 3: 25000 cell(s) converted (10.00 ha).", "Step 4: 25000 cell(s) converted (10.00 ha).", "Step 5: 5633 cell(s) converted (2.25 ha).", "Final urban fabric 56.2 ha (+42.3 ha).", "Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\growthsim\\\\growthsim_OUTPUT.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "140625/140625 populated pixel(s)"}, "seconds": 0.055, "warnings": ["Demand of 125000 cells exceeds the 105633 open cells - the growth will saturate."]}, {"algorithm": "planx:gtfsimport", "choices": {"DAY": "skipped(optional)", "FILE": "override:fixture:gtfs", "OUT_ROUTES": "destination", "OUT_STOPS": "destination"}, "display_name": "GTFS Import and Service Stats", "error": "", "extra_info": {}, "info": ["No date given - using the feed's first service day: 20260101.", "Feed OK: 8 stops, 1 route(s) running on 20260101 (1 service pattern(s), 1 trips).", "Results: {'OUT_ROUTES': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\gtfsimport\\\\gtfsimport_OUT_ROUTES.gpkg', 'OUT_STOPS': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\gtfsimport\\\\gtfsimport_OUT_STOPS.gpkg'}"], "ok": true, "outputs": {"OUT_ROUTES": "1 feature(s)", "OUT_STOPS": "8 feature(s)"}, "seconds": 0.044, "warnings": []}, {"algorithm": "planx:handindex", "choices": {"ACCUM": "override:art:planx:flowaccumulation/OUTPUT_ACCUM", "D8_DIR": "override:art:planx:flowaccumulation/OUTPUT_DIR", "DEM": "name:DEM->dem", "DEPTH": "default:1", "OUTPUT_HAND": "destination", "OUTPUT_INUNDATION": "destination", "THRESHOLD": "default:100"}, "display_name": "HAND and Inundation", "error": "", "extra_info": {}, "info": ["Results: {'OUTPUT_HAND': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\handindex\\\\handindex_OUTPUT_HAND.gpkg', 'OUTPUT_INUNDATION': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\handindex\\\\handindex_OUTPUT_INUNDATION.gpkg'}"], "ok": true, "outputs": {"OUTPUT_HAND": "140625/140625 populated pixel(s)", "OUTPUT_INUNDATION": "140625/140625 populated pixel(s)"}, "seconds": 0.295, "warnings": []}, {"algorithm": "planx:heatriskgrid", "choices": {"BUILDINGS": "name:BUILDINGS->buildings", "CELL_SIZE": "default:100", "GREEN": "override:green", "HEIGHT_FIELD": "hint:height@buildings", "H_REF": "default:20", "OUTPUT": "destination", "WATER": "skipped(optional)", "W_BUILT": "default:0.4", "W_GREEN": "default:0.3", "W_HEIGHT": "default:0.2", "W_WATER": "default:0.1"}, "display_name": "Heat Island Risk Grid", "error": "", "extra_info": {}, "info": ["70 buildings, 5 green, 0 water polygons; grid 8 x 8 cells of 100", "63 cells | mean risk 57.9 | Very High share 20.6%", "Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\heatriskgrid\\\\heatriskgrid_OUTPUT.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "63 feature(s)"}, "seconds": 0.032, "warnings": []}, {"algorithm": "planx:housingneeds", "choices": {"BACKLOG": "default:0", "EXISTING": "default:3500", "HH_SIZE": "default:2.5", "OUT_SUMMARY": "destination", "POP_FUTURE": "default:10000", "REPLACEMENT": "default:0", "VACANCY": "default:0.05"}, "display_name": "Housing Needs Assessment", "error": "", "extra_info": {}, "info": ["4,000 households -> target stock 4,200; 700 dwelling(s) to deliver.", "Results: {'OUT_SUMMARY': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\housingneeds\\\\housingneeds_OUT_SUMMARY.gpkg'}"], "ok": true, "outputs": {"OUT_SUMMARY": "9 feature(s)"}, "seconds": 0.014, "warnings": []}, {"algorithm": "planx:inequalitycurves", "choices": {"EPSILON": "default:1", "INPUT": "override:demand", "OUT_CURVE": "destination", "OUT_SUMMARY": "destination", "POP_FIELD": "hint:pop@demand", "RANK_FIELD": "hint:rank@demand", "VALUE_FIELD": "hint:value@demand"}, "display_name": "Inequality Curves (Lorenz & Atkinson)", "error": "", "extra_info": {}, "info": ["Concentration curve over 34 units, population 10965, mean value 385.842.", "Gini 0.1603  |  Atkinson(0.5) 0.0282  |  Atkinson(1) 0.0634  |  Atkinson(2) 0.1642", "Concentration index -0.0109: the value leans toward the disadvantaged (low-rank) end of the ranking.", "Results: {'OUT_CURVE': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\inequalitycurves\\\\inequalitycurves_OUT_CURVE.gpkg', 'OUT_SUMMARY': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\inequalitycurves\\\\inequalitycurves_OUT_SUMMARY.gpkg'}"], "ok": true, "outputs": {"OUT_CURVE": "35 feature(s)", "OUT_SUMMARY": "8 feature(s)"}, "seconds": 0.03, "warnings": []}, {"algorithm": "planx:isovistfield", "choices": {"BUILDINGS": "name:BUILDINGS->buildings", "CELL": "default:10", "EXTENT": "skipped(optional)", "MAX_DIST": "default:200", "N_RAYS": "default:180", "OUT_POINTS": "destination"}, "display_name": "Isovist Field", "error": "", "extra_info": {}, "info": ["Obstacle grid 72 x 72 at 10; 70 buildings; 180 rays up to 200.", "3434 isovist points; mean visible area 29,527, mean occlusivity 0.75.", "Results: {'OUT_POINTS': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\isovistfield\\\\isovistfield_OUT_POINTS.gpkg'}"], "ok": true, "outputs": {"OUT_POINTS": "3434 feature(s)"}, "seconds": 6.681, "warnings": []}, {"algorithm": "planx:landallocation", "choices": {"ADJACENCY": "skipped(optional)", "AREA_FIELD": "hint:area_m2@parcels", "CONTIGUITY": "default:0", "LOCK_FIELD": "hint:lock@parcels", "OUT_PARCELS": "destination", "OUT_SUMMARY": "destination", "PARCELS": "name:PARCELS->parcels", "SUIT_FIELDS": "list:s_residential,s_commercial,s_green@parcels", "TARGETS": "default:'s_residential=50000, s_commercial=20000, s_green=30000'", "W_COMPACT": "default:0", "W_SUITABILITY": "default:1"}, "display_name": "Land-Use Allocation Optimizer", "error": "", "extra_info": {}, "info": ["Allocating 25 parcels to 3 use(s)...", "Allocated 67500 of 100000 target area (67.5 percent); 22 parcel(s) left over.", "Suitability score 57375 (area-weighted mean 0.850); 0 reassignment(s), 0 swap(s).", "Results: {'OUT_PARCELS': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\landallocation\\\\landallocation_OUT_PARCELS.gpkg', 'OUT_SUMMARY': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\landallocation\\\\landallocation_OUT_SUMMARY.gpkg'}"], "ok": true, "outputs": {"OUT_PARCELS": "25 feature(s)", "OUT_SUMMARY": "4 feature(s)"}, "seconds": 0.034, "warnings": ["25 lock value(s) did not match any suitability field name - those parcels were left free."]}, {"algorithm": "planx:landcoverchange", "choices": {"CLASS_NAMES": "skipped(optional)", "OUT_CLASSES": "destination", "OUT_MATRIX": "destination", "RASTER_T1": "name:RASTER_T1->landcover_t1", "RASTER_T2": "name:RASTER_T2->landcover_t2"}, "display_name": "Land-Cover Change Analysis", "error": "", "extra_info": {}, "info": ["2 classes over 140625 shared cells.", "Largest conversion: 3 -> 4 (41.96 ha).", "Results: {'OUT_CLASSES': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\landcoverchange\\\\landcoverchange_OUT_CLASSES.gpkg', 'OUT_MATRIX': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\landcoverchange\\\\landcoverchange_OUT_MATRIX.gpkg'}"], "ok": true, "outputs": {"OUT_CLASSES": "2 feature(s)", "OUT_MATRIX": "2 feature(s)"}, "seconds": 0.049, "warnings": []}, {"algorithm": "planx:linkcriticality", "choices": {"COST_FIELD": "hint:cost@network", "CRITICAL": "destination", "CUTOFF": "default:0", "DESTINATIONS": "name:DESTINATIONS->pois", "NETWORK": "name:NETWORK->network", "ORIGINS": "name:ORIGINS->demand"}, "display_name": "Link Criticality (Network Robustness)", "error": "", "extra_info": {}, "info": ["Graph: 36 nodes / 65 edges (SciPy fast path: yes)", "OD demand: 544/544 pairs reachable; baseline cost total 269380.8; candidate segments tested: 64", "Results: {'CRITICAL': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\linkcriticality\\\\linkcriticality_CRITICAL.gpkg'}"], "ok": true, "outputs": {"CRITICAL": "65 feature(s)"}, "seconds": 0.035, "warnings": []}, {"algorithm": "planx:lowstressislands", "choices": {"DESTINATIONS": "name:DESTINATIONS->pois", "LTS_FIELD": "hint:lts@network", "NETWORK": "name:NETWORK->network", "ORIGINS": "name:ORIGINS->demand", "OUTPUT": "destination", "POP_FIELD": "hint:pop@demand", "SUMMARY": "destination", "THRESHOLD": "default:2"}, "display_name": "Low-Stress Connectivity", "error": "", "extra_info": {}, "info": ["5 low-stress island(s); 51.1 percent of network length is LTS 2 or lower.", "9548 of 10965 population reaches a destination island at the chosen threshold.", "Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\lowstressislands\\\\lowstressislands_OUTPUT.gpkg', 'SUMMARY': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\lowstressislands\\\\lowstressislands_SUMMARY.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "65 feature(s)", "SUMMARY": "10 feature(s)"}, "seconds": 0.036, "warnings": []}, {"algorithm": "planx:modesplit", "choices": {"FLOWS": "name:FLOWS->flows", "FLOW_FIELD": "hint:flow@flows", "MODE_ASCS": "default:'0.0,0.0'", "MODE_BETAS": "default:'-0.1,-0.1'", "MODE_NAMES": "default:'car,transit'", "MODE_TIMES": "default:'time_car,time_transit'", "OBSERVED_SHARES": "skipped(optional)", "OUTPUT": "destination"}, "display_name": "Mode Split", "error": "", "extra_info": {}, "info": ["Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\modesplit\\\\modesplit_OUTPUT.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "65 feature(s)"}, "seconds": 0.022, "warnings": []}, {"algorithm": "planx:nearestfacility", "choices": {"COST_FIELD": "hint:cost@network", "CUTOFF": "default:0", "DEMAND": "name:DEMAND->demand", "FACILITIES": "name:FACILITIES->facilities", "FACILITY_ID": "hint:facility_id@facilities", "NETWORK": "name:NETWORK->network", "OUTPUT": "destination", "ROUTES": "destination", "SPIDER": "destination", "SUMMARY": "destination"}, "display_name": "Nearest Facility Allocation", "error": "", "extra_info": {}, "info": ["Created 30 allocation route(s).", "Allocated 34 of 34 demand points.", "Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\nearestfacility\\\\nearestfacility_OUTPUT.gpkg', 'ROUTES': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\nearestfacility\\\\nearestfacility_ROUTES.gpkg', 'SPIDER': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\nearestfacility\\\\nearestfacility_SPIDER.gpkg', 'SUMMARY': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\nearestfacility\\\\nearestfacility_SUMMARY.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "34 feature(s)", "ROUTES": "30 feature(s)", "SPIDER": "34 feature(s)", "SUMMARY": "7 feature(s)"}, "seconds": 0.071, "warnings": []}, {"algorithm": "planx:networkcentrality", "choices": {"COST_FIELD": "hint:cost@network", "EDGES": "destination", "NETWORK": "name:NETWORK->network", "NODES": "destination", "RADIUS": "default:0", "SAMPLES": "default:0"}, "display_name": "Network Centrality", "error": "", "extra_info": {}, "info": ["Graph: 36 nodes / 65 edges", "Closeness / straightness pass...", "Betweenness pass (Brandes)...", "Eigenvector pass (power iteration)...", "Results: {'EDGES': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\networkcentrality\\\\networkcentrality_EDGES.gpkg', 'NODES': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\networkcentrality\\\\networkcentrality_NODES.gpkg'}"], "ok": true, "outputs": {"EDGES": "65 feature(s)", "NODES": "36 feature(s)"}, "seconds": 0.05, "warnings": []}, {"algorithm": "planx:noisescreen", "choices": {"BUILDINGS": "name:BUILDINGS->buildings", "CELL": "default:10", "CUTOFF": "default:300", "EXTENT": "skipped(optional)", "HEAVY_FIELD": "hint:heavy@network", "HEAVY_PCT": "default:5", "HOURLY_FACTOR": "default:1", "OUTPUT": "destination", "OUT_RECEIVERS": "destination", "POP_FIELD": "hint:pop@demand", "RECEIVERS": "name:RECEIVERS->demand", "ROADS": "name:ROADS->network", "SCREEN_DB": "default:10", "VOLUME_FIELD": "hint:volume@network"}, "display_name": "Road Noise Screening", "error": "", "extra_info": {}, "info": ["1005 road samples (every ~10 map units).", "Screening against 70 building(s), insertion loss 10 dB.", "Grid levels: mean 62.7, max 81.9 dB(A).", "Receivers: 10965 people at >= 55 dB, 0 at >= 65 dB (of 10965).", "Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\noisescreen\\\\noisescreen_OUTPUT.gpkg', 'OUT_RECEIVERS': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\noisescreen\\\\noisescreen_OUT_RECEIVERS.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "17413/18225 populated pixel(s)", "OUT_RECEIVERS": "34 feature(s)"}, "seconds": 17.534, "warnings": []}, {"algorithm": "planx:odmatrix", "choices": {"COST_FIELD": "hint:cost@network", "CUTOFF": "default:0", "DESTINATIONS": "name:DESTINATIONS->pois", "DEST_ID": "hint:dest_id@pois", "LINES": "destination", "MATRIX": "destination", "NETWORK": "name:NETWORK->network", "ORIGINS": "name:ORIGINS->demand", "ORIGIN_ID": "hint:origin_id@demand"}, "display_name": "OD Cost Matrix", "error": "", "extra_info": {}, "info": ["Graph: 36 nodes / 65 edges (SciPy fast path: yes)", "Results: {'LINES': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\odmatrix\\\\odmatrix_LINES.gpkg', 'MATRIX': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\odmatrix\\\\odmatrix_MATRIX.gpkg'}"], "ok": true, "outputs": {"LINES": "544 feature(s)", "MATRIX": "544 feature(s)"}, "seconds": 0.05, "warnings": []}, {"algorithm": "planx:odroutes", "choices": {"COST_FIELD": "hint:cost@network", "CUTOFF": "default:0", "DESTINATIONS": "name:DESTINATIONS->pois", "DEST_ID": "hint:dest_id@pois", "K_NEAREST": "default:0", "NETWORK": "name:NETWORK->network", "ORIGINS": "name:ORIGINS->demand", "ORIGIN_ID": "hint:origin_id@demand", "OUT_LINES": "destination", "OUT_ROUTES": "destination"}, "display_name": "OD Routes (Shortest Paths)", "error": "", "extra_info": {}, "info": ["Graph: 36 nodes / 65 edges. Routing with embedded Dijkstra engine.", "Created 538 route(s).", "Created 538 desire line(s).", "Results: {'OUT_LINES': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\odroutes\\\\odroutes_OUT_LINES.gpkg', 'OUT_ROUTES': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\odroutes\\\\odroutes_OUT_ROUTES.gpkg'}"], "ok": true, "outputs": {"OUT_LINES": "538 feature(s)", "OUT_ROUTES": "538 feature(s)"}, "seconds": 0.075, "warnings": []}, {"algorithm": "planx:paretoallocation", "choices": {"AREA_FIELD": "hint:area_m2@parcels", "LOCK_FIELD": "hint:lock@parcels", "N_POINTS": "default:9", "OUT_FRONT": "destination", "OUT_PARCELS": "destination", "PARCELS": "name:PARCELS->parcels", "SOLUTION": "default:0", "SUIT_FIELDS": "list:s_residential,s_commercial,s_green@parcels", "TARGETS": "default:'s_residential=50000, s_commercial=20000, s_green=30000'", "W_MAX": "default:0", "W_SUITABILITY": "default:1"}, "display_name": "Land-Use Pareto Front", "error": "", "extra_info": {}, "info": ["Adjacency graph: 40 shared parcel boundaries (total length 6000).", "Sweeping 9 compactness weights from 0 to 57.375 over 25 parcels and 3 use(s)...", "Pareto front: 9 of 9 solutions are non-dominated.", "Suitability ranges 57375 to 57375; compactness 0 to 0 (shared same-use boundary).", "Exported the knee (best trade-off) solution (weight 0) as the parcel map.", "Results: {'OUT_FRONT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\paretoallocation\\\\paretoallocation_OUT_FRONT.gpkg', 'OUT_PARCELS': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\paretoallocation\\\\paretoallocation_OUT_PARCELS.gpkg'}"], "ok": true, "outputs": {"OUT_FRONT": "9 feature(s)", "OUT_PARCELS": "25 feature(s)"}, "seconds": 0.043, "warnings": ["25 lock value(s) did not match any suitability field name - those parcels were left free."]}, {"algorithm": "planx:parkingsupplybalance", "choices": {"DEMAND_FIELD": "hint:parking_demand@art:planx:parkingdemand/OUTPUT", "NETWORK": "name:NETWORK->network", "OUTPUT": "destination", "RADIUS": "default:300", "SUPPLY": "override:facilities", "SUPPLY_FIELD": "hint:capacity@facilities", "ZONES": "override:art:planx:parkingdemand/OUTPUT"}, "display_name": "Parking Supply-Demand Balance", "error": "", "extra_info": {}, "info": ["Measuring access in EPSG:3857.", "Network reach: 65 street segments, 36 nodes, radius 300.", "  parking demand (all zones, spaces): 338,130", "  parking supply (surveyed zones, spaces): 12,000", "  surplus (+) or deficit (-), surveyed zones, spaces: -326,130", "  surveyed zones in deficit: 12", "  zones counted: 13", "  zones zero supply found: 12", "Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\parkingsupplybalance\\\\parkingsupplybalance_OUTPUT.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "25 feature(s)"}, "seconds": 0.048, "warnings": []}, {"algorithm": "planx:performancereport", "choices": {"ACCESS": "override:art:planx:accessscore/OUTPUT", "ACCESS_SCORE": "hint:score@art:planx:accessscore/OUTPUT", "BALANCE": "override:art:planx:landusebalance/OUTPUT", "DEMAND": "override:art:planx:facilityadequacy/OUT_DEMAND", "DEMAND_POP": "hint:pop@art:planx:facilityadequacy/OUT_DEMAND", "DENSITY": "override:art:planx:densitygrid/OUTPUT", "DENSITY_FIELD": "hint:dens_ha@art:planx:densitygrid/OUTPUT", "FACILITIES": "override:art:planx:facilityadequacy/OUT_FACILITIES", "OUTPUT": "destination", "POPULATION": "default:0", "TITLE": "default:'Urban Plan'"}, "display_name": "Plan Dashboard & Performance Report (HTML)", "error": "", "extra_info": {}, "info": ["Access scores: 34 origins.", "Land-use balance: 4 categories.", "Facility adequacy: 7 facilities, 34 demand points.", "Density grid: 26 cells.", "  Plan Performance Index: 100 (mean of available components (0-100))", "  Accessibility Score: 100 (34 origins - 100% reach every category)", "  Standards Compliance: 100% (2 categories with a standard)", "  Population Covered: 100% (7 facilities - 3 overloaded)", "Report written to C:\\Users\\YE\\AppData\\Local\\Temp\\planx_matrix_7qkk4jei\\outputs\\performancereport\\performancereport_OUTPUT.gpkg", "Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\performancereport\\\\performancereport_OUTPUT.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "10651 byte(s)"}, "seconds": 0.083, "warnings": []}, {"algorithm": "planx:planaudit", "choices": {"AMENITIES": "multi:pois,facilities,green", "CAPACITY_FIELD": "hint:capacity@facilities", "CATEGORY_FIELD": "hint:category@landuse", "DEMAND": "name:DEMAND->demand", "FACILITIES": "name:FACILITIES->facilities", "FACILITY_ID": "hint:facility_id@facilities", "GREENS": "name:GREENS->green", "HIERARCHY": "default:'0.5=300, 2=800'", "LANDUSE": "name:LANDUSE->landuse", "MAX_COST": "default:500", "NAME": "default:'Plan'", "NETWORK": "name:NETWORK->network", "OUTPUT_HTML": "destination", "OUTPUT_JSON": "destination", "OUT_METRICS": "destination", "POPULATION": "default:0", "POP_FIELD": "hint:pop@demand", "STANDARDS": "default:'green=10, school=4'", "THRESHOLD": "default:15"}, "display_name": "Batch Plan Auditor", "error": "", "extra_info": {}, "info": ["Battery: access score, walkability, facility adequacy, green access.", "Category 'pois': 16 amenities", "Category 'facilities': 7 amenities", "Category 'green': 5 amenities", "Population 10,965 | weighted mean score 100.0 | full access 100.0% | no category reachable 0.0%", "Results: {'OUTPUT': 'Access_scores_51614c29_8f8f_499e_9032_e43ab216f827'}", "65 street segments, 36 nodes; audit radius 400.", "Components used: intersections, land-use mix, destinations, block length.", "Mean walk score 50.7; 44.6 percent of segments score below 50.", "Results: {'OUT_SEGMENTS': 'Walkability_segments_a3b5c7d9_5edc_4f0b_ae26_f8cbeff5ac37'}", "Covered population: 10965 of 10965 (100.0%); 3 facility(ies) overloaded.", "Results: {'OUT_DEMAND': 'Demand_coverage_c911c3f3_e82a_4545_998e_4071665fe720', 'OUT_FACILITIES': 'Facility_adequacy_4131d038_b1ed_4d1c_9b17_61bd4b6c19aa'}", "5 greens against 2 classes for 34 demand points.", "Class 1 (0.5 ha within 300): 43.8 percent covered.", "Class 2 (2 ha within 800): 100.0 percent covered.", "Citywide green provision: 10.3 m2 per capita.", "Results: {'OUT_DEMAND': 'Demand_with_green_access_31f499ed_8b01_491b_97f5_0bb38acda0fe', 'OUT_SUMMARY': 'Coverage_per_class_e7203ef3_ba7e_4957_9a73_a05842224cc1'}", "Population 10965 over 34 units. Mean value 100.", "Gini 0.000  |  Theil T 0.000  |  P90/P10 1.00  |  CV 0.000", "Results: {'OUT_POINTS': 'Units__with_equity_attributes__40e80312_6704_49fb_b505_f3ebafb4c547', 'OUT_SUMMARY': 'Equity_summary_table_589f9f19_fa20_4762_8f48_9f65a4b97f07'}", "Report written: C:\\Users\\YE\\AppData\\Local\\Temp\\planx_matrix_7qkk4jei\\outputs\\planaudit\\planaudit_OUTPUT_HTML.html", "Plan Performance Index 100.0.", "Snapshot 'Plan' with 17 metrics: C:\\Users\\YE\\AppData\\Local\\Temp\\planx_matrix_7qkk4jei\\outputs\\planaudit\\planaudit_OUTPUT_JSON.json", "Results: {'OUTPUT_HTML': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\planaudit\\\\planaudit_OUTPUT_HTML.html', 'OUTPUT_JSON': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\planaudit\\\\planaudit_OUTPUT_JSON.json', 'OUT_METRICS': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\planaudit\\\\planaudit_OUT_METRICS.gpkg'}"], "ok": true, "outputs": {"OUTPUT_HTML": "8185 byte(s)", "OUTPUT_JSON": "669 byte(s)", "OUT_METRICS": "17 feature(s)"}, "seconds": 0.083, "warnings": ["fid: Aliases are not compatible with scratch layers", "fid: Comments are not compatible with scratch layers", "pop: Aliases are not compatible with scratch layers", "pop: Comments are not compatible with scratch layers", "value: Aliases are not compatible with scratch layers", "value: Comments are not compatible with scratch layers", "category: Aliases are not compatible with scratch layers", "category: Comments are not compatible with scratch layers", "zone_id: Aliases are not compatible with scratch layers", "zone_id: Comments are not compatible with scratch layers", "production: Aliases are not compatible with scratch layers", "production: Comments are not compatible with scratch layers", "attraction: Aliases are not compatible with scratch layers", "attraction: Comments are not compatible with scratch layers", "rank: Aliases are not compatible with scratch layers", "rank: Comments are not compatible with scratch layers", "jobs: Aliases are not compatible with scratch layers", "jobs: Comments are not compatible with scratch layers", "origin_id: Aliases are not compatible with scratch layers", "origin_id: Comments are not compatible with scratch layers"]}, {"algorithm": "planx:popallocate", "choices": {"CAPACITY_FIELD": "hint:capacity@parcels", "INCREMENT": "default:100", "OUTPUT": "destination", "PARCELS": "name:PARCELS->parcels", "WEIGHT_FIELD": "hint:weight@parcels"}, "display_name": "Allocate Population Growth", "error": "", "extra_info": {}, "info": ["Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\popallocate\\\\popallocate_OUTPUT.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "25 feature(s)"}, "seconds": 0.033, "warnings": []}, {"algorithm": "planx:populationprojection", "choices": {"AGE_FIELD": "hint:age@demand", "FERTILITY_FIELD": "hint:fertility@demand", "INPUT": "override:demand", "MIGRATION_FIELD": "hint:migration@demand", "OUT_PROJECTION": "destination", "OUT_TOTALS": "destination", "POP_FIELD": "hint:pop@demand", "STEPS": "default:4", "STEP_YEARS": "default:5", "SURVIVAL_FIELD": "hint:survival@demand"}, "display_name": "Population Projection (Cohort-Component)", "error": "", "extra_info": {}, "info": ["34 age groups projected 4 step(s) (20 years): 10,965 -> 42,123 (+284.2 percent).", "Share of the oldest group at the horizon: 2.7 percent.", "Results: {'OUT_PROJECTION': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\populationprojection\\\\populationprojection_OUT_PROJECTION.gpkg', 'OUT_TOTALS': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\populationprojection\\\\populationprojection_OUT_TOTALS.gpkg'}"], "ok": true, "outputs": {"OUT_PROJECTION": "170 feature(s)", "OUT_TOTALS": "5 feature(s)"}, "seconds": 0.043, "warnings": []}, {"algorithm": "planx:preparenetwork", "choices": {"CREATE_INDEX": "default:True", "FORWARD_COST": "hint:fwd_cost@network", "INPUT": "override:network", "MIN_LENGTH": "default:0.05", "ONEWAY_FIELD": "hint:oneway@network", "OUTPUT": "destination", "REVERSE_COST": "hint:rev_cost@network", "SNAP_TOLERANCE": "default:0", "TARGET_CRS": "skipped(optional)"}, "display_name": "Prepare Network", "error": "", "extra_info": {}, "info": ["Exploding multipart geometries...", "Results: {'OUTPUT': 'Single_parts_70dda731_449d_44e1_87d0_845c18d9c9cb'}", "Noding lines at mutual intersections...", "Results: {'OUTPUT': 'Split_b89fe86c_27e8_4e57_a64c_17c2895c62ef'}", "0 duplicate feature(s) removed", "Results: {'DUPLICATE_COUNT': 0, 'OUTPUT': 'Cleaned_5ae5bde8_41ca_4dae_9ee9_8f8bcd3280cf', 'RETAINED_COUNT': 65}", "Prepared network: 65 segments, 36 nodes, 1 weak component(s), 0 directed dead-end node(s).", "Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\preparenetwork\\\\preparenetwork_OUTPUT.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "65 feature(s)"}, "seconds": 0.128, "warnings": []}, {"algorithm": "planx:residentialcapacity", "choices": {"DISTRICT_FIELD": "hint:district@parcels", "EFFICIENCY": "default:0.85", "EXISTING_FIELD": "hint:existing@parcels", "FAR_FIELD": "hint:far@parcels", "OUT_DISTRICTS": "destination", "OUT_PARCELS": "destination", "PARCELS": "name:PARCELS->parcels", "UNIT_SIZE": "default:90"}, "display_name": "Residential Capacity", "error": "", "extra_info": {}, "info": ["25 parcels: 843,750 m2 buildable -> 7,950 dwelling(s) at 90 m2 net 0.85 efficiency.", "Results: {'OUT_DISTRICTS': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\residentialcapacity\\\\residentialcapacity_OUT_DISTRICTS.gpkg', 'OUT_PARCELS': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\residentialcapacity\\\\residentialcapacity_OUT_PARCELS.gpkg'}"], "ok": true, "outputs": {"OUT_DISTRICTS": "4 feature(s)", "OUT_PARCELS": "25 feature(s)"}, "seconds": 0.04, "warnings": []}, {"algorithm": "planx:roademissions", "choices": {"EF_GKM": "default:0.5", "HOURLY_FACTOR": "default:1", "OUTPUT": "destination", "ROADS": "name:ROADS->network", "VOLUME_FIELD": "hint:volume@network"}, "display_name": "Road Emissions", "error": "", "extra_info": {}, "info": ["Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\roademissions\\\\roademissions_OUTPUT.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "65 feature(s)"}, "seconds": 0.023, "warnings": []}, {"algorithm": "planx:routequality", "choices": {"DESTINATIONS": "name:DESTINATIONS->pois", "LOW_THRESHOLD": "default:50", "NETWORK": "name:NETWORK->network", "ORIGINS": "name:ORIGINS->demand", "OUT_ROUTES": "destination", "PAIRING": "default:0", "PENALTY": "default:1", "SCORE_FIELD": "hint:score@network"}, "display_name": "Pedestrian Route Quality", "error": "", "extra_info": {}, "info": ["28 route(s); mean walk score along routes 74.1 (penalty 1).", "Results: {'OUT_ROUTES': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\routequality\\\\routequality_OUT_ROUTES.gpkg'}"], "ok": true, "outputs": {"OUT_ROUTES": "28 feature(s)"}, "seconds": 0.029, "warnings": []}, {"algorithm": "planx:scenariocompare", "choices": {"OUTPUT_HTML": "destination", "OUT_TABLE": "destination", "SNAPSHOT_A": "override:art:planx:scenariosnapshot/OUTPUT_JSON", "SNAPSHOT_B": "override:art:extra/scene_b"}, "display_name": "Scenario Compare (A/B)", "error": "", "extra_info": {}, "info": ["Compared 'Scenario A' (2026-09-19 12:06) with 'Scenario B' (2026-09-19 12:06): 19 metrics.", "'Scenario A' leads: Scenario B wins 0, Scenario A wins 5, 6 tied, over 19 compared metrics.", "Comparison report written: C:\\Users\\YE\\AppData\\Local\\Temp\\planx_matrix_7qkk4jei\\outputs\\scenariocompare\\scenariocompare_OUTPUT_HTML.html", "Results: {'OUTPUT_HTML': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\scenariocompare\\\\scenariocompare_OUTPUT_HTML.html', 'OUT_TABLE': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\scenariocompare\\\\scenariocompare_OUT_TABLE.gpkg'}"], "ok": true, "outputs": {"OUTPUT_HTML": "5421 byte(s)", "OUT_TABLE": "19 feature(s)"}, "seconds": 0.017, "warnings": []}, {"algorithm": "planx:scenariopipeline", "choices": {"AMENITIES": "multi:pois,facilities,green", "BASE": "default:0.1", "CATEGORY_FIELD": "hint:category@landuse", "CONSTRAINTS": "name:CONSTRAINTS->constraints", "DEMAND": "name:DEMAND->demand", "DEMAND_HA": "default:50", "ITERATIONS": "default:5", "LANDUSE": "name:LANDUSE->landuse", "NAME": "default:'Scenario'", "NEIGH_WEIGHT": "default:1", "NETWORK": "name:NETWORK->network", "OUTPUT_JSON": "destination", "OUT_METRICS": "destination", "POP_FIELD": "hint:pop@demand", "POP_GROWTH": "default:1000", "RNG_SEED": "default:0", "SEED": "name:SEED->seed", "SUITABILITY": "name:SUITABILITY->suitability", "THRESHOLD": "default:15"}, "display_name": "Scenario Pipeline (LUTI-lite)", "error": "", "extra_info": {}, "info": ["Seed fabric 14.0 ha; demand 50 ha = 125000 cells over 5 step(s); weight 1, base 0.1, seed 0.", "Step 1: 25000 cell(s) converted (10.00 ha).", "Step 2: 25000 cell(s) converted (10.00 ha).", "Step 3: 25000 cell(s) converted (10.00 ha).", "Step 4: 25000 cell(s) converted (10.00 ha).", "Step 5: 5633 cell(s) converted (2.25 ha).", "Final urban fabric 56.2 ha (+42.3 ha).", "Results: {'OUTPUT': 'C:/Users/YE/AppData/Local/Temp/processing_jCKMDx/ff7c0f61191f4131a969dc564160bd92/OUTPUT.tif'}", "Category 'pois': 16 amenities", "Category 'facilities': 7 amenities", "Category 'green': 5 amenities", "Population 11,965 | weighted mean score 100.0 | full access 100.0% | no category reachable 0.0%", "Results: {'OUTPUT': 'Access_scores_88078170_5366_4211_ad58_0b4f11e6eeba'}", "65 street segments, 36 nodes; audit radius 400.", "Components used: intersections, land-use mix, destinations, block length.", "Mean walk score 50.7; 44.6 percent of segments score below 50.", "Results: {'OUT_SEGMENTS': 'Walkability_segments_c5da0d86_fa51_4e92_beb3_adf9cdcdec69'}", "Scenario Pipeline complete. Snapshot 'Scenario' with 8 metrics: C:\\Users\\YE\\AppData\\Local\\Temp\\planx_matrix_7qkk4jei\\outputs\\scenariopipeline\\scenariopipeline_OUTPUT_JSON.json", "Results: {'OUTPUT_JSON': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\scenariopipeline\\\\scenariopipeline_OUTPUT_JSON.json', 'OUT_METRICS': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\scenariopipeline\\\\scenariopipeline_OUT_METRICS.gpkg'}"], "ok": true, "outputs": {"OUTPUT_JSON": "407 byte(s)", "OUT_METRICS": "8 feature(s)"}, "seconds": 6.351, "warnings": ["Demand of 125000 cells exceeds the 105633 open cells - the growth will saturate."]}, {"algorithm": "planx:scenariorank", "choices": {"FILES": "override:['art:planx:scenariosnapshot/OUTPUT_JSON', 'art:extra/scene_b']", "FOLDER": "skipped(optional)", "OUTPUT_HTML": "destination", "OUT_DETAIL": "destination", "OUT_TABLE": "destination", "RANDOM_SEED": "default:42", "SIMULATIONS": "default:200", "WEIGHTS": "skipped(optional)", "WEIGHT_VARIATION": "default:0.2"}, "display_name": "Scenario Ranking", "error": "", "extra_info": {}, "info": ["Ranking 2 snapshots...", "Scored metrics: 5", "Skipped metric 'origins': neutral", "Skipped metric 'standards_compliance_pct': constant", "Skipped metric 'standards_deficits': constant", "Skipped metric 'standards_categories': neutral", "Skipped metric 'covered_share': constant", "Skipped metric 'covered_pop': constant", "Skipped metric 'total_pop': neutral", "Skipped metric 'facilities': neutral", "Skipped metric 'facilities_overloaded': constant", "Skipped metric 'facilities_unused': constant", "Skipped metric 'mean_utilization': neutral", "Skipped metric 'density_mean': neutral", "Skipped metric 'density_max': neutral", "Skipped metric 'density_cells': neutral", "1. Scenario A (100.0)  2. Scenario B (0.0)", "Ranking board written: C:\\Users\\YE\\AppData\\Local\\Temp\\planx_matrix_7qkk4jei\\outputs\\scenariorank\\scenariorank_OUTPUT_HTML.html", "Results: {'OUTPUT_HTML': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\scenariorank\\\\scenariorank_OUTPUT_HTML.html', 'OUT_DETAIL': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\scenariorank\\\\scenariorank_OUT_DETAIL.gpkg', 'OUT_TABLE': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\scenariorank\\\\scenariorank_OUT_TABLE.gpkg'}"], "ok": true, "outputs": {"OUTPUT_HTML": "5570 byte(s)", "OUT_DETAIL": "10 feature(s)", "OUT_TABLE": "2 feature(s)"}, "seconds": 0.047, "warnings": []}, {"algorithm": "planx:seismicdebris", "choices": {"BLOCKS": "override:parcels", "BUILDINGS": "name:BUILDINGS->buildings", "DEBRIS_FACTOR": "default:0.4", "DEFAULT_WIDTH": "default:8", "FLOOR_FIELD": "hint:floors@buildings", "FLOOR_HEIGHT": "default:3", "HIGHWAY_FIELD": "hint:highway@network", "MAGNITUDE": "default:7", "NETWORK": "override:network", "NETWORK_LINES": "override:network", "NETWORK_MODE": "default:0", "OUT_BLOCKED": "destination", "OUT_BUILDINGS": "destination", "OUT_CORRIDORS": "destination", "OUT_ENVELOPE": "destination", "ROI": "override:study_area", "SEED": "default:42", "SOLID_VOLUME_RATIO": "default:0.3", "WIDTH_FIELD": "hint:width@network", "YEAR_FIELD": "hint:year@buildings"}, "display_name": "Seismic Collapse and Debris Spread (Monte Carlo)", "error": "", "extra_info": {}, "info": ["Network A: 65 open-space polygons used as-is.", "Mw 7 scenario (seed 42): 30/70 buildings collapsed, 523411.9 m3 estimated debris.", "Results: {'OUT_BLOCKED': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\seismicdebris\\\\seismicdebris_OUT_BLOCKED.gpkg', 'OUT_BUILDINGS': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\seismicdebris\\\\seismicdebris_OUT_BUILDINGS.gpkg', 'OUT_CORRIDORS': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\seismicdebris\\\\seismicdebris_OUT_CORRIDORS.gpkg', 'OUT_ENVELOPE': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\seismicdebris\\\\seismicdebris_OUT_ENVELOPE.gpkg'}"], "ok": true, "outputs": {"OUT_BLOCKED": "1 feature(s)", "OUT_BUILDINGS": "70 feature(s)", "OUT_CORRIDORS": "1 feature(s)", "OUT_ENVELOPE": "1 feature(s)"}, "seconds": 0.109, "warnings": []}, {"algorithm": "planx:serviceareas", "choices": {"AREAS": "destination", "BREAKS": "default:'250, 500, 1000'", "BUFFER": "default:30", "CIRCLES": "destination", "COMBINE": "default:0", "COST_FIELD": "hint:cost@network", "EDGES": "destination", "FACILITIES": "name:FACILITIES->facilities", "FACILITY_ID": "hint:facility_id@facilities", "HULL_DETAIL": "default:0.3", "METHOD": "default:0", "NETWORK": "name:NETWORK->network", "RINGS": "default:False", "SUMMARY": "destination"}, "display_name": "Service Areas (Isochrones)", "error": "", "extra_info": {}, "info": ["Graph: 36 nodes / 65 edges; 7 facilities snapped onto the nearest street (max snap distance 75.0 map units).", "Reached street pieces: 99.", "Cost field in use: circles read the breaks as map-unit radii, so the pedshed ratio mixes units - interpret with care (or leave the cost field empty for distances).", "Break 250: 6674 map units of street reached, catchment 343769, pedshed 0.41", "Break 500: 10061 map units of street reached, catchment 481993, pedshed 0.25", "Break 1000: 10061 map units of street reached, catchment 481993, pedshed 0.09", "Results: {'AREAS': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\serviceareas\\\\serviceareas_AREAS.gpkg', 'CIRCLES': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\serviceareas\\\\serviceareas_CIRCLES.gpkg', 'EDGES': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\serviceareas\\\\serviceareas_EDGES.gpkg', 'SUMMARY': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\serviceareas\\\\serviceareas_SUMMARY.gpkg'}"], "ok": true, "outputs": {"AREAS": "3 feature(s)", "CIRCLES": "3 feature(s)", "EDGES": "99 feature(s)", "SUMMARY": "3 feature(s)"}, "seconds": 0.14, "warnings": []}, {"algorithm": "planx:shadowcasting", "choices": {"DSM": "name:DSM->dsm", "MAX_SEARCH": "default:0", "OUTPUT": "destination", "UTC_OFFSET": "default:0", "WHEN": "datetime:2026-06-21 12:00"}, "display_name": "Shadow Casting (DSM)", "error": "", "extra_info": {}, "info": ["Site 0.0034N 0.0034E | sun altitude 66.56 deg, azimuth 1.04 deg", "Shadowed share of the scene: 5.2%", "Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\shadowcasting\\\\shadowcasting_OUTPUT.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "140625/140625 populated pixel(s)"}, "seconds": 0.025, "warnings": []}, {"algorithm": "planx:skyviewfactor", "choices": {"DIRECTIONS": "default:16", "DSM": "name:DSM->dsm", "OUTPUT": "destination", "RADIUS": "default:100"}, "display_name": "Sky View Factor (DSM)", "error": "", "extra_info": {}, "info": ["DSM 375x375 px, pixel 2.00; 16 directions, radius 100", "SVF range 0.214 - 1.000, mean 0.843", "Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\skyviewfactor\\\\skyviewfactor_OUTPUT.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "140625/140625 populated pixel(s)"}, "seconds": 1.368, "warnings": []}, {"algorithm": "planx:solarirradiation", "choices": {"DATE": "datetime:2026-06-21 12:00", "DSM": "name:DSM->dsm", "INTERVAL": "default:30", "MAX_SEARCH": "default:0", "OUTPUT": "destination", "SVF_RADIUS": "default:100", "USE_SVF": "default:True", "UTC_OFFSET": "default:0"}, "display_name": "Solar Irradiation (DSM)", "error": "", "extra_info": {}, "info": ["Site 0.0034N 0.0034E | 2026-06-21 swept every 30 min", "Sky view factor pass...", "Irradiation sweep...", "Flat-ground clear-sky reference 6.60 kWh/m2 | scene mean 5.66, min 0.23, max 6.60", "Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\solarirradiation\\\\solarirradiation_OUTPUT.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "140625/140625 populated pixel(s)"}, "seconds": 2.962, "warnings": []}, {"algorithm": "planx:spacematrix", "choices": {"BLOCKS": "name:BLOCKS->parcels", "BUILDINGS": "name:BUILDINGS->buildings", "DEFAULT_LEVELS": "default:2", "LEVELS_FIELD": "hint:floors@buildings", "OUTPUT": "destination"}, "display_name": "Spacematrix Density", "error": "", "extra_info": {}, "info": ["Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\spacematrix\\\\spacematrix_OUTPUT.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "25 feature(s)"}, "seconds": 0.028, "warnings": []}, {"algorithm": "planx:spacesyntax", "choices": {"NETWORK": "name:NETWORK->network", "OUTPUT": "destination", "RADII": "default:'800, n'"}, "display_name": "Space Syntax (Segment Angular Analysis)", "error": "", "extra_info": {}, "info": ["Segment graph: 65 segments", "Radius 800...", "Radius n...", "Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\spacesyntax\\\\spacesyntax_OUTPUT.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "65 feature(s)"}, "seconds": 0.09, "warnings": []}, {"algorithm": "planx:sprawlmetrics", "choices": {"OUT_SUMMARY": "destination", "POP_T1": "default:100000", "POP_T2": "default:120000", "URBAN_T1": "name:URBAN_T1->urban_t1", "URBAN_T2": "name:URBAN_T2->urban_t2"}, "display_name": "Urban Sprawl Metrics", "error": "", "extra_info": {}, "info": ["Large urban mask - the patch labelling may take a while.", "LCRPGR 0.000 (densifying); 70 patch(es), largest holds 1.4 percent.", "Results: {'OUT_SUMMARY': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\sprawlmetrics\\\\sprawlmetrics_OUT_SUMMARY.gpkg'}"], "ok": true, "outputs": {"OUT_SUMMARY": "12 feature(s)"}, "seconds": 0.09, "warnings": []}, {"algorithm": "planx:streetcomfort", "choices": {"BANDWIDTH": "default:50", "KERNEL": "default:2", "NEGATIVE": "multi:network", "NETWORK": "name:NETWORK->network", "OUTPUT": "destination", "POSITIVE": "multi:pois,green", "RASTER_MINUS": "default:RASTER_MINUS->dsm", "RASTER_PLUS": "default:RASTER_PLUS->dsm", "SAMPLE_STEP": "default:10", "WEIGHTS": "skipped(optional)", "WEIGHT_FIELD": "skipped(optional)"}, "display_name": "Street Environment Comfort", "error": "", "extra_info": {}, "info": ["Used components: positive=1.0, negative=1.0", "Mean comfort score: 26.05", "Comfort score < 25 count: 38", "Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\streetcomfort\\\\streetcomfort_OUTPUT.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "65 feature(s)"}, "seconds": 0.12, "warnings": ["10 segment(s) outside raster_plus coverage - neutral", "10 segment(s) outside raster_minus coverage - neutral", "Component 'raster_plus' is constant across segments and was dropped.", "Component 'raster_minus' is constant across segments and was dropped."]}, {"algorithm": "planx:streetmorphology", "choices": {"NETWORK": "name:NETWORK->network", "NODES": "destination", "SUMMARY": "destination"}, "display_name": "Street Network Morphology", "error": "", "extra_info": {}, "info": ["  nodes = 36", "  edges = 65", "  components = 1", "  total_length_km = 10.061", "  avg_segment_length_m = 154.78", "  avg_node_degree = 3.611", "  intersections_deg3plus = 34", "  culdesac_count = 0", "  culdesac_ratio = 0.0", "  intersection_density_km2 = 60.44", "  alpha_meshedness = 0.4478", "  beta_index = 1.8056", "  gamma_index = 0.6373", "  orientation_entropy_nats = 1.6501", "  orientation_order = 0.9856", "Results: {'NODES': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\streetmorphology\\\\streetmorphology_NODES.gpkg', 'SUMMARY': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\streetmorphology\\\\streetmorphology_SUMMARY.gpkg'}"], "ok": true, "outputs": {"NODES": "36 feature(s)", "SUMMARY": "15 feature(s)"}, "seconds": 0.053, "warnings": []}, {"algorithm": "planx:sunhours", "choices": {"DATE": "datetime:2026-06-21 12:00", "DSM": "name:DSM->dsm", "INTERVAL": "default:30", "MAX_SEARCH": "default:0", "OUTPUT": "destination", "UTC_OFFSET": "default:0"}, "display_name": "Sun Hours (DSM)", "error": "", "extra_info": {}, "info": ["Site 0.0034N 0.0034E | 2026-06-21 swept every 30 min", "Potential daylight 12.0 h | direct sun mean 9.2 h, min 0.0 h, max 12.0 h", "Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\sunhours\\\\sunhours_OUTPUT.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "140625/140625 populated pixel(s)"}, "seconds": 1.596, "warnings": []}, {"algorithm": "planx:tessellation", "choices": {"BUILDINGS": "name:BUILDINGS->buildings", "DENSIFY": "default:2", "LIMIT": "default:100", "OUTPUT": "destination", "SHRINK": "default:0.4", "STUDY_AREA": "name:STUDY_AREA->study_area"}, "display_name": "Morphological Tessellation", "error": "", "extra_info": {}, "info": ["70 buildings -> 7280 seed points", "7280 Voronoi cells", "Wrote 70 tessellation cells.", "Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\tessellation\\\\tessellation_OUTPUT.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "70 feature(s)"}, "seconds": 0.53, "warnings": []}, {"algorithm": "planx:transitaccess", "choices": {"DAY": "skipped(optional)", "DEMAND": "name:DEMAND->demand", "DEPARTURE": "default:8", "DEPARTURE_SAMPLES": "default:5", "FILE": "override:fixture:gtfs", "MAX_TRANSFERS": "default:2", "MAX_WALK": "default:10", "MIN_TRANSFER": "default:2", "NETWORK": "name:NETWORK->network", "ORIGINS": "name:ORIGINS->demand", "OUT_DEMAND": "destination", "SAMPLE_WINDOW": "default:60", "TRANSFER_WALK": "default:250", "WALK_SPEED": "default:4.8"}, "display_name": "Transit Travel-Time Access", "error": "", "extra_info": {}, "info": ["No date given - using the feed's first service day: 20260101.", "8 stop(s) within a 10 min access walk; departure 20260101 at 8:00, up to 2 transfer(s).", "34 of 34 destination(s) reached faster by transit.", "Results: {'OUT_DEMAND': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\transitaccess\\\\transitaccess_OUT_DEMAND.gpkg'}"], "ok": true, "outputs": {"OUT_DEMAND": "34 feature(s)"}, "seconds": 0.094, "warnings": []}, {"algorithm": "planx:transitfrequency", "choices": {"DAY": "skipped(optional)", "END": "default:9", "FILE": "override:fixture:gtfs", "OUT_ROUTES": "destination", "OUT_STOPS": "destination", "START": "default:7"}, "display_name": "Transit Frequency Map", "error": "", "extra_info": {}, "info": ["No date given - using the feed's first service day: 20260101.", "7 of 8 stops served in 7:00-9:00 on 20260101; busiest: Stop 0 (1 departures, headway 120 min).", "Results: {'OUT_ROUTES': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\transitfrequency\\\\transitfrequency_OUT_ROUTES.gpkg', 'OUT_STOPS': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\transitfrequency\\\\transitfrequency_OUT_STOPS.gpkg'}"], "ok": true, "outputs": {"OUT_ROUTES": "1 feature(s)", "OUT_STOPS": "8 feature(s)"}, "seconds": 0.046, "warnings": []}, {"algorithm": "planx:tripgeneration", "choices": {"A_RATE": "default:2", "JOBS_FIELD": "hint:jobs@demand", "OUTPUT": "destination", "POP_FIELD": "hint:pop@demand", "P_RATE": "default:1.5", "ZONES": "name:ZONES->demand"}, "display_name": "Trip Generation", "error": "", "extra_info": {}, "info": ["Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\tripgeneration\\\\tripgeneration_OUTPUT.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "34 feature(s)"}, "seconds": 0.025, "warnings": []}, {"algorithm": "planx:viewshed", "choices": {"DIRECTIONS": "default:720", "DSM": "name:DSM->dsm", "OBSERVERS": "name:OBSERVERS->demand", "OBSERVER_HEIGHT": "default:1.6", "OUTPUT": "destination", "RADIUS": "default:0", "TARGET_HEIGHT": "default:0"}, "display_name": "Viewshed (DSM)", "error": "", "extra_info": {}, "info": ["Observer 1: sees 2.4 percent of the raster.", "Observer 2: sees 7.3 percent of the raster.", "Observer 3: sees 2.8 percent of the raster.", "Observer 4: sees 0.6 percent of the raster.", "Observer 5: sees 6.6 percent of the raster.", "Observer 6: sees 3.5 percent of the raster.", "Observer 7: sees 2.4 percent of the raster.", "Observer 8: sees 4.2 percent of the raster.", "Observer 9: sees 7.0 percent of the raster.", "Observer 10: sees 0.9 percent of the raster.", "Observer 11: sees 5.3 percent of the raster.", "Observer 12: sees 5.9 percent of the raster.", "Observer 13: sees 8.4 percent of the raster.", "Observer 14: sees 3.2 percent of the raster.", "Observer 15: sees 4.2 percent of the raster.", "Observer 16: sees 11.0 percent of the raster.", "Observer 17: sees 2.9 percent of the raster.", "Observer 18: sees 0.8 percent of the raster.", "Observer 19: sees 2.4 percent of the raster.", "Observer 20: sees 5.2 percent of the raster.", "Observer 21: sees 5.5 percent of the raster.", "Observer 22: sees 4.0 percent of the raster.", "Observer 23: sees 1.9 percent of the raster.", "Observer 24: sees 1.7 percent of the raster.", "Observer 25: sees 9.9 percent of the raster.", "Observer 26: sees 5.8 percent of the raster.", "Observer 27: sees 5.4 percent of the raster.", "Observer 28: sees 3.4 percent of the raster.", "Observer 29: sees 6.8 percent of the raster.", "Observer 30: sees 6.0 percent of the raster.", "Observer 31: sees 6.7 percent of the raster.", "Observer 32: sees 3.4 percent of the raster.", "Observer 33: sees 2.4 percent of the raster.", "Observer 34: sees 5.9 percent of the raster.", "34 observer(s); 39.9 percent of cells seen by at least one.", "Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\viewshed\\\\viewshed_OUTPUT.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "140625/140625 populated pixel(s)"}, "seconds": 0.833, "warnings": []}, {"algorithm": "planx:visualexposure", "choices": {"DSM": "name:DSM->dsm", "EXTRA_HEIGHT": "default:0", "EYE_HEIGHT": "default:1.6", "LANDMARKS": "name:LANDMARKS->facilities", "OUTPUT": "destination", "RADIUS": "default:0", "SAMPLE_STEP": "default:10"}, "display_name": "Visual Exposure of Landmarks", "error": "", "extra_info": {}, "info": ["7 outline point(s); 47.2 percent of cells see the landmark.", "Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\visualexposure\\\\visualexposure_OUTPUT.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "140625/140625 populated pixel(s)"}, "seconds": 0.102, "warnings": []}, {"algorithm": "planx:walkability", "choices": {"CATEGORY_FIELD": "hint:category@landuse", "DEM": "name:DEM->dem", "LANDUSE": "name:LANDUSE->landuse", "NETWORK": "name:NETWORK->network", "OUT_SEGMENTS": "destination", "POIS": "name:POIS->pois", "RADIUS": "default:400", "WEIGHTS": "default:'intersections=0.3, mix=0.25, destinations=0.25, blocklength=0.1, slope=0.1'"}, "display_name": "Walkability Audit", "error": "", "extra_info": {}, "info": ["65 street segments, 36 nodes; audit radius 400.", "Components used: intersections, land-use mix, destinations, block length, slope.", "Mean walk score 55.7; 15.4 percent of segments score below 50.", "Results: {'OUT_SEGMENTS': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\walkability\\\\walkability_OUT_SEGMENTS.gpkg'}"], "ok": true, "outputs": {"OUT_SEGMENTS": "65 feature(s)"}, "seconds": 0.073, "warnings": ["22 segment(s) had no DEM value - treated as flat."]}, {"algorithm": "planx:walkingslope", "choices": {"BREAKS": "default:'5,8,12'", "DEM": "name:DEM->dem", "NETWORK": "name:NETWORK->network", "OUTPUT": "destination", "SAMPLE_STEP": "default:10"}, "display_name": "Walking Slope Comfort", "error": "", "extra_info": {}, "info": ["Mean slope_pct: 0.00%", "Share of comfort class >= 3: 0.0%", "Worst segment slope_pct: 0.00% (fid -1)", "Results: {'OUTPUT': 'C:\\\\Users\\\\YE\\\\AppData\\\\Local\\\\Temp\\\\planx_matrix_7qkk4jei\\\\outputs\\\\walkingslope\\\\walkingslope_OUTPUT.gpkg'}"], "ok": true, "outputs": {"OUTPUT": "65 feature(s)"}, "seconds": 0.075, "warnings": ["10 segment(s) with insufficient DEM coverage - treated as flat."]}], "catalog_errors": [], "failed": [], "failed_count": 0, "fixture_seconds": 0.412, "ok_count": 71, "qgis_release": "Bel\u00e9m do Par\u00e1", "qgis_version": "4.2.0-Bel\u00e9m do Par\u00e1"}
PLANX_RUNTIME_MATRIX: PASS (71/71)

Result lines kept: **71** `ok`/`FAIL` lines, of which **0** `FAIL`. Third-party diagnostic lines filtered out: **1035**.
```

JSON summary:

```
{
  "case_count": 71,
  "catalog_errors": [],
  "failed_count": 0,
  "fixture_seconds": 0.412,
  "ok_count": 71,
  "qgis_release": "Bel\u00e9m do Par\u00e1",
  "qgis_version": "4.2.0-Bel\u00e9m do Par\u00e1"
}
```

### 4.4 dashboard checks (verbatim, complete)

**PARTIAL — no dashboard test suite exists in this repository, so there is no artifact to report verbatim.** This is S7, not an omission in the reporting.

`ls tests/` yields exactly: `__init__.py`, `qgis_runtime_algorithm_matrix.py`, `smoke_plugin.py`, `smoke_provider_catalog.py`, `test_engine.py`. Nothing in `tests/` references the dashboard.

What *does* cover the dashboard's computational surface is the runtime matrix, which executes every registered algorithm in the Reporting and Dashboard group and verifies that each declared output is actually populated. Those cases, from the 4.2.0 JSON:

```
  ok   planx:scenariosnapshot                0.10s 
         outputs: OUTPUT_JSON=729 byte(s), OUT_METRICS=19 feature(s)
  ok   planx:democity                        0.05s 
         outputs: OUTPUT_BUILDINGS=70 feature(s), OUTPUT_DEMAND=34 feature(s), OUTPUT_DSM=140625/140625 populated pixel(s), OUTPUT_FACILITIES=7 feature(s), OUTPUT_GREEN=5 feature(s), OUTPUT_LANDUSE=25 feature(s), OUTPUT_POIS=16 feature(s), OUTPUT_STREETS=65 feature(s)
  ok   planx:performancereport               0.08s 
         outputs: OUTPUT=10651 byte(s)
  ok   planx:planaudit                       0.08s 
         outputs: OUTPUT_HTML=8185 byte(s), OUTPUT_JSON=669 byte(s), OUT_METRICS=17 feature(s)
  ok   planx:scenariocompare                 0.02s 
         outputs: OUTPUT_HTML=5421 byte(s), OUT_TABLE=19 feature(s)
  ok   planx:scenariopipeline                6.35s 
         outputs: OUTPUT_JSON=407 byte(s), OUT_METRICS=8 feature(s)
  ok   planx:scenariorank                    0.05s 
         outputs: OUTPUT_HTML=5570 byte(s), OUT_DETAIL=10 feature(s), OUT_TABLE=2 feature(s)
```

A dedicated suite for the dashboard (report generation, score cards, snapshot round-tripping, Sparkline history) remains future work and is recorded here rather than implied.

### 4.5 Supporting gates

Catalog gates — the two that were red on exactly `['parkingdemand', 'parkingsupplybalance']` through Phase 2 are now green:

```
15/15 catalog gates passed
exit 0
```

Plugin shell smoke test (QGIS 3.44.12 LTR):

```
PlanX smoke: initializing QGIS
PlanX smoke: importing provider
PlanX smoke: loading algorithms
PASS PlanX provider: 71 unique algorithms initialized
```

Import/registration check (S5), run from the monorepo root:

```
QGIS: 3.44.12-Solothurn
provider 'planx': 71 algorithms, scipy=True
groups: ['Accessibility', 'Centrality and Space Syntax', 'Cycling', 'Equity', 'Green Infrastructure', 'Hazard Screening', 'Microclimate', 'Network Analysis', 'Optimization', 'Plan Standards and QA', 'Population and Housing', 'Reporting and Dashboard', 'Seismic Risk', 'Transit', 'Travel Demand', 'Urban Growth', 'Urban Morphology', 'Visibility', 'Walkability']
IMPORT CHECK OK
exit 0
```

CI gates, all exit 0:

```
compileall: exit 0
flake8: exit 0
bandit: exit 0
```

## 5. Deviations from this plan

1. **Registration happened in Phases 1 and 2, not Phase 3.** The plan placed provider registration in Phase 3; registering each algorithm alongside its own implementation is the sibling pattern and keeps every phase independently runnable. Consequence: Phase 3 contained no registration work.
2. **`name()` is `parkingsupplybalance`, not the plan's `parking_supply_balance`.** All 70 pre-existing slugs are underscore-free and ground rule 7 freezes ids, so an underscore here would have been the only one in the plugin. The manual anchor and the Processing ID both use the underscore-free slug.
3. **The rate-table grammar extends the existing `keyword=value` UI.** Parking standards have no single denominator, so each entry carries its own basis (`category=basis:rate`) instead of assuming one. This is a grammar extension, not a new parameter type.
4. **§7's file list has wrong paths and omissions.** It names `planx/algorithms/provider.py`; the real path is `planx/provider.py`. It also omits the engine modules (`engine/parking.py`), the icon, and all four test files, every one of which this plan necessarily touched.
5. **Both `shortHelpString()`s were written in their own phases, not Phase 3.** Ground rule 3 and the versioned catalog gate both require them, and the sibling pattern is to write help with the algorithm.
6. **Phase 1's output sink was amended to preserve geometry** (within the `e741c47` commit, before it was pushed anywhere), drawing on the `alg_facility_adequacy` precedent: a zone layer that loses its geometry cannot be mapped without a join.
7. **The runtime matrix needed a small extension.** `build_inputs` could resolve a field parameter only against a fixture layer; the parking chain needs a field resolved against an artefact-fed parent. Without it, a field guessed onto a layer that does not carry it would leave the algorithm on its own default and the case green having tested nothing.
8. **`metadata.txt`'s `description` and `tags` were updated**, not only its version. The description enumerates the plugin's capabilities and, as released, omitted the two tools this release adds; `about` was left alone because it carries no travel-demand clause for either the new or the existing demand tools, and editing one without the other would be inconsistent.
9. **Two count claims outside the plan's scope were corrected** because Phase 3 is the release's documentation phase and both were false: the README's "503 engine unit checks" is now 570 (verified by running it), and the Studio dock's "Search 69 planning tools…" placeholder is now 71. `studio_dock.py` is not in §7; it is named in Phase 3 as the Studio wiring to check, and the check found this literal. The README's "448 end-to-end assertions" was left untouched — see S9.
10. **Two DOIs in the plan's spirit are absent by choice.** Citations were verified against Crossref, and an unverifiable candidate was dropped rather than included on recall.
11. **The report lives in `docs/`, not the plugin root.** §R asked for `REPORT_v4.12.md` in the plugin root. This repository already keeps its release reports at `docs/AGENT_REPORT_v4.8.md` and `docs/AGENT_REPORT_v4.9.md`, and `.zipignore` lists `docs` — so the root is packaged into the released plugin zip and `docs/` is not. A working report in the root would therefore have shipped to users. Filed as `docs/AGENT_REPORT_v4.12.md`, under the sibling naming, and noted here rather than silently relocated.
12. **The Phase 2 commit message was amended, and its SHA moved.** While assembling the evidence for §4.2 the Phase 2 message was re-read and found to assert, in its test-evidence block, an LTR `PLANX_RUNTIME_MATRIX: PASS (71/71), exit 0, report written` — and then, two sentences later, that on that runtime neither the verdict nor the report is produced. Both cannot hold, and no LTR 71/71 verdict exists: the runtime's completed runs are 69/69 and 70/70, and the 71/71 verdict is 4.2.0's. The claim was false, and it reads as having been carried over from the 4.2.0 line above it. The commit was unpushed with nothing built on it, so the message was corrected in place rather than left for a reviewer to trip over. The amendment is **message-only**: the tree hash is unchanged (`48f7b4b5`), author and committer are unchanged, and the SHA moved `61d3d3c` → `719d4b7`. Every reference in this report uses the new SHA; if `61d3d3c` was already noted anywhere, this is the mapping. The corrected block now states the per-case result and says plainly that the run-level LTR verdict is not on record.

Explicitly **not** done, per ground rule 11's carve-out for the final phase: no tag, no `release.ps1`, no upload, no push. The version bump, CHANGELOG and `metadata.txt` update were written because Phase 3 is the final phase, and the maintainer releases manually after reviewing this report.

## 6. Commit list

Prior commits, newest first:

```
719d4b7 phase-2: add Parking Supply-Demand Balance
e741c47 phase-1: add Parking Demand Estimator (ITE-style rate table)
74e3d4d release: 4.11.2 - quality infrastructure
b3d73f6 docs: add ENHANCEMENT_PLAN_v5 - audit, defect register, release roadmap
```

Phase 3 itself is the commit that adds this report — subject `phase-3: document both parking tools, bump to 4.12.0`. A file cannot list the hash of the commit that introduces it, so it is identified by subject here and is readable in `git log`. The newest commit above, `719d4b7`, is where this release's code work stopped; nothing after it changes behaviour.

Working state at hand-off: nothing is tagged, nothing is pushed, and the release is not cut. This release's own commits are local only.
