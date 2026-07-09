# -*- coding: utf-8 -*-
"""Isovist Field: 2-D visibility measures on a point grid between buildings."""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsFeature,
    QgsFeatureSink,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterExtent,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
    QgsSpatialIndex,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_VISIBILITY, PlanXAlgorithm
from ..engine import visibility


class IsovistFieldAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_VISIBILITY
    ICON = "tool_isovistfield.png"
    BUILDINGS = "BUILDINGS"
    EXTENT = "EXTENT"
    CELL = "CELL"
    N_RAYS = "N_RAYS"
    MAX_DIST = "MAX_DIST"
    OUT_POINTS = "OUT_POINTS"

    def name(self):
        return "isovistfield"

    def displayName(self):
        return self.tr("Isovist Field")

    def shortHelpString(self):
        return self.tr(
            "How does OPEN SPACE feel from inside? Samples a point grid "
            "between the buildings and measures the ISOVIST at every point "
            "- the 2-D area you can see standing there (Benedikt 1979), the "
            "visibility-graph companion to the street-network space syntax "
            "tools.\n\n"
            "Buildings are rasterised to an obstacle grid at the cell size; "
            "rays march from every free cell to the first obstacle, the "
            "range limit or the study edge. Per point it reports:\n"
            "- iso_area / iso_perim: the visible polygon's size;\n"
            "- min_rad / max_rad / mean_rad: shortest, longest and mean "
            "sight line;\n"
            "- circular: 4 pi A / P squared - 1 for a plaza, small for "
            "corridors;\n"
            "- occlus: the share of sight lines stopped by a building "
            "rather than by range - high where walls dominate the view.\n\n"
            "Style 'iso_area' for the classic openness map: plazas glow, "
            "alleys darken. The extent defaults to the buildings layer; "
            "give your own to frame a district. Use a projected CRS.\n\n"
            "Cost grows with grid points x rays - start with a 10 m cell "
            "and 180 rays, refine where it matters."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.BUILDINGS, self.tr("Buildings (polygons)"),
            [QgsProcessing.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterExtent(
            self.EXTENT, self.tr("Study extent (empty = buildings extent)"),
            optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.CELL, self.tr("Grid cell size (map units)"),
            QgsProcessingParameterNumber.Double, 10.0, minValue=0.5))
        self.addParameter(QgsProcessingParameterNumber(
            self.N_RAYS, self.tr("Rays per point"),
            QgsProcessingParameterNumber.Integer, 180, minValue=36,
            maxValue=1440))
        self.addParameter(QgsProcessingParameterNumber(
            self.MAX_DIST, self.tr("Max sight distance (map units)"),
            QgsProcessingParameterNumber.Double, 200.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_POINTS, self.tr("Isovist points")))

    def processAlgorithm(self, parameters, context, feedback):
        buildings = self.parameterAsSource(parameters, self.BUILDINGS, context)
        cell = self.parameterAsDouble(parameters, self.CELL, context)
        n_rays = self.parameterAsInt(parameters, self.N_RAYS, context)
        max_dist = self.parameterAsDouble(parameters, self.MAX_DIST, context)
        self.require_projected(buildings, "Buildings")
        crs = buildings.sourceCrs()
        extent = self.parameterAsExtent(parameters, self.EXTENT, context, crs)
        if extent is None or extent.isEmpty():
            extent = buildings.sourceExtent()

        cols = max(2, int(np.ceil(extent.width() / cell)))
        rows = max(2, int(np.ceil(extent.height() / cell)))
        if rows * cols > 400000:
            raise QgsProcessingException(
                f"{rows * cols} grid cells - use a larger cell size or a "
                "smaller extent.")
        x0, y1 = extent.xMinimum(), extent.yMaximum()

        index = QgsSpatialIndex()
        geoms = []
        for f in buildings.getFeatures():
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
            qf = QgsFeature(len(geoms))
            qf.setGeometry(g)
            index.insertFeature(qf)
            geoms.append(g)
        if not geoms:
            raise QgsProcessingException("No building geometry found.")

        feedback.pushInfo(self.tr(
            f"Obstacle grid {rows} x {cols} at {cell:g}; {len(geoms)} "
            f"buildings; {n_rays} rays up to {max_dist:g}."))
        mask = np.zeros((rows, cols), dtype=bool)
        centers = {}
        for r in range(rows):
            if feedback.isCanceled():
                break
            cy = y1 - (r + 0.5) * cell
            for c in range(cols):
                cx = x0 + (c + 0.5) * cell
                pt = QgsGeometry.fromPointXY(QgsPointXY(cx, cy))
                blocked = False
                for fid in index.intersects(pt.boundingBox()):
                    if geoms[fid].intersects(pt):
                        blocked = True
                        break
                mask[r, c] = blocked
                if not blocked:
                    centers[(r, c)] = (cx, cy)
            feedback.setProgress(30.0 * (r + 1) / rows)

        points = list(centers.keys())
        fld = visibility.isovist_field(
            mask, points, pixel=cell, n_rays=n_rays, max_dist=max_dist,
            cancel=feedback.isCanceled)

        fields = self.make_fields(
            ("iso_area", DOUBLE), ("iso_perim", DOUBLE), ("min_rad", DOUBLE),
            ("max_rad", DOUBLE), ("mean_rad", DOUBLE), ("circular", DOUBLE),
            ("occlus", DOUBLE))
        sink, dest = self.parameterAsSink(
            parameters, self.OUT_POINTS, context, fields,
            QgsWkbTypes.Point, crs)
        for i, rc in enumerate(points):
            if feedback.isCanceled():
                break
            out = QgsFeature(fields)
            out.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*centers[rc])))
            out.setAttributes([
                round(float(fld["area"][i]), 1),
                round(float(fld["perimeter"][i]), 1),
                round(float(fld["min_rad"][i]), 2),
                round(float(fld["max_rad"][i]), 2),
                round(float(fld["mean_rad"][i]), 2),
                round(float(fld["circularity"][i]), 4),
                round(float(fld["occlusivity"][i]), 4)])
            sink.addFeature(out, QgsFeatureSink.FastInsert)

        feedback.pushInfo(self.tr(
            f"{len(points)} isovist points; mean visible area "
            f"{float(fld['area'].mean()):,.0f}, mean occlusivity "
            f"{float(fld['occlusivity'].mean()):.2f}."))
        return {self.OUT_POINTS: dest}

    def createInstance(self):
        return IsovistFieldAlgorithm()
