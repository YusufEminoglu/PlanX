# PlanX — Enhancement Plan v5

**Audited:** 2026-09-19 · **Plugin state:** v4.11.1, branch `main`, clean tree, HEAD `b28f7c3`
**Scope:** the 69-algorithm plugin **and** its reference manual as one deliverable.
**Supersedes:** `docs/ENHANCEMENT_PLAN_v4.12.md` — its Parking Demand work becomes Release 1
here, unchanged, keeping its own ground rules and its three phases. The v4.12 file is kept for
the record.
**Status:** plan only. Nothing in this document has been implemented. No file was modified by
the audit, and nothing was released, tagged, pushed or uploaded.

---

## 0. Baseline (measured, not assumed)

Every row was produced by running something. The command or file is named so a reviewer can
re-run it.

| Fact | Value | How measured |
|---|---|---|
| Registered algorithms | **69** | `grep -c "addAlgorithm" provider.py` = 69; `ls algorithms/alg_*.py \| wc -l` = 69 |
| Groups | **19** | 19 `GROUP_*` constants, `algorithms/base.py:31–49`; all 19 used |
| Python LOC | **26,820** | `find -name "*.py" \| xargs wc -l` (engine 7,254 · algorithms 16,064) |
| Engine modules | 32, of which **26 numpy-only and 0 importing QGIS** | `grep -rn "^\s*\(import\|from\)\s\+qgis" engine/*.py` → no matches |
| Pure engine suite | **`tests/test_engine.py`, 528 checks, exit 0** | `py -3 tests/test_engine.py` → `528/528 checks passed` |
| Manual | 1,038,470 B, `docs/PLANX_REFERENCE_MANUAL.html`, 69 algorithm cards, 19 group sections | direct count |
| Algorithm id ↔ manual anchor | **69 ↔ 69, no gaps, no orphans** | `name()` of every `alg_*.py` against every `id="…"` in the manual |
| Numbered display equations | **289** (`\tag{…}`) | counted in the manual |
| Citation entries | 377 (`class="ref"`), 292 DOI links | counted in the manual |
| QGIS runtimes | 3.44.12-Solothurn (LTR), 4.2.0-Belém do Pará | both launchers present |
| Hub security scan (the gate that blocks) | **CLEAN, 187 shipped files, exit 0** | `py -3 packaging/hub_security_scan.py planx` |
| Qt6 compatibility | no errors, **6 advisories** | `py -3 packaging/hub_qt6_scan.py planx` |
| `%` in `metadata.txt` | none (gate clean) | `grep -n "%" metadata.txt` → exit 1 |
| `.bandit` skip file | none present | `find . -name .bandit` → no matches |
| `plugins.toml` test registration | `tests_pure = []` · `tests_qgis = ["tests/test_engine.py", "-m planx.tests.smoke_plugin"]` | `plugins.toml` |
| Runtime algorithm matrix | **does not exist for planx** | only `planx_geostats/tests/qgis_runtime_algorithm_matrix.py` exists in the monorepo |

The two consequences that shape this plan:

1. **The plugin is in good shape where it is measured and unmeasured where it is not.** Both Hub
   gates pass, the manual is complete and its anchors are exact, and 528 engine checks pass. What
   is missing is not correctness — it is the *machinery that keeps these things true*, which is
   what let the defects in §1 sit in a released version.
2. **`tests/test_engine.py` is already a pure suite.** Its docstring says so — *"No qgis imports
   - pure engine"* — and it imports `numpy`, `math`, `os`, `sys` and `planx.engine`, nothing else.
   It is filed in the QGIS tier anyway (§1 D2). The cheapest high-value change in this plan is a
   one-line registry edit.

---

## 1. Defects found during the audit — fix before new features

These are live, user-facing, and cheap. Fixing them is Release 0. Each one was reproduced, not
inferred; the reproduction is printed with it.

### D1 — The Help button is dead for all 69 algorithms (severity: high)

