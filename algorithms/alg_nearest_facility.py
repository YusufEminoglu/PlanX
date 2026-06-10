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
    NETWORK = "NETWORK"
    DEMAND = "DEMAND"
    FACILITIES = "FACILITIES"
    FACILITY_ID = "FACILITY_ID"
    COST_FIELD = "COST_FIELD"
    CUTOFF = "CUTOFF"
    OUTPUT = "OUTPUT"
    SPIDER = "SPIDER"
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
            "unlimited."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("Street network (lines)"), [QgsProcessing.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.DEMAND, self.tr("Demand points"), [QgsProcessing.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.FACILITIES, self.tr("Facilities"), [QgsProcessing.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterField(
            self.FACILITY_ID, self.tr("Facility ID field"),
            parentLayerParameterName=self.FACILITIES))
        self.addParameter(QgsProcessingParameterField(
            self.COST_FIELD, self.tr("Cost field on network (empty = length)"),
            parentLayerParameterName=self.NETWORK, optional=True,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.CUTOFF, self.tr("Maximum cost (0 = unlimited)"),
            QgsProcessingParameterNumber.Double, 0.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Allocated demand")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.SPIDER, self.tr("Allocation lines"), optional=True, createByDefault=False))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.SUMMARY, self.tr("Facility load summary"), type=QgsProcessing.TypeVector))

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
        dist, label = paths.multi_source(graph.indptr, graph.adj_node, graph.adj_cost,
                                         graph.num_nodes, unique_nodes, cutoff=cutoff)

        out_fields = self.make_fields(("facility", STRING), ("net_cost", DOUBLE),
                                      base=demand.fields())
        sink, out_dest = self.parameterAsSink(
            parameters, self.OUTPUT, context, out_fields,
            QgsWkbTypes.Point, crs)
        spider_sink = spider_dest = None
        if parameters.get(self.SPIDER) is not None:
            spider_sink, spider_dest = self.parameterAsSink(
                parameters, self.SPIDER, context,
                self.make_fields(("facility", STRING), ("net_cost", DOUBLE)),
                QgsWkbTypes.LineString, crs)

        n_dem_fields = len(demand.fields())
        loads = {}
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
            sink.addFeature(out, QgsFeatureSink.FastInsert)
            if spider_sink is not None and fac:
                j = first_pos[lab]
                lf = QgsFeature()
                lf.setGeometry(QgsGeometry.fromPolylineXY(
                    [QgsPointXY(*d_xy[i]), QgsPointXY(*f_xy[j])]))
                lf.setAttributes([fac, cost_val])
                spider_sink.addFeature(lf, QgsFeatureSink.FastInsert)

        sum_fields = self.make_fields(("facility", STRING), ("demand_n", INT),
                                      ("mean_cost", DOUBLE), ("max_cost", DOUBLE))
        sum_sink, sum_dest = self.parameterAsSink(
            parameters, self.SUMMARY, context, sum_fields, QgsWkbTypes.NoGeometry, crs)
        for fac in f_ids:
            stat = loads.get(fac)
            f = QgsFeature(sum_fields)
            if stat:
                f.setAttributes([fac, stat[0], stat[1] / stat[0], stat[2]])
            else:
                f.setAttributes([fac, 0, 0.0, 0.0])
            sum_sink.addFeature(f, QgsFeatureSink.FastInsert)
        feedback.pushInfo(self.tr(
            f"Allocated {sum(s[0] for s in loads.values())} of {len(d_feats)} demand points."))

        results = {self.OUTPUT: out_dest, self.SUMMARY: sum_dest}
        if spider_dest is not None:
            results[self.SPIDER] = spider_dest
        return results

    def createInstance(self):
        return NearestFacilityAlgorithm()
