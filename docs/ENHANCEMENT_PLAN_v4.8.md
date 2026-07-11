# PlanX Enhancement Plan v4.8 — Scenario Ranking (Phase G, the final v4 phase)

**Target release: 4.8.0** (the release itself is NOT your job — see §0.13).
**Baseline: v4.7.0, commit `20e8990`** — 64 algorithms, 19 groups, 425 engine unit
checks, 363 e2e assertions (both QGIS), 24 dashboard checks. Your work must only
ADD to these numbers; every existing check must still pass.

**One sentence:** PlanX can snapshot a plan alternative and compare TWO of them
(A/B); this phase adds ranking of ANY NUMBER of scenario snapshots into a
direction-aware, optionally weighted composite score, as (1) a pure engine
function, (2) a Processing algorithm `planx:scenariorank`, (3) a one-file HTML
ranking board, and (4) a `Rank...` button in the Plan Dashboard dock.

---

## 0. Ground rules (hard requirements — each one has burned us before)

1. **Read this whole file first. Touch ONLY the files listed in §8.** Do not
   refactor, reformat, or "improve" anything outside scope. Existing algorithm
   ids, parameters, outputs and engine functions must not change.
2. **100% English** in all code, help, docs. Never use the words
   "elite", "best-in-class", "ultimate" or similar self-praise in any copy.
3. Every algorithm help string in this plugin ends with a
   **"How to read the results"** section followed by a **"Using the results"**
   passage. Yours must too — `scratch/planx_import_check.py` asserts the
   former's presence and will fail without it.
4. **No dead knobs**: every parameter you declare must change the output.
   Every parameter you read must be used in the computation.
5. **Determinism**: no unseeded randomness, no `hash()`, no set/dict iteration
   order affecting results. Tie-breaks must be explicit and documented (§2).
6. **Copy the sibling patterns.** File naming (`alg_scenario_rank.py`), class
   naming (`ScenarioRankAlgorithm`), parameter constants, `self.tr(...)`,
   `make_fields`, sink creation — imitate `alg_scenario_compare.py` and
   `alg_scenario_snapshot.py`. When in doubt, do what the neighbours do.
7. **Pure engine**: nothing under `engine/` may import qgis. `scenario.rank`
   is stdlib-only (like the rest of `scenario.py`); `report.build_rank_html`
   is stdlib-only (like `build_compare_html`).
8. **Pin scripts move UP, never sideways or down** (a past agent weakened one
   to make its shortcut pass — instant rejection):
   - `scratch/planx_import_check.py`: `len(algs) == 64` → `== 65`.
   - `scratch/planx_e2e_qgis.py`: the distinct-icon invariant `== 64` → `== 65`.
   - `scratch/planx_zip_audit.py`: ADD file asserts for
     `planx/algorithms/alg_scenario_rank.py` and
     `planx/icons/tool_scenariorank.png`. Do **NOT** touch its `version=` pin
     or changelog-count pins — the release owner bumps those.
9. **e2e discipline**: new block label is **[61]** (labels currently end at
   [60]; grep first and keep labels unique — a past agent produced a duplicate
   label). Keep the `os._exit(...)` tail intact. Run from the monorepo root
   (`C:\Users\YE\PyCharmMiscProject\qgis_plugins`) — running with CWD inside
   `planx/` makes `planx.py` shadow the package. Script files only (multiline
   `-c` silently fails on OSGeo4W). Set `PYTHONUNBUFFERED=1`. Run BOTH
   runners: `C:\OSGeo4W\bin\python-qgis-ltr.bat` (QGIS 3 LTR) and
   `C:\OSGeo4W\bin\python-qgis.bat` (QGIS 4). **Never claim a run you did not
   execute; paste the exact printed totals into your report (§9).**
10. **Icon**: extend `scratch/make_planx_tool_icons.ps1` with a
    `tool_scenariorank` entry using **inline point arrays** (helper functions
    returning arrays inside the scriptblock crash GDI+ — known trap). Glyph
    suggestion: a podium (three bars of heights 2-3-1) in the REPORT cyan
    palette. Regenerate, then verify with `git status` that ONLY
    `icons/tool_scenariorank.png` is new and every existing PNG is
    byte-identical (the generator is deterministic; if others changed, you
    broke it).
11. **Lint/security**: `py -m flake8 --max-line-length=127 planx` must be
    clean; `py -m bandit -r planx -q` must add nothing above Low severity.
