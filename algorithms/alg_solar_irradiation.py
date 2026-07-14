# -*- coding: utf-8 -*-
"""Solar Irradiation: clear-sky daily global irradiation per DSM cell."""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsProcessingParameterBoolean,
    QgsProcessingParameterDateTime,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterRasterLayer,
)

from .base import GROUP_MICRO, PlanXAlgorithm
from . import _raster
from ..engine import solar


class SolarIrradiationAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_MICRO
    ICON = "tool_solarirradiation.png"
    DSM = "DSM"
    DATE = "DATE"
    UTC_OFFSET = "UTC_OFFSET"
    INTERVAL = "INTERVAL"
    USE_SVF = "USE_SVF"
    SVF_RADIUS = "SVF_RADIUS"
    MAX_SEARCH = "MAX_SEARCH"
    OUTPUT = "OUTPUT"

    def name(self):
        return "solarirradiation"

    def displayName(self):
        return self.tr("Solar Irradiation (DSM)")

    def shortHelpString(self):
        return self.tr(
            "Clear-sky global solar irradiation per cell for one day "
            "(kWh/m2) - quick screening of roofs, facades-at-ground and "
            "open spaces for solar potential or summer heat exposure, with "
            "no external solver or atmospheric dataset.\n\n"
            "The day is swept at a fixed interval. Each step combines:\n"
            "- beam: ASHRAE-style clear-sky direct irradiance, only on "
            "cells outside the cast shadow (embedded NOAA sun position + "
            "UMEP-style DSM sweep)\n"
            "- diffuse: isotropic sky component, scaled per cell by the "
            "sky view factor (optional but recommended in street canyons)\n\n"
            "Output is kWh/m2 for that day on a horizontal surface; the log "
            "reports the unobstructed flat-ground reference. Run for "
            "solstices/equinoxes to bracket the year. Screening quality - "
            "clouds and slope/aspect of roofs are not modelled.\n\n"
            "How to read the results\n"
            "- Always read cells RELATIVE to the flat-ground reference in "
            "the log: a roof at 90 percent of reference is essentially "
            "unshaded; below ~70 percent the surroundings cost real "
            "yield and PV there needs a closer look.\n"
            "- Clear-sky means every value is an upper bound - ranking "
            "between roofs/spaces is reliable, absolute kWh is not "
            "(clouds typically remove 30-50 percent depending on "
            "climate).\n"
            "- For heat questions invert the reading: south-facing "
            "hard-surface cells at high kWh/m2 on a summer date are the "
            "surfaces that will radiate heat into the evening.\n\n"
            "Using the results: shortlist roofs by winter-day irradiation "
            "(the binding season for PV economics); test how a proposed "
            "tower cuts a neighbour's daily kWh (before/after DSM "
            "difference); use the summer run to target shading sails and "
            "trees on overexposed plazas. For yearly totals use Annual "
            "Solar Potential."
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
        self.addParameter(QgsProcessingParameterBoolean(
            self.USE_SVF, self.tr("Weight diffuse light by sky view factor"), True))
        self.addParameter(QgsProcessingParameterNumber(
            self.SVF_RADIUS, self.tr("SVF search radius (map units)"),
            QgsProcessingParameterNumber.Type.Double, 100.0, minValue=10.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.MAX_SEARCH, self.tr("Maximum shadow length to scan (map units, 0 = auto)"),
            QgsProcessingParameterNumber.Type.Double, 0.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterRasterDestination(
            self.OUTPUT, self.tr("Daily irradiation (kWh/m2)")))

    def processAlgorithm(self, parameters, context, feedback):
        layer = self.parameterAsRasterLayer(parameters, self.DSM, context)
        when = self.parameterAsDateTime(parameters, self.DATE, context)
        utc_offset = self.parameterAsDouble(parameters, self.UTC_OFFSET, context)
        interval = self.parameterAsDouble(parameters, self.INTERVAL, context)
        use_svf = self.parameterAsBool(parameters, self.USE_SVF, context)
        svf_radius = self.parameterAsDouble(parameters, self.SVF_RADIUS, context)
        max_search = self.parameterAsDouble(parameters, self.MAX_SEARCH, context) or None
        out_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        arr, gt, proj, pixel = _raster.read_dsm(layer)
        lon, lat = _raster.raster_center_lonlat(layer)
        d = when.date()
        feedback.pushInfo(self.tr(
            f"Site {lat:.4f}N {lon:.4f}E | {d.year()}-{d.month():02d}-{d.day():02d} "
            f"swept every {interval:g} min"))

        svf = None
        if use_svf:
            feedback.pushInfo(self.tr("Sky view factor pass..."))
            svf = solar.sky_view_factor(
                arr, pixel, directions=16, max_radius=svf_radius,
                progress=lambda p: feedback.setProgress(int(30 * p)))
            if feedback.isCanceled():
                return {self.OUTPUT: out_path}

        base = 30 if use_svf else 0
        feedback.pushInfo(self.tr("Irradiation sweep..."))
        kwh, flat_kwh = solar.daily_irradiation(
            arr, pixel, d.year(), d.month(), d.day(), utc_offset, lat, lon,
            interval_min=interval, svf=svf, max_search=max_search,
            progress=lambda p: feedback.setProgress(base + int((100 - base) * p)),
            cancel=feedback.isCanceled)

        out = np.where(np.isnan(arr), -9999.0, kwh).astype(np.float32)
        _raster.write_raster(out_path, out, gt, proj, nodata=-9999.0)
        valid = kwh[~np.isnan(arr)]
        if valid.size:
            feedback.pushInfo(self.tr(
                f"Flat-ground clear-sky reference {flat_kwh:.2f} kWh/m2 | "
                f"scene mean {float(valid.mean()):.2f}, "
                f"min {float(valid.min()):.2f}, max {float(valid.max()):.2f}"))
        return {self.OUTPUT: out_path}

    def createInstance(self):
        return SolarIrradiationAlgorithm()