`algorithms/base.py:29` hard-codes

```python
DOC_BASE_URL = "https://yusufeminoglu.github.io/PlanX/PLANX_REFERENCE_MANUAL.html"
```

and `helpUrl()` at `base.py:81` returns `DOC_BASE_URL + "#" + self.name()`. Probed:

```
$ curl -o /dev/null -w "%{http_code}" https://yusufeminoglu.github.io/PlanX/PLANX_REFERENCE_MANUAL.html
404
$ curl -o /dev/null -w "%{http_code}" https://geophilo.com/planx/
200
$ curl -o /dev/null -w "%{http_code}" https://gitlab.com/geophilo1/planx
200
```

Every one of the 69 Help buttons and both Studio dock documentation actions open a 404, while
`metadata.txt` advertises `homepage=https://geophilo.com/planx/` and the README badge links to
the same live host. This is the identical failure mode to **D1 in `planx_geostats`**, where it was
the R0 headline defect, and it is the failure the monorepo already learned once: the manual moved
and the code kept naming the old host.

### D2 — A 528-check pure suite is filed in the QGIS tier, and `tests_pure` is empty (severity: high)

```
$ py -3 tests/test_engine.py
528/528 checks passed          exit 0
```

Zero QGIS imports in `tests/test_engine.py` and zero in `engine/`. Yet `plugins.toml` registers it
under `tests_qgis` and declares `tests_pure = []`. The suite passes and nothing runs it: the
monorepo's pure-test gate, the one that can run in CI without a QGIS install, is empty for the
flagship plugin. The likely cause is visible in the file's own run instructions — it names the
OSGeo4W interpreter (`python-qgis-ltr.bat`) because that is what has NumPy on this machine, so it
was filed by launcher rather than by dependency.

### D3 — The manual advertises the wrong version (severity: medium)

`metadata.txt` says `version=4.11.1`; the manual contains **three** `v4.11.0` literals and no
`v4.11.1`. Same class as `planx_geostats` D4, which was fixed by a gate that counts the literals
so it cannot drift again.

### D4 — Nothing ties the algorithm registry to the manual, or the manual to `metadata.txt` (severity: medium)

The 69 algorithm anchors match the 69 `name()` values **today** — I checked all 69 in both
directions. Nothing enforces it. A renamed algorithm silently produces a dead anchor, which is how
D1 and D3 became release-visible in the first place. This is the gate the sibling plugin built in
its R0 and has run green on every release since.

### D5 — README counts have drifted, and one of them cannot be checked (severity: low)

`README.md:41` claims "285 numbered display equations"; the manual contains **289** `\tag{…}`
expressions. The same sentence claims "~600 citations"; the manual has 377 `class="ref"` entries
and 292 DOI links. The second number is hedged with `~` and no definition of "citation" is given,
so it is unfalsifiable as written — either define the unit and count it, or drop the claim. A
count in the marketing copy that no gate checks will always drift; the fix is to check it.

### D6 — No runtime matrix: nothing proves the 69 algorithms execute (severity: high)

`tests/test_engine.py` exercises the **engine**. `tests/smoke_plugin.py` imports the plugin and
checks it loads. Neither runs an algorithm. `docs/TRAPS.md` 5.1 puts it plainly — *"Does it load?"
is not a test* — and `planx_geostats` answers this with
`tests/qgis_runtime_algorithm_matrix.py`, which instantiates and executes every registered
algorithm on both runtimes and prints `case_count/ok_count/failed_count`. PlanX, four times the
size, has no equivalent. Every release therefore rests on the maintainer's manual testing.

### D7 — The documentation host is hard-coded twice (severity: medium)

`DOC_BASE_URL` is defined in `algorithms/base.py:29` **and** again in `studio_dock.py:17` — same
value, two copies, no import between them. Whatever D1 is fixed to, the fix must land in one
place or the two will drift apart exactly as the manual and the code did.

### D8 — A stale manual build sits outside the repository (severity: low, informational)

