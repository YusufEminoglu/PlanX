# -*- coding: utf-8 -*-
"""Green Space Access: park hierarchy standards on network distances."""
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
    QgsProcessingParameterString,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_GREEN, INT, PlanXAlgorithm
from ..engine import graphs, green, paths


class GreenAccessAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_GREEN
    ICON = "tool_greenaccess.png"
    NETWORK = "NETWORK"
    DEMAND = "DEMAND"
    POP_FIELD = "POP_FIELD"
    GREENS = "GREENS"
    HIERARCHY = "HIERARCHY"
    OUT_DEMAND = "OUT_DEMAND"
    OUT_SUMMARY = "OUT_SUMMARY"

    def name(self):
        return "greenaccess"

    def displayName(self):
        return self.tr("Green Space Access")

    def shortHelpString(self):
        return self.tr(
            "Does everyone have a park NEARBY - and a big one within "
            "reach? Tests the classic park HIERARCHY standard on real "
            "street-network distances: every class pairs a minimum size "
            "with a maximum distance, e.g. '0.5=300, 2=800, 10=2000' "
            "reads as a pocket park (0.5 ha or more) within 300 m, a "
            "neighbourhood park (2 ha) within 800 m and a district park "
            "(10 ha) within 2 km.\n\n"
            "Each demand point (buildings, blocks, addresses; population "
            "optional) reports the network distance to the nearest green "
            "of every class, whether it meets the standard, and how many "
            "classes it meets in total. The summary table gives the "
            "covered population share per class - the plan's green "
            "scorecard - plus the citywide green area per capita in the "
            "log.\n\n"
            "Greens enter the network at their representative points; the "
            "leftover straight-line snap distance is added to the network "
            "distance. All standards are free-text parameters - bring "
            "your own regulation. Use a projected CRS.\n\n"
            "How to read the results\n"
            "- The summary's covered share per CLASS is the scorecard: "
            "cities commonly pass the pocket-park line and fail the "
            "district-park line - meaning greenery is fragmented into "
            "many small pieces with no large destination park in reach.\n"
            "- On the demand layer, met_n = 0 points are the true green "
            "deserts; points failing only the largest class need a BIG "
            "park (or a connection to one), which is a land acquisition "
            "problem, not a landscaping one.\n"
            "- Green per capita (log) and access can disagree: a city "
            "can be 'green' on paper while the greenery sits where "
            "nobody lives - this tool exists to expose exactly that.\n\n"
            "Using the results: map the uncovered population per class "
            "to locate and SIZE the next park (the failing class names "
            "the minimum hectares); test candidate sites by adding the "
            "polygon and rerunning the covered shares; where distance "
            "fails but a park lies just beyond a barrier, the remedy is "
            "a crossing, not a new park - check with Service Areas."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("Street network (lines)"),
            [QgsProcessing.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.DEMAND, self.tr("Demand (buildings / blocks / addresses)"),
            [QgsProcessing.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterField(
            self.POP_FIELD, self.tr("Population field (empty = 1 per point)"),
            parentLayerParameterName=self.DEMAND, optional=True,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.GREENS, self.tr("Public green spaces (polygons)"),
            [QgsProcessing.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterString(
            self.HIERARCHY,
            self.tr("Hierarchy classes 'min_ha=max_dist, ...'"),
            "0.5=300, 2=800, 10=2000"))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_DEMAND, self.tr("Demand with green access")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_SUMMARY, self.tr("Coverage per class"),
            type=QgsProcessing.TypeVector))

    def processAlgorithm(self, parameters, context, feedback):
        network = self.parameterAsSource(parameters, self.NETWORK, context)
        demand = self.parameterAsSource(parameters, self.DEMAND, context)
        pop_f = self.parameterAsString(parameters, self.POP_FIELD, context)
        greens = self.parameterAsSource(parameters, self.GREENS, context)
        hier_text = self.parameterAsString(parameters, self.HIERARCHY, context)
        self.require_projected(network, "Street network")
        try:
            classes = green.parse_hierarchy(hier_text)
        except ValueError as exc:
            raise QgsProcessingException(str(exc))

        polylines, _f = self.source_polylines(network)
        graph = graphs.build_node_graph(polylines)
        crs = network.sourceCrs()
        xform = context.transformContext()
        d_xy, d_feats = self.source_points(demand, crs, xform)
        d_nodes = graphs.nearest_nodes(graph, d_xy)

        g_xy, g_feats = self.source_points(greens, crs, xform)
        g_nodes = graphs.nearest_nodes(graph, g_xy)
        g_area = np.asarray([f.geometry().area() for f in g_feats])
        g_snap = np.hypot(g_xy[:, 0] - graph.node_xy[g_nodes, 0],
                          g_xy[:, 1] - graph.node_xy[g_nodes, 1])

        pop_i = demand.fields().lookupField(pop_f) if pop_f else -1
        pops = np.ones(len(d_feats))
        if pop_i >= 0:
            for i, f in enumerate(d_feats):
                try:
                    pops[i] = max(0.0, float(f.attributes()[pop_i]))
                except (TypeError, ValueError):
                    pops[i] = 0.0

        # one multi-source Dijkstra per hierarchy class
        per_class = []
        for min_ha, max_dist in classes:
            qual = np.where(g_area >= min_ha * 10000.0)[0]
            if not len(qual):
                per_class.append(None)
                feedback.pushWarning(self.tr(
                    f"No green space reaches {min_ha:g} ha - that class "
                    "covers nobody."))
                continue
            dist, label = paths.multi_source_offset(
                graph.indptr, graph.adj_node, graph.adj_cost,
                graph.num_nodes, g_nodes[qual], g_snap[qual])
            per_class.append(dist[d_nodes])
        feedback.pushInfo(self.tr(
            f"{len(g_feats)} greens against {len(classes)} classes for "
            f"{len(d_feats)} demand points."))

        specs = []
        for k, (min_ha, max_dist) in enumerate(classes):
            specs.append((f"d_c{k + 1}", DOUBLE))
            specs.append((f"ok_c{k + 1}", INT))
        specs.append(("classes_met", INT))
        fields = self.make_fields(*specs, base=demand.fields())
        sink, dest = self.parameterAsSink(
            parameters, self.OUT_DEMAND, context, fields,
            QgsWkbTypes.Point, crs)
        n_base = len(demand.fields())
        met_pop = np.zeros(len(classes))
        for i, feat in enumerate(d_feats):
            if feedback.isCanceled():
                break
            extra = []
            n_met = 0
            for k, (min_ha, max_dist) in enumerate(classes):
                dist = per_class[k]
                dval = float(dist[i]) if dist is not None else np.inf
                ok = 1 if np.isfinite(dval) and dval <= max_dist else 0
                n_met += ok
                if ok:
                    met_pop[k] += pops[i]
                extra += [None if not np.isfinite(dval) else round(dval, 1),
                          ok]
            extra.append(n_met)
            out = QgsFeature(fields)
            out.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*d_xy[i])))
            out.setAttributes(list(feat.attributes())[:n_base] + extra)
            sink.addFeature(out, QgsFeatureSink.FastInsert)

        s_fields = self.make_fields(
            ("class", INT), ("min_ha", DOUBLE), ("max_dist", DOUBLE),
            ("covered_pop", DOUBLE), ("coverage_pct", DOUBLE),
            ("n_greens", INT))
        s_sink, s_dest = self.parameterAsSink(
            parameters, self.OUT_SUMMARY, context, s_fields,
            QgsWkbTypes.NoGeometry, QgsCoordinateReferenceSystem())
        total_pop = float(pops.sum()) or 1.0
        for k, (min_ha, max_dist) in enumerate(classes):
            n_q = int((g_area >= min_ha * 10000.0).sum())
            feat = QgsFeature(s_fields)
            feat.setAttributes([
                k + 1, min_ha, max_dist, round(float(met_pop[k]), 1),
                round(100.0 * met_pop[k] / total_pop, 2), n_q])
            s_sink.addFeature(feat, QgsFeatureSink.FastInsert)
            feedback.pushInfo(self.tr(
                f"Class {k + 1} ({min_ha:g} ha within {max_dist:g}): "
                f"{100.0 * met_pop[k] / total_pop:.1f} percent covered."))
        feedback.pushInfo(self.tr(
            f"Citywide green provision: "
            f"{float(g_area.sum()) / total_pop:.1f} m2 per capita."))
        return {self.OUT_DEMAND: dest, self.OUT_SUMMARY: s_dest}

    def createInstance(self):
        return GreenAccessAlgorithm()
