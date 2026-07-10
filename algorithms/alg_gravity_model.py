# -*- coding: utf-8 -*-
"""Gravity Model algorithm wrapper."""
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

from .base import DOUBLE, GROUP_DEMAND, PlanXAlgorithm, STRING
from ..engine import demand, graphs, paths


class GravityModelAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_DEMAND
    ICON = "tool_gravitymodel.png"
    ZONES = "ZONES"
    ZONE_ID = "ZONE_ID"
    PRODUCTION_FIELD = "PRODUCTION_FIELD"
    ATTRACTION_FIELD = "ATTRACTION_FIELD"
    NETWORK = "NETWORK"
    COST_FIELD = "COST_FIELD"
    BETA = "BETA"
    KIND = "KIND"
    MAX_ITER = "MAX_ITER"
    TOL = "TOL"
    OUTPUT = "OUTPUT"
    LINES = "LINES"

    KINDS = ["Exponential", "Power"]

    def name(self):
        return "gravitymodel"

    def displayName(self):
        return self.tr("Gravity Distribution")

    def shortHelpString(self):
        return self.tr(
            "Screening-quality gravity travel distribution model.\n\n"
            "Runs a doubly constrained Furness/IPF gravity model over zone productions, "
            "attractions, and a travel cost matrix computed over the street network. "
            "Deterrence functions include exponential exp(-beta * cost) and power cost^(-beta).\n\n"
            "Outputs an OD flow table and optional desire lines styled by flow, with the "
            "top 10 flows logged.\n\n"
            "How to read the results\n"
            "- Each flow value is 'trips from i to j' implied by the "
            "land-use pattern and travel costs. Style the desire lines "
            "by flow: the thick bundles are the corridors the land-use "
            "plan is silently ordering from the transport system.\n"
            "- beta is trip-length behaviour: higher beta = people "
            "stay local (short trips dominate), lower beta = distance "
            "barely deters. Calibrate it so the modelled mean trip "
            "cost matches an observed one - or run 2-3 betas and treat "
            "the spread as uncertainty.\n"
            "- Doubly constrained means row/column totals are honoured "
            "by construction - the model distributes trips, it never "
            "creates them; watch the log's balancing error to confirm "
            "convergence.\n\n"
            "Using the results: difference two scenario OD tables "
            "(base vs plan) to see which corridors gain and lose - "
            "the transport case for or against a land-use decision; "
            "feed the flows to Mode Split for the sustainable-mode "
            "share; big flows on pairs with poor transit (check "
            "Transit Access) are your priority transit corridors."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.ZONES, self.tr("Zone layer"), [QgsProcessing.TypeVectorPolygon, QgsProcessing.TypeVectorPoint]))
        self.addParameter(QgsProcessingParameterField(
            self.ZONE_ID, self.tr("Zone ID field"), parentLayerParameterName=self.ZONES))
        self.addParameter(QgsProcessingParameterField(
            self.PRODUCTION_FIELD, self.tr("Productions field"), parentLayerParameterName=self.ZONES,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterField(
            self.ATTRACTION_FIELD, self.tr("Attractions field"), parentLayerParameterName=self.ZONES,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("Street network (lines)"), [QgsProcessing.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterField(
            self.COST_FIELD, self.tr("Cost field on network (empty = length)"),
            parentLayerParameterName=self.NETWORK, optional=True,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.BETA, self.tr("Deterrence coefficient (beta)"),
            QgsProcessingParameterNumber.Double, defaultValue=0.1, minValue=0.0))
        self.addParameter(QgsProcessingParameterEnum(
            self.KIND, self.tr("Deterrence function type"), self.KINDS,
            defaultValue=0))
        self.addParameter(QgsProcessingParameterNumber(
            self.MAX_ITER, self.tr("Maximum balancing iterations"),
            QgsProcessingParameterNumber.Integer, defaultValue=100, minValue=1))
        self.addParameter(QgsProcessingParameterNumber(
            self.TOL, self.tr("Convergence tolerance"),
            QgsProcessingParameterNumber.Double, defaultValue=1e-4, minValue=1e-12))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("OD matrix (table)"),
            type=QgsProcessing.TypeVector))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.LINES, self.tr("Desire lines"), optional=True,
            createByDefault=False))

    def processAlgorithm(self, parameters, context, feedback):
        zones = self.parameterAsSource(parameters, self.ZONES, context)
        zone_id_f = self.parameterAsString(parameters, self.ZONE_ID, context)
        prod_f = self.parameterAsString(parameters, self.PRODUCTION_FIELD, context)
        attr_f = self.parameterAsString(parameters, self.ATTRACTION_FIELD, context)
        network = self.parameterAsSource(parameters, self.NETWORK, context)
        cost_field = self.parameterAsString(parameters, self.COST_FIELD, context)
        beta = self.parameterAsDouble(parameters, self.BETA, context)
        kind_idx = self.parameterAsEnum(parameters, self.KIND, context)
        kind = "exp" if kind_idx == 0 else "power"
        max_iter = self.parameterAsInt(parameters, self.MAX_ITER, context)
        tol = self.parameterAsDouble(parameters, self.TOL, context)

        self.require_projected(network, "Street network")
        crs = network.sourceCrs()

        polylines, line_feats = self.source_polylines(network)
        costs = None
        if cost_field:
            idx = network.fields().lookupField(cost_field)
            costs = [float(f.attributes()[idx] or 0.0) for f in line_feats]
        graph = graphs.build_node_graph(polylines, costs=costs)
        feedback.pushInfo(self.tr(
            f"Graph: {graph.num_nodes} nodes / {graph.num_edges} edges"))

        o_xy, o_feats = self.source_points(zones, crs, context.transformContext())
        o_nodes = graphs.nearest_nodes(graph, o_xy)

        oid_idx = zones.fields().lookupField(zone_id_f)
        prod_idx = zones.fields().lookupField(prod_f)
        attr_idx = zones.fields().lookupField(attr_f)

        o_ids = []
        P = []
        A = []
        for f in o_feats:
            o_ids.append(str(f.attributes()[oid_idx]))
            try:
                p = float(f.attributes()[prod_idx] or 0.0)
            except (TypeError, ValueError):
                p = 0.0
            try:
                a = float(f.attributes()[attr_idx] or 0.0)
            except (TypeError, ValueError):
                a = 0.0
            P.append(p)
            A.append(a)

        cost_matrix = paths.many_to_many(graph.indptr, graph.adj_node, graph.adj_cost,
                                         graph.num_nodes, o_nodes, cancel=feedback.isCanceled)
        cost_matrix = cost_matrix[:, o_nodes]
        cost_matrix[~np.isfinite(cost_matrix)] = 1e9

        T, iterations, error = demand.gravity(
            np.array(P, dtype=np.float64),
            np.array(A, dtype=np.float64),
            cost_matrix, beta, kind, max_iter, tol
        )

        feedback.pushInfo(self.tr(
            f"Gravity balancing: {iterations} iterations, max error: {error:.6f}"))

        fields = self.make_fields(
            ("origin_id", STRING),
            ("dest_id", STRING),
            ("cost", DOUBLE),
            ("flow", DOUBLE)
        )

        sink, dest_matrix = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields,
            QgsWkbTypes.NoGeometry, crs)

        line_sink = line_dest = None
        if parameters.get(self.LINES) is not None:
            line_sink, line_dest = self.parameterAsSink(
                parameters, self.LINES, context, fields,
                QgsWkbTypes.LineString, crs)

        N = len(o_ids)
        flat_flows = []
        for i in range(N):
            if feedback.isCanceled():
                break
            feedback.setProgress(int(100.0 * i / max(1, N)))
            for j in range(N):
                if i == j:
                    continue
                flow_val = float(T[i, j])
                cost_val = float(cost_matrix[i, j])
                flat_flows.append((flow_val, o_ids[i], o_ids[j], cost_val, i, j))

                if flow_val <= 0.0:
                    continue

                attrs = [o_ids[i], o_ids[j], cost_val, flow_val]
                f = QgsFeature(fields)
                f.setAttributes(attrs)
                sink.addFeature(f, QgsFeatureSink.FastInsert)

                if line_sink is not None:
                    lf = QgsFeature(fields)
                    lf.setAttributes(attrs)
                    lf.setGeometry(QgsGeometry.fromPolylineXY([
                        QgsPointXY(*o_xy[i]), QgsPointXY(*o_xy[j])
                    ]))
                    line_sink.addFeature(lf, QgsFeatureSink.FastInsert)

        flat_flows.sort(key=lambda x: x[0], reverse=True)
        feedback.pushInfo(self.tr("Top 10 travel demand flows:"))
        for rank, (flow, o_id, d_id, c, _, _) in enumerate(flat_flows[:10], 1):
            feedback.pushInfo(self.tr(f"  {rank}. {o_id} -> {d_id}: flow={flow:.2f}, cost={c:.2f}"))

        results = {self.OUTPUT: dest_matrix}
        if line_dest is not None:
            results[self.LINES] = line_dest
        return results

    def createInstance(self):
        return GravityModelAlgorithm()
