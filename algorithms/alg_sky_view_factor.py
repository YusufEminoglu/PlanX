# -*- coding: utf-8 -*-
"""Sky View Factor from a DSM."""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterRasterLayer,
)

from .base import GROUP_MICRO, PlanXAlgorithm
from . import _raster
from ..engine import solar


class SkyViewFactorAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_MICRO
    ICON = "tool_skyviewfactor.png"
    DSM = "DSM"
    DIRECTIONS = "DIRECTIONS"
    RADIUS = "RADIUS"
    OUTPUT = "OUTPUT"

    def name(self):
        return "skyviewfactor"

    def displayName(self):
        return self.tr("Sky View Factor (DSM)")

    def shortHelpString(self):
        return self.tr(
            "Computes the Sky View Factor - the fraction of the sky "
            "hemisphere visible from each cell (1 = open field, ~0.5 at the "
            "foot of a long wall, lower in deep canyons). A key indicator "
            "for urban heat island, nocturnal cooling and daylight studies.\n\n"
            "For every cell the horizon angle is scanned in N equally "
            "spaced azimuths up to the search radius; "
            "SVF = 1 - mean(sin^2 horizon). More directions = smoother "
            "result, longer runtime (16 is a good default; 32 for "
            "publication maps).\n\n"
            "Use a DSM including buildings, in a projected CRS. Pair with "
            "Shadow Casting for a quick microclimate screening.\n\n"
            "How to read the results\n"
            "- SVF > 0.9: open field / plaza - cools fast at night but "
            "bakes by day (no shade). 0.6-0.9: normal streets. 0.4-0.6: "
            "dense fabric, canyons forming. < 0.4: deep canyon - traps "
            "daytime heat and blocks nocturnal cooling, the classic "
            "urban-heat-island core signature.\n"
            "- Low SVF is not automatically bad: it also means shaded, "
            "wind-sheltered streets. Judge it together with orientation "
            "and greenery - the problem is low SVF + heavy traffic + no "
            "vegetation.\n"
            "- Read extremes first: continuous low-SVF corridors with "
            "night-heat complaints are your mitigation targets.\n\n"
            "Using the results: combine with Heat Island Risk Grid (it "
            "uses built fraction and height) to prioritise cool-roof / "
            "tree-planting streets; check that proposed infill does not "
            "push courtyard SVF below what daylight rules imply; use the "
            "before/after difference of a massing study to show exactly "
            "which public spaces lose sky."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.DSM, self.tr("Digital surface model (terrain + buildings)")))
        self.addParameter(QgsProcessingParameterNumber(
            self.DIRECTIONS, self.tr("Horizon scan directions"),
            QgsProcessingParameterNumber.Integer, 16, minValue=4, maxValue=64))
        self.addParameter(QgsProcessingParameterNumber(
            self.RADIUS, self.tr("Search radius (map units)"),
            QgsProcessingParameterNumber.Double, 100.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterRasterDestination(
            self.OUTPUT, self.tr("Sky view factor")))

    def processAlgorithm(self, parameters, context, feedback):
        layer = self.parameterAsRasterLayer(parameters, self.DSM, context)
        directions = self.parameterAsInt(parameters, self.DIRECTIONS, context)
        radius = self.parameterAsDouble(parameters, self.RADIUS, context)
        out_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        arr, gt, proj, pixel = _raster.read_dsm(layer)
        feedback.pushInfo(self.tr(
            f"DSM {arr.shape[1]}x{arr.shape[0]} px, pixel {pixel:.2f}; "
            f"{directions} directions, radius {radius:g}"))
        svf = solar.sky_view_factor(
            arr, pixel, directions=directions, max_radius=radius,
            progress=lambda p: feedback.setProgress(int(100 * p)))
        out = svf.astype(np.float32)
        out[np.isnan(svf)] = -9999.0
        _raster.write_raster(out_path, out, gt, proj, nodata=-9999.0)
        valid = svf[~np.isnan(svf)]
        if valid.size:
            feedback.pushInfo(self.tr(
                f"SVF range {valid.min():.3f} - {valid.max():.3f}, "
                f"mean {valid.mean():.3f}"))
        return {self.OUTPUT: out_path}

    def createInstance(self):
        return SkyViewFactorAlgorithm()
