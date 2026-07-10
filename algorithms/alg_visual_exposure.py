# -*- coding: utf-8 -*-
"""Visual Exposure: from where can a landmark be seen (inverse viewshed)."""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterRasterLayer,
    QgsCoordinateTransform,
    QgsGeometry,
)

from .base import GROUP_VISIBILITY, PlanXAlgorithm
from ._raster import read_dsm, write_raster
from ..engine import visibility

_MAX_RIM_POINTS = 200


class VisualExposureAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_VISIBILITY
    ICON = "tool_visualexposure.png"
    DSM = "DSM"
    LANDMARKS = "LANDMARKS"
    EXTRA_HEIGHT = "EXTRA_HEIGHT"
    SAMPLE_STEP = "SAMPLE_STEP"
    EYE_HEIGHT = "EYE_HEIGHT"
    RADIUS = "RADIUS"
    OUTPUT = "OUTPUT"

    def name(self):
        return "visualexposure"

    def displayName(self):
        return self.tr("Visual Exposure of Landmarks")

    def shortHelpString(self):
        return self.tr(
            "From WHERE can the landmark be seen? The inverse viewshed: "
            "sample points around the landmark's outline, sweep a viewshed "
            "from each (at the DSM surface there, plus an optional extra "
            "height for a spire or antenna the DSM misses) and count, for "
            "every cell, how many of those sample points a person standing "
            "there (eye height) would see.\n\n"
            "High counts = the full silhouette is visible; low counts = "
            "glimpses between buildings; zero = the landmark is hidden. "
            "The classic input to skyline and heritage impact studies: run "
            "it before and after inserting a proposed building into the "
            "DSM and difference the rasters to see the views a project "
            "would take away.\n\n"
            "The outline is sampled every 'sample step' along each "
            "landmark polygon's boundary (capped at 200 points - coarser "
            "steps on very large landmarks). Sight lines respect the DSM "
            "exactly as in the Viewshed tool.\n\n"
            "Output: visible-point count per cell (NoData where the DSM is "
            "empty); the log reports the share of cells that see the "
            "landmark at all.\n\n"
            "How to read the results\n"
            "- Treat the count as silhouette completeness: cells near "
            "the maximum see the WHOLE landmark (the postcard views), "
            "mid counts see it partially, 1-2 = glimpses between "
            "buildings. The high-count corridors radiating along "
            "streets are the classic 'view cones' heritage plans "
            "protect.\n"
            "- The zero/nonzero boundary is the landmark's visual "
            "catchment - the log's share number summarises it for "
            "comparing alternatives.\n"
            "- Weight by where people actually are: a high-count cell "
            "on a busy square is worth more than a hilltop nobody "
            "visits - overlay footfall or population before ranking "
            "views.\n\n"
            "Using the results: the before/after difference raster "
            "(insert the proposed massing into the DSM, rerun) IS the "
            "heritage-impact exhibit - it shows every place that loses "
            "sight of the minaret/tower/monument, with the count drop "
            "as severity; use it in reverse when siting a new civic "
            "landmark - candidate sites with larger high-count "
            "catchments buy more presence per storey."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.DSM, self.tr("Surface model (DSM, projected CRS)")))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.LANDMARKS, self.tr("Landmark footprint(s) (polygons)"),
            [QgsProcessing.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterNumber(
            self.EXTRA_HEIGHT,
            self.tr("Extra height above the DSM at the landmark (m)"),
            QgsProcessingParameterNumber.Double, 0.0, minValue=0.0,
            maxValue=1000.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.SAMPLE_STEP, self.tr("Outline sample step (map units)"),
            QgsProcessingParameterNumber.Double, 10.0, minValue=0.5))
        self.addParameter(QgsProcessingParameterNumber(
            self.EYE_HEIGHT, self.tr("Observer eye height (m)"),
            QgsProcessingParameterNumber.Double, 1.6, minValue=0.0,
            maxValue=100.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.RADIUS, self.tr("Exposure radius (map units, 0 = unlimited)"),
            QgsProcessingParameterNumber.Double, 0.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterRasterDestination(
            self.OUTPUT, self.tr("Landmark visibility count")))

    def processAlgorithm(self, parameters, context, feedback):
        dsm_layer = self.parameterAsRasterLayer(parameters, self.DSM, context)
        landmarks = self.parameterAsSource(parameters, self.LANDMARKS, context)
        extra_h = self.parameterAsDouble(parameters, self.EXTRA_HEIGHT, context)
        step = self.parameterAsDouble(parameters, self.SAMPLE_STEP, context)
        eye_h = self.parameterAsDouble(parameters, self.EYE_HEIGHT, context)
        radius = self.parameterAsDouble(parameters, self.RADIUS, context)
        out_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        dsm, gt, proj, pixel = read_dsm(dsm_layer)
        rows, cols = dsm.shape

        xform = None
        if landmarks.sourceCrs() != dsm_layer.crs():
            xform = QgsCoordinateTransform(
                landmarks.sourceCrs(), dsm_layer.crs(),
                context.transformContext())
        rim = []
        for f in landmarks.getFeatures():
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
            g = QgsGeometry(g)
            if xform is not None:
                g.transform(xform)
            dense = g.densifyByDistance(step)
            for v in dense.vertices():
                rim.append((v.x(), v.y()))
        if not rim:
            raise QgsProcessingException("No landmark geometry found.")
        if len(rim) > _MAX_RIM_POINTS:
            keep = np.linspace(0, len(rim) - 1, _MAX_RIM_POINTS).astype(int)
            rim = [rim[i] for i in keep]
            feedback.pushWarning(self.tr(
                f"Outline sampled down to {_MAX_RIM_POINTS} points - "
                "increase the sample step for full control."))

        total = np.zeros((rows, cols), dtype=np.float64)
        n_used = 0
        for i, (x, y) in enumerate(rim):
            if feedback.isCanceled():
                break
            col = int((x - gt[0]) / gt[1])
            row = int((y - gt[3]) / gt[5])
            if not (0 <= row < rows and 0 <= col < cols):
                continue
            vis = visibility.viewshed(
                dsm, pixel, (row, col), observer_h=extra_h, target_h=eye_h,
                radius=radius if radius > 0 else None, n_dirs=360,
                cancel=feedback.isCanceled)
            total += vis
            n_used += 1
            feedback.setProgress(100.0 * (i + 1) / len(rim))
        if n_used == 0:
            raise QgsProcessingException(
                "No landmark outline point lies on the DSM.")

        total[~np.isfinite(dsm)] = -1.0
        write_raster(out_path, total.astype(np.float32), gt, proj, -1.0)
        valid = int(np.isfinite(dsm).sum())
        seeing = float((total > 0).sum()) / max(1, valid)
        feedback.pushInfo(self.tr(
            f"{n_used} outline point(s); {100.0 * seeing:.1f} percent of "
            "cells see the landmark."))
        return {self.OUTPUT: out_path}

    def createInstance(self):
        return VisualExposureAlgorithm()
