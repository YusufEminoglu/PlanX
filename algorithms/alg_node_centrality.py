# -*- coding: utf-8 -*-
"""Network Centrality: degree, closeness, straightness, betweenness."""
from __future__ import annotations

import random

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

from .base import DOUBLE, GROUP_CENTRALITY, INT, PlanXAlgorithm
from ..engine import centrality, graphs


class NetworkCentralityAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_CENTRALITY
    ICON = "tool_networkcentrality.png"
    NETWORK = "NETWORK"
    COST_FIELD = "COST_FIELD"
    RADIUS = "RADIUS"
    SAMPLES = "SAMPLES"
    NODES = "NODES"
    EDGES = "EDGES"

    def name(self):
        return "networkcentrality"

    def displayName(self):
        return self.tr("Network Centrality")

    def shortHelpString(self):
        return self.tr(
            "The full centrality family on the street network, computed by "
            "the embedded engine (Multiple Centrality Assessment, Porta et "
            "al. 2006):\n"
            "- degree: connections per junction\n"
            "- closeness: Wasserman-Faust corrected, plus harmonic closeness "
            "(robust to disconnected parts)\n"
            "- straightness: how close network paths are to straight lines\n"
            "- betweenness: exact Brandes (2001) on junctions AND street "
            "segments\n"
            "- eigenvector: influence of a junction given its neighbours' "
            "influence (Bonacich power iteration, max = 1)\n\n"
            "Radius limits the analysis to a local catchment (recommended on "
            "large networks; 0 = global). Betweenness sampling approximates "
            "from N random sources (0 = exact; use ~500 for metropolitan "
            "networks). Outputs junction points and the network with all "
            "scores attached.\n\n"
            "How to read the results\n"
            "- degree: 1 = cul-de-sac, 3-4 = ordinary junction. The share "
            "of degree-1 nodes measures how fragmented a layout is.\n"
            "- reach: junctions reachable within the radius, i.e. catchment "
            "size. Low-reach pockets expose enclaves and severance.\n"
            "- closeness / harm_clo: average nearness to everything else - "
            "the network's centre of gravity. High values are strong "
            "locations for daily services and public facilities; with a "
            "radius it reads as local accessibility. Prefer harm_clo "
            "whenever the network has disconnected parts.\n"
            "- straight: 1 = network paths are almost straight lines. High "
            "= a legible, easy-to-navigate grid; low = circuitous fabric "
            "(typical cul-de-sac layouts).\n"
            "- betweenness / betw_norm: how often shortest paths pass "
            "through the junction - where movement concentrates, so expect "
            "footfall and congestion pressure. betw_norm (0-1) is "
            "comparable across networks and scenarios.\n"
            "- eigen: high where neighbours are themselves well connected - "
            "highlights the dense, well-linked core.\n"
            "Streets output: betw_edge is the same flow logic per street - "
            "set line width by it and the main-street skeleton appears; "
            "clo_mean / str_mean carry junction accessibility onto streets "
            "for mapping.\n\n"
            "Using the results: style with quantile classes and read the "
            "top 5-10% as the structure that matters. High betweenness + "
            "high closeness = a centre under through-traffic pressure; "
            "high betweenness + low closeness = a pure movement corridor. "
            "Scores are potentials from network geometry alone - no land "
            "use or demand - and values near the map edge are biased low, "
            "so include network at least one radius beyond the study area."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("Street network (lines)"), [QgsProcessing.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterField(
            self.COST_FIELD, self.tr("Cost field on network (empty = length)"),
            parentLayerParameterName=self.NETWORK, optional=True,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.RADIUS, self.tr("Analysis radius in cost units (0 = global)"),
            QgsProcessingParameterNumber.Double, 0.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.SAMPLES, self.tr("Betweenness sample sources (0 = exact)"),
            QgsProcessingParameterNumber.Integer, 0, minValue=0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.NODES, self.tr("Junction centrality (points)")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.EDGES, self.tr("Street centrality (lines)")))

    def processAlgorithm(self, parameters, context, feedback):
        network = self.parameterAsSource(parameters, self.NETWORK, context)
        cost_field = self.parameterAsString(parameters, self.COST_FIELD, context)
        radius = self.parameterAsDouble(parameters, self.RADIUS, context) or None
        samples = self.parameterAsInt(parameters, self.SAMPLES, context)
        self.require_projected(network, "Street network")

        polylines, line_feats = self.source_polylines(network)
        costs = None
        if cost_field:
            idx = network.fields().lookupField(cost_field)
            costs = [float(f.attributes()[idx] or 0.0) for f in line_feats]
        graph = graphs.build_node_graph(polylines, costs=costs)
        n = graph.num_nodes
        feedback.pushInfo(self.tr(f"Graph: {n} nodes / {graph.num_edges} edges"))
        if radius is None and samples == 0 and n > 20000:
            feedback.pushWarning(self.tr(
                "Large network with global exact betweenness - this can take "
                "a long time. Consider a radius or sampling."))

        feedback.pushInfo(self.tr("Closeness / straightness pass..."))
        clo = centrality.closeness_straightness(
            graph.indptr, graph.adj_node, graph.adj_cost, n,
            node_xy=graph.node_xy, radius=radius,
            cancel=feedback.isCanceled,
            progress=lambda p: feedback.setProgress(int(50 * p)))

        feedback.pushInfo(self.tr("Betweenness pass (Brandes)..."))
        sources = None
        if 0 < samples < n:
            sources = random.Random(20260611).sample(range(n), samples)
        node_bc, edge_bc, _ = centrality.brandes_betweenness(
            graph.indptr, graph.adj_node, graph.adj_cost, n,
            adj_edge=graph.adj_edge, num_edges=graph.num_edges,
            w_prune=graph.adj_cost if radius is not None else None,
            radius=radius, sources=sources,
            cancel=feedback.isCanceled,
            progress=lambda p: feedback.setProgress(50 + int(50 * p)))
        # Pair-based convention: undirected Brandes counts each pair twice.
        node_bc /= 2.0
        edge_bc /= 2.0
        norm = (n - 1) * (n - 2) / 2.0 if n > 2 else 1.0

        feedback.pushInfo(self.tr("Eigenvector pass (power iteration)..."))
        eig = centrality.eigenvector(graph.indptr, graph.adj_node, n)

        crs = network.sourceCrs()
        degrees = graph.degrees()
        node_fields = self.make_fields(
            ("node_id", INT), ("degree", INT), ("reach", INT),
            ("closeness", DOUBLE), ("harm_clo", DOUBLE),
            ("straight", DOUBLE), ("betweenness", DOUBLE), ("betw_norm", DOUBLE),
            ("eigen", DOUBLE))
        node_sink, nodes_dest = self.parameterAsSink(
            parameters, self.NODES, context, node_fields, QgsWkbTypes.Point, crs)
        for i in range(n):
            f = QgsFeature(node_fields)
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*graph.node_xy[i])))
            f.setAttributes([i, int(degrees[i]), int(clo["reach"][i]),
                             float(clo["closeness"][i]), float(clo["harmonic"][i]),
                             float(clo["straightness"][i]), float(node_bc[i]),
                             float(node_bc[i] / norm), float(eig[i])])
            node_sink.addFeature(f, QgsFeatureSink.FastInsert)

        edge_fields = self.make_fields(
            ("betw_edge", DOUBLE), ("clo_mean", DOUBLE), ("str_mean", DOUBLE),
            base=network.fields())
        edge_sink, edges_dest = self.parameterAsSink(
            parameters, self.EDGES, context, edge_fields, QgsWkbTypes.LineString, crs)
        n_src = len(network.fields())
        for e in range(graph.num_edges):
            a, b = graph.edge_from[e], graph.edge_to[e]
            f = QgsFeature(edge_fields)
            f.setGeometry(QgsGeometry.fromPolylineXY(
                [QgsPointXY(x, y) for x, y in polylines[e]]))
            f.setAttributes(list(line_feats[e].attributes())[:n_src] + [
                float(edge_bc[e]),
                float((clo["closeness"][a] + clo["closeness"][b]) / 2.0),
                float((clo["straightness"][a] + clo["straightness"][b]) / 2.0)])
            edge_sink.addFeature(f, QgsFeatureSink.FastInsert)

        return {self.NODES: nodes_dest, self.EDGES: edges_dest}

    def createInstance(self):
        return NetworkCentralityAlgorithm()
