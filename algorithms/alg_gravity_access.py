# -*- coding: utf-8 -*-
"""Gravity Accessibility: Hansen potential, cumulative opportunities and 2SFCA."""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsFeature,
    QgsFeatureSink,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsWkbTypes,
)

from . import _units
from .base import DOUBLE, GROUP_ACCESS, INT, PlanXAlgorithm
from ..engine import accessibility, graphs, paths

#: Destinations routed per Dijkstra batch: bounds memory at batch x nodes.
_BATCH = 128


def _reverse_csr(indptr, adj_node, weights, n):
    """The same graph with every arc turned round, as CSR arrays.

    Searching outward from a destination on the reversed graph gives the cost
    of reaching it FROM every node - the direction accessibility needs once
    one-way streets make the two differ.
    """
    counts = np.diff(np.asarray(indptr, dtype=np.int64))
    src = np.repeat(np.arange(n, dtype=np.int64), counts)
    dst = np.asarray(adj_node, dtype=np.int64)
    order = np.argsort(dst, kind="stable")
    rev_indptr = np.concatenate([[0], np.cumsum(np.bincount(dst, minlength=n))]).astype(np.int64)
    return rev_indptr, src[order].astype(np.int32), np.asarray(weights, dtype=np.float64)[order]


def _value(feature, index, fallback):
    if index < 0:
        return fallback
    try:
        out = float(feature.attributes()[index])
    except (TypeError, ValueError):
        return fallback
    return out if np.isfinite(out) and out >= 0 else fallback


class GravityAccessibilityAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_ACCESS
    ICON = "tool_gravityaccess.png"
    RENDER_FIELD = "acc_index"

    ORIGINS = "ORIGINS"
    POP_FIELD = "POP_FIELD"
    OPPORTUNITIES = "OPPORTUNITIES"
    SUPPLY_FIELD = "SUPPLY_FIELD"
    NETWORK = "NETWORK"
    COST_FIELD = "COST_FIELD"
    SPEED = "SPEED"
    DECAY = "DECAY"
    DECAY_PARAM = "DECAY_PARAM"
    CUTOFF = "CUTOFF"
    PER_POP = "PER_POP"
    OUTPUT = "OUTPUT"
    OUT_OPPORTUNITIES = "OUT_OPPORTUNITIES"

    DECAYS = ["Cumulative (step at the cutoff)", "Linear (cone to the cutoff)",
              "Negative exponential  exp(-p c)", "Gaussian  exp(-c^2 / 2p^2)",
              "Inverse power  c^-p", "Logistic (half weight at p minutes)"]

    def name(self):
        return "gravityaccess"

    def displayName(self):
        return self.tr("Gravity Accessibility (Hansen and 2SFCA)")

    def shortHelpString(self):
        return self.tr(
            "Measures how many opportunities - jobs, school places, hospital "
            "beds, shop floorspace - every origin can reach over the street "
            "network, weighted by how far away they are. Unlike the "
            "Multi-Amenity Access Score, which asks 'is there one within 15 "
            "minutes?', this counts the opportunities themselves.\n\n"
            "Three measures from one run:\n"
            "- acc_cum: cumulative opportunities within the cutoff (Wachs & "
            "Kumagai 1973) - 'jobs within 30 minutes'.\n"
            "- acc_hansen: Hansen (1959) potential, sum of supply x decay; "
            "acc_share is it as a share of all supply, acc_index scaled 0-100 "
            "by the best-served origin.\n"
            "- fca: two-step floating catchment area (Luo & Wang 2003) with a "
            "decayed catchment (Luo & Qi 2009) - supply per POP population "
            "after each facility's capacity is shared among everyone who can "
            "reach it. Needs the population field; without it fca is empty.\n\n"
            "Decay library: cumulative, linear, negative exponential (p = beta "
            "per minute), Gaussian (p = sigma in minutes), inverse power "
            "(p = beta) and logistic (p = minutes at which an opportunity "
            "counts half). Every kind is cut to zero beyond the cutoff, which "
            "keeps the measure local and the searches bounded. The parameter "
            "p is not used by the cumulative and linear kinds. Travel cost is "
            "a cost field in minutes, or ground length over the walking speed; "
            "one-way rules from Prepare Network are honoured in the "
            "origin-to-opportunity direction.\n\n"
            "How to read the results\n"
            "- acc_cum is the most quotable number ('residents here reach "
            "12 400 jobs within 30 minutes'); acc_hansen ranks the same places "
            "with nearer opportunities counted more.\n"
            "- fca is the fair-share measure: a place next to a large clinic "
            "that half the city also reaches scores lower than its raw "
            "Hansen value suggests. Population-weighted, the fca values add "
            "back up to the total supply that anyone can reach - the log "
            "prints that check.\n"
            "- The log states the decay's half-weight time; compare decays by "
            "it, not by their parameters.\n"
            "- Optional opportunities output: catchment_pop is the decayed "
            "population competing for each facility and ratio its supply per "
            "POP residents - the overloaded facilities are the low ratios.\n\n"
            "Using the results: map acc_index against income with Access "
            "Equity to test who is served; rerun with a proposed facility "
            "added to the opportunities to measure its catchment gain; use "
            "fca for health and school planning, where capacity matters, and "
            "acc_cum for jobs."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.ORIGINS, self.tr("Origins (homes, zones, grid cells)"),
            [QgsProcessing.SourceType.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterField(
            self.POP_FIELD, self.tr("Population field on origins (needed for 2SFCA)"),
            parentLayerParameterName=self.ORIGINS, optional=True,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.OPPORTUNITIES, self.tr("Opportunities (jobs, facilities...)"),
            [QgsProcessing.SourceType.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterField(
            self.SUPPLY_FIELD, self.tr("Supply field on opportunities (empty = 1 each)"),
            parentLayerParameterName=self.OPPORTUNITIES, optional=True,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("Street network (lines)"),
            [QgsProcessing.SourceType.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterField(
            self.COST_FIELD, self.tr("Travel-time field on network, minutes (empty = length / speed)"),
            parentLayerParameterName=self.NETWORK, optional=True,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.SPEED, self.tr("Travel speed when no time field is given (km/h)"),
            QgsProcessingParameterNumber.Type.Double, 4.8, minValue=0.5, maxValue=200.0))
        self.addParameter(QgsProcessingParameterEnum(
            self.DECAY, self.tr("Distance-decay function"), self.DECAYS, defaultValue=2))
        self.addParameter(QgsProcessingParameterNumber(
            self.DECAY_PARAM, self.tr("Decay parameter p (beta, sigma or half-weight minutes)"),
            QgsProcessingParameterNumber.Type.Double, 0.1, minValue=1e-6))
        self.addParameter(QgsProcessingParameterNumber(
            self.CUTOFF, self.tr("Cutoff (minutes)"),
            QgsProcessingParameterNumber.Type.Double, 30.0, minValue=0.5))
        self.addParameter(QgsProcessingParameterNumber(
            self.PER_POP, self.tr("Report 2SFCA supply per this many residents"),
            QgsProcessingParameterNumber.Type.Double, 1000.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Origins with accessibility")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_OPPORTUNITIES, self.tr("Opportunities with catchment"),
            optional=True, createByDefault=False))

    def processAlgorithm(self, parameters, context, feedback):
        origins = self.parameterAsSource(parameters, self.ORIGINS, context)
        opps = self.parameterAsSource(parameters, self.OPPORTUNITIES, context)
        network = self.parameterAsSource(parameters, self.NETWORK, context)
        pop_f = self.parameterAsString(parameters, self.POP_FIELD, context)
        supply_f = self.parameterAsString(parameters, self.SUPPLY_FIELD, context)
        cost_f = self.parameterAsString(parameters, self.COST_FIELD, context)
        speed = self.parameterAsDouble(parameters, self.SPEED, context)
        kind = accessibility.DECAY_KINDS[self.parameterAsEnum(parameters, self.DECAY, context)]
        param = self.parameterAsDouble(parameters, self.DECAY_PARAM, context)
        cutoff = self.parameterAsDouble(parameters, self.CUTOFF, context)
        per_pop = self.parameterAsDouble(parameters, self.PER_POP, context)
        self.require_projected(network, "Street network")
        crs = network.sourceCrs()

        graph, _polylines, _feats = self.network_graph(network, cost_f, use_prepared_costs=False)
        if cost_f:
            minutes = graph.adj_cost.copy()
            feedback.pushInfo(self.tr(f"Travel times read from '{cost_f}' as minutes."))
        else:
            per_unit = _units.GroundUnits(crs, context.transformContext()).scale(
                network.sourceExtent())
            metres_per_min = speed * 1000.0 / 60.0
            minutes = graph.adj_cost / per_unit / metres_per_min
        rev_indptr, rev_adj, rev_w = _reverse_csr(graph.indptr, graph.adj_node, minutes,
                                                  graph.num_nodes)

        o_xy, o_feats = self.source_points(origins, crs, context.transformContext())
        o_nodes = graphs.nearest_nodes(graph, o_xy)
        p_idx = origins.fields().lookupField(pop_f) if pop_f else -1
        population = np.asarray([_value(f, p_idx, 0.0) for f in o_feats])
        has_pop = p_idx >= 0 and population.sum() > 0
        if pop_f and not has_pop:
            feedback.pushWarning(self.tr(
                f"Population field '{pop_f}' sums to zero - 2SFCA cannot share "
                "supply among nobody and fca is left empty."))

        d_xy, d_feats = self.source_points(opps, crs, context.transformContext())
        d_nodes = graphs.nearest_nodes(graph, d_xy)
        s_idx = opps.fields().lookupField(supply_f) if supply_f else -1
        supply = np.asarray([_value(f, s_idx, 0.0) if s_idx >= 0 else 1.0 for f in d_feats])
        if supply.sum() <= 0:
            raise QgsProcessingException("The opportunities carry no positive supply.")

        try:
            acc = accessibility.AccessAccumulator(len(o_feats), population, kind, param, cutoff)
            accessibility.decay(np.array([0.0]), kind, param, cutoff)
        except ValueError as exc:
            raise QgsProcessingException(str(exc))
        hw = accessibility.half_weight_time(kind, param, cutoff)
        feedback.pushInfo(self.tr(
            f"Decay {kind}, p = {param:g}, cutoff {cutoff:g} min; "
            + (f"an opportunity {hw:.1f} min away counts half."
               if hw is not None else "no half-weight point inside the cutoff.")))

        # One search per distinct destination node; supply summed per node.
        uniq, inverse = np.unique(d_nodes, return_inverse=True)
        node_supply = np.bincount(inverse, weights=supply, minlength=len(uniq))
        n_batches = (len(uniq) + _BATCH - 1) // _BATCH
        for b in range(n_batches):
            if feedback.isCanceled():
                break
            chunk = uniq[b * _BATCH:(b + 1) * _BATCH]
            dist = paths.many_to_many(rev_indptr, rev_adj, rev_w, graph.num_nodes,
                                      chunk, cutoff=cutoff)
            acc.add_block(dist[:, o_nodes], node_supply[b * _BATCH:(b + 1) * _BATCH])
            feedback.setProgress(int(90.0 * (b + 1) / max(1, n_batches)))
        ratios_node = np.asarray(acc.ratios)
        catch_node = np.asarray(acc.catchment_pop)

        total_supply = float(supply.sum())
        best = float(acc.hansen.max()) if len(acc.hansen) else 0.0
        fields = self.make_fields(
            ("acc_cum", DOUBLE), ("acc_hansen", DOUBLE), ("acc_share", DOUBLE),
            ("acc_index", DOUBLE), ("n_opps", INT), ("near_min", DOUBLE), ("fca", DOUBLE),
            base=origins.fields())
        sink, dest = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields, QgsWkbTypes.Type.Point, crs)
        n_base = len(origins.fields())
        for i, feat in enumerate(o_feats):
            if feedback.isCanceled():
                break
            near = acc.nearest[i]
            out = QgsFeature(fields)
            out.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*o_xy[i])))
            out.setAttributes(list(feat.attributes())[:n_base] + [
                round(float(acc.cumulative[i]), 4),
                round(float(acc.hansen[i]), 4),
                round(float(acc.hansen[i]) / total_supply, 6),
                round(100.0 * float(acc.hansen[i]) / best, 3) if best > 0 else 0.0,
                int(acc.n_reached[i]),
                round(float(near), 3) if np.isfinite(near) and near <= cutoff else None,
                round(float(acc.fca[i]) * per_pop, 6) if has_pop else None])
            sink.addFeature(out, QgsFeatureSink.Flag.FastInsert)

        results = {self.OUTPUT: dest}
        if parameters.get(self.OUT_OPPORTUNITIES) is not None:
            ofields = self.make_fields(("supply", DOUBLE), ("catchment_pop", DOUBLE),
                                       ("ratio", DOUBLE), base=opps.fields())
            osink, odest = self.parameterAsSink(
                parameters, self.OUT_OPPORTUNITIES, context, ofields, QgsWkbTypes.Type.Point, crs)
            nb = len(opps.fields())
            for j, feat in enumerate(d_feats):
                node_pos = inverse[j]
                out = QgsFeature(ofields)
                out.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*d_xy[j])))
                # A node's ratio is its summed supply over its catchment; each
                # facility on the node gets its own supply over that catchment.
                pop_here = float(catch_node[node_pos]) if len(catch_node) > node_pos else 0.0
                out.setAttributes(list(feat.attributes())[:nb] + [
                    float(supply[j]), round(pop_here, 3) if has_pop else None,
                    round(float(supply[j]) / pop_here * per_pop, 6)
                    if has_pop and pop_here > 0 else None])
                osink.addFeature(out, QgsFeatureSink.Flag.FastInsert)
            results[self.OUT_OPPORTUNITIES] = odest

        reached = float(node_supply[catch_node > 0].sum()) if len(catch_node) else 0.0
        msg = (f"Supply {total_supply:,.1f}; origins reaching none within the cutoff: "
               f"{int((acc.n_reached == 0).sum())} of {len(o_feats)}.")
        if has_pop:
            weighted = float(np.dot(population, acc.fca))
            msg += (f" 2SFCA check: population-weighted access {weighted:,.3f} == supply "
                    f"reachable by anyone {reached:,.3f}.")
            unserved = float(population[acc.n_reached == 0].sum())
            msg += f" Residents with no opportunity in reach: {unserved:,.0f}."
        feedback.pushInfo(self.tr(msg))
        if has_pop and len(ratios_node):
            feedback.pushInfo(self.tr(
                f"Facility supply per {per_pop:g} residents: median "
                f"{float(np.median(ratios_node)) * per_pop:.4g}, min "
                f"{float(ratios_node.min()) * per_pop:.4g}, max "
                f"{float(ratios_node.max()) * per_pop:.4g}."))
        return results

    def createInstance(self):
        return GravityAccessibilityAlgorithm()
