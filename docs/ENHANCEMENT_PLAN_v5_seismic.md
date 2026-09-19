# PlanX — Seismic Risk Programme (Enhancement Plan v5 · seismic)

**Audited:** 2026-09-19 · **Plugin state:** v4.13.0, `da3a2ea`, annotated tag `v4.13.0`
**Scope:** the `Seismic Risk` group (`GROUP_SEISMIC`, `algorithms/base.py:55`) extended from
one algorithm to five, as four releases.
**Relationship to `docs/ENHANCEMENT_PLAN_v5.md`:** that document is the broad audit and
quality programme for the 71-algorithm plugin. It lists a candidate `v4.13.0` for traffic
assignment; that number is now taken by the seismic debris rebuild. This document owns the
seismic thread and takes `v4.14.0` upward. It does not supersede the other file.
**Status:** Faz 1 built in the working tree at v4.14.0 (engine, algorithm, provider
registration, icon, runtime-matrix binding, manual card, tests and fixture), not yet
committed, tagged, pushed or uploaded. Faz 2 to Faz 4 are unstarted. The plan text below
is left as written, with Faz 1's deviations from it recorded in §3.1 under "as built" -
the plan is the contract, so where the implementation departed from it the departure is
stated rather than the plan quietly edited to match. **Faz 1 is held only by commit, tag
and upload.** A distance-unit defect found by the matrix's own run log (every receiver
1000× too far) and the inverted unit factor that replaced it are both fixed; the engine
suite stands at 627 checks and the matrix case passes with the new value check.

---

## 0. Baseline (measured, not assumed)

Every row was produced by running something in this repository. The command is named so a
reviewer can re-run it.

| Fact | Value | How measured |
|---|---|---|
| Registered algorithms | **71** | `grep -c "addAlgorithm" provider.py` = 71; `ls algorithms/alg_*.py \| wc -l` = 71 |
| Tool groups | **19** | 19 `GROUP_*` constants, `algorithms/base.py:37–55` |
| Algorithms in `Seismic Risk` | **1** (`planx:seismicdebris`) | `grep -n "GROUP_SEISMIC" algorithms/*.py` |
| Engine modules | 33 files | `ls engine/*.py` |
| Seismic engine | `engine/seismic.py`, 635 lines, **imports no QGIS** | module header; `engine/` is QGIS-free by design |
| Fragility model | Hazus equivalent-PGA, `P(DS≥ds)=Φ(ln(IM/θ)/β)`, β = 0.64, tables 5-37…5-40 | `engine/seismic.py:70,93` |
| Debris outputs today | `debris_vol_m3`, `debris_pile_m3`, `debris_mass_t`, `collapse_prob`, `collapsed`, `damage_state`, `collapse_freq` | `algorithms/alg_seismic_debris.py:448` |
| Hazard input today | `PGA_FIELD` (optional) or `MAGNITUDE` with `effective_pga()` | `alg_seismic_debris.py:43`; `engine/seismic.py:368` |
| Ground-motion model | **none.** `effective_pga` is `reference_pga · exp(0.8(Mw−7))`, documented as carrying "no distance, site class or fault term" | `engine/seismic.py:315–374` |
| Flow accumulation (CTI prerequisite) | `engine/hydro.py`: `fill_depressions`, `d8_flow`, `flow_accumulation`, `hand`, `inundation`, `exposure` | `grep -n "^def " engine/hydro.py` |
| Slope / gradient helper | **none exposed** — `d8_flow` computes slope internally and discards it | `grep -rn "def slope\|np.gradient" engine/*.py` → no match |
| Raster IO idiom | `algorithms/_raster.py`: `read_dsm`, `write_raster`, `write_raster_multiband` | `grep -n "^def " algorithms/_raster.py` |
| Renderer field choice | `_apply_default_renderer` colours by the **last** numeric field matching `score, risk, access, criticality, centrality, coverage, prob, index, cost` | `algorithms/base.py:170–197` |
| Runtime matrix chaining | `VALUE_OVERRIDES` accepts `art:<algid>/<OUTPUT>` references between algorithms | `tests/qgis_runtime_algorithm_matrix.py:600+` |
| Algorithm-count gate | `MIN_EXPECTED_ALGORITHM_COUNT = 71`, a **floor** — adding is safe, dropping fails | `tests/smoke_provider_catalog.py:38,252` |
| Hub security scan | CLEAN at v4.13.0 | `py -3 packaging/pf.py gate planx` |
| Last verify | all 9 gates PASS on 3.44 LTR and 4.2 | `py -3 packaging/pf.py verify planx` |

