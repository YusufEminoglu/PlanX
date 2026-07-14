# -*- coding: utf-8 -*-
"""Nearest Facility Allocation with facility load summary."""
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


class NearestFacilityAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_NETWORK
    ICON = "tool_nearestfacility.png"
    NETWORK = "NETWORK"
    DEMAND = "DEMAND"
    FACILITIES = "FACILITIES"
    FACILITY_ID = "FACILITY_ID"
    COST_FIELD = "COST_FIELD"
    CUTOFF = "CUTOFF"
    OUTPUT = "OUTPUT"
    SPIDER = "SPIDER"
    ROUTES = "ROUTES"
    SUMMARY = "SUMMARY"

    def name(self):
        return "nearestfacility"

    def displayName(self):
        return self.tr("Nearest Facility Allocation")

    def shortHelpString(self):
        return self.tr(
            "Assigns every demand point (building, household, parcel "
            "centroid...) to its nearest facility over the street network "
            "and reports each facility's load.\n\n"
            "A single multi-source Dijkstra run resolves all assignments at "
            "once. Outputs: demand points with assigned facility and network "
            "cost; optional spider (allocation) lines; a per-facility summary "
            "with demand count and mean/max cost - the quickest way to spot "
            "over- and under-served catchments. A cost cutoff of 0 means "
            "unlimited.\n\n"
            "The optional cost field is a numeric attribute column of the "
            "network layer; assignment then minimises the SUM of that column "
            "along each path instead of metres, so it must be additive per "
            "segment - a travel time or weighted length, never a speed "
            "(convert first, e.g. time_min = length_m / (speed_kmh · 1000 / "
            "60)). net_cost and the cutoff inherit the column's units; NULL "
            "costs are read as 0 (free segments) and values must be zero or "
            "positive. Walking Slope Comfort's time_fwd_min column gives "
            "slope-aware catchments that price uphill walks honestly.\n\n"
            "How to read the results\n"
            "- Demand points: net_cost = the real walk/drive to the "
            "assigned facility (-1 and an empty facility = unreachable "
            "within the cutoff - map these first, they are the service "
            "gaps). Colour by 'facility' to see de-facto catchment "
            "boundaries, which rarely match administrative ones.\n"
            "- Summary: demand_n is each facility's load - a proxy for "
            "crowding when capacities are similar; max_cost is the worst "
            "trip anyone must make (the number standards care about); "
            "mean_cost compares overall convenience between facilities.\n"
            "- Spider lines: long bundles crossing other catchments "
            "indicate a missing facility or a network barrier.\n"
            "- Allocation routes show the real streets the trips use — "
            "bundle widths reveal which corridors carry each catchment; "
            "length_m vs net_cost differences flag time-weighted assignments.\n\n"
            "Using the results: demand_n far above the average marks where "
            "the next facility relieves the most load; rerun with a "
            "candidate site added and compare max_cost/demand_n shifts. "
            "For capacity-constrained assignment use Capacitated "
            "Allocation instead."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("Street network (lines)"), [QgsProcessing.SourceType.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.DEMAND, self.tr("Demand points"), [QgsProcessing.SourceType.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.FACILITIES, self.tr("Facilities"), [QgsProcessing.SourceType.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterField(
            self.FACILITY_ID, self.tr("Facility ID field"),
            parentLayerParameterName=self.FACILITIES))
        self.addParameter(QgsProcessingParameterField(
            self.COST_FIELD, self.tr("Cost field on network (empty = length)"),
            parentLayerParameterName=self.NETWORK, optional=True,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.CUTOFF, self.tr("Maximum cost (0 = unlimited)"),
            QgsProcessingParameterNumber.Type.Double, 0.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Allocated demand")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.SPIDER, self.tr("Allocation lines"), optional=True, createByDefault=False))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.ROUTES, self.tr("Allocation routes (network paths)"), optional=True, createByDefault=False))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.SUMMARY, self.tr("Facility load summary"), type=QgsProcessing.SourceType.TypeVector))

    def processAlgorithm(self, parameters, context, feedback):
        network = self.parameterAsSource(parameters, self.NETWORK, context)
        demand = self.parameterAsSource(parameters, self.DEMAND, context)
        facilities = self.parameterAsSource(parameters, self.FACILITIES, context)
        fac_id_name = self.parameterAsString(parameters, self.FACILITY_ID, context)
        cost_field = self.parameterAsString(parameters, self.COST_FIELD, context)
        cutoff = self.parameterAsDouble(parameters, self.CUTOFF, context) or None
        self.require_projected(network, "Street network")

        polylines, line_feats = self.source_polylines(network)
        costs = None
        if cost_field:
            idx = network.fields().lookupField(cost_field)
            costs = [float(f.attributes()[idx] or 0.0) for f in line_feats]
        graph = graphs.build_node_graph(polylines, costs=costs)
        crs = network.sourceCrs()
        d_xy, d_feats = self.source_points(demand, crs, context.transformContext())
        f_xy, f_feats = self.source_points(facilities, crs, context.transformContext())
        d_nodes = graphs.nearest_nodes(graph, d_xy)
        f_nodes = graphs.nearest_nodes(graph, f_xy)
        fid_idx = facilities.fields().lookupField(fac_id_name)
        f_ids = [str(f.attributes()[fid_idx]) for f in f_feats]

        # Several facilities can share a node: keep the first per node and
        # remap labels afterwards.
        unique_nodes, first_pos = np.unique(f_nodes, return_index=True)

        req_routes = parameters.get(self.ROUTES) is not None
        pred_node = pred_edge = None
        if req_routes:
            dist, label, pred_node, pred_edge = paths.multi_source_tree(
                graph.indptr, graph.adj_node, graph.adj_edge, graph.adj_cost,
                graph.num_nodes, unique_nodes, cutoff=cutoff
            )
        else:
            dist, label = paths.multi_source(
                graph.indptr, graph.adj_node, graph.adj_cost,
                graph.num_nodes, unique_nodes, cutoff=cutoff
            )

        out_fields = self.make_fields(("facility", STRING), ("net_cost", DOUBLE),
                                      base=demand.fields())
        sink, out_dest = self.parameterAsSink(
            parameters, self.OUTPUT, context, out_fields,
            QgsWkbTypes.Type.Point, crs)
        spider_sink = spider_dest = None
        if parameters.get(self.SPIDER) is not None:
            spider_sink, spider_dest = self.parameterAsSink(
                parameters, self.SPIDER, context,
                self.make_fields(("facility", STRING), ("net_cost", DOUBLE)),
                QgsWkbTypes.Type.LineString, crs)

        routes_sink = routes_dest = None
        if req_routes:
            routes_sink, routes_dest = self.parameterAsSink(
                parameters, self.ROUTES, context,
                self.make_fields(("demand_i", INT), ("facility", STRING),
                                 ("net_cost", DOUBLE), ("length_m", DOUBLE)),
                QgsWkbTypes.Type.LineString, crs)

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

        n_dem_fields = len(demand.fields())
        loads = {}
        n_routes = 0
        for i, feat in enumerate(d_feats):
            if feedback.isCanceled():
                break
            node = d_nodes[i]
            d = dist[node]
            lab = label[node]
            fac = ""
            cost_val = -1.0
            if lab >= 0 and np.isfinite(d):
                fac = f_ids[first_pos[lab]]
                cost_val = float(d)
                stat = loads.setdefault(fac, [0, 0.0, 0.0, first_pos[lab]])
                stat[0] += 1
                stat[1] += cost_val
                stat[2] = max(stat[2], cost_val)
            out = QgsFeature(out_fields)
            out.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*d_xy[i])))
            out.setAttributes(list(feat.attributes())[:n_dem_fields] + [fac, cost_val])
            sink.addFeature(out, QgsFeatureSink.Flag.FastInsert)
            if spider_sink is not None and fac:
                j = first_pos[lab]
                lf = QgsFeature()
                lf.setGeometry(QgsGeometry.fromPolylineXY(
                    [QgsPointXY(*d_xy[i]), QgsPointXY(*f_xy[j])]))
                lf.setAttributes([fac, cost_val])
                spider_sink.addFeature(lf, QgsFeatureSink.Flag.FastInsert)

            if routes_sink is not None and fac:
                nodes, edges = paths.path_to_root(pred_node, pred_edge, node)
                if edges:
                    length_val = float(np.sum(graph.edge_len[edges]))
                    rf = QgsFeature()
                    rf.setGeometry(route_geometry(nodes, edges))
                    rf.setAttributes([i, fac, cost_val, length_val])
                    routes_sink.addFeature(rf, QgsFeatureSink.Flag.FastInsert)
                    n_routes += 1

        if routes_sink is not None:
            feedback.pushInfo(self.tr(f"Created {n_routes} allocation route(s)."))

        sum_fields = self.make_fields(("facility", STRING), ("demand_n", INT),
                                      ("mean_cost", DOUBLE), ("max_cost", DOUBLE))
        sum_sink, sum_dest = self.parameterAsSink(
            parameters, self.SUMMARY, context, sum_fields, QgsWkbTypes.Type.NoGeometry, crs)
        for fac in f_ids:
            stat = loads.get(fac)
            f = QgsFeature(sum_fields)
            if stat:
                f.setAttributes([fac, stat[0], stat[1] / stat[0], stat[2]])
            else:
                f.setAttributes([fac, 0, 0.0, 0.0])
            sum_sink.addFeature(f, QgsFeatureSink.Flag.FastInsert)
        feedback.pushInfo(self.tr(
            f"Allocated {sum(s[0] for s in loads.values())} of {len(d_feats)} demand points."))

        results = {self.OUTPUT: out_dest, self.SUMMARY: sum_dest}
        if spider_dest is not None:
            results[self.SPIDER] = spider_dest
        if routes_dest is not None:
            results[self.ROUTES] = routes_dest
        return results

    def createInstance(self):
        return NearestFacilityAlgorithm()
