# -*- coding: utf-8 -*-
"""Street Network Morphology: orientation order, meshedness, node typology."""
from __future__ import annotations

import math

import numpy as np

from qgis.core import (
    QgsFeature,
    QgsFeatureSink,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_MORPHOLOGY, INT, PlanXAlgorithm, STRING
from ..engine import graphs, morphology


class StreetNetworkMorphologyAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_MORPHOLOGY
    ICON = "tool_streetmorphology.png"
    NETWORK = "NETWORK"
    NODES = "NODES"
    SUMMARY = "SUMMARY"

    def name(self):
        return "streetmorphology"

    def displayName(self):
        return self.tr("Street Network Morphology")

    def shortHelpString(self):
        return self.tr(
            "Profiles the structure of a street network in one pass:\n"
            "- orientation entropy and orientation order (Boeing 2019): how "
            "grid-like the street bearings are (order 1 = perfect grid)\n"
            "- meshedness / connectivity indices (alpha, beta, gamma)\n"
            "- intersection density, cul-de-sac ratio, average segment "
            "length and node degree\n\n"
            "Outputs a junction layer typed as cul-de-sac / continuation / "
            "intersection and a summary table of all indicators - ideal for "
            "comparing neighbourhoods or tracking plan alternatives.\n\n"
            "How to read the results\n"
            "- orientation order: 1 = one perfect grid, 0 = bearings in "
            "every direction. ~0.7+ planned grid fabric, ~0.1-0.3 organic "
            "or topography-driven growth. A district whose order jumps at "
            "a boundary is two different planning eras meeting.\n"
            "- alpha/gamma (meshedness): share of possible loops/links "
            "actually built. alpha < 0.1 = tree-like, few route choices "
            "(fragile, congestion-prone); 0.2+ = well-meshed with "
            "redundancy. beta (edges per node) ~1.4 suburban, ~2.0 dense "
            "grid.\n"
            "- cul-de-sac ratio vs intersection density: the sprawl "
            "signature in two numbers - many dead ends + few "
            "intersections per km2 = low walkability before you compute "
            "any walk score.\n"
            "- avg segment length: ~80-120 m supports pedestrian "
            "permeability; 200 m+ blocks resist walking.\n\n"
            "Using the results: benchmark a proposal against a loved "
            "existing district (same table, side by side); use components "
            "> 1 as a data-quality alarm (disconnected network = run "
            "Prepare Network); track alpha and intersection density "
            "across plan iterations to prove connectivity gains."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("Street network (lines)"), [QgsProcessing.SourceType.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.NODES, self.tr("Junction typology (points)")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.SUMMARY, self.tr("Network summary (table)"), type=QgsProcessing.SourceType.TypeVector))

    def processAlgorithm(self, parameters, context, feedback):
        network = self.parameterAsSource(parameters, self.NETWORK, context)
        self.require_projected(network, "Street network")
        polylines, _ = self.source_polylines(network)
        graph = graphs.build_node_graph(polylines)
        n, e = graph.num_nodes, graph.num_edges

        bearings = np.asarray([
            math.degrees(math.atan2(pl[-1][1] - pl[0][1], pl[-1][0] - pl[0][0]))
            for pl in polylines])
        entropy, order = morphology.orientation_entropy(bearings, graph.edge_len)

        degrees = graph.degrees()
        components = self._component_count(graph)
        mesh = morphology.meshedness(n, e, components)
        hull = morphology.convex_hull(graph.node_xy)
        hull_km2 = morphology.ring_area(hull) / 1e6 if len(hull) >= 3 else 0.0
        n_intersections = int((degrees >= 3).sum())
        n_culdesac = int((degrees == 1).sum())
        total_len_km = float(graph.edge_len.sum()) / 1000.0

        crs = network.sourceCrs()
        node_fields = self.make_fields(("node_id", INT), ("degree", INT), ("node_type", STRING))
        node_sink, nodes_dest = self.parameterAsSink(
            parameters, self.NODES, context, node_fields, QgsWkbTypes.Type.Point, crs)
        for i in range(n):
            d = int(degrees[i])
            ntype = "cul-de-sac" if d == 1 else ("continuation" if d == 2 else "intersection")
            f = QgsFeature(node_fields)
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*graph.node_xy[i])))
            f.setAttributes([i, d, ntype])
            node_sink.addFeature(f, QgsFeatureSink.Flag.FastInsert)

        rows = [
            ("nodes", n), ("edges", e), ("components", components),
            ("total_length_km", round(total_len_km, 3)),
            ("avg_segment_length_m", round(float(graph.edge_len.mean()), 2)),
            ("avg_node_degree", round(float(degrees.mean()), 3)),
            ("intersections_deg3plus", n_intersections),
            ("culdesac_count", n_culdesac),
            ("culdesac_ratio", round(n_culdesac / n, 4) if n else 0.0),
            ("intersection_density_km2", round(n_intersections / hull_km2, 2) if hull_km2 > 0 else 0.0),
            ("alpha_meshedness", round(mesh["alpha"], 4)),
            ("beta_index", round(mesh["beta"], 4)),
            ("gamma_index", round(mesh["gamma"], 4)),
            ("orientation_entropy_nats", round(entropy, 4)),
            ("orientation_order", round(order, 4)),
        ]
        sum_fields = self.make_fields(("metric", STRING), ("value", DOUBLE))
        sum_sink, sum_dest = self.parameterAsSink(
            parameters, self.SUMMARY, context, sum_fields, QgsWkbTypes.Type.NoGeometry, crs)
        for name, value in rows:
            f = QgsFeature(sum_fields)
            f.setAttributes([name, float(value)])
            sum_sink.addFeature(f, QgsFeatureSink.Flag.FastInsert)
            feedback.pushInfo(f"  {name} = {value}")

        return {self.NODES: nodes_dest, self.SUMMARY: sum_dest}

    @staticmethod
    def _component_count(graph) -> int:
        try:
            from scipy.sparse import csgraph, csr_matrix
            mat = csr_matrix((graph.adj_cost, graph.adj_node, graph.indptr),
                             shape=(graph.num_nodes, graph.num_nodes))
            return int(csgraph.connected_components(mat, directed=False)[0])
        except Exception:
            seen = np.zeros(graph.num_nodes, dtype=bool)
            comps = 0
            for start in range(graph.num_nodes):
                if seen[start]:
                    continue
                comps += 1
                stack = [start]
                seen[start] = True
                while stack:
                    u = stack.pop()
                    for k in range(graph.indptr[u], graph.indptr[u + 1]):
                        v = graph.adj_node[k]
                        if not seen[v]:
                            seen[v] = True
                            stack.append(v)
            return comps

    def createInstance(self):
        return StreetNetworkMorphologyAlgorithm()
