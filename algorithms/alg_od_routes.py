# -*- coding: utf-8 -*-
"""OD Routes: origin-destination shortest path routing with real street geometries."""
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

from .base import DOUBLE, GROUP_NETWORK, INT, PlanXAlgorithm, STRING
from ..engine import graphs, paths


class ODRoutesAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_NETWORK
    ICON = "tool_odroutes.png"
    NETWORK = "NETWORK"
    ORIGINS = "ORIGINS"
    ORIGIN_ID = "ORIGIN_ID"
    DESTINATIONS = "DESTINATIONS"
    DEST_ID = "DEST_ID"
    COST_FIELD = "COST_FIELD"
    CUTOFF = "CUTOFF"
    K_NEAREST = "K_NEAREST"
    OUT_ROUTES = "OUT_ROUTES"
    OUT_LINES = "OUT_LINES"

    def name(self):
        return "odroutes"

    def displayName(self):
        return self.tr("OD Routes (Shortest Paths)")

    def shortHelpString(self):
        return self.tr(
            "Computes shortest-path routes over the street network from origins "
            "to destinations. For each pair, it reconstructs the actual streets "
            "traversed and optional straight desire lines.\n\n"
            "This serves as the embedded-engine alternative to the QNEAT3 OD "
            "workflow. It offers k-nearest and cost cutoff controls. "
            "Points snap to their nearest network node. A cost cutoff of 0 means "
            "unlimited.\n\n"
            "Cost model: with the cost field empty, every segment costs its "
            "geometric length, so net_cost is metres and 'nearest' means "
            "physically shortest. Selecting a numeric attribute column of the "
            "network layer overrides this: the router minimises the SUM of that "
            "column's values along the route, so the column must hold an "
            "additive per-segment quantity - a travel time, a weighted length, "
            "a generalised cost - never a speed. Convert speeds first, e.g. "
            "time_min = length_m / (speed_kmh · 1000 / 60) in the Field "
            "Calculator. net_cost, the k-nearest ranking and the cutoff all "
            "inherit the column's units: a minutes column with cutoff 15 keeps "
            "only pairs within 15 minutes, and k = 1 returns the FASTEST "
            "destination, not the closest. Values must be zero or positive and "
            "complete - NULL costs are read as 0, which makes those segments "
            "free and pulls every route towards them. Walking Slope Comfort's "
            "time_fwd_min column is a ready-made cost field for slope-aware "
            "routing.\n\n"
            "How to read the results\n"
            "- net_cost is the operative distance or travel time - metres with "
            "the default length cost, the cost field's units otherwise.\n"
            "- detour (network cost / Euclidean distance) indicates barrier effects: "
            "values >= ~1.4 flag major detours forced by superblocks, railways, or rivers. "
            "Read it as a pure ratio only with the default length cost; with a time "
            "cost it mixes units (time / metre) and only orders pairs.\n"
            "- ROUTE BUNDLES show which streets carry the flows. Overlaying many routes "
            "reveals the de-facto corridors (the demand-side complement to betweenness centrality).\n"
            "- Straight desire lines represent the same OD table drawn as direct glyphs.\n\n"
            "Using the results\n"
            "- Identify key corridors for sidewalk, cycle, or transit investment.\n"
            "- Overlay route flows with Cycling Stress or Walkability Audit scores to target safety improvements.\n"
            "- Setting k=1 yields assignment-like nearest-service routes.\n"
            "- Feed net_cost values into Gravity or Mode Split models."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("Street network (lines)"), [QgsProcessing.SourceType.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.ORIGINS, self.tr("Origins"), [QgsProcessing.SourceType.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterField(
            self.ORIGIN_ID, self.tr("Origin ID field"), parentLayerParameterName=self.ORIGINS))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.DESTINATIONS, self.tr("Destinations (empty = origins)"),
            [QgsProcessing.SourceType.TypeVectorAnyGeometry], optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.DEST_ID, self.tr("Destination ID field"),
            parentLayerParameterName=self.DESTINATIONS, optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.COST_FIELD, self.tr("Cost field on network (empty = length)"),
            parentLayerParameterName=self.NETWORK, optional=True,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.CUTOFF, self.tr("Maximum cost (0 = unlimited)"),
            QgsProcessingParameterNumber.Type.Double, 0.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.K_NEAREST, self.tr("Keep only the k nearest destinations per origin (0 = all)"),
            QgsProcessingParameterNumber.Type.Integer, 0, minValue=0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_ROUTES, self.tr("OD routes")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_LINES, self.tr("Desire lines (straight)"), optional=True,
            createByDefault=False))

    def processAlgorithm(self, parameters, context, feedback):
        network = self.parameterAsSource(parameters, self.NETWORK, context)
        origins = self.parameterAsSource(parameters, self.ORIGINS, context)
        dests = self.parameterAsSource(parameters, self.DESTINATIONS, context)
        origin_id = self.parameterAsString(parameters, self.ORIGIN_ID, context)
        dest_id = self.parameterAsString(parameters, self.DEST_ID, context)
        cost_field = self.parameterAsString(parameters, self.COST_FIELD, context)
        cutoff = self.parameterAsDouble(parameters, self.CUTOFF, context) or None
        k_nearest = self.parameterAsInt(parameters, self.K_NEAREST, context)
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
            f"Graph: {graph.num_nodes} nodes / {graph.num_edges} edges. "
            f"Routing with embedded Dijkstra engine."))

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

        if len(o_ids) * len(d_ids) > 250000 and cutoff is None and k_nearest == 0:
            feedback.pushWarning(self.tr("This will be huge — set a cutoff or k."))

        fields = self.make_fields(
            ("origin_id", STRING), ("dest_id", STRING), ("k", INT),
            ("net_cost", DOUBLE), ("euclid_m", DOUBLE), ("detour", DOUBLE),
            ("n_edges", INT)
        )

        sink, routes_dest = self.parameterAsSink(
            parameters, self.OUT_ROUTES, context, fields, QgsWkbTypes.Type.LineString, crs)
        line_sink = line_dest = None
        if parameters.get(self.OUT_LINES) is not None:
            line_sink, line_dest = self.parameterAsSink(
                parameters, self.OUT_LINES, context, fields, QgsWkbTypes.Type.LineString, crs)

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

        n_routes = n_lines = 0
        total = len(o_ids)
        for i in range(total):
            if feedback.isCanceled():
                break
            feedback.setProgress(int(100.0 * i / max(1, total)))
            src = int(o_nodes[i])
            dist_d, pred_n, pred_e = paths.shortest_path_tree(
                graph.indptr, graph.adj_node, graph.adj_edge, graph.adj_cost,
                graph.num_nodes, src, cutoff=cutoff
            )

            candidates = []
            for j in range(len(d_ids)):
                if same_layer and i == j:
                    continue
                tgt = int(d_nodes[j])
                c = dist_d[tgt]
                if np.isfinite(c):
                    candidates.append((c, j, tgt))

            # sorted is stable, so tie-breaks keep the destination-index order
            sorted_candidates = sorted(candidates, key=lambda x: x[0])
            if k_nearest > 0:
                sorted_candidates = sorted_candidates[:k_nearest]

            for rank, (c, j, tgt) in enumerate(sorted_candidates, 1):
                if src == tgt:
                    continue
                nodes, edges = paths.reconstruct_path(pred_n, pred_e, src, tgt)
                if not edges:
                    continue

                eu = float(np.hypot(o_xy[i, 0] - d_xy[j, 0], o_xy[i, 1] - d_xy[j, 1]))
                detour = float(c / eu) if eu > 0 else 0.0

                attrs = [o_ids[i], d_ids[j], rank, float(c), eu, detour, len(edges)]

                rf = QgsFeature(fields)
                rf.setGeometry(route_geometry(nodes, edges))
                rf.setAttributes(attrs)
                sink.addFeature(rf, QgsFeatureSink.Flag.FastInsert)
                n_routes += 1

                if line_sink is not None:
                    lf = QgsFeature(fields)
                    lf.setGeometry(QgsGeometry.fromPolylineXY(
                        [QgsPointXY(*o_xy[i]), QgsPointXY(*d_xy[j])]))
                    lf.setAttributes(attrs)
                    line_sink.addFeature(lf, QgsFeatureSink.Flag.FastInsert)
                    n_lines += 1

        feedback.pushInfo(self.tr(f"Created {n_routes} route(s)."))
        if line_sink is not None:
            feedback.pushInfo(self.tr(f"Created {n_lines} desire line(s)."))

        results = {self.OUT_ROUTES: routes_dest}
        if line_dest is not None:
            results[self.OUT_LINES] = line_dest
        return results

    def createInstance(self):
        return ODRoutesAlgorithm()
