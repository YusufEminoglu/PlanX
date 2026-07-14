# -*- coding: utf-8 -*-
"""Accessibility Equity: how (un)equally access is distributed."""
from __future__ import annotations

import math

import numpy as np

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsFeatureSink,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_EQUITY, INT, PlanXAlgorithm, STRING
from ..engine import equity


class AccessEquityAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_EQUITY
    ICON = "tool_accessequity.png"
    INPUT = "INPUT"
    VALUE_FIELD = "VALUE_FIELD"
    POP_FIELD = "POP_FIELD"
    GROUP_FIELD = "GROUP_FIELD"
    DIRECTION = "DIRECTION"
    POVERTY = "POVERTY"
    OUT_POINTS = "OUT_POINTS"
    OUT_SUMMARY = "OUT_SUMMARY"

    DIRECTIONS = ["Higher is better (e.g. access score)",
                  "Lower is better (e.g. travel time / distance)"]

    def name(self):
        return "accessequity"

    def displayName(self):
        return self.tr("Accessibility Equity (Gini / Theil)")

    def shortHelpString(self):
        return self.tr(
            "Measures how FAIRLY a value is distributed across the "
            "population - the spatial-equity / environmental-justice view "
            "that the level-of-access tools do not give you. Feed it any "
            "per-unit value: an Access Score, a travel time, a distance to "
            "the nearest facility...\n\n"
            "Headline indices (population-weighted):\n"
            "- Gini coefficient (0 = everyone equal, ->1 = maximal "
            "inequality);\n"
            "- Theil's T index, additively split into BETWEEN-group and "
            "WITHIN-group inequality when you give a group field (district, "
            "income class, tenure...) - the share of inequality that is "
            "between groups is the environmental-justice number;\n"
            "- P90/P10 ratio, coefficient of variation, and the "
            "access-poverty share (population beyond your threshold).\n\n"
            "Outputs:\n"
            "- Units: the input features plus their weighted percentile "
            "rank, deviation from the mean and an access-poverty flag;\n"
            "- Summary table: one row for the whole study area and one per "
            "group, with all the indices.\n\n"
            "Population defaults to 1 per unit when no field is given. "
            "Inequality indices treat the value as a non-negative good; "
            "negatives are clipped to zero.\n\n"
            "How to read the results\n"
            "- Rules of thumb for access Gini: < 0.2 = evenly provided; "
            "0.2-0.35 = normal urban unevenness; > 0.4 = strongly "
            "concentrated - a few places enjoy most of the access. "
            "Always read it WITH the mean: perfect equality at a "
            "miserable level is not a goal.\n"
            "- The Theil between-share is the justice headline: if 60 "
            "percent of inequality is BETWEEN districts (or income "
            "groups), place-based investment fixes it; if most is "
            "WITHIN, the problem is fine-grained and district-level "
            "policy will miss it.\n"
            "- P90/P10 is the plain-language version ('the best-served "
            "tenth enjoys 4x the access of the worst-served tenth'); "
            "the poverty share names how many people fall below your "
            "chosen line.\n"
            "- On the units layer, pct_rank < 10 marks the structurally "
            "underserved - map them, they cluster.\n\n"
            "Using the results: put the Gini/Theil row of each scenario "
            "next to its mean access - projects that raise the mean by "
            "serving already-good areas WORSEN these indices; use the "
            "between-share to justify targeting; track the poverty "
            "share as the plan's equity KPI over time."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT, self.tr("Units (origins / cells with a value)"),
            [QgsProcessing.SourceType.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterField(
            self.VALUE_FIELD, self.tr("Value field (access score, time, distance...)"),
            parentLayerParameterName=self.INPUT,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterField(
            self.POP_FIELD, self.tr("Population field (empty = 1 per unit)"),
            parentLayerParameterName=self.INPUT, optional=True,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterField(
            self.GROUP_FIELD,
            self.tr("Group field for between/within decomposition (optional)"),
            parentLayerParameterName=self.INPUT, optional=True))
        self.addParameter(QgsProcessingParameterEnum(
            self.DIRECTION, self.tr("Value meaning"), self.DIRECTIONS,
            defaultValue=0))
        self.addParameter(QgsProcessingParameterNumber(
            self.POVERTY,
            self.tr("Access-poverty threshold (optional)"),
            QgsProcessingParameterNumber.Type.Double, optional=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_POINTS, self.tr("Units (with equity attributes)")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_SUMMARY, self.tr("Equity summary table"),
            type=QgsProcessing.SourceType.TypeVector))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        value_field = self.parameterAsString(parameters, self.VALUE_FIELD, context)
        pop_field = self.parameterAsString(parameters, self.POP_FIELD, context)
        group_field = self.parameterAsString(parameters, self.GROUP_FIELD, context)
        direction = self.parameterAsEnum(parameters, self.DIRECTION, context)
        higher_better = direction == 0
        pov_set = parameters.get(self.POVERTY) is not None
        pov_thr = self.parameterAsDouble(parameters, self.POVERTY, context)

        v_idx = source.fields().lookupField(value_field)
        p_idx = source.fields().lookupField(pop_field) if pop_field else -1
        g_idx = source.fields().lookupField(group_field) if group_field else -1

        def num_of(feat, idx, default):
            if idx < 0:
                return default
            try:
                return float(feat.attributes()[idx])
            except (TypeError, ValueError):
                return None

        feats, vals, pops, grps = [], [], [], []
        skipped = 0
        for f in source.getFeatures():
            if feedback.isCanceled():
                break
            v = num_of(f, v_idx, None)
            if v is None or not math.isfinite(v):
                skipped += 1
                continue
            p = num_of(f, p_idx, 1.0)
            if p is None or not math.isfinite(p) or p < 0:
                p = 0.0
            feats.append(f)
            vals.append(v)
            pops.append(p)
            grps.append(str(f.attributes()[g_idx]) if g_idx >= 0 else "")
        if not vals:
            raise QgsProcessingException(
                "No features with a usable numeric value were found.")
        if skipped:
            feedback.pushWarning(self.tr(
                f"{skipped} feature(s) skipped (missing/invalid value)."))

        vals = np.asarray(vals, dtype=float)
        pops = np.asarray(pops, dtype=float)
        if float(pops.sum()) <= 0:
            pops = np.ones_like(vals)
        if float(vals.min()) < 0:
            feedback.pushWarning(self.tr(
                "Negative values present - inequality indices (Gini, Theil) "
                "clip them to zero."))

        ranks = equity.percentile_rank(vals, pops) * 100.0
        mean_all = equity.weighted_mean(vals, pops)

        def poverty_flag(v):
            if not pov_set:
                return 0
            poor = v < pov_thr if higher_better else v > pov_thr
            return 1 if poor else 0

        # --------------------------------------------------------- units out
        p_fields = self.make_fields(
            ("eq_value", DOUBLE), ("pct_rank", DOUBLE), ("dev_mean", DOUBLE),
            ("poverty", INT), base=source.fields())
        p_sink, p_dest = self.parameterAsSink(
            parameters, self.OUT_POINTS, context, p_fields,
            source.wkbType(), source.sourceCrs())
        n_base = len(source.fields())
        for i, feat in enumerate(feats):
            out = QgsFeature(p_fields)
            out.setGeometry(feat.geometry())
            out.setAttributes(
                list(feat.attributes())[:n_base]
                + [round(float(vals[i]), 4), round(float(ranks[i]), 2),
                   round(float(vals[i] - mean_all), 4), poverty_flag(vals[i])])
            p_sink.addFeature(out, QgsFeatureSink.Flag.FastInsert)

        # ------------------------------------------------------- summary out
        s_fields = self.make_fields(
            ("scope", STRING), ("population", DOUBLE), ("mean", DOUBLE),
            ("median", DOUBLE), ("gini", DOUBLE), ("theil", DOUBLE),
            ("theil_btw", DOUBLE), ("theil_wth", DOUBLE), ("cv", DOUBLE),
            ("p90_p10", DOUBLE), ("pov_share", DOUBLE))
        s_sink, s_dest = self.parameterAsSink(
            parameters, self.OUT_SUMMARY, context, s_fields,
            QgsWkbTypes.Type.NoGeometry, QgsCoordinateReferenceSystem())

        def pov_share(xv, wv):
            if not pov_set:
                return 0.0
            if higher_better:
                return equity.share_below(xv, pov_thr, wv)
            return equity.share_above(xv, pov_thr, wv)

        def row(scope, xv, wv, theil, btw, wth):
            f = QgsFeature(s_fields)
            f.setAttributes([
                scope, round(float(np.asarray(wv).sum()), 1),
                round(equity.weighted_mean(xv, wv), 3),
                round(equity.weighted_quantile(xv, 0.5, wv), 3),
                round(equity.gini(xv, wv), 4), round(theil, 4),
                round(btw, 4), round(wth, 4),
                round(equity.coefficient_of_variation(xv, wv), 4),
                round(equity.percentile_ratio(xv, wv), 3),
                round(pov_share(xv, wv), 4)])
            return f

        if g_idx >= 0:
            groups = np.asarray(grps)
            t_tot, t_btw, t_wth, per_group = equity.theil_decomposition(
                vals, pops, groups)
        else:
            groups = None
            t_tot, t_btw, t_wth, per_group = equity.theil_t(vals, pops), 0.0, 0.0, {}

        s_sink.addFeature(row("ALL", vals, pops, t_tot, t_btw, t_wth),
                          QgsFeatureSink.Flag.FastInsert)
        if groups is not None:
            for lab in sorted(per_group, key=str):
                m = groups == lab
                s_sink.addFeature(
                    row(str(lab), vals[m], pops[m], per_group[lab]["theil"],
                        0.0, 0.0),
                    QgsFeatureSink.Flag.FastInsert)

        # ------------------------------------------------------------- report
        feedback.pushInfo(self.tr(
            f"Population {pops.sum():g} over {len(vals)} units. "
            f"Mean value {mean_all:g}."))
        feedback.pushInfo(self.tr(
            f"Gini {equity.gini(vals, pops):.3f}  |  Theil T {t_tot:.3f}  |  "
            f"P90/P10 {equity.percentile_ratio(vals, pops):.2f}  |  "
            f"CV {equity.coefficient_of_variation(vals, pops):.3f}"))
        if g_idx >= 0 and t_tot > 0:
            feedback.pushInfo(self.tr(
                f"Theil split: {t_btw:.3f} between groups "
                f"({100.0 * t_btw / t_tot:.0f} percent of total) + "
                f"{t_wth:.3f} within groups."))
        if pov_set:
            feedback.pushInfo(self.tr(
                f"Access poverty (value {'below' if higher_better else 'above'} "
                f"{pov_thr:g}): {100.0 * pov_share(vals, pops):.1f} percent of "
                "the population."))

        return {self.OUT_POINTS: p_dest, self.OUT_SUMMARY: s_dest}

    def createInstance(self):
        return AccessEquityAlgorithm()
