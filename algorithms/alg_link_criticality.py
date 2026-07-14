# -*- coding: utf-8 -*-
"""Link Criticality: road-network vulnerability over an OD demand set."""
from __future__ import annotations

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

from .base import DOUBLE, GROUP_NETWORK, LONG, PlanXAlgorithm
from ..engine import graphs, paths, robustness


class LinkCriticalityAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_NETWORK
    ICON = "tool_linkcriticality.png"
    NETWORK = "NETWORK"
    ORIGINS = "ORIGINS"
    DESTINATIONS = "DESTINATIONS"
    COST_FIELD = "COST_FIELD"
    CUTOFF = "CUTOFF"
    CRITICAL = "CRITICAL"

    def name(self):
        return "linkcriticality"

    def displayName(self):
        return self.tr("Link Criticality (Network Robustness)")

    def shortHelpString(self):
        return self.tr(
            "Ranks every street segment by how badly the network would suffer "
            "if that segment were lost - the road-network vulnerability view "
            "(Network Robustness Index; Scott et al. 2006 / Jenelius et al. "
            "2006), computed with the embedded Dijkstra engine, no external "
            "routing plugin or server.\n\n"
            "For the origin-destination demand you supply (origins to "
            "destinations, or all pairs among the origins when no destination "
            "layer is given), the tool first routes every pair on the intact "
            "network, then removes each segment in turn and re-routes, and "
            "reports the extra travel each removal forces plus any demand it "
            "cuts off entirely. Only segments that carry at least one shortest "
            "path are re-tested - the rest cannot change any route and score "
            "zero.\n\n"
            "Cost defaults to metric length; a numeric attribute column of the "
            "network layer (e.g. travel time) can override it. The engine "
            "minimises the SUM of segment costs along each path, so the column "
            "must be additive per segment - a time, a weighted length, a "
            "generalised cost - never a speed. Convert speeds first, e.g. "
            "time_min = length_m / (speed_kmh * 1000 / 60) in the Field "
            "Calculator; extra_cost and the cutoff then work in the column's "
            "units. Values must be zero or positive; NULL costs read as 0 "
            "(free segments). Origins and destinations snap to their nearest "
            "network node; run 'Prepare Network' first if your lines are not "
            "noded. A cost cutoff of 0 means unlimited.\n\n"
            "How to read the results\n"
            "- criticality is the headline score: the extra network-wide "
            "travel cost caused by losing this one segment, as a fraction of "
            "the whole demand's baseline cost. 0 = redundant (traffic simply "
            "takes an equally short alternative); the top few percent are the "
            "links the network leans on.\n"
            "- extra_cost is the same rise in absolute units (metres, or the "
            "cost column's units) summed over every OD pair - the detour bill "
            "of losing the link.\n"
            "- n_disconnected counts OD pairs that become unreachable when the "
            "segment goes: a nonzero value flags a genuine cut edge (a bridge, "
            "a single tunnel, a lone connector) whose loss isolates demand - "
            "usually more urgent than any detour.\n"
            "- used_by is how many shortest paths run over the segment: high "
            "use with low criticality means well-served redundancy, high use "
            "with high criticality means a real bottleneck.\n\n"
            "Using the results: sort by n_disconnected then criticality to "
            "triage the segments a resilience plan should duplicate, protect "
            "or provide a bypass for; style the layer by criticality for a "
            "network-vulnerability map; place your origins/destinations on the "
            "trips that matter (population to hospitals, depots to demand) so "
            "the ranking reflects real exposure, not just geometry."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("Street network (lines)"),
            [QgsProcessing.SourceType.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.ORIGINS, self.tr("Origins"),
            [QgsProcessing.SourceType.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.DESTINATIONS, self.tr("Destinations (empty = origins)"),
            [QgsProcessing.SourceType.TypeVectorAnyGeometry], optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.COST_FIELD, self.tr("Cost field on network (empty = length)"),
            parentLayerParameterName=self.NETWORK, optional=True,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.CUTOFF, self.tr("Maximum cost (0 = unlimited)"),
            QgsProcessingParameterNumber.Type.Double, 0.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.CRITICAL, self.tr("Segment criticality"),
            type=QgsProcessing.SourceType.TypeVectorLine))

    def processAlgorithm(self, parameters, context, feedback):
        network = self.parameterAsSource(parameters, self.NETWORK, context)
        origins = self.parameterAsSource(parameters, self.ORIGINS, context)
        dests = self.parameterAsSource(parameters, self.DESTINATIONS, context)
        cost_field = self.parameterAsString(parameters, self.COST_FIELD, context)
        cutoff = self.parameterAsDouble(parameters, self.CUTOFF, context) or None
        self.require_projected(network, "Street network")
        same_layer = dests is None

        polylines, line_feats = self.source_polylines(network)
        costs = None
        if cost_field:
            idx = network.fields().lookupField(cost_field)
            costs = [float(f.attributes()[idx] or 0.0) for f in line_feats]
        graph = graphs.build_node_graph(polylines, costs=costs)
        feedback.pushInfo(self.tr(
            f"Graph: {graph.num_nodes} nodes / {graph.num_edges} edges "
            f"(SciPy fast path: {'yes' if paths.HAS_SCIPY else 'no'})"))

        crs = network.sourceCrs()
        o_xy, _ = self.source_points(origins, crs, context.transformContext())
        if same_layer:
            d_xy = o_xy
        else:
            d_xy, _ = self.source_points(dests, crs, context.transformContext())
        o_nodes = graphs.nearest_nodes(graph, o_xy)
        d_nodes = graphs.nearest_nodes(graph, d_xy)

        res = robustness.edge_criticality(
            graph.indptr, graph.adj_node, graph.adj_edge, graph.adj_cost,
            graph.num_nodes, graph.num_edges, o_nodes, d_nodes,
            same_layer=same_layer, cutoff=cutoff,
            progress=lambda fr: feedback.setProgress(int(100.0 * fr)),
            cancel=feedback.isCanceled)
        feedback.pushInfo(self.tr(
            f"OD demand: {res['n_reachable']}/{res['n_pairs']} pairs reachable; "
            f"baseline cost total {res['base_total']:.1f}; "
            f"candidate segments tested: {int((res['used_by'] > 0).sum())}"))

        fields = self.make_fields(
            ("edge_id", LONG), ("criticality", DOUBLE), ("extra_cost", DOUBLE),
            ("n_disconnected", LONG), ("used_by", LONG), ("length_m", DOUBLE))
        sink, dest = self.parameterAsSink(
            parameters, self.CRITICAL, context, fields,
            QgsWkbTypes.Type.LineString, crs)

        crit = res["criticality"]
        extra = res["extra_cost"]
        ndisc = res["n_disconnected"]
        usedby = res["used_by"]
        edge_len = graph.edge_len
        for e in range(graph.num_edges):
            if feedback.isCanceled():
                break
            f = QgsFeature(fields)
            f.setGeometry(QgsGeometry.fromPolylineXY(
                [QgsPointXY(float(x), float(y)) for x, y in polylines[e]]))
            f.setAttributes([int(e), float(crit[e]), float(extra[e]),
                             int(ndisc[e]), int(usedby[e]), float(edge_len[e])])
            sink.addFeature(f, QgsFeatureSink.Flag.FastInsert)

        return {self.CRITICAL: dest}

    def createInstance(self):
        return LinkCriticalityAlgorithm()
