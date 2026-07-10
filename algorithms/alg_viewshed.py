# -*- coding: utf-8 -*-
"""Viewshed (DSM): line-of-sight visibility from observer points."""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsProcessingException,
    QgsProcessing,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterRasterLayer,
)

from .base import GROUP_VISIBILITY, PlanXAlgorithm
from ._raster import read_dsm, write_raster
from ..engine import visibility


class ViewshedAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_VISIBILITY
    ICON = "tool_viewshed.png"
    DSM = "DSM"
    OBSERVERS = "OBSERVERS"
    OBSERVER_HEIGHT = "OBSERVER_HEIGHT"
    TARGET_HEIGHT = "TARGET_HEIGHT"
    RADIUS = "RADIUS"
    DIRECTIONS = "DIRECTIONS"
    OUTPUT = "OUTPUT"

    def name(self):
        return "viewshed"

    def displayName(self):
        return self.tr("Viewshed (DSM)")

    def shortHelpString(self):
        return self.tr(
            "What can be SEEN from here? Sweeps sight lines over a surface "
            "model (DSM - terrain plus buildings) from one or more observer "
            "points and writes the visibility count raster: how many "
            "observers see each cell.\n\n"
            "The observer's eye sits at the DSM surface plus the observer "
            "height; a cell counts as visible when the line to its surface "
            "plus the target height clears every surface in between - set "
            "a target height of 1.6 m to ask 'can a person THERE be seen', "
            "or leave 0 to test the bare ground.\n\n"
            "Uses the same radial-sweep idiom as the PlanX shadow tools: "
            "azimuth rays marched at half-pixel steps with a running "
            "horizon angle, capped at the raster diagonal. More directions "
            "= smoother edges, slower run.\n\n"
            "Output: visibility count per cell (0 = seen by nobody). With "
            "one observer it is a plain 0/1 viewshed. NoData where the DSM "
            "has no value. The log reports the visible share within the "
            "radius per observer.\n\n"
            "Applications: viewpoint and lookout planning, CCTV / lighting "
            "coverage, visual impact screening, defensible-space audits.\n\n"
            "How to read the results\n"
            "- With one observer the raster is binary truth: 1 = a "
            "sight line exists (vegetation and glazing permitting - the "
            "DSM is the arbiter). With many observers the VALUE is "
            "coverage redundancy: cells at 0 are blind spots, cells "
            "seen by 3+ observers are robust to losing one.\n"
            "- The visible-share percentage in the log turns a proposed "
            "lookout into a number - compare candidate viewpoints by "
            "it.\n"
            "- Remember the asymmetry knobs: observer height asks 'what "
            "do I see', target height asks 'can a person/object there "
            "be seen'. For surveillance questions set both.\n\n"
            "Using the results: for CCTV/lighting audits, map the "
            "0-count cells along pedestrian routes - those are the "
            "defensible-space fixes; for visual impact, put observers "
            "at the protected viewpoints and test whether the proposed "
            "massing cells fall inside their viewshed; for a new "
            "lookout or landmark, run Visual Exposure instead - it asks "
            "the reverse question (who can SEE the object)."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.DSM, self.tr("Surface model (DSM, projected CRS)")))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.OBSERVERS, self.tr("Observer points"),
            [QgsProcessing.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterNumber(
            self.OBSERVER_HEIGHT, self.tr("Observer height above surface (m)"),
            QgsProcessingParameterNumber.Double, 1.6, minValue=0.0,
            maxValue=500.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.TARGET_HEIGHT, self.tr("Target height above surface (m)"),
            QgsProcessingParameterNumber.Double, 0.0, minValue=0.0,
            maxValue=500.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.RADIUS, self.tr("View radius (map units, 0 = unlimited)"),
            QgsProcessingParameterNumber.Double, 0.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.DIRECTIONS, self.tr("Sweep directions"),
            QgsProcessingParameterNumber.Integer, 720, minValue=90,
            maxValue=3600))
        self.addParameter(QgsProcessingParameterRasterDestination(
            self.OUTPUT, self.tr("Visibility count")))

    def processAlgorithm(self, parameters, context, feedback):
        dsm_layer = self.parameterAsRasterLayer(parameters, self.DSM, context)
        observers = self.parameterAsSource(parameters, self.OBSERVERS, context)
        obs_h = self.parameterAsDouble(parameters, self.OBSERVER_HEIGHT, context)
        tgt_h = self.parameterAsDouble(parameters, self.TARGET_HEIGHT, context)
        radius = self.parameterAsDouble(parameters, self.RADIUS, context)
        n_dirs = self.parameterAsInt(parameters, self.DIRECTIONS, context)
        out_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        dsm, gt, proj, pixel = read_dsm(dsm_layer)
        rows, cols = dsm.shape
        o_xy, _feats = self.source_points(
            observers, dsm_layer.crs(), context.transformContext())

        total = np.zeros((rows, cols), dtype=np.float64)
        n_used = 0
        for i, (x, y) in enumerate(o_xy):
            if feedback.isCanceled():
                break
            col = int((x - gt[0]) / gt[1])
            row = int((y - gt[3]) / gt[5])
            if not (0 <= row < rows and 0 <= col < cols):
                feedback.pushWarning(self.tr(
                    f"Observer {i + 1} lies outside the DSM - skipped."))
                continue
            vis = visibility.viewshed(
                dsm, pixel, (row, col), observer_h=obs_h, target_h=tgt_h,
                radius=radius if radius > 0 else None, n_dirs=n_dirs,
                cancel=feedback.isCanceled)
            total += vis
            n_used += 1
            share = 100.0 * float(vis.sum()) / vis.size
            feedback.pushInfo(self.tr(
                f"Observer {i + 1}: sees {share:.1f} percent of the raster."))
            feedback.setProgress(100.0 * (i + 1) / len(o_xy))
        if n_used == 0:
            raise QgsProcessingException(
                "No observer lies on the DSM - check the layers' extents.")

        total[~np.isfinite(dsm)] = -1.0
        write_raster(out_path, total.astype(np.float32), gt, proj, -1.0)
        seen = float((total > 0).sum()) / max(1, int(np.isfinite(dsm).sum()))
        feedback.pushInfo(self.tr(
            f"{n_used} observer(s); {100.0 * seen:.1f} percent of cells "
            "seen by at least one."))
        return {self.OUTPUT: out_path}

    def createInstance(self):
        return ViewshedAlgorithm()
