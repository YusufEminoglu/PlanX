# -*- coding: utf-8 -*-
"""Scenario Rank: Composite ranking of multiple plan snapshot JSON files."""
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
    QgsProcessingParameterString,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_REPORT, PlanXAlgorithm, STRING, INT
from ..engine import report as rpt
from ..engine import scenario


def _read_snapshot(path: str):
    if not path or not os.path.exists(path):
        raise QgsProcessingException(
            f"Snapshot: file not found: '{path}'.")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return scenario.from_json(fh.read())
    except (OSError, ValueError) as exc:
        raise QgsProcessingException(
            f"Snapshot: could not read '{path}': {exc}")


class ScenarioRankAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_REPORT
    ICON = "tool_scenariorank.png"

    FILES = "FILES"
    FOLDER = "FOLDER"
    WEIGHTS = "WEIGHTS"
    OUT_TABLE = "OUT_TABLE"
    OUT_DETAIL = "OUT_DETAIL"
    OUTPUT_HTML = "OUTPUT_HTML"

    def name(self):
        return "scenariorank"

    def displayName(self):
        return self.tr("Scenario Ranking")

    def shortHelpString(self):
        return self.tr(
            "Ranks any number of scenario snapshots by a weighted composite score using direction-aware "
            "min-max normalisation.\n\n"
            "Provide a list of paths to scenario snapshots (JSON format) and/or a folder containing scenario snapshots. "
            "Specify weights for individual metrics as key=weight pairs (e.g., 'walk_score_mean=3, access_gini=2'). "
            "Only metrics that are present in every snapshot, have a non-zero direction registry, and are not constant "
            "across all snapshots are scored. All other metrics are skipped and reported with their reasons (neutral, "
            "not-shared, or constant).\n\n"
            "How to read the results\n"
            "- The composite score is RELATIVE to the compared set, not an absolute quality index - adding or removing "
            "a scenario rescales all scores.\n"
            "- Rank ties represent genuinely undistinguishable alternatives under the chosen weights.\n"
            "- Wins vs rank divergence: a scenario that beats others on composite score may win zero individual "
            "metrics if it is balanced, whereas specialists win specific metrics but score lower overall.\n"
            "- Check the skipped 'not-shared' metrics list before trusting a ranking - a scenario "
            "evaluated with fewer tools is not comparable.\n\n"
            "Using the results: rank the audited alternatives from Batch Plan Auditor or Scenario Pipeline "
            "to choose the best option. Weight metrics to reflect plan priorities and show the weights next to "
            "any published ranking. Use the generated HTML ranking board in option meetings to visualize trade-offs "
            "and scores."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterString(
            self.FILES, self.tr("Snapshot files (paths, ';' or ',' separated)"),
            defaultValue="", optional=True))

        self.addParameter(QgsProcessingParameterFile(
            self.FOLDER, self.tr("Snapshot folder (contains *.json)"),
            behavior=QgsProcessingParameterFile.Folder, optional=True))

        self.addParameter(QgsProcessingParameterString(
            self.WEIGHTS, self.tr("Metric weights 'key=weight, ...' (empty = equal)"),
            defaultValue="", optional=True))

        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_TABLE, self.tr("Ranking"),
            type=QgsProcessing.TypeVector))

        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_DETAIL, self.tr("Metric detail"),
            type=QgsProcessing.TypeVector))

        self.addParameter(QgsProcessingParameterFileDestination(
            self.OUTPUT_HTML, self.tr("Ranking board (HTML)"),
            self.tr("HTML files (*.html)"), optional=True,
            createByDefault=False))

    def processAlgorithm(self, parameters, context, feedback):
        files_str = self.parameterAsString(parameters, self.FILES, context).strip()
        folder_path = self.parameterAsFile(parameters, self.FOLDER, context).strip()
        weights_str = self.parameterAsString(parameters, self.WEIGHTS, context).strip()
        html_path = self.parameterAsFileOutput(parameters, self.OUTPUT_HTML, context)

        # Collect paths from FILES + FOLDER
        tokens = []
        if files_str:
            if ";" in files_str:
                raw_tokens = files_str.split(";")
            else:
                raw_tokens = files_str.split(",")
            for t in raw_tokens:
                t = t.strip()
                if t.startswith(('"', "'")) and t.endswith(t[0]):
                    t = t[1:-1].strip()
                if t:
                    tokens.append(t)

        folder_files = []
        if folder_path and os.path.isdir(folder_path):
            filenames = sorted(os.listdir(folder_path))
            for fn in filenames:
                if fn.lower().endswith(".json"):
                    folder_files.append(os.path.join(folder_path, fn))

        seen = set()
        unique_paths = []
        for p in tokens + folder_files:
            abs_p = os.path.abspath(p)
            norm_p = os.path.normcase(abs_p)
            if norm_p not in seen:
                seen.add(norm_p)
                unique_paths.append(abs_p)

        if len(unique_paths) < 2:
            raise QgsProcessingException(
                self.tr("Fewer than 2 snapshot files collected. Please provide sufficient paths in FILES and/or FOLDER.")
            )

        # Read snapshot JSONs
        snapshots = []
        for path in unique_paths:
            snapshots.append(_read_snapshot(path))

        # Parse weights
        try:
            weights, unknown_keys = scenario.parse_weights(weights_str)
        except ValueError as exc:
            raise QgsProcessingException(str(exc))

        if unknown_keys:
            feedback.pushWarning(
                self.tr(f"Unknown weight keys ignored: {', '.join(unknown_keys)}")
            )

        # Rank snapshots
        try:
            result = scenario.rank(snapshots, weights)
        except ValueError as exc:
            raise QgsProcessingException(str(exc))

        # Log
        feedback.pushInfo(self.tr(f"Ranking {len(snapshots)} snapshots..."))
        feedback.pushInfo(self.tr(f"Scored metrics: {len(result['metrics'])}"))
        for item in result["skipped"]:
            feedback.pushInfo(self.tr(f"Skipped metric '{item['key']}': {item['reason']}"))

        verdict = "  ".join(f"{sc['rank']}. {sc['name']} ({sc['score']:.1f})" for sc in result["scenarios"])
        feedback.pushInfo(self.tr(verdict))

        # Sinks
        fields_table = self.make_fields(
            ("rank", INT), ("scenario", STRING), ("score", DOUBLE),
            ("wins", INT), ("n_metrics", INT)
        )
        sink_table, dest_table = self.parameterAsSink(
            parameters, self.OUT_TABLE, context, fields_table,
            QgsWkbTypes.NoGeometry, QgsCoordinateReferenceSystem()
        )

        for sc in result["scenarios"]:
            feat = QgsFeature(fields_table)
            feat.setAttributes([
                int(sc["rank"]), str(sc["name"]), float(sc["score"]),
                int(sc["wins"]), int(sc["n_metrics"])
            ])
            sink_table.addFeature(feat, QgsFeatureSink.FastInsert)

        fields_detail = self.make_fields(
            ("metric", STRING), ("label", STRING), ("direction", INT),
            ("weight", DOUBLE), ("scenario", STRING), ("value", DOUBLE),
            ("norm", DOUBLE)
        )
        sink_detail, dest_detail = self.parameterAsSink(
            parameters, self.OUT_DETAIL, context, fields_detail,
            QgsWkbTypes.NoGeometry, QgsCoordinateReferenceSystem()
        )

        for mr in result["metrics"]:
            for sc in result["scenarios"]:
                name = sc["name"]
                feat = QgsFeature(fields_detail)
                feat.setAttributes([
                    str(mr["key"]), str(mr["label"]), int(mr["direction"]),
                    float(mr["weight"]), str(name), float(mr["values"][name]),
                    float(mr["norms"][name])
                ])
                sink_detail.addFeature(feat, QgsFeatureSink.FastInsert)

        results = {
            self.OUT_TABLE: dest_table,
            self.OUT_DETAIL: dest_detail,
        }

        if html_path:
            html = rpt.build_rank_html(
                self.tr("Scenario Ranking"), result,
                weights_note=weights_str, generated=""
            )
            try:
                with open(html_path, "w", encoding="utf-8") as fh:
                    fh.write(html)
            except OSError as exc:
                raise QgsProcessingException(
                    self.tr(f"Could not write the HTML report: {exc}")
                )
            feedback.pushInfo(self.tr(f"Ranking board written: {html_path}"))
            results[self.OUTPUT_HTML] = html_path

        return results

    def createInstance(self):
        return ScenarioRankAlgorithm()
