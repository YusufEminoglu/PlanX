# -*- coding: utf-8 -*-
"""Demographic Equity Cross-Tabs: value distribution by population subgroup."""
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
    QgsProcessingParameterString,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_EQUITY, INT, PlanXAlgorithm, STRING
from ..engine import equity


class EquityCrosstabAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_EQUITY
    ICON = "tool_equitycrosstab.png"
    INPUT = "INPUT"
    VALUE_FIELD = "VALUE_FIELD"
    POP_FIELD = "POP_FIELD"
    GROUP_FIELD = "GROUP_FIELD"
    GROUP_FIELD_B = "GROUP_FIELD_B"
    N_CLASSES = "N_CLASSES"
    BREAKS = "BREAKS"
    OUT_CELLS = "OUT_CELLS"
    OUT_GROUPS = "OUT_GROUPS"
    OUT_UNITS = "OUT_UNITS"

    def name(self):
        return "equitycrosstab"

    def displayName(self):
        return self.tr("Demographic Equity Cross-Tabs")

    def shortHelpString(self):
        return self.tr(
            "Cross-tabulates any per-unit value (an access score, green space "
            "per capita, travel time...) by POPULATION SUBGROUP - who actually "
            "holds the low and the high values? The environmental-justice "
            "companion to the Accessibility Equity summary.\n\n"
            "The value axis is cut into population-weighted quantile classes "
            "(quintiles by default - each class holds the same population) or "
            "into your own fixed breaks. For every group x class cell the tool "
            "reports the REPRESENTATION RATIO: the group's share of that "
            "class's population divided by its share of the total population. "
            "1 means proportional, 2 means twice over-represented; over-"
            "representation in the lowest class flags a disadvantaged group.\n\n"
            "Per group it also reports population and value shares, weighted "
            "mean / P10 / median / P90, an internal Gini, and the Duncan & "
            "Duncan DISSIMILARITY INDEX of the group against the rest across "
            "the value classes (0 = same distribution, 1 = complete "
            "separation).\n\n"
            "Give a second group field to cross two demographics: the groups "
            "become each 'A | B' combination.\n\n"
            "Outputs:\n"
            "- Cross-tab cells: one row per group x class (population, share "
            "of the class, representation ratio);\n"
            "- Group summary: one row per group with the distribution "
            "statistics;\n"
            "- Units with class: the input annotated with its value class and "
            "its group's representation ratio in that class (map it to see "
            "where a group is over-represented among the worst-served).\n\n"
            "Population defaults to 1 per unit. The value is read as-is - "
            "class 1 always collects the LOWEST values."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT, self.tr("Units (origins / cells with a value)"),
            [QgsProcessing.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterField(
            self.VALUE_FIELD, self.tr("Value field"),
            parentLayerParameterName=self.INPUT,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterField(
            self.GROUP_FIELD, self.tr("Group field (demographic subgroup)"),
            parentLayerParameterName=self.INPUT))
        self.addParameter(QgsProcessingParameterField(
            self.GROUP_FIELD_B,
            self.tr("Second group field (optional, crosses the two)"),
            parentLayerParameterName=self.INPUT, optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.POP_FIELD, self.tr("Population field (empty = 1 per unit)"),
            parentLayerParameterName=self.INPUT, optional=True,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.N_CLASSES, self.tr("Value classes (weighted quantiles)"),
            QgsProcessingParameterNumber.Integer, 5, minValue=2, maxValue=10))
        self.addParameter(QgsProcessingParameterString(
            self.BREAKS,
            self.tr("Fixed class breaks instead (e.g. '50, 100, 150')"),
            "", optional=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_CELLS, self.tr("Cross-tab cells"),
            type=QgsProcessing.TypeVector))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_GROUPS, self.tr("Group summary"),
            type=QgsProcessing.TypeVector))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_UNITS, self.tr("Units with class"),
            type=QgsProcessing.TypeVector))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        value_field = self.parameterAsString(parameters, self.VALUE_FIELD, context)
        group_field = self.parameterAsString(parameters, self.GROUP_FIELD, context)
        group_field_b = self.parameterAsString(parameters, self.GROUP_FIELD_B, context)
        pop_field = self.parameterAsString(parameters, self.POP_FIELD, context)
        n_classes = self.parameterAsInt(parameters, self.N_CLASSES, context)
        breaks_text = self.parameterAsString(parameters, self.BREAKS, context)

        fields = source.fields()
        v_idx = fields.lookupField(value_field)
        g_idx = fields.lookupField(group_field)
        gb_idx = fields.lookupField(group_field_b) if group_field_b else -1
        p_idx = fields.lookupField(pop_field) if pop_field else -1

        breaks = None
        if breaks_text.strip():
            try:
                breaks = [float(t) for t in
                          breaks_text.replace(";", ",").split(",") if t.strip()]
            except ValueError:
                raise QgsProcessingException(
                    f"Could not read the class breaks: '{breaks_text}'. "
                    "Give comma-separated numbers, e.g. '50, 100, 150'.")
            if len(breaks) < 1:
                breaks = None

        feats, vals, pops, labels = [], [], [], []
        skipped = 0
        for f in source.getFeatures():
            if feedback.isCanceled():
                break
            attrs = f.attributes()
            try:
                v = float(attrs[v_idx])
            except (TypeError, ValueError):
                v = float("nan")
            if not math.isfinite(v):
                skipped += 1
                continue
            raw = attrs[g_idx]
            lab = str(raw).strip() if raw is not None else ""
            if not lab:
                skipped += 1
                continue
            if gb_idx >= 0:
                raw_b = attrs[gb_idx]
                lab_b = str(raw_b).strip() if raw_b is not None else ""
                if not lab_b:
                    skipped += 1
                    continue
                lab = f"{lab} | {lab_b}"
            p = 1.0
            if p_idx >= 0:
                try:
                    p = float(attrs[p_idx])
                except (TypeError, ValueError):
                    p = 0.0
                if not math.isfinite(p) or p < 0:
                    p = 0.0
            feats.append(f)
            vals.append(v)
            pops.append(p)
            labels.append(lab)
        if not feats:
            raise QgsProcessingException(
                "No features with a usable value and group were found.")
        if skipped:
            feedback.pushWarning(self.tr(
                f"{skipped} feature(s) skipped (missing value or group)."))

        vals = np.asarray(vals, dtype=float)
        pops = np.asarray(pops, dtype=float)
        if float(pops.sum()) <= 0:
            feedback.pushWarning(self.tr(
                "All population weights are zero - counting 1 per unit."))
            pops = np.ones_like(vals)
        group_names = sorted(set(labels))
        code_of = {name: i for i, name in enumerate(group_names)}
        codes = np.asarray([code_of[lab] for lab in labels], dtype=np.int64)

        xt = equity.crosstab(vals, codes, w=pops,
                             n_classes=n_classes, breaks=breaks)
        edges = xt["edges"]
        n_q = len(edges) + 1

        def class_label(k: int) -> str:
            if breaks is None:
                tag = " (lowest)" if k == 0 else (
                    " (highest)" if k == n_q - 1 else "")
                return f"Q{k + 1}{tag}"
            if k == 0:
                return f"< {edges[0]:g}"
            if k == n_q - 1:
                return f">= {edges[-1]:g}"
            return f"{edges[k - 1]:g} - {edges[k]:g}"

        # ------------------------------------------------------- cells out
        c_fields = self.make_fields(
            ("group", STRING), ("v_class", INT), ("class_label", STRING),
            ("pop", DOUBLE), ("class_share", DOUBLE), ("rep_ratio", DOUBLE))
        c_sink, c_dest = self.parameterAsSink(
            parameters, self.OUT_CELLS, context, c_fields,
            QgsWkbTypes.NoGeometry, QgsCoordinateReferenceSystem())
        col_pop = xt["cells"].sum(axis=0)
        for gi, gname in enumerate(group_names):
            for k in range(n_q):
                cell_pop = float(xt["cells"][gi, k])
                share = cell_pop / col_pop[k] if col_pop[k] > 0 else 0.0
                rr = xt["rep_ratio"][gi, k]
                feat = QgsFeature(c_fields)
                feat.setAttributes([
                    gname, int(k + 1), class_label(k), round(cell_pop, 3),
                    round(share, 4),
                    None if not np.isfinite(rr) else round(float(rr), 4)])
                c_sink.addFeature(feat, QgsFeatureSink.FastInsert)

        # ------------------------------------------------------ groups out
        g_fields = self.make_fields(
            ("group", STRING), ("pop", DOUBLE), ("pop_share", DOUBLE),
            ("val_share", DOUBLE), ("mean", DOUBLE), ("p10", DOUBLE),
            ("median", DOUBLE), ("p90", DOUBLE), ("gini", DOUBLE),
            ("dissim", DOUBLE))
        g_sink, g_dest = self.parameterAsSink(
            parameters, self.OUT_GROUPS, context, g_fields,
            QgsWkbTypes.NoGeometry, QgsCoordinateReferenceSystem())
        for gi, gname in enumerate(group_names):
            feat = QgsFeature(g_fields)
            feat.setAttributes([
                gname, round(float(xt["pop"][gi]), 3),
                round(float(xt["pop_share"][gi]), 4),
                round(float(xt["value_share"][gi]), 4),
                round(float(xt["mean"][gi]), 4),
                round(float(xt["p10"][gi]), 4),
                round(float(xt["median"][gi]), 4),
                round(float(xt["p90"][gi]), 4),
                round(float(xt["gini"][gi]), 4),
                round(float(xt["dissimilarity"][gi]), 4)])
            g_sink.addFeature(feat, QgsFeatureSink.FastInsert)

        # ------------------------------------------------------- units out
        u_fields = self.make_fields(
            ("v_class", INT), ("class_label", STRING), ("cell_rep", DOUBLE),
            base=fields)
        u_sink, u_dest = self.parameterAsSink(
            parameters, self.OUT_UNITS, context, u_fields,
            source.wkbType(), source.sourceCrs())
        n_base = len(fields)
        for i, f in enumerate(feats):
            if feedback.isCanceled():
                break
            k = int(xt["class_of"][i])
            rr = xt["rep_ratio"][codes[i], k]
            out = QgsFeature(u_fields)
            out.setGeometry(f.geometry())
            out.setAttributes(list(f.attributes())[:n_base] + [
                int(k + 1), class_label(k),
                None if not np.isfinite(rr) else round(float(rr), 4)])
            u_sink.addFeature(out, QgsFeatureSink.FastInsert)

        # -------------------------------------------------------- headline
        feedback.pushInfo(self.tr(
            f"{len(feats)} units in {len(group_names)} group(s) across "
            f"{n_q} value classes (population {pops.sum():g})."))
        low = [(xt["rep_ratio"][gi, 0], gname)
               for gi, gname in enumerate(group_names)
               if np.isfinite(xt["rep_ratio"][gi, 0])]
        if low:
            worst = max(low)
            best = min(low)
            feedback.pushInfo(self.tr(
                f"Most over-represented in the lowest class "
                f"'{class_label(0)}': {worst[1]} (ratio {worst[0]:.2f}); "
                f"least: {best[1]} (ratio {best[0]:.2f})."))
        d_top = int(np.argmax(xt["dissimilarity"]))
        feedback.pushInfo(self.tr(
            f"Highest dissimilarity vs the rest: {group_names[d_top]} "
            f"({xt['dissimilarity'][d_top]:.3f})."))
        return {self.OUT_CELLS: c_dest, self.OUT_GROUPS: g_dest,
                self.OUT_UNITS: u_dest}

    def createInstance(self):
        return EquityCrosstabAlgorithm()
