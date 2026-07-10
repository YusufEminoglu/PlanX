# -*- coding: utf-8 -*-
"""Prepare Network: node a raw street layer for graph analysis."""
from __future__ import annotations

import processing
from qgis.core import (
    QgsFeature,
    QgsFeatureSink,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
    QgsProcessingUtils,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_NETWORK, LONG, PlanXAlgorithm


class PrepareNetworkAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_NETWORK
    ICON = "tool_preparenetwork.png"
    INPUT = "INPUT"
    MIN_LENGTH = "MIN_LENGTH"
    OUTPUT = "OUTPUT"

    def name(self):
        return "preparenetwork"

    def displayName(self):
        return self.tr("Prepare Network")

    def shortHelpString(self):
        return self.tr(
            "Turns a raw street/centerline layer into an analysis-ready network: "
            "multipart geometries are exploded, lines are split at every mutual "
            "intersection (noding), exact duplicates are dropped and segments "
            "shorter than the minimum length are removed.\n\n"
            "Run this once before the other PlanX network tools whenever your "
            "data may contain crossing lines that do not share a vertex "
            "(typical for raw OSM or CAD exports). The output carries seg_id "
            "and length_m fields plus the original attributes.\n\n"
            "How to read the results\n"
            "- The segment count in the log is the first sanity check: a "
            "raw layer that keeps its feature count after noding had no "
            "crossings to fix - either it was already noded or (more "
            "likely for CAD/OSM) lines cross without touching and layers "
            "were merged wrong.\n"
            "- seg_id is a stable per-segment key for joins back to any "
            "PlanX result; length_m is ready for length-weighted stats.\n"
            "- If a later tool reports a surprisingly disconnected graph "
            "(low reach, empty catchments), come back here: overpasses "
            "kept as crossings, tiny gaps at junctions and duplicate "
            "digitising are the usual culprits. Raising the minimum "
            "length drops slivers that would otherwise become fake "
            "dead-end junctions."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT, self.tr("Street network (lines)"),
            [QgsProcessing.TypeVectorLine]))
        p = QgsProcessingParameterNumber(
            self.MIN_LENGTH, self.tr("Drop segments shorter than (map units)"),
            QgsProcessingParameterNumber.Double, 0.05, minValue=0.0)
        self.addParameter(p)
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Prepared network")))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        min_len = self.parameterAsDouble(parameters, self.MIN_LENGTH, context)
        self.require_projected(source, "Street network")

        def child(alg, params):
            res = processing.run(alg, params, context=context,
                                 feedback=feedback, is_child_algorithm=True)
            return res["OUTPUT"]

        feedback.pushInfo(self.tr("Exploding multipart geometries..."))
        single = child("native:multiparttosingleparts",
                       {"INPUT": parameters[self.INPUT], "OUTPUT": "TEMPORARY_OUTPUT"})
        feedback.pushInfo(self.tr("Noding lines at mutual intersections..."))
        noded = child("native:splitwithlines",
                      {"INPUT": single, "LINES": single, "OUTPUT": "TEMPORARY_OUTPUT"})
        deduped = child("native:deleteduplicategeometries",
                        {"INPUT": noded, "OUTPUT": "TEMPORARY_OUTPUT"})

        layer = QgsProcessingUtils.mapLayerFromString(deduped, context)
        if layer is None:
            raise QgsProcessingException("Internal error: noding produced no layer.")

        fields = self.make_fields(("seg_id", LONG), ("length_m", DOUBLE),
                                  base=source.fields())
        sink, dest_id = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields,
            QgsWkbTypes.LineString, source.sourceCrs())

        seg_id = 0
        kept = 0
        for f in layer.getFeatures():
            if feedback.isCanceled():
                break
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
            length = g.length()
            if length <= min_len:
                continue
            out = QgsFeature(fields)
            out.setGeometry(g)
            attrs = list(f.attributes())[:len(source.fields())]
            out.setAttributes(attrs + [seg_id, float(length)])
            sink.addFeature(out, QgsFeatureSink.FastInsert)
            seg_id += 1
            kept += 1
        feedback.pushInfo(self.tr(f"Prepared network: {kept} segments."))
        return {self.OUTPUT: dest_id}

    def createInstance(self):
        return PrepareNetworkAlgorithm()