12. Standing geometry rule (context, mostly N/A here): never copy an input
    `QgsFeature`'s geometry into a sink with a different CRS or geometry type;
    rebuild from coordinates. Your two sinks are `NoGeometry` tables — keep
    them so.
13. **STOP BEFORE RELEASE.** Do NOT bump the version in `metadata.txt`, do NOT
    build a zip, do NOT `git add/commit/tag/push`. Leave the working tree
    dirty for review. The CHANGELOG heading must read exactly
    `## [4.8.0] - UNRELEASED`.
14. Deliver a report file (§9). Deviations from this plan require a written
    justification there — the default expectation is zero deviations.

---

## 1. Scope

**New:**
- `engine/scenario.py`: `rank(...)` + `parse_weights(...)` (append to the
  existing module; do not reorganise it).
- `engine/report.py`: `build_rank_html(...)` (append; reuse `ramp_color`,
  follow `build_compare_html`'s structure and inline-CSS style).
- `algorithms/alg_scenario_rank.py`: `ScenarioRankAlgorithm`
  (`planx:scenariorank`, group `GROUP_REPORT`, icon `tool_scenariorank.png`).
- `dashboard_dock.py`: a `Rank...` button next to `Audit...`.
- Icon `icons/tool_scenariorank.png` via the generator script.
- Tests: engine unit section + e2e block [61] + 2 dashboard checks.
- Docs: README, metadata description/tags, CHANGELOG, `docs/METHODS.md`.

**Explicitly out of scope:** everything else. No changes to `compare`,
`snapshot`, `from_json`, the dashboard's existing buttons, or any other
algorithm.

---

## 2. Engine contract — `scenario.rank`

Append to `planx/engine/scenario.py` (stdlib only):

```python
def parse_weights(text):
    """Parse 'key=weight, key=weight' free text into a dict.

    Returns (weights: dict[str, float], unknown: list[str]) where ``unknown``
    lists keys not present in METRICS (they still apply if the snapshots
    carry them - the caller decides how to report them). Accepts ';' as a
    separator like the other PlanX free-text parsers. Empty/whitespace text
    -> ({}, []). A malformed token or a weight <= 0 raises ValueError with
    the offending token in the message.
    """

def rank(snapshots, weights=None):
    """Rank any number of scenario snapshots by a weighted composite score.

    ``snapshots``: list of snapshot dicts (from ``snapshot``/``from_json``).
    ``weights``: optional {metric_key: float > 0}; default weight is 1.0.

    Raises ValueError when fewer than 2 snapshots are given or when two
    snapshots share the same name (names key the result tables).

    SCORED metrics are those that are (a) present in EVERY snapshot,
    (b) have a non-zero direction in METRICS (unknown keys have direction 0
    via direction_of and are therefore never scored), and (c) are not
    constant across the snapshots. Everything else is reported as skipped
    with a reason: 'neutral' (direction 0 / unknown), 'not-shared' (missing
    in at least one snapshot), 'constant' (shared but max == min). Reason
    precedence: neutral > not-shared > constant.

    Per scored metric k with values v_s over scenarios s:
        norm_s = (v_s - min) / (max - min)          if direction(k) == +1
        norm_s = (max - v_s) / (max - min)          if direction(k) == -1
    so 1.0 is always BEST. Composite per scenario:
        score_s = 100 * sum_k(w_k * norm_k_s) / sum_k(w_k)
    Ranks use competition ranking on descending score (equal scores share a
    rank; the next rank is skipped: 1, 2, 2, 4). ``wins_s`` counts the scored
    metrics where scenario s holds the strictly best norm (exact ties on a
    metric award no win).

    Returns {
      "scenarios": [ {"name", "score", "rank", "wins", "n_metrics"} ... ]
                   sorted by (rank, name),
      "metrics":   [ {"key", "label", "direction", "weight",
                      "values": {name: v}, "norms": {name: n}} ... ]
                   ordered by the METRICS registry order (unknown keys never
                   appear here - they are always skipped),
      "skipped":   [ {"key", "reason"} ... ] ordered registry-first then
                   alphabetically, deterministic,
    }
    "n_metrics" is len(result["metrics"]) (same for every scenario, kept per
    row for table readability). All floats stay full precision - no rounding
    in the engine.
    """
```

**Hand-worked example — copy these EXACT numbers into the unit tests:**

```python
snapA = scenario.snapshot("Alpha", {"walk_score_mean": 60.0, "access_gini": 0.20,
                                    "walk_low_share": 30.0, "units_total": 100.0})
snapB = scenario.snapshot("Beta",  {"walk_score_mean": 80.0, "access_gini": 0.40,
                                    "walk_low_share": 30.0, "units_total": 200.0})
snapC = scenario.snapshot("Gamma", {"walk_score_mean": 70.0, "access_gini": 0.25,
                                    "walk_low_share": 30.0, "units_total": 300.0})
res = scenario.rank([snapA, snapB, snapC])
```

- `walk_score_mean` (direction +1): norms Alpha 0.0, Beta 1.0, Gamma 0.5.
- `access_gini` (direction −1): norms Alpha 1.0, Beta 0.0, Gamma
  (0.40−0.25)/0.20 = **0.75**.
- `walk_low_share`: shared but constant → skipped `("walk_low_share", "constant")`.
- `units_total`: unknown to METRICS → direction 0 → skipped
  `("units_total", "neutral")`.
- Default weights → scores: **Alpha 50.0, Beta 50.0, Gamma 62.5**.
- Ranks: **Gamma 1, Alpha 2, Beta 2** (competition ranking; the scenarios list
  is ordered Gamma, Alpha, Beta by (rank, name)).
- Wins: **Alpha 1** (gini), **Beta 1** (walk score), **Gamma 0** — note the
  teaching point: the balanced scenario wins overall with zero individual
  wins; assert exactly this.
- `weights={"walk_score_mean": 3.0}` → Alpha (3·0+1·1)/4 = **25.0**,
  Beta **75.0**, Gamma (3·0.5+1·0.75)/4 = **56.25** → order Beta, Gamma, Alpha.
- With a fourth snapshot "Delta" that lacks `access_gini`, ranking
  [snapA, snapB, snapD] scores on `walk_score_mean` alone and skips
  `("access_gini", "not-shared")`.
- Error cases: `rank([snapA])` → ValueError; two snapshots named "Alpha" →
  ValueError; `parse_weights("walk_score_mean=0")` → ValueError;
  `parse_weights("banana")` → ValueError;
  `parse_weights("access_gini=2, made_up=1")` → weights parsed, unknown ==
  ["made_up"].

---

## 3. Report contract — `report.build_rank_html`

```python
def build_rank_html(title, result, weights_note="", generated=""):
    """One-file HTML ranking board for a scenario.rank result. Stdlib only.

    Sections: (1) scoreboard - one row per scenario in rank order: rank,
    name, score to one decimal, and a horizontal bar whose width is the
    score and whose colour is ramp_color(score/100); (2) a metric heat
    table - rows = scored metrics (label + direction arrow + weight),
    columns = scenarios, each cell showing the raw value with its
    background from ramp_color(norm); (3) a skipped-metrics footnote line
    naming each skipped key and reason; (4) the optional weights note and
    generated stamp in the footer. html.escape every name/label/value
    string. Follow build_compare_html's document skeleton and CSS idiom.
    """
```

---

## 4. Algorithm contract — `planx:scenariorank`

File `planx/algorithms/alg_scenario_rank.py`, class `ScenarioRankAlgorithm`,
`GROUP = GROUP_REPORT`, `ICON = "tool_scenariorank.png"`,
`name() = "scenariorank"`, `displayName() = "Scenario Ranking"`.

**Parameters** (constants in this order):
- `FILES` — `QgsProcessingParameterString`, label
  `"Snapshot files (paths, ';' or ',' separated)"`, optional, default `""`.
  Split on `;` first, then `,` for tokens without `;`; strip whitespace and
  surrounding quotes from each token.
- `FOLDER` — `QgsProcessingParameterFile` with
  `behavior=QgsProcessingParameterFile.Folder`, optional: every `*.json`
  directly in that folder (non-recursive), sorted by filename for
  determinism.
- `WEIGHTS` — `QgsProcessingParameterString`, label
  `"Metric weights 'key=weight, ...' (empty = equal)"`, optional, default
  `""`.
- `OUT_TABLE` — sink `"Ranking"`, `type=QgsProcessing.TypeVector`,
  NoGeometry. Fields: `rank` INT, `scenario` STRING, `score` DOUBLE,
  `wins` INT, `n_metrics` INT. One row per scenario in (rank, name) order.
- `OUT_DETAIL` — sink `"Metric detail"`, `type=QgsProcessing.TypeVector`,
  NoGeometry. Fields: `metric` STRING (key), `label` STRING,
  `direction` INT, `weight` DOUBLE, `scenario` STRING, `value` DOUBLE,
  `norm` DOUBLE. One row per scored metric × scenario, metrics in registry
  order, scenarios in (rank, name) order — for the fixture that is exactly
  2 × 3 = 6 rows.
- `OUTPUT_HTML` — `QgsProcessingParameterFileDestination`,
  `"Ranking board (HTML)"`, filter `"HTML files (*.html)"`, optional,
  `createByDefault=False`.

**Behaviour:**
- Collect paths from FILES + FOLDER, de-duplicate on `os.path.abspath`
  (case-insensitive on Windows: compare `os.path.normcase`), keep first-seen
  order (FILES tokens first, then folder files).
- Fewer than 2 collected paths → `QgsProcessingException` telling the user
  both parameters are empty/insufficient.
- Each file: read UTF-8, `scenario.from_json`; any failure →
  `QgsProcessingException` naming the offending file.
- `parse_weights` ValueError → `QgsProcessingException` with the message.
  Unknown weight keys → `feedback.pushWarning` listing them.
- `scenario.rank` ValueError (duplicate names) → `QgsProcessingException`.
- Log (`pushInfo`): number of snapshots, scored metric count, each skipped
  metric with reason, then a verdict line
  `"1. Gamma (62.5)  2. Alpha (50.0)  2. Beta (50.0)"` built from the result.
- Write the HTML only when the parameter was set
  (`parameters.get(self.OUTPUT_HTML)` truthy — follow how the OD matrix /
  annual solar tools detect optional destinations), and return its path in
  the results dict alongside the two sinks.

**Help string:** keep the established shape — a factual description of the
method (direction-aware min-max normalisation, weighted mean, competition
ranking, skipped-metric rules), then **"How to read the results"** (at
minimum: score is RELATIVE to the compared set, not absolute quality —
adding/removing a scenario rescales everything; rank ties mean genuinely
undistinguishable; wins vs rank divergence = balanced-beats-specialist;
check skipped 'not-shared' metrics before trusting a ranking — a scenario
evaluated with fewer tools is not comparable), then **"Using the results"**
(rank the audited alternatives from Batch Plan Auditor / Scenario Pipeline;
weight metrics to reflect plan priorities and SHOW the weights next to any
published ranking; use the HTML board in options meetings).

---

## 5. Dashboard button

In `dashboard_dock.py`, next to the existing `Audit...` button (follow its
creation, object naming, tooltip and wiring pattern exactly):
- `self.rank_btn = QPushButton("Rank...")`, tooltip
  `"Open Scenario Ranking - rank any number of saved scenario snapshots."`.
- Clicked → `processing.execAlgorithmDialog("planx:scenariorank", {})`,
  guarded the same way the audit button guards its call.

Extend `scratch/planx_dashboard_check.py` with 2 checks following its
existing style ("rank button exists", "rank button wired") → the harness
must report **26 / 26** on both QGIS.

---

## 6. Icon

§0.10 has the rules. Palette/group: REPORT cyan (same family as
`tool_scenariocompare.png` / `tool_planaudit.png`). Suggested glyph: three
podium bars (order 2-1-3 heights) with a small crown/star over the tallest —
keep it readable at 24 px.

---

## 7. Tests

### 7.1 Engine unit tests (`planx/tests/test_engine.py`)

Append a section `# Scenario ranking (v4.8 Phase G)` before the summary
block, using the §2 fixture verbatim. Required checks (~16):
ranks/scores exact (Gamma 62.5 / Alpha 50 / Beta 50; competition ranks
1,2,2); scenarios order (rank, name); norms exact per metric; wins
Alpha 1 / Beta 1 / Gamma 0; skipped constant + neutral reasons; not-shared
with the Delta variant; weighted rerun (75 / 56.25 / 25, Beta first);
n_metrics == 2; parse_weights happy path, unknown list, `<=0` ValueError,
malformed ValueError; rank ValueError on 1 snapshot and on duplicate names.

Run: `C:\OSGeo4W\bin\python-qgis-ltr.bat planx\tests\test_engine.py`
(from the monorepo root). Expect ≥ 440 total, ALL passing; report the exact
number.

### 7.2 e2e (`scratch/planx_e2e_qgis.py`, new block `[61]`)

Build the three §2 snapshots in-harness via
`from planx.engine import scenario` (the harness already imports `planx`),
write them with `scenario.to_json` into `tempfile.mkdtemp()`, then:
- run `planx:scenariorank` with `FILES=";".join(paths)`, both sinks
  TEMPORARY, `OUTPUT_HTML` to a temp path;
- assert: table has 3 rows; Gamma rank 1 score 62.5 (±1e-9); Alpha and Beta
  both rank 2 score 50.0; wins 1/1/0; detail has exactly 6 rows and the
  (Gamma, access_gini) row's norm is 0.75; the HTML file exists and its text
  contains "Gamma" and "Scenario Ranking";
- weighted rerun `WEIGHTS="walk_score_mean=3"`: Beta 75.0 rank 1,
  Gamma 56.25, Alpha 25.0;
- FOLDER variant: pass the temp dir instead of FILES → same 3-row table;
- error path (follow the seismic error-path idiom): FILES with a single
  path must fail with a clear error (expect the run to raise).

Also bump the distinct-icon invariant to 65. Run the FULL harness on BOTH
runners; expect ≥ 375 passed / 0 failed on each; report exact totals.

### 7.3 Regression

All pre-existing checks must pass untouched: 425 unit / 363 e2e / 24
dashboard are the floors. `scratch/planx_import_check.py` (after your 64→65
edit) must print OK on both runners.

---

## 8. Files you may touch (complete list) + registration checklist

| File | Change |
|---|---|
| `planx/engine/scenario.py` | append `parse_weights`, `rank` |
| `planx/engine/report.py` | append `build_rank_html` |
| `planx/algorithms/alg_scenario_rank.py` | NEW |
| `planx/provider.py` | import + `addAlgorithm(ScenarioRankAlgorithm())` (alphabetical/near its scenario siblings, match file style) |
| `planx/dashboard_dock.py` | Rank... button (§5) |
| `planx/icons/tool_scenariorank.png` | NEW, via generator |
| `scratch/make_planx_tool_icons.ps1` | add inline-array entry |
| `planx/tests/test_engine.py` | §7.1 section |
| `scratch/planx_e2e_qgis.py` | block [61] + icon invariant 65 |
| `scratch/planx_dashboard_check.py` | +2 checks |
| `scratch/planx_import_check.py` | 64 → 65 |
| `scratch/planx_zip_audit.py` | + 2 file asserts (NOT the version pin) |
| `planx/README.md` | "sixty-four" → "sixty-five" in BOTH places (the *Why PlanX?* paragraph and the *Interpretation built in* bullet); extend the *Scenario A/B comparison* feature bullet with multi-scenario ranking; add the tool table row under *Reporting and Dashboard* |
| `planx/metadata.txt` | description: extend the "scenario A/B comparison" clause to "...scenario A/B comparison and weighted multi-scenario ranking..."; tags: append `scenario ranking`. **No bare `%` anywhere** (configparser interpolation breaks the Hub upload). Do NOT touch `version=` |
| `planx/CHANGELOG.md` | new top section `## [4.8.0] - UNRELEASED` (Added: engine rank + parse_weights, algorithm, HTML board, dock button; Tested: your exact counts) |
| `planx/docs/METHODS.md` | short section: formula, normalisation, competition ranking, skip rules |
| `planx/docs/AGENT_REPORT_v4.8.md` | NEW — your report (§9) |

Anything not in this table is off-limits.

---

## 9. Definition of done + report

Done means ALL of:
1. §7 test targets met with the EXACT totals pasted into
   `planx/docs/AGENT_REPORT_v4.8.md` (unit; e2e LTR; e2e QGIS 4; dashboard
   LTR + QGIS 4; import_check both runners).
2. flake8 (127) clean; bandit nothing above Low; `git status` shows only the
   §8 files changed and only the one new PNG.
3. Working tree left UNCOMMITTED (§0.13).
4. Report contains: file-by-file summary, any decisions the plan left open,
   deviations (expected: none), and the exact commands you ran.

## 10. What the reviewer will verify (deterrence disclosure)

The review re-runs everything independently: both e2e runners and the unit
suite from a clean shell; the §2 fixture numbers recomputed by hand; a
byte-identity check of all pre-existing icons; a dead-knob scan of the new
parameters; the pin scripts diffed against §0.8 (any weakened invariant =
rejection); README/metadata/CHANGELOG cross-checked; help sections checked
for both required headings; and `git status` checked for out-of-scope
touches. Shortcuts are cheaper to skip than to attempt.