Two consequences shape everything below:

1. **The chain has one hole, and it is not at the top.** Every stage downstream of ground
   motion now exists and is defensible: fragility curves, damage sampling, debris volumes,
   passability. What is missing is the ground motion itself. Today the tool's best path
   asks the user to bring a PGA field from outside; its fallback is a documented knob.
   Joining the field is fine once, and impossible to defend in a workflow that has to
   state what scenario it ran.
2. **The group has depth in one direction only.** `Seismic Risk` models what an earthquake
   does to buildings and streets. It models nothing about what that does to *people* — and
   that is precisely where the maintained competition stopped.

---

## 1. What we are actually competing with

Stated plainly, because a plan that claims novelty has to survive the check.

| Product | Status | What it does that we do not | Why it does not close our gap |
|---|---|---|---|
| **InaSAFE** | dormant, last substantive release 2021 | scenario-based impact on population and infrastructure | unmaintained; QGIS 3.x era; no fragility-curve depth |
| **GEM IRMT** | active, but as a *web* platform | integrated risk toolkit | its QGIS-side social-vulnerability and recovery modelling was **removed**; the plugin is an upload client |
| **USGS ShakeMap / PAGER** | active, authoritative | real ground-motion fields, fatality estimates | a *service*, not a QGIS workflow; PAGER's non-US rates are not calibrated past 2010 and are explicitly not Hazus |
| **OpenQuake** | active, AGPL, heavy | full probabilistic engine, GMPE library | not QGIS-native, not a plugin, AGPL — we may read its papers, not its code |
| **Hazus** | 7.2 (2026-06); the earthquake model landed in 6.1 (2024-07), was absent from 7.0/7.1, and 6.1's downloads were withdrawn 2026-03 | the methodology everything else cites | Windows/ArcGIS-bound, US data model, no QGIS path |

**The claim this programme makes, and no more than this:** PlanX becomes the only QGIS-native
workflow that goes from a scenario (magnitude and geometry) to a ground-motion field to a
per-building damage distribution to debris, casualties and shelter need, with every constant
traceable to a named table in a named document — and that says out loud which of those
constants are calibrated to Turkey and which are not.

**The claim it does not make:** that any of this is a calibrated Turkish loss model. It is
not, and §2 R6 makes that a rule rather than a wish.

---

## 2. Sourcing discipline — the rules that bind every phase

These are not aspirations. Each one exists because the alternative has already produced a
wrong number somewhere in this ecosystem.

**R1 — Transcribe, never recall.** Every numeric constant comes from a named table in a
named document, and the citation carries the table number. A coefficient written from memory
is indistinguishable from a correct one until it is wrong. **This document therefore
contains no GMPE coefficients, no fragility medians and no casualty rates** — their absence
is deliberate, so that no value can be carried in from this file. The implementation reads
them from the source.

**R2 — The licence line decides the method, not the convenience.**

| Source | Licence | Permitted use |
|---|---|---|
| pyGMM | MIT | read the implementation; **vendor derived test vectors with attribution** |
| USGS gfail, ShakeMap `gmice` | CC0 | read freely |
| liquepy | MIT (note: declares no `scipy` dependency but imports it) | read |
| Jibson 2007 / USGS OFR 98-113 | USGS, public domain | transcribe |
| ASB2014 paper | publisher PDF | transcribe the equations from the paper |
| **OpenQuake / oq-engine** | **AGPL-3.0** | CSV tables used as a **local dev-time oracle only — never committed** |

**R3 — No silent default.** Where a parameter is a modelling choice rather than a data
description — the distance metric above all — it is an explicit enum with no default, and
the run log states what was used. A silent `RJB` produces plausible-looking wrong numbers,
which is the worst failure mode available to us.

**R4 — Applicability envelope, enforced and reported.** Every model carries its published
validity range as a checked guard. Outside it the tool either refuses or warns and stamps
the output; it never extrapolates quietly.

**R5 — Provenance is written.** Every new tool emits a manifest through the existing
`engine/provenance.py` (`SCHEMA = "planx-analysis-manifest-v1"`, `build_manifest`,
`fingerprint`): model name, source table, every parameter, the applicability verdict. This
is the generalisation of the v4.13.0 caveat into a mechanism.

