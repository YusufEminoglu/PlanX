# -*- coding: utf-8 -*-
"""Capacitated Allocation: nearest facility WITH free capacity, spill when full."""
from __future__ import annotations

import numpy as np

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

from .base import DOUBLE, GROUP_OPTIMIZE, INT, PlanXAlgorithm, STRING
from ..engine import graphs, optimize, paths


class CapacitatedAllocationAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_OPTIMIZE
    ICON = "tool_capacitatedallocation.png"
    NETWORK = "NETWORK"
    DEMAND = "DEMAND"
    POP_FIELD = "POP_FIELD"
    FACILITIES = "FACILITIES"
    FACILITY_ID = "FACILITY_ID"
    CAPACITY_FIELD = "CAPACITY_FIELD"
    MAX_COST = "MAX_COST"
    OUT_DEMAND = "OUT_DEMAND"
    OUT_FACILITIES = "OUT_FACILITIES"

    def name(self):
        return "capacitatedallocation"

    def displayName(self):
        return self.tr("Capacitated Allocation (Nearest with Capacity)")

    def shortHelpString(self):
        return self.tr(
            "Allocates demand to fixed facilities while RESPECTING their "
            "capacity - the realistic companion to Facility Adequacy (which "
            "assigns everyone to the nearest facility and only flags the "
            "overload afterwards).\n\n"
            "Each demand point is sent, in full, to the nearest facility "
            "over the street network that still has room; when its nearest "
            "facility is already full it spills to the next-nearest one with "
            "free capacity, within the catchment. Points that fit nowhere in "
            "reach are left uncovered - a true picture of who would be turned "
            "away once capacity bites.\n\n"
            "Outputs:\n"
            "- Demand: assigned facility, network cost, status "
            "(Assigned / Spilled / Uncovered) and the nearest facility for "
            "reference;\n"
            "- Facilities: assigned load, remaining capacity, utilization "
            "and status (Full / Has space / Unused).\n\n"
            "A fast greedy heuristic (cheapest eligible pairs first), not a "
            "global optimum; demand points are not split. Population defaults "
            "to 1 per point. Use a projected CRS.\n\n"
            "How to read the results\n"
            "- 'Spilled' is the diagnostic gold: those people have a "
            "facility nearby but no room in it - compare net_cost with "
            "the cost to their nearest to see the extra distance "
            "capacity shortages impose. Many spills around one facility "
            "= expand THAT facility.\n"
            "- 'Uncovered' = turned away entirely within the catchment: "
            "the true unmet demand once seats are counted (Facility "
            "Adequacy would still have assigned them and only flagged "
            "overload).\n"
            "- Facilities 'Unused' while others are Full: geography puts "
            "them on the wrong side of demand or a barrier - relocation "
            "candidates.\n"
            "- Whole-point assignment can strand slack: a facility with "
            "remaining capacity smaller than any nearby point's "
            "population stays 'Has space' yet accepts no one.\n\n"
            "Using the results: this is the enrolment-planning view - "
            "size capacity expansions by the spilled+uncovered "
            "population per catchment; test 'expand vs build new' by "
            "editing capacities vs adding a facility and rerunning; "
            "quote 'X residents beyond reach once capacity bites' "
            "rather than distance-only coverage."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("Street network (lines)"),
            [QgsProcessing.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.DEMAND, self.tr("Demand (buildings / address points)"),
            [QgsProcessing.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterField(
            self.POP_FIELD, self.tr("Population field (empty = 1 per point)"),
            parentLayerParameterName=self.DEMAND, optional=True,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.FACILITIES, self.tr("Facilities"),
            [QgsProcessing.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterField(
            self.FACILITY_ID, self.tr("Facility ID field"),
            parentLayerParameterName=self.FACILITIES))
        self.addParameter(QgsProcessingParameterField(
            self.CAPACITY_FIELD, self.tr("Capacity field (persons)"),
            parentLayerParameterName=self.FACILITIES,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.MAX_COST, self.tr("Maximum network cost (catchment, map units)"),
            QgsProcessingParameterNumber.Double, 500.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_DEMAND, self.tr("Demand allocation")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_FACILITIES, self.tr("Facility load")))

    def processAlgorithm(self, parameters, context, feedback):
        network = self.parameterAsSource(parameters, self.NETWORK, context)
        demand = self.parameterAsSource(parameters, self.DEMAND, context)
        facilities = self.parameterAsSource(parameters, self.FACILITIES, context)
        pop_field = self.parameterAsString(parameters, self.POP_FIELD, context)
        fac_id = self.parameterAsString(parameters, self.FACILITY_ID, context)
        cap_field = self.parameterAsString(parameters, self.CAPACITY_FIELD, context)
        max_cost = self.parameterAsDouble(parameters, self.MAX_COST, context)
        self.require_projected(network, "Street network")

        polylines, _ = self.source_polylines(network)
        graph = graphs.build_node_graph(polylines)
        crs = network.sourceCrs()
        xform = context.transformContext()
        d_xy, d_feats = self.source_points(demand, crs, xform)
        f_xy, f_feats = self.source_points(facilities, crs, xform)
        d_nodes = graphs.nearest_nodes(graph, d_xy)
        f_nodes = graphs.nearest_nodes(graph, f_xy)

        pop_idx = demand.fields().lookupField(pop_field) if pop_field else -1
        fid_idx = facilities.fields().lookupField(fac_id)
        cap_idx = facilities.fields().lookupField(cap_field)

        def pop_of(feat):
            if pop_idx < 0:
                return 1.0
            try:
                return max(0.0, float(feat.attributes()[pop_idx]))
            except (TypeError, ValueError):
                return 0.0

        def cap_of(feat):
            try:
                return max(0.0, float(feat.attributes()[cap_idx]))
            except (TypeError, ValueError):
                return 0.0

        w = np.array([pop_of(f) for f in d_feats])
        cap = np.array([cap_of(f) for f in f_feats])
        f_ids = [str(f.attributes()[fid_idx]) for f in f_feats]

        feedback.pushInfo(self.tr(
            f"Computing network distances: {len(f_feats)} facilities x "
            f"{len(d_feats)} demand points (catchment {max_cost:g})..."))
        dist = paths.many_to_many(graph.indptr, graph.adj_node, graph.adj_cost,
                                  graph.num_nodes, f_nodes, cutoff=max_cost,
                                  cancel=feedback.isCanceled)
        D = dist[:, d_nodes]
        res = optimize.capacitated_assign(D, w, cap, max_cost=None)
        assign = res["assign"]
        cost = res["cost"]
        spilled = res["spilled"]
        nearest = res["nearest"]
        load = res["load"]
        remaining = res["remaining"]

        # ---------------------------------------------------- demand out
        d_fields = self.make_fields(
            ("facility", STRING), ("net_cost", DOUBLE), ("status", STRING),
            ("nearest", STRING), ("covered", INT), base=demand.fields())
        d_sink, d_dest = self.parameterAsSink(
            parameters, self.OUT_DEMAND, context, d_fields,
            QgsWkbTypes.Point, crs)
        n_dem = len(demand.fields())
        covered_pop = total_pop = 0.0
        n_uncov = n_spill = 0
        for i, feat in enumerate(d_feats):
            if feedback.isCanceled():
                break
            total_pop += float(w[i])
            j = int(assign[i])
            if j < 0:
                status, fac, c, cov = "Uncovered", "", -1.0, 0
                n_uncov += 1
            else:
                cov = 1
                covered_pop += float(w[i])
                fac = f_ids[j]
                c = round(float(cost[i]), 3)
                if bool(spilled[i]):
                    status = "Spilled"
                    n_spill += 1
                else:
                    status = "Assigned"
            near = f_ids[int(nearest[i])] if int(nearest[i]) >= 0 else ""
            out = QgsFeature(d_fields)
            out.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*d_xy[i])))
            out.setAttributes(list(feat.attributes())[:n_dem]
                              + [fac, c, status, near, cov])
            d_sink.addFeature(out, QgsFeatureSink.FastInsert)

        # ------------------------------------------------- facilities out
        f_fields = self.make_fields(
            ("facility", STRING), ("capacity", DOUBLE), ("assigned", DOUBLE),
            ("remaining", DOUBLE), ("utilization", DOUBLE), ("status", STRING))
        f_sink, f_dest = self.parameterAsSink(
            parameters, self.OUT_FACILITIES, context, f_fields,
            QgsWkbTypes.Point, crs)
        for j, feat in enumerate(f_feats):
            ld = float(load[j])
            rem = float(remaining[j])
            cp = float(cap[j])
            util = ld / cp if cp > 0 else (0.0 if ld == 0 else 9999.0)
            if ld <= 0:
                status = "Unused"
            elif rem <= 1e-9:
                status = "Full"
            else:
                status = "Has space"
            out = QgsFeature(f_fields)
            out.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*f_xy[j])))
            out.setAttributes([f_ids[j], round(cp, 2), round(ld, 2),
                               round(rem, 2), round(util, 3), status])
            f_sink.addFeature(out, QgsFeatureSink.FastInsert)

        share = covered_pop / total_pop if total_pop > 0 else 0.0
        feedback.pushInfo(self.tr(
            f"Covered population: {covered_pop:g} of {total_pop:g} "
            f"({share:.1%}); {n_spill} spilled to a farther facility, "
            f"{n_uncov} point(s) uncovered (no facility with room in reach)."))
        return {self.OUT_DEMAND: d_dest, self.OUT_FACILITIES: f_dest}

    def createInstance(self):
        return CapacitatedAllocationAlgorithm()
