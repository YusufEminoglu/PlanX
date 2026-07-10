# -*- coding: utf-8 -*-
"""OD Cost Matrix: many-to-many network distances, embedded Dijkstra."""
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

from .base import DOUBLE, GROUP_NETWORK, PlanXAlgorithm, STRING
from ..engine import graphs, paths


class ODCostMatrixAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_NETWORK
    ICON = "tool_odmatrix.png"
    NETWORK = "NETWORK"
    ORIGINS = "ORIGINS"
    ORIGIN_ID = "ORIGIN_ID"
    DESTINATIONS = "DESTINATIONS"
    DEST_ID = "DEST_ID"
    COST_FIELD = "COST_FIELD"
    CUTOFF = "CUTOFF"
    MATRIX = "MATRIX"
    LINES = "LINES"

    def name(self):
        return "odmatrix"

    def displayName(self):
        return self.tr("OD Cost Matrix")

    def shortHelpString(self):
        return self.tr(
            "Computes the full origin-destination cost matrix over the street "
            "network with the embedded Dijkstra engine (SciPy-accelerated when "
            "available) - no external routing plugin or server needed.\n\n"
            "Cost defaults to metric length; an optional numeric line field "
            "(e.g. travel time) can override it. Each OD pair reports the "
            "network cost, the straight-line distance and the detour ratio "
            "(network / Euclidean). Optional desire lines visualize the matrix. "
            "Points snap to their nearest network node; run 'Prepare Network' "
            "first if your lines are not noded. A cost cutoff of 0 means "
            "unlimited.\n\n"
            "How to read the results\n"
            "- net_cost is the operative number: real distance (or time) "
            "people must travel, the input for catchment rules, siting "
            "studies and gravity models.\n"
            "- detour (network / straight line) is the shape diagnostic: "
            "~1.0-1.2 = direct, well-gridded connection; 1.4+ = the "
            "network forces a long way round (river, rail, superblock, "
            "missing link). Map desire lines coloured by detour and the "
            "worst barriers light up.\n"
            "- Missing pairs (no row) are unreachable within the cutoff - "
            "count them per origin to find disconnected pockets.\n\n"
            "Using the results: sort by detour to shortlist where a new "
            "bridge, underpass or street link pays off most; feed net_cost "
            "into Gravity Model / Mode Split for demand work; rerun on a "
            "proposed network and diff net_cost per pair to quantify a "
            "plan's accessibility gain."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("Street network (lines)"), [QgsProcessing.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.ORIGINS, self.tr("Origins"), [QgsProcessing.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterField(
            self.ORIGIN_ID, self.tr("Origin ID field"), parentLayerParameterName=self.ORIGINS))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.DESTINATIONS, self.tr("Destinations (empty = origins)"),
            [QgsProcessing.TypeVectorAnyGeometry], optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.DEST_ID, self.tr("Destination ID field"),
            parentLayerParameterName=self.DESTINATIONS, optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.COST_FIELD, self.tr("Cost field on network (empty = length)"),
            parentLayerParameterName=self.NETWORK, optional=True,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.CUTOFF, self.tr("Maximum cost (0 = unlimited)"),
            QgsProcessingParameterNumber.Double, 0.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.MATRIX, self.tr("OD matrix (table)"),
            type=QgsProcessing.TypeVector))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.LINES, self.tr("Desire lines"), optional=True,
            createByDefault=False))

    def processAlgorithm(self, parameters, context, feedback):
        network = self.parameterAsSource(parameters, self.NETWORK, context)
        origins = self.parameterAsSource(parameters, self.ORIGINS, context)
        dests = self.parameterAsSource(parameters, self.DESTINATIONS, context)
        origin_id = self.parameterAsString(parameters, self.ORIGIN_ID, context)
        dest_id = self.parameterAsString(parameters, self.DEST_ID, context)
        cost_field = self.parameterAsString(parameters, self.COST_FIELD, context)
        cutoff = self.parameterAsDouble(parameters, self.CUTOFF, context) or None
        self.require_projected(network, "Street network")
        same_layer = dests is None
        if same_layer:
            dests, dest_id = origins, origin_id
        if not dest_id:
            dest_id = dest_id or origin_id

        polylines, line_feats = self.source_polylines(network)
        costs = None
        if cost_field:
            idx = network.fields().lookupField(cost_field)
            costs = [float(f.attributes()[idx] or 0.0) for f in line_feats]
        graph = graphs.build_node_graph(polylines, costs=costs)
        feedback.pushInfo(self.tr(
            f"Graph: {graph.num_nodes} nodes / {graph.num_edges} edges "
            f"(SciPy fast path: {'yes' if paths.HAS_SCIPY else 'no'})"))

        crs = network.sourceCrs()
        o_xy, o_feats = self.source_points(origins, crs, context.transformContext())
        if same_layer:
            d_xy, d_feats = o_xy, o_feats
        else:
            d_xy, d_feats = self.source_points(dests, crs, context.transformContext())
        o_nodes = graphs.nearest_nodes(graph, o_xy)
        d_nodes = graphs.nearest_nodes(graph, d_xy)
        oid_idx = origins.fields().lookupField(origin_id)
        did_idx = dests.fields().lookupField(dest_id) if dest_id else -1
        o_ids = [str(f.attributes()[oid_idx]) for f in o_feats]
        d_ids = [str(f.attributes()[did_idx]) if did_idx >= 0 else str(i)
                 for i, f in enumerate(d_feats)]

        fields = self.make_fields(("origin_id", STRING), ("dest_id", STRING),
                                  ("net_cost", DOUBLE), ("euclid_m", DOUBLE),
                                  ("detour", DOUBLE))
        sink, matrix_dest = self.parameterAsSink(
            parameters, self.MATRIX, context, fields, QgsWkbTypes.NoGeometry, crs)
        line_sink = line_dest = None
        if parameters.get(self.LINES) is not None:
            line_sink, line_dest = self.parameterAsSink(
                parameters, self.LINES, context, fields, QgsWkbTypes.LineString, crs)

        dist = paths.many_to_many(graph.indptr, graph.adj_node, graph.adj_cost,
                                  graph.num_nodes, o_nodes, cutoff=cutoff,
                                  cancel=feedback.isCanceled)
        total = len(o_ids)
        for i in range(total):
            if feedback.isCanceled():
                break
            feedback.setProgress(int(100.0 * i / max(1, total)))
            row = dist[i]
            for j in range(len(d_ids)):
                if same_layer and i == j:
                    continue
                d = row[d_nodes[j]]
                if not np.isfinite(d):
                    continue
                eu = float(np.hypot(o_xy[i, 0] - d_xy[j, 0], o_xy[i, 1] - d_xy[j, 1]))
                detour = float(d / eu) if eu > 0 else 0.0
                attrs = [o_ids[i], d_ids[j], float(d), eu, detour]
                f = QgsFeature(fields)
                f.setAttributes(attrs)
                sink.addFeature(f, QgsFeatureSink.FastInsert)
                if line_sink is not None:
                    lf = QgsFeature(fields)
                    lf.setAttributes(attrs)
                    lf.setGeometry(QgsGeometry.fromPolylineXY(
                        [QgsPointXY(*o_xy[i]), QgsPointXY(*d_xy[j])]))
                    line_sink.addFeature(lf, QgsFeatureSink.FastInsert)

        results = {self.MATRIX: matrix_dest}
        if line_dest is not None:
            results[self.LINES] = line_dest
        return results

    def createInstance(self):
        return ODCostMatrixAlgorithm()
