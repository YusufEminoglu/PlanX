# Agent prompt — PlanX v4.9 "Network Routing UX & Walking Comfort" (copy everything below the line)

---

You are implementing FIVE fully specified features in an existing, released
QGIS plugin. This is precision work against a written contract, not a design
task.

REPO: `C:\Users\YE\PyCharmMiscProject\qgis_plugins\planx` (the plugin;
`main`, clean at commit `f3d2b20` = v4.8.0). Test harnesses live in
`C:\Users\YE\PyCharmMiscProject\qgis_plugins\scratch\`.

YOUR ENTIRE SPECIFICATION:
`planx/docs/ENHANCEMENT_PLAN_v4.9.md`

Read that file completely BEFORE opening any code. It defines: the exact
engine APIs with hand-worked numeric fixtures you must reproduce (Tobler
speeds, the 0.8375 kernel cell, the [100, 0, 25] combine, the predecessor
arrays), the two extended and three new Processing algorithm contracts
(parameters, field lists, behaviour, help-text requirements), the icon
rules, the complete list of files you may touch, the e2e blocks [62]–[66]
with expected values, and the ground rules in its §0 — every §0 rule encodes
a real failure from a previous agent and is enforced at review.

The six rules most often broken, up front:
1. Work ONLY within the plan's §9 file table. No refactors, no drive-by
   fixes. The two EXTENDED algorithms must behave byte-identically at
   default parameter values (§3/§4 state the exact back-compat paths).
2. Run the REAL gates and report the EXACT printed totals: unit suite, the
   FULL e2e harness on BOTH `python-qgis-ltr.bat` AND `python-qgis.bat`,
   dashboard check on both, import check on both — from the monorepo root,
   `PYTHONUNBUFFERED=1`, script files only. Never report a number you did
   not personally see printed.
3. Pin scripts and invariants go UP (65→68 etc.); weakening any check to
   make your work pass is an automatic rejection.
4. Rebuild all route geometry from graph coordinates (the `route_geometry`
   idiom in `alg_route_quality.py`); never copy an input feature's geometry
   into a differently-typed or differently-projected sink.
5. STOP before release: no version bump, no zip, no git commit/tag/push.
   Leave the working tree dirty. CHANGELOG heading: `## [4.9.0] - UNRELEASED`.
   `docs/METHODS.md` additions use inline-backtick prose formulas — NO
   `$$`/LaTeX.
6. Write `planx/docs/AGENT_REPORT_v4.9.md` (per plan §10) with files
   touched, commands run, exact totals, and deviations (target: none).

Your work will be independently re-run and hand-checked against the plan's
numbers (§11 of the plan lists exactly how). Deliver: the implementation,
the green gates, and the report.
