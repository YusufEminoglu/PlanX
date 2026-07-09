# -*- coding: utf-8 -*-
"""HAND index and inundation mask wrapper."""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterRasterLayer,
)

from .base import GROUP_HAZARD, PlanXAlgorithm
from ._raster import read_dsm, write_raster
from ..engine import hydro


class HandIndexAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_HAZARD
    ICON = "tool_handindex.png"
    DEM = "DEM"
    D8_DIR = "D8_DIR"
    ACCUM = "ACCUM"
    THRESHOLD = "THRESHOLD"
    DEPTH = "DEPTH"
    OUTPUT_HAND = "OUTPUT_HAND"
    OUTPUT_INUNDATION = "OUTPUT_INUNDATION"

    def name(self):
        return "handindex"

    def displayName(self):
        return self.tr("HAND and Inundation")

    def shortHelpString(self):
        return self.tr(
            "Screening-quality Height Above Nearest Drainage (HAND) and inundation mapping.\n\n"
            "Calculates the HAND index: the vertical height of each cell above its nearest drainage "
            "cell (where flow accumulation >= threshold) by tracing flow paths downstream. "
            "Then generates a binary inundation mask where HAND <= depth.\n\n"
            "Outputs the HAND raster and the binary inundation mask."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.DEM, self.tr("Filled DEM (projected CRS)")))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.D8_DIR, self.tr("D8 flow direction raster")))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.ACCUM, self.tr("Flow accumulation raster")))
        self.addParameter(QgsProcessingParameterNumber(
            self.THRESHOLD, self.tr("Drainage accumulation threshold (cells)"),
            QgsProcessingParameterNumber.Double, 100.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.DEPTH, self.tr("Inundation depth (m)"),
            QgsProcessingParameterNumber.Double, 1.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterRasterDestination(
            self.OUTPUT_HAND, self.tr("HAND index")))
        self.addParameter(QgsProcessingParameterRasterDestination(
            self.OUTPUT_INUNDATION, self.tr("Inundation mask")))

    def processAlgorithm(self, parameters, context, feedback):
        dem_layer = self.parameterAsRasterLayer(parameters, self.DEM, context)
        dirs_layer = self.parameterAsRasterLayer(parameters, self.D8_DIR, context)
        accum_layer = self.parameterAsRasterLayer(parameters, self.ACCUM, context)
        threshold = self.parameterAsDouble(parameters, self.THRESHOLD, context)
        depth = self.parameterAsDouble(parameters, self.DEPTH, context)
        out_hand = self.parameterAsOutputLayer(parameters, self.OUTPUT_HAND, context)
        out_inund = self.parameterAsOutputLayer(parameters, self.OUTPUT_INUNDATION, context)

        dem, gt, proj, pixel = read_dsm(dem_layer)
        dirs_arr, _, _, _ = read_dsm(dirs_layer)
        accum_arr, _, _, _ = read_dsm(accum_layer)

        valid = np.isfinite(dem)

        dirs_arr_clean = np.zeros_like(dirs_arr, dtype=np.uint8)
        valid_dirs = np.isfinite(dirs_arr) & (dirs_arr > 0)
        dirs_arr_clean[valid_dirs] = dirs_arr[valid_dirs].astype(np.uint8)

        drainage_mask = np.zeros_like(accum_arr, dtype=bool)
        valid_accum = np.isfinite(accum_arr)
        drainage_mask[valid_accum] = accum_arr[valid_accum] >= threshold

        hand_arr = hydro.hand(dem, dirs_arr_clean, drainage_mask)
        inund = hydro.inundation(hand_arr, depth)

        hand_arr[~valid] = np.nan
        inund[~valid] = np.nan

        write_raster(out_hand, hand_arr.astype(np.float32), gt, proj, float("nan"))
        write_raster(out_inund, inund.astype(np.float32), gt, proj, float("nan"))

        return {
            self.OUTPUT_HAND: out_hand,
            self.OUTPUT_INUNDATION: out_inund
        }

    def createInstance(self):
        return HandIndexAlgorithm()
