# -*- coding: utf-8 -*-
"""Cycling Stress: simplified Level of Traffic Stress classification."""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsCoordinateReferenceSystem,
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

from .base import DOUBLE, GROUP_CYCLE, INT, PlanXAlgorithm, STRING
from ..engine import cycling, graphs


class CyclingStressAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_CYCLE
    ICON = "tool_cyclingstress.png"
    NETWORK = "NETWORK"
    SPEED_FIELD = "SPEED_FIELD"
    LANES_FIELD = "LANES_FIELD"
    AADT_FIELD = "AADT_FIELD"
    INFRA_FIELD = "INFRA_FIELD"
    DEFAULT_SPEED = "DEFAULT_SPEED"
    DEFAULT_LANES = "DEFAULT_LANES"
    DEFAULT_AADT = "DEFAULT_AADT"
    DEFAULT_INFRA = "DEFAULT_INFRA"
    RULES = "RULES"
    OUTPUT = "OUTPUT"
    SUMMARY = "SUMMARY"

    def name(self):
        return "cyclingstress"

    def displayName(self):
        return self.tr("Cycling Stress (LTS)")

    def shortHelpString(self):
        return self.tr(
            "Classifies every street segment into Level of Traffic Stress "
            "(LTS 1-4) for cycling. LTS 1 is low-stress, LTS 4 is high-"
            "stress. The classifier is a deliberately simplified "
            "Mekuria/Furth-style screening rule, not a legal design "
            "standard.\n\n"
            "Inputs are speed, lanes, AADT and cycling infrastructure "
            "fields. Every field is optional: missing speed defaults to "
            "50, lanes to 2, AADT to 0, and infrastructure to 'mixed'. "
            "Infrastructure values are interpreted as 'path' for separated "
            "paths, 'lane' for painted cycling lanes, and anything else as "
            "mixed traffic.\n\n"
            "Rules: separated path -> LTS 1; cycling lane -> LTS 2 when "
            "speed <= 50 and lanes <= 3, else LTS 3; mixed traffic -> LTS "
            "1 when speed <= 30, lanes <= 2 and AADT < 1000, LTS 2 when "
            "speed <= 30 and lanes <= 2, LTS 3 when speed <= 50, else "
            "LTS 4. The threshold table is editable as key=value text.\n\n"
            "Outputs the network with lts, lts_label and length_m fields, "
            "plus a share table by LTS class. Use a projected CRS."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("Street network (lines)"),
            [QgsProcessing.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterField(
            self.SPEED_FIELD, self.tr("Speed field (empty = default speed)"),
            parentLayerParameterName=self.NETWORK, optional=True,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterField(
            self.LANES_FIELD, self.tr("Lane count field (empty = default lanes)"),
            parentLayerParameterName=self.NETWORK, optional=True,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterField(
            self.AADT_FIELD, self.tr("AADT field (empty = default AADT)"),
            parentLayerParameterName=self.NETWORK, optional=True,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterField(
            self.INFRA_FIELD,
            self.tr("Cycling infrastructure field (path / lane / mixed)"),
            parentLayerParameterName=self.NETWORK, optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.DEFAULT_SPEED, self.tr("Default speed"),
            QgsProcessingParameterNumber.Double, 50.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.DEFAULT_LANES, self.tr("Default lane count"),
            QgsProcessingParameterNumber.Double, 2.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.DEFAULT_AADT, self.tr("Default AADT"),
            QgsProcessingParameterNumber.Double, 0.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterString(
            self.DEFAULT_INFRA,
            self.tr("Default cycling infrastructure (path / lane / mixed)"),
            "mixed"))
        self.addParameter(QgsProcessingParameterString(
            self.RULES, self.tr("LTS threshold rules"),
            cycling.DEFAULT_LTS_RULES_TEXT))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Segments with LTS")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.SUMMARY, self.tr("LTS length share"),
            type=QgsProcessing.TypeVector))

    def processAlgorithm(self, parameters, context, feedback):
        network = self.parameterAsSource(parameters, self.NETWORK, context)
        speed_f = self.parameterAsString(parameters, self.SPEED_FIELD, context)
        lanes_f = self.parameterAsString(parameters, self.LANES_FIELD, context)
        aadt_f = self.parameterAsString(parameters, self.AADT_FIELD, context)
        infra_f = self.parameterAsString(parameters, self.INFRA_FIELD, context)
        default_speed = self.parameterAsDouble(parameters, self.DEFAULT_SPEED, context)
        default_lanes = self.parameterAsDouble(parameters, self.DEFAULT_LANES, context)
        default_aadt = self.parameterAsDouble(parameters, self.DEFAULT_AADT, context)
        default_infra = self.parameterAsString(parameters, self.DEFAULT_INFRA, context) or "mixed"
        rules_text = self.parameterAsString(parameters, self.RULES, context)
        self.require_projected(network, "Street network")
        try:
            rules = cycling.parse_lts_rules(rules_text)
        except ValueError as exc:
            raise QgsProcessingException(str(exc))

        polylines, feats = self.source_polylines(network, feedback)
        graph = graphs.build_node_graph(polylines)
        fields_in = network.fields()
        s_idx = fields_in.lookupField(speed_f) if speed_f else -1
        l_idx = fields_in.lookupField(lanes_f) if lanes_f else -1
        a_idx = fields_in.lookupField(aadt_f) if aadt_f else -1
        i_idx = fields_in.lookupField(infra_f) if infra_f else -1

        speeds = np.full(len(feats), default_speed, dtype=float)
        lanes = np.full(len(feats), default_lanes, dtype=float)
        aadts = np.full(len(feats), default_aadt, dtype=float)
        infra = np.full(len(feats), default_infra, dtype=object)

        def read_num(attrs, idx, default):
            if idx < 0:
                return default
            try:
                val = float(attrs[idx])
            except (TypeError, ValueError):
                return default
            return val if np.isfinite(val) else default

        for e, feat in enumerate(feats):
            attrs = feat.attributes()
            speeds[e] = read_num(attrs, s_idx, default_speed)
            lanes[e] = read_num(attrs, l_idx, default_lanes)
            aadts[e] = read_num(attrs, a_idx, default_aadt)
            if i_idx >= 0 and attrs[i_idx] is not None and str(attrs[i_idx]).strip():
                infra[e] = str(attrs[i_idx]).strip()

        lts = cycling.lts_classify(speeds, lanes, aadts, infra, rules)
        labels = {1: "LTS 1 low stress", 2: "LTS 2 low stress",
                  3: "LTS 3 moderate stress", 4: "LTS 4 high stress"}

        out_fields = self.make_fields(
            ("lts", INT), ("lts_label", STRING), ("length_m", DOUBLE),
            ("speed_used", DOUBLE), ("lanes_used", DOUBLE), ("aadt_used", DOUBLE),
            ("infra_used", STRING), base=fields_in)
        sink, dest = self.parameterAsSink(
            parameters, self.OUTPUT, context, out_fields,
            QgsWkbTypes.LineString, network.sourceCrs())
        n_base = len(fields_in)
        for e, feat in enumerate(feats):
            if feedback.isCanceled():
                break
            out = QgsFeature(out_fields)
            out.setGeometry(QgsGeometry.fromPolylineXY(
                [QgsPointXY(float(x), float(y)) for x, y in polylines[e]]))
            out.setAttributes(list(feat.attributes())[:n_base] + [
                int(lts[e]), labels[int(lts[e])], round(float(graph.edge_len[e]), 2),
                round(float(speeds[e]), 2), round(float(lanes[e]), 2),
                round(float(aadts[e]), 1), str(infra[e]).lower()])
            sink.addFeature(out, QgsFeatureSink.FastInsert)

        s_fields = self.make_fields(
            ("lts", INT), ("label", STRING), ("length_m", DOUBLE),
            ("share_len", DOUBLE), ("segments", INT))
        s_sink, s_dest = self.parameterAsSink(
            parameters, self.SUMMARY, context, s_fields,
            QgsWkbTypes.NoGeometry, QgsCoordinateReferenceSystem())
        total_len = float(graph.edge_len.sum()) or 1.0
        for cls in range(1, 5):
            m = lts == cls
            length = float(graph.edge_len[m].sum())
            feat = QgsFeature(s_fields)
            feat.setAttributes([
                cls, labels[cls], round(length, 2),
                round(length / total_len, 4), int(m.sum())])
            s_sink.addFeature(feat, QgsFeatureSink.FastInsert)
        feedback.pushInfo(self.tr(
            f"{len(feats)} segment(s) classified; "
            f"{100.0 * float(graph.edge_len[lts <= 2].sum()) / total_len:.1f} percent "
            "of network length is LTS 1-2."))
        return {self.OUTPUT: dest, self.SUMMARY: s_dest}

    def createInstance(self):
        return CyclingStressAlgorithm()