**R6 — Uncalibrated is stated in the interface, not only in the changelog.** Any constant
that is a US or European value used by analogy carries `UNCALIBRATED` in the code comment,
a sentence in `shortHelpString`, and a line in the manual card.

**R7 — A missing input is not a missing hazard.** Where a model needs a dataset the user
may not have (a liquefaction susceptibility map, a water-table depth), the tool must fail
loudly or refuse. Hazus's own manual permits the opposite — *"Without user input, Hazus
assumes no PGD occurs"* — and a planner reading that output as "no ground-failure risk here"
is the single most dangerous failure this programme can introduce. A test asserts the
warning, not just the number.

---

## 3. The four phases

Each phase is one release, gated by the full ritual in §6 before the next begins.

### 3.1 Faz 1 — `v4.14.0` · `planx:groundmotion`

**Why first.** It is the missing link. It fills `PGA_FIELD` from inside the plugin, which
turns a four-step workflow with an external dependency into a self-contained one, and it
gives every later phase a shaking field to stand on.

**Model: ASB2014** — Akkar, Sandıkkaya & Bommer (2014), *Bulletin of Earthquake
Engineering* 12(1), 359–387, DOI `10.1007/s10518-013-9461-4`.

The choice is measured, not aesthetic: ASB2014 is a component of Turkey's 2018 national
seismic hazard map logic tree at weight 0.30. **Akkar & Bommer (2010), the model one would
reach for first, is not in that tree at all** and is not implemented in pyGMM. The earlier
research that pointed at AB2010 was wrong, and this plan does not repeat it.

**Functional form.** Verified against the reference implementation before this plan was
finalised, not sketched from expectation — an earlier draft of this section invented
site-class terms (`S_S`, `S_A`, `S_N`) that **ASB2014 does not have.** The model takes its
site terms from Vs30 alone. The real form, in the paper's own symbol names and
deliberately without numbers:

```
ln Y_ref = a1 + a3(8.5 − Mw)² + [a4 + a5(Mw − c1)] · ln( √(R² + a6²) )
         + a2(Mw − c1)   if Mw ≤ c1
         + a7(Mw − c1)   if Mw > c1          (magnitude saturation)
         + a8 · δ(NS) + a9 · δ(RS)           (strike-slip is the reference)

ln Y     = ln Y_ref + site term
```

Three properties of this form are load-bearing, and each was measured before being
written down:

1. **The nonlinear site term is a function of the rock PGA at the same site**, so rock
   motion is computed first and the site term applied second. Computing them in one pass,
   or in the other order, produces numbers that are smooth, monotone and wrong.
2. **The site term is not monotone in Vs30 at short periods, and that is correct.** Measured
   at Mw 7, R = 20 km, PGA runs 0.1459 / 0.1625 / 0.1742 / 0.1461 / 0.1295 g at Vs30 of 150
   / 200 / 400 / 750 / 1000 — it **peaks at 400 m/s** because the nonlinear term suppresses
   short-period motion on soft soil. Sa(1.0) over the same sweep is cleanly monotone
   (0.2775 → 0.0797 g). A naive "softer is always stronger" assertion would therefore encode
   a falsehood, pass nowhere, and be "fixed" by breaking the model. The test asserts
   monotonicity **at long periods only**, and asserts the short-period reversal explicitly
   so that a future change which flattens it fails.
3. **Vs30 above 1000 m/s is capped** (`min(Vs30, v_con)`); 1000 and 1200 give bit-identical
   results. The log says when the cap bites, because a user who enters 1200 m/s deserves to
   know they received a 1000 m/s answer.

**Inputs — as built.** The table below is what shipped, and it is narrower than the
first draft of this plan in three places. Each narrowing is recorded with its reason,
because this plan is a contract with later phases and not a wish list.

| Parameter | Type | Notes |
|---|---|---|
| `SCENARIO` | enum, default point | `point` (one epicentre) / `fault` (a trace) |
| `MAGNITUDE` | number | Mw |
| `EPICENTRE` | point feature source, optional | scenario = point; refuses a multi-feature layer |
| `DEPTH_KM` | number | scenario = point; the only geometry where Rhypo differs from Repi |
| `FAULT_TRACE` | line feature source, optional | scenario = fault |
| `DISTANCE_METRIC` | enum, default `RJB` | `RJB` / `Repi` / `Rhypo`; the choice is written to every row |
| `FAULT_MECHANISM` | enum, default strike-slip | strike-slip / normal / reverse |
| `VS30` | number, default 750 m/s | the model's own reference velocity, where its site term is zero |
| `VS30_FIELD` | field on `RECEIVERS`, optional | overrides the constant; an empty cell falls back and is flagged |
| `SPECTRAL_PERIODS` | string, optional | comma-separated seconds; no interpolation (see below) |
| `EPSILON` | number, default 0 | number of sigma above/below the median; 0 = median |
| `RECEIVERS` | feature source, any geometry | one row out per row in |
| `OUTPUT` | sink | the receiver layer, plus the new columns |

