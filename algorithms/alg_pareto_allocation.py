# -*- coding: utf-8 -*-
"""Land-Use Pareto Front: the suitability vs compactness trade-off."""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsFeatureSink,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterDefinition,
    QgsProcessingParameterEnum,
    QgsProcessingParameterField,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsSpatialIndex,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_OPTIMIZE, INT, PlanXAlgorithm, STRING
from ..engine import allocate

# How far past the suitability/compactness break-even weight to sweep when the
# upper weight is left on auto (so compactness can clearly dominate the top).
_AUTO_SPAN = 6.0


class ParetoAllocationAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_OPTIMIZE
    ICON = "tool_paretoallocation.png"
    PARCELS = "PARCELS"
    SUIT_FIELDS = "SUIT_FIELDS"
    TARGETS = "TARGETS"
    AREA_FIELD = "AREA_FIELD"
    LOCK_FIELD = "LOCK_FIELD"
    N_POINTS = "N_POINTS"
    W_MAX = "W_MAX"
    SOLUTION = "SOLUTION"
    W_SUITABILITY = "W_SUITABILITY"
    OUT_FRONT = "OUT_FRONT"
    OUT_PARCELS = "OUT_PARCELS"

    _SOLUTIONS = ("Knee (best trade-off)", "Maximum suitability",
                  "Maximum compactness")

    def name(self):
        return "paretoallocation"

    def displayName(self):
        return self.tr("Land-Use Pareto Front")

    def shortHelpString(self):
        return self.tr(
            "Maps the TRADE-OFF between suitability and compactness in "
            "land-use allocation, instead of committing to a single weighted "
            "run. There is rarely one best plan: pushing parcels of a use to "
            "cluster into compact zones (good form) usually costs some "
            "per-parcel suitability, and vice versa. This tool traces that "
            "frontier so you can choose the balance with eyes open.\n\n"
            "It solves the Land-Use Allocation Optimizer several times across "
            "a range of compactness weights (from 0 = pure suitability up to "
            "a strongly compact run) and records two scores for each result, "
            "both higher-is-better:\n"
            "- Suitability: the area-weighted suitability achieved;\n"
            "- Compactness: the total shared boundary between adjacent "
            "same-use parcels.\n\n"
            "The results that are not beaten on BOTH scores by another result "
            "form the Pareto front (the non-dominated set). The knee of that "
            "front - the point furthest from the line joining its extremes - "
            "is the best-balanced compromise.\n\n"
            "Inputs match the Land-Use Allocation Optimizer: one suitability "
            "field per land use and a target area per use "
            "('s_residential=50000, s_green=30000', map units; names match "
            "the field names, exact else by containment), an optional area "
            "field and an optional lock field for already-zoned parcels.\n\n"
            "Outputs:\n"
            "- Front (table): one row per weight sampled - the weight, the "
            "two scores (raw and 0-1 normalised), whether it lies on the "
            "front and whether it is the knee. Plot suitability against "
            "compactness to see the curve.\n"
            "- Parcels: the allocation of ONE chosen solution (the knee by "
            "default; or the maximum-suitability or maximum-compactness end) "
            "as a land-use map - style by 'alloc_use'.\n\n"
            "Method: a fast allocation heuristic run once per weight; the "
            "weight range auto-scales to the data unless you set an upper "
            "weight. More points or more parcels means more runs - use a "
            "projected CRS."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.PARCELS, self.tr("Parcels / cells"),
            [QgsProcessing.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterField(
            self.SUIT_FIELDS, self.tr("Suitability fields (one per land use)"),
            parentLayerParameterName=self.PARCELS, allowMultiple=True,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterString(
            self.TARGETS, self.tr("Target area per use (name=area, ...)"),
            self.tr("s_residential=50000, s_commercial=20000, s_green=30000")))
        self.addParameter(QgsProcessingParameterField(
            self.AREA_FIELD, self.tr("Area field (optional; default = geometry area)"),
            parentLayerParameterName=self.PARCELS, optional=True,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterField(
            self.LOCK_FIELD, self.tr("Lock field (optional; pre-assigned use name)"),
            parentLayerParameterName=self.PARCELS, optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.N_POINTS, self.tr("Number of weights to sample along the front"),
            QgsProcessingParameterNumber.Integer, 9, minValue=2, maxValue=25))
        self.addParameter(QgsProcessingParameterNumber(
            self.W_MAX,
            self.tr("Maximum compactness weight (0 = auto-scale to the data)"),
            QgsProcessingParameterNumber.Double, 0.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterEnum(
            self.SOLUTION, self.tr("Solution to export as the parcel map"),
            options=[self.tr(s) for s in self._SOLUTIONS], defaultValue=0))
        w_suit = QgsProcessingParameterNumber(
            self.W_SUITABILITY,
            self.tr("Suitability weight (relative to compactness)"),
            QgsProcessingParameterNumber.Double, 1.0, minValue=0.0)
        w_suit.setFlags(w_suit.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(w_suit)
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_FRONT, self.tr("Pareto front"),
            type=QgsProcessing.TypeVector))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_PARCELS, self.tr("Allocated parcels (selected solution)")))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.PARCELS, context)
        suit_fields = self.parameterAsFields(parameters, self.SUIT_FIELDS, context)
        area_field = self.parameterAsString(parameters, self.AREA_FIELD, context)
        lock_field = self.parameterAsString(parameters, self.LOCK_FIELD, context)
        n_points = self.parameterAsInt(parameters, self.N_POINTS, context)
        w_max = self.parameterAsDouble(parameters, self.W_MAX, context)
        solution = self.parameterAsEnum(parameters, self.SOLUTION, context)
        w_suit = self.parameterAsDouble(parameters, self.W_SUITABILITY, context)
        self.require_projected(source, "Parcels")
        if not suit_fields:
            raise QgsProcessingException("Select at least one suitability field.")
        try:
            parsed = allocate.parse_targets(
                self.parameterAsString(parameters, self.TARGETS, context))
        except ValueError as exc:
            raise QgsProcessingException(str(exc))

        use_names = list(suit_fields)
        name_to_use = {fn.lower(): i for i, fn in enumerate(use_names)}
        targets = []
        used_keys = set()
        for fn in use_names:
            low = fn.lower()
            target = 0.0
            for key, val in parsed:
                if key == low or key in low:
                    target = val
                    used_keys.add(key)
                    break
            targets.append(target)
        for key, _ in parsed:
            if key not in used_keys:
                feedback.pushWarning(self.tr(
                    f"Target '{key}' matches no suitability field - ignored."))
        if not any(t > 0 for t in targets):
            raise QgsProcessingException(
                "No target matched a suitability field (check the names).")

        # ---- read parcels (geometry, per-use suitability, area, lock) ----
        fields = source.fields()
        suit_idx = [fields.lookupField(fn) for fn in use_names]
        area_idx = fields.lookupField(area_field) if area_field else -1
        lock_idx = fields.lookupField(lock_field) if lock_field else -1

        feats, geoms, suit_rows, areas, locked = [], [], [], [], []
        bad_locks = 0
        for f in source.getFeatures():
            if feedback.isCanceled():
                break
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
            attrs = f.attributes()
            row = []
            for idx in suit_idx:
                try:
                    row.append(float(attrs[idx]))
                except (TypeError, ValueError):
                    row.append(0.0)
            ar = None
            if area_idx >= 0:
                try:
                    ar = float(attrs[area_idx])
                except (TypeError, ValueError):
                    ar = None
            if ar is None or ar < 0:
                ar = g.area()
            lk = -1
            if lock_idx >= 0:
                raw = attrs[lock_idx]
                if raw is not None and str(raw).strip():
                    key = str(raw).strip().lower()
                    if key in name_to_use:
                        lk = name_to_use[key]
                    else:
                        bad_locks += 1
            feats.append(f)
            geoms.append(g)
            suit_rows.append(row)
            areas.append(ar)
            locked.append(lk)
        if not feats:
            raise QgsProcessingException("No parcels with geometry found.")
        if bad_locks:
            feedback.pushWarning(self.tr(
                f"{bad_locks} lock value(s) did not match any suitability "
                "field name - those parcels were left free."))

        suit = np.asarray(suit_rows, dtype=float)
        area = np.asarray(areas, dtype=float)
        tvec = np.asarray(targets, dtype=float)
        lvec = np.asarray(locked, dtype=np.int64)
        n_use = len(use_names)

        # ---- parcel adjacency graph (shared boundary lengths) ----
        index = QgsSpatialIndex()
        for i in range(len(feats)):
            qf = QgsFeature(i)
            qf.setGeometry(geoms[i])
            index.insertFeature(qf)
        edges = []
        for i in range(len(feats)):
            if feedback.isCanceled():
                break
            gi = geoms[i]
            for j in index.intersects(gi.boundingBox()):
                if j <= i:
                    continue
                inter = gi.intersection(geoms[j])
                if inter is None or inter.isEmpty():
                    continue
                length = inter.length()
                if length > 1e-6:
                    edges.append((i, j, length))
        l_total = sum(length for _, _, length in edges)
        feedback.pushInfo(self.tr(
            f"Adjacency graph: {len(edges)} shared parcel boundaries "
            f"(total length {l_total:g})."))
        if l_total <= 0:
            feedback.pushWarning(self.tr(
                "Parcels share no boundaries - compactness is always zero, so "
                "the front collapses to a single point. Check the geometry."))

        # ---- weight sweep: auto-scale unless an upper weight is given ----
        suit0 = allocate.allocate_land_use(suit, area, tvec, locked=lvec)["suit_score"]
        if w_max > 0:
            w_hi = float(w_max)
        elif l_total > 0:
            w_hi = _AUTO_SPAN * suit0 / l_total
        else:
            w_hi = 1.0
        weights = np.linspace(0.0, w_hi, int(n_points))
        feedback.pushInfo(self.tr(
            f"Sweeping {n_points} compactness weights from 0 to {w_hi:g} "
            f"over {len(feats)} parcels and {n_use} use(s)..."))

        res = allocate.pareto_front(suit, area, tvec, edges, weights,
                                    locked=lvec, w_suit=w_suit)
        suit_vals = res["suit"]
        comp_vals = res["compact"]
        on_front = res["on_front"]
        knee = int(res["knee"])

        # ---- choose which solution to export as the parcel map ----
        if solution == 1:                       # maximum suitability
            sel = int(np.argmax(suit_vals))
            sel_label = "maximum suitability"
        elif solution == 2:                     # maximum compactness
            sel = int(np.argmax(comp_vals))
            sel_label = "maximum compactness"
        else:                                   # knee / best trade-off
            if knee >= 0:
                sel = knee
            else:
                balanced = res["suit_norm"] + res["compact_norm"]
                balanced = np.where(on_front, balanced, -np.inf)
                sel = int(np.argmax(balanced))
            sel_label = "knee (best trade-off)"
        sel_assign = res["assign"][sel]
        sel_weight = float(res["weights"][sel])

        # ----------------------------------------------------- front table
        f_fields = self.make_fields(
            ("point", INT), ("w_compact", DOUBLE), ("suitability", DOUBLE),
            ("compactness", DOUBLE), ("suit_norm", DOUBLE),
            ("compact_norm", DOUBLE), ("on_front", INT), ("knee", INT),
            ("selected", INT), ("n_swaps", INT), ("n_reassign", INT))
        f_sink, f_dest = self.parameterAsSink(
            parameters, self.OUT_FRONT, context, f_fields,
            QgsWkbTypes.NoGeometry, QgsCoordinateReferenceSystem())
        for k in range(len(weights)):
            feat = QgsFeature(f_fields)
            feat.setAttributes([
                int(k), round(float(res["weights"][k]), 6),
                round(float(suit_vals[k]), 4), round(float(comp_vals[k]), 4),
                round(float(res["suit_norm"][k]), 4),
                round(float(res["compact_norm"][k]), 4),
                1 if bool(on_front[k]) else 0,
                1 if k == knee else 0,
                1 if k == sel else 0,
                int(res["swaps"][k]), int(res["reassigned"][k])])
            f_sink.addFeature(feat, QgsFeatureSink.FastInsert)

        # --------------------------------------------- selected parcel map
        p_fields = self.make_fields(
            ("alloc_use", STRING), ("alloc_suit", DOUBLE),
            ("alloc_area", DOUBLE), ("sel_weight", DOUBLE), base=fields)
        p_sink, p_dest = self.parameterAsSink(
            parameters, self.OUT_PARCELS, context, p_fields,
            source.wkbType(), source.sourceCrs())
        n_base = len(fields)
        for i, feat in enumerate(feats):
            u = int(sel_assign[i])
            use = use_names[u] if u >= 0 else ""
            s = float(suit[i, u]) if u >= 0 else 0.0
            out = QgsFeature(p_fields)
            out.setGeometry(feat.geometry())
            out.setAttributes(list(feat.attributes())[:n_base]
                              + [use, round(s, 4), round(float(area[i]), 2),
                                 round(sel_weight, 6)])
            p_sink.addFeature(out, QgsFeatureSink.FastInsert)

        # ----------------------------------------------------------- log
        n_front = int(on_front.sum())
        feedback.pushInfo(self.tr(
            f"Pareto front: {n_front} of {len(weights)} solutions are "
            "non-dominated."))
        feedback.pushInfo(self.tr(
            f"Suitability ranges {float(suit_vals.min()):g} to "
            f"{float(suit_vals.max()):g}; compactness {float(comp_vals.min()):g} "
            f"to {float(comp_vals.max()):g} (shared same-use boundary)."))
        if knee >= 0:
            feedback.pushInfo(self.tr(
                f"Knee at weight {float(res['weights'][knee]):g}: suitability "
                f"{float(suit_vals[knee]):g}, compactness "
                f"{float(comp_vals[knee]):g}."))
        feedback.pushInfo(self.tr(
            f"Exported the {sel_label} solution (weight {sel_weight:g}) as the "
            "parcel map."))
        return {self.OUT_FRONT: f_dest, self.OUT_PARCELS: p_dest}

    def createInstance(self):
        return ParetoAllocationAlgorithm()
