# -*- coding: utf-8 -*-
"""Batch Plan Auditor: run the standard PlanX battery and snapshot it."""
from __future__ import annotations

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsFeatureSink,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingMultiStepFeedback,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterMultipleLayers,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
    QgsProcessingUtils,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_REPORT, PlanXAlgorithm, STRING
from ..collect import collect
from ..engine import report as rpt
from ..engine import scenario


class PlanAuditAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_REPORT
    ICON = "tool_planaudit.png"
    NAME = "NAME"
    NETWORK = "NETWORK"
    DEMAND = "DEMAND"
    POP_FIELD = "POP_FIELD"
    AMENITIES = "AMENITIES"
    THRESHOLD = "THRESHOLD"
    LANDUSE = "LANDUSE"
    CATEGORY_FIELD = "CATEGORY_FIELD"
    POPULATION = "POPULATION"
    STANDARDS = "STANDARDS"
    FACILITIES = "FACILITIES"
    FACILITY_ID = "FACILITY_ID"
    CAPACITY_FIELD = "CAPACITY_FIELD"
    MAX_COST = "MAX_COST"
    GREENS = "GREENS"
    HIERARCHY = "HIERARCHY"
    OUTPUT_JSON = "OUTPUT_JSON"
    OUTPUT_HTML = "OUTPUT_HTML"
    OUT_METRICS = "OUT_METRICS"

    def name(self):
        return "planaudit"

    def displayName(self):
        return self.tr("Batch Plan Auditor")

    def shortHelpString(self):
        return self.tr(
            "The WHOLE standard battery in one run: give the plan's core "
            "layers once and the auditor chains the PlanX tools, gathers "
            "their scores into one scenario snapshot and (optionally) "
            "writes the one-file Plan Performance Report.\n\n"
            "What runs (each part optional - supply its inputs and it "
            "joins the battery):\n"
            "- 15-minute access score (network + demand + amenity layers);\n"
            "- Walkability audit (network, plus land use for the mix and "
            "the amenities as destinations);\n"
            "- Land-use balance vs per-capita standards (land use + "
            "population + standards);\n"
            "- Facility adequacy (facilities with capacities + demand);\n"
            "- Green space access (green polygons + hierarchy ladder);\n"
            "- Access equity (Gini over the access scores).\n\n"
            "Everything lands in the snapshot JSON - ready for Scenario "
            "Compare (A/B): audit plan A, audit plan B, compare. The "
            "metric table mirrors the snapshot; the HTML report carries "
            "the access, balance and adequacy sections.\n\n"
            "Model-designer friendly and fully headless: one call turns a "
            "set of plan layers into a comparable scorecard.\n\n"
            "How to read the results\n"
            "- Read the metric table as a triage list, worst first: mean "
            "access and low-walk share point at network/amenity work, "
            "compliance and deficits at land budgeting, covered share "
            "and overloads at facility programming, the Gini at "
            "distributional problems no mean will show.\n"
            "- The PPI is the summary needle - meaningful over "
            "iterations of the same plan, weak as an absolute grade "
            "(sections you did not feed cannot pull it down).\n"
            "- Each headline number has a dedicated tool behind it; when "
            "a number looks wrong, run that tool alone and inspect its "
            "map - the auditor's job is breadth, not depth.\n\n"
            "Using the results: audit every alternative with the SAME "
            "inputs and thresholds so the snapshots are comparable; keep "
            "the JSON per iteration as the plan's metric history; the "
            "sentence for the report is 'audited on the standard "
            "battery, improved on X of Y metrics since draft 1'."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterString(
            self.NAME, self.tr("Scenario name"), "Plan"))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("Street network (lines)"),
            [QgsProcessing.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.DEMAND, self.tr("Demand / origins (points or buildings)"),
            [QgsProcessing.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterField(
            self.POP_FIELD, self.tr("Population field (empty = 1 per point)"),
            parentLayerParameterName=self.DEMAND, optional=True,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterMultipleLayers(
            self.AMENITIES,
            self.tr("Amenity layers for the access score (optional)"),
            QgsProcessing.TypeVectorAnyGeometry, optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.THRESHOLD, self.tr("Access threshold (minutes)"),
            QgsProcessingParameterNumber.Double, 15.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.LANDUSE, self.tr("Land-use polygons (optional)"),
            [QgsProcessing.TypeVectorPolygon], optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.CATEGORY_FIELD, self.tr("Land-use category field"),
            parentLayerParameterName=self.LANDUSE, optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.POPULATION, self.tr("Planned population (for the standards)"),
            QgsProcessingParameterNumber.Double, 0.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterString(
            self.STANDARDS, self.tr("Per-capita standards"),
            "green=10, school=4", optional=True))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.FACILITIES, self.tr("Facilities with capacity (optional)"),
            [QgsProcessing.TypeVectorPoint], optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.FACILITY_ID, self.tr("Facility ID field"),
            parentLayerParameterName=self.FACILITIES, optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.CAPACITY_FIELD, self.tr("Facility capacity field"),
            parentLayerParameterName=self.FACILITIES, optional=True,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.MAX_COST, self.tr("Facility catchment (map units)"),
            QgsProcessingParameterNumber.Double, 500.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.GREENS, self.tr("Public green spaces (optional)"),
            [QgsProcessing.TypeVectorPolygon], optional=True))
        self.addParameter(QgsProcessingParameterString(
            self.HIERARCHY, self.tr("Green hierarchy 'min_ha=max_dist, ...'"),
            "0.5=300, 2=800", optional=True))
        self.addParameter(QgsProcessingParameterFileDestination(
            self.OUTPUT_JSON, self.tr("Scenario snapshot (JSON)"),
            self.tr("JSON files (*.json)")))
        self.addParameter(QgsProcessingParameterFileDestination(
            self.OUTPUT_HTML, self.tr("Plan Performance Report (HTML)"),
            self.tr("HTML files (*.html)"), optional=True,
            createByDefault=False))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_METRICS, self.tr("Audit metrics"),
            type=QgsProcessing.TypeVector))

    def processAlgorithm(self, parameters, context, feedback):
        import processing

        name = self.parameterAsString(parameters, self.NAME, context)
        network = self.parameterAsVectorLayer(parameters, self.NETWORK, context)
        demand = self.parameterAsVectorLayer(parameters, self.DEMAND, context)
        pop_field = self.parameterAsString(parameters, self.POP_FIELD, context)
        amenities = self.parameterAsLayerList(parameters, self.AMENITIES, context)
        threshold = self.parameterAsDouble(parameters, self.THRESHOLD, context)
        landuse = self.parameterAsVectorLayer(parameters, self.LANDUSE, context)
        cat_field = self.parameterAsString(parameters, self.CATEGORY_FIELD, context)
        population = self.parameterAsDouble(parameters, self.POPULATION, context)
        standards = self.parameterAsString(parameters, self.STANDARDS, context)
        facilities = self.parameterAsVectorLayer(parameters, self.FACILITIES, context)
        fac_id = self.parameterAsString(parameters, self.FACILITY_ID, context)
        cap_field = self.parameterAsString(parameters, self.CAPACITY_FIELD, context)
        max_cost = self.parameterAsDouble(parameters, self.MAX_COST, context)
        greens = self.parameterAsVectorLayer(parameters, self.GREENS, context)
        hierarchy = self.parameterAsString(parameters, self.HIERARCHY, context)
        json_path = self.parameterAsFileOutput(parameters, self.OUTPUT_JSON, context)
        html_path = self.parameterAsFileOutput(parameters, self.OUTPUT_HTML, context)

        parts = []
        run_access = bool(amenities)
        run_balance = (landuse is not None and cat_field and population > 0
                       and standards.strip())
        run_adequacy = facilities is not None and fac_id and cap_field
        run_green = greens is not None and hierarchy.strip()
        for flag, label in ((run_access, "access score"),
                            (True, "walkability"),
                            (run_balance, "land-use balance"),
                            (run_adequacy, "facility adequacy"),
                            (run_green, "green access")):
            if flag:
                parts.append(label)
        feedback.pushInfo(self.tr("Battery: " + ", ".join(parts) + "."))
        steps = QgsProcessingMultiStepFeedback(len(parts) + 1, feedback)
        step = 0

        def child(alg_id, params):
            return processing.run(alg_id, params, context=context,
                                  feedback=steps, is_child_algorithm=True)

        def as_layer(ref):
            return QgsProcessingUtils.mapLayerFromString(str(ref), context)

        metrics = {}
        layers = {"access": None, "balance": None, "facilities": None,
                  "demand": None, "density": None}

        access_layer = None
        if run_access:
            res = child("planx:accessscore", {
                "ORIGINS": demand, "NETWORK": network,
                "AMENITIES": amenities, "POP_FIELD": pop_field or None,
                "SPEED": 4.8, "THRESHOLD": threshold,
                "OUTPUT": "TEMPORARY_OUTPUT"})
            access_layer = as_layer(res["OUTPUT"])
            layers["access"] = access_layer
            step += 1
            steps.setCurrentStep(step)
            if feedback.isCanceled():
                raise QgsProcessingException("Cancelled.")

        walk_params = {"NETWORK": network, "RADIUS": 400.0,
                       "OUT_SEGMENTS": "TEMPORARY_OUTPUT"}
        if landuse is not None and cat_field:
            walk_params["LANDUSE"] = landuse
            walk_params["CATEGORY_FIELD"] = cat_field
        if amenities:
            walk_params["POIS"] = amenities[0]
        res = child("planx:walkability", walk_params)
        walk_layer = as_layer(res["OUT_SEGMENTS"])
        if walk_layer is not None:
            scores = [f["walk_score"] for f in walk_layer.getFeatures()
                      if f["walk_score"] is not None]
            if scores:
                metrics["walk_score_mean"] = sum(scores) / len(scores)
                metrics["walk_low_share"] = (
                    100.0 * sum(1 for s in scores if s < 50.0) / len(scores))
        step += 1
        steps.setCurrentStep(step)

        if run_balance:
            res = child("planx:landusebalance", {
                "LANDUSE": landuse, "CATEGORY_FIELD": cat_field,
                "POPULATION": population, "STANDARDS": standards,
                "OUTPUT": "TEMPORARY_OUTPUT"})
            layers["balance"] = as_layer(res["OUTPUT"])
            step += 1
            steps.setCurrentStep(step)

        if run_adequacy:
            res = child("planx:facilityadequacy", {
                "NETWORK": network, "DEMAND": demand,
                "POP_FIELD": pop_field or None, "FACILITIES": facilities,
                "FACILITY_ID": fac_id, "CAPACITY_FIELD": cap_field,
                "MAX_COST": max_cost,
                "OUT_FACILITIES": "TEMPORARY_OUTPUT",
                "OUT_DEMAND": "TEMPORARY_OUTPUT"})
            layers["facilities"] = as_layer(res["OUT_FACILITIES"])
            layers["demand"] = as_layer(res["OUT_DEMAND"])
            step += 1
            steps.setCurrentStep(step)

        if run_green:
            res = child("planx:greenaccess", {
                "NETWORK": network, "DEMAND": demand,
                "POP_FIELD": pop_field or None, "GREENS": greens,
                "HIERARCHY": hierarchy,
                "OUT_DEMAND": "TEMPORARY_OUTPUT",
                "OUT_SUMMARY": "TEMPORARY_OUTPUT"})
            green_summary = as_layer(res["OUT_SUMMARY"])
            if green_summary is not None:
                coverages = [f["coverage_pct"]
                             for f in green_summary.getFeatures()]
                if coverages:
                    metrics["green_coverage_worst"] = min(coverages)
            step += 1
            steps.setCurrentStep(step)

        if access_layer is not None:
            res = child("planx:accessequity", {
                "INPUT": access_layer, "VALUE_FIELD": "score",
                "POP_FIELD": pop_field or None, "DIRECTION": 0,
                "OUT_POINTS": "TEMPORARY_OUTPUT",
                "OUT_SUMMARY": "TEMPORARY_OUTPUT"})
            eq_summary = as_layer(res["OUT_SUMMARY"])
            if eq_summary is not None:
                for f in eq_summary.getFeatures():
                    if str(f["scope"]) == "ALL":
                        metrics["access_gini"] = float(f["gini"])
                        break

        access, balance, adequacy, density = collect(layers)
        a_sum = rpt.access_summary(access["scores"]) if access else None
        b_sum = rpt.balance_summary(balance) if balance is not None else None
        q_sum = (rpt.adequacy_summary(adequacy["facilities"], adequacy["demand"])
                 if adequacy else None)
        d_sum = rpt.density_summary(density["values"]) if density else None
        overall = rpt.overall_score(a_sum, b_sum, q_sum)
        metrics.update(scenario.metrics_from_summaries(
            a_sum, b_sum, q_sum, d_sum, overall))
        if not metrics:
            raise QgsProcessingException(
                "The battery produced no metrics - check the inputs.")

        snap = scenario.snapshot(name, metrics)
        try:
            with open(json_path, "w", encoding="utf-8") as fh:
                fh.write(scenario.to_json(snap))
        except OSError as exc:
            raise QgsProcessingException(f"Could not write the snapshot: {exc}")

        fields = self.make_fields(
            ("metric", STRING), ("metric_key", STRING), ("value", DOUBLE))
        sink, dest = self.parameterAsSink(
            parameters, self.OUT_METRICS, context, fields,
            QgsWkbTypes.NoGeometry, QgsCoordinateReferenceSystem())
        for key in metrics:
            feat = QgsFeature(fields)
            feat.setAttributes([scenario.label_of(key), key,
                                round(float(metrics[key]), 4)])
            sink.addFeature(feat, QgsFeatureSink.FastInsert)

        results = {self.OUTPUT_JSON: json_path, self.OUT_METRICS: dest}
        if html_path:
            from .alg_performance_report import _plugin_version
            html = rpt.build_html(
                name, population=population or None, access=access,
                balance=balance, adequacy=adequacy, density=density,
                plugin_version=_plugin_version())
            try:
                with open(html_path, "w", encoding="utf-8") as fh:
                    fh.write(html)
            except OSError as exc:
                raise QgsProcessingException(
                    f"Could not write the report: {exc}")
            results[self.OUTPUT_HTML] = html_path
            feedback.pushInfo(self.tr(f"Report written: {html_path}"))

        if overall is not None:
            feedback.pushInfo(self.tr(
                f"Plan Performance Index {overall:.1f}."))
        feedback.pushInfo(self.tr(
            f"Snapshot '{name}' with {len(metrics)} metrics: {json_path}"))
        return results

    def createInstance(self):
        return PlanAuditAlgorithm()