Three deliberate deviations from the version of this table that preceded the build:

- **No `DIP` / `DEPTH_TOP`, and no `Rrup`.** The model has no Rrup term, so an extended
  rupture is evaluated at the Joyner-Boore distance, measured to the trace. For the
  near-vertical crustal ruptures the model was built for, the trace *is* the rupture's
  surface projection and the distance is right; on a shallow-dipping thrust the real
  Joyner-Boore distance is shorter and the shaking is understated. The tool says so in its
  help text and its run log rather than offering dip parameters it cannot use.
- **No raster mode, and therefore no `OUTPUT_RASTER`, `ROI` or `CELL_SIZE`.** A scenario
  grid is QGIS's own *Create grid* fed into `RECEIVERS`. The reason is a test-harness
  contract rather than a modelling one: the runtime matrix supplies every declared
  destination with a path and fails a run whose destination is never produced, and it never
  supplies an extent - so a declared raster output would have been a permanent matrix
  failure with raster mode unreachable. A destination that can only fail is worse than a
  grid the user builds and can see in the model designer.
- **`DISTANCE_METRIC` carries a default (`RJB`) where R3 first said "no default".** R3
  exists so that a modelling choice is never made silently; a combo box whose default is
  *written into every output row* satisfies it, because the choice is visible in the result
  rather than remembered. R3 still governs the site term, where the default is the one value
  at which the model's site term is exactly zero: a default run reports rock-reference
  motion, and every bit of amplification in a result is a user decision.
- **The distance is converted from the CRS's units, and the conversion is not optional.**
  This plan's first draft did not mention the unit at all, which is how the first build
  shipped without it: `point_distances` returned the layer's raw linear units and `predict`
  read them as kilometres. Every distance came out 1000× too large — the matrix run put a
  demo city 750 m across at 472 km from the epicentre, and 34 of 34 receivers "outside" the
  model's range. The engine's distance functions now take a required `units_per_km` with no
  default, the algorithm reads it off the receivers' CRS, and an extended rupture is
  reprojected into the receivers' CRS before it is measured, so a trace in a different
  projection is not silently mixed in.

  The unit factor was then written the wrong way round on the first attempt — the model
  reported 471 993 km — and the new value check failed the case on the very next run. That
  is the argument for having it: the factor is now the second place in this phase where a
  plausible-looking number was wrong, and the first where the harness said so.

**The gate hole this exposed.** `tests/qgis_runtime_algorithm_matrix.py` asserted that
every declared destination was produced and non-empty, and nothing about the values in it.
No unit error can ever fail that question, which is why the 1000× error passed a green
matrix. The matrix now carries `VALUE_EXPECTATIONS`, a per-tool check on the demo run's
numbers, applied only after the ordinary verification passes — so a complaint from it is
always "this value is wrong", never "this output is missing". It has one entry today, the
ground-motion distance; the hook exists for the later phases and for any tool that
converts a unit.

**Applicability guard (R4).** The envelope is transcribed from the paper's own stated
range at implementation and encoded as data, not as literals scattered in branches: a
magnitude band, a distance ceiling, a focal-depth ceiling and a Vs30 band. Out-of-envelope
receivers are flagged in the output `caveat` column and counted in the log; the run does
not silently drop them. As built there is no period band to guard, because a period the
paper does not tabulate is refused outright rather than interpolated.

**Verification — this phase has the strongest oracle in the whole programme, and it is
independent of our implementation.**

1. **Committed regression fixture, generated by pyGMM (MIT).** Input→output vectors
   produced with pyGMM, which the authors' own spreadsheet generated. Committed as a
   fixture with a `THIRD_PARTY_NOTICES` entry. This is a genuine oracle: it cannot lock in
   our bugs, because our code did not produce it.
2. **Local cross-check, not committed (R2).** GEM OpenQuake's `AKKAR14` tables — twelve
   files crossing three distance metrics with mean and three sigma components. Run at
   development time, never vendored.
