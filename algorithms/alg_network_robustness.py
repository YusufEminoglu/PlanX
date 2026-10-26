# -*- coding: utf-8 -*-
"""Network Robustness: bridges, percolation under failure and attack, efficiency."""
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

from . import _units
from .base import DOUBLE, GROUP_NETWORK, INT, PlanXAlgorithm, STRING
from ..engine import centrality, graphs, robustness

#: Share of links removed when the efficiency loss is reported.
_EFFICIENCY_LOSS_SHARE = 0.05


def _drop(graph, removed, weights):
    """CSR arrays without the arcs of the removed edges."""
    keep = ~removed[graph.adj_edge]
    counts = np.diff(graph.indptr)
    src = np.repeat(np.arange(graph.num_nodes), counts)
    new_counts = np.bincount(src[keep], minlength=graph.num_nodes)
    indptr = np.concatenate([[0], np.cumsum(new_counts)]).astype(np.int64)
    return indptr, graph.adj_node[keep], weights[keep]


class NetworkRobustnessAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_NETWORK
    ICON = "tool_networkrobustness.png"
    RENDER_FIELD = "attack_rank"

    NETWORK = "NETWORK"
    COST_FIELD = "COST_FIELD"
    RUNS = "RUNS"
    SEED = "SEED"
    SAMPLE = "SAMPLE"
    BATCHES = "BATCHES"
    OUT_EDGES = "OUT_EDGES"
    OUT_CURVE = "OUT_CURVE"
    OUT_SUMMARY = "OUT_SUMMARY"

    def name(self):
        return "networkrobustness"

    def displayName(self):
        return self.tr("Network Robustness (Bridges and Percolation)")

    def shortHelpString(self):
        return self.tr(
            "How much of the street network holds together when links fail - "
            "the structural question that comes before any demand. Link "
            "Criticality asks which street costs THESE trips the most; this "
            "asks which streets the network cannot do without at all.\n\n"
            "- Bridges (Tarjan 1974): streets whose loss alone splits the "
            "network in two. A bridge is a single point of failure for every "
            "trip that crosses it.\n"
            "- Percolation: links are removed one at a time, at random "
            "(averaged over seeded runs, with the 10th-90th percentile band) "
            "and as a targeted attack on the highest edge betweenness - "
            "recalculated after every batch of removals (Holme et al. 2002), "
            "because the link that matters most changes once the first spines "
            "are gone - and the share of junctions still in the largest "
            "connected piece is "
            "recorded after every removal. R (Schneider et al. 2011) is the "
            "mean of that curve; f50 is the share of links whose loss leaves "
            "less than half the junctions connected.\n"
            "- Global efficiency (Latora & Marchiori 2001): mean of 1/d over "
            "all junction pairs, unreachable pairs counting zero, and how much "
            "of it is lost when the 5 percent most central links fail - "
            "against the same number failing at random.\n\n"
            "Betweenness and efficiency use a seeded sample of source "
            "junctions on large networks (the sample size parameter; 0 = all), "
            "so the run is repeatable.\n\n"
            "How to read the results\n"
            "- is_bridge = 1 marks the links to protect first: no detour "
            "exists. A long cul-de-sac is a chain of bridges by definition - "
            "Dead-End Analysis says which of them are only that.\n"
            "- A gap between R_random and R_attack means the network depends "
            "on a few spines; attack_rank orders them. On a regular grid the "
            "two can be close, because a grid has no spine - which is the "
            "finding, not a failure of the attack.\n"
            "- eff_loss_attack against eff_loss_random is the price of losing "
            "the spines rather than ordinary streets.\n\n"
            "Using the results: overlay the bridges and the first 1-2 percent "
            "of attack_rank with hazard layers (flood, debris, landslide) to "
            "find where one event cuts the city; propose a new link and rerun "
            "- a link that removes a bridge or lifts R_attack is a resilience "
            "investment you can quantify."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("Street network (lines)"),
            [QgsProcessing.SourceType.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterField(
            self.COST_FIELD, self.tr("Cost field for efficiency (empty = ground length)"),
            parentLayerParameterName=self.NETWORK, optional=True,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.RUNS, self.tr("Random failure runs"),
            QgsProcessingParameterNumber.Type.Integer, 20, minValue=1, maxValue=500))
        self.addParameter(QgsProcessingParameterNumber(
            self.SEED, self.tr("Random seed"),
            QgsProcessingParameterNumber.Type.Integer, 42, minValue=0))
        self.addParameter(QgsProcessingParameterNumber(
            self.SAMPLE, self.tr("Source junctions sampled for betweenness and efficiency (0 = all)"),
            QgsProcessingParameterNumber.Type.Integer, 400, minValue=0))
        self.addParameter(QgsProcessingParameterNumber(
            self.BATCHES, self.tr("Attack batches (betweenness recalculated after each)"),
            QgsProcessingParameterNumber.Type.Integer, 10, minValue=1, maxValue=200))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_EDGES, self.tr("Streets with robustness flags"),
            type=QgsProcessing.SourceType.TypeVectorLine))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_CURVE, self.tr("Percolation curve"),
            type=QgsProcessing.SourceType.TypeVector))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_SUMMARY, self.tr("Robustness summary"),
            type=QgsProcessing.SourceType.TypeVector))

    def processAlgorithm(self, parameters, context, feedback):
        network = self.parameterAsSource(parameters, self.NETWORK, context)
        cost_f = self.parameterAsString(parameters, self.COST_FIELD, context)
        runs = self.parameterAsInt(parameters, self.RUNS, context)
        seed = self.parameterAsInt(parameters, self.SEED, context)
        sample = self.parameterAsInt(parameters, self.SAMPLE, context)
        batches = self.parameterAsInt(parameters, self.BATCHES, context)
        self.require_projected(network, "Street network")
        crs = network.sourceCrs()

        graph, polylines, line_feats = self.network_graph(network, cost_f, use_prepared_costs=False)
        per_unit = _units.GroundUnits(crs, context.transformContext()).scale(network.sourceExtent())
        ground_len = graph.edge_len / per_unit
        weights = graph.adj_cost.copy() if cost_f else graph.adj_cost / per_unit
        n, m = graph.num_nodes, graph.num_edges
        rng = np.random.default_rng(seed)
        sources = None
        if sample and sample < n:
            sources = np.sort(rng.choice(n, size=sample, replace=False))
        feedback.pushInfo(self.tr(
            f"Graph: {n} junctions / {m} links; "
            + ("all junctions as sources." if sources is None
               else f"{len(sources)} sampled source junctions (seed {seed}).")))

        # 1. Bridges and components.
        is_bridge = robustness.bridges(n, graph.edge_from, graph.edge_to)
        labels, n_comp = graphs.weak_components(graph)
        giant = np.bincount(labels).max() / n if n else 0.0
        feedback.setProgress(10)

        # 2. Attack order: edge betweenness, recalculated on what is left after
        # each batch (ties broken by edge id). The intact network's betweenness
        # is also what the edge layer reports.
        edge_bc = None
        attack = []
        removed = np.zeros(m, dtype=bool)
        per_batch = max(1, int(np.ceil(m / float(batches))))
        while len(attack) < m:
            if feedback.isCanceled():
                break
            ip, an, w = _drop(graph, removed, weights)
            keep = ~removed[graph.adj_edge]
            _nbc, bc, _ = centrality.brandes_betweenness(
                ip, an, w, n, adj_edge=graph.adj_edge[keep], num_edges=m,
                sources=sources, cancel=feedback.isCanceled)
            if edge_bc is None:
                edge_bc = bc
            left = np.nonzero(~removed)[0]
            order = left[np.lexsort((left, -bc[left]))]
            take = order[:per_batch]
            attack.extend(int(e) for e in take)
            removed[take] = True
            feedback.setProgress(10 + int(40 * len(attack) / m))
        attack = np.asarray(attack, dtype=np.int64)
        attack_rank = np.empty(m, dtype=np.int64)
        attack_rank[attack] = np.arange(1, m + 1)

        # 3. Percolation curves.
        curve_attack = robustness.giant_component_curve(n, graph.edge_from, graph.edge_to, attack)
        random_curves = np.empty((runs, m + 1))
        for r in range(runs):
            if feedback.isCanceled():
                break
            random_curves[r] = robustness.giant_component_curve(
                n, graph.edge_from, graph.edge_to, rng.permutation(m))
        feedback.setProgress(65)
        mean_random = random_curves.mean(axis=0)

        # 4. Efficiency and its loss.
        eff = robustness.global_efficiency(graph.indptr, graph.adj_node, weights, n, sources,
                                           cancel=feedback.isCanceled)
        k = max(1, int(round(_EFFICIENCY_LOSS_SHARE * m)))
        removed = np.zeros(m, dtype=bool)
        removed[attack[:k]] = True
        ip, an, w = _drop(graph, removed, weights)
        eff_attack = robustness.global_efficiency(ip, an, w, n, sources)
        eff_random = []
        for r in range(min(runs, 5)):
            removed = np.zeros(m, dtype=bool)
            removed[rng.permutation(m)[:k]] = True
            ip, an, w = _drop(graph, removed, weights)
            eff_random.append(robustness.global_efficiency(ip, an, w, n, sources))
        feedback.setProgress(90)
        loss_attack = 1.0 - eff_attack / eff if eff > 0 else 0.0
        loss_random = 1.0 - float(np.mean(eff_random)) / eff if eff > 0 else 0.0

        # Outputs.
        fields = self.make_fields(
            ("is_bridge", INT), ("edge_btw", DOUBLE), ("attack_rank", INT),
            ("component", INT), ("link_m", DOUBLE), base=network.fields())
        sink, dest = self.parameterAsSink(
            parameters, self.OUT_EDGES, context, fields, QgsWkbTypes.Type.LineString, crs)
        nb = len(network.fields())
        for e in range(m):
            if feedback.isCanceled():
                break
            out = QgsFeature(fields)
            out.setGeometry(QgsGeometry.fromPolylineXY(
                [QgsPointXY(float(x), float(y)) for x, y in polylines[e]]))
            out.setAttributes(list(line_feats[e].attributes())[:nb] + [
                int(is_bridge[e]), round(float(edge_bc[e]) / 2.0, 3), int(attack_rank[e]),
                int(labels[graph.edge_from[e]]), round(float(ground_len[e]), 2)])
            sink.addFeature(out, QgsFeatureSink.Flag.FastInsert)

        cfields = self.make_fields(
            ("removed", DOUBLE), ("links_out", INT), ("gc_random", DOUBLE),
            ("gc_rand_p10", DOUBLE), ("gc_rand_p90", DOUBLE), ("gc_attack", DOUBLE))
        csink, cdest = self.parameterAsSink(
            parameters, self.OUT_CURVE, context, cfields, QgsWkbTypes.Type.NoGeometry, crs)
        steps = sorted(set(int(round(s * m / 100.0)) for s in range(101)))
        p10 = np.percentile(random_curves, 10, axis=0)
        p90 = np.percentile(random_curves, 90, axis=0)
        for s in steps:
            row = QgsFeature(cfields)
            row.setAttributes([round(s / m, 6) if m else 0.0, int(s),
                               round(float(mean_random[s]), 6), round(float(p10[s]), 6),
                               round(float(p90[s]), 6), round(float(curve_attack[s]), 6)])
            csink.addFeature(row, QgsFeatureSink.Flag.FastInsert)

        bridge_len = float(ground_len[is_bridge].sum())
        total_len = float(ground_len.sum())
        metrics = [
            ("junctions", float(n), "count"),
            ("links", float(m), "count"),
            ("components", float(n_comp), "count"),
            ("giant_share", float(giant), "share of junctions"),
            ("bridges", float(is_bridge.sum()), "count"),
            ("bridge_length_share", bridge_len / total_len if total_len > 0 else 0.0,
             "share of network length"),
            ("R_random", robustness.robustness_index(mean_random), "Schneider et al. 2011"),
            ("R_attack", robustness.robustness_index(curve_attack), "Schneider et al. 2011"),
            ("f50_random", robustness.critical_fraction(mean_random), "share of links"),
            ("f50_attack", robustness.critical_fraction(curve_attack), "share of links"),
            ("efficiency", eff, "1 / cost unit" if cost_f else "1 / m"),
            ("eff_loss_attack", loss_attack, f"share lost, top {k} links"),
            ("eff_loss_random", loss_random, f"share lost, {k} random links"),
        ]
        sfields = self.make_fields(("metric", STRING), ("value", DOUBLE), ("unit", STRING))
        ssink, sdest = self.parameterAsSink(
            parameters, self.OUT_SUMMARY, context, sfields, QgsWkbTypes.Type.NoGeometry, crs)
        for name, value, unit in metrics:
            row = QgsFeature(sfields)
            row.setAttributes([name, float(value), unit])
            ssink.addFeature(row, QgsFeatureSink.Flag.FastInsert)
            feedback.pushInfo(f"  {name}: {value:.6g} ({unit})")
        feedback.setProgress(100)
        return {self.OUT_EDGES: dest, self.OUT_CURVE: cdest, self.OUT_SUMMARY: sdest}

    def createInstance(self):
        return NetworkRobustnessAlgorithm()
