# Agent prompt — PlanX v4.8 "Scenario Ranking" (copy everything below the line)

---

You are implementing ONE fully specified feature in an existing, released QGIS
plugin. This is precision work against a written contract, not a design task.

REPO: `C:\Users\YE\PyCharmMiscProject\qgis_plugins\planx` (the plugin;
`main`, clean at commit `20e8990` = v4.7.0). Test harnesses live in
`C:\Users\YE\PyCharmMiscProject\qgis_plugins\scratch\`.

YOUR ENTIRE SPECIFICATION:
`planx/docs/ENHANCEMENT_PLAN_v4.8.md`

Read that file completely BEFORE opening any code. It defines: the exact
engine API with a hand-worked numeric example you must reproduce, the
Processing algorithm contract (parameters, field lists, behaviour, help-text
requirements), the dashboard button, the icon rules, the complete list of
files you may touch, the test fixtures with expected values, and the ground
rules in its §0 — every §0 rule encodes a real failure from a previous agent
and is enforced at review.

The five rules most often broken, up front:
1. Work ONLY within the plan's §8 file table. No refactors, no drive-by fixes.
2. Run the REAL gates and report the EXACT printed totals: unit suite, the
   FULL e2e harness on BOTH `python-qgis-ltr.bat` AND `python-qgis.bat`,
   dashboard check on both, import check on both — from the monorepo root,
   `PYTHONUNBUFFERED=1`, script files only. Never report a number you did not
   personally see printed.
3. Pin scripts and invariants go UP (64→65 etc.); weakening any check to make
   your work pass is an automatic rejection.
4. STOP before release: no version bump, no zip, no git commit/tag/push.
   Leave the working tree dirty. CHANGELOG heading: `## [4.8.0] - UNRELEASED`.
5. Write `planx/docs/AGENT_REPORT_v4.8.md` (per plan §9) with files touched,
   commands run, exact totals, and deviations (target: none).

Your work will be independently re-run and hand-checked against the plan's
numbers (§10 of the plan lists exactly how). Deliver: the implementation, the
green gates, and the report.
