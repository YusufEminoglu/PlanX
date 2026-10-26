# -*- coding: utf-8 -*-
"""Least-Cost Corridor: cost distance, the least-cost path and its corridor."""
from __future__ import annotations

import math

import numpy as np

from osgeo import gdal, ogr, osr
from qgis.core import (
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureSink,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterRasterLayer,
    QgsWkbTypes,
)

from . import _units
from ._raster import read_dsm, write_raster
from .base import DOUBLE, GROUP_GREEN, INT, PlanXAlgorithm
from ..engine import costdistance

gdal.UseExceptions()

_NODATA = -9999.0


def _rasterize(source, raster_crs, transform_context, gt, shape, proj):
    """Boolean grid of the cells a vector source touches (ALL_TOUCHED)."""
    rows, cols = shape
    driver = gdal.GetDriverByName("MEM")
    target = driver.Create("", cols, rows, 1, gdal.GDT_Byte)
    target.SetGeoTransform(gt)
    if proj:
        target.SetProjection(proj)
    target.GetRasterBand(1).Fill(0)
    srs = osr.SpatialReference()
    if proj:
        srs.ImportFromWkt(proj)
    # GDAL 3.11 folded the vector "Memory" driver into "MEM"; take whichever exists.
    vector_driver = ogr.GetDriverByName("Memory") or ogr.GetDriverByName("MEM")
    vector = vector_driver.CreateDataSource("")
    layer = vector.CreateLayer("src", srs if proj else None, ogr.wkbUnknown)
    xform = None
    if source.sourceCrs() != raster_crs:
        xform = QgsCoordinateTransform(source.sourceCrs(), raster_crs, transform_context)
    count = 0
    for feature in source.getFeatures():
        geom = feature.geometry()
        if geom is None or geom.isEmpty():
            continue
        geom = QgsGeometry(geom)
        if xform is not None:
            geom.transform(xform)
        ogr_feature = ogr.Feature(layer.GetLayerDefn())
        ogr_feature.SetGeometry(ogr.CreateGeometryFromWkb(bytes(geom.asWkb())))
        layer.CreateFeature(ogr_feature)
        count += 1
    if not count:
        raise QgsProcessingException(f"'{source.sourceName()}' has no usable geometry.")
    gdal.RasterizeLayer(target, [1], layer, burn_values=[1], options=["ALL_TOUCHED=TRUE"])
    return target.GetRasterBand(1).ReadAsArray().astype(bool)


class LeastCostCorridorAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_GREEN
    ICON = "tool_leastcostcorridor.png"

    RESISTANCE = "RESISTANCE"
    SOURCES = "SOURCES"
    TARGETS = "TARGETS"
    RULE = "RULE"
    SLACK = "SLACK"
    OUT_COST = "OUT_COST"
    OUT_CORRIDOR = "OUT_CORRIDOR"
    OUT_PATH = "OUT_PATH"

    RULES = ["8 directions (queen)", "4 directions (rook)"]

    def name(self):
        return "leastcostcorridor"

    def displayName(self):
        return self.tr("Least-Cost Corridor")

    def shortHelpString(self):
        return self.tr(
            "The cheapest way across a resistance surface between two sets "
            "of places - habitat patches for a wildlife corridor, two ends of "
            "a greenway, a pipeline's endpoints - and the band of near-optimal "
            "routes around it.\n\n"
            "The resistance raster gives the cost of crossing one metre of "
            "each cell (1 = easy; 10 = ten times harder; nodata = impassable). "
            "Accumulated cost spreads from the sources by Dijkstra on the cell "
            "grid with the trapezoid rule every GIS uses - half of the cell you "
            "leave plus half of the one you enter, times the ground step "
            "length, diagonals sqrt(2) longer. The least-cost path runs to the "
            "cheapest target cell; the corridor is the sum of the cost "
            "surfaces from both sides minus the path cost (Linkage Mapper's "
            "normalised least-cost corridor): 0 along the best route, and "
            "elsewhere how much dearer a route through that cell would be.\n\n"
            "Outputs: the cost-distance raster from the sources, the "
            "normalised corridor raster (cells within the slack are the "
            "corridor to protect; the log reports its area), and the path as "
            "a line with its cost, ground length, the straight-line distance "
            "and their ratio.\n\n"
            "How to read the results\n"
            "- path cost / straight distance is the effective resistance of "
            "the link: 1 on a uniform surface of resistance 1, higher the "
            "more the route has to cross or skirt hostile ground.\n"
            "- A corridor that is wide at a given slack has many near-equal "
            "routes; a narrow waist is a pinch point, where a single barrier "
            "would cut the link.\n"
            "- A path that bends round a block of high resistance is the tool "
            "telling you where the barrier is - test it by lowering that "
            "block's resistance (a green bridge, a culvert) and rerunning.\n\n"
            "Using the results: overlay the corridor at a slack of 5-10 "
            "percent of the path cost with the land-use plan to find the "
            "parcels that must stay open; compare path costs before and after "
            "a development scenario to measure how much harder the link "
            "became."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.RESISTANCE, self.tr("Resistance raster (cost per metre; nodata = barrier)")))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.SOURCES, self.tr("Sources (habitat A)"),
            [QgsProcessing.SourceType.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.TARGETS, self.tr("Targets (habitat B)"),
            [QgsProcessing.SourceType.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterEnum(
            self.RULE, self.tr("Movement"), self.RULES, defaultValue=0))
        self.addParameter(QgsProcessingParameterNumber(
            self.SLACK, self.tr("Corridor slack, percent of the path cost"),
            QgsProcessingParameterNumber.Type.Double, 10.0, minValue=0.0, maxValue=1000.0))
        self.addParameter(QgsProcessingParameterRasterDestination(
            self.OUT_COST, self.tr("Cost distance from the sources")))
        self.addParameter(QgsProcessingParameterRasterDestination(
            self.OUT_CORRIDOR, self.tr("Normalised corridor")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_PATH, self.tr("Least-cost path"), type=QgsProcessing.SourceType.TypeVectorLine))

    def processAlgorithm(self, parameters, context, feedback):
        layer = self.parameterAsRasterLayer(parameters, self.RESISTANCE, context)
        sources = self.parameterAsSource(parameters, self.SOURCES, context)
        targets = self.parameterAsSource(parameters, self.TARGETS, context)
        rule = 8 if self.parameterAsEnum(parameters, self.RULE, context) == 0 else 4
        slack_pct = self.parameterAsDouble(parameters, self.SLACK, context)
        grid, gt, proj, pixel = read_dsm(layer)
        if np.any(grid[np.isfinite(grid)] < 0):
            raise QgsProcessingException(
                "The resistance raster has negative cells. A resistance is a cost per "
                "metre and cannot be negative - shortest paths are undefined with "
                "negative costs.")
        crs = layer.crs()
        ctx = context.transformContext()
        units = _units.GroundUnits(crs, ctx)
        per_unit = units.scale(layer.extent())
        cell_m = pixel / per_unit
        a_mask = _rasterize(sources, crs, ctx, gt, grid.shape, proj)
        b_mask = _rasterize(targets, crs, ctx, gt, grid.shape, proj)
        a_mask &= np.isfinite(grid)
        b_mask &= np.isfinite(grid)
        if not a_mask.any() or not b_mask.any():
            raise QgsProcessingException(
                "The sources or the targets touch no passable cell of the resistance "
                "raster - check that they overlap it and are not on nodata.")
        feedback.pushInfo(self.tr(
            f"{grid.shape[1]} x {grid.shape[0]} cells of {cell_m:.3f} ground m; "
            f"{int(a_mask.sum())} source and {int(b_mask.sum())} target cells; "
            f"{rule}-direction movement."))
        try:
            cost_a, pred_a = costdistance.cost_distance(grid, a_mask, cell_m, rule)
            feedback.setProgress(40)
            cost_b, _ = costdistance.cost_distance(grid, b_mask, cell_m, rule)
            feedback.setProgress(80)
            corr, best = costdistance.corridor(cost_a, cost_b)
        except ValueError as exc:
            raise QgsProcessingException(str(exc))

        cost_out = np.where(np.isfinite(cost_a), cost_a, _NODATA)
        corr_out = np.where(np.isfinite(corr), corr, _NODATA)
        cost_path = self.parameterAsOutputLayer(parameters, self.OUT_COST, context)
        corr_path = self.parameterAsOutputLayer(parameters, self.OUT_CORRIDOR, context)
        write_raster(cost_path, cost_out.astype(np.float64), gt, proj, _NODATA, dtype=gdal.GDT_Float64)
        write_raster(corr_path, corr_out.astype(np.float64), gt, proj, _NODATA, dtype=gdal.GDT_Float64)

        # Path to the cheapest target cell.
        target_costs = np.where(b_mask, cost_a, np.inf)
        end = int(np.argmin(target_costs))
        cells = costdistance.trace_path(pred_a, end)
        cols = grid.shape[1]
        pts = [QgsPointXY(gt[0] + (c % cols + 0.5) * gt[1] + (c // cols + 0.5) * gt[2],
                          gt[3] + (c % cols + 0.5) * gt[4] + (c // cols + 0.5) * gt[5])
               for c in cells]
        if len(pts) == 1:
            pts = [pts[0], pts[0]]
        line = QgsGeometry.fromPolylineXY(pts)
        length_m = units.length(line)
        straight = units.length(QgsGeometry.fromPolylineXY([pts[0], pts[-1]]))
        fields = self.make_fields(("path_cost", DOUBLE), ("length_m", DOUBLE),
                                  ("straight_m", DOUBLE), ("cost_ratio", DOUBLE),
                                  ("cells", INT), ("corridor_ha", DOUBLE))
        slack = best * slack_pct / 100.0
        corridor_cells = int(np.sum(np.isfinite(corr) & (corr <= slack)))
        corridor_ha = corridor_cells * cell_m * cell_m / 10000.0
        sink, dest = self.parameterAsSink(
            parameters, self.OUT_PATH, context, fields, QgsWkbTypes.Type.LineString, crs)
        out = QgsFeature(fields)
        out.setGeometry(line)
        out.setAttributes([round(best, 6), round(length_m, 3), round(straight, 3),
                           round(best / straight, 6) if straight > 0 else None,
                           len(cells), round(corridor_ha, 6)])
        sink.addFeature(out, QgsFeatureSink.Flag.FastInsert)
        feedback.pushInfo(self.tr(
            f"Least-cost path: cost {best:,.2f} over {length_m:,.1f} ground m "
            f"(straight line {straight:,.1f} m, ratio "
            f"{(best / straight if straight > 0 else math.nan):.3f}). Corridor within "
            f"{slack_pct:g}% of that cost: {corridor_cells} cells, {corridor_ha:,.3f} ha."))
        if best <= 0.0:
            feedback.pushWarning(self.tr(
                "The sources and the targets share a cell, so the least-cost link "
                "between them costs nothing and the corridor is where they touch. "
                "Remove the overlap if the two sets are meant to be separate."))
        unreachable = int(np.sum(np.isfinite(grid) & ~np.isfinite(cost_a)))
        if unreachable:
            feedback.pushWarning(self.tr(
                f"{unreachable} passable cell(s) cannot be reached from the sources - "
                "they sit behind a nodata barrier."))
        feedback.setProgress(100)
        return {self.OUT_COST: cost_path, self.OUT_CORRIDOR: corr_path, self.OUT_PATH: dest}

    def createInstance(self):
        return LeastCostCorridorAlgorithm()
