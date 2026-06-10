# -*- coding: utf-8 -*-
"""Multi-Amenity Access Score: the 15-minute-city composite indicator."""
from __future__ import annotations

import re

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
    QgsProcessingParameterMultipleLayers,
    QgsProcessingParameterNumber,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_ACCESS, INT, PlanXAlgorithm
from ..engine import graphs, paths


def field_token(name: str, used: set) -> str:
    token = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")[:8] or "cat"
    final = f"t_{token}"
    i = 1
    while final.lower() in used:
        i += 1
        final = f"t_{token}{i}"
    used.add(final.lower())
    return final


class MultiAmenityAccessAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_ACCESS
    ORIGINS = "ORIGINS"
    NETWORK = "NETWORK"
    AMENITIES = "AMENITIES"
    SPEED = "SPEED"
    THRESHOLD = "THRESHOLD"
    OUTPUT = "OUTPUT"

    def name(self):
        return "accessscore"

    def displayName(self):
        return self.tr("Multi-Amenity Access Score (15-Minute City)")

    def shortHelpString(self):
        return self.tr(
            "Scores every origin (building, address point, parcel...) on "
            "walkable access to amenities - the 15-minute-city indicator, "
            "computed on the real street network by the embedded engine.\n\n"
            "Pick any number of amenity layers (schools, health, parks, "
            "shops...). Each layer is one category: the tool finds the "
            "walking time to the nearest amenity of every category (one "
            "multi-source Dijkstra per category) and reports:\n"
            "- t_<category>: minutes to the nearest amenity (-1 = beyond "
            "2x threshold)\n"
            "- n_reach: categories reachable within the threshold\n"
            "- score: 0-100 share of categories within the threshold\n\n"
            "Defaults: 4.8 km/h walking speed, 15-minute threshold. All "
            "layers are snapped to the same network; use a projected CRS."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.ORIGINS, self.tr("Origins"), [QgsProcessing.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("Street network (lines)"), [QgsProcessing.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterMultipleLayers(
            self.AMENITIES, self.tr("Amenity layers (one per category)"),
            QgsProcessing.TypeVectorAnyGeometry))
        self.addParameter(QgsProcessingParameterNumber(
            self.SPEED, self.tr("Walking speed (km/h)"),
            QgsProcessingParameterNumber.Double, 4.8, minValue=0.5))
        self.addParameter(QgsProcessingParameterNumber(
            self.THRESHOLD, self.tr("Time threshold (minutes)"),
            QgsProcessingParameterNumber.Double, 15.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Access scores")))

    def processAlgorithm(self, parameters, context, feedback):
        origins = self.parameterAsSource(parameters, self.ORIGINS, context)
        network = self.parameterAsSource(parameters, self.NETWORK, context)
        amenity_layers = self.parameterAsLayerList(parameters, self.AMENITIES, context)
        speed = self.parameterAsDouble(parameters, self.SPEED, context)
        threshold = self.parameterAsDouble(parameters, self.THRESHOLD, context)
        self.require_projected(network, "Street network")
        if not amenity_layers:
            raise QgsProcessingException("Select at least one amenity layer.")

        polylines, _ = self.source_polylines(network)
        graph = graphs.build_node_graph(polylines)
        crs = network.sourceCrs()
        o_xy, o_feats = self.source_points(origins, crs, context.transformContext())
        o_nodes = graphs.nearest_nodes(graph, o_xy)

        meters_per_min = speed * 1000.0 / 60.0
        cutoff_m = threshold * 2.0 * meters_per_min  # report up to 2x threshold

        used = set()
        tokens = []
        times = np.full((len(amenity_layers), len(o_feats)), -1.0)
        for li, layer in enumerate(amenity_layers):
            if feedback.isCanceled():
                break
            tokens.append(field_token(layer.name(), used))
            a_xy, _ = self.source_points(layer, crs, context.transformContext())
            a_nodes = np.unique(graphs.nearest_nodes(graph, a_xy))
            feedback.pushInfo(self.tr(
                f"Category '{layer.name()}': {len(a_xy)} amenities"))
            dist, _ = paths.multi_source(graph.indptr, graph.adj_node, graph.adj_cost,
                                         graph.num_nodes, a_nodes, cutoff=cutoff_m)
            node_min = dist[o_nodes]
            ok = np.isfinite(node_min)
            times[li, ok] = node_min[ok] / meters_per_min
            feedback.setProgress(int(100.0 * (li + 1) / len(amenity_layers)))

        specs = [(t, DOUBLE) for t in tokens] + [("n_reach", INT), ("score", DOUBLE)]
        fields = self.make_fields(*specs, base=origins.fields())
        sink, dest = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields, QgsWkbTypes.Point, crs)

        n_src = len(origins.fields())
        n_cat = len(amenity_layers)
        for i, feat in enumerate(o_feats):
            if feedback.isCanceled():
                break
            col = times[:, i]
            reached = int(((col >= 0) & (col <= threshold)).sum())
            out = QgsFeature(fields)
            out.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*o_xy[i])))
            out.setAttributes(
                list(feat.attributes())[:n_src]
                + [round(float(v), 2) if v >= 0 else -1.0 for v in col]
                + [reached, round(100.0 * reached / n_cat, 1)])
            sink.addFeature(out, QgsFeatureSink.FastInsert)
        return {self.OUTPUT: dest}

    def createInstance(self):
        return MultiAmenityAccessAlgorithm()
