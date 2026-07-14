# -*- coding: utf-8 -*-
"""Sun Hours: direct-sun duration per DSM cell over one day."""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsProcessingParameterDateTime,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterRasterLayer,
)

from .base import GROUP_MICRO, PlanXAlgorithm
from . import _raster
from ..engine import solar


class SunHoursAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_MICRO
    ICON = "tool_sunhours.png"
    DSM = "DSM"
    DATE = "DATE"
    UTC_OFFSET = "UTC_OFFSET"
    INTERVAL = "INTERVAL"
    MAX_SEARCH = "MAX_SEARCH"
    OUTPUT = "OUTPUT"

    def name(self):
        return "sunhours"

    def displayName(self):
        return self.tr("Sun Hours (DSM)")

    def shortHelpString(self):
        return self.tr(
            "Hours of direct sunlight per cell over one full day - the "
            "shadow-duration map that previously required a Batch run of "
            "Shadow Casting, now in a single tool.\n\n"
            "The day is swept at a fixed interval (default 30 minutes): for "
            "every step with the sun above the horizon the DSM shadow mask "
            "is cast (embedded NOAA solar-position model) and sunlit cells "
            "accumulate time. Output cells hold hours of direct sun; the "
            "log reports the site's potential daylight for comparison.\n\n"
            "Use a DSM that includes building heights, in a projected CRS "
            "with metric pixels. Typical uses: right-to-light checks, "
            "courtyard and playground sun audits, terrace/garden siting. "
            "Smaller intervals are more accurate but proportionally slower.\n\n"
            "How to read the results\n"
            "- Compare against the site's potential daylight in the log: "
            "a courtyard getting 3 h out of a possible 9 h loses "
            "two-thirds of its sun to the surrounding massing.\n"
            "- Common thresholds to test against: ~2 h of direct sun on "
            "Dec 21 (or the equinox, depending on the local rule) for "
            "habitable rooms; 4-6 h for playgrounds and food gardens; "
            "many daylight guidelines phrase it as 'half the open space "
            "gets 2+ hours'.\n"
            "- Run winter AND summer: winter shows solar-access "
            "violations, summer shows where shade is missing (a "
            "playground with 10 h summer sun needs trees, not more sun).\n\n"
            "Using the results: difference before/after DSMs of a "
            "proposal to show exactly which gardens fall under the "
            "2-hour line - the decisive right-to-light exhibit; screen "
            "roofs with long winter sun hours for PV before running the "
            "full Solar Irradiation tools."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.DSM, self.tr("Digital surface model (terrain + buildings)")))
        self.addParameter(QgsProcessingParameterDateTime(
            self.DATE, self.tr("Date (time of day is ignored)")))
        self.addParameter(QgsProcessingParameterNumber(
            self.UTC_OFFSET, self.tr("UTC offset of local time (hours)"),
            QgsProcessingParameterNumber.Type.Double, 0.0, minValue=-14.0, maxValue=14.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.INTERVAL, self.tr("Time step (minutes)"),
            QgsProcessingParameterNumber.Type.Double, 30.0, minValue=5.0, maxValue=120.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.MAX_SEARCH, self.tr("Maximum shadow length to scan (map units, 0 = auto)"),
            QgsProcessingParameterNumber.Type.Double, 0.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterRasterDestination(
            self.OUTPUT, self.tr("Sun hours raster")))

    def processAlgorithm(self, parameters, context, feedback):
        layer = self.parameterAsRasterLayer(parameters, self.DSM, context)
        when = self.parameterAsDateTime(parameters, self.DATE, context)
        utc_offset = self.parameterAsDouble(parameters, self.UTC_OFFSET, context)
        interval = self.parameterAsDouble(parameters, self.INTERVAL, context)
        max_search = self.parameterAsDouble(parameters, self.MAX_SEARCH, context) or None
        out_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        arr, gt, proj, pixel = _raster.read_dsm(layer)
        lon, lat = _raster.raster_center_lonlat(layer)
        d = when.date()
        feedback.pushInfo(self.tr(
            f"Site {lat:.4f}N {lon:.4f}E | {d.year()}-{d.month():02d}-{d.day():02d} "
            f"swept every {interval:g} min"))

        hours, daylight = solar.sun_hours(
            arr, pixel, d.year(), d.month(), d.day(), utc_offset, lat, lon,
            interval_min=interval, max_search=max_search,
            progress=lambda p: feedback.setProgress(int(100 * p)),
            cancel=feedback.isCanceled)

        out = np.where(np.isnan(arr), -9999.0, hours).astype(np.float32)
        _raster.write_raster(out_path, out, gt, proj, nodata=-9999.0)
        valid = hours[~np.isnan(arr)]
        if valid.size:
            feedback.pushInfo(self.tr(
                f"Potential daylight {daylight:.1f} h | direct sun mean "
                f"{float(valid.mean()):.1f} h, min {float(valid.min()):.1f} h, "
                f"max {float(valid.max()):.1f} h"))
        return {self.OUTPUT: out_path}

    def createInstance(self):
        return SunHoursAlgorithm()
