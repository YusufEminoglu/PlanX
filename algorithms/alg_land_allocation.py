# -*- coding: utf-8 -*-
"""Land-Use Allocation Optimizer: multi-objective parcel-to-use assignment."""
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


class LandUseAllocationAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_OPTIMIZE
    ICON = "tool_landallocation.png"
    PARCELS = "PARCELS"
    SUIT_FIELDS = "SUIT_FIELDS"
    TARGETS = "TARGETS"
    AREA_FIELD = "AREA_FIELD"
    LOCK_FIELD = "LOCK_FIELD"
    W_COMPACT = "W_COMPACT"
    ADJACENCY = "ADJACENCY"
    CONTIGUITY = "CONTIGUITY"
    W_SUITABILITY = "W_SUITABILITY"
    OUT_PARCELS = "OUT_PARCELS"
    OUT_SUMMARY = "OUT_SUMMARY"

    def name(self):
        return "landallocation"

    def displayName(self):
        return self.tr("Land-Use Allocation Optimizer")

    def shortHelpString(self):
        return self.tr(
            "Assigns a land use to each parcel to MAXIMISE an objective "
            "while meeting a target area for each use - the spatial "
            "allocation problem at the heart of plan-making, solved "
            "natively, no external solver.\n\n"
            "You provide, on the parcel layer, one suitability field per "
            "land use (0-1 or 0-100, e.g. straight from Suitability Lab) "
            "and a target AREA to fill for each use. Each parcel is assigned "
            "in full to at most one use so that the area given to a use does "
            "not exceed its target. Parcels not needed are left unassigned; "
            "a use that cannot be filled reports a shortfall.\n\n"
            "MULTI-OBJECTIVE: beyond per-parcel suitability you can shape "
            "the spatial pattern.\n"
            "- Compactness weight (> 0): rewards same-use parcels that share "
            "a boundary, so a use forms compact zones instead of scattering "
            "(the reward is per map unit of shared boundary).\n"
            "- Adjacency rules: 'residential|industry=-2, residential|"
            "green=1' rewards (+) or penalises (-) specific use pairs being "
            "neighbours, again per unit of shared boundary.\n"
            "- Suitability weight (advanced): balances suitability against "
            "the spatial terms. Leave compactness 0 and rules empty for pure "
            "suitability allocation.\n\n"
            "Targets are free text: 's_residential=50000, s_green=30000' "
            "(area in the layer's map units); names match the suitability "
            "field names (exact, else by containment). An optional lock "
            "field fixes already-zoned parcels to a use (its name must match "
            "a suitability field).\n\n"
            "Method: greedy construction (best suitability first) plus a "
            "local search of reassignments and capacity-respecting swaps on "
            "the full objective - a fast heuristic, not a guaranteed global "
            "optimum. Parcel area comes from the geometry unless an area "
            "field is given. Use a projected CRS.\n\n"
            "Outputs:\n"
            "- Parcels: the assigned use, its suitability, the parcel area "
            "and a locked flag - style by 'alloc_use' for a land-use map;\n"
            "- Summary: per use the target vs allocated area, the shortfall, "
            "the parcel count and the mean suitability achieved."
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
            self.W_COMPACT,
            self.tr("Compactness weight (reward per unit of shared same-use "
                    "boundary; 0 = off)"),
            QgsProcessingParameterNumber.Double, 0.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterString(
            self.ADJACENCY,
            self.tr("Adjacency rules (useA|useB=value, ...; + attract, - repel)"),
            "", optional=True))
        self.addParameter(QgsProcessingParameterEnum(
            self.CONTIGUITY, self.tr("Contiguity mode"),
            ["Soft (compactness weight)", "Hard (single connected zone per use)"],
            defaultValue=0))
        w_suit = QgsProcessingParameterNumber(
            self.W_SUITABILITY,
            self.tr("Suitability weight (relative to the spatial terms)"),
            QgsProcessingParameterNumber.Double, 1.0, minValue=0.0)
        w_suit.setFlags(w_suit.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(w_suit)
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_PARCELS, self.tr("Allocated parcels")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_SUMMARY, self.tr("Allocation summary"),
            type=QgsProcessing.TypeVector))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.PARCELS, context)
        suit_fields = self.parameterAsFields(parameters, self.SUIT_FIELDS, context)
        area_field = self.parameterAsString(parameters, self.AREA_FIELD, context)
        lock_field = self.parameterAsString(parameters, self.LOCK_FIELD, context)
        w_compact = self.parameterAsDouble(parameters, self.W_COMPACT, context)
        adjacency_text = self.parameterAsString(parameters, self.ADJACENCY, context)
        contiguity = self.parameterAsEnum(parameters, self.CONTIGUITY, context)
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

        # adjacency rules -> symmetric compatibility matrix off-diagonal
        n_use = len(use_names)
        compat = np.zeros((n_use, n_use))
        if w_compact != 0:
            np.fill_diagonal(compat, w_compact)
        has_rules = False
        for token in str(adjacency_text).replace(";", ",").split(","):
            token = token.strip()
            if not token:
                continue
            if "=" not in token or "|" not in token:
                feedback.pushWarning(self.tr(
                    f"Adjacency rule needs 'useA|useB=value': '{token}' - ignored."))
                continue
            names, _, val = token.partition("=")
            a, _, b = names.partition("|")
            ai = name_to_use.get(a.strip().lower())
            bi = name_to_use.get(b.strip().lower())
            try:
                value = float(val.strip())
            except ValueError:
                feedback.pushWarning(self.tr(
                    f"Adjacency rule '{token}' has no number - ignored."))
                continue
            if ai is None or bi is None:
                feedback.pushWarning(self.tr(
                    f"Adjacency rule '{token}' names an unknown use - ignored."))
                continue
            compat[bi, ai] = value
            compat[ai, bi] = value
            has_rules = True
        spatial_active = w_compact != 0 or has_rules or contiguity == 1

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

        # parcel adjacency (shared boundary lengths) - only when needed
        edges = []
        if spatial_active:
            index = QgsSpatialIndex()
            for i in range(len(feats)):
                qf = QgsFeature(i)
                qf.setGeometry(geoms[i])
                index.insertFeature(qf)
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
            feedback.pushInfo(self.tr(
                f"Adjacency graph: {len(edges)} shared parcel boundaries."))

        feedback.pushInfo(self.tr(
            f"Allocating {len(feats)} parcels to {n_use} use(s)"
            f"{' with spatial objectives' if spatial_active else ''}..."))
        if contiguity == 1:
            res = allocate.allocate_contiguous(suit, area, tvec, edges, compat,
                                               locked=lvec, w_suit=w_suit, log_warning_fn=feedback.pushWarning)
        elif spatial_active:
            res = allocate.allocate_multi(suit, area, tvec, edges, compat,
                                          locked=lvec, w_suit=w_suit)
        else:
            res = allocate.allocate_land_use(suit, area, tvec, locked=lvec)
        assign = res["assign"]
        allocated = res["allocated"]
        counts = res["n_parcels"]

        # ----------------------------------------------------- parcels out
        p_fields = self.make_fields(
            ("alloc_use", STRING), ("alloc_suit", DOUBLE),
            ("alloc_area", DOUBLE), ("locked", INT), base=fields)
        p_sink, p_dest = self.parameterAsSink(
            parameters, self.OUT_PARCELS, context, p_fields,
            source.wkbType(), source.sourceCrs())
        n_base = len(fields)
        suit_sum = np.zeros(n_use)
        for i, feat in enumerate(feats):
            u = int(assign[i])
            use = use_names[u] if u >= 0 else ""
            s = float(suit[i, u]) if u >= 0 else 0.0
            if u >= 0:
                suit_sum[u] += area[i] * s
            out = QgsFeature(p_fields)
            out.setGeometry(feat.geometry())
            out.setAttributes(list(feat.attributes())[:n_base]
                              + [use, round(s, 4), round(float(area[i]), 2),
                                 1 if int(lvec[i]) >= 0 else 0])
            p_sink.addFeature(out, QgsFeatureSink.FastInsert)

        # ----------------------------------------------------- summary out
        s_fields = self.make_fields(
            ("use", STRING), ("target_area", DOUBLE), ("alloc_area", DOUBLE),
            ("balance", DOUBLE), ("n_parcels", INT), ("mean_suit", DOUBLE),
            ("status", STRING))
        s_sink, s_dest = self.parameterAsSink(
            parameters, self.OUT_SUMMARY, context, s_fields,
            QgsWkbTypes.NoGeometry, QgsCoordinateReferenceSystem())
        for u, name in enumerate(use_names):
            alloc = float(allocated[u])
            target = float(tvec[u])
            mean_s = suit_sum[u] / alloc if alloc > 0 else 0.0
            status = "Met" if alloc + 1e-6 >= target else "Short"
            f = QgsFeature(s_fields)
            f.setAttributes([name, round(target, 2), round(alloc, 2),
                             round(alloc - target, 2), int(counts[u]),
                             round(mean_s, 4), status])
            s_sink.addFeature(f, QgsFeatureSink.FastInsert)
        unassigned_area = float(area[assign < 0].sum())
        unassigned_n = int((assign < 0).sum())
        f = QgsFeature(s_fields)
        f.setAttributes(["(unassigned)", 0.0, round(unassigned_area, 2),
                         0.0, unassigned_n, 0.0, ""])
        s_sink.addFeature(f, QgsFeatureSink.FastInsert)

        total_target = float(tvec.sum())
        total_alloc = float(allocated.sum())
        fill = 100.0 * total_alloc / total_target if total_target > 0 else 0.0
        mean_suit = res["suit_score"] / total_alloc if total_alloc > 0 else 0.0
        feedback.pushInfo(self.tr(
            f"Allocated {total_alloc:g} of {total_target:g} target area "
            f"({fill:.1f} percent); {unassigned_n} parcel(s) left over."))
        feedback.pushInfo(self.tr(
            f"Suitability score {res['suit_score']:g} (area-weighted mean "
            f"{mean_suit:.3f}); {res['reassigned']} reassignment(s), "
            f"{res['swaps']} swap(s)."))
        if spatial_active:
            same = sum(length for i, j, length in edges
                       if assign[i] >= 0 and assign[i] == assign[j])
            both = sum(length for i, j, length in edges
                       if assign[i] >= 0 and assign[j] >= 0)
            pct = 100.0 * same / both if both > 0 else 0.0
            feedback.pushInfo(self.tr(
                f"Objective {res['objective']:g} (spatial term "
                f"{res['spatial_score']:g}); {pct:.1f} percent of shared "
                "boundary is between same-use parcels (compactness)."))
        return {self.OUT_PARCELS: p_dest, self.OUT_SUMMARY: s_dest}

    def createInstance(self):
        return LandUseAllocationAlgorithm()