`qgis_plugins/_planx_reference_manual_full.html` has md5 `f918652fbdb1a022760f9be85d5d7098`
against the shipped manual's `fbf71af151c857764ba71c98b126cca2` — a different file, at the
monorepo root, outside every git repo. It is not shipped and not tracked, but it is a manual that
looks current and is not. Whether to delete it is the maintainer's call.

---

## 2. Capability gap analysis

### 2.1 Method, and what this analysis does not establish

Every "PlanX has X" and "PlanX does not have X" below was decided by grepping the source
(`grep -ril "<keyword>" --include=*.py algorithms engine`) and then **reading the matched lines**
to resolve false positives. Raw keyword counts were never trusted: `"corridor"` matches 57 times
and every one is help-text prose, while `"moran"` matches twice and both are the word
*"normalisation"*.

**What this does not establish.** The reference implementations were chosen from the mainstream of
each field (ArcGIS Pro/Urban, DepthmapX, sDNA, FRAGSTATS, SOLWEIG, TfL PTAL, AequilibraE, PySAL,
`momepy`, `tobler`, `spopt`, `giddy`, `segregation`, `gtfs_kit`, `r5py`) and their documented
capability lists. No reference *feature matrix* was built by installing and running them, so the
gap list is a judgement about what a planner expects of a toolkit of this class, not an exhaustive
catalogue. Treat §2.3 as the ranked shortlist it is, not as a finished specification.

### 2.2 Already committed — do not duplicate

Verified against `docs/ENHANCEMENT_PLAN_v4.12.md`, `docs/ROADMAP.md`, `docs/ENHANCEMENT_PLAN_v4.md`
and `provider.py`. All of `ENHANCEMENT_PLAN_v4.md` phases A–G shipped. `ROADMAP.md`'s inventory
table is a **partial** enumeration (66 rows, one duplicated) and must not be used as a registry.
Parking demand and supply balance are committed in v4.12 and are Release 1 here. Nothing in §2.3
below overlaps any of it.

### 2.3 Ranked gaps

Legend — **L** light (tens–hundreds of lines of numpy/scipy on existing engines) · **M** medium
(new solver or loop) · **H** heavy, or blocked by data.

