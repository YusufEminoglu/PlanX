# -*- coding: utf-8 -*-
"""Trip Generation algorithm wrapper."""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsFeature,
    QgsFeatureSink,
    QgsProcessing,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_DEMAND, PlanXAlgorithm
from ..engine import demand


class TripGenerationAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_DEMAND
    ICON = "tool_tripgeneration.png"
    ZONES = "ZONES"
    POP_FIELD = "POP_FIELD"
    JOBS_FIELD = "JOBS_FIELD"
    P_RATE = "P_RATE"
    A_RATE = "A_RATE"
    OUTPUT = "OUTPUT"

    def name(self):
        return "tripgeneration"

    def displayName(self):
        return self.tr("Trip Generation")

    def shortHelpString(self):
        return self.tr(
            "Screening-quality trip generation model.\n\n"
            "Calculates trip productions (P) and attractions (A) for each zone "
            "based on zone population, employment, and production/attraction rates.\n\n"
            "Outputs a summary table containing original attributes and the computed productions "
            "and attractions.\n\n"
            "How to read the results\n"
            "- productions = trips a zone's residents send out; "
            "attractions = trips its jobs pull in. The P/A balance per "
            "zone is the land-use diagnosis: P >> A = dormitory "
            "district (out-commuting), A >> P = employment core "
            "(in-commuting) - both mean traffic across the boundary "
            "between them.\n"
            "- Totals are linear in the rates you typed: the MAP "
            "(which zones dominate) is robust, the absolute trip "
            "numbers are only as good as the rates - calibrate them "
            "against a survey or count before quoting totals.\n"
            "- ZoneP and A totals need not match; the gravity step "
            "rescales attractions - large imbalance is a signal about "
            "your study-area boundary (jobs or homes outside it).\n\n"
            "Using the results: this is step 1 of the classic "
            "four-step chain - feed the table into Gravity "
            "Distribution; test a land-use scenario (new housing area, "
            "relocated jobs) by editing pop/jobs and re-chaining; the "
            "P/A imbalance map alone is often enough to argue for "
            "mixed-use rebalancing."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.ZONES, self.tr("Zone layer"), [QgsProcessing.TypeVectorPolygon, QgsProcessing.TypeVectorPoint]))
        self.addParameter(QgsProcessingParameterField(
            self.POP_FIELD, self.tr("Population field"), parentLayerParameterName=self.ZONES,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterField(
            self.JOBS_FIELD, self.tr("Jobs field"), parentLayerParameterName=self.ZONES,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.P_RATE, self.tr("Production rate (trips per capita)"),
            QgsProcessingParameterNumber.Double, defaultValue=1.5, minValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.A_RATE, self.tr("Attraction rate (trips per job)"),
            QgsProcessingParameterNumber.Double, defaultValue=2.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Trip generation table")))

    def processAlgorithm(self, parameters, context, feedback):
        zones = self.parameterAsSource(parameters, self.ZONES, context)
        pop_field = self.parameterAsString(parameters, self.POP_FIELD, context)
        jobs_field = self.parameterAsString(parameters, self.JOBS_FIELD, context)
        p_rate = self.parameterAsDouble(parameters, self.P_RATE, context)
        a_rate = self.parameterAsDouble(parameters, self.A_RATE, context)

        pop_idx = zones.fields().lookupField(pop_field)
        jobs_idx = zones.fields().lookupField(jobs_field)

        out_fields = self.make_fields(
            ("production", DOUBLE),
            ("attraction", DOUBLE),
            base=zones.fields()
        )

        sink, dest = self.parameterAsSink(
            parameters, self.OUTPUT, context, out_fields,
            QgsWkbTypes.NoGeometry)

        pop_vals = []
        jobs_vals = []
        feats = []
        for f in zones.getFeatures():
            feats.append(f)
            try:
                p = float(f.attributes()[pop_idx] or 0.0)
            except (TypeError, ValueError):
                p = 0.0
            try:
                j = float(f.attributes()[jobs_idx] or 0.0)
            except (TypeError, ValueError):
                j = 0.0
            pop_vals.append(p)
            jobs_vals.append(j)

        P, A = demand.trip_generation(
            np.array(pop_vals, dtype=np.float64),
            np.array(jobs_vals, dtype=np.float64),
            p_rate, a_rate
        )

        n_base = len(zones.fields())
        for i, f in enumerate(feats):
            if feedback.isCanceled():
                break
            out_feat = QgsFeature(out_fields)
            out_feat.setAttributes(list(f.attributes())[:n_base] + [round(P[i], 2), round(A[i], 2)])
            sink.addFeature(out_feat, QgsFeatureSink.FastInsert)

        return {self.OUTPUT: dest}

    def createInstance(self):
        return TripGenerationAlgorithm()
