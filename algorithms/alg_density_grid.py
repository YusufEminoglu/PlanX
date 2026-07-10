# -*- coding: utf-8 -*-
"""Density Grid: distribute any numeric value onto a regular grid."""
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

from .base import DOUBLE, GROUP_STANDARDS, INT, PlanXAlgorithm


class DensityGridAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_STANDARDS
    ICON = "tool_densitygrid.png"
    INPUT = "INPUT"
    VALUE_FIELD = "VALUE_FIELD"
    CELL_SIZE = "CELL_SIZE"
    OUTPUT = "OUTPUT"

    def name(self):
        return "densitygrid"

    def displayName(self):
        return self.tr("Density Grid")

    def shortHelpString(self):
        return self.tr(
            "Distributes a numeric value (population, dwellings, jobs, gross "
            "floor area...) from buildings, parcels or census polygons onto "
            "a regular grid and reports density per hectare - the quickest "
            "way to compare planned density against thresholds or to feed "
            "other PlanX tools with a uniform analysis surface.\n\n"
            "Polygons are split by area share (a building half inside a "
            "cell contributes half its value - simple dasymetric "
            "disaggregation); points contribute fully to the cell that "
            "contains them. Leave the value field empty to simply count "
            "features.\n\n"
            "Output cells carry the summed value, density per hectare and "
            "the contributing feature count; empty cells are skipped.\n\n"
            "How to read the results\n"
            "- dens_ha puts every district on one comparable scale "
            "regardless of parcel size. Reference points for population: "
            "under ~30 persons/ha struggles to support bus service and "
            "local shops; 50-150/ha = walkable urban range; 300+/ha "
            "needs serious open-space and infrastructure provision.\n"
            "- The grid exposes what averages hide: a 'low-density' "
            "district may contain cells at three times the plan cap - "
            "those cells, not the average, drive school and park demand.\n"
            "- Mind the modifiable-unit effect: cell size changes the "
            "picture. 100 m cells show project-level texture; 500 m "
            "cells show structure. Quote the cell size with any number.\n\n"
            "Using the results: check cells against the plan's density "
            "caps (the outliers are either data errors or enforcement "
            "cases); use the population grid as the demand input for "
            "Facility Adequacy / Green Access so provision follows "
            "people, not parcels; difference two horizon grids to map "
            "where growth is actually being placed."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT, self.tr("Source features (polygons or points)"),
            [QgsProcessing.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterField(
            self.VALUE_FIELD, self.tr("Value field (empty = count features)"),
            parentLayerParameterName=self.INPUT, optional=True,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.CELL_SIZE, self.tr("Grid cell size (map units)"),
            QgsProcessingParameterNumber.Double, 100.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Density grid")))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        value_field = self.parameterAsString(parameters, self.VALUE_FIELD, context)
        cell = self.parameterAsDouble(parameters, self.CELL_SIZE, context)
        self.require_projected(source, "Source features")

        v_idx = source.fields().lookupField(value_field) if value_field else -1
        feats = []   # (geometry, value, area_or_None)
        index = QgsSpatialIndex()
        for f in source.getFeatures():
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
            value = 1.0
            if v_idx >= 0:
                try:
                    value = float(f.attributes()[v_idx])
                except (TypeError, ValueError):
                    value = 0.0
            is_poly = QgsWkbTypes.geometryType(g.wkbType()) == QgsWkbTypes.PolygonGeometry
            area = g.area() if is_poly else None
            i = len(feats)
            feats.append((g, value, area))
            pf = QgsFeature(i)
            pf.setGeometry(g)
            index.addFeature(pf)
        if not feats:
            raise QgsProcessingException("No usable features.")

        extent = QgsRectangle()
        for g, _, _ in feats:
            extent.combineExtentWith(g.boundingBox())
        x0 = math.floor(extent.xMinimum() / cell) * cell
        y0 = math.floor(extent.yMinimum() / cell) * cell
        nx = int(math.ceil((extent.xMaximum() - x0) / cell)) or 1
        ny = int(math.ceil((extent.yMaximum() - y0) / cell)) or 1
        feedback.pushInfo(self.tr(
            f"{len(feats)} features; grid {nx} x {ny} cells of {cell:g}"))

        fields = self.make_fields(("cell_id", INT), ("n_feat", INT),
                                  ("value", DOUBLE), ("dens_ha", DOUBLE))
        sink, dest = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields,
            QgsWkbTypes.Polygon, source.sourceCrs())
        cell_ha = cell * cell / 10000.0
        cid = 0
        for iy in range(ny):
            if feedback.isCanceled():
                break
            for ix in range(nx):
                rect = QgsRectangle(x0 + ix * cell, y0 + iy * cell,
                                    x0 + (ix + 1) * cell, y0 + (iy + 1) * cell)
                cell_geom = QgsGeometry.fromRect(rect)
                total = 0.0
                count = 0
                for hid in index.intersects(rect):
                    g, value, area = feats[hid]
                    if area is None:
                        # point/line: count where the representative point falls
                        if cell_geom.contains(g.pointOnSurface()):
                            total += value
                            count += 1
                        continue
                    inter = cell_geom.intersection(g)
                    if inter is None or inter.isEmpty():
                        continue
                    a = inter.area()
                    if a <= 0 or area <= 0:
                        continue
                    total += value * (a / area)
                    count += 1
                if count == 0:
                    continue
                out = QgsFeature(fields)
                out.setGeometry(cell_geom)
                out.setAttributes([cid, count, round(total, 4),
                                   round(total / cell_ha, 4)])
                sink.addFeature(out, QgsFeatureSink.FastInsert)
                cid += 1
            feedback.setProgress(int(100.0 * (iy + 1) / ny))
        feedback.pushInfo(self.tr(f"Wrote {cid} occupied cells."))
        return {self.OUTPUT: dest}

    def createInstance(self):
        return DensityGridAlgorithm()