| # | Capability | Reference | PlanX today (verified) | W |
|---|---|---|---|---|
| 1 | **Traffic assignment** — all-or-nothing → BPR volume–delay → MSA / Frank–Wolfe user equilibrium, with V/C ratios | AequilibraE, TransCAD, Visum, EMME | `grep "traffic assignment\|user equilibrium\|BPR\|volume.delay"` → 0. `gravitymodel` produces an OD matrix that **nothing consumes** — the four-step chain dead-ends at step 3 | L–M |
| 2 | **Gravity accessibility over arbitrary opportunities** (jobs, schools) + a decay library; **logsum / utility-based access** | Hansen 1959; UDST `access`; Conveyal | Decay exists but only over amenity categories (`alg_access_score.py` `DECAY` enum + `gravity` field). `grep "logsum"` → 0, `"cumulative opportunit"` → 0 | L (M for logsum) |
| 3 | **PTAL** (TfL, bands 0–6b) | TfL *Measuring PTAL* / WebCAT | `grep "ptal"` → 0, **but every ingredient exists**: walk times (`accessscore`), headways (`engine/transit.stop_frequencies`), street graph | L |
| 4 | **Solar envelope** (Knowles) + **BRE / EN 17037** solar access (VSC, APSH, 21-March overshadowing) | Knowles 1974; BRE BR209; BS EN 17037 | `grep "solar envelope\|right to light\|daylight factor\|en17037"` → 0. Near-free on the existing `shadow_mask` / `sky_view_factor` kernels | L–M |
| 5 | **Local Climate Zones** (Stewart & Oke, 17 classes), replacing the ad-hoc 0–100 heat composite | Stewart & Oke 2012; WUDAPT | `grep "lcz\|local climate zone\|wudapt"` → 0. 6 of 10 prototype parameters are already computable from DSM + land cover | M |
| 6 | **Mean radiant temperature + UTCI** | SOLWEIG; Höppe 1992; Bröde 2012 | `grep "utci\|mean radiant"` → 0. SOLWEIG steps 1, 2 and 4 (shadows, SVF, beam+diffuse) already exist | M (Tmrt), L (UTCI) |
| 7 | **Land suitability as a computed output** — WLC + AHP with consistency ratio + OWA + weight sensitivity | Saaty 1980; Malczewski 1999; ArcGIS Suitability Modeler | Suitability is an **input**; `alg_growth_sim.py:55` tells the user to bring their own MCDA. `grep "ahp\|topsis\|weighted overlay"` → 0 | L |
| 8 | **Plain-language space-syntax top-ups** — intelligibility, synergy, segment clustering coefficient, NQPD, detour ratio, place-syntax attraction weighting | DepthmapX; sDNA; Place Syntax Tool | `grep "intelligibility\|synergy\|clustering coefficient\|place syntax"` → 0. `engine/syntax.py` already produces nc, td, md, nain, choice, nach | L |
| 9 | **FRAGSTATS families** — core area, shape, aggregation (CLUMPY/AI/CONTAG/ENN), diversity (SHDI/SHEI); **probabilistic PC with a dispersal kernel, dIIC, patch betweenness** | McGarigal; Saura & Pascual-Hortal | Patch decomposition, edge length, largest-patch share exist; `green.py::pc_index` is **binary only**. `grep "fragstats\|contag\|core area"` → 0 | L (M for connectivity) |
| 10 | **Least-cost path / corridor + one-to-all current-flow pinchpoints** | Esri Cost Distance; Linkage Mapper; Circuitscape | `grep "least.cost\|cost distance\|circuitscape\|pinch"` → 0. `"corridor"` hits are all prose | L–M |
| 11 | **Classification schemes for the default renderer** — Jenks/natural breaks, quantiles, box plot, std-mean, user class count | `mapclassify`; ArcGIS symbology | `algorithms/base.py:164–191` hard-codes **5 classes, fixed palette, equal rank positions**. No Jenks, no class count | L |
| 12 | **Cheap robustness suite** — percolation/giant component, weighted network efficiency, Jenelius exposure, alternative-path redundancy | Jenelius 2006; Nagurney & Qiang | `engine/robustness.py` has exactly two functions, NRI only. `grep "percolation\|giant component"` → 0 | L |
| 13 | **Household projection** (headship rates) + **housing-unit method**, closing population → dwellings → occupancy | UN Manual VII; ONS; POPGROUP | Three disconnected halves: `populationprojection`, `housingneeds`, `residentialcapacity`. `grep "headship"` → 0 | L–M |
| 14 | **Zoning build-out / dimensional-standards audit** — as-of-right capacity, bonuses, 3D envelope | ArcGIS Urban; CityEngine | Parcel FAR arithmetic exists; `grep "zoning envelope\|build.out\|floor area bonus"` → 0 | L–M |
| 15 | **Areal interpolation between incompatible zonal systems** | `tobler` | `densitygrid` disaggregates only within its own units. `grep "areal interpolation\|pycnophylactic"` → 0 | M |
| 16 | **Jobs–housing balance / laboursheds** | Cervero 1989; Giuliano 1991 | `grep "jobs.housing\|labourshed"` → 0 | L |
| 17 | **Wind comfort screening** (Lawson / NEN 8100 classes) | Lawson 2001; NEN 8100 | `frontalarea` λf/λp and EPW wind means exist. `grep "wind comfort"` → 0 | M |
| 18 | **GTFS service-supply analytics** — service-km, speed by route, leg-level itineraries with wait decomposition | `gtfs_kit` | Frequency and RAPTOR access exist; `grep "wait time"` → 0 | M |
| 19 | **Markov dynamics on the existing land-cover transition matrix** — steady state, mean first passage, spatial Markov | `giddy` | `engine/growth.change_matrix` exists as accounting only | L |
| 20 | **Spatial statistics** — Moran's I, LISA + FDR, Geary, Getis-Ord Gi\*, join counts, rate smoothing, permutation inference; **segregation** beyond Duncan dissimilarity | `esda`, `segregation`, GeoDa | `grep "moran\|geary\|getis\|lisa"` → 2 hits, both false positives. `grep "permut\|significan\|p_value"` → **0**: the plugin has no significance testing anywhere | L–M |

