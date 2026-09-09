# PlanX Enhancement Plan v4.12 — Parking Demand & Supply-Balance

**Target release: 4.12.0** (the release itself is NOT your job — see §0.9).
**Baseline: v4.11.0** — 69 algorithms, 19 tool groups. Verified fresh
against the current tree, not against `ENHANCEMENT_PLAN_v4.9.md`'s baseline
(v4.8.0/65 algorithms) — that plan's five features shipped and the plugin
has moved two more releases past it (v4.10.x/v4.11.0 added provenance
manifests, PlanX Studio search, directed routing, multi-threshold
accessibility, Monte Carlo weight sensitivity, GTFS reliability windows,
solar/mode-split calibration options). This plan does not continue that
backlog — it identifies a fresh, real gap.

**One paragraph:** Across 69 algorithms spanning network analysis, space
syntax, transit/GTFS, land use, solar/shadow, hazard screening, equity and
demographic modeling, **there is no parking analysis of any kind** —
verified by grep across the whole `algorithms/` tree for "parking", zero
hits. This is a real, well-defined gap directly adjacent to an existing
tool: `alg_trip_generation.py` already implements a per-capita/per-job
rate-based trip generation model in the `GROUP_DEMAND` group; parking
demand estimation is the same well-established methodology family
(standard land-use-based generation rates, e.g. the ITE Parking Generation
convention), just producing parking-space counts instead of trip counts,
and pairs naturally with an optional supply-comparison step when a real
parking-inventory layer exists — something trip generation has no
equivalent for, since trips don't have a fixed "supply."

---

## 0. Ground rules (hard requirements — each one has burned us before)

1. **Read this whole file first. Touch ONLY the files listed in §7.** Do
   not refactor, reformat, or "improve" anything outside scope.
2. **100% English** in all code, help, docs. Never use the words "elite",
   "best-in-class", "ultimate" or similar self-praise in any copy.
3. Every algorithm help string ends with a **"How to read the results"**
   section followed by a **"Using the results"** passage — `scratch/
   planx_import_check.py` asserts the former's presence on ALL algorithms;
   confirm this script still exists and still runs as part of your gate
   before assuming it will catch a miss.
4. **No dead knobs**: every parameter you declare must change the output.
   Every parameter you read must be used in the computation.
5. **Determinism**: no unseeded randomness, no `hash()`, no set/dict
   iteration order affecting results.
6. **Copy the sibling pattern.** `alg_parking_demand.py` imitates
   `alg_trip_generation.py` directly: same `PlanXAlgorithm` base, same
   `GROUP_DEMAND` group constant, same rate-parameter-per-field-per-zone
   structure, same output-field-naming convention. Where the two
   necessarily differ (parking is a per-land-use-category rate table, not
   a flat per-capita/per-job rate), follow whichever existing PlanX
   algorithm already has a per-category rate-table UI pattern (check for
   one — e.g. `alg_land_use_balance.py`'s per-capita standards table is a
   plausible model — before inventing a new UI convention for entering
   multiple rates).
7. **Frozen IDs, byte-for-byte compatible extensions:** if any existing
   algorithm's parameters or outputs are touched (they should not need to
   be for this plan — it is purely additive), existing ids/fields/behaviour
   at default values must not change.
8. **No AI attribution** in commits (no `Co-Authored-By:` trailers of any
   kind).
9. **Do not bump the version, write the changelog, or release** — see the
   monorepo's `RELEASING.md`. The maintainer releases manually after
   reviewing your report.
10. One commit per completed phase, e.g.
    `phase-1: add Parking Demand Estimator (ITE-style rate table)`.

---

## 1. Baseline facts (verified against the current tree)

- 69 algorithms, 19 groups, `GROUP_DEMAND` already exists and holds
  `alg_trip_generation.py` (production/attraction rates in
  trips-per-capita / trips-per-job applied to a zone layer's population/
  employment fields → a new `QgsProcessingParameterFeatureSink` result
  with generated-trip fields).
- Zero parking-related algorithms anywhere in `algorithms/` (verified by
  grep, not assumed).
- `PlanXAlgorithm` (`algorithms/base.py`) is the shared base: per-tool
  icon, translation helper, geometry extraction, a `GROUP` class
  attribute for grouping.

---

## Phase 1 — Parking Demand Estimator

**What.** A new algorithm, `algorithms/alg_parking_demand.py`
(`name()`: `parking_demand`, `displayName()`: `"Parking Demand Estimator"`,
`GROUP = GROUP_DEMAND`), estimating parking space demand for a zone/parcel
layer using standard land-use-based generation rates — e.g. spaces per
dwelling unit (residential), spaces per 1,000 m² gross floor area
(commercial/office), spaces per seat (assembly/restaurant) — entered as a
per-land-use-category rate table (find and reuse whichever existing PlanX
UI pattern already handles a multi-row rate table, per ground rule 6,
rather than building a new one). The zone layer needs a land-use-category
field and a size/unit-count field (dwelling units, floor area, or seats,
whichever the category calls for); output is the input layer plus a
computed parking-demand field per zone, with per-category subtotals
reported in the algorithm's log/output summary.

