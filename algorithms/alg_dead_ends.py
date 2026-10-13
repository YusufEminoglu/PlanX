# -*- coding: utf-8 -*-
"""Dead-End Analysis: cul-de-sac branches, their depth, and their share of the network."""
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
    QgsProcessingParameterNumber,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_NETWORK, INT, LONG, STRING, PlanXAlgorithm
from . import _units
from ..engine import graphs, morphology


class DeadEndAnalysisAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_NETWORK
    ICON = "tool_deadends.png"
    NETWORK = "NETWORK"
    MIN_BRANCH = "MIN_BRANCH"
    SEGMENTS = "SEGMENTS"
    DEAD_ENDS = "DEAD_ENDS"
    SUMMARY = "SUMMARY"

    def name(self):
        return "deadends"

    def displayName(self):
        return self.tr("Dead-End Analysis")

    def shortHelpString(self):
        return self.tr(
            "Finds the dead ends in a street network and measures them as "
            "streets, not as points:\n"
            "- every segment is tagged with the dead-end branch it belongs to, "
            "so cul-de-sacs can be mapped, measured and styled as whole streets\n"
            "- branch depth: how many segments you drive before reaching a "
            "junction, and the junction you reach\n"
            "- a dead-end ratio by node count and by network length, so "
            "'how much of this network is dead end' has a length answer as "
            "well as a count answer\n\n"
            "A dead end here is a *chain*, not a node. A cul-de-sac is the "
            "whole street from its junction out to the turning head, and that "
            "is the length a resident has to drive twice before reaching a "
            "through route. Counting degree-1 nodes sees the tip and misses "
            "the street.\n\n"
            "Lengths are ground metres, not the layer's coordinate units: on a "
            "state-plane layer in feet, or on EPSG:3857 away from the equator, "
            "those two differ by a constant factor and every length row would "
            "be wrong without saying so.\n\n"
            "How to read the results\n"
            "- deadend_node_ratio: share of junctions/endpoints that are a "
            "dead end. ~0.02-0.10 for a grid, 0.10-0.25 for modernist "
            "superblocks, 0.30-0.60 for planned suburban 'loops and lollipops'.\n"
            "- deadend_length_ratio: the share of the network's total length "
            "that is dead-end branch. This is the number that decides how "
            "much carriageway is maintained for local traffic only, and it "
            "usually exceeds the node ratio because a cul-de-sac street is "
            "longer than the junction it ends at. A network that is 30% dead "
            "end by node count is often 40%+ by length.\n"
            "- mean_branch_m vs longest_branch_m: a mean of 60-90 m is a "
            "conventional cul-de-sac; a single branch of 500 m+ is a "
            "dendritic estate where whole neighbourhoods have one way in and "
            "out - the shape that fails first under an emergency or a closure.\n"
            "- mean_branch_segments near 1 with many branches: the network is "
            "digitised with a break at nearly every segment, so most "
            "'dead ends' are stubs at a junction rather than streets. Prepare "
            "Network closes those breaks.\n"
            "- stub_branches: branches shorter than the threshold you set. "
            "These are usually digitising gaps from under-snapping, not "
            "geometry - a 0.3 m cul-de-sac is not a street. Read them as a "
            "data-quality signal. Prepare Network's snapping tolerance is the "
            "fix; raising the minimum segment length drops the slivers before "
            "they become fake dead-end junctions here.\n"
            "- components > 1: the network is disconnected. A disconnected "
            "piece has an unnatural number of degree-1 nodes, so the ratios "
            "above describe a broken layer rather than a street pattern.\n"
            "- Every branch is anchored on the junction it leaves from "
            "(anchor_node). Branches with no anchor are segments that touch "
            "nothing else at all - an island, or a layer where the digitising "
            "gaps were never closed.\n\n"
            "Using the results\n"
            "Style the segment layer on branch_id to see each dead-end street "
            "as one object, or on is_dead_end to isolate them from the through "
            "network; burst them out with Selection by Expression on "
            "branch_segments >= 3 to review the deepest ones. Use "
            "branch_length_m to rank cul-de-sacs for turning-head upgrades or "
            "for a refuse/recycling route that has to reverse. Feed the "
            "summary into a plan audit: deadend_length_ratio falling between "
            "two scheme iterations is connectivity gain you can quote, and "
            "deadends_per_km2 is the sprawl counterpart to intersection "
            "density. For a per-district reading, intersect the segment layer "
            "with your neighbourhood polygons and aggregate "
            "branch_length_m against total length inside each.\n\n"
            "Run Prepare Network first on raw OSM or CAD data: unclosed "
            "crossings and duplicate digitising both invent dead ends that "
            "are not in the street pattern."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("Street network (lines)"),
            [QgsProcessing.SourceType.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterNumber(
            self.MIN_BRANCH,
            self.tr("Flag branches shorter than (map units; 0 = flag none)"),
            QgsProcessingParameterNumber.Type.Double, 0.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.SEGMENTS, self.tr("Segments with dead-end attribution (lines)")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.DEAD_ENDS, self.tr("Dead-end points (points)")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.SUMMARY, self.tr("Dead-end summary (table)"),
            type=QgsProcessing.SourceType.TypeVector))

    def processAlgorithm(self, parameters, context, feedback):
        network = self.parameterAsSource(parameters, self.NETWORK, context)
        self.require_projected(network, "Street network")
        min_branch = self.parameterAsDouble(parameters, self.MIN_BRANCH, context)

        # Edge lengths inside the graph are in the layer's coordinate units, not
        # metres. Every length this tool publishes - length_m, branch_length_m,
        # the kilometres and the length ratio's denominator - is a ground-metre
        # claim, so all of them go through the layer's own ground scale. A
        # state-plane layer in feet is otherwise 3.28x too long with nothing in
        # the table to suggest it. See algorithms/_units.py.
        units = _units.GroundUnits(network.sourceCrs(), context.transformContext())
        per_unit = units.scale(network.sourceExtent())

        graph, polylines, _ = self.network_graph(network, use_prepared_costs=False)
        analysis = graphs.dead_end_branches(graph, min_length=min_branch)

        degree = analysis["degree"]
        edge_branch = analysis["edge_branch"]
        edge_depth = analysis["edge_depth"]
        branch_length = analysis["branch_length"]
        branch_edges = analysis["branch_edges"]
        branch_stub = analysis["branch_stub"]
        branch_anchor = analysis["branch_anchor"]
        branch_count = len(branch_length)

        n, e = graph.num_nodes, graph.num_edges
        components = graphs.weak_component_count(graph)
        hull = morphology.convex_hull(graph.node_xy)
        hull_km2 = morphology.ring_area(hull) / (per_unit * per_unit) / 1e6 if len(hull) >= 3 else 0.0
        total_len_m = float(graph.edge_len.sum()) / per_unit

        tip_nodes = np.flatnonzero(degree == 1)
        if branch_count and int(np.sum(analysis["node_branch"][tip_nodes] < 0)):
            # Every degree-1 node is the start of a branch or the far end of one.
            # A node in neither means the walk lost an edge, and reporting it as
            # "not a dead end" would hide a genuine cul-de-sac instead of saying
            # the analysis broke.
            raise QgsProcessingException(
                "Internal error: a degree-1 node was not assigned to a dead-end branch.")
        tip_branch = analysis["node_branch"][tip_nodes]
        tip_stub = branch_stub[tip_branch]

        crs = network.sourceCrs()

        # ---------------------------------------------------------------- #
        # Segments: the whole network, each line tagged with its branch
        # ---------------------------------------------------------------- #
        seg_fields = self.make_fields(
            ("seg_id", LONG), ("length_m", DOUBLE),
            ("node_from", LONG), ("node_to", LONG),
            ("deg_from", INT), ("deg_to", INT),
            ("is_dead_end", INT), ("is_stub", INT),
            ("branch_id", LONG), ("depth", INT),
            ("branch_length_m", DOUBLE), ("branch_segments", INT),
            ("anchor_node", LONG))
        seg_sink, seg_dest = self.parameterAsSink(
            parameters, self.SEGMENTS, context, seg_fields,
            QgsWkbTypes.Type.LineString, crs)
        for seg_id in range(e):
            if feedback.isCanceled():
                break
            branch = int(edge_branch[seg_id])
            in_branch = branch >= 0
            start = int(graph.edge_from[seg_id])
            end = int(graph.edge_to[seg_id])
            feature = QgsFeature(seg_fields)
            feature.setGeometry(QgsGeometry.fromPolylineXY(
                [QgsPointXY(float(point[0]), float(point[1])) for point in polylines[seg_id]]))
            feature.setAttributes([
                seg_id,
                round(float(graph.edge_len[seg_id]) / per_unit, 3),
                start, end,
                int(degree[start]), int(degree[end]),
                1 if in_branch else 0,
                int(branch_stub[branch]) if in_branch else 0,
                branch,
                int(edge_depth[seg_id]) if in_branch else -1,
                round(float(branch_length[branch]) / per_unit, 3) if in_branch else 0.0,
                int(branch_edges[branch]) if in_branch else 0,
                int(branch_anchor[branch]) if in_branch else -1,
            ])
            seg_sink.addFeature(feature, QgsFeatureSink.Flag.FastInsert)

        # ---------------------------------------------------------------- #
        # Dead-end points: one per degree-1 node, carrying its branch
        # ---------------------------------------------------------------- #
        tip_fields = self.make_fields(
            ("node_id", LONG), ("degree", INT),
            ("branch_id", LONG), ("branch_length_m", DOUBLE),
            ("branch_segments", INT), ("anchor_node", LONG),
            ("anchor_degree", INT), ("is_stub", INT))
        tip_sink, tip_dest = self.parameterAsSink(
            parameters, self.DEAD_ENDS, context, tip_fields,
            QgsWkbTypes.Type.Point, crs)
        for index, node in enumerate(tip_nodes):
            if feedback.isCanceled():
                break
            node = int(node)
            branch = int(tip_branch[index])
            anchor = int(branch_anchor[branch])
            feature = QgsFeature(tip_fields)
            feature.setGeometry(QgsGeometry.fromPointXY(
                QgsPointXY(float(graph.node_xy[node][0]), float(graph.node_xy[node][1]))))
            feature.setAttributes([
                node, int(degree[node]),
                branch,
                round(float(branch_length[branch]) / per_unit, 3),
                int(branch_edges[branch]),
                anchor,
                int(degree[anchor]) if anchor >= 0 else 0,
                int(branch_stub[branch]),
            ])
            tip_sink.addFeature(feature, QgsFeatureSink.Flag.FastInsert)

        # ---------------------------------------------------------------- #
        # Summary
        # ---------------------------------------------------------------- #
        deadend_nodes = int(len(tip_nodes))
        deadend_len_m = float(graph.edge_len[edge_branch >= 0].sum()) / per_unit
        real_nodes = int((~tip_stub).sum())
        real_len_m = float(branch_length[~branch_stub].sum()) / per_unit if branch_count else 0.0
        rows = [
            ("nodes", n),
            ("edges", e),
            ("components", components),
            ("total_length_km", round(total_len_m / 1000.0, 3)),
            ("deadend_nodes", deadend_nodes),
            ("deadend_branches", branch_count),
            ("deadend_length_m", round(deadend_len_m, 2)),
            ("deadend_node_ratio", round(deadend_nodes / n, 4) if n else 0.0),
            ("deadend_length_ratio", round(deadend_len_m / total_len_m, 4) if total_len_m > 0 else 0.0),
            ("stub_branches", int(branch_stub.sum())),
            ("deadend_node_ratio_excl_stubs", round(real_nodes / n, 4) if n else 0.0),
            ("deadend_length_ratio_excl_stubs",
             round(real_len_m / total_len_m, 4) if total_len_m > 0 else 0.0),
            ("longest_branch_m", round(float(branch_length.max()) / per_unit, 2) if branch_count else 0.0),
            ("mean_branch_m", round(float(branch_length.mean()) / per_unit, 2) if branch_count else 0.0),
            ("median_branch_m", round(float(np.median(branch_length)) / per_unit, 2) if branch_count else 0.0),
            ("mean_branch_segments", round(float(branch_edges.mean()), 2) if branch_count else 0.0),
            ("deadends_per_km2", round(branch_count / hull_km2, 2) if hull_km2 > 0 else 0.0),
        ]
        sum_fields = self.make_fields(("metric", STRING), ("value", DOUBLE))
        sum_sink, sum_dest = self.parameterAsSink(
            parameters, self.SUMMARY, context, sum_fields, QgsWkbTypes.Type.NoGeometry, crs)
        for name, value in rows:
            feature = QgsFeature(sum_fields)
            feature.setAttributes([name, float(value)])
            sum_sink.addFeature(feature, QgsFeatureSink.Flag.FastInsert)
            feedback.pushInfo(f"  {name} = {value}")

        if components > 1:
            feedback.pushWarning(self.tr(
                f"The network has {components} disconnected components. Endpoints "
                "created by the breaks inflate the dead-end counts - run Prepare "
                "Network with a snapping tolerance first."))
        return {self.SEGMENTS: seg_dest, self.DEAD_ENDS: tip_dest, self.SUMMARY: sum_dest}

    def createInstance(self):
        return DeadEndAnalysisAlgorithm()
