# -*- coding: utf-8 -*-
"""Low-Stress Connectivity: LTS-filtered cycling islands."""
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
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_CYCLE, INT, PlanXAlgorithm, STRING
from ..engine import cycling, graphs


class LowStressIslandsAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_CYCLE
    ICON = "tool_lowstressislands.png"
    NETWORK = "NETWORK"
    LTS_FIELD = "LTS_FIELD"
    THRESHOLD = "THRESHOLD"
    ORIGINS = "ORIGINS"
    POP_FIELD = "POP_FIELD"
    DESTINATIONS = "DESTINATIONS"
    OUTPUT = "OUTPUT"
    SUMMARY = "SUMMARY"

    def name(self):
        return "lowstressislands"

    def displayName(self):
        return self.tr("Low-Stress Connectivity")

    def shortHelpString(self):
        return self.tr(
            "Finds the connected cycling islands available at or below a "
            "chosen Level of Traffic Stress. Use the output of Cycling "
            "Stress as the network and choose a threshold such as LTS 2 "
            "for an all-ages low-stress network.\n\n"
            "The tool removes segments above the threshold, builds connected "
            "components on the remaining primal street graph, and writes "
            "each segment's island id and island length. High-stress "
            "segments are kept in the output with island id 0 so the breaks "
            "remain visible on the map.\n\n"
            "If origins with population and a destination layer are supplied, "
            "the summary also reports the population whose snapped network "
            "node lies in an island that contains at least one destination. "
            "This is a screening answer to 'can people reach there at low "
            "stress?' using network topology only. Use a projected CRS.\n\n"
            "How to read the results\n"
            "- The island map is the honest cycling map: however much "
            "'bike network' the city has painted, an everyday rider can "
            "only use ONE island per trip. Many small islands = a "
            "network in name only.\n"
            "- The gaps between islands (the id-0 high-stress segments "
            "separating two large islands) are the entire work "
            "programme: each is a candidate crossing, protected link "
            "or traffic-calmed street.\n"
            "- The destination-reach population is the KPI: 'X percent "
            "of residents can reach a school at LTS 2' - watch it jump "
            "when a single strategic gap closes.\n\n"
            "Using the results: rank candidate links by the population "
            "of the islands they would merge (merge two big islands = "
            "step change; extend a big island into a field = little); "
            "rerun with each candidate fixed to LTS 2 and compare the "
            "reach percentage - the cheapest link with the biggest "
            "merge is the budget argument; repeat at threshold 1 for "
            "the children/seniors network."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("Street network with LTS (lines)"),
            [QgsProcessing.SourceType.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterField(
            self.LTS_FIELD, self.tr("LTS field"),
            parentLayerParameterName=self.NETWORK,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.THRESHOLD, self.tr("Maximum LTS for low-stress network"),
            QgsProcessingParameterNumber.Type.Integer, 2, minValue=1, maxValue=4))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.ORIGINS, self.tr("Origins with population (optional)"),
            [QgsProcessing.SourceType.TypeVectorAnyGeometry], optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.POP_FIELD, self.tr("Population field (empty = 1 per origin)"),
            parentLayerParameterName=self.ORIGINS, optional=True,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.DESTINATIONS, self.tr("Destination layer (optional)"),
            [QgsProcessing.SourceType.TypeVectorAnyGeometry], optional=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Segments with low-stress islands")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.SUMMARY, self.tr("Low-stress connectivity summary"),
            type=QgsProcessing.SourceType.TypeVector))

    def processAlgorithm(self, parameters, context, feedback):
        network = self.parameterAsSource(parameters, self.NETWORK, context)
        lts_field = self.parameterAsString(parameters, self.LTS_FIELD, context)
        threshold = self.parameterAsInt(parameters, self.THRESHOLD, context)
        origins = self.parameterAsSource(parameters, self.ORIGINS, context)
        destinations = self.parameterAsSource(parameters, self.DESTINATIONS, context)
        pop_field = self.parameterAsString(parameters, self.POP_FIELD, context)
        self.require_projected(network, "Street network")

        polylines, feats = self.source_polylines(network, feedback)
        graph = graphs.build_node_graph(polylines)
        l_idx = network.fields().lookupField(lts_field)
        if l_idx < 0:
            raise QgsProcessingException(f"LTS field '{lts_field}' was not found.")
        lts = np.full(len(feats), 4.0, dtype=float)
        bad = 0
        for e, feat in enumerate(feats):
            try:
                lts[e] = float(feat.attributes()[l_idx])
            except (TypeError, ValueError):
                bad += 1
                lts[e] = 4.0
        if bad:
            feedback.pushWarning(self.tr(
                f"{bad} segment(s) without numeric LTS - counted as LTS 4."))

        islands = cycling.low_stress_islands(
            graph.edge_from, graph.edge_to, graph.edge_len, lts, threshold)
        edge_comp = islands["edge_labels"]
        comp_len = islands["component_length"]

        out_fields = self.make_fields(
            ("lowstress", INT), ("island_id", INT), ("island_m", DOUBLE),
            base=network.fields())
        sink, dest = self.parameterAsSink(
            parameters, self.OUTPUT, context, out_fields,
            QgsWkbTypes.Type.LineString, network.sourceCrs())
        n_base = len(network.fields())
        for e, feat in enumerate(feats):
            if feedback.isCanceled():
                break
            c = int(edge_comp[e])
            out = QgsFeature(out_fields)
            out.setGeometry(QgsGeometry.fromPolylineXY(
                [QgsPointXY(float(x), float(y)) for x, y in polylines[e]]))
            out.setAttributes(list(feat.attributes())[:n_base] + [
                1 if c >= 0 else 0, c + 1 if c >= 0 else 0,
                round(float(comp_len[c]), 2) if c >= 0 else 0.0])
            sink.addFeature(out, QgsFeatureSink.Flag.FastInsert)

        reachable_pop = None
        total_pop = None
        dest_islands = set()
        if origins is not None and destinations is not None:
            crs = network.sourceCrs()
            xform = context.transformContext()
            o_xy, o_feats = self.source_points(origins, crs, xform)
            d_xy, _d_feats = self.source_points(destinations, crs, xform)
            o_nodes = graphs.nearest_nodes(graph, o_xy)
            d_nodes = graphs.nearest_nodes(graph, d_xy)
            node_labels = islands["node_labels"]
            dest_islands = {int(node_labels[n]) for n in d_nodes if node_labels[n] >= 0}
            p_idx = origins.fields().lookupField(pop_field) if pop_field else -1
            pops = np.ones(len(o_feats), dtype=float)
            if p_idx >= 0:
                for i, feat in enumerate(o_feats):
                    try:
                        pops[i] = max(0.0, float(feat.attributes()[p_idx]))
                    except (TypeError, ValueError):
                        pops[i] = 0.0
            total_pop = float(pops.sum())
            reachable = np.asarray([int(node_labels[n]) in dest_islands for n in o_nodes])
            reachable_pop = float(pops[reachable].sum())
        elif origins is not None or destinations is not None:
            feedback.pushWarning(self.tr(
                "Origin reachability needs both origins and destinations; "
                "population reach was not computed."))

        s_fields = self.make_fields(
            ("metric", STRING), ("value", DOUBLE), ("note", STRING))
        s_sink, s_dest = self.parameterAsSink(
            parameters, self.SUMMARY, context, s_fields,
            QgsWkbTypes.Type.NoGeometry, QgsCoordinateReferenceSystem())

        rows = [
            ("Threshold LTS", float(threshold), ""),
            ("Segments", float(len(feats)), ""),
            ("Low-stress segments", float((lts <= threshold).sum()), ""),
            ("Low-stress length (m)", float(islands["low_length"]), ""),
            ("Network length low-stress share", float(islands["low_share"]), ""),
            ("Low-stress islands", float(islands["n_components"]), ""),
            ("Largest island length (m)", float(comp_len.max()) if len(comp_len) else 0.0, ""),
        ]
        if reachable_pop is not None:
            share = reachable_pop / total_pop if total_pop and total_pop > 0 else 0.0
            rows.extend([
                ("Destination islands", float(len(dest_islands)), ""),
                ("Population reaching a destination island", reachable_pop, ""),
                ("Population reach share", share, ""),
            ])
        for metric, value, note in rows:
            feat = QgsFeature(s_fields)
            feat.setAttributes([metric, round(float(value), 6), note])
            s_sink.addFeature(feat, QgsFeatureSink.Flag.FastInsert)

        feedback.pushInfo(self.tr(
            f"{islands['n_components']} low-stress island(s); "
            f"{100.0 * islands['low_share']:.1f} percent of network length "
            f"is LTS {threshold} or lower."))
        if reachable_pop is not None:
            feedback.pushInfo(self.tr(
                f"{reachable_pop:g} of {total_pop:g} population reaches a "
                "destination island at the chosen threshold."))
        return {self.OUTPUT: dest, self.SUMMARY: s_dest}

    def createInstance(self):
        return LowStressIslandsAlgorithm()