### 2.4 The one structural prerequisite

Items 9, 10, 20 and the spatial variants in 15 all sit behind a single missing abstraction: **a
spatial-weights layer** (Queen/Rook contiguity, k-nearest, distance band, kernel) exposed as a
reusable engine object. PlanX already builds shared-boundary adjacency with `QgsSpatialIndex` in
`alg_land_allocation.py:281–303` and a morphological tessellation in `alg_tessellation.py`, so the
inputs exist; what does not exist is the weights matrix itself. Roughly 150 lines. It is the
keystone for §2.3 items 9, 10 and the spatial half of 20 — and it is **not** a headline feature,
which is why it belongs to whichever release first needs it, not to a release of its own.

### 2.5 Explicitly out of scope — name these, do not attempt them

Recorded so no future plan re-litigates them, and so the manual never implies they are coming:

- **Commercial-grade transit assignment** — hyperpath / optimal strategies, crowding, multi-class
  equilibrium.
- **Turn-restriction graphs** — a structural change to the CSR network representation, not a feature.
- **Full spatial econometrics** — ML/GMM SAR/SEM. (Also `planx_geostats` owns regression.)
- **Full CityEngine CGA shape grammars.**
- **WUDAPT's Landsat + training-areas + random-forest LCZ route** — the morphometric classifier in
  §2.3 item 5 is shippable; that one is not, and the manual must say which one shipped.
- **UrbanSim / ActivitySim-class LUTI** — parcel base year, rents, travel skims, choice microdata.
- **AERMOD** (a regulatory model) and full COPERT/HBEFA fleet datasets.
- **Circuitscape all-pairs and Omniscape** — only one-to-all is plugin-viable.
- **`r5py`** (JVM + R5 jar) and **GeoAI / deep learning** (torch/TF + GPU).
- **Synthetic population** — the IPF algorithm is light, but it is blocked by census marginals and
  microdata that the plugin cannot ship.

---

## 3. Releases

Each release is independently shippable, independently verifiable, and ends with the manual,
README, CHANGELOG and `metadata.txt` in sync. One commit per completed phase.

### R0 — v4.11.2 · The quality-infrastructure release — **firm**

A **patch**, because it adds no algorithms — the same reasoning that made `planx_geostats` R0
3.8.2 rather than 3.9.0. It ships D1–D8 and the three missing gates. No feature work.

| # | Deliverable | Acceptance |
|---|---|---|
| 1 | Point the documentation host at the live manual, from **one** definition | `helpUrl()` and both dock actions resolve 200; `grep -rn "DOC_BASE_URL" --include=*.py` returns one definition and its importers, not two literals |
| 2 | File `tests/test_engine.py` under `tests_pure` in `plugins.toml` | the monorepo's pure-test runner executes it; `py -3 tests/test_engine.py` → `528/528 checks passed` |
| 3 | New **`tests/smoke_provider_catalog.py`**, pure — the gate set adapted from `planx_geostats`: 69 registered algorithms; 19 groups as an exact set; one registered algorithm per `alg_*.py`; stable ids and groups; a unique 64×64 PNG per algorithm; `name()` ↔ manual `id=` one-to-one **both directions**; per-card `<div>` balance; no bare `<` before a letter; exactly one version literal in the manual, matching `metadata.txt`; the help host matching `metadata.txt`'s `homepage` | green on `py -3`, and **validated against the pre-fix tree** (`git show HEAD:…`) so at least one assertion is shown to fail before the fix — an assertion that passes against both the broken and the fixed file proves nothing (`docs/TRAPS.md` 5.2) |
| 4 | New **`tests/qgis_runtime_algorithm_matrix.py`** — instantiate and execute all 69 algorithms on both runtimes | `case_count 69, ok_count 69, failed_count 0` on 3.44.12-Solothurn **and** 4.2.0-Belém do Pará; the count may only go up |
| 5 | Refresh the manual's stale literals; count what the README claims | manual says `v4.11.2` in every site; the equation count in `README.md` equals the manual's `\tag{…}` count; the citation claim is either given a countable definition or removed |
| 6 | Delete or refresh the stale manual artefact outside the repo (§1 D8) | maintainer's call — recorded in §6 |

