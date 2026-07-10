# -*- coding: utf-8 -*-
"""Flow Accumulation algorithm wrapper."""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterRasterLayer,
)

from .base import GROUP_HAZARD, PlanXAlgorithm
from ._raster import read_dsm, write_raster
from ..engine import hydro


class FlowAccumulationAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_HAZARD
    ICON = "tool_flowaccumulation.png"
    DEM = "DEM"
    OUTPUT_FILLED = "OUTPUT_FILLED"
    OUTPUT_DIR = "OUTPUT_DIR"
    OUTPUT_ACCUM = "OUTPUT_ACCUM"

    def name(self):
        return "flowaccumulation"

    def displayName(self):
        return self.tr("Flow Accumulation")

    def shortHelpString(self):
        return self.tr(
            "Screening-quality flow direction and flow accumulation. "
            "Fills depressions in the DEM using a deterministic priority-flood "
            "algorithm, computes D8 steepest-descent direction, and calculates "
            "topological flow accumulation.\n\n"
            "Outputs the filled DEM, D8 direction raster, and flow accumulation raster.\n\n"
            "How to read the results\n"
            "- Accumulation counts the upstream cells draining THROUGH "
            "each cell: style it with a log scale, because values span "
            "orders of magnitude - the bright branching lines are where "
            "water concentrates when it rains, whether or not any "
            "stream is mapped there.\n"
            "- In urban areas those lines crossing streets and parcels "
            "are the surface-flow paths of a cloudburst: buildings "
            "sitting ON a high-accumulation line flood first, "
            "culverts under it are the choke points to check.\n"
            "- filled-minus-original DEM marks the depressions: real "
            "ponds and karst, but in cities often underpasses and "
            "basins - exactly where pluvial water parks itself.\n"
            "- The direction raster is plumbing for HAND and other "
            "downstream tools; 255 = nodata, 0 = flat/pit.\n\n"
            "Using the results: keep the high-accumulation corridors "
            "free of building in new layouts (they are free drainage); "
            "threshold accumulation (e.g. top 1 percent) to sketch a "
            "synthetic stream network where none is mapped; feed the "
            "results straight into HAND Index and Flood Exposure."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.DEM, self.tr("Digital Elevation Model (projected CRS)")))
        self.addParameter(QgsProcessingParameterRasterDestination(
            self.OUTPUT_FILLED, self.tr("Filled DEM")))
        self.addParameter(QgsProcessingParameterRasterDestination(
            self.OUTPUT_DIR, self.tr("D8 Flow Direction")))
        self.addParameter(QgsProcessingParameterRasterDestination(
            self.OUTPUT_ACCUM, self.tr("Flow Accumulation")))

    def processAlgorithm(self, parameters, context, feedback):
        dem_layer = self.parameterAsRasterLayer(parameters, self.DEM, context)
        out_filled = self.parameterAsOutputLayer(parameters, self.OUTPUT_FILLED, context)
        out_dir = self.parameterAsOutputLayer(parameters, self.OUTPUT_DIR, context)
        out_accum = self.parameterAsOutputLayer(parameters, self.OUTPUT_ACCUM, context)

        dem, gt, proj, pixel = read_dsm(dem_layer)
        valid = np.isfinite(dem)

        filled = hydro.fill_depressions(dem)
        dirs = hydro.d8_flow(filled)
        accum = hydro.flow_accumulation(dirs)

        filled[~valid] = np.nan
        dirs_float = dirs.astype(np.float32)
        # 0 is the legitimate "no descent" D8 code (flats, pits) - nodata is 255
        dirs_float[~valid] = 255.0
        accum[~valid] = np.nan

        write_raster(out_filled, filled.astype(np.float32), gt, proj, float("nan"))
        write_raster(out_dir, dirs_float, gt, proj, 255.0)
        write_raster(out_accum, accum.astype(np.float32), gt, proj, float("nan"))

        return {
            self.OUTPUT_FILLED: out_filled,
            self.OUTPUT_DIR: out_dir,
            self.OUTPUT_ACCUM: out_accum
        }

    def createInstance(self):
        return FlowAccumulationAlgorithm()
