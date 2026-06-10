# -*- coding: utf-8 -*-
"""Service Areas (Isochrones): multi-facility network cost bands."""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsFeature,
    QgsFeatureSink,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_NETWORK, INT, PlanXAlgorithm
from ..engine import graphs, paths


def parse_breaks(text: str):
    vals = sorted({float(t) for t in text.replace(";", ",").split(",") if t.strip()})
    if not vals or any(v <= 0 for v in vals):
        raise QgsProcessingException(
            "Breaks must be a comma-separated list of positive numbers, e.g. 250, 500, 1000")
    return vals


class ServiceAreasAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_NETWORK
    NETWORK = "NETWORK"
    FACILITIES = "FACILITIES"
    COST_FIELD = "COST_FIELD"
    BREAKS = "BREAKS"
    BUFFER = "BUFFER"
    EDGES = "EDGES"
    AREAS = "AREAS"

    def name(self):
        return "serviceareas"

    def displayName(self):
        return self.tr("Service Areas (Isochrones)")

    def shortHelpString(self):
        return self.tr(
            "Network service areas around one or more facilities, computed "
            "with the embedded multi-source Dijkstra engine (every facility "
            "expands simultaneously; each street gets the cost from its "
            "*nearest* facility).\n\n"
            "Outputs: (1) the reached street segments with their cost and "
            "band, (2) dissolved band polygons (street buffer union) ready "
            "for cartography. Cost defaults to length in map units; pass a "
            "numeric field (e.g. minutes) to use travel time, and express "
            "the breaks in the same unit."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("Street network (lines)"), [QgsProcessing.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.FACILITIES, self.tr("Facilities"), [QgsProcessing.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterField(
            self.COST_FIELD, self.tr("Cost field on network (empty = length)"),
            parentLayerParameterName=self.NETWORK, optional=True,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterString(
            self.BREAKS, self.tr("Cost breaks (comma separated)"), "250, 500, 1000"))
        self.addParameter(QgsProcessingParameterNumber(
            self.BUFFER, self.tr("Polygon buffer width (map units)"),
            QgsProcessingParameterNumber.Double, 30.0, minValue=0.1))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.EDGES, self.tr("Service area edges")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.AREAS, self.tr("Service area polygons")))

    def processAlgorithm(self, parameters, context, feedback):
        network = self.parameterAsSource(parameters, self.NETWORK, context)
        facilities = self.parameterAsSource(parameters, self.FACILITIES, context)
        cost_field = self.parameterAsString(parameters, self.COST_FIELD, context)
        breaks = parse_breaks(self.parameterAsString(parameters, self.BREAKS, context))
        buffer_w = self.parameterAsDouble(parameters, self.BUFFER, context)
        self.require_projected(network, "Street network")

        polylines, line_feats = self.source_polylines(network)
        costs = None
        if cost_field:
            idx = network.fields().lookupField(cost_field)
            costs = [float(f.attributes()[idx] or 0.0) for f in line_feats]
        graph = graphs.build_node_graph(polylines, costs=costs)
        crs = network.sourceCrs()
        f_xy, _ = self.source_points(facilities, crs, context.transformContext())
        f_nodes = np.unique(graphs.nearest_nodes(graph, f_xy))
        feedback.pushInfo(self.tr(
            f"Graph: {graph.num_nodes} nodes / {graph.num_edges} edges; "
            f"{len(f_nodes)} facility nodes"))

        dist, _ = paths.multi_source(graph.indptr, graph.adj_node, graph.adj_cost,
                                     graph.num_nodes, f_nodes, cutoff=breaks[-1])

        # Edge cost = cost of cheapest endpoint (entry cost into the edge).
        edge_cost = np.minimum(dist[graph.edge_from], dist[graph.edge_to])
        band_of = np.full(graph.num_edges, -1, dtype=np.int64)
        for bi in range(len(breaks) - 1, -1, -1):
            band_of[edge_cost <= breaks[bi]] = bi

        edge_fields = self.make_fields(("cost", DOUBLE), ("band", DOUBLE),
                                       base=network.fields())
        edge_sink, edges_dest = self.parameterAsSink(
            parameters, self.EDGES, context, edge_fields,
            QgsWkbTypes.LineString, crs)
        n_src_fields = len(network.fields())
        geoms_per_band = {bi: [] for bi in range(len(breaks))}
        reached = 0
        for e in range(graph.num_edges):
            bi = band_of[e]
            if bi < 0:
                continue
            reached += 1
            geom = QgsGeometry.fromPolylineXY(
                [QgsPointXY(x, y) for x, y in polylines[e]])
            out = QgsFeature(edge_fields)
            out.setGeometry(geom)
            attrs = list(line_feats[e].attributes())[:n_src_fields]
            out.setAttributes(attrs + [float(edge_cost[e]), float(breaks[bi])])
            edge_sink.addFeature(out, QgsFeatureSink.FastInsert)
            geoms_per_band[bi].append(geom)
        feedback.pushInfo(self.tr(f"Reached {reached} of {graph.num_edges} segments."))

        area_fields = self.make_fields(("band", DOUBLE), ("rank", INT))
        area_sink, areas_dest = self.parameterAsSink(
            parameters, self.AREAS, context, area_fields,
            QgsWkbTypes.MultiPolygon, crs)
        cumulative = []
        for bi, brk in enumerate(breaks):
            if feedback.isCanceled():
                break
            cumulative.extend(geoms_per_band[bi])
            if not cumulative:
                continue
            feedback.pushInfo(self.tr(f"Dissolving band <= {brk:g} ({len(cumulative)} edges)..."))
            buffered = [g.buffer(buffer_w, 8) for g in cumulative]
            merged = QgsGeometry.unaryUnion(buffered)
            f = QgsFeature(area_fields)
            f.setGeometry(merged)
            f.setAttributes([float(brk), bi + 1])
            area_sink.addFeature(f, QgsFeatureSink.FastInsert)

        return {self.EDGES: edges_dest, self.AREAS: areas_dest}

    def createInstance(self):
        return ServiceAreasAlgorithm()
