# -*- coding: utf-8 -*-
"""Land-Use Balance: per-capita areas vs configurable standards."""
from __future__ import annotations

from qgis.core import (
    QgsFeature,
    QgsFeatureSink,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsWkbTypes,
)

from .base import DOUBLE, PlanXAlgorithm, STRING
from .base import GROUP_STANDARDS
from ..engine import standards as std

DEFAULT_STANDARDS = "green=10, park=10, playground=1.5, education=4, school=4, health=1.5, social=1.5, sport=3.5, market=0.5"


class LandUseBalanceAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_STANDARDS
    LANDUSE = "LANDUSE"
    CATEGORY_FIELD = "CATEGORY_FIELD"
    POPULATION = "POPULATION"
    STANDARDS = "STANDARDS"
    OUTPUT = "OUTPUT"

    def name(self):
        return "landusebalance"

    def displayName(self):
        return self.tr("Land-Use Balance (Per-Capita Standards)")

    def shortHelpString(self):
        return self.tr(
            "Builds the classic land-use balance table: total area per "
            "category, square metres per capita, the area required by your "
            "per-capita standards, and the surplus or deficit - the core QA "
            "check of any land-use plan.\n\n"
            "Standards are free text, e.g. 'green=10, education=4, "
            "health=1.5' (10 m2 of green space per capita...). Keywords "
            "match category names case-insensitively by containment, so "
            "'green' catches 'Urban Green Area'. The defaults are "
            "ILLUSTRATIVE - replace them with the values of your own "
            "regulation (e.g. the Turkish Spatial Plans Regulation annex).\n\n"
            "Output: one row per category found in the plan with status "
            "'Meets standard' / 'Deficit' / 'No standard'."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.LANDUSE, self.tr("Land-use plan (polygons)"),
            [QgsProcessing.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterField(
            self.CATEGORY_FIELD, self.tr("Land-use category field"),
            parentLayerParameterName=self.LANDUSE))
        self.addParameter(QgsProcessingParameterNumber(
            self.POPULATION, self.tr("Planned population"),
            QgsProcessingParameterNumber.Double, 10000.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterString(
            self.STANDARDS, self.tr("Per-capita standards (keyword=m2, ...)"),
            DEFAULT_STANDARDS))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Land-use balance table"),
            type=QgsProcessing.TypeVector))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.LANDUSE, context)
        cat_field = self.parameterAsString(parameters, self.CATEGORY_FIELD, context)
        population = self.parameterAsDouble(parameters, self.POPULATION, context)
        self.require_projected(source, "Land-use plan")
        try:
            stds = std.parse_standards(
                self.parameterAsString(parameters, self.STANDARDS, context))
        except ValueError as exc:
            raise QgsProcessingException(str(exc))

        cat_idx = source.fields().lookupField(cat_field)
        areas = {}
        for f in source.getFeatures():
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
            category = str(f.attributes()[cat_idx])
            areas[category] = areas.get(category, 0.0) + g.area()
        if not areas:
            raise QgsProcessingException("No polygons with a category value found.")

        rows = std.balance_rows(areas, population, stds)
        fields = self.make_fields(
            ("category", STRING), ("area_m2", DOUBLE), ("m2_capita", DOUBLE),
            ("std_key", STRING), ("std_m2cap", DOUBLE), ("required", DOUBLE),
            ("balance_m2", DOUBLE), ("status", STRING))
        sink, dest = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields,
            QgsWkbTypes.NoGeometry, source.sourceCrs())
        deficits = 0
        for row in rows:
            f = QgsFeature(fields)
            f.setAttributes([
                row["category"], round(row["area_m2"], 1),
                round(row["m2_per_capita"], 3), row["standard_key"],
                row["std_m2_capita"], round(row["required_m2"], 1),
                round(row["balance_m2"], 1), row["status"]])
            sink.addFeature(f, QgsFeatureSink.FastInsert)
            mark = ""
            if row["status"] == "Deficit":
                deficits += 1
                mark = "  <-- DEFICIT"
            feedback.pushInfo(
                f"  {row['category']}: {row['area_m2']:.0f} m2 "
                f"({row['m2_per_capita']:.2f} m2/capita){mark}")
        feedback.pushInfo(self.tr(
            f"{len(rows)} categories, {deficits} in deficit "
            f"for a population of {population:g}."))
        return {self.OUTPUT: dest}

    def createInstance(self):
        return LandUseBalanceAlgorithm()
