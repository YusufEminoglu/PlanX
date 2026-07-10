# -*- coding: utf-8 -*-
"""Frontal Area Index: wind-facing building density on a grid."""
from __future__ import annotations

import math

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

from .base import DOUBLE, GROUP_MICRO, INT, PlanXAlgorithm
from .alg_building_metrics import _main_rings
from ..engine import solar


class FrontalAreaIndexAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_MICRO
    ICON = "tool_frontalarea.png"
    BUILDINGS = "BUILDINGS"
    HEIGHT_FIELD = "HEIGHT_FIELD"
    DEFAULT_HEIGHT = "DEFAULT_HEIGHT"
    WIND_DIR = "WIND_DIR"
    CELL_SIZE = "CELL_SIZE"
    OUTPUT = "OUTPUT"

    def name(self):
        return "frontalarea"

    def displayName(self):
        return self.tr("Frontal Area Index")

    def shortHelpString(self):
        return self.tr(
            "Computes the frontal area index (lambda_f) and plan area index "
            "(lambda_p) per grid cell - the standard urban roughness "
            "indicators for wind permeability and ventilation-corridor "
            "studies (Grimmond and Oke 1999).\n\n"
            "lambda_f = wind-facing facade area / cell area: each building "
            "contributes its footprint width perpendicular to the wind "
            "times its height, distributed over the cells it overlaps. "
            "lambda_p = footprint area / cell area.\n\n"
            "Typical reading: lambda_f below 0.1 = open, 0.1-0.3 = "
            "moderate roughness, above 0.3 = strong wind blockage. Wind "
            "direction is the compass bearing the wind comes FROM "
            "(0 = north, 90 = east). Heights come from a numeric field "
            "(metres) or the default value.\n\n"
            "How to read the results\n"
            "- Run it with the prevailing SUMMER breeze direction: the "
            "map then shows where cooling air can and cannot penetrate. "
            "Continuous low-lambda_f bands aligned with the wind are "
            "your ventilation corridors - the asset to protect.\n"
            "- lambda_f > 0.3 cells form barriers: rows of slabs "
            "perpendicular to the breeze that dam the airflow. A single "
            "tall perimeter row can shelter (and overheat) an entire "
            "district behind it.\n"
            "- Compare lambda_f under different wind directions: fabric "
            "that is open north-south but closed east-west only "
            "ventilates in one season.\n"
            "- lambda_p is plain coverage - use it to separate 'dense "
            "but low' (high lambda_p, low lambda_f) from 'porous but "
            "tall' fabric; they behave differently for wind and heat.\n\n"
            "Using the results: keep new massing out of the low-lambda_f "
            "corridors that feed hot districts; orient new slabs "
            "parallel to the breeze; pair with Sky View Factor and Heat "
            "Risk Grid for a complete ventilation-and-heat screening."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.BUILDINGS, self.tr("Buildings (polygons)"),
            [QgsProcessing.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterField(
            self.HEIGHT_FIELD, self.tr("Height field, metres (empty = default)"),
            parentLayerParameterName=self.BUILDINGS, optional=True,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.DEFAULT_HEIGHT, self.tr("Default building height (m)"),
            QgsProcessingParameterNumber.Double, 6.0, minValue=0.1))
        self.addParameter(QgsProcessingParameterNumber(
            self.WIND_DIR, self.tr("Wind direction (degrees from north, wind FROM)"),
            QgsProcessingParameterNumber.Double, 0.0, minValue=0.0, maxValue=360.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.CELL_SIZE, self.tr("Grid cell size (map units)"),
            QgsProcessingParameterNumber.Double, 100.0, minValue=10.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Roughness grid")))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.BUILDINGS, context)
        height_field = self.parameterAsString(parameters, self.HEIGHT_FIELD, context)
        default_h = self.parameterAsDouble(parameters, self.DEFAULT_HEIGHT, context)
        wind_dir = self.parameterAsDouble(parameters, self.WIND_DIR, context)
        cell = self.parameterAsDouble(parameters, self.CELL_SIZE, context)
        self.require_projected(source, "Buildings")

        h_idx = source.fields().lookupField(height_field) if height_field else -1
        blds = []   # (geometry, frontal_area, footprint_area)
        index = QgsSpatialIndex()
        for f in source.getFeatures():
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
            h = default_h
            if h_idx >= 0:
                try:
                    h = float(f.attributes()[h_idx])
                except (TypeError, ValueError):
                    h = default_h
            ext_ring, _ = _main_rings(g)
            if ext_ring is None:
                continue
            frontal = solar.projected_width(ext_ring, wind_dir) * max(h, 0.0)
            i = len(blds)
            blds.append((g, frontal, g.area()))
            pf = QgsFeature(i)
            pf.setGeometry(g)
            index.addFeature(pf)
        if not blds:
            raise QgsProcessingException("No usable building polygons.")
        extent = QgsRectangle()
        for g, _, _ in blds:
            extent.combineExtentWith(g.boundingBox())

        fields = self.make_fields(("cell_id", INT), ("b_count", INT),
                                  ("lambda_f", DOUBLE), ("lambda_p", DOUBLE))
        sink, dest = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields,
            QgsWkbTypes.Polygon, source.sourceCrs())

        x0 = math.floor(extent.xMinimum() / cell) * cell
        y0 = math.floor(extent.yMinimum() / cell) * cell
        nx = int(math.ceil((extent.xMaximum() - x0) / cell))
        ny = int(math.ceil((extent.yMaximum() - y0) / cell))
        feedback.pushInfo(self.tr(
            f"{len(blds)} buildings; grid {nx} x {ny} cells of {cell:g}"))
        cell_area = cell * cell
        cid = 0
        total = max(1, nx * ny)
        for iy in range(ny):
            if feedback.isCanceled():
                break
            for ix in range(nx):
                rect = QgsRectangle(x0 + ix * cell, y0 + iy * cell,
                                    x0 + (ix + 1) * cell, y0 + (iy + 1) * cell)
                cell_geom = QgsGeometry.fromRect(rect)
                lam_f = lam_p = 0.0
                count = 0
                for bid in index.intersects(rect):
                    g, frontal, fp_area = blds[bid]
                    inter = cell_geom.intersection(g)
                    if inter is None or inter.isEmpty():
                        continue
                    a = inter.area()
                    if a <= 0 or fp_area <= 0:
                        continue
                    share = a / fp_area
                    lam_f += frontal * share / cell_area
                    lam_p += a / cell_area
                    count += 1
                if count == 0:
                    continue  # keep the grid sparse: only built cells
                out = QgsFeature(fields)
                out.setGeometry(cell_geom)
                out.setAttributes([cid, count, lam_f, lam_p])
                sink.addFeature(out, QgsFeatureSink.FastInsert)
                cid += 1
            feedback.setProgress(int(100.0 * (iy + 1) * nx / total))
        feedback.pushInfo(self.tr(f"Wrote {cid} built grid cells."))
        return {self.OUTPUT: dest}

    def createInstance(self):
        return FrontalAreaIndexAlgorithm()
