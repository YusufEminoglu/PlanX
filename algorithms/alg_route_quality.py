# -*- coding: utf-8 -*-
"""Pedestrian Route Quality: quality-weighted routes vs the plain shortest."""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsFeature,
    QgsFeatureSink,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_WALK, INT, PlanXAlgorithm
from ..engine import graphs, paths


class RouteQualityAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_WALK
    ICON = "tool_routequality.png"
    NETWORK = "NETWORK"
    SCORE_FIELD = "SCORE_FIELD"
    ORIGINS = "ORIGINS"
    DESTINATIONS = "DESTINATIONS"
    PAIRING = "PAIRING"
    PENALTY = "PENALTY"
    LOW_THRESHOLD = "LOW_THRESHOLD"
    OUT_ROUTES = "OUT_ROUTES"

    def name(self):
        return "routequality"

    def displayName(self):
        return self.tr("Pedestrian Route Quality")

    def shortHelpString(self):
        return self.tr(
            "Routes pedestrians over QUALITY-WEIGHTED streets and reports "
            "what the walk is actually like - the follow-up to the "
            "Walkability Audit: feed its output as the network and the "
            "router prefers pleasant streets, accepting a detour when the "
            "direct street scores badly.\n\n"
            "Each segment's routing weight is length x (1 + penalty x "
            "(100 - walk score) / 100): with penalty 1, a score-0 street "
            "counts double its length; penalty 0 reproduces the plain "
            "shortest path. Segments without a score count as neutral "
            "(100).\n\n"
            "For every origin-destination pair the tool returns the "
            "quality-optimal route with:\n"
            "- length_m and the plain shortest length (and the detour "
            "ratio between them - the price of quality);\n"
            "- the length-weighted MEAN WALK SCORE along the route;\n"
            "- the share of the route on LOW-scoring segments (below the "
            "threshold);\n"
            "- the number of segments traversed.\n\n"
            "Pairing: each origin to its nearest destination (by the "
            "quality-weighted cost) or all pairs. Use a projected CRS."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK,
            self.tr("Street network (ideally the Walkability output)"),
            [QgsProcessing.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterField(
            self.SCORE_FIELD,
            self.tr("Walk-score field 0-100 (empty = all neutral)"),
            parentLayerParameterName=self.NETWORK, optional=True,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.ORIGINS, self.tr("Origins"),
            [QgsProcessing.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.DESTINATIONS, self.tr("Destinations"),
            [QgsProcessing.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterEnum(
            self.PAIRING, self.tr("Pairing"),
            ["Nearest destination", "All pairs"], defaultValue=0))
        self.addParameter(QgsProcessingParameterNumber(
            self.PENALTY,
            self.tr("Quality penalty (0 = plain shortest path)"),
            QgsProcessingParameterNumber.Double, 1.0, minValue=0.0,
            maxValue=10.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.LOW_THRESHOLD,
            self.tr("Low-quality threshold (walk score)"),
            QgsProcessingParameterNumber.Double, 50.0, minValue=0.0,
            maxValue=100.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_ROUTES, self.tr("Quality routes")))

    def processAlgorithm(self, parameters, context, feedback):
        network = self.parameterAsSource(parameters, self.NETWORK, context)
        score_field = self.parameterAsString(parameters, self.SCORE_FIELD, context)
        origins = self.parameterAsSource(parameters, self.ORIGINS, context)
        dests = self.parameterAsSource(parameters, self.DESTINATIONS, context)
        pairing = self.parameterAsEnum(parameters, self.PAIRING, context)
        penalty = self.parameterAsDouble(parameters, self.PENALTY, context)
        low_thr = self.parameterAsDouble(parameters, self.LOW_THRESHOLD, context)
        self.require_projected(network, "Street network")

        polylines, line_feats = self.source_polylines(network)
        graph = graphs.build_node_graph(polylines)
        n_edges = graph.num_edges

        scores = np.full(n_edges, 100.0)
        missing = 0
        if score_field:
            idx = network.fields().lookupField(score_field)
            for e in range(n_edges):
                try:
                    scores[e] = float(line_feats[e].attributes()[idx])
                except (TypeError, ValueError):
                    missing += 1
            scores = np.clip(scores, 0.0, 100.0)
            if missing:
                feedback.pushWarning(self.tr(
                    f"{missing} segment(s) without a score - counted as "
                    "neutral (100)."))

        quality_edge = graph.edge_len * (1.0 + penalty * (100.0 - scores) / 100.0)
        w_quality = quality_edge[graph.adj_edge]

        crs = network.sourceCrs()
        xform = context.transformContext()
        o_xy, o_feats = self.source_points(origins, crs, xform)
        d_xy, d_feats = self.source_points(dests, crs, xform)
        o_nodes = graphs.nearest_nodes(graph, o_xy)
        d_nodes = graphs.nearest_nodes(graph, d_xy)

        fields = self.make_fields(
            ("origin", INT), ("dest", INT), ("length_m", DOUBLE),
            ("shortest_m", DOUBLE), ("detour", DOUBLE), ("mean_score", DOUBLE),
            ("low_share", DOUBLE), ("n_edges", INT))
        sink, dest_id = self.parameterAsSink(
            parameters, self.OUT_ROUTES, context, fields,
            QgsWkbTypes.LineString, crs)

        def route_geometry(nodes, edges):
            pts = []
            cur_xy = graph.node_xy[nodes[0]]
            for eid in edges:
                coords = polylines[eid]
                d_start = float(np.hypot(*(coords[0] - cur_xy)))
                d_end = float(np.hypot(*(coords[-1] - cur_xy)))
                ordered = coords if d_start <= d_end else coords[::-1]
                start = 1 if pts else 0
                pts.extend(QgsPointXY(x, y) for x, y in ordered[start:])
                cur_xy = np.asarray([ordered[-1, 0], ordered[-1, 1]])
            return QgsGeometry.fromPolylineXY(pts)

        n_routes = unreachable = 0
        mean_scores = []
        for oi in range(len(o_nodes)):
            if feedback.isCanceled():
                break
            src = int(o_nodes[oi])
            dist_q, pred_n, pred_e = paths.shortest_path_tree(
                graph.indptr, graph.adj_node, graph.adj_edge, w_quality,
                graph.num_nodes, src)
            dist_p = paths.many_to_many(
                graph.indptr, graph.adj_node, graph.adj_cost,
                graph.num_nodes, np.asarray([src]))[0]
            if pairing == 0:
                reach = [di for di in range(len(d_nodes))
                         if np.isfinite(dist_q[d_nodes[di]])]
                targets = ([min(reach, key=lambda di: dist_q[d_nodes[di]])]
                           if reach else [])
                if not targets:
                    unreachable += 1
            else:
                targets = range(len(d_nodes))
            for di in targets:
                tgt = int(d_nodes[di])
                if not np.isfinite(dist_q[tgt]):
                    unreachable += 1
                    continue
                if tgt == src:
                    continue
                nodes, edges = paths.reconstruct_path(pred_n, pred_e, src, tgt)
                if not edges:
                    continue
                eids = np.asarray(edges, dtype=np.int64)
                lens = graph.edge_len[eids]
                length = float(lens.sum())
                mean_score = float((lens * scores[eids]).sum() / length)
                low_share = float(lens[scores[eids] < low_thr].sum() / length)
                shortest = float(dist_p[tgt])
                out = QgsFeature(fields)
                out.setGeometry(route_geometry(nodes, edges))
                out.setAttributes([
                    oi + 1, di + 1, round(length, 2), round(shortest, 2),
                    round(length / shortest, 4) if shortest > 0 else 1.0,
                    round(mean_score, 2), round(low_share, 4), len(edges)])
                sink.addFeature(out, QgsFeatureSink.FastInsert)
                n_routes += 1
                mean_scores.append(mean_score)
            feedback.setProgress(100.0 * (oi + 1) / len(o_nodes))

        if not n_routes:
            raise QgsProcessingException(
                "No route could be built - are origins and destinations on "
                "(or near) the network?")
        if unreachable:
            feedback.pushWarning(self.tr(
                f"{unreachable} pair(s) unreachable on the network."))
        feedback.pushInfo(self.tr(
            f"{n_routes} route(s); mean walk score along routes "
            f"{float(np.mean(mean_scores)):.1f} (penalty {penalty:g})."))
        return {self.OUT_ROUTES: dest_id}

    def createInstance(self):
        return RouteQualityAlgorithm()
