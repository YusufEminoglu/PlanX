# -*- coding: utf-8 -*-
"""Inequality Curves: Lorenz / concentration curve + Atkinson index."""
from __future__ import annotations

import math

import numpy as np

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsFeatureSink,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_EQUITY, INT, PlanXAlgorithm, STRING
from ..engine import equity


class InequalityCurvesAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_EQUITY
    ICON = "tool_inequalitycurves.png"
    INPUT = "INPUT"
    VALUE_FIELD = "VALUE_FIELD"
    POP_FIELD = "POP_FIELD"
    RANK_FIELD = "RANK_FIELD"
    EPSILON = "EPSILON"
    OUT_CURVE = "OUT_CURVE"
    OUT_SUMMARY = "OUT_SUMMARY"

    def name(self):
        return "inequalitycurves"

    def displayName(self):
        return self.tr("Inequality Curves (Lorenz & Atkinson)")

    def shortHelpString(self):
        return self.tr(
            "Draws the LORENZ CURVE of a value across the population and the "
            "ATKINSON inequality index - the distributional view, with an "
            "exportable curve you can chart and a measure that lets you set "
            "how much you care about the worst-off.\n\n"
            "Feed it any per-unit value treated as a non-negative good "
            "(an access score, green space per capita, income...) and an "
            "optional population field. It returns:\n"
            "- the Lorenz curve as a table - cumulative population share "
            "against cumulative value share - which bows below the 45-degree "
            "line of equality the more unequal the distribution is;\n"
            "- the Gini coefficient (twice the area between the curve and the "
            "line of equality);\n"
            "- the Atkinson index at low/medium/high inequality aversion "
            "(epsilon 0.5, 1, 2) and at your own epsilon. Higher epsilon "
            "weights the lower tail more, so the index says how much total "
            "value society would trade to equalise the distribution.\n\n"
            "Give a RANK field (e.g. a deprivation or income rank) to get a "
            "CONCENTRATION curve and index instead: the value is accumulated "
            "in that external order, revealing whether it concentrates on the "
            "advantaged or disadvantaged end (the index is negative when the "
            "value falls as rank rises).\n\n"
            "Outputs:\n"
            "- Curve: one row per cumulative point (population share, value "
            "share, the line of equality, and the gap between them);\n"
            "- Summary: a metric/value table (units, population, mean, Gini, "
            "Atkinson at each epsilon, concentration index if a rank is "
            "given).\n\n"
            "Population defaults to 1 per unit. For a 'bad' such as travel "
            "time, transform it to a good first (e.g. its inverse)."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT, self.tr("Units (origins / cells with a value)"),
            [QgsProcessing.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterField(
            self.VALUE_FIELD, self.tr("Value field (a non-negative good)"),
            parentLayerParameterName=self.INPUT,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterField(
            self.POP_FIELD, self.tr("Population field (empty = 1 per unit)"),
            parentLayerParameterName=self.INPUT, optional=True,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterField(
            self.RANK_FIELD,
            self.tr("Rank field for a concentration curve (optional)"),
            parentLayerParameterName=self.INPUT, optional=True,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.EPSILON, self.tr("Atkinson inequality-aversion (epsilon)"),
            QgsProcessingParameterNumber.Double, 1.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_CURVE, self.tr("Lorenz / concentration curve"),
            type=QgsProcessing.TypeVector))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_SUMMARY, self.tr("Inequality summary"),
            type=QgsProcessing.TypeVector))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        value_field = self.parameterAsString(parameters, self.VALUE_FIELD, context)
        pop_field = self.parameterAsString(parameters, self.POP_FIELD, context)
        rank_field = self.parameterAsString(parameters, self.RANK_FIELD, context)
        epsilon = self.parameterAsDouble(parameters, self.EPSILON, context)

        v_idx = source.fields().lookupField(value_field)
        p_idx = source.fields().lookupField(pop_field) if pop_field else -1
        r_idx = source.fields().lookupField(rank_field) if rank_field else -1

        def num_of(feat, idx, default):
            if idx < 0:
                return default
            try:
                return float(feat.attributes()[idx])
            except (TypeError, ValueError):
                return None

        vals, pops, ranks = [], [], []
        skipped = 0
        for f in source.getFeatures():
            if feedback.isCanceled():
                break
            v = num_of(f, v_idx, None)
            if v is None or not math.isfinite(v):
                skipped += 1
                continue
            if r_idx >= 0:
                r = num_of(f, r_idx, None)
                if r is None or not math.isfinite(r):
                    skipped += 1
                    continue
                ranks.append(r)
            p = num_of(f, p_idx, 1.0)
            if p is None or not math.isfinite(p) or p < 0:
                p = 0.0
            vals.append(v)
            pops.append(p)
        if not vals:
            raise QgsProcessingException(
                "No features with a usable numeric value were found.")
        if skipped:
            feedback.pushWarning(self.tr(
                f"{skipped} feature(s) skipped (missing/invalid value or rank)."))

        vals = np.asarray(vals, dtype=float)
        pops = np.asarray(pops, dtype=float)
        if float(pops.sum()) <= 0:
            pops = np.ones_like(vals)
        if float(vals.min()) < 0:
            feedback.pushWarning(self.tr(
                "Negative values present - they are clipped to zero (the "
                "indices treat the value as a non-negative good)."))
        rank_arr = np.asarray(ranks, dtype=float) if r_idx >= 0 else None
        is_concentration = rank_arr is not None

        pop_share, val_share = equity.lorenz_points(vals, pops, rank=rank_arr)
        index_val = equity.gini_from_lorenz(pop_share, val_share)
        mean_all = equity.weighted_mean(vals, pops)

        # ---------------------------------------------------------- curve out
        c_fields = self.make_fields(
            ("point", INT), ("pop_share", DOUBLE), ("value_share", DOUBLE),
            ("equality", DOUBLE), ("gap", DOUBLE))
        c_sink, c_dest = self.parameterAsSink(
            parameters, self.OUT_CURVE, context, c_fields,
            QgsWkbTypes.NoGeometry, QgsCoordinateReferenceSystem())
        for k in range(len(pop_share)):
            ps, vs = float(pop_share[k]), float(val_share[k])
            feat = QgsFeature(c_fields)
            feat.setAttributes([int(k), round(ps, 6), round(vs, 6),
                                round(ps, 6), round(ps - vs, 6)])
            c_sink.addFeature(feat, QgsFeatureSink.FastInsert)

        # -------------------------------------------------------- summary out
        s_fields = self.make_fields(("metric", STRING), ("value", DOUBLE))
        s_sink, s_dest = self.parameterAsSink(
            parameters, self.OUT_SUMMARY, context, s_fields,
            QgsWkbTypes.NoGeometry, QgsCoordinateReferenceSystem())

        def srow(metric, value):
            f = QgsFeature(s_fields)
            f.setAttributes([metric, round(float(value), 6)])
            s_sink.addFeature(f, QgsFeatureSink.FastInsert)

        gini_val = equity.gini(vals, pops)
        srow("Units (n)", float(len(vals)))
        srow("Population", float(pops.sum()))
        srow("Mean value", mean_all)
        srow("Gini", gini_val)
        eps_list = [0.5, 1.0, 2.0]
        if not any(abs(epsilon - e) < 1e-9 for e in eps_list):
            eps_list.append(float(epsilon))
        for e in eps_list:
            srow(f"Atkinson (epsilon={e:g})", equity.atkinson_index(vals, pops, e))
        if is_concentration:
            srow("Concentration index", index_val)

        # ------------------------------------------------------------- report
        kind = "Concentration" if is_concentration else "Lorenz"
        feedback.pushInfo(self.tr(
            f"{kind} curve over {len(vals)} units, population {pops.sum():g}, "
            f"mean value {mean_all:g}."))
        feedback.pushInfo(self.tr(
            f"Gini {gini_val:.4f}  |  Atkinson(0.5) "
            f"{equity.atkinson_index(vals, pops, 0.5):.4f}  |  Atkinson(1) "
            f"{equity.atkinson_index(vals, pops, 1.0):.4f}  |  Atkinson(2) "
            f"{equity.atkinson_index(vals, pops, 2.0):.4f}"))
        if is_concentration:
            where = "advantaged (high-rank)" if index_val >= 0 else "disadvantaged (low-rank)"
            feedback.pushInfo(self.tr(
                f"Concentration index {index_val:+.4f}: the value leans toward "
                f"the {where} end of the ranking."))
        return {self.OUT_CURVE: c_dest, self.OUT_SUMMARY: s_dest}

    def createInstance(self):
        return InequalityCurvesAlgorithm()