### R1 — v4.12.0 · Parking demand and supply balance — **firm, adopted**

Executes `docs/ENHANCEMENT_PLAN_v4.12.md` **unchanged**, including its three phases, its own
ground rules and its four declared deferrals (shared-parking discounts, illustrative defaults,
zero-versus-absent supply, radius-method disclosure). 69 → 71 algorithms. Its `§0.9` already
forbids a version bump during the working phase; this plan inherits that.

**The only change to it:** its phase 3 "verify `scratch/planx_import_check.py` still exists" is
answered here. That file **does not exist** — `scratch/` is empty — so the "How to read the
results" contract it was supposed to enforce is currently enforced by nothing. R0's gate (item 3)
takes it over. Every one of the 69 algorithms contains that heading today; the gate is what keeps
that true.

### R2 — v4.13.0 · Finish the four-step chain: traffic assignment — **candidate**

Closes the dead-end at §2.3 item 1: `gravitymodel` writes an OD matrix that nothing consumes.
All-or-nothing assignment on the existing Dijkstra, BPR volume–delay, then MSA / Frank–Wolfe user
equilibrium, with V/C ratios and flow-weighted criticality. Unlocks select-link analysis and OD
matrix estimation.

**Design constraints:** AequilibraE occupies this niche already, so the differentiator must be
*integration with the OD, equity and scenario machinery*, not the solver. Convergence must be
reported (relative gap per iteration), not assumed. Determinism: fixed iteration counts, seeded.

### R3 — v4.14.0 · Accessibility as an instrument — **candidate**

§2.3 items 2 and 3. Gravity access over arbitrary opportunities, a decay-function library, logsum
access built on `modesplit`'s existing MNL, and **PTAL** bands 0–6b. "Accessibility" is a headline
claim and this is its least defensible omission.

### R4 — v4.15.0 · Sun, sky and the right to light — **candidate**

§2.3 items 4 and 14. Solar envelope, VSC/APSH, 21-March overshadowing, and the zoning build-out
envelope. Nearly free on the existing shadow and SVF kernels, and statutory-adjacent — the design
twin of the capacity arithmetic already shipped.

### R5 — v4.16.0 · Human thermal comfort — **candidate**

§2.3 items 5, 6 and 17. Local Climate Zones replacing the ad-hoc heat composite, mean radiant
temperature, UTCI, and wind comfort screening. Moves the microclimate group from *how much sun*
to *how hot a person feels*. The manual must state that the LCZ route shipped is morphometric and
that wind comfort is a screening index, not permit-grade.

### R6 — v4.17.0 · Landscape structure and corridors — **candidate**

§2.3 items 9, 10, 11, 12 and 15, which share the §2.4 weights keystone where the spatial forms
need it. FRAGSTATS families, probabilistic PC with a dispersal kernel, dIIC, patch betweenness,
least-cost corridors, one-to-all pinchpoints, the Jenks renderer, and the robustness suite. Ships
the grain/extent/edge-buffer caveat FRAGSTATS metrics require.

### R7 — v5.0.0 · Manual and UX overhaul — **candidate**

