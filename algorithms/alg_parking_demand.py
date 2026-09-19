# -*- coding: utf-8 -*-
"""Parking Demand Estimator algorithm wrapper."""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsFeature,
    QgsFeatureSink,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterString,
)

from .base import DOUBLE, GROUP_DEMAND, PlanXAlgorithm
from ..engine import parking

#: Illustrative starting rates in the ITE Parking Generation convention, not
#: taken from it. Local standards must replace them - see shortHelpString.
DEFAULT_RATES = (
    "residential=unit:1.5, office=sqm:2.5, commercial=sqm:3.5, "
    "retail=sqm:3.0, restaurant=seat:0.2, assembly=seat:0.15, "
    "industrial=sqm:1.0, education=sqm:1.5, health=sqm:3.0"
)


class ParkingDemandAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_DEMAND
    ICON = "tool_parkingdemand.png"
    ZONES = "ZONES"
    CATEGORY_FIELD = "CATEGORY_FIELD"
    SIZE_FIELD = "SIZE_FIELD"
    RATES = "RATES"
    OUTPUT = "OUTPUT"

    def name(self):
        return "parkingdemand"

    def displayName(self):
        return self.tr("Parking Demand Estimator")

    def shortHelpString(self):
        return self.tr(
            "Screening-quality parking demand estimator.\n\n"
            "Converts each zone's land-use category and size into parking "
            "spaces demanded, using a per-category rate table you control. "
            "Each entry is category=basis:rate, where the basis says what "
            "one rate unit counts against: unit = spaces per dwelling "
            "unit, sqm = spaces per 1000 m2 gross floor area, seat = "
            "spaces per seat. A zone takes the first rate row whose "
            "category keyword it contains.\n\n"
            "The size column is read in each matched category's own basis, "
            "so the table is only fully coherent when the categories it "
            "matches share one basis. A single layer mixing dwelling "
            "counts, floor areas and seats cannot be correct for all three "
            "at once: where the bases differ, split the zones into one "
            "layer per basis and run each with its own table.\n\n"
            "The shipped rates are illustrative starting values written in "
            "the convention of the ITE Parking Generation manual (Institute "
            "of Transportation Engineers), not figures taken from it. They "
            "are not a substitute for a local standard: substitute your own "
            "municipal, campus or survey rates before quoting absolute "
            "space counts.\n\n"
            "How to read the results\n"
            "- parking_demand is one number per zone, in spaces, and is "
            "linear in the rates you typed: which zones dominate demand is "
            "robust, the absolute counts are only as good as the rates.\n"
            "- A zone whose category matches no rate row demands 0 and is "
            "listed separately in the log. That is a coverage gap in your "
            "rate table, not a real zero-demand zone - a large unmatched "
            "share means the reported total is an undercount.\n"
            "- The per-category subtotals in the log are the diagnostic "
            "that matters for policy: they show whether one land use "
            "drives the whole requirement, which is the claim any "
            "shared-parking or reduction argument has to answer.\n\n"
            "Using the results: this is the demand half of a supply "
            "balance - feed the output into Parking Supply-Demand Balance "
            "together with a counted parking inventory to get surplus and "
            "deficit per zone; test a land-use scenario by editing "
            "categories or sizes and re-running; sum parking_demand for a "
            "district requirement, reading the unmatched share first to "
            "know whether that total is trustworthy."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.ZONES, self.tr("Zone layer"),
            [QgsProcessing.SourceType.TypeVectorPolygon,
             QgsProcessing.SourceType.TypeVectorPoint]))
        self.addParameter(QgsProcessingParameterField(
            self.CATEGORY_FIELD, self.tr("Land-use category field"),
            parentLayerParameterName=self.ZONES,
            type=QgsProcessingParameterField.DataType.String))
        self.addParameter(QgsProcessingParameterField(
            self.SIZE_FIELD, self.tr("Size field (counted in the basis unit "
                                     "of the categories it matches)"),
            parentLayerParameterName=self.ZONES,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterString(
            self.RATES, self.tr("Parking rates (category=basis:rate, ...)"),
            DEFAULT_RATES))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Parking demand layer (zones with their "
                                 "demand)")))

    def processAlgorithm(self, parameters, context, feedback):
        zones = self.parameterAsSource(parameters, self.ZONES, context)
        category_field = self.parameterAsString(
            parameters, self.CATEGORY_FIELD, context)
        size_field = self.parameterAsString(parameters, self.SIZE_FIELD, context)
        try:
            rates = parking.parse_rates(
                self.parameterAsString(parameters, self.RATES, context))
        except ValueError as exc:
            raise QgsProcessingException(str(exc))

        cat_idx = zones.fields().lookupField(category_field)
        size_idx = zones.fields().lookupField(size_field)

        feats = []
        categories = []
        sizes = []
        for f in zones.getFeatures():
            feats.append(f)
            categories.append(f.attributes()[cat_idx] or "")
            try:
                sizes.append(float(f.attributes()[size_idx] or 0.0))
            except (TypeError, ValueError):
                sizes.append(0.0)

        demand = parking.parking_demand(
            categories, np.array(sizes, dtype=np.float64), rates)

        out_fields = self.make_fields(("parking_demand", DOUBLE),
                                      base=zones.fields())
        sink, dest = self.parameterAsSink(
            parameters, self.OUTPUT, context, out_fields,
            zones.wkbType(), zones.sourceCrs())

        n_base = len(zones.fields())
        for i, f in enumerate(feats):
            if feedback.isCanceled():
                break
            out_feat = QgsFeature(out_fields)
            out_feat.setGeometry(f.geometry())
            out_feat.setAttributes(
                list(f.attributes())[:n_base] + [round(float(demand[i]), 2)])
            sink.addFeature(out_feat, QgsFeatureSink.Flag.FastInsert)

        subtotals = parking.category_subtotals(categories, demand)
        for category, spaces in subtotals:
            feedback.pushInfo(f"  {category}: {spaces:.2f} spaces")
        feedback.pushInfo(
            f"Parking demand: {float(demand.sum()):.2f} spaces over "
            f"{len(feats)} zone(s), {len(subtotals)} category/ies")
        unmatched = parking.unmatched_categories(categories, rates)
        if unmatched:
            feedback.pushInfo(
                "Matched no rate row, so demand 0 (a coverage gap in the "
                "rate table, not a real zero): " + ", ".join(unmatched))

        return {self.OUTPUT: dest}

    def createInstance(self):
        return ParkingDemandAlgorithm()