3. **A free invariant, straight from the published tables.** `σ_total ≈ √(σ_between² +
   σ_within²)` in every one of the three tables — measured worst deviation **4.8 × 10⁻⁵**,
   which is the coefficients' own four-decimal rounding, not a modelling gap. The test uses
   a 5 × 10⁻⁵ tolerance; asserting exactness would fail on the source's rounding, and
   loosening it to 1 × 10⁻³ would stop catching a real transcription slip.
4. **Monotonicity, stated to the precision the model actually has.** PGA increases with Mw
   at fixed R (measured at R = 10 km: 0.0274 / 0.0651 / 0.1464 / 0.2591 / 0.2737 / 0.3024 /
   0.3295 g at Mw 4 / 5 / 6 / 6.75 / 7 / 7.5 / 8) and decreases with R at fixed Mw (0.4928 g
   at 1 km → 0.0106 g at 200 km). The site term is asserted monotone **at long periods
   only** — see the note below.
5. **Envelope behaviour.** A receiver outside the published range produces a flag and a log
   line — asserted, because an unguarded extrapolation is invisible in the output.

**Honest limitations to state in `shortHelpString`, the manifest and the manual card.** The
model is a European and Middle Eastern crustal model; it carries no basin term, so deep
soft-soil amplification is not represented. It predicts a *median*, not a design level. It
is not a substitute for the national hazard map, and a scenario run is not a probabilistic
result.

---

### 3.2 Faz 2 — `v4.15.0` · `planx:seismicimpact`

**Why second, and why this is the phase that matters most.** Research across the QGIS
plugin ecosystem found **no maintained plugin that models earthquake consequences for
people.** InaSAFE is dormant; GEM removed its social-vulnerability and recovery modelling.
So "my buildings, my scenario → how many are injured, how many households need shelter" is
a gap with nothing standing in it — and it chains directly off the `damage_state` field
`planx:seismicdebris` already writes.

**Prerequisite inside this phase, and it carries a trap.** Casualty and shelter models want
the damage *distribution*, not one sampled realisation: the expected number of injuries is
`Σ_severity Σ_state occupants · rate(severity | state, occupancy) · P(state)`. Today
`alg_seismic_debris` writes only `collapse_prob` and a sampled `damage_state`. So this phase
first appends four columns — one probability per damage state — to `output_fields()`
(`alg_seismic_debris.py:448`).

**The trap, precisely.** `_apply_default_renderer` (`base.py:174–176`) colours the output by
the **last** numeric field whose name contains one of `…, prob, …`, scanning in field order.
Appending `prob_complete` *after* `collapse_prob` silently repaints every map the tool has
ever produced, and per the v4.13.0 finding **no count-based test catches it.** The new
columns are therefore **prepended before `collapse_prob`**, which stays last among the
token-matching fields and keeps the rendered field unchanged. A test asserts the rendered
field name against `output_fields()` so a future reorder fails rather than repaints.

**Model: Hazus 6.1 §12 (casualties) and §13 (shelter).** Transcribed, per R1: Eq. 12-3…12-6
with Tables 12-1, 12-2 and 12-3…12-11; Eq. 13-1…13-5 with Tables 13-1, 13-2 and 13-3. Note
for the implementer: **the equations are raster images in the PDF and must be read
visually; the tables extract as text.**

**The structural problem, and the honest answer to it.** The shelter and casualty equations
consume US census percentages — income, ethnicity, tenure, age. None of that exists for a
Turkish city. The answer is not to invent equivalents and not to omit the terms:

- the **structure** of the equations is implemented;
- every demographic modifier **defaults to neutral** (multiplier 1.0), which is exactly the
  case Hazus 6.1 itself exposes as GUI-editable;
- the modifiers are **parameters**, so a planner who has real local data supplies it and a
  planner who does not gets an unfiltered result rather than an American one.

This gets a test of its own: **with default parameters the modifier vector must be exactly
all-ones.** A "neutral" default that quietly multiplies by 1.05 is the failure this check
exists to prevent.

**Inputs.** `BUILDINGS` (the debris tool's output, or any layer carrying the four
probability fields, or a single damage-state field as a coarser fallback); `OCCUPANCY_SOURCE`
(`field` → `POPULATION_FIELD`, or `area` → floor area ÷ `AREA_PER_OCCUPANT`); `TIME_OF_DAY`
(drives the indoor/outdoor split); the demographic modifier parameters; `SEVERITY_LEVELS`
(fixed 1–4).

