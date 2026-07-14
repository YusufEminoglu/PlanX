# -*- coding: utf-8 -*-
"""Scenario Snapshot: capture the plan score metrics of the open project."""
from __future__ import annotations

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsFeatureSink,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_REPORT, PlanXAlgorithm, STRING
from ..collect import auto_detect, collect
from ..engine import report as rpt
from ..engine import scenario


class ScenarioSnapshotAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_REPORT
    ICON = "tool_scenariosnapshot.png"
    NAME = "NAME"
    ACCESS = "ACCESS"
    BALANCE = "BALANCE"
    FACILITIES = "FACILITIES"
    DEMAND = "DEMAND"
    DENSITY = "DENSITY"
    OUTPUT_JSON = "OUTPUT_JSON"
    OUT_METRICS = "OUT_METRICS"

    def name(self):
        return "scenariosnapshot"

    def displayName(self):
        return self.tr("Scenario Snapshot")

    def shortHelpString(self):
        return self.tr(
            "Captures the plan score metrics of the CURRENT PROJECT into a "
            "scenario snapshot JSON - the batchable front door to scenario "
            "comparison: run the PlanX tools for plan alternative A, "
            "snapshot, rerun for alternative B, snapshot, then feed both "
            "files to Scenario Compare (A/B). Works in the model designer, "
            "so a whole plan-evaluation pipeline can end in a snapshot.\n\n"
            "PlanX output layers are auto-detected by their field "
            "signatures - the access-score layer (score + n_reach), the "
            "land-use balance table (balance_m2 + m2_capita), facility "
            "adequacy (utilization + assigned), demand coverage (covered + "
            "net_cost) and the density grid (dens_ha + value). Any of them "
            "can also be pinned explicitly; an explicit choice always wins "
            "over auto-detection.\n\n"
            "The snapshot stores the same metrics as the Plan Dashboard "
            "cards: Plan Performance Index, accessibility mean/median and "
            "shares, standards compliance and deficits, covered population "
            "share, facility overload/unused counts, density summary.\n\n"
            "Outputs the snapshot JSON file plus a metric table (key, "
            "label, value) for inspection.\n\n"
            "How to read the results\n"
            "- The metric table is the scenario reduced to comparable "
            "numbers; single snapshots are rarely the point - the value "
            "appears when two of them meet in Scenario Compare.\n"
            "- Check the log's detection lines before trusting the "
            "numbers: a snapshot silently missing a section (no density "
            "grid detected, for instance) will later read as 'metric "
            "missing on one side' in the comparison.\n"
            "- Give scenarios honest names ('2040 compact', '2040 "
            "corridor') - the name is carried into every later report.\n\n"
            "Using the results: end every evaluation model with a "
            "snapshot node so each plan run leaves a comparable record; "
            "keep the JSONs in the project folder as the plan's metric "
            "history; snapshot before and after a major revision even "
            "within one alternative - Scenario Compare then documents "
            "what the revision bought."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterString(
            self.NAME, self.tr("Scenario name"), "Scenario A"))
        for key, label in (
                (self.ACCESS, "Access-score layer (empty = auto-detect)"),
                (self.BALANCE, "Land-use balance table (empty = auto-detect)"),
                (self.FACILITIES, "Facility adequacy layer (empty = auto-detect)"),
                (self.DEMAND, "Demand coverage layer (empty = auto-detect)"),
                (self.DENSITY, "Density grid (empty = auto-detect)")):
            self.addParameter(QgsProcessingParameterVectorLayer(
                key, self.tr(label), [QgsProcessing.SourceType.TypeVector],
                optional=True))
        self.addParameter(QgsProcessingParameterFileDestination(
            self.OUTPUT_JSON, self.tr("Scenario snapshot (JSON)"),
            self.tr("JSON files (*.json)")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_METRICS, self.tr("Snapshot metrics"),
            type=QgsProcessing.SourceType.TypeVector))

    def processAlgorithm(self, parameters, context, feedback):
        name = self.parameterAsString(parameters, self.NAME, context)
        json_path = self.parameterAsFileOutput(
            parameters, self.OUTPUT_JSON, context)

        layers = auto_detect(context.project())
        explicit = {
            "access": self.parameterAsVectorLayer(parameters, self.ACCESS, context),
            "balance": self.parameterAsVectorLayer(parameters, self.BALANCE, context),
            "facilities": self.parameterAsVectorLayer(
                parameters, self.FACILITIES, context),
            "demand": self.parameterAsVectorLayer(parameters, self.DEMAND, context),
            "density": self.parameterAsVectorLayer(parameters, self.DENSITY, context),
        }
        for role, lyr in explicit.items():
            if lyr is not None:
                layers[role] = lyr
        used = [f"{role}: {lyr.name()}" for role, lyr in layers.items()
                if lyr is not None]
        if not used:
            raise QgsProcessingException(
                "No PlanX output layers found - run the PlanX tools first "
                "(access score, land-use balance, facility adequacy, density "
                "grid) or pin the layers explicitly.")
        feedback.pushInfo(self.tr("Reading " + "; ".join(used)))

        access, balance, adequacy, density = collect(layers)
        a_sum = rpt.access_summary(access["scores"]) if access else None
        b_sum = rpt.balance_summary(balance) if balance is not None else None
        q_sum = (rpt.adequacy_summary(adequacy["facilities"], adequacy["demand"])
                 if adequacy else None)
        d_sum = rpt.density_summary(density["values"]) if density else None
        overall = rpt.overall_score(a_sum, b_sum, q_sum)
        metrics = scenario.metrics_from_summaries(a_sum, b_sum, q_sum, d_sum,
                                                  overall)
        if not metrics:
            raise QgsProcessingException(
                "The detected layers produced no metrics - are they really "
                "PlanX outputs?")

        snap = scenario.snapshot(name, metrics)
        try:
            with open(json_path, "w", encoding="utf-8") as fh:
                fh.write(scenario.to_json(snap))
        except OSError as exc:
            raise QgsProcessingException(
                f"Could not write the snapshot: {exc}")

        fields = self.make_fields(
            ("metric", STRING), ("metric_key", STRING), ("value", DOUBLE))
        sink, dest = self.parameterAsSink(
            parameters, self.OUT_METRICS, context, fields,
            QgsWkbTypes.Type.NoGeometry, QgsCoordinateReferenceSystem())
        for key in metrics:
            feat = QgsFeature(fields)
            feat.setAttributes([scenario.label_of(key), key,
                                round(float(metrics[key]), 4)])
            sink.addFeature(feat, QgsFeatureSink.Flag.FastInsert)

        if overall is not None:
            feedback.pushInfo(self.tr(
                f"Plan Performance Index {overall:.1f} - snapshot "
                f"'{name}' with {len(metrics)} metrics: {json_path}"))
        return {self.OUTPUT_JSON: json_path, self.OUT_METRICS: dest}

    def createInstance(self):
        return ScenarioSnapshotAlgorithm()