Mirrors `planx_geostats` R7. The manual is 1.0 MB and 69 cards; it deserves the same treatment
that plugin's got: a searchable, dark-mode, deep-linked reference whose every claim is gated.
The README's unverifiable claims (§1 D5) are settled here for good.

**Ordering note:** R0 and R1 are firm. R2–R7 are ordered by value × fit ÷ effort from §2.3, and
the order is the maintainer's to change — the releases are independent, and each names the gap it
closes so any subset can be executed. §2.3 is the source list; §2.5 is the line that does not move.

---

## 4. Verification ritual (every phase, both runtimes)

Per `qgis_plugins/AGENTS.md`, `docs/TRAPS.md` and `RELEASING.md`:

1. `python -m compileall` + `flake8` before and after on every touched `.py`. Compare by message
   text, not line number.
2. Manual tag balance; anchor cross-check `name()` ↔ manual `id=` in **both** directions, no
   orphans; version literals; root/docs copy identity where two copies exist.
3. `py -3 packaging/pf.py verify planx` — both QGIS runtimes, all suites, both Hub gates. Bandit
   is the one that blocks: **a blocked version number is burned forever**, so gate before upload,
   never after.
4. **Do not trust the QGIS line `pf.py` prints** (`docs/TRAPS.md`; D10 in `planx_geostats`). It
   surfaces whichever stderr warning came last, not the verdict. Read the matrix's own numbers:

   ```
   QGIS_CUSTOM_CONFIG_PATH=$(mktemp -d) C:/OSGeo4W/bin/python-qgis-ltr.bat tests/qgis_runtime_algorithm_matrix.py \
     | grep -o 'PLANX_RUNTIME_MATRIX: [A-Z]* ([0-9]*/[0-9]*)'
   ```

   Repeat with `python-qgis.bat`. Both must print `PASS (n/n)` against a count that may only go up.
   A `PASS` from `pf.py` alone is not evidence.
5. `grep -n "%" metadata.txt` → nothing. No `.bandit` file, ever (`docs/TRAPS.md` 1.4). No AI
   attribution in any commit — **Rule 0**.
6. **Verify by running something.** "Should work" is not a result. Every number that reaches a
   report, a manual card or a commit message must have the command that produced it printed
   beside it.
7. **Ask before pushing or uploading.** Nothing in this plan is released by an agent. The
   maintainer reviews, then releases manually.

---

## 5. Known-shortcomings register

| # | Shortcoming | Severity | Release |
|---|---|---|---|
| S1 | The manual is 1.0 MB in one file; that is a download cost on every Help click, and it grows with each release | Low | R7 |
| S2 | `engine/` has a SciPy fast path and a pure-Python fallback; the two must agree exactly, and the *fallback* is the harder one to test because this machine has SciPy | Medium | R0 |
| S3 | No significance testing anywhere in the plugin (`permut`, `p_value` → 0 hits); any future "is this difference real" claim must either ship inference or not make the claim | Medium | §2.3 item 20 |
| S4 | Reading a 1.0 MB manual for one algorithm is slow; deep links help, but there is no per-algorithm standalone page | Low | R7 |
| S5 | `ROADMAP.md`'s inventory table is a partial enumeration with a duplicated row — it must not be used as a registry by any agent | Low | R0 |
| S6 | The §2.4 weights keystone has no owner until a release needs it; if it is built twice in two releases, that is a defect | Medium | R6 |
| S7 | Traffic assignment (R2) can converge to different equilibria under different iteration counts; the convergence criterion must be stated, not implied | Medium | R2 |
| S8 | Conditional simulation, full spatial econometrics and full transit assignment are out of scope — recorded here so they are not silently omitted later | Low | §2.5 |

---

## 6. Decisions this plan does not make for you