**Outputs.** Per building: expected casualties by severity, and the shelter need (displaced
households, temporary vs. public shelter requirement). Plus a summary via `feedback.pushInfo`
and a manifest.

**Verification.**

1. **Conservation:** `Σ severity counts ≤ occupancy`, always. A violation is a bug by
   definition and is the cheapest possible property test.
2. **Monotonicity:** fatalities per building are non-decreasing as the complete-damage
   probability rises toward 1.
3. **The neutral-default test above.**
4. **Degenerate case:** all damage `none` ⇒ zero casualties, asserted.
5. **Chaining, in the matrix:** `BUILDINGS` binds to `art:planx:seismicdebris/OUT_BUILDINGS`,
   so the end-to-end scenario→debris→casualties workflow is executed, not merely declared.
6. **Anti-fabrication:** the shelter ladder that everyone expects — "Day 1 / Week 1 /
   Month 2" — **is not in Hazus.** Verified by full-text search of both the 477-page
   earthquake and 809-page hurricane technical manuals: zero hits. Hazus's time steps are
   Day 1/3/7/14/30/90 and belong to facility and infrastructure restoration. If this tool
   ever needs a ladder, it is our construct and it will be labelled as ours.

**Deliberately not in this phase:** repair cost and downtime. See §4.

---

### 3.3 Faz 3 — `v4.16.0` · `planx:liquefaction`

**Why third.** It is the one secondary ground-failure hazard that can be run from the layers
a user actually has. Research established the key negative result: **no ground-failure
method works from PGA alone** — they all want a water-table depth, rainfall, or a modelled
susceptibility surface. Zhu et al. (2015) is the exception, and its two extra inputs are
derivable from a DEM we already know how to read.

**Model: Zhu, Daley, Baise, Thompson, Wald & Knudsen (2015)**, *Earthquake Spectra* 31(3),
1813–1837, DOI `10.1193/121912eqs353m`:

```
X = c0 + c1 · ln[ (PGA/100) · (Mw^c2 / 10^c3) ] + c4 · CTI − c5 · ln(Vs30)
P = 1 / (1 + e^(−X))
```

Coefficients per R1; the clamp ranges (`CTI` and `PGA` are clipped to the ranges the paper
calibrated on) are transcribed with the coefficients and reported in the log when they bite.

**The two prerequisite engine additions, both small and both honestly new:**

1. **Slope.** `engine/hydro.py` has none exposed — `d8_flow` computes slope internally and
   discards it. Add `slope_radians(dem, pixel)` to `hydro` and reuse it inside `d8_flow` so
   the two cannot drift.
2. **CTI.** `CTI = ln(a / tan β)` with `a` the specific catchment area. `flow_accumulation`
   already returns upstream cell counts, so `a = accumulation · pixel`, and the wetness
   index is `ln(accumulation · pixel / tan β)` — a handful of lines over machinery that
   already exists and is already tested.

**Vs30.** Wald & Allen (2007) is the natural pairing, and the research corrected a
misconception about it: there is **no two-branch `log(Vs30) = a + b·log(slope)` regression
in USGS OFR 2007-1357.** What is published is a table — slope bins mapped to NEHRP site
classes. That makes it *easier* for us, not harder: it transcribes as a table with no
coefficients. Users with a real Vs30 raster supply it instead.

**Two modes, and only one of them may stay quiet.**

- **Regression mode (default):** Zhu 2015, from PGA + CTI + Vs30. Runs from what the user has.
- **Susceptibility mode:** Hazus Tables 4-11/4-12/4-13 with 4-10 and the `K_M`/`K_W`
  corrections, which requires a liquefaction susceptibility map. **This mode refuses to run
  without one**, and the interface says why in the terms R7 sets out: *a missing
  susceptibility map means no result, not no hazard.* A test asserts the refusal, because a
  silent "no ground failure" is a plausible-looking wrong answer of the worst kind.

**Verification.** `X` monotone increasing in PGA and CTI, decreasing in Vs30; the logit is
bounded in (0,1) and never evaluated unclipped; a homogeneous plane gives the analytic CTI;
a synthetic DEM gives a CTI surface against a hand-computed value; susceptibility mode
raises without a map. **The exponent trap gets its own test:** the seismic term is not a
plain `ln(PGA)` — the magnitude scaling is folded *inside* the logarithm, and writing the
obvious `c1·ln(PGA) + …` produces a smooth, monotone, wrong surface that nothing else would
catch.

---

