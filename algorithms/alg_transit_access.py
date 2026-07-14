# -*- coding: utf-8 -*-
"""Transit Travel-Time Access: walk + timetable earliest arrival to demand."""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureSink,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFile,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_TRANSIT, INT, PlanXAlgorithm, STRING
from .alg_gtfs_import import load_feed
from ..engine import graphs, paths, transit


class TransitAccessAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_TRANSIT
    ICON = "tool_transitaccess.png"
    FILE = "FILE"
    DAY = "DAY"
    DEPARTURE = "DEPARTURE"
    NETWORK = "NETWORK"
    ORIGINS = "ORIGINS"
    DEMAND = "DEMAND"
    WALK_SPEED = "WALK_SPEED"
    MAX_WALK = "MAX_WALK"
    MAX_TRANSFERS = "MAX_TRANSFERS"
    OUT_DEMAND = "OUT_DEMAND"

    def name(self):
        return "transitaccess"

    def displayName(self):
        return self.tr("Transit Travel-Time Access")

    def shortHelpString(self):
        return self.tr(
            "Door-to-door travel times WITH PUBLIC TRANSPORT: from the "
            "origin(s), walk to a stop on the street network, ride the "
            "timetable (with transfers), walk from the alighting stop to "
            "each destination - and compare against walking all the way. "
            "The transit sibling of the 15-minute-city tools.\n\n"
            "The timetable is read straight from a GTFS zip and answered "
            "with a RAPTOR-style earliest-arrival computation: board the "
            "first catchable trip, allow up to the given number of "
            "transfers (re-boarding at the same stop; walking legs happen "
            "on the street network before and after). Overtaking trips on "
            "one route are treated as first-in-first-out - the standard "
            "screening simplification.\n\n"
            "Multiple origin features act as one departure place (the "
            "best of them wins, e.g. the entrances of a campus). Each "
            "destination reports:\n"
            "- walk_min: walking all the way;\n"
            "- transit_min: walk + ride (+ transfer waits) + walk;\n"
            "- best_min and mode: which one wins;\n"
            "- saved_min: minutes transit saves (negative never happens - "
            "walking is kept when faster).\n\n"
            "Stops are matched to the street network by nearest node "
            "within the access-walk limit. Use a projected CRS for the "
            "network; the GTFS stops are reprojected automatically.\n\n"
            "How to read the results\n"
            "- saved_min is transit's value proposition per destination: "
            "where it is ~0, transit does not compete with walking - "
            "normal under ~1.5 km, damning at 5 km. Style best_min for "
            "the reachability map, mode for WHERE transit wins.\n"
            "- transit_min includes the honest costs riders feel: "
            "waiting for the first catchable trip and transfer waits. A "
            "destination that is 15 min at 08:00 and 40 min at 10:00 is "
            "frequency failing, not distance.\n"
            "- 'mode = walk' everywhere near a rail line usually means "
            "the access walk is the killer - check max walk distance "
            "and station entrances before blaming the timetable.\n\n"
            "Using the results: run from a proposed housing site to the "
            "daily destinations (jobs centre, schools, hospital) - "
            "best_min under ~30-40 makes 'transit-accessible' claims "
            "credible; test a timetable improvement by editing the GTFS "
            "(more trips) and rerunning; sweep departure hours to "
            "expose the all-day vs peak-only difference that averages "
            "hide."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(
            self.FILE, self.tr("GTFS feed (zip)"), extension="zip"))
        self.addParameter(QgsProcessingParameterString(
            self.DAY, self.tr("Service day YYYYMMDD (empty = first active)"),
            "", optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.DEPARTURE, self.tr("Departure time (hour of day)"),
            QgsProcessingParameterNumber.Type.Double, 8.0, minValue=0.0,
            maxValue=30.0))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("Street network (lines, projected CRS)"),
            [QgsProcessing.SourceType.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.ORIGINS, self.tr("Origin(s) - one departure place"),
            [QgsProcessing.SourceType.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.DEMAND, self.tr("Destinations (demand points)"),
            [QgsProcessing.SourceType.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterNumber(
            self.WALK_SPEED, self.tr("Walking speed (km/h)"),
            QgsProcessingParameterNumber.Type.Double, 4.8, minValue=0.5,
            maxValue=15.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.MAX_WALK, self.tr("Max access/egress walk (minutes)"),
            QgsProcessingParameterNumber.Type.Double, 10.0, minValue=1.0,
            maxValue=120.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.MAX_TRANSFERS, self.tr("Max transfers"),
            QgsProcessingParameterNumber.Type.Integer, 2, minValue=0, maxValue=5))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_DEMAND, self.tr("Destinations with travel times")))

    def processAlgorithm(self, parameters, context, feedback):
        path = self.parameterAsFile(parameters, self.FILE, context)
        day_text = self.parameterAsString(parameters, self.DAY, context)
        dep_hour = self.parameterAsDouble(parameters, self.DEPARTURE, context)
        network = self.parameterAsSource(parameters, self.NETWORK, context)
        origins = self.parameterAsSource(parameters, self.ORIGINS, context)
        demand = self.parameterAsSource(parameters, self.DEMAND, context)
        speed_kmh = self.parameterAsDouble(parameters, self.WALK_SPEED, context)
        max_walk_min = self.parameterAsDouble(parameters, self.MAX_WALK, context)
        max_transfers = self.parameterAsInt(parameters, self.MAX_TRANSFERS, context)
        self.require_projected(network, "Street network")

        gtfs, day, _services = load_feed(path, day_text, feedback)
        dep_sec = dep_hour * 3600.0
        speed = speed_kmh / 3.6  # m/s
        max_walk_sec = max_walk_min * 60.0

        polylines, _feats = self.source_polylines(network)
        graph = graphs.build_node_graph(polylines)
        w_sec = graph.adj_cost / speed  # walking seconds per CSR entry

        crs = network.sourceCrs()
        xform_ctx = context.transformContext()
        o_xy, _o = self.source_points(origins, crs, xform_ctx)
        d_xy, d_feats = self.source_points(demand, crs, xform_ctx)
        o_nodes = np.unique(graphs.nearest_nodes(graph, o_xy)).astype(np.int64)
        d_nodes = graphs.nearest_nodes(graph, d_xy)

        wgs = QgsCoordinateReferenceSystem("EPSG:4326")
        to_net = QgsCoordinateTransform(wgs, crs, xform_ctx)
        stop_pts = []
        for i in range(len(gtfs["stop_ids"])):
            p = to_net.transform(QgsPointXY(float(gtfs["stop_lon"][i]),
                                            float(gtfs["stop_lat"][i])))
            stop_pts.append((p.x(), p.y()))
        stop_xy = np.asarray(stop_pts)
        stop_nodes = graphs.nearest_nodes(graph, stop_xy)
        snap_off = np.hypot(stop_xy[:, 0] - graph.node_xy[stop_nodes, 0],
                            stop_xy[:, 1] - graph.node_xy[stop_nodes, 1])
        far = snap_off > (max_walk_sec * speed)
        if np.all(far):
            raise QgsProcessingException(
                "No GTFS stop lies near the street network - are the feed "
                "and the network from the same city (and the network in a "
                "projected CRS)?")

        # access walk: origin(s) -> every node (seconds)
        walk_from_o, _ = paths.multi_source(
            graph.indptr, graph.adj_node, w_sec, graph.num_nodes, o_nodes)

        access = {}
        for s in range(len(stop_nodes)):
            if far[s]:
                continue
            w = walk_from_o[stop_nodes[s]] + snap_off[s] / speed
            if w <= max_walk_sec:
                access[s] = dep_sec + w
        feedback.pushInfo(self.tr(
            f"{len(access)} stop(s) within a {max_walk_min:g} min access "
            f"walk; departure {day} at {dep_hour:g}:00, up to "
            f"{max_transfers} transfer(s)."))

        patterns, stop_patterns = transit.compile_day(gtfs, day)
        arrivals = transit.earliest_arrival(
            patterns, stop_patterns, len(gtfs["stop_ids"]), access,
            max_transfers=max_transfers)

        # egress: min over stops of (arrival + walk) via offset Dijkstra
        egress_nodes, offsets = [], []
        for s in range(len(stop_nodes)):
            if far[s] or not np.isfinite(arrivals[s]):
                continue
            egress_nodes.append(int(stop_nodes[s]))
            offsets.append(float(arrivals[s]) + snap_off[s] / speed)
        transit_at_node = np.full(graph.num_nodes, np.inf)
        if egress_nodes:
            transit_at_node, _ = paths.multi_source_offset(
                graph.indptr, graph.adj_node, w_sec, graph.num_nodes,
                np.asarray(egress_nodes), np.asarray(offsets))

        fields = self.make_fields(
            ("walk_min", DOUBLE), ("transit_min", DOUBLE),
            ("best_min", DOUBLE), ("saved_min", DOUBLE), ("mode", STRING),
            ("transfers_max", INT), base=demand.fields())
        sink, dest = self.parameterAsSink(
            parameters, self.OUT_DEMAND, context, fields,
            QgsWkbTypes.Type.Point, crs)
        n_base = len(demand.fields())

        n_transit = 0
        for i, feat in enumerate(d_feats):
            if feedback.isCanceled():
                break
            node = int(d_nodes[i])
            walk_min = float(walk_from_o[node]) / 60.0 \
                if np.isfinite(walk_from_o[node]) else None
            t_arr = transit_at_node[node]
            transit_min = (float(t_arr) - dep_sec) / 60.0 \
                if np.isfinite(t_arr) else None
            cands = [m for m in (walk_min, transit_min) if m is not None]
            best = min(cands) if cands else None
            if best is None:
                mode = "Unreachable"
                saved = None
            elif transit_min is not None and transit_min < (walk_min or np.inf):
                mode = "Transit"
                saved = round((walk_min - transit_min), 2) \
                    if walk_min is not None else None
                n_transit += 1
            else:
                mode = "Walk"
                saved = 0.0
            out = QgsFeature(fields)
            out.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*d_xy[i])))
            out.setAttributes(list(feat.attributes())[:n_base] + [
                None if walk_min is None else round(walk_min, 2),
                None if transit_min is None else round(transit_min, 2),
                None if best is None else round(best, 2),
                saved, mode, max_transfers])
            sink.addFeature(out, QgsFeatureSink.Flag.FastInsert)

        feedback.pushInfo(self.tr(
            f"{n_transit} of {len(d_feats)} destination(s) reached faster "
            "by transit."))
        return {self.OUT_DEMAND: dest}

    def createInstance(self):
        return TransitAccessAlgorithm()
