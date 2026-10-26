# -*- coding: utf-8 -*-
"""Traffic Assignment: step four of the four-step model (user equilibrium)."""
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
from .base import DOUBLE, GROUP_DEMAND, INT, PlanXAlgorithm, STRING
from ..engine import assignment, graphs


def _number(value, fallback=None):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return fallback
    return out if np.isfinite(out) else fallback


def _rounded(value, digits=3):
    if value is None or not np.isfinite(value):
        return None
    return round(float(value), digits)


class TrafficAssignmentAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_DEMAND
    ICON = "tool_trafficassignment.png"
    RENDER_FIELD = "vc_max"

    NETWORK = "NETWORK"
    ZONES = "ZONES"
    ZONE_ID = "ZONE_ID"
    OD = "OD"
    ORIGIN_FIELD = "ORIGIN_FIELD"
    DEST_FIELD = "DEST_FIELD"
    FLOW_FIELD = "FLOW_FIELD"
    DEMAND_FACTOR = "DEMAND_FACTOR"
    TIME_FIELD = "TIME_FIELD"
    SPEED_FIELD = "SPEED_FIELD"
    DEFAULT_SPEED = "DEFAULT_SPEED"
    CAPACITY_FIELD = "CAPACITY_FIELD"
    LANES_FIELD = "LANES_FIELD"
    LANE_CAPACITY = "LANE_CAPACITY"
    METHOD = "METHOD"
    MAX_ITER = "MAX_ITER"
    GAP = "GAP"
    ALPHA = "ALPHA"
    BETA = "BETA"
    OUTPUT = "OUTPUT"
    CONVERGENCE = "CONVERGENCE"

    METHODS = ["Conjugate Frank-Wolfe user equilibrium", "Frank-Wolfe user equilibrium",
               "Method of successive averages (MSA)", "All-or-nothing (no congestion feedback)"]
    METHOD_KEYS = ("cfw", "fw", "msa", "aon")

    def name(self):
        return "trafficassignment"

    def displayName(self):
        return self.tr("Traffic Assignment (User Equilibrium)")

    def shortHelpString(self):
        return self.tr(
            "Loads an origin-destination matrix onto the street network and "
            "lets congestion redistribute it - step four of the four-step "
            "model, closing the chain Trip Generation -> Gravity "
            "Distribution -> Mode Split -> assignment.\n\n"
            "Each link slows down with its volume by the Bureau of Public "
            "Roads function t = t0 (1 + alpha (v/c)^beta). The equilibrium "
            "methods find Wardrop's user equilibrium - no driver can save "
            "time by switching route - by solving Beckmann's convex program. "
            "Conjugate Frank-Wolfe (default; Mitradjieva & Lindberg 2013) "
            "mixes each new search direction with the previous one and "
            "converges several times faster than plain Frank-Wolfe once the "
            "network is congested; Frank-Wolfe uses an exact line search on "
            "the shortest-path flows alone; MSA uses the fixed step 1/k; "
            "all-or-nothing loads every trip on its free-flow shortest path "
            "and shows what the network would carry with no congestion "
            "feedback at all.\n\n"
            "Inputs: the OD table written by Gravity Distribution (or any "
            "table with origin, destination and flow columns), the zone "
            "layer whose ids it uses, and the street network. Free-flow time "
            "comes from a time field (minutes) or from ground length over a "
            "speed field / default speed; capacity per direction from a "
            "capacity field or from lanes per direction x capacity per lane. "
            "One-way streets prepared by Prepare Network are honoured. The "
            "demand factor converts the OD table into the assignment period "
            "(e.g. 0.1 for a daily table and a peak hour that carries 10 "
            "percent of the day).\n\n"
            "Outputs: every street with its volume in each direction, v/c, "
            "a screening level-of-service letter, congested times and the "
            "vehicle-hours of delay it causes; and a convergence table with "
            "the relative gap of every iteration.\n\n"
            "How to read the results\n"
            "- vc_max above 1.0 is a link asked to carry more than its "
            "capacity: in reality the queue spreads in time (peak "
            "spreading), so read it as 'over capacity', not as a literal "
            "flow. 0.85-1.0 is the band where delay grows fastest.\n"
            "- The relative gap is the share of total travel time drivers "
            "could still save by switching to the current best route. "
            "Below 1e-3 the volumes are stable to the first decimal; a run "
            "that stopped at the iteration limit with a larger gap is not "
            "an equilibrium and the log says so.\n"
            "- delay_vh is where the congestion cost sits: rank links by it, "
            "not by v/c, to see which bottleneck costs the most "
            "vehicle-hours.\n"
            "- Intrazonal and unreachable demand never enter the network; "
            "both are reported in the log, so a small loaded total is "
            "explained rather than hidden.\n\n"
            "Using the results: run the base and the plan scenario with the "
            "same OD table and difference the volumes to see where a "
            "land-use change or a new link moves traffic; feed the volumes "
            "to Road Emissions or Noise Screen as AADT after scaling the "
            "period back to a day; compare all-or-nothing against "
            "equilibrium to see which corridors only work because traffic "
            "spills onto alternatives."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("Street network (lines)"),
            [QgsProcessing.SourceType.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.ZONES, self.tr("Zones (points or polygons)"),
            [QgsProcessing.SourceType.TypeVectorPolygon,
             QgsProcessing.SourceType.TypeVectorPoint]))
        self.addParameter(QgsProcessingParameterField(
            self.ZONE_ID, self.tr("Zone ID field"), parentLayerParameterName=self.ZONES))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.OD, self.tr("OD table (e.g. Gravity Distribution output)"),
            [QgsProcessing.SourceType.TypeVector]))
        self.addParameter(QgsProcessingParameterField(
            self.ORIGIN_FIELD, self.tr("Origin zone field"), defaultValue="origin_id",
            parentLayerParameterName=self.OD))
        self.addParameter(QgsProcessingParameterField(
            self.DEST_FIELD, self.tr("Destination zone field"), defaultValue="dest_id",
            parentLayerParameterName=self.OD))
        self.addParameter(QgsProcessingParameterField(
            self.FLOW_FIELD, self.tr("Flow field"), defaultValue="flow",
            parentLayerParameterName=self.OD,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.DEMAND_FACTOR, self.tr("Demand factor (OD flow -> vehicles in the period)"),
            QgsProcessingParameterNumber.Type.Double, 1.0, minValue=1e-9))
        self.addParameter(QgsProcessingParameterField(
            self.TIME_FIELD, self.tr("Free-flow time field, minutes (optional)"),
            parentLayerParameterName=self.NETWORK, optional=True,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterField(
            self.SPEED_FIELD, self.tr("Speed field, km/h (optional)"),
            parentLayerParameterName=self.NETWORK, optional=True,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.DEFAULT_SPEED, self.tr("Default free-flow speed (km/h)"),
            QgsProcessingParameterNumber.Type.Double, 40.0, minValue=1.0, maxValue=200.0))
        self.addParameter(QgsProcessingParameterField(
            self.CAPACITY_FIELD, self.tr("Capacity field, vehicles/hour per direction (optional)"),
            parentLayerParameterName=self.NETWORK, optional=True,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterField(
            self.LANES_FIELD, self.tr("Lanes per direction field (optional)"),
            parentLayerParameterName=self.NETWORK, optional=True,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.LANE_CAPACITY, self.tr("Capacity per lane (vehicles/hour)"),
            QgsProcessingParameterNumber.Type.Double, 900.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterEnum(
            self.METHOD, self.tr("Assignment method"), self.METHODS, defaultValue=0))
        self.addParameter(QgsProcessingParameterNumber(
            self.MAX_ITER, self.tr("Maximum iterations"),
            QgsProcessingParameterNumber.Type.Integer, 100, minValue=1, maxValue=1000))
        self.addParameter(QgsProcessingParameterNumber(
            self.GAP, self.tr("Relative gap to stop at"),
            QgsProcessingParameterNumber.Type.Double, 1e-4, minValue=1e-12, maxValue=0.5))
        self.addParameter(QgsProcessingParameterNumber(
            self.ALPHA, self.tr("BPR alpha"),
            QgsProcessingParameterNumber.Type.Double, assignment.BPR_ALPHA, minValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.BETA, self.tr("BPR beta"),
            QgsProcessingParameterNumber.Type.Double, assignment.BPR_BETA, minValue=0.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Loaded network"), type=QgsProcessing.SourceType.TypeVectorLine))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.CONVERGENCE, self.tr("Convergence"), type=QgsProcessing.SourceType.TypeVector))

    # ------------------------------------------------------------------ #
    def processAlgorithm(self, parameters, context, feedback):
        network = self.parameterAsSource(parameters, self.NETWORK, context)
        zones = self.parameterAsSource(parameters, self.ZONES, context)
        od = self.parameterAsSource(parameters, self.OD, context)
        zone_id_f = self.parameterAsString(parameters, self.ZONE_ID, context)
        o_field = self.parameterAsString(parameters, self.ORIGIN_FIELD, context)
        d_field = self.parameterAsString(parameters, self.DEST_FIELD, context)
        f_field = self.parameterAsString(parameters, self.FLOW_FIELD, context)
        factor = self.parameterAsDouble(parameters, self.DEMAND_FACTOR, context)
        time_f = self.parameterAsString(parameters, self.TIME_FIELD, context)
        speed_f = self.parameterAsString(parameters, self.SPEED_FIELD, context)
        default_speed = self.parameterAsDouble(parameters, self.DEFAULT_SPEED, context)
        cap_f = self.parameterAsString(parameters, self.CAPACITY_FIELD, context)
        lanes_f = self.parameterAsString(parameters, self.LANES_FIELD, context)
        lane_cap = self.parameterAsDouble(parameters, self.LANE_CAPACITY, context)
        method = self.METHOD_KEYS[self.parameterAsEnum(parameters, self.METHOD, context)]
        max_iter = self.parameterAsInt(parameters, self.MAX_ITER, context)
        gap_tol = self.parameterAsDouble(parameters, self.GAP, context)
        alpha = self.parameterAsDouble(parameters, self.ALPHA, context)
        beta = self.parameterAsDouble(parameters, self.BETA, context)
        self.require_projected(network, "Street network")
        crs = network.sourceCrs()

        graph, polylines, line_feats = self.network_graph(network, use_prepared_costs=False)
        units = _units.GroundUnits(crs, context.transformContext())
        per_unit = units.scale(network.sourceExtent())
        ground_len = graph.edge_len / per_unit

        def edge_values(field_name):
            if not field_name:
                return None
            index = network.fields().lookupField(field_name)
            if index < 0:
                raise QgsProcessingException(f"Field '{field_name}' is not on the network.")
            return [_number(f.attributes()[index]) for f in line_feats]

        times = edge_values(time_f)
        speeds = edge_values(speed_f)
        caps = edge_values(cap_f)
        lanes = edge_values(lanes_f)

        # Free-flow minutes and capacity per EDGE, then per directed arc.
        t0_edge = np.empty(graph.num_edges)
        cap_edge = np.empty(graph.num_edges)
        n_speed_default = n_cap_default = 0
        for e in range(graph.num_edges):
            t = times[e] if times is not None else None
            if t is None or t <= 0:
                s = speeds[e] if speeds is not None else None
                if s is None or s <= 0:
                    s = default_speed
                    n_speed_default += speeds is not None
                t = ground_len[e] / 1000.0 / s * 60.0
            t0_edge[e] = max(t, 1e-6)
            c = caps[e] if caps is not None else None
            if c is None or c <= 0:
                ln = lanes[e] if lanes is not None else None
                if ln is None or ln <= 0:
                    ln = 1.0
                    n_cap_default += lanes is not None
                c = ln * lane_cap
            cap_edge[e] = c
        if n_speed_default:
            feedback.pushWarning(self.tr(
                f"{n_speed_default} street(s) had no usable speed - the default "
                f"{default_speed:g} km/h was used."))
        if n_cap_default:
            feedback.pushWarning(self.tr(
                f"{n_cap_default} street(s) had no usable lane count - one lane "
                "per direction was assumed."))

        arc_edge = graph.adj_edge.astype(np.int64)
        net = assignment.ArcNetwork(graph.indptr, graph.adj_node, graph.num_nodes,
                                    t0_edge[arc_edge])
        arc_forward = graph.edge_from[arc_edge] == net.arc_from
        t0 = t0_edge[arc_edge]
        cap = cap_edge[arc_edge]

        # Zones -> nodes, OD table -> matrix.
        z_xy, z_feats = self.source_points(zones, crs, context.transformContext())
        z_nodes = graphs.nearest_nodes(graph, z_xy)
        zid_idx = zones.fields().lookupField(zone_id_f)
        position = {}
        for i, feat in enumerate(z_feats):
            key = str(feat.attributes()[zid_idx])
            if key in position:
                raise QgsProcessingException(
                    f"Zone id '{key}' occurs more than once in the zone layer - "
                    "an OD row naming it would be ambiguous.")
            position[key] = i
        oi = od.fields().lookupField(o_field)
        di = od.fields().lookupField(d_field)
        fi = od.fields().lookupField(f_field)
        if min(oi, di, fi) < 0:
            raise QgsProcessingException("The OD table lacks the origin, destination or flow field.")
        n_z = len(z_feats)
        demand = np.zeros((n_z, n_z))
        unknown = 0
        unknown_flow = 0.0
        for row in od.getFeatures():
            attrs = row.attributes()
            flow = _number(attrs[fi], 0.0)
            if flow <= 0:
                continue
            o = position.get(str(attrs[oi]))
            d = position.get(str(attrs[di]))
            if o is None or d is None:
                unknown += 1
                unknown_flow += flow
                continue
            demand[o, d] += flow * factor
        if unknown:
            feedback.pushWarning(self.tr(
                f"{unknown} OD row(s) ({unknown_flow:,.1f} trips) name a zone the "
                "zone layer does not carry and were left out."))
        total = float(demand.sum())
        if total <= 0:
            raise QgsProcessingException(
                "The OD table carries no positive flow between known zones - "
                "there is nothing to assign.")
        feedback.pushInfo(self.tr(
            f"Graph: {graph.num_nodes} nodes / {net.num_arcs} directed arcs; "
            f"{n_z} zones; {total:,.1f} vehicles to assign ({method.upper()})."))
        if net.parallel:
            feedback.pushInfo(self.tr(
                f"{net.parallel} parallel arc(s) share their end nodes with a "
                "faster one and are not used for routing."))

        try:
            res = assignment.equilibrium(
                net, t0, cap, z_nodes, z_nodes, demand, method=method,
                max_iter=max_iter, gap_tol=gap_tol, alpha=alpha, beta=beta,
                cancel=feedback.isCanceled,
                progress=lambda fr: feedback.setProgress(int(90.0 * fr)))
        except ValueError as exc:
            raise QgsProcessingException(str(exc))

        hist = res["history"]
        last_gap = hist[-1]["gap"] if hist else float("nan")
        if method == "aon":
            feedback.pushInfo(self.tr(
                f"All-or-nothing: relative gap at the loaded costs {last_gap:.4g} - "
                "this is what congestion would make drivers re-route, and is why "
                "AON is not an equilibrium."))
        elif res["converged"]:
            feedback.pushInfo(self.tr(
                f"Converged after {res['iterations']} iteration(s): relative gap "
                f"{last_gap:.3g} <= {gap_tol:g}."))
        else:
            feedback.pushWarning(self.tr(
                f"NOT converged: {res['iterations']} iteration(s), relative gap "
                f"{last_gap:.3g} > {gap_tol:g}. Raise the iteration limit before "
                "reading the volumes as an equilibrium."))
        if res["intrazonal"] > 0:
            feedback.pushInfo(self.tr(
                f"{res['intrazonal']:,.1f} vehicle trip(s) start and end on the same "
                "network node (intrazonal) and are not on any street."))
        if res["unreachable"] > 0:
            feedback.pushWarning(self.tr(
                f"{res['unreachable']:,.1f} vehicle trip(s) have no route (one-way "
                "rules or a disconnected network) and were not assigned."))

        # Per edge, per direction.
        vol = res["volume"]
        tc = res["time"]
        E = graph.num_edges
        vol_ab = np.zeros(E)
        vol_ba = np.zeros(E)
        tc_ab = np.full(E, np.nan)
        tc_ba = np.full(E, np.nan)
        cap_ab = np.full(E, np.nan)
        cap_ba = np.full(E, np.nan)
        for k in range(net.num_arcs):
            e = arc_edge[k]
            if net.arc_from[k] == net.arc_to[k]:
                continue
            if arc_forward[k]:
                vol_ab[e] += vol[k]
                tc_ab[e] = tc[k]
                cap_ab[e] = cap[k]
            else:
                vol_ba[e] += vol[k]
                tc_ba[e] = tc[k]
                cap_ba[e] = cap[k]
        delay = vol * (tc - t0) / 60.0
        delay_edge = np.bincount(arc_edge, weights=delay, minlength=E)

        fields = self.make_fields(
            ("vol_ab", DOUBLE), ("vol_ba", DOUBLE), ("vol_total", DOUBLE),
            ("cap_ab", DOUBLE), ("cap_ba", DOUBLE), ("vc_ab", DOUBLE),
            ("vc_ba", DOUBLE), ("vc_max", DOUBLE), ("los", STRING),
            ("t0_min", DOUBLE), ("tc_ab_min", DOUBLE), ("tc_ba_min", DOUBLE),
            ("delay_vh", DOUBLE), ("link_m", DOUBLE),
            base=network.fields())
        sink, dest = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields, QgsWkbTypes.Type.LineString, crs)
        n_base = len(network.fields())
        over = 0
        for e in range(E):
            if feedback.isCanceled():
                break
            vc_ab = vol_ab[e] / cap_ab[e] if np.isfinite(cap_ab[e]) else None
            vc_ba = vol_ba[e] / cap_ba[e] if np.isfinite(cap_ba[e]) else None
            vcs = [v for v in (vc_ab, vc_ba) if v is not None]
            vc_max = max(vcs) if vcs else None
            over += vc_max is not None and vc_max > 1.0
            r = _rounded
            out = QgsFeature(fields)
            out.setGeometry(QgsGeometry.fromPolylineXY(
                [QgsPointXY(float(x), float(y)) for x, y in polylines[e]]))
            out.setAttributes(list(line_feats[e].attributes())[:n_base] + [
                r(vol_ab[e], 2), r(vol_ba[e], 2), r(vol_ab[e] + vol_ba[e], 2),
                r(cap_ab[e], 1), r(cap_ba[e], 1), r(vc_ab), r(vc_ba), r(vc_max),
                None if vc_max is None else assignment.level_of_service(vc_max),
                r(t0_edge[e], 4), r(tc_ab[e], 4), r(tc_ba[e], 4),
                r(delay_edge[e], 4), r(ground_len[e], 2)])
            sink.addFeature(out, QgsFeatureSink.Flag.FastInsert)

        conv_fields = self.make_fields(
            ("iteration", INT), ("rel_gap", DOUBLE), ("tstt_vh", DOUBLE),
            ("sptt_vh", DOUBLE), ("step", DOUBLE), ("objective", DOUBLE))
        csink, cdest = self.parameterAsSink(
            parameters, self.CONVERGENCE, context, conv_fields, QgsWkbTypes.Type.NoGeometry, crs)
        for h in hist:
            row = QgsFeature(conv_fields)
            row.setAttributes([int(h["iteration"]), float(h["gap"]), h["tstt"] / 60.0,
                               h["sptt"] / 60.0, float(h["step"]), h["objective"] / 60.0])
            csink.addFeature(row, QgsFeatureSink.Flag.FastInsert)

        vkt = float(np.sum(vol * ground_len[arc_edge])) / 1000.0
        vht = float(np.sum(vol * tc)) / 60.0
        feedback.pushInfo(self.tr(
            f"Vehicle-km {vkt:,.1f} | vehicle-hours {vht:,.2f} | delay "
            f"{float(delay.sum()):,.2f} veh-h | mean network speed "
            f"{(vkt / vht if vht > 0 else 0.0):.1f} km/h | {over} street(s) over capacity."))
        feedback.setProgress(100)
        return {self.OUTPUT: dest, self.CONVERGENCE: cdest}

    def createInstance(self):
        return TrafficAssignmentAlgorithm()