### 3.4 Faz 4 — `v4.17.0` · `planx:coseismiclandslide`

**Why last.** It is the least defensible of the four, and it is last because of that rather
than in spite of it. It is also last because the others are the ones a planner reaches for.

**Model: Jibson (2007)**, *Bulletin of the Seismological Society of America* 97(4),
1206–1219 — the Newmark-displacement regression:

```
Eq. 6:  log D_N = a + b·log(1 − a_c/PGA) + c·log(a_c/PGA)
Eq. 7:  the same with a magnitude term added
```

Coefficients per R1. The better citation for a GIS implementation is actually the free one:
**Jibson, Harp & Michael (1998), USGS OFR 98-113** carries the whole GIS workflow, open
domain, no paywall — cite that as the primary and the 2007 paper for the regression.

**Critical acceleration.** `a_c = (c' / γ·t·cos θ + tan φ'·(tan θ/tan φ') ... )` needs
cohesion and friction angle, which users do not have as layers. Two answers, both honest:

1. A **strength-by-geologic-unit table shipped with the tool**, editable, with each row
   carrying its source — clearly marked as literature values, not as site data.
2. **Hazus Tables 4-14/4-16/4-17** with a three-class Group A/B/C geology map.

**Jibson's own disclaimer goes in the interface verbatim in spirit** — *not for site-specific
design; for regional-scale screening and rapid preliminary assessment.* That is exactly our
use case; saying so is the difference between a defensible tool and an overclaim.

**A trap we would otherwise build into our own test suite.** The runtime matrix carries the
comment *"A city DSM stands in wherever a tool wants a terrain DEM."* For a slope-based tool
that is actively wrong: the demo city's DSM includes roofs, so slope would measure
**roof pitch**, the tool would produce a full, plausible, non-empty output, and the case
would read green. This is the slope-shaped repetition of the v4.13.0 defect in which a
centreline layer satisfied a polygon input and every areal output came back zero. **This
phase requires a synthetic terrain fixture** — a DEM built for the purpose, not borrowed —
and a test asserting the slope statistics of that fixture, so that a future reuse of the
city DSM fails loudly.

**Verification.** `D_N → 0` as `a_c/PGA → 1`; `D_N` falls monotonically as `a_c` rises;
`D_N` rises with Mw under Eq. 7; the synthetic-terrain fixture check above; and an explicit
assertion that the output records which strength source was used (table row or geology
class), because an unlabelled `a_c` is an unattributable number.

---

## 4. Rejected, with the reason

Written down because each of these is the obvious next suggestion, and a plan that silently
omits them invites the same conversation twice.

| Rejected | Reason |
|---|---|
| **Zhu et al. (2017)**, **Asadi et al. (2024)** liquefaction | Both need water-table depth and/or rainfall. Asadi 2024 is genuinely attractive — calibrated on the 2023 Türkiye sequences — but its USGS implementation **deviates from the published coefficients on purpose** ("sign changed from original") and the paper is paywalled, so we could not establish which is correct. Publishing an unverifiable model as "Türkiye-calibrated" is the worst outcome available. |
| **Nowicki Jessee et al. (2018)** landslide | The per-lithology GLIM and per-landcover coefficient tables could not be obtained from any accessible source; the USGS implementation carries `b3 = b5 = 1.0` as bare literals. **Not transcribable, therefore not implementable** under R1. |
| **Hazus repair cost / downtime** | `$`/m² come from RSMeans (commercial) and repair durations from ATC-13 (1985, paid). The engine is not reproducible. Only published ratios and published unit costs could be used, and that is not "Hazus". **A real opportunity sits here** — a transparent, parameterised cost basis is something Hazus cannot offer — but it is its own release with its own sourcing plan, not a subsection of this one. |
| **PAGER fatality rates** | Not calibrated past 2010 and uses non-Hazus rates outside the US. Using it would mean two casualty models in one plugin with different provenance and no way to reconcile them. |
| **Probabilistic fault displacement (PFDHA)** | Site-specific; a regional screening version would be fabrication. A deterministic **proximity screen** (Wells & Coppersmith 1994, free) is defensible and is noted here as a possible fifth release, not a fourth. |
| **Landlab** | Definitively has no Jibson/Newmark/Arias component. Checked, so we stop checking. |
| **oq-engine, gmpe-smtk** | AGPL. Read the papers, never the code (R2). |

---

## 5. Cross-cutting traps

Beyond the per-phase traps above, these apply to every phase and are the ones that fail
*silently*.

