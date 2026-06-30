# -*- coding: utf-8 -*-
"""Annual Solar Potential: clear-sky yearly global irradiation per DSM cell."""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsProcessingParameterBoolean,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterRasterLayer,
)

from .base import GROUP_MICRO, PlanXAlgorithm
from . import _raster
from ..engine import solar


class AnnualSolarAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_MICRO
    ICON = "tool_annualsolar.png"
    DSM = "DSM"
    YEAR = "YEAR"
    UTC_OFFSET = "UTC_OFFSET"
    INTERVAL = "INTERVAL"
    USE_SVF = "USE_SVF"
    SVF_RADIUS = "SVF_RADIUS"
    MAX_SEARCH = "MAX_SEARCH"
    OUTPUT = "OUTPUT"
    OUTPUT_MONTHLY = "OUTPUT_MONTHLY"

    def name(self):
        return "annualsolar"

    def displayName(self):
        return self.tr("Annual Solar Potential (DSM)")

    def shortHelpString(self):
        return self.tr(
            "Clear-sky global solar irradiation per cell summed over a whole "
            "year (kWh/m2/yr) - rooftop PV potential, annual solar access and "
            "year-round heat exposure, with no external solver or atmospheric "
            "dataset.\n\n"
            "Rather than sweeping all 365 days, one representative average "
            "day per month (Klein 1977; Duffie & Beckman) is computed with "
            "the same shadow-aware beam + sky-view-weighted diffuse model as "
            "the single-day Solar Irradiation tool, then scaled by the number "
            "of days in that month and summed. Twelve day-sweeps stand in for "
            "the year - accurate enough for screening, far faster than a "
            "full daily run.\n\n"
            "Outputs the annual irradiation raster (kWh/m2/yr); optionally a "
            "12-band monthly raster (one band per month, named) for seasonal "
            "analysis. The log reports the unobstructed flat-ground annual "
            "reference, the scene statistics and the peak month.\n\n"
            "The DSM must be in a projected CRS (metric pixels). Screening "
            "quality: clouds, terrain albedo and roof slope/aspect are not "
            "modelled. A coarser time step runs faster; 30-60 min is a good "
            "compromise for a year."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.DSM, self.tr("Digital surface model (terrain + buildings)")))
        self.addParameter(QgsProcessingParameterNumber(
            self.YEAR, self.tr("Year"),
            QgsProcessingParameterNumber.Integer, 2026, minValue=1901, maxValue=2099))
        self.addParameter(QgsProcessingParameterNumber(
            self.UTC_OFFSET, self.tr("UTC offset of local time (hours)"),
            QgsProcessingParameterNumber.Double, 0.0, minValue=-14.0, maxValue=14.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.INTERVAL, self.tr("Time step (minutes)"),
            QgsProcessingParameterNumber.Double, 60.0, minValue=5.0, maxValue=120.0))
        self.addParameter(QgsProcessingParameterBoolean(
            self.USE_SVF, self.tr("Weight diffuse light by sky view factor"), True))
        self.addParameter(QgsProcessingParameterNumber(
            self.SVF_RADIUS, self.tr("SVF search radius (map units)"),
            QgsProcessingParameterNumber.Double, 100.0, minValue=10.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.MAX_SEARCH, self.tr("Maximum shadow length to scan (map units, 0 = auto)"),
            QgsProcessingParameterNumber.Double, 0.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterRasterDestination(
            self.OUTPUT, self.tr("Annual irradiation (kWh/m2/yr)")))
        monthly = QgsProcessingParameterRasterDestination(
            self.OUTPUT_MONTHLY, self.tr("Monthly irradiation (12-band, optional)"),
            optional=True, createByDefault=False)
        self.addParameter(monthly)

    def processAlgorithm(self, parameters, context, feedback):
        layer = self.parameterAsRasterLayer(parameters, self.DSM, context)
        year = self.parameterAsInt(parameters, self.YEAR, context)
        utc_offset = self.parameterAsDouble(parameters, self.UTC_OFFSET, context)
        interval = self.parameterAsDouble(parameters, self.INTERVAL, context)
        use_svf = self.parameterAsBool(parameters, self.USE_SVF, context)
        svf_radius = self.parameterAsDouble(parameters, self.SVF_RADIUS, context)
        max_search = self.parameterAsDouble(parameters, self.MAX_SEARCH, context) or None
        out_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)
        monthly_req = bool(parameters.get(self.OUTPUT_MONTHLY))

        arr, gt, proj, pixel = _raster.read_dsm(layer)
        lon, lat = _raster.raster_center_lonlat(layer)
        feedback.pushInfo(self.tr(
            f"Site {lat:.4f}N {lon:.4f}E | year {year} | 12 monthly "
            f"average-day sweeps every {interval:g} min"))

        svf = None
        if use_svf:
            feedback.pushInfo(self.tr("Sky view factor pass..."))
            svf = solar.sky_view_factor(
                arr, pixel, directions=16, max_radius=svf_radius,
                progress=lambda p: feedback.setProgress(int(20 * p)))
            if feedback.isCanceled():
                return {self.OUTPUT: out_path}

        base = 20 if use_svf else 0
        feedback.pushInfo(self.tr("Annual irradiation sweep (12 months)..."))
        res = solar.annual_irradiation(
            arr, pixel, year, utc_offset, lat, lon,
            interval_min=interval, svf=svf, max_search=max_search,
            keep_monthly=monthly_req,
            progress=lambda p: feedback.setProgress(base + int((100 - base) * p)),
            cancel=feedback.isCanceled)

        annual = res["annual"]
        out = np.where(np.isnan(arr), -9999.0, annual).astype(np.float32)
        _raster.write_raster(out_path, out, gt, proj, nodata=-9999.0)
        results = {self.OUTPUT: out_path}

        if monthly_req and res["monthly"] is not None:
            monthly_path = self.parameterAsOutputLayer(
                parameters, self.OUTPUT_MONTHLY, context)
            bands = [np.where(np.isnan(arr), -9999.0, mk).astype(np.float32)
                     for mk in res["monthly"]]
            names = [solar.MONTH_NAMES[m - 1] for m in res["months"]]
            _raster.write_raster_multiband(
                monthly_path, bands, gt, proj, nodata=-9999.0, band_names=names)
            results[self.OUTPUT_MONTHLY] = monthly_path

        valid = annual[~np.isnan(arr)]
        if valid.size:
            feedback.pushInfo(self.tr(
                f"Flat-ground clear-sky annual reference {res['flat_annual']:.0f} "
                f"kWh/m2/yr | scene mean {float(valid.mean()):.0f}, "
                f"min {float(valid.min()):.0f}, max {float(valid.max()):.0f}"))
            means = res["month_mean"]
            if means:
                parts = " ".join(
                    f"{solar.MONTH_NAMES[m - 1][:3]} {mm:.0f}"
                    for m, mm in zip(res["months"], means))
                feedback.pushInfo(self.tr(f"Scene monthly means (kWh/m2): {parts}"))
                peak = max(range(len(means)), key=lambda i: means[i])
                feedback.pushInfo(self.tr(
                    f"Peak month: {solar.MONTH_NAMES[res['months'][peak] - 1]} "
                    f"({means[peak]:.0f} kWh/m2)"))
        return results

    def createInstance(self):
        return AnnualSolarAlgorithm()
