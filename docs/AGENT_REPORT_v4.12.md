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

**S8 — on QGIS 3.44 LTR the runtime matrix takes about ten minutes to return after its last case.**
The sweep finishes all 71 cases in well under a minute and then spins: for roughly ten minutes it burns CPU in the exit path without printing anything, and only then returns, writes its JSON report and prints its verdict. **This section originally described that as a hang that never returns, and that was wrong.** On the first several attempts the process was read as permanently stuck and abandoned at that point, which is why the run in §4.2 was driven through a wrapper and why the Phase 2 commit message had to be corrected. A later attempt was left alone, and it completed: verdict `PLANX_RUNTIME_MATRIX: PASS (71/71)`, exit 0, report written. The delay is real, the hang is not. The immediate cause is not pinned down here; the harness's own comment already anticipates it — "QGIS teardown on Windows can block for minutes after the work is done and the report is out" — and it is the reason `main()` calls `os._exit` rather than returning normally. The 4.2.0 runtime does not pay this cost. Worth fixing anyway: `_teardown` is already guarded on Windows for exactly this class of hazard and its sibling cleanup is not.

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

One point of provenance, stated rather than glossed because it bounds what this section proves: the stock invocation on this runtime prints all 71 per-case lines and then does not return for roughly ten minutes — that is **S8**. To get the lines without that wait, this run was driven through `scratch/_run_matrix_diag.py`, which loads the matrix module unmodified by path and replaces its final `shutil.rmtree` with a no-op. Nothing else is changed: the fixtures, the cases, the assertions and the pass/fail decision are the matrix module's own.

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
PLANX_RUNTIME_MATRIX: PASS (71/71)

Result lines kept: **71** `ok`/`FAIL` lines, of which **0** `FAIL`. Lines filtered out: **1044** — third-party GDAL/OSGeo4W diagnostics, chiefly `RasterIO() ... Access window out of range` from the raster tools, plus the harness's own single-line JSON dump, which is quoted in summary form below rather than inline.
```

The run finished and printed its own verdict: **`PLANX_RUNTIME_MATRIX: PASS (71/71)`**, process exit code 0 — and it wrote its JSON report. It did so only after the delay described in **S8**: the cases were done in under a minute, and the verdict took roughly ten more to appear.

This is the strongest single piece of evidence in the release. It is the whole catalog executing on the runtime it was easiest to give up on, and `catalog_errors` is empty — that field is the harness's own registry-versus-manual check, so the cards, anchors and icons added in this phase agree with the registry as seen from inside QGIS, not only from the static gates.

JSON summary of this run:

```
{
  "case_count": 71,
  "catalog_errors": [],
  "failed_count": 0,
  "fixture_seconds": 0.501,
  "ok_count": 71,
  "qgis_release": "Solothurn",
  "qgis_version": "3.44.12-Solothurn"
}
```

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
PLANX_RUNTIME_MATRIX: PASS (71/71)

Result lines kept: **71** `ok`/`FAIL` lines, of which **0** `FAIL`. Third-party diagnostic lines filtered out: **1036**.
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
12. **The Phase 2 commit message was amended, and its SHA moved.** While assembling the evidence for §4.2 the Phase 2 message was re-read and found to assert, in its test-evidence block, an LTR `PLANX_RUNTIME_MATRIX: PASS (71/71), exit 0, report written` — and then, two sentences later, that on that runtime neither the verdict nor the report is produced. Both cannot hold, and no LTR 71/71 verdict exists: the runtime's completed runs are 69/69 and 70/70, and the 71/71 verdict is 4.2.0's. The claim was false, and it reads as having been carried over from the 4.2.0 line above it. The commit was unpushed with nothing built on it, so the message was corrected in place rather than left for a reviewer to trip over. The amendment is **message-only**: the tree hash is unchanged (`48f7b4b5`), author and committer are unchanged, and the SHA moved `61d3d3c` → `719d4b7`. Every reference in this report uses the new SHA; if `61d3d3c` was already noted anywhere, this is the mapping. The corrected block states the per-case result and says the run-level LTR verdict was not on record. That last part was true when it was written and is no longer: the final-tree LTR sweep returned a few minutes later, with `PASS (71/71)`. Phase 2's message was deliberately left as it stands rather than amended a second time — it was faithful to the evidence available during that phase — and the final verdict lives here instead. The sequence is set out in S8.
13. **This report was corrected after Phase 3 had already been committed.** The sweep described in §4.2 was read as hung, abandoned, and the report was written and committed on that basis. It then returned on its own with `PASS (71/71)`, exit 0 and a JSON report, so §4.2, S8 and this section were wrong in the Phase 3 commit. They are corrected here, in a separate follow-up commit, rather than by rewriting the Phase 3 commit: the phase commits stay as delivered, and the correction is visible as its own commit. That is deliberately the less tidy option and the more honest one.

Explicitly **not** done, per ground rule 11's carve-out for the final phase: no tag, no `release.ps1`, no upload, no push. The version bump, CHANGELOG and `metadata.txt` update were written because Phase 3 is the final phase, and the maintainer releases manually after reviewing this report.

## 6. Commit list

This release's commits, newest first, down to the release it builds on:

```
26a025c phase-3: document both parking tools, bump to 4.12.0
719d4b7 phase-2: add Parking Supply-Demand Balance
e741c47 phase-1: add Parking Demand Estimator (ITE-style rate table)
74e3d4d release: 4.11.2 - quality infrastructure
```

`e741c47` is where this release's code work starts and `719d4b7` is where it stops; `26a025c` changes documentation and version metadata only. The report you are reading is carried by a later commit, subject `docs: correct the report's LTR evidence, which returned after all`, which changes no code, no test and no plugin file — it replaces the report with the corrected version described in S8 and deviation 13. A file cannot name the hash of the commit that introduces it, so both are identified by subject and are readable in `git log`.

Working state at hand-off: nothing is tagged for this release, nothing is pushed, and the release is not cut. This release's own commits are local only, and the maintainer releases manually after reviewing this report.
