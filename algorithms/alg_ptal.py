# -*- coding: utf-8 -*-
"""PTAL: Public Transport Accessibility Level (Transport for London method)."""
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
    QgsProcessingParameterDefinition,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFile,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsWkbTypes,
)

from . import _units
from .alg_gtfs_import import load_feed
from .base import DOUBLE, GROUP_TRANSIT, INT, PlanXAlgorithm, STRING
from ..engine import graphs, paths, ptal

#: Stops routed per Dijkstra batch.
_BATCH = 128


class PTALAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_TRANSIT
    ICON = "tool_ptal.png"
    RENDER_FIELD = "ptal_rank"

    FILE = "FILE"
    DAY = "DAY"
    WINDOW_START = "WINDOW_START"
    WINDOW_END = "WINDOW_END"
    NETWORK = "NETWORK"
    ORIGINS = "ORIGINS"
    WALK_SPEED = "WALK_SPEED"
    BUS_CATCHMENT = "BUS_CATCHMENT"
    RAIL_CATCHMENT = "RAIL_CATCHMENT"
    BUS_RELIABILITY = "BUS_RELIABILITY"
    RAIL_RELIABILITY = "RAIL_RELIABILITY"
    OUTPUT = "OUTPUT"
    OUT_SUMMARY = "OUT_SUMMARY"

    def name(self):
        return "ptal"

    def displayName(self):
        return self.tr("Public Transport Accessibility Level (PTAL)")

    def shortHelpString(self):
        return self.tr(
            "Rates every place 0 to 6b by the public transport service it can "
            "walk to, with Transport for London's PTAL method (TfL 2015, "
            "'Assessing transport connectivity in London').\n\n"
            "For each place: every stop within the walk catchment - 8 minutes "
            "for bus and tram, 12 for rail and metro, walked on the street "
            "network - is a service access point. Each route counts once, at "
            "its nearest stop, with its frequency in the analysis window "
            "(TfL: 08:15-09:15). Waiting time = half the headway plus a "
            "reliability allowance (2 min bus, 0.75 min rail and tram); "
            "equivalent doorstep frequency EDF = 30 / (walk + wait). Per mode "
            "the best route counts in full and every other one at half; the "
            "modes add up to the accessibility index AI, which falls into "
            "the bands 0, 1a, 1b, 2, 3, 4, 5, 6a, 6b.\n\n"
            "Inputs: a GTFS zip, the street network (projected CRS) and the "
            "places to rate - typically a 100 m grid of points or address "
            "points. GTFS route_type decides the mode: metro, rail and "
            "monorail take the rail catchment; tram and light rail the bus "
            "catchment with rail reliability; everything else is bus.\n\n"
            "How to read the results\n"
            "- ptal is the band, ptal_ai the index behind it, ptal_rank the "
            "band as 0-8 for styling. 0 means no service within the "
            "catchments, 1a-2 poor, 3 moderate, 4-5 good, 6a-6b excellent.\n"
            "- ai_bus and ai_rail split the index by mode: a place at band 4 "
            "on buses alone is one timetable change away from band 2.\n"
            "- best_route is the route that contributes most - usually the "
            "one a resident would name.\n"
            "- PTAL measures service density at the doorstep, not where the "
            "services go; pair it with Transit Access for destinations.\n\n"
            "Using the results: TfL ties residential density ranges and "
            "parking standards to PTAL bands - map the bands against "
            "Residential Capacity to find sites under-using good transit; "
            "rerun with a new or more frequent route in the GTFS to measure "
            "how many places move up a band."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(
            self.FILE, self.tr("GTFS feed (zip)"), extension="zip"))
        self.addParameter(QgsProcessingParameterString(
            self.DAY, self.tr("Service day YYYYMMDD (empty = first active)"),
            "", optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.WINDOW_START, self.tr("Window start (hour of day; TfL 8.25 = 08:15)"),
            QgsProcessingParameterNumber.Type.Double, 8.25, minValue=0.0, maxValue=30.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.WINDOW_END, self.tr("Window end (hour of day; TfL 9.25 = 09:15)"),
            QgsProcessingParameterNumber.Type.Double, 9.25, minValue=0.0, maxValue=30.0))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("Street network (lines, projected CRS)"),
            [QgsProcessing.SourceType.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.ORIGINS, self.tr("Places to rate (grid points, addresses, parcels)"),
            [QgsProcessing.SourceType.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterNumber(
            self.WALK_SPEED, self.tr("Walking speed (km/h; TfL 4.8 = 80 m/min)"),
            QgsProcessingParameterNumber.Type.Double, 4.8, minValue=0.5, maxValue=15.0))
        for key, label, default in (
                (self.BUS_CATCHMENT, "Bus and tram walk catchment (minutes)", ptal.BUS_CATCHMENT_MIN),
                (self.RAIL_CATCHMENT, "Rail and metro walk catchment (minutes)", ptal.RAIL_CATCHMENT_MIN),
                (self.BUS_RELIABILITY, "Bus reliability allowance (minutes)", ptal.BUS_RELIABILITY_MIN),
                (self.RAIL_RELIABILITY, "Rail and tram reliability allowance (minutes)",
                 ptal.RAIL_RELIABILITY_MIN)):
            param = QgsProcessingParameterNumber(
                key, self.tr(label), QgsProcessingParameterNumber.Type.Double, default,
                minValue=0.0, maxValue=60.0)
            param.setFlags(param.flags() | QgsProcessingParameterDefinition.Flag.FlagAdvanced)
            self.addParameter(param)
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Places with PTAL")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_SUMMARY, self.tr("PTAL band summary"),
            type=QgsProcessing.SourceType.TypeVector, optional=True, createByDefault=False))

    def processAlgorithm(self, parameters, context, feedback):
        path = self.parameterAsFile(parameters, self.FILE, context)
        day_text = self.parameterAsString(parameters, self.DAY, context)
        w0 = self.parameterAsDouble(parameters, self.WINDOW_START, context)
        w1 = self.parameterAsDouble(parameters, self.WINDOW_END, context)
        network = self.parameterAsSource(parameters, self.NETWORK, context)
        origins = self.parameterAsSource(parameters, self.ORIGINS, context)
        speed_kmh = self.parameterAsDouble(parameters, self.WALK_SPEED, context)
        bus_catch = self.parameterAsDouble(parameters, self.BUS_CATCHMENT, context)
        rail_catch = self.parameterAsDouble(parameters, self.RAIL_CATCHMENT, context)
        bus_rel = self.parameterAsDouble(parameters, self.BUS_RELIABILITY, context)
        rail_rel = self.parameterAsDouble(parameters, self.RAIL_RELIABILITY, context)
        if w1 <= w0:
            raise QgsProcessingException("The window must end after it starts.")
        self.require_projected(network, "Street network")

        gtfs, day, services = load_feed(path, day_text, feedback)
        stop_routes = ptal.route_frequencies(gtfs, services, (w0 * 3600.0, w1 * 3600.0))
        route_mode = {rid: ptal.mode_class(info.get("type", 3))
                      for rid, info in gtfs["routes"].items()}
        n_served = len(stop_routes)
        n_routes = len({rid for routes in stop_routes.values() for rid in routes})
        feedback.pushInfo(self.tr(
            f"{day}, {w0:g}h-{w1:g}h: {n_routes} route(s) depart from {n_served} "
            f"of {len(gtfs['stop_ids'])} stop(s)."))
        if not stop_routes:
            feedback.pushWarning(self.tr(
                "No departure falls inside the window - every place will be band 0. "
                "Check the window against the feed's timetable."))

        crs = network.sourceCrs()
        xform_ctx = context.transformContext()
        graph, _polylines, _feats = self.network_graph(network, use_prepared_costs=False)
        per_unit = _units.GroundUnits(crs, xform_ctx).scale(network.sourceExtent())
        m_per_min = speed_kmh * 1000.0 / 60.0
        walk_min = graph.adj_cost / per_unit / m_per_min

        o_xy, o_feats = self.source_points(origins, crs, xform_ctx)
        o_nodes = graphs.nearest_nodes(graph, o_xy)
        o_snap = np.hypot(o_xy[:, 0] - graph.node_xy[o_nodes, 0],
                          o_xy[:, 1] - graph.node_xy[o_nodes, 1]) / per_unit / m_per_min

        to_net = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:4326"), crs, xform_ctx)
        served = sorted(stop_routes)
        s_xy = []
        for pos in served:
            p = to_net.transform(QgsPointXY(float(gtfs["stop_lon"][pos]),
                                            float(gtfs["stop_lat"][pos])))
            s_xy.append((p.x(), p.y()))
        s_xy = np.asarray(s_xy, dtype=np.float64).reshape(-1, 2)
        max_catch = max(bus_catch, rail_catch)
        walks = [dict() for _ in range(len(o_feats))]
        if len(served):
            s_nodes = graphs.nearest_nodes(graph, s_xy)
            s_snap = np.hypot(s_xy[:, 0] - graph.node_xy[s_nodes, 0],
                              s_xy[:, 1] - graph.node_xy[s_nodes, 1]) / per_unit / m_per_min
            far = s_snap > max_catch
            if np.all(far):
                raise QgsProcessingException(
                    "No served stop lies within a catchment of the street network - "
                    "are the feed and the network from the same city?")
            # Walking is two-way: a search outward from each stop gives the walk
            # from every node to it.
            for b in range(0, len(served), _BATCH):
                if feedback.isCanceled():
                    break
                dist = paths.many_to_many(graph.indptr, graph.adj_node, walk_min,
                                          graph.num_nodes, s_nodes[b:b + _BATCH],
                                          cutoff=max_catch)
                at_o = dist[:, o_nodes] + o_snap[None, :]
                for r in range(at_o.shape[0]):
                    s = b + r
                    if far[s]:
                        continue
                    total = at_o[r] + s_snap[s]
                    for i in np.nonzero(total <= max_catch)[0]:
                        walks[i][served[s]] = float(total[i])
                feedback.setProgress(int(70.0 * min(1.0, (b + _BATCH) / len(served))))

        fields = self.make_fields(
            ("ptal", STRING), ("ptal_ai", DOUBLE), ("ptal_rank", INT),
            ("ai_bus", DOUBLE), ("ai_tram", DOUBLE), ("ai_rail", DOUBLE),
            ("n_routes", INT), ("n_saps", INT), ("best_route", STRING),
            base=origins.fields())
        sink, dest = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields, QgsWkbTypes.Type.Point, crs)
        n_base = len(origins.fields())
        counts = {label: 0 for label in ("0", "1a", "1b", "2", "3", "4", "5", "6a", "6b")}
        ai_values = []
        for i, feat in enumerate(o_feats):
            if feedback.isCanceled():
                break
            res = ptal.accessibility_index(walks[i], stop_routes, route_mode,
                                           bus_catch, rail_catch, bus_rel, rail_rel)
            label = ptal.band(res["ai"])
            counts[label] += 1
            ai_values.append(res["ai"])
            by_mode = res["ai_by_mode"]
            best = res["best"]
            best_name = None
            if best is not None:
                info = gtfs["routes"].get(best, {})
                best_name = info.get("short") or info.get("long") or str(best)
            out = QgsFeature(fields)
            out.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*o_xy[i])))
            out.setAttributes(list(feat.attributes())[:n_base] + [
                label, round(res["ai"], 3), ptal.band_rank(label),
                round(by_mode.get("bus", 0.0), 3), round(by_mode.get("tram", 0.0), 3),
                round(by_mode.get("rail", 0.0), 3), int(res["n_routes"]),
                int(res["n_saps"]), best_name])
            sink.addFeature(out, QgsFeatureSink.Flag.FastInsert)
        feedback.setProgress(95)

        n = max(1, len(ai_values))
        feedback.pushInfo(self.tr(
            "Band shares: " + ", ".join(
                f"{label} {100.0 * c / n:.1f}%" for label, c in counts.items() if c)))
        results = {self.OUTPUT: dest}
        if parameters.get(self.OUT_SUMMARY) is not None:
            sfields = self.make_fields(("ptal", STRING), ("ptal_rank", INT),
                                       ("places", INT), ("share", DOUBLE))
            ssink, sdest = self.parameterAsSink(
                parameters, self.OUT_SUMMARY, context, sfields, QgsWkbTypes.Type.NoGeometry, crs)
            for label, c in counts.items():
                row = QgsFeature(sfields)
                row.setAttributes([label, ptal.band_rank(label), int(c), round(c / n, 6)])
                ssink.addFeature(row, QgsFeatureSink.Flag.FastInsert)
            results[self.OUT_SUMMARY] = sdest
        return results

    def createInstance(self):
        return PTALAlgorithm()