1. **Field order repaints the map.** `base.py:174–176` picks the last token-matching numeric
   field. Faz 2 prepends its new columns for this reason; any phase that adds a numeric
   output field re-checks the rendered field name against `output_fields()`.
2. **A fixture standing in for the wrong thing.** The city DSM for terrain (Faz 4), a
   centreline for a polygon (already burned us at v4.13.0). Both produce full, green,
   meaningless output. Every new fixture states in a comment what it is *not*.
3. **A model's no-data layer is not a zero layer.** A raster output where "no result" and
   "zero displacement" are both `0.0` is unreadable and untestable. Every raster phase
   writes a distinct nodata value and documents it.
4. **The transcribe-don't-recall rule has a mechanical form.** Each transcribed table gets a
   single module-level dict with the table number in the comment above it, and a test that
   checks the table's own internal invariants (σ decomposition in Faz 1, monotonicity of
   severity rates by damage state in Faz 2, coefficient counts per period in Faz 3). A
   transcription error then fails a test instead of shipping.
5. **An extra run nobody verifies is not coverage.** Carried from TRAPS 5.6. Every new
   `EXTRA_RUNS` case goes through the same `verify_outputs` path with an `only=` argument.
6. **`%` in `metadata.txt` breaks the Hub upload** (configparser interpolation). No literal
   percent sign in the new descriptions or changelog entries.
7. **`QgsField(name, int)` is a hard `TypeError` on QGIS 4** and `hub_qt6_scan.py` cannot
   see it. New fields use the `DOUBLE`/`INT`/`STRING` constants in `algorithms/base.py`.
8. **Bandit B110 blocks a Hub version and `# nosec` does not help.** No `try/except: pass`
   in new code; `contextlib.suppress` where suppression is genuinely intended. Never add a
   `.bandit` skip file.
9. **A blocked Hub version number is burned.** Nothing in this programme uploads; that is
   the owner's step and it is manual.

---

## 6. Verification ritual (every phase, both runtimes)

```powershell
py -3 packaging/pf.py verify planx        # all gates, 3.44 LTR and 4.2
py -3 packaging/pf.py gate planx          # Hub security scan standalone + Qt6 advisory
py -3 tests/test_engine.py                # pure engine suite, no QGIS
py -3 packaging/pf.py attribution         # Rule 0 — no AI attribution, ever
```

Per phase, additionally:

- **Pure engine tests** for every new engine module, written so they fail if the module is
  deleted: a new module with no test is not finished.
- **Runtime matrix** entry for every new algorithm, with inputs bound — a new algorithm
  absent from the matrix is untested, because the matrix is the only thing that proves an
  algorithm *executes*.
- **Renderer assertion** for any algorithm adding numeric fields (§5.1).
- **Manual card** at the depth of the neighbouring cards: numbered equations, parameter
  table, the applicability envelope, and the honest-limitations paragraph. The manual is
  hand-maintained and edited by targeted splice, not regenerated — so the card is a splice,
  and the equation numbering continues from the current maximum.
- **`metadata.txt`** version, description and changelog; **`CHANGELOG.md`** section.
- **Provenance manifest** present in the output of every new tool (R5).
- **Rule 0:** commits in Yusuf Eminoğlu's name alone, no `Co-Authored-By`, no generated-by
  trailer. The hooks and `pf attribution` enforce it; if they cannot be satisfied, stop.

Release is a separate, owner-controlled step: tag annotated, `planx v<version>` message, in
the style of `v4.10.x`–`v4.13.0`. Push and Hub upload are not part of this plan.

---

## 7. What this plan deliberately does not decide

- **Whether the four phases all ship.** Faz 1 and Faz 2 are the programme's argument —
  the chain closed and the unoccupied gap filled. Faz 3 and Faz 4 add depth. Stopping after
  Faz 2 is a coherent outcome and is not a failure.
- **Whether the Hazus design-level mapping is revisited.** v4.13.0 documented the
  Turkish-regulation-year mapping as an uncalibrated analogy. Calibrating it is real
  research with real data requirements and is not in scope here.
- **The cost model.** Named as an opportunity in §4 and left there.
- **The `planx_urban_resilience` duplicate.** The same seismic constants are duplicated in
  that plugin's `processing/seismic/monte_carlo_debris.py:247–256`. Separate git
  repositories, so the port happens in that plugin's own release; until then the two models
  drift. Restated here because this programme widens the drift.
