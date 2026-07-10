# -*- coding: utf-8 -*-
"""Scenario Compare: A/B diff of two plan snapshot JSON files."""
from __future__ import annotations

import os

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsFeatureSink,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFile,
    QgsProcessingParameterFileDestination,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_REPORT, PlanXAlgorithm, STRING
from ..engine import report as rpt
from ..engine import scenario


def _read_snapshot(path: str, side: str):
    if not path or not os.path.exists(path):
        raise QgsProcessingException(
            f"Snapshot {side}: file not found: '{path}'.")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return scenario.from_json(fh.read())
    except (OSError, ValueError) as exc:
        raise QgsProcessingException(
            f"Snapshot {side}: could not read '{path}': {exc}")


class ScenarioCompareAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_REPORT
    ICON = "tool_scenariocompare.png"
    SNAPSHOT_A = "SNAPSHOT_A"
    SNAPSHOT_B = "SNAPSHOT_B"
    OUT_TABLE = "OUT_TABLE"
    OUTPUT_HTML = "OUTPUT_HTML"

    def name(self):
        return "scenariocompare"

    def displayName(self):
        return self.tr("Scenario Compare (A/B)")

    def shortHelpString(self):
        return self.tr(
            "Compares two plan alternatives metric by metric - the A/B view "
            "of the Plan Dashboard.\n\n"
            "Feed it two scenario snapshot JSON files. Snapshots are written "
            "by the Plan Dashboard dock (Scenario: Save A / Save B) - run the "
            "PlanX tools for one plan alternative, snapshot it, rerun them for "
            "the other alternative, snapshot again, then compare.\n\n"
            "Every metric knows which direction is better (a higher access "
            "score is good, more deficits are bad), so each row of the "
            "comparison names the winning scenario; neutral metrics (plain "
            "counts) are reported without a verdict.\n\n"
            "Outputs a comparison table (metric, both values, delta, percent "
            "change, winner) and optionally a one-file HTML comparison report "
            "to share.\n\n"
            "Metrics missing on one side are listed with the available value "
            "only. The verdict line in the log counts the wins.\n\n"
            "How to read the results\n"
            "- Do not stop at the win count: scenarios rarely dominate. "
            "The normal outcome is a TRADE-OFF profile - B wins access "
            "and compliance, A wins density and coverage - and naming "
            "that trade-off is the analysis.\n"
            "- Use pct_change to judge materiality: a 0.4 percent win is "
            "noise (input data moved, not the plan); double-digit swings "
            "are decisions.\n"
            "- Rows missing on one side usually mean one scenario was "
            "evaluated with fewer tools - fix the snapshots before "
            "drawing conclusions.\n\n"
            "Using the results: the HTML report is built for the options "
            "meeting - each row names its winner, so the discussion "
            "moves from 'which do you like' to 'which trade-offs do we "
            "accept'; when a hybrid emerges, snapshot it as a third run "
            "and compare against the previous best."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(
            self.SNAPSHOT_A, self.tr("Scenario snapshot A (JSON)"),
            extension="json"))
        self.addParameter(QgsProcessingParameterFile(
            self.SNAPSHOT_B, self.tr("Scenario snapshot B (JSON)"),
            extension="json"))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_TABLE, self.tr("Scenario comparison"),
            type=QgsProcessing.TypeVector))
        self.addParameter(QgsProcessingParameterFileDestination(
            self.OUTPUT_HTML, self.tr("Comparison report (HTML)"),
            self.tr("HTML files (*.html)"), optional=True,
            createByDefault=False))

    def processAlgorithm(self, parameters, context, feedback):
        path_a = self.parameterAsFile(parameters, self.SNAPSHOT_A, context)
        path_b = self.parameterAsFile(parameters, self.SNAPSHOT_B, context)
        html_path = self.parameterAsFileOutput(
            parameters, self.OUTPUT_HTML, context)

        snap_a = _read_snapshot(path_a, "A")
        snap_b = _read_snapshot(path_b, "B")
        name_a = snap_a["name"]
        name_b = snap_b["name"]
        if name_a == name_b:
            name_a, name_b = f"{name_a} (A)", f"{name_b} (B)"
        rows = scenario.compare(snap_a, snap_b)
        if not rows:
            raise QgsProcessingException(
                "The snapshots share no metrics to compare.")
        verdict = scenario.score_line(rows, name_a, name_b)

        fields = self.make_fields(
            ("metric", STRING), ("metric_key", STRING),
            ("scenario_a", DOUBLE), ("scenario_b", DOUBLE),
            ("delta", DOUBLE), ("delta_pct", DOUBLE), ("better", STRING))
        sink, dest = self.parameterAsSink(
            parameters, self.OUT_TABLE, context, fields,
            QgsWkbTypes.NoGeometry, QgsCoordinateReferenceSystem())

        def num(v):
            return None if v is None else round(float(v), 4)

        for r in rows:
            feat = QgsFeature(fields)
            feat.setAttributes([
                r["label"], r["key"], num(r["a"]), num(r["b"]),
                num(r["delta"]), num(r["delta_pct"]), r["better"]])
            sink.addFeature(feat, QgsFeatureSink.FastInsert)

        feedback.pushInfo(self.tr(
            f"Compared '{name_a}' ({snap_a['generated']}) with "
            f"'{name_b}' ({snap_b['generated']}): {len(rows)} metrics."))
        feedback.pushInfo(self.tr(verdict))

        results = {self.OUT_TABLE: dest}
        if html_path:
            from .alg_performance_report import _plugin_version
            html = rpt.build_compare_html(
                f"{name_a} vs {name_b}", rows, name_a, name_b,
                verdict=verdict, plugin_version=_plugin_version())
            try:
                with open(html_path, "w", encoding="utf-8") as fh:
                    fh.write(html)
            except OSError as exc:
                raise QgsProcessingException(
                    f"Could not write the HTML report: {exc}")
            feedback.pushInfo(self.tr(f"Comparison report written: {html_path}"))
            results[self.OUTPUT_HTML] = html_path
        return results

    def createInstance(self):
        return ScenarioCompareAlgorithm()
