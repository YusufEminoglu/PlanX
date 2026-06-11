# -*- coding: utf-8 -*-
"""Plan Performance Report: one-click HTML scorecard of the plan."""
from __future__ import annotations

import configparser
import os

from qgis.core import (
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
)

from .base import GROUP_REPORT, PLUGIN_DIR, PlanXAlgorithm
from ..engine import report as rpt


def _plugin_version() -> str:
    try:
        ini = configparser.ConfigParser()
        ini.read(os.path.join(PLUGIN_DIR, "metadata.txt"), encoding="utf-8")
        return "v" + ini["general"]["version"]
    except Exception:
        return ""


def layer_rows(source, names):
    """Read ``names`` fields of a vector source into plain dict rows.

    ``names`` maps output keys to field names; missing fields read None.
    """
    idx = {key: source.fields().lookupField(fname) for key, fname in names.items()}
    rows = []
    for f in source.getFeatures():
        attrs = f.attributes()
        rows.append({key: (attrs[i] if i >= 0 else None) for key, i in idx.items()})
    return rows


class PlanPerformanceReportAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_REPORT
    TITLE = "TITLE"
    POPULATION = "POPULATION"
    ACCESS = "ACCESS"
    ACCESS_SCORE = "ACCESS_SCORE"
    BALANCE = "BALANCE"
    FACILITIES = "FACILITIES"
    DEMAND = "DEMAND"
    DEMAND_POP = "DEMAND_POP"
    DENSITY = "DENSITY"
    DENSITY_FIELD = "DENSITY_FIELD"
    OUTPUT = "OUTPUT"

    def name(self):
        return "performancereport"

    def displayName(self):
        return self.tr("Plan Performance Report (HTML)")

    def shortHelpString(self):
        return self.tr(
            "Builds a single-file HTML 'Plan Performance Report' from the "
            "outputs of the other PlanX tools - score cards, charts and "
            "compliance tables, ready to share with stakeholders. No "
            "external services: charts are inline SVG drawn by the "
            "embedded engine.\n\n"
            "Feed it any combination of (all optional, at least one):\n"
            "- Access scores: output of Multi-Amenity Access Score - score "
            "distribution, score map and the accessibility card;\n"
            "- Land-use balance table: output of Land-Use Balance - "
            "provided-vs-required bars and the compliance card;\n"
            "- Facility adequacy + demand coverage: outputs of Facility "
            "Adequacy - utilization table and the covered-population card;\n"
            "- Density grid: output of Density Grid - density summary.\n\n"
            "The same cards are shown live in the PlanX Dashboard dock "
            "(PlanX menu > Plan Dashboard)."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterString(
            self.TITLE, self.tr("Report title"), "Urban Plan"))
        self.addParameter(QgsProcessingParameterNumber(
            self.POPULATION, self.tr("Planned population (0 = omit)"),
            QgsProcessingParameterNumber.Double, 0.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.ACCESS, self.tr("Access scores (from Multi-Amenity Access Score)"),
            [QgsProcessing.TypeVectorAnyGeometry], optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.ACCESS_SCORE, self.tr("Score field"),
            parentLayerParameterName=self.ACCESS, optional=True,
            type=QgsProcessingParameterField.Numeric, defaultValue="score"))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.BALANCE, self.tr("Land-use balance table (from Land-Use Balance)"),
            [QgsProcessing.TypeVector], optional=True))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.FACILITIES, self.tr("Facility adequacy (from Facility Adequacy)"),
            [QgsProcessing.TypeVectorAnyGeometry], optional=True))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.DEMAND, self.tr("Demand coverage (from Facility Adequacy)"),
            [QgsProcessing.TypeVectorAnyGeometry], optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.DEMAND_POP, self.tr("Demand population field (empty = 1 per point)"),
            parentLayerParameterName=self.DEMAND, optional=True,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.DENSITY, self.tr("Density grid (from Density Grid)"),
            [QgsProcessing.TypeVectorAnyGeometry], optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.DENSITY_FIELD, self.tr("Density field"),
            parentLayerParameterName=self.DENSITY, optional=True,
            type=QgsProcessingParameterField.Numeric, defaultValue="dens_ha"))
        self.addParameter(QgsProcessingParameterFileDestination(
            self.OUTPUT, self.tr("Plan Performance Report"),
            self.tr("HTML files (*.html)")))

    # ------------------------------------------------------------------ #
    def _access_data(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.ACCESS, context)
        if source is None:
            return None
        field = self.parameterAsString(parameters, self.ACCESS_SCORE, context) or "score"
        idx = source.fields().lookupField(field)
        if idx < 0:
            raise QgsProcessingException(
                f"Access layer has no numeric field '{field}'.")
        scores, points = [], []
        for f in source.getFeatures():
            try:
                scores.append(float(f.attributes()[idx]))
            except (TypeError, ValueError):
                continue
            g = f.geometry()
            if g is not None and not g.isEmpty():
                p = g.pointOnSurface().asPoint()
                points.append((p.x(), p.y()))
            else:
                points.append((0.0, 0.0))
        feedback.pushInfo(self.tr(f"Access scores: {len(scores)} origins."))
        return {"scores": scores, "points": points} if scores else None

    def _balance_rows(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.BALANCE, context)
        if source is None:
            return None
        rows = layer_rows(source, {
            "category": "category", "area_m2": "area_m2",
            "m2_per_capita": "m2_capita", "required_m2": "required",
            "balance_m2": "balance_m2", "status": "status"})
        for r in rows:
            for k in ("area_m2", "m2_per_capita", "required_m2", "balance_m2"):
                r[k] = float(r[k] or 0.0)
            r["status"] = str(r["status"] or "")
        feedback.pushInfo(self.tr(f"Land-use balance: {len(rows)} categories."))
        return rows

    def _adequacy_data(self, parameters, context, feedback):
        fac = self.parameterAsSource(parameters, self.FACILITIES, context)
        if fac is None:
            return None
        f_rows = layer_rows(fac, {
            "facility": "facility", "capacity": "capacity",
            "assigned": "assigned", "utilization": "utilization",
            "status": "status"})
        d_rows = []
        dem = self.parameterAsSource(parameters, self.DEMAND, context)
        if dem is not None:
            pop_field = self.parameterAsString(parameters, self.DEMAND_POP, context)
            names = {"covered": "covered"}
            if pop_field:
                names["pop"] = pop_field
            d_rows = layer_rows(dem, names)
        feedback.pushInfo(self.tr(
            f"Facility adequacy: {len(f_rows)} facilities, "
            f"{len(d_rows)} demand points."))
        return {"facilities": f_rows, "demand": d_rows}

    def _density_data(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.DENSITY, context)
        if source is None:
            return None
        field = self.parameterAsString(parameters, self.DENSITY_FIELD, context) or "dens_ha"
        idx = source.fields().lookupField(field)
        if idx < 0:
            raise QgsProcessingException(
                f"Density layer has no numeric field '{field}'.")
        values = []
        for f in source.getFeatures():
            try:
                values.append(float(f.attributes()[idx]))
            except (TypeError, ValueError):
                continue
        feedback.pushInfo(self.tr(f"Density grid: {len(values)} cells."))
        return {"values": values} if values else None

    def processAlgorithm(self, parameters, context, feedback):
        title = self.parameterAsString(parameters, self.TITLE, context) or "Urban Plan"
        population = self.parameterAsDouble(parameters, self.POPULATION, context)
        out_path = self.parameterAsFileOutput(parameters, self.OUTPUT, context)

        access = self._access_data(parameters, context, feedback)
        balance = self._balance_rows(parameters, context, feedback)
        adequacy = self._adequacy_data(parameters, context, feedback)
        density = self._density_data(parameters, context, feedback)
        if access is None and balance is None and adequacy is None:
            raise QgsProcessingException(
                "Nothing to report: provide at least one of access scores, "
                "land-use balance or facility adequacy.")

        html = rpt.build_html(
            title, population=population or None, access=access,
            balance=balance, adequacy=adequacy, density=density,
            plugin_version=_plugin_version())
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(html)

        a_sum = rpt.access_summary(access["scores"]) if access else None
        b_sum = rpt.balance_summary(balance) if balance is not None else None
        q_sum = (rpt.adequacy_summary(adequacy["facilities"], adequacy["demand"])
                 if adequacy else None)
        for card in rpt.report_cards(a_sum, b_sum, q_sum):
            feedback.pushInfo(f"  {card['label']}: {card['value']} ({card['sub']})")
        feedback.pushInfo(self.tr(f"Report written to {out_path}"))
        return {self.OUTPUT: out_path}

    def createInstance(self):
        return PlanPerformanceReportAlgorithm()
