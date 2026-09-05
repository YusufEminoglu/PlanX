# -*- coding: utf-8 -*-
"""Facility Adequacy: capacity AND distance in one network check."""
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

from .base import DOUBLE, GROUP_STANDARDS, INT, PlanXAlgorithm, STRING
from ..engine import graphs, paths


class FacilityAdequacyAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_STANDARDS
    ICON = "tool_facilityadequacy.png"
    NETWORK = "NETWORK"
    DEMAND = "DEMAND"
    POP_FIELD = "POP_FIELD"
    FACILITIES = "FACILITIES"
    FACILITY_ID = "FACILITY_ID"
    CAPACITY_FIELD = "CAPACITY_FIELD"
    MAX_COST = "MAX_COST"
    FCA_DECAY = "FCA_DECAY"
    OUT_FACILITIES = "OUT_FACILITIES"
    OUT_DEMAND = "OUT_DEMAND"

    def name(self):
        return "facilityadequacy"

    def displayName(self):
        return self.tr("Facility Adequacy (Capacity + Distance)")

    def shortHelpString(self):
        return self.tr(
            "Checks whether facilities (schools, clinics, parks...) are "
            "adequate in BOTH dimensions at once:\n"
            "- distance: every demand point is assigned to its nearest "
            "facility over the street network, but only within the maximum "
            "cost (catchment) - beyond it the demand counts as uncovered;\n"
            "- capacity: assigned population is compared with each "
            "facility's capacity.\n\n"
            "Outputs: facilities with assigned population, utilization "
            "(assigned/capacity) and status (Adequate / Overloaded / "
            "Unused), plus demand points flagged covered/uncovered with "
            "their network cost. The log reports the covered population "
            "share - the headline number for plan QA.\n\n"
            "The output also includes an enhanced two-step floating catchment "
            "measure: each facility's capacity-to-catchment-demand ratio and "
            "each demand point's distance-decayed fca_access value.\n\n"
            "Population defaults to 1 per demand point when no field is "
            "given (i.e. counts).\n\n"
            "How to read the results\n"
            "- The covered-population share in the log is the pass/fail "
            "headline; everything else explains WHY it is not 100.\n"
            "- Facilities: utilization > 1 (Overloaded) = enough distance "
            "coverage but not enough seats - expand capacity, not "
            "location. 'Unused' with uncovered demand nearby = wrong "
            "location or a network barrier between them.\n"
            "- Uncovered demand points fall into two kinds - beyond every "
            "catchment (build new / extend catchment) versus inside a "
            "catchment whose facility is full (capacity problem). The "
            "combination of point flags and facility status separates "
            "them.\n\n"
            "Using the results: this is the tool for sizing AND siting "
            "school/health investments in one pass - a deficit shows up "
            "either as overload (add classrooms) or as uncovered pockets "
            "(add a facility); test a candidate site by adding it with a "
            "capacity and rerunning; watch max utilization over scenario "
            "years to time the investment."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("Street network (lines)"), [QgsProcessing.SourceType.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.DEMAND, self.tr("Demand (buildings / address points)"),
            [QgsProcessing.SourceType.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterField(
            self.POP_FIELD, self.tr("Population field (empty = 1 per point)"),
            parentLayerParameterName=self.DEMAND, optional=True,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.FACILITIES, self.tr("Facilities"), [QgsProcessing.SourceType.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterField(
            self.FACILITY_ID, self.tr("Facility ID field"),
            parentLayerParameterName=self.FACILITIES))
        self.addParameter(QgsProcessingParameterField(
            self.CAPACITY_FIELD, self.tr("Capacity field (persons)"),
            parentLayerParameterName=self.FACILITIES,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.MAX_COST, self.tr("Maximum network cost (catchment, map units)"),
            QgsProcessingParameterNumber.Type.Double, 500.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.FCA_DECAY, self.tr("E2SFCA Gaussian decay strength (0 = unweighted catchment)"),
            QgsProcessingParameterNumber.Type.Double, 1.0, minValue=0.0, maxValue=10.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_FACILITIES, self.tr("Facility adequacy")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_DEMAND, self.tr("Demand coverage")))

    def processAlgorithm(self, parameters, context, feedback):
        network = self.parameterAsSource(parameters, self.NETWORK, context)
        demand = self.parameterAsSource(parameters, self.DEMAND, context)
        facilities = self.parameterAsSource(parameters, self.FACILITIES, context)
        pop_field = self.parameterAsString(parameters, self.POP_FIELD, context)
        fac_id = self.parameterAsString(parameters, self.FACILITY_ID, context)
        cap_field = self.parameterAsString(parameters, self.CAPACITY_FIELD, context)
        max_cost = self.parameterAsDouble(parameters, self.MAX_COST, context)
        fca_decay = self.parameterAsDouble(parameters, self.FCA_DECAY, context)
        self.require_projected(network, "Street network")

        graph, polylines, _ = self.network_graph(network, use_prepared_costs=False)
        crs = network.sourceCrs()
        d_xy, d_feats = self.source_points(demand, crs, context.transformContext())
        f_xy, f_feats = self.source_points(facilities, crs, context.transformContext())
        d_nodes = graphs.nearest_nodes(graph, d_xy)
        f_nodes = graphs.nearest_nodes(graph, f_xy)

        pop_idx = demand.fields().lookupField(pop_field) if pop_field else -1
        fid_idx = facilities.fields().lookupField(fac_id)
        cap_idx = facilities.fields().lookupField(cap_field)

        unique_nodes, first_pos = np.unique(f_nodes, return_index=True)
        dist, label = paths.multi_source(graph.indptr, graph.adj_node, graph.adj_cost,
                                         graph.num_nodes, unique_nodes, cutoff=max_cost)

        def pop_of(feat):
            if pop_idx < 0:
                return 1.0
            try:
                return max(0.0, float(feat.attributes()[pop_idx]))
            except (TypeError, ValueError):
                return 0.0

        f_ids = [str(f.attributes()[fid_idx]) for f in f_feats]
        populations = np.asarray([pop_of(feature) for feature in d_feats], dtype=float)
        capacity_values = []
        for feature in f_feats:
            try:
                capacity_values.append(max(0.0, float(feature.attributes()[cap_idx])))
            except (TypeError, ValueError):
                capacity_values.append(0.0)
        facility_dist = paths.many_to_many(
            graph.indptr, graph.adj_node, graph.adj_cost, graph.num_nodes,
            f_nodes, cutoff=max_cost,
        )[:, d_nodes]
        decay_weights = np.where(
            np.isfinite(facility_dist),
            np.exp(-fca_decay * (facility_dist / max(max_cost, 1e-9)) ** 2),
            0.0,
        )
        catchment_demand = decay_weights @ populations
        supply_ratio = np.divide(
            np.asarray(capacity_values), catchment_demand,
            out=np.zeros(len(f_feats), dtype=float), where=catchment_demand > 0,
        )
        fca_access = decay_weights.T @ supply_ratio
        assigned = {}   # facility position -> population
        d_fields = self.make_fields(("covered", INT), ("facility", STRING),
                                    ("net_cost", DOUBLE), ("fca_access", DOUBLE), base=demand.fields())
        d_sink, d_dest = self.parameterAsSink(
            parameters, self.OUT_DEMAND, context, d_fields, QgsWkbTypes.Type.Point, crs)
        covered_pop = total_pop = 0.0
        n_dem = len(demand.fields())
        for i, feat in enumerate(d_feats):
            if feedback.isCanceled():
                break
            p = pop_of(feat)
            total_pop += p
            node = d_nodes[i]
            d = dist[node]
            lab = label[node]
            covered = bool(lab >= 0 and np.isfinite(d))
            fac = ""
            cost_val = -1.0
            if covered:
                j = int(first_pos[lab])
                fac = f_ids[j]
                cost_val = float(d)
                assigned[j] = assigned.get(j, 0.0) + p
                covered_pop += p
            out = QgsFeature(d_fields)
            out.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*d_xy[i])))
            out.setAttributes(list(feat.attributes())[:n_dem] +
                              [1 if covered else 0, fac, cost_val, float(fca_access[i])])
            d_sink.addFeature(out, QgsFeatureSink.Flag.FastInsert)

        f_fields = self.make_fields(
            ("facility", STRING), ("capacity", DOUBLE), ("assigned", DOUBLE),
            ("utilization", DOUBLE), ("status", STRING),
            ("catch_demand", DOUBLE), ("supply_ratio", DOUBLE))
        f_sink, f_dest = self.parameterAsSink(
            parameters, self.OUT_FACILITIES, context, f_fields, QgsWkbTypes.Type.Point, crs)
        overloaded = 0
        for j, feat in enumerate(f_feats):
            try:
                cap = float(feat.attributes()[cap_idx])
            except (TypeError, ValueError):
                cap = 0.0
            load = assigned.get(j, 0.0)
            util = load / cap if cap > 0 else (0.0 if load == 0 else 9999.0)
            if load == 0:
                status = "Unused"
            elif util <= 1.0:
                status = "Adequate"
            else:
                status = "Overloaded"
                overloaded += 1
            out = QgsFeature(f_fields)
            out.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*f_xy[j])))
            out.setAttributes([f_ids[j], cap, load, round(util, 3), status,
                               float(catchment_demand[j]), float(supply_ratio[j])])
            f_sink.addFeature(out, QgsFeatureSink.Flag.FastInsert)

        share = covered_pop / total_pop if total_pop > 0 else 0.0
        feedback.pushInfo(self.tr(
            f"Covered population: {covered_pop:g} of {total_pop:g} "
            f"({share:.1%}); {overloaded} facility(ies) overloaded."))
        return {self.OUT_FACILITIES: f_dest, self.OUT_DEMAND: d_dest}

    def createInstance(self):
        return FacilityAdequacyAlgorithm()