| # | Question | Why it is yours |
|---|---|---|
| Q1 | Which releases to execute, and in what order | Effort is yours to spend. R0 and R1 are firm; R2–R7 are scoped but untouched. |
| Q2 | Delete or refresh `_planx_reference_manual_full.html` (§1 D8) | It sits outside every repo. Deleting a file is yours to authorise. |
| Q3 | **Should PlanX reimplement spatial statistics (§2.3 item 20) when `planx_geostats` ships LISA, Moran, Geary and Getis-Ord?** | The monorepo's own rule is *cross-reference, do not duplicate*. The honest options are: (a) skip it and have PlanX consume `planx_geostats` outputs, (b) ship only the *local/weights* primitives PlanX needs for its own metrics and point at `planx_geostats` for inference. **Recommendation: (b).** It is the only answer that serves both plugins. |
| Q4 | Whether to commit this plan, and under whose name | Settled by the repo: commits are under Yusuf Eminoğlu alone, with no AI trailer of any kind. Nothing has been committed. |
| Q5 | Do the R0 gates block a release, or warn? | `planx_geostats` made them block. Making them block in a 69-algorithm plugin with no history of green will surface real drift on day one — which is the point, but it is a one-time cost you should choose. |

---

## 7. Required response format (per executed release)

```markdown
# Implementation Report v<X.Y.Z>
## 1. Release status — each numbered item: DONE | PARTIAL, one line each
## 2. Defect outcomes — each D-item, plus any NEW defects discovered, numbered on
## 3. Capability summary — table of new algorithm id | displayName | inputs | outputs
## 4. Validation evidence — real numbers (hand-computed graphs, cross-validation
     error, measured runtimes), not "it ran without error"
## 5. Test evidence — verbatim: pure suites, QGIS 3.44 LTR, QGIS 4.x
## 6. Gate outputs — Hub scan, Qt6 scan, `%`-in-metadata grep, verbatim
## 7. Deviations from this plan
## 8. Commit list — hash + message, one per line
```

**Honesty over completeness.** A PARTIAL with truthful evidence is acceptable. A DONE that the
reviewer's re-run contradicts invalidates the delivery.

---

## 8. Ground rules (hard requirements — each one has burned this repo before)

1. **Read this whole file first.** Touch only the files a release names. Do not refactor,
   reformat, or "improve" anything outside scope.
2. **Rule 0 — attribution is absolute.** No AI is ever credited as a contributor. Every commit
   ships under Yusuf Eminoğlu's name alone: no `Co-Authored-By:`, no "Generated with …", no bot
   signature, no AI-looking `user.name` / `user.email`. If you are an agent and cannot comply,
   stop and say so instead of committing.
3. **100% English** in code, help and docs. No self-praise wording — "elite", "best-in-class",
   "ultimate" and friends are banned in every string that ships.
4. Every algorithm help string keeps its **"How to read the results"** and **"Using the results"**
   sections. This is a gate from R0 onward, not a convention.
5. **No literal `%` in `metadata.txt`** — `grep -n "%" metadata.txt` must return nothing.
6. **Never add a `.bandit` skip file.** Every bandit finding blocks the Hub, and a blocked version
   number is dead forever.
7. **No dead knobs**: every parameter declared changes the output; every parameter read is used.
8. **Determinism**: no unseeded randomness, no `hash()`, no set/dict iteration order affecting
   results. The plugin's own Demo City generator is the model.
9. **Frozen ids.** If an existing algorithm's parameters or outputs are touched, ids, fields and
   behaviour at default values must not change.
10. **No new required dependency.** NumPy is the floor; SciPy stays an optional fast path with an
    identical pure-Python fallback. Anything else is a decision (§6), not a convenience.
11. **Do not bump the version, write the CHANGELOG, or release** until the final phase of the
    release you are executing. The maintainer releases manually after reviewing your report.
12. **One commit per completed phase.**
13. **Ask before pushing to a remote or uploading anything outward-facing.**

---

*Audit performed read-only. No file was modified, no commit was made, and nothing was released,
tagged, pushed or uploaded.*
