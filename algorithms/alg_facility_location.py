# -*- coding: utf-8 -*-
"""Facility Location Optimizer: maximal coverage / p-median on the network."""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsFeature,
    QgsFeatureSink,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_OPTIMIZE, INT, PlanXAlgorithm, STRING
from ..engine import graphs, optimize, paths


class FacilityLocationAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_OPTIMIZE
    ICON = "tool_facilitylocation.png"
    NETWORK = "NETWORK"
    DEMAND = "DEMAND"
    POP_FIELD = "POP_FIELD"
    CANDIDATES = "CANDIDATES"
    CANDIDATE_ID = "CANDIDATE_ID"
    EXISTING = "EXISTING"
    METHOD = "METHOD"
    P = "P"
    RADIUS = "RADIUS"
    OUT_SITES = "OUT_SITES"
    OUT_ASSIGN = "OUT_ASSIGN"

    METHODS = ["Maximize coverage within catchment (greedy)",
               "Minimize total travel (p-median, Teitz-Bart)"]

    def name(self):
        return "facilitylocation"

    def displayName(self):
        return self.tr("Facility Location Optimizer (Coverage / P-Median)")

    def shortHelpString(self):
        return self.tr(
            "Chooses the best sites for new facilities (schools, clinics, "
            "parks, fire stations...) among your candidate locations, "
            "computed on the real street network by the embedded engine - "
            "the classic location-allocation models, no external solver.\n\n"
            "Methods:\n"
            "- Maximize coverage (Church & ReVelle): each pick adds the "
            "most uncovered demand within the catchment radius;\n"
            "- P-median (Teitz & Bart vertex substitution): minimizes the "
            "population-weighted travel cost to the nearest facility.\n\n"
            "Existing facilities (optional) are kept in the solution and "
            "new sites complement them. Outputs:\n"
            "- Candidate sites: every candidate with its standalone "
            "screening score (demand within the radius), selection flag, "
            "pick rank and marginal gain;\n"
            "- Demand allocation: every demand point with its assigned "
            "facility, network cost and covered flag.\n\n"
            "Population defaults to 1 per demand point when no field is "
            "given. Use a projected CRS."
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
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.EXISTING, self.tr("Existing facilities (kept in the solution)"),
            [QgsProcessing.TypeVectorAnyGeometry], optional=True))
        self.addParameter(QgsProcessingParameterEnum(
            self.METHOD, self.tr("Objective"), self.METHODS, defaultValue=0))
        self.addParameter(QgsProcessingParameterNumber(
            self.P, self.tr("Number of new facilities to site (p)"),
            QgsProcessingParameterNumber.Integer, 3, minValue=1))
        self.addParameter(QgsProcessingParameterNumber(
            self.RADIUS, self.tr("Catchment radius (map units; coverage + screening)"),
            QgsProcessingParameterNumber.Double, 500.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_SITES, self.tr("Candidate sites (screened + selected)")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_ASSIGN, self.tr("Demand allocation")))

    def processAlgorithm(self, parameters, context, feedback):
        network = self.parameterAsSource(parameters, self.NETWORK, context)
        demand = self.parameterAsSource(parameters, self.DEMAND, context)
        candidates = self.parameterAsSource(parameters, self.CANDIDATES, context)
        existing = self.parameterAsSource(parameters, self.EXISTING, context)
        pop_field = self.parameterAsString(parameters, self.POP_FIELD, context)
        cand_id = self.parameterAsString(parameters, self.CANDIDATE_ID, context)
        method = self.parameterAsEnum(parameters, self.METHOD, context)
        p = self.parameterAsInt(parameters, self.P, context)
        radius = self.parameterAsDouble(parameters, self.RADIUS, context)
        self.require_projected(network, "Street network")

        polylines, _ = self.source_polylines(network)
        graph = graphs.build_node_graph(polylines)
        crs = network.sourceCrs()
        xform = context.transformContext()
        d_xy, d_feats = self.source_points(demand, crs, xform)
        c_xy, c_feats = self.source_points(candidates, crs, xform)
        d_nodes = graphs.nearest_nodes(graph, d_xy)
        c_nodes = graphs.nearest_nodes(graph, c_xy)
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
        labels = [f"EX{i + 1}" for i in range(len(e_feats))] + c_ids

        # Distance matrix rows: existing facilities first (fixed), then
        # candidates. Coverage only needs distances up to the radius.
        sources = np.concatenate([e_nodes, c_nodes]).astype(np.int64)
        cutoff = radius if method == 0 else None
        feedback.pushInfo(self.tr(
            f"Computing network distances: {len(sources)} sites x "
            f"{len(d_feats)} demand points..."))
        dist = paths.many_to_many(graph.indptr, graph.adj_node, graph.adj_cost,
                                  graph.num_nodes, sources, cutoff=cutoff,
                                  cancel=feedback.isCanceled)
        D = dist[:, d_nodes]
        fixed = list(range(len(e_feats)))
        n_free = len(c_feats)
        if p > n_free:
            feedback.pushWarning(self.tr(
                f"p={p} exceeds the {n_free} candidates - selecting all."))
            p = n_free

        screening = optimize.coverage_weights(D[len(e_feats):], w, radius)

        if method == 0:
            res = optimize.greedy_max_coverage(D, w, p, radius, fixed=fixed)
            sel_rows = res["selected"]
            gains = res["gains"]
            share = (100.0 * res["covered_weight"] / res["total_weight"]
                     if res["total_weight"] > 0 else 0.0)
            running = float(w[(D[fixed] <= radius).any(axis=0)].sum()) if fixed else 0.0
            for rank, (row, gain) in enumerate(zip(sel_rows, gains), start=1):
                running += gain
                feedback.pushInfo(self.tr(
                    f"  pick {rank}: {labels[row]} (+{gain:g} demand, "
                    f"running coverage {running:g})"))
            feedback.pushInfo(self.tr(
                f"Covered demand: {res['covered_weight']:g} of "
                f"{res['total_weight']:g} ({share:.1f} percent) within {radius:g}."))
        else:
            res = optimize.p_median(D, w, p, fixed=fixed)
            sel_rows = res["selected"]
            gains = [0.0] * len(sel_rows)
            total_w = float(w.sum())
            mean_cost = res["objective"] / total_w if total_w > 0 else 0.0
            feedback.pushInfo(self.tr(
                f"P-median objective: {res['objective']:g} weighted cost "
                f"(mean {mean_cost:g} per person), {res['swaps']} improving "
                f"swap(s) applied."))

        solution = fixed + list(sel_rows)
        assign, cost = optimize.assign_to_nearest(D, solution)

        # ------------------------------------------------------- sites out
        s_fields = self.make_fields(
            ("cand_id", STRING), ("reach_dem", DOUBLE), ("selected", INT),
            ("rank", INT), ("gain", DOUBLE), base=candidates.fields())
        s_sink, s_dest = self.parameterAsSink(
            parameters, self.OUT_SITES, context, s_fields, QgsWkbTypes.Point, crs)
        rank_of = {row: i + 1 for i, row in enumerate(sel_rows)}
        gain_of = {row: gains[i] for i, row in enumerate(sel_rows)}
        n_cand_fields = len(candidates.fields())
        for j, feat in enumerate(c_feats):
            row = len(e_feats) + j
            out = QgsFeature(s_fields)
            out.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*c_xy[j])))
            out.setAttributes(
                list(feat.attributes())[:n_cand_fields]
                + [c_ids[j], round(float(screening[j]), 2),
                   1 if row in rank_of else 0, rank_of.get(row, 0),
                   round(float(gain_of.get(row, 0.0)), 2)])
            s_sink.addFeature(out, QgsFeatureSink.FastInsert)

        # -------------------------------------------------- allocation out
        a_fields = self.make_fields(
            ("facility", STRING), ("net_cost", DOUBLE), ("covered", INT),
            base=demand.fields())
        a_sink, a_dest = self.parameterAsSink(
            parameters, self.OUT_ASSIGN, context, a_fields, QgsWkbTypes.Point, crs)
        n_dem_fields = len(demand.fields())
        for i, feat in enumerate(d_feats):
            if feedback.isCanceled():
                break
            pos = int(assign[i])
            c = float(cost[i])
            reachable = pos >= 0 and c >= 0.0
            covered = bool(reachable and c <= radius)
            out = QgsFeature(a_fields)
            out.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*d_xy[i])))
            out.setAttributes(
                list(feat.attributes())[:n_dem_fields]
                + [labels[solution[pos]] if reachable else "",
                   round(c, 3) if reachable else -1.0,
                   1 if covered else 0])
            a_sink.addFeature(out, QgsFeatureSink.FastInsert)

        return {self.OUT_SITES: s_dest, self.OUT_ASSIGN: a_dest}

    def createInstance(self):
        return FacilityLocationAlgorithm()
