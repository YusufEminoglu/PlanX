# -*- coding: utf-8 -*-
"""Prepare Network: node a raw street layer for graph analysis."""
from __future__ import annotations

import numpy as np
from qgis.core import (
    QgsFeature,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsProcessingParameterCrs,
    QgsProcessingParameterBoolean,
    QgsProcessingUtils,
    QgsWkbTypes,
    QgsCoordinateTransform,
    QgsVectorDataProvider,
)

from .base import DOUBLE, GROUP_NETWORK, LONG, PlanXAlgorithm
from ..engine import graphs


class PrepareNetworkAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_NETWORK
    ICON = "tool_preparenetwork.png"
    INPUT = "INPUT"
    MIN_LENGTH = "MIN_LENGTH"
    TARGET_CRS = "TARGET_CRS"
    CREATE_INDEX = "CREATE_INDEX"
    SNAP_TOLERANCE = "SNAP_TOLERANCE"
    ONEWAY_FIELD = "ONEWAY_FIELD"
    FORWARD_COST = "FORWARD_COST"
    REVERSE_COST = "REVERSE_COST"
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
            "PlanX result; length_m is measured in the source CRS and is "
            "ready for length-weighted stats.\n"
            "- The target CRS option allows reprojecting the output; geographic "
            "CRS outputs will issue a warning since other PlanX tools require "
            "projected coordinates. The spatial index option makes the resulting "
            "temporary layer immediately fast in spatial joins/snapping.\n"
            "- If a later tool reports a surprisingly disconnected graph "
            "(low reach, empty catchments), come back here: overpasses "
            "kept as crossings, tiny gaps at junctions and duplicate "
            "digitising are the usual culprits. Raising the minimum "
            "length drops slivers that would otherwise become fake "
            "dead-end junctions.\n\n"
            "Using the results\n"
            "Save the prepared network or feed it directly into routing, OD, or "
            "walkability tools."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT, self.tr("Street network (lines)"),
            [QgsProcessing.SourceType.TypeVectorLine]))
        p = QgsProcessingParameterNumber(
            self.MIN_LENGTH, self.tr("Drop segments shorter than (map units)"),
            QgsProcessingParameterNumber.Type.Double, 0.05, minValue=0.0)
        self.addParameter(p)
        self.addParameter(QgsProcessingParameterCrs(
            self.TARGET_CRS, self.tr("Reproject result to (empty = keep network CRS)"),
            optional=True))
        self.addParameter(QgsProcessingParameterBoolean(
            self.CREATE_INDEX, self.tr("Create spatial index on the result"),
            defaultValue=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.SNAP_TOLERANCE, self.tr("Snap endpoint gaps within (map units; 0 = off)"),
            QgsProcessingParameterNumber.Type.Double, 0.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterField(
            self.ONEWAY_FIELD, self.tr("One-way field (optional: yes/1, -1/reverse, no/0)"),
            parentLayerParameterName=self.INPUT, optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.FORWARD_COST, self.tr("Forward additive cost field (optional)"),
            parentLayerParameterName=self.INPUT, optional=True,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterField(
            self.REVERSE_COST, self.tr("Reverse additive cost field (optional)"),
            parentLayerParameterName=self.INPUT, optional=True,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Prepared network")))

    def processAlgorithm(self, parameters, context, feedback):
        import processing

        source = self.parameterAsSource(parameters, self.INPUT, context)
        min_len = self.parameterAsDouble(parameters, self.MIN_LENGTH, context)
        self.require_projected(source, "Street network")

        target_crs = self.parameterAsCrs(parameters, self.TARGET_CRS, context)
        create_index = self.parameterAsBool(parameters, self.CREATE_INDEX, context)
        snap_tolerance = self.parameterAsDouble(parameters, self.SNAP_TOLERANCE, context)
        oneway_field = self.parameterAsString(parameters, self.ONEWAY_FIELD, context)
        forward_field = self.parameterAsString(parameters, self.FORWARD_COST, context)
        reverse_field = self.parameterAsString(parameters, self.REVERSE_COST, context)

        def child(alg, params):
            res = processing.run(alg, params, context=context,
                                 feedback=feedback, is_child_algorithm=True)
            return res["OUTPUT"]

        feedback.pushInfo(self.tr("Exploding multipart geometries..."))
        single = child("native:multiparttosingleparts",
                       {"INPUT": parameters[self.INPUT], "OUTPUT": "TEMPORARY_OUTPUT"})
        if snap_tolerance > 0:
            feedback.pushInfo(self.tr(f"Snapping endpoint gaps within {snap_tolerance:g} map units..."))
            single = child("native:snapgeometries",
                           {"INPUT": single, "REFERENCE_LAYER": single,
                            "TOLERANCE": snap_tolerance, "BEHAVIOR": 0,
                            "OUTPUT": "TEMPORARY_OUTPUT"})
            single = child("native:fixgeometries",
                           {"INPUT": single, "OUTPUT": "TEMPORARY_OUTPUT"})
        feedback.pushInfo(self.tr("Noding lines at mutual intersections..."))
        noded = child("native:splitwithlines",
                      {"INPUT": single, "LINES": single, "OUTPUT": "TEMPORARY_OUTPUT"})
        deduped = child("native:deleteduplicategeometries",
                        {"INPUT": noded, "OUTPUT": "TEMPORARY_OUTPUT"})

        layer = QgsProcessingUtils.mapLayerFromString(deduped, context)
        if layer is None:
            raise QgsProcessingException("Internal error: noding produced no layer.")

        source_crs = source.sourceCrs()
        out_crs = source_crs
        transform = None
        if target_crs.isValid() and target_crs != source_crs:
            out_crs = target_crs
            transform = QgsCoordinateTransform(source_crs, target_crs, context.transformContext())
            if target_crs.isGeographic():
                feedback.pushWarning(self.tr("The target CRS is geographic. Other PlanX tools require a projected CRS."))

        source_fields = QgsFields()
        keep_indices = []
        for idx, fld in enumerate(source.fields()):
            if fld.name().lower() not in ("fid", "ogc_fid"):
                source_fields.append(QgsField(fld))
                keep_indices.append(idx)

        fields = self.make_fields(("seg_id", LONG), ("length_m", DOUBLE),
                                  ("dir_code", LONG), ("cost_fwd", DOUBLE),
                                  ("cost_rev", DOUBLE), ("node_from", LONG),
                                  ("node_to", LONG), ("component", LONG),
                                  base=source_fields)
        sink, dest_id = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields,
            QgsWkbTypes.Type.LineString, out_crs)

        records = []
        source_count = len(source.fields())
        field_names = [field.name() for field in layer.fields()]
        oneway_idx = field_names.index(oneway_field) if oneway_field in field_names else -1
        forward_idx = field_names.index(forward_field) if forward_field in field_names else -1
        reverse_idx = field_names.index(reverse_field) if reverse_field in field_names else -1
        for f in layer.getFeatures():
            if feedback.isCanceled():
                break
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
            length = g.length()
            if length <= min_len:
                continue
            value = str(f.attributes()[oneway_idx]).strip().lower() if oneway_idx >= 0 else ""
            direction = -1 if value in ("-1", "reverse", "backward") else 1 if value in ("1", "yes", "true", "forward") else 0
            def positive_cost(index):
                try:
                    number = float(f.attributes()[index]) if index >= 0 else length
                    return number if number > 0 else length
                except (TypeError, ValueError):
                    return length
            records.append((f, QgsGeometry(g), length, direction, positive_cost(forward_idx), positive_cost(reverse_idx)))

        if not records:
            raise QgsProcessingException("Network preparation removed every segment.")
        polylines = []
        for _, geometry, _, _, _, _ in records:
            line = (geometry.asMultiPolyline()[0] if geometry.isMultipart()
                    else geometry.asPolyline())
            polylines.append([[point.x(), point.y()] for point in line])
        graph = graphs.build_node_graph(
            polylines, tolerance=max(0.01, snap_tolerance or 0.01),
            costs=[item[4] for item in records], reverse_costs=[item[5] for item in records],
            directions=[item[3] for item in records],
        )
        component_labels, component_count = graphs.weak_components(graph)

        for seg_id, (f, g, length, direction, cost_fwd, cost_rev) in enumerate(records):
            if feedback.isCanceled():
                break
            out = QgsFeature(fields)
            if transform is not None:
                g_trans = QgsGeometry(g)
                g_trans.transform(transform)
                out.setGeometry(g_trans)
            else:
                out.setGeometry(g)
            attrs = [f.attributes()[i] for i in keep_indices]
            node_from = int(graph.edge_from[seg_id])
            node_to = int(graph.edge_to[seg_id])
            component = int(component_labels[node_from])
            out.setAttributes(attrs + [seg_id, float(length), direction, cost_fwd, cost_rev,
                                        node_from, node_to, component])
            sink.addFeature(out, QgsFeatureSink.Flag.FastInsert)

        if create_index:
            out_layer = QgsProcessingUtils.mapLayerFromString(dest_id, context)
            if out_layer is not None:
                if out_layer.dataProvider().capabilities() & QgsVectorDataProvider.Capability.CreateSpatialIndex:
                    out_layer.dataProvider().createSpatialIndex()
                    feedback.pushInfo(self.tr("Spatial index created."))
                else:
                    feedback.pushWarning(self.tr("Format does not support spatial index creation."))

        degree = graph.degrees()
        dead_ends = int(np.sum(degree == 1))
        feedback.pushInfo(self.tr(
            f"Prepared network: {len(records)} segments, {graph.num_nodes} nodes, "
            f"{component_count} weak component(s), {dead_ends} directed dead-end node(s)."
        ))
        if component_count > 1:
            feedback.pushWarning(self.tr(
                "The network is disconnected. Inspect the component field and increase snapping tolerance where gaps are unintended."
            ))
        return {self.OUTPUT: dest_id}

    def createInstance(self):
        return PrepareNetworkAlgorithm()
