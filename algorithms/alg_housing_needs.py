# -*- coding: utf-8 -*-
"""Housing Needs Assessment: the standard needs identity as a tool."""
from __future__ import annotations

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsFeatureSink,
    QgsProcessing,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterNumber,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_POPULATION, PlanXAlgorithm, STRING
from ..engine import population


class HousingNeedsAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_POPULATION
    ICON = "tool_housingneeds.png"
    POP_FUTURE = "POP_FUTURE"
    HH_SIZE = "HH_SIZE"
    EXISTING = "EXISTING"
    VACANCY = "VACANCY"
    REPLACEMENT = "REPLACEMENT"
    BACKLOG = "BACKLOG"
    OUT_SUMMARY = "OUT_SUMMARY"

    def name(self):
        return "housingneeds"

    def displayName(self):
        return self.tr("Housing Needs Assessment")

    def shortHelpString(self):
        return self.tr(
            "How many dwellings must the plan deliver? The standard "
            "needs identity, as a batchable tool:\n\n"
            "1. Future households = horizon population / household size "
            "(take the population from the Population Projection tool);\n"
            "2. Target stock = households x (1 + vacancy allowance) - a "
            "healthy market needs empty units to move within;\n"
            "3. NEED = target stock - existing dwellings + replacement "
            "losses over the period + the current backlog (overcrowded / "
            "unfit units to absorb).\n\n"
            "A negative need is a surplus. The output is a metric/value "
            "table carrying every intermediate (households, target stock, "
            "components), ready for the plan report or a model chain: "
            "Population Projection feeds this tool, and its need feeds "
            "Residential Capacity to test whether the zoning can deliver "
            "it.\n\n"
            "All standards (household size, vacancy, losses, backlog) are "
            "parameters - no locale assumptions.\n\n"
            "How to read the results\n"
            "- 'need' is the delivery target the plan must zone for - "
            "but read the components before quoting it: household size "
            "is the lever everything hinges on (a 0.2 drop in household "
            "size can generate more need than a decade of growth - "
            "shrinking households need MORE units for the SAME "
            "population).\n"
            "- Zero backlog and zero replacement almost always "
            "understate need - they mean 'assume today's stock is fine "
            "and eternal'. If you lack data, note the omission rather "
            "than defaulting to optimism.\n"
            "- A surplus (negative need) with observed housing stress "
            "means the mismatch is in TYPE, price or location - this "
            "identity counts units, not affordability.\n\n"
            "Using the results: run the household-size sensitivities "
            "(e.g. 2.8 / 2.5 / 2.2) - the spread IS the honest need "
            "range; hand the need to Residential Capacity to test "
            "whether current zoning can physically deliver it; if "
            "capacity < need, the plan must upzone, extend or challenge "
            "its assumptions - there is no fourth option."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterNumber(
            self.POP_FUTURE, self.tr("Horizon population"),
            QgsProcessingParameterNumber.Type.Double, 10000.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.HH_SIZE, self.tr("Household size at the horizon"),
            QgsProcessingParameterNumber.Type.Double, 2.5, minValue=0.5,
            maxValue=15.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.EXISTING, self.tr("Existing dwellings"),
            QgsProcessingParameterNumber.Type.Double, 3500.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.VACANCY, self.tr("Vacancy allowance (share, e.g. 0.05)"),
            QgsProcessingParameterNumber.Type.Double, 0.05, minValue=0.0,
            maxValue=0.5))
        self.addParameter(QgsProcessingParameterNumber(
            self.REPLACEMENT,
            self.tr("Replacement losses over the period (units)"),
            QgsProcessingParameterNumber.Type.Double, 0.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.BACKLOG, self.tr("Backlog to absorb (units)"),
            QgsProcessingParameterNumber.Type.Double, 0.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_SUMMARY, self.tr("Housing needs summary"),
            type=QgsProcessing.SourceType.TypeVector))

    def processAlgorithm(self, parameters, context, feedback):
        pop_future = self.parameterAsDouble(parameters, self.POP_FUTURE, context)
        hh_size = self.parameterAsDouble(parameters, self.HH_SIZE, context)
        existing = self.parameterAsDouble(parameters, self.EXISTING, context)
        vacancy = self.parameterAsDouble(parameters, self.VACANCY, context)
        replacement = self.parameterAsDouble(parameters, self.REPLACEMENT, context)
        backlog = self.parameterAsDouble(parameters, self.BACKLOG, context)

        res = population.housing_needs(
            pop_future, hh_size, existing, vacancy_target=vacancy,
            replacement_units=replacement, backlog_units=backlog)

        fields = self.make_fields(("metric", STRING), ("value", DOUBLE))
        sink, dest = self.parameterAsSink(
            parameters, self.OUT_SUMMARY, context, fields,
            QgsWkbTypes.Type.NoGeometry, QgsCoordinateReferenceSystem())
        rows = [
            ("Horizon population", pop_future),
            ("Household size", hh_size),
            ("Future households", res["households"]),
            ("Vacancy allowance", vacancy),
            ("Target stock (units)", res["target_stock"]),
            ("Existing dwellings", res["existing"]),
            ("Replacement losses", res["replacement"]),
            ("Backlog", res["backlog"]),
            ("Dwellings needed", res["need"]),
        ]
        for metric, value in rows:
            feat = QgsFeature(fields)
            feat.setAttributes([metric, round(float(value), 2)])
            sink.addFeature(feat, QgsFeatureSink.Flag.FastInsert)

        verdict = ("surplus" if res["need"] < 0 else "to deliver")
        feedback.pushInfo(self.tr(
            f"{res['households']:,.0f} households -> target stock "
            f"{res['target_stock']:,.0f}; {abs(res['need']):,.0f} "
            f"dwelling(s) {verdict}."))
        return {self.OUT_SUMMARY: dest}

    def createInstance(self):
        return HousingNeedsAlgorithm()