**Design notes.**
- Cite the ITE Parking Generation manual (or an equivalent, real,
  verifiable standard) as the methodological basis in the help text and
  manual entry — do not present made-up rate numbers as if they were an
  authoritative standard; the tool's *defaults* can be reasonable
  illustrative starting values, but the help text must say plainly that
  local rates should be substituted, exactly the same honesty stance
  `alg_trip_generation.py` already takes with its own default rates
  (check its help text's exact wording and match that stance).
- Mixed-use reduction and shared-parking discount factors (real,
  well-established refinements to raw generation-rate parking estimates)
  are a plausible follow-on but are **out of scope for this phase** — ship
  the raw per-category rate model correctly first; record the reduction-
  factor omission as a deferred shortcoming, not a silent gap.

---

## Phase 2 — Parking Supply-Demand Balance

**What.** A new algorithm, `algorithms/alg_parking_balance.py`
(`name()`: `parking_supply_balance`, `displayName()`:
`"Parking Supply-Demand Balance"`, `GROUP = GROUP_DEMAND`), taking Phase 1's
demand output plus a real parking-inventory layer (points or polygons
representing actual parking facilities/spaces, with a space-count field)
and computing, per zone, the surplus or deficit between estimated demand
and actual counted supply within that zone (or within a configurable search
radius, for a more realistic walk-to-parking assumption — reuse this
plugin's existing service-area/isochrone infrastructure for that radius
computation rather than a naive straight-line buffer, if a suitable
existing helper is available; a straight-line buffer is an acceptable
fallback if not, but say which was used in the report).

**Design notes.**
- This is the one tool in the pairing with no equivalent elsewhere in the
  plugin (trip generation has no "supply" concept to balance against) — so
  there is no sibling pattern to copy for the balance computation itself;
  the *demand* half of this algorithm's inputs should still come from
  Phase 1's output shape, not a reimplementation.
- A zone with no parking-inventory features nearby is a real, expected
  case (undercounted or genuinely unserved), not an error — the output
  must distinguish "zero supply found" from "supply data absent for this
  zone" if the inventory layer only partially covers the study area, since
  conflating the two would misrepresent a data-coverage gap as a real
  deficit.

---

## Phase 3 — Documentation, registration, version bump

Only after Phases 1–2 are done and tested:
- Register both algorithms in the provider; confirm PlanX Studio's
  search/favorites/recent-tools index (added in v4.11.0) picks them up
  automatically or needs an explicit registration step — check how the
  most recently added algorithms (v4.11.0's OD routes, walking slope,
  street comfort) were wired into Studio and match that.
- Write both `shortHelpString()`s with the required "How to read the
  results"/"Using the results" sections (ground rule 3).
- Add both to `docs/PLANX_REFERENCE_MANUAL.html` in the Demand group
  section, matching the manual's existing per-algorithm depth.
- Update `README.md`'s algorithm count (69 → 71) and `CHANGELOG.md` with a
  new `## [4.12.0]` entry.
- Bump `metadata.txt`'s `version=4.12.0`.
- Do **not** tag, run `release.ps1`, or upload.

---

## Known shortcomings register (fix or explicitly defer with reason)

| # | Shortcoming | Severity | Phase |
|---|---|---|---|
| S1 | Mixed-use reduction / shared-parking discount factors are real refinements not included in this plan — must be stated as future work, not silently absent | Medium | 1 |
| S2 | Default generation rates are illustrative, not a substitute for a real local standard — the help text must say so as plainly as `alg_trip_generation.py` already does for its own rates | Medium | 1 |
| S3 | "Zero supply found" vs. "supply data not collected for this zone" must be distinguishable in Phase 2's output, not conflated | Medium | 2 |
| S4 | Whether a proper network/isochrone-based search radius or a straight-line buffer was used for Phase 2's zone-to-supply matching must be stated explicitly in the report | Low | 2 |
| S5 | Confirm `scratch/planx_import_check.py` (the help-string-section assertion script referenced in ground rule 3) still exists at that path and still runs cleanly before relying on it as a gate | Low | 3 |

---

## 7. Files this plan touches

- `planx/algorithms/alg_parking_demand.py` (new)
- `planx/algorithms/alg_parking_balance.py` (new)
- `planx/algorithms/provider.py` (registration)
- `planx/docs/PLANX_REFERENCE_MANUAL.html` (new manual entries)
- `planx/README.md`, `planx/CHANGELOG.md`, `planx/metadata.txt` (Phase 3 only)

---

## R. Required response format

Deliver a single file `REPORT_v4.12.md` in the plugin root:

```markdown
# Implementation Report v4.12.0
## 1. Phase status
Phase 1: DONE|PARTIAL — <one line>
Phase 2: DONE|PARTIAL — <one line>
Phase 3: DONE|PARTIAL — <one line>
## 2. Shortcomings register outcomes
S1–S5, plus any NEW shortcomings discovered, numbered S6+
## 3. New algorithm summary
| algorithm id | displayName | inputs | outputs | rate-source citation |
(2 rows)
## 4. Test evidence
### 4.1 pure/engine unit checks (verbatim, complete)
### 4.2 e2e QGIS 3.44 output (verbatim, complete)
### 4.3 e2e QGIS 4.x output (verbatim, complete)
### 4.4 dashboard checks (verbatim, complete)
## 5. Deviations from this plan
## 6. Commit list
(hash + message, one per line)
```

**Honesty over completeness:** a PARTIAL with truthful evidence is
acceptable; a DONE that the reviewer's re-run contradicts invalidates the
delivery.
