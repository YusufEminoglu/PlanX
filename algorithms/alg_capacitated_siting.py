# -*- coding: utf-8 -*-
"""Capacitated Facility Siting: choose where to build facilities under capacity constraints."""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsFeature,
    QgsFeatureSink,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_OPTIMIZE, INT, PlanXAlgorithm, STRING
from ..engine import graphs, optimize, paths


class CapacitatedSitingAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_OPTIMIZE
    ICON = "tool_capacitatedsiting.png"
    NETWORK = "NETWORK"
    DEMAND = "DEMAND"
    POP_FIELD = "POP_FIELD"
    CANDIDATES = "CANDIDATES"
    CANDIDATE_ID = "CANDIDATE_ID"
    CAPACITY_FIELD = "CAPACITY_FIELD"
    EXISTING = "EXISTING"
    EXISTING_ID = "EXISTING_ID"
    EXISTING_CAP_FIELD = "EXISTING_CAP_FIELD"
    P = "P"
    MAX_COST = "MAX_COST"
    COST_FIELD = "COST_FIELD"
    OUT_SITES = "OUT_SITES"
    OUT_ALLOCATION = "OUT_ALLOCATION"
    OUT_UNCOVERED = "OUT_UNCOVERED"

    def name(self):
        return "capacitatedsiting"

    def displayName(self):
        return self.tr("Capacitated Facility Siting")

    def shortHelpString(self):
        return self.tr(
            "Chooses where to build p new facilities among candidate locations "
            "while respecting per-site capacity constraints and minimizing travel cost.\n\n"
            "First, a greedy construction phase selects sites that maximize newly "
            "served demand under a capacity-respecting allocation. Then, a Teitz-Bart "
            "vertex substitution phase optimizes the locations by swapping sites to "
            "maximize total served demand (with total travel cost as a tiebreaker).\n\n"
            "Existing facilities are kept in the solution as fixed-open.\n\n"
            "Outputs:\n"
            "- Selected sites: the open facilities (existing and selected candidate sites) "
            "with their rank, assigned load, utilization, and marginal demand gain;\n"
            "- Allocation lines: straight lines connecting each assigned demand point "
            "to its chosen facility, with network travel cost;\n"
            "- Uncovered demand: demand points that could not be assigned within the "
            "travel limit or due to capacity constraints.\n\n"
            "Population defaults to 1 per demand point when no field is given. Use a projected CRS."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("Street network (lines)"), [QgsProcessing.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.DEMAND, self.tr("Demand (buildings / address points)"),
            [QgsProcessing.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterField(
            self.POP_FIELD, self.tr("Population field (empty = 1 per point)"),
            parentLayerParameterName=self.DEMAND, optional=True,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.CANDIDATES, self.tr("Candidate sites"),
            [QgsProcessing.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterField(
            self.CANDIDATE_ID, self.tr("Candidate ID field"),
            parentLayerParameterName=self.CANDIDATES))
        self.addParameter(QgsProcessingParameterField(
            self.CAPACITY_FIELD, self.tr("Capacity field (persons)"),
            parentLayerParameterName=self.CANDIDATES,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.EXISTING, self.tr("Existing facilities (kept in the solution)"),
            [QgsProcessing.TypeVectorAnyGeometry], optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.EXISTING_ID, self.tr("Existing facility ID field"),
            parentLayerParameterName=self.EXISTING, optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.EXISTING_CAP_FIELD, self.tr("Existing facility capacity field"),
            parentLayerParameterName=self.EXISTING, optional=True,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.P, self.tr("Number of new facilities to site (p)"),
            QgsProcessingParameterNumber.Integer, 3, minValue=1))
        self.addParameter(QgsProcessingParameterNumber(
            self.MAX_COST, self.tr("Maximum travel cost (catchment limit, map units)"),
            QgsProcessingParameterNumber.Double, 500.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterField(
            self.COST_FIELD, self.tr("Cost field on network (empty = length)"),
            parentLayerParameterName=self.NETWORK, optional=True,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_SITES, self.tr("Selected sites")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_ALLOCATION, self.tr("Allocation lines")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_UNCOVERED, self.tr("Uncovered demand")))

    def processAlgorithm(self, parameters, context, feedback):
        network = self.parameterAsSource(parameters, self.NETWORK, context)
        demand = self.parameterAsSource(parameters, self.DEMAND, context)
        candidates = self.parameterAsSource(parameters, self.CANDIDATES, context)
        existing = self.parameterAsSource(parameters, self.EXISTING, context)
        pop_field = self.parameterAsString(parameters, self.POP_FIELD, context)
        cand_id = self.parameterAsString(parameters, self.CANDIDATE_ID, context)
        capacity_field = self.parameterAsString(parameters, self.CAPACITY_FIELD, context)
        existing_id = self.parameterAsString(parameters, self.EXISTING_ID, context)
        existing_cap = self.parameterAsString(parameters, self.EXISTING_CAP_FIELD, context)
        p = self.parameterAsInt(parameters, self.P, context)
        max_cost = self.parameterAsDouble(parameters, self.MAX_COST, context)
        cost_field = self.parameterAsString(parameters, self.COST_FIELD, context)
        self.require_projected(network, "Street network")

        polylines, line_feats = self.source_polylines(network)
        costs = None
        if cost_field:
            idx = network.fields().lookupField(cost_field)
            costs = [float(f.attributes()[idx] or 0.0) for f in line_feats]
        graph = graphs.build_node_graph(polylines, costs=costs)

        crs = network.sourceCrs()
        xform = context.transformContext()
        d_xy, d_feats = self.source_points(demand, crs, xform)
        c_xy, c_feats = self.source_points(candidates, crs, xform)
        d_nodes = graphs.nearest_nodes(graph, d_xy)
        c_nodes = graphs.nearest_nodes(graph, c_xy)

        e_xy = np.empty((0, 2))
        e_feats = []
        e_nodes = np.empty(0, dtype=np.int64)
        if existing is not None:
            e_xy, e_feats = self.source_points(existing, crs, xform)
            e_nodes = graphs.nearest_nodes(graph, e_xy)

        pop_idx = demand.fields().lookupField(pop_field) if pop_field else -1

        def pop_of(feat):
            if pop_idx < 0:
                return 1.0
            try:
                return max(0.0, float(feat.attributes()[pop_idx]))
            except (TypeError, ValueError):
                return 0.0

        w = np.array([pop_of(f) for f in d_feats])

        cid_idx = candidates.fields().lookupField(cand_id)
        c_ids = [str(f.attributes()[cid_idx]) for f in c_feats]

        e_ids = []
        if existing is not None and existing_id:
            e_id_idx = existing.fields().lookupField(existing_id)
            e_ids = [str(f.attributes()[e_id_idx]) for f in e_feats]
        else:
            e_ids = [f"EX{i + 1}" for i in range(len(e_feats))]

        labels = e_ids + c_ids

        # Build capacities
        e_cap_vals = []
        if existing is not None and existing_cap:
            ecap_idx = existing.fields().lookupField(existing_cap)
            for f in e_feats:
                try:
                    e_cap_vals.append(max(0.0, float(f.attributes()[ecap_idx])))
                except (TypeError, ValueError):
                    e_cap_vals.append(1e9)  # default very large if not parsable
        else:
            e_cap_vals = [1e9] * len(e_feats)

        c_cap_vals = []
        cap_idx = candidates.fields().lookupField(capacity_field)
        for f in c_feats:
            try:
                c_cap_vals.append(max(0.0, float(f.attributes()[cap_idx])))
            except (TypeError, ValueError):
                c_cap_vals.append(0.0)

        capacities = np.array(e_cap_vals + c_cap_vals)

        sources = np.concatenate([e_nodes, c_nodes]).astype(np.int64)
        feedback.pushInfo(self.tr(
            f"Computing network distances: {len(sources)} sites x "
            f"{len(d_feats)} demand points (catchment {max_cost:g})..."))

        dist = paths.many_to_many(graph.indptr, graph.adj_node, graph.adj_cost,
                                  graph.num_nodes, sources, cutoff=max_cost,
                                  cancel=feedback.isCanceled)
        D = dist[:, d_nodes]

        fixed = list(range(len(e_feats)))
        n_free = len(c_feats)
        if p > n_free:
            feedback.pushWarning(self.tr(
                f"p={p} exceeds the {n_free} candidates - selecting all."))
            p = n_free

        res = optimize.capacitated_siting(D, w, capacities, p, existing_idx=fixed, max_cost=max_cost)
        selected_indices = res["selected"]
        assign = res["assign"]
        cost = res["cost"]
        load = res["load"]
        utilization = res["utilization"]

        # Calculate marginal demand gains
        gain_of = {}
        rank_of = {}
        for rank, idx in enumerate(selected_indices, start=1):
            rank_of[idx] = rank
            if rank < len(res["obj_history"]):
                gain_of[idx] = res["obj_history"][rank][0] - res["obj_history"][rank - 1][0]
            else:
                gain_of[idx] = 0.0

        # Log metrics
        total_w = float(w.sum())
        covered_w = float(w[assign != -1].sum()) if assign.size else 0.0
        share = covered_w / total_w if total_w > 0 else 0.0
        mean_cost = float(cost[assign != -1].mean()) if np.any(assign != -1) else 0.0
        total_cap_open = float(capacities[fixed + selected_indices].sum())
        capacity_slack = total_cap_open - covered_w

        feedback.pushInfo(self.tr(
            f"Coverage: {covered_w:g} of {total_w:g} ({share:.1%}); "
            f"mean cost: {mean_cost:.2f}; capacity slack: {capacity_slack:g}."))

        # 1. Output selected/open sites
        s_fields = self.make_fields(
            ("facility", STRING), ("rank", INT), ("load", DOUBLE),
            ("utilization", DOUBLE), ("gain", DOUBLE), base=candidates.fields())
        s_sink, s_dest = self.parameterAsSink(
            parameters, self.OUT_SITES, context, s_fields, QgsWkbTypes.Point, crs)

        n_cand_fields = len(candidates.fields())

        for idx in fixed + selected_indices:
            out = QgsFeature(s_fields)
            if idx < len(e_feats):
                # Existing facility
                out.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*e_xy[idx])))
                # Use default/blank attributes for candidate fields
                attrs = [""] * n_cand_fields + [labels[idx], 0, round(float(load[idx]), 2),
                                                round(float(utilization[idx]), 3), 0.0]
                out.setAttributes(attrs)
            else:
                # Selected candidate
                c_idx = idx - len(e_feats)
                out.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*c_xy[c_idx])))
                attrs = list(c_feats[c_idx].attributes())[:n_cand_fields] + [
                    labels[idx], rank_of[idx], round(float(load[idx]), 2),
                    round(float(utilization[idx]), 3), round(float(gain_of.get(idx, 0.0)), 2)
                ]
                out.setAttributes(attrs)
            s_sink.addFeature(out, QgsFeatureSink.FastInsert)

        # 2. Output allocation lines
        l_fields = self.make_fields(("facility", STRING), ("net_cost", DOUBLE))
        l_sink, l_dest = self.parameterAsSink(
            parameters, self.OUT_ALLOCATION, context, l_fields, QgsWkbTypes.LineString, crs)

        for i, feat in enumerate(d_feats):
            if feedback.isCanceled():
                break
            f_idx = int(assign[i])
            if f_idx >= 0:
                facility_xy = e_xy[f_idx] if f_idx < len(e_feats) else c_xy[f_idx - len(e_feats)]
                lf = QgsFeature(l_fields)
                lf.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(*d_xy[i]), QgsPointXY(*facility_xy)]))
                lf.setAttributes([labels[f_idx], round(float(cost[i]), 3)])
                l_sink.addFeature(lf, QgsFeatureSink.FastInsert)

        # 3. Output uncovered demand
        u_fields = demand.fields()
        u_sink, u_dest = self.parameterAsSink(
            parameters, self.OUT_UNCOVERED, context, u_fields, QgsWkbTypes.Point, crs)

        for i, feat in enumerate(d_feats):
            if feedback.isCanceled():
                break
            if assign[i] == -1:
                out = QgsFeature(u_fields)
                out.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*d_xy[i])))
                out.setAttributes(list(feat.attributes()))
                u_sink.addFeature(out, QgsFeatureSink.FastInsert)

        return {
            self.OUT_SITES: s_dest,
            self.OUT_ALLOCATION: l_dest,
            self.OUT_UNCOVERED: u_dest,
        }

    def createInstance(self):
        return CapacitatedSitingAlgorithm()
