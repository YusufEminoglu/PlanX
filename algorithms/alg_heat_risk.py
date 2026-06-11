# -*- coding: utf-8 -*-
"""Heat Island Risk Grid: vector UHI screening from built/green/water shares."""
from __future__ import annotations

import math

import numpy as np

from qgis.core import (
    QgsFeature,
    QgsFeatureSink,
    QgsGeometry,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsRectangle,
    QgsSpatialIndex,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_MICRO, INT, STRING, PlanXAlgorithm
from ..engine import solar


def _coverage(items, index, cell_geom, rect):
    """(covered_area, area-weighted height sum) of polygons inside a cell."""
    area = 0.0
    h_sum = 0.0
    for hid in index.intersects(rect):
        g, h = items[hid]
        inter = cell_geom.intersection(g)
        if inter is None or inter.isEmpty():
            continue
        a = inter.area()
        area += a
        h_sum += a * h
    return area, h_sum


class HeatRiskGridAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_MICRO
    ICON = "tool_heatrisk.png"
    BUILDINGS = "BUILDINGS"
    HEIGHT_FIELD = "HEIGHT_FIELD"
    GREEN = "GREEN"
    WATER = "WATER"
    CELL_SIZE = "CELL_SIZE"
    H_REF = "H_REF"
    W_BUILT = "W_BUILT"
    W_HEIGHT = "W_HEIGHT"
    W_GREEN = "W_GREEN"
    W_WATER = "W_WATER"
    OUTPUT = "OUTPUT"

    def name(self):
        return "heatriskgrid"

    def displayName(self):
        return self.tr("Heat Island Risk Grid")

    def shortHelpString(self):
        return self.tr(
            "Screens a plan area for urban heat island risk on a regular "
            "grid - no satellite imagery or DSM needed, just the layers "
            "every plan already has: building footprints, green areas and "
            "(optionally) water.\n\n"
            "Per cell the tool measures the built fraction, area-weighted "
            "mean building height, green fraction and water fraction, then "
            "combines them into a fixed-scale 0-100 risk score:\n"
            "risk = w_built*built + w_height*min(h/h_ref,1) - w_green*green "
            "- w_water*water, rescaled so the theoretical extremes (fully "
            "vegetated vs fully built at reference height) map to 0 and "
            "100. Because the scale is set by the weights - not stretched "
            "to the data - scores are comparable between scenarios and "
            "study areas: re-run after adding a park and the numbers are "
            "directly comparable.\n\n"
            "Output: risk score, class (Low / Moderate / High / Very High "
            "at 25/50/75) and all component fractions per cell. Defaults "
            "follow the common surface-cover reasoning (built 0.4, height "
            "0.2, green 0.3, water 0.1)."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.BUILDINGS, self.tr("Building footprints (polygons)"),
            [QgsProcessing.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterField(
            self.HEIGHT_FIELD, self.tr("Building height field (m, empty = ignore height)"),
            parentLayerParameterName=self.BUILDINGS, optional=True,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.GREEN, self.tr("Green / vegetated areas (polygons, optional)"),
            [QgsProcessing.TypeVectorPolygon], optional=True))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.WATER, self.tr("Water bodies (polygons, optional)"),
            [QgsProcessing.TypeVectorPolygon], optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.CELL_SIZE, self.tr("Grid cell size (map units)"),
            QgsProcessingParameterNumber.Double, 100.0, minValue=10.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.H_REF, self.tr("Reference height for full height effect (m)"),
            QgsProcessingParameterNumber.Double, 20.0, minValue=1.0))
        for key, label, default in (
                (self.W_BUILT, "Weight: built fraction", 0.4),
                (self.W_HEIGHT, "Weight: building height", 0.2),
                (self.W_GREEN, "Weight: green cooling", 0.3),
                (self.W_WATER, "Weight: water cooling", 0.1)):
            self.addParameter(QgsProcessingParameterNumber(
                key, self.tr(label), QgsProcessingParameterNumber.Double,
                default, minValue=0.0, maxValue=1.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Heat risk grid")))

    @staticmethod
    def _load_polygons(source, height_idx=-1):
        """Read (geometry, height) tuples + spatial index from a source."""
        items = []
        index = QgsSpatialIndex()
        if source is None:
            return items, index
        for f in source.getFeatures():
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
            h = 0.0
            if height_idx >= 0:
                try:
                    h = float(f.attributes()[height_idx] or 0.0)
                except (TypeError, ValueError):
                    h = 0.0
            i = len(items)
            items.append((g, h))
            pf = QgsFeature(i)
            pf.setGeometry(g)
            index.addFeature(pf)
        return items, index

    def processAlgorithm(self, parameters, context, feedback):
        buildings = self.parameterAsSource(parameters, self.BUILDINGS, context)
        height_field = self.parameterAsString(parameters, self.HEIGHT_FIELD, context)
        green = self.parameterAsSource(parameters, self.GREEN, context)
        water = self.parameterAsSource(parameters, self.WATER, context)
        cell = self.parameterAsDouble(parameters, self.CELL_SIZE, context)
        h_ref = self.parameterAsDouble(parameters, self.H_REF, context)
        w_built = self.parameterAsDouble(parameters, self.W_BUILT, context)
        w_height = self.parameterAsDouble(parameters, self.W_HEIGHT, context)
        w_green = self.parameterAsDouble(parameters, self.W_GREEN, context)
        w_water = self.parameterAsDouble(parameters, self.W_WATER, context)
        self.require_projected(buildings, "Building footprints")
        if not height_field:
            w_height = 0.0

        h_idx = buildings.fields().lookupField(height_field) if height_field else -1
        b_items, b_index = self._load_polygons(buildings, h_idx)
        if not b_items:
            raise QgsProcessingException("No usable building polygons.")
        g_items, g_index = self._load_polygons(green)
        w_items, w_index = self._load_polygons(water)

        extent = QgsRectangle()
        for g, _ in b_items + g_items + w_items:
            extent.combineExtentWith(g.boundingBox())
        x0 = math.floor(extent.xMinimum() / cell) * cell
        y0 = math.floor(extent.yMinimum() / cell) * cell
        nx = int(math.ceil((extent.xMaximum() - x0) / cell)) or 1
        ny = int(math.ceil((extent.yMaximum() - y0) / cell)) or 1
        feedback.pushInfo(self.tr(
            f"{len(b_items)} buildings, {len(g_items)} green, {len(w_items)} "
            f"water polygons; grid {nx} x {ny} cells of {cell:g}"))

        cells = []  # (geometry, built, green, water, height)
        cell_area = cell * cell
        for iy in range(ny):
            if feedback.isCanceled():
                break
            for ix in range(nx):
                rect = QgsRectangle(x0 + ix * cell, y0 + iy * cell,
                                    x0 + (ix + 1) * cell, y0 + (iy + 1) * cell)
                cell_geom = QgsGeometry.fromRect(rect)
                ba, bh = _coverage(b_items, b_index, cell_geom, rect)
                ga, _ = _coverage(g_items, g_index, cell_geom, rect)
                wa, _ = _coverage(w_items, w_index, cell_geom, rect)
                if ba <= 0 and ga <= 0 and wa <= 0:
                    continue
                mean_h = (bh / ba) if ba > 0 else 0.0
                cells.append((cell_geom, min(ba / cell_area, 1.0),
                              min(ga / cell_area, 1.0),
                              min(wa / cell_area, 1.0), mean_h))
            feedback.setProgress(int(90.0 * (iy + 1) / ny))
        if not cells:
            raise QgsProcessingException("No occupied grid cells.")

        risk = solar.heat_risk_index(
            np.array([c[1] for c in cells]), np.array([c[2] for c in cells]),
            np.array([c[3] for c in cells]), np.array([c[4] for c in cells]),
            h_ref=h_ref, w_built=w_built, w_height=w_height,
            w_green=w_green, w_water=w_water)

        fields = self.make_fields(
            ("cell_id", INT), ("built_frac", DOUBLE), ("green_frac", DOUBLE),
            ("water_frac", DOUBLE), ("mean_h", DOUBLE), ("uhi_risk", DOUBLE),
            ("risk_class", STRING))
        sink, dest = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields,
            QgsWkbTypes.Polygon, buildings.sourceCrs())
        for i, (geom, bf, gf, wf, mh) in enumerate(cells):
            r = float(risk[i])
            klass = ("Low" if r < 25.0 else "Moderate" if r < 50.0
                     else "High" if r < 75.0 else "Very High")
            f = QgsFeature(fields)
            f.setGeometry(geom)
            f.setAttributes([i, round(bf, 4), round(gf, 4), round(wf, 4),
                             round(mh, 2), round(r, 2), klass])
            sink.addFeature(f, QgsFeatureSink.FastInsert)
        share_hot = float((risk >= 75.0).mean())
        feedback.pushInfo(self.tr(
            f"{len(cells)} cells | mean risk {float(risk.mean()):.1f} | "
            f"Very High share {share_hot:.1%}"))
        return {self.OUTPUT: dest}

    def createInstance(self):
        return HeatRiskGridAlgorithm()
