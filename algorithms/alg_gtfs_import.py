# -*- coding: utf-8 -*-
"""GTFS Import & Service Stats: stops, routes and a validated feed summary."""
from __future__ import annotations

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsFeatureSink,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFile,
    QgsProcessingParameterString,
    QgsWkbTypes,
)

from .base import GROUP_TRANSIT, INT, PlanXAlgorithm, STRING
from ..engine import transit


def load_feed(path: str, day_text: str, feedback):
    """Shared front door: parse the feed and resolve the service day."""
    try:
        gtfs = transit.read_gtfs(path)
    except ValueError as exc:
        raise QgsProcessingException(f"GTFS: {exc}")
    day = day_text.strip().replace("-", "")
    if not day:
        try:
            day = transit.first_service_day(gtfs)
        except ValueError as exc:
            raise QgsProcessingException(f"GTFS: {exc}")
        feedback.pushInfo(f"No date given - using the feed's first service "
                          f"day: {day}.")
    try:
        services = transit.active_services(gtfs, day)
    except ValueError as exc:
        raise QgsProcessingException(f"GTFS: {exc}")
    if not services:
        raise QgsProcessingException(
            f"No service runs on {day} - pick another date (calendar spans "
            "differ per feed).")
    return gtfs, day, services


class GtfsImportAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_TRANSIT
    ICON = "tool_gtfsimport.png"
    FILE = "FILE"
    DAY = "DAY"
    OUT_STOPS = "OUT_STOPS"
    OUT_ROUTES = "OUT_ROUTES"

    def name(self):
        return "gtfsimport"

    def displayName(self):
        return self.tr("GTFS Import and Service Stats")

    def shortHelpString(self):
        return self.tr(
            "Loads a GTFS transit feed (the zip you download from an agency "
            "or a national open-data portal) into QGIS layers - and "
            "validates it on the way in, with clear errors for missing "
            "files or malformed times.\n\n"
            "Outputs:\n"
            "- Stops as points (WGS84) with the daily departure count and "
            "the number of distinct routes serving each stop on the chosen "
            "service day;\n"
            "- A route summary table: one row per route with its name, "
            "mode, trips on the day, service span (first / last departure) "
            "and the longest stop sequence.\n\n"
            "The service day defaults to the feed's first active day; give "
            "a date as YYYYMMDD (or YYYY-MM-DD) to inspect a specific day - "
            "weekday and weekend timetables usually differ.\n\n"
            "The stops layer is the geocoded front door for Transit "
            "Frequency Map and Transit Travel-Time Access, which read the "
            "same feed directly."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(
            self.FILE, self.tr("GTFS feed (zip)"), extension="zip"))
        self.addParameter(QgsProcessingParameterString(
            self.DAY, self.tr("Service day YYYYMMDD (empty = first active)"),
            "", optional=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_STOPS, self.tr("Transit stops")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_ROUTES, self.tr("Route summary"),
            type=QgsProcessing.TypeVector))

    def processAlgorithm(self, parameters, context, feedback):
        path = self.parameterAsFile(parameters, self.FILE, context)
        day_text = self.parameterAsString(parameters, self.DAY, context)
        gtfs, day, services = load_feed(path, day_text, feedback)

        freq = transit.stop_frequencies(gtfs, day, window=(0, 30 * 3600))

        crs = QgsCoordinateReferenceSystem("EPSG:4326")
        s_fields = self.make_fields(
            ("stop_id", STRING), ("name", STRING), ("departures", INT),
            ("n_routes", INT))
        s_sink, s_dest = self.parameterAsSink(
            parameters, self.OUT_STOPS, context, s_fields,
            QgsWkbTypes.Point, crs)
        for i, sid in enumerate(gtfs["stop_ids"]):
            feat = QgsFeature(s_fields)
            feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(
                float(gtfs["stop_lon"][i]), float(gtfs["stop_lat"][i]))))
            feat.setAttributes([sid, gtfs["stop_names"][i],
                                int(freq["departures"][i]),
                                int(freq["n_routes"][i])])
            s_sink.addFeature(feat, QgsFeatureSink.FastInsert)

        # per-route day stats
        stats = {}
        for tid, (rid, sid) in gtfs["trips"].items():
            if sid not in services:
                continue
            st = gtfs["stop_times"].get(tid)
            if not st:
                continue
            rec = stats.setdefault(rid, {"trips": 0, "first": None,
                                         "last": None, "stops": 0})
            rec["trips"] += 1
            dep0, depN = st[0][1], st[-1][0]
            rec["first"] = dep0 if rec["first"] is None else min(rec["first"], dep0)
            rec["last"] = depN if rec["last"] is None else max(rec["last"], depN)
            rec["stops"] = max(rec["stops"], len(st))

        def hhmm(sec):
            return f"{int(sec) // 3600:02d}:{int(sec) % 3600 // 60:02d}"

        r_fields = self.make_fields(
            ("route_id", STRING), ("name", STRING), ("mode", STRING),
            ("n_trips", INT), ("first_dep", STRING), ("last_arr", STRING),
            ("n_stops", INT))
        r_sink, r_dest = self.parameterAsSink(
            parameters, self.OUT_ROUTES, context, r_fields,
            QgsWkbTypes.NoGeometry, QgsCoordinateReferenceSystem())
        for rid in sorted(stats):
            info = gtfs["routes"].get(rid, {"short": "", "long": "", "type": -1})
            label = info["short"] or info["long"] or rid
            if info["short"] and info["long"]:
                label = f"{info['short']} - {info['long']}"
            rec = stats[rid]
            feat = QgsFeature(r_fields)
            feat.setAttributes([
                rid, label, transit.ROUTE_TYPES.get(info["type"], "Other"),
                rec["trips"], hhmm(rec["first"]), hhmm(rec["last"]),
                rec["stops"]])
            r_sink.addFeature(feat, QgsFeatureSink.FastInsert)

        feedback.pushInfo(self.tr(
            f"Feed OK: {len(gtfs['stop_ids'])} stops, {len(stats)} route(s) "
            f"running on {day} ({len(services)} service pattern(s), "
            f"{sum(r['trips'] for r in stats.values())} trips)."))
        return {self.OUT_STOPS: s_dest, self.OUT_ROUTES: r_dest}

    def createInstance(self):
        return GtfsImportAlgorithm()
