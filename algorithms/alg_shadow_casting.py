# -*- coding: utf-8 -*-
"""Shadow Casting: DSM shadows for any date and time, embedded sun position."""
from __future__ import annotations

import numpy as np

from osgeo import gdal
from qgis.core import (
    QgsProcessingParameterDateTime,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterRasterLayer,
)

from .base import GROUP_MICRO, PlanXAlgorithm
from . import _raster
from ..engine import solar


class ShadowCastingAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_MICRO
    ICON = "tool_shadowcasting.png"
    DSM = "DSM"
    WHEN = "WHEN"
    UTC_OFFSET = "UTC_OFFSET"
    MAX_SEARCH = "MAX_SEARCH"
    OUTPUT = "OUTPUT"

    def name(self):
        return "shadowcasting"

    def displayName(self):
        return self.tr("Shadow Casting (DSM)")

    def shortHelpString(self):
        return self.tr(
            "Casts building and terrain shadows from a digital surface model "
            "for any date and time - the UMEP-style shadow algorithm with an "
            "embedded NOAA solar-position model (no plugins, no ephemeris "
            "files).\n\n"
            "The sun's altitude and azimuth are computed for the raster "
            "center (give the local clock time plus its UTC offset, e.g. "
            "+3 for Türkiye). The DSM is swept toward the sun; output cells "
            "are 1 = in cast shadow, 0 = sunlit.\n\n"
            "Use a DSM that includes building heights (terrain + buildings). "
            "The raster must be in a projected CRS with metric pixels. Run "
            "it for several hours in Batch mode to build shadow-duration "
            "maps.\n\n"
            "How to read the results\n"
            "- 1 = the cell is in cast shadow at that instant, 0 = sunlit. "
            "One run answers a specific claim ('the tower shades the "
            "playground at 15:00 on Dec 21'); a Batch series over the day "
            "answers duration questions.\n"
            "- The critical planning dates: winter solstice (Dec 21, "
            "worst case - rights-to-light and solar-access rules are "
            "usually tested here), equinoxes (typical case), summer "
            "solstice (shade as a HEAT asset for playgrounds and "
            "squares).\n"
            "- Shadow at ground level is what matters for public space; "
            "shadow on facades (cells adjacent to buildings) indicates "
            "lost solar gain and daylight for dwellings.\n\n"
            "Using the results: overlay the Dec-21 noon shadow on gardens, "
            "schoolyards and existing solar roofs to test a proposed "
            "massing; run before/after DSMs and difference the rasters to "
            "isolate exactly the NEW shadow a project casts - the figure "
            "an objection or approval turns on. Use Sun Hours for the "
            "full-day accumulated picture."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.DSM, self.tr("Digital surface model (terrain + buildings)")))
        self.addParameter(QgsProcessingParameterDateTime(
            self.WHEN, self.tr("Date and local clock time")))
        self.addParameter(QgsProcessingParameterNumber(
            self.UTC_OFFSET, self.tr("UTC offset of that clock time (hours)"),
            QgsProcessingParameterNumber.Type.Double, 0.0, minValue=-14.0, maxValue=14.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.MAX_SEARCH, self.tr("Maximum shadow length to scan (map units, 0 = auto)"),
            QgsProcessingParameterNumber.Type.Double, 0.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterRasterDestination(
            self.OUTPUT, self.tr("Shadow raster (1 = shadow)")))

    def processAlgorithm(self, parameters, context, feedback):
        layer = self.parameterAsRasterLayer(parameters, self.DSM, context)
        when = self.parameterAsDateTime(parameters, self.WHEN, context)
        utc_offset = self.parameterAsDouble(parameters, self.UTC_OFFSET, context)
        max_search = self.parameterAsDouble(parameters, self.MAX_SEARCH, context) or None
        out_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        arr, gt, proj, pixel = _raster.read_dsm(layer)
        lon, lat = _raster.raster_center_lonlat(layer)
        d = when.date()
        t = when.time()
        hour_utc = t.hour() + t.minute() / 60.0 + t.second() / 3600.0 - utc_offset
        alt, az = solar.sun_position(d.year(), d.month(), d.day(), hour_utc, lat, lon)
        feedback.pushInfo(self.tr(
            f"Site {lat:.4f}N {lon:.4f}E | sun altitude {alt:.2f} deg, "
            f"azimuth {az:.2f} deg"))
        if alt <= 0:
            feedback.pushWarning(self.tr(
                "The sun is below the horizon at that time - everything is shadow."))

        shadow = solar.shadow_mask(arr, alt, az, pixel, max_search=max_search,
                                   progress=lambda p: feedback.setProgress(int(100 * p)))
        out = shadow.astype(np.uint8)
        out[np.isnan(arr)] = 255
        _raster.write_raster(out_path, out, gt, proj, nodata=255, dtype=gdal.GDT_Byte)
        share = float(shadow[~np.isnan(arr)].mean()) if np.isfinite(arr).any() else 0.0
        feedback.pushInfo(self.tr(f"Shadowed share of the scene: {share:.1%}"))
        return {self.OUTPUT: out_path}

    def createInstance(self):
        return ShadowCastingAlgorithm()
