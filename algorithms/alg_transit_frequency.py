# -*- coding: utf-8 -*-
"""Transit Frequency Map: departures and headways per stop in a time window."""
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
    QgsProcessingParameterFile,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_TRANSIT, INT, PlanXAlgorithm, STRING
from .alg_gtfs_import import load_feed
from ..engine import transit


class TransitFrequencyAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_TRANSIT
    ICON = "tool_transitfrequency.png"
    FILE = "FILE"
    DAY = "DAY"
    START = "START"
    END = "END"
    OUT_STOPS = "OUT_STOPS"
    OUT_ROUTES = "OUT_ROUTES"

    def name(self):
        return "transitfrequency"

    def displayName(self):
        return self.tr("Transit Frequency Map")

    def shortHelpString(self):
        return self.tr(
            "How OFTEN does transit actually come? Counts the scheduled "
            "departures at every stop within a time window of a service day "
            "and turns them into the two numbers riders feel: departures "
            "per hour and the mean headway (minutes between services).\n\n"
            "Point it at a GTFS zip, pick the day (defaults to the feed's "
            "first active day) and the window - the morning peak "
            "(07:00-09:00) is the classic choice; a departure is counted "
            "when a vehicle leaves the stop within the window (final "
            "arrivals do not count).\n\n"
            "Outputs:\n"
            "- Stops (WGS84 points) with departures, departures/hour, mean "
            "headway in minutes and the number of distinct routes - style "
            "by 'per_hour' for the classic frequent-network map;\n"
            "- A route table with the trips each route runs in the window.\n\n"
            "Headway here is the scheduled average (window / departures), "
            "not the gap distribution - a screening number, robust across "
            "feeds.\n\n"
            "How to read the results\n"
            "- The magic line is a ~10-12 minute headway (5-6/hour): "
            "below it riders stop reading timetables and just show up - "
            "'turn-up-and-go' service. 15-20 min needs planning; 30+ "
            "min structures a rider's whole day around the bus.\n"
            "- Style per_hour with breaks at 2/4/6: the 6+ subnetwork "
            "IS the 'frequent network' map that transit agencies "
            "publish - and the corridor where transit-oriented density "
            "is defensible.\n"
            "- Compare windows: a stop at 8/hour in the peak but 1/hour "
            "midday serves commuters only - different land uses than "
            "all-day service.\n\n"
            "Using the results: test 'transit-served' claims in plans "
            "against per_hour, not stop dots - a stop with 2 buses/day "
            "is paint, not service; concentrate housing intensification "
            "within walking reach of the frequent network; where a "
            "corridor's frequency justifies it, argue stop upgrades and "
            "priority lanes with the departures table."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(
            self.FILE, self.tr("GTFS feed (zip)"), extension="zip"))
        self.addParameter(QgsProcessingParameterString(
            self.DAY, self.tr("Service day YYYYMMDD (empty = first active)"),
            "", optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.START, self.tr("Window start (hour of day)"),
            QgsProcessingParameterNumber.Double, 7.0, minValue=0.0,
            maxValue=30.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.END, self.tr("Window end (hour of day)"),
            QgsProcessingParameterNumber.Double, 9.0, minValue=0.0,
            maxValue=30.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_STOPS, self.tr("Stop frequencies")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_ROUTES, self.tr("Route trips in window"),
            type=QgsProcessing.TypeVector))

    def processAlgorithm(self, parameters, context, feedback):
        path = self.parameterAsFile(parameters, self.FILE, context)
        day_text = self.parameterAsString(parameters, self.DAY, context)
        start_h = self.parameterAsDouble(parameters, self.START, context)
        end_h = self.parameterAsDouble(parameters, self.END, context)
        if end_h <= start_h:
            raise QgsProcessingException(
                "The window end must be after its start.")
        gtfs, day, _services = load_feed(path, day_text, feedback)
        freq = transit.stop_frequencies(
            gtfs, day, window=(start_h * 3600.0, end_h * 3600.0))

        crs = QgsCoordinateReferenceSystem("EPSG:4326")
        s_fields = self.make_fields(
            ("stop_id", STRING), ("name", STRING), ("departures", INT),
            ("per_hour", DOUBLE), ("headway_min", DOUBLE), ("n_routes", INT))
        s_sink, s_dest = self.parameterAsSink(
            parameters, self.OUT_STOPS, context, s_fields,
            QgsWkbTypes.Point, crs)
        for i, sid in enumerate(gtfs["stop_ids"]):
            feat = QgsFeature(s_fields)
            feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(
                float(gtfs["stop_lon"][i]), float(gtfs["stop_lat"][i]))))
            feat.setAttributes([
                sid, gtfs["stop_names"][i], int(freq["departures"][i]),
                round(float(freq["per_hour"][i]), 3),
                round(float(freq["headway_min"][i]), 2),
                int(freq["n_routes"][i])])
            s_sink.addFeature(feat, QgsFeatureSink.FastInsert)

        r_fields = self.make_fields(
            ("route_id", STRING), ("name", STRING), ("trips_in_window", INT))
        r_sink, r_dest = self.parameterAsSink(
            parameters, self.OUT_ROUTES, context, r_fields,
            QgsWkbTypes.NoGeometry, QgsCoordinateReferenceSystem())
        for rid in sorted(freq["route_trips"]):
            info = gtfs["routes"].get(rid, {"short": "", "long": ""})
            feat = QgsFeature(r_fields)
            feat.setAttributes([rid, info["short"] or info["long"] or rid,
                                int(freq["route_trips"][rid])])
            r_sink.addFeature(feat, QgsFeatureSink.FastInsert)

        served = freq["departures"] > 0
        if np.any(served):
            busiest = int(np.argmax(freq["departures"]))
            feedback.pushInfo(self.tr(
                f"{int(served.sum())} of {len(served)} stops served in "
                f"{start_h:g}:00-{end_h:g}:00 on {day}; busiest: "
                f"{gtfs['stop_names'][busiest]} "
                f"({int(freq['departures'][busiest])} departures, headway "
                f"{freq['headway_min'][busiest]:.0f} min)."))
        else:
            feedback.pushWarning(self.tr(
                "No departures in the window - try another day or window."))
        return {self.OUT_STOPS: s_dest, self.OUT_ROUTES: r_dest}

    def createInstance(self):
        return TransitFrequencyAlgorithm()
