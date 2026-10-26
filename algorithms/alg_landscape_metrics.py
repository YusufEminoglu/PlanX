# -*- coding: utf-8 -*-
"""Landscape Metrics: FRAGSTATS class- and landscape-level pattern metrics."""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsFeature,
    QgsFeatureSink,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterRasterLayer,
    QgsWkbTypes,
)

from . import _units
from ._raster import read_dsm, write_raster
from .base import DOUBLE, GROUP_GREEN, INT, PlanXAlgorithm, STRING
from ..engine import landscape


def _r(value, digits=6):
    return None if value is None else round(float(value), digits)


class LandscapeMetricsAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_GREEN
    ICON = "tool_landscapemetrics.png"

    LANDCOVER = "LANDCOVER"
    RULE = "RULE"
    EDGE_DEPTH = "EDGE_DEPTH"
    OUT_CLASS = "OUT_CLASS"
    OUT_LANDSCAPE = "OUT_LANDSCAPE"
    OUT_PATCHES = "OUT_PATCHES"

    RULES = ["8-neighbour (FRAGSTATS default)", "4-neighbour"]

    def name(self):
        return "landscapemetrics"

    def displayName(self):
        return self.tr("Landscape Metrics (FRAGSTATS)")

    def shortHelpString(self):
        return self.tr(
            "Pattern metrics of a categorical raster - land cover, habitat, "
            "green/grey - in FRAGSTATS's vocabulary, so the numbers can be "
            "compared with the landscape-ecology literature.\n\n"
            "Per class: class area CA (ha), share of landscape PLAND, number "
            "of patches NP, patch density PD (per 100 ha), largest patch index "
            "LPI, total edge TE and edge density ED, mean patch area, mean "
            "shape index (1 = square), total core area TCA and core-area "
            "share CPLAND at the edge depth you set, and the aggregation index "
            "AI (He et al. 2000). Landscape level: the same area, density and "
            "edge totals plus patch richness PR, Shannon diversity SHDI and "
            "evenness SHEI, Simpson's SIDI, contagion CONTAG and the area-"
            "weighted AI. Optional raster of patch ids.\n\n"
            "Conventions, stated: patches use the 8-neighbour rule unless you "
            "choose 4; only edges between two valid cells of different "
            "classes count as edge (the landscape boundary and nodata do not); "
            "areas and lengths are ground metres, converted from the raster's "
            "CRS once; nodata cells are outside the landscape.\n\n"
            "How to read the results\n"
            "- PLAND says how much; NP, PD, LPI and AREA_MN say how it is "
            "broken up. A class losing LPI while PLAND holds is fragmenting.\n"
            "- AI near 100 = the class is as clumped as its area allows; low "
            "AI = scattered. CONTAG is the landscape-wide version: high = a few "
            "large uniform blocks, low = a fine-grained mosaic.\n"
            "- CPLAND against PLAND is the edge effect: a habitat that is 30 "
            "percent of the landscape but 5 percent core is mostly edge.\n"
            "- Every metric depends on grain (cell size) and extent; compare "
            "two landscapes only at the same resolution and extent.\n\n"
            "Using the results: compute before and after a development "
            "scenario (Urban Growth's CA output or two land-cover years) and "
            "report the change in LPI, ED, CPLAND and AI for the green "
            "classes; pair it with Green Connectivity, which measures links "
            "between patches rather than their shape."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.LANDCOVER, self.tr("Categorical raster (land cover classes)")))
        self.addParameter(QgsProcessingParameterEnum(
            self.RULE, self.tr("Patch neighbour rule"), self.RULES, defaultValue=0))
        self.addParameter(QgsProcessingParameterNumber(
            self.EDGE_DEPTH, self.tr("Edge depth for core area (metres)"),
            QgsProcessingParameterNumber.Type.Double, 30.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_CLASS, self.tr("Class metrics"), type=QgsProcessing.SourceType.TypeVector))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_LANDSCAPE, self.tr("Landscape metrics"), type=QgsProcessing.SourceType.TypeVector))
        self.addParameter(QgsProcessingParameterRasterDestination(
            self.OUT_PATCHES, self.tr("Patch ids"), optional=True, createByDefault=False))

    def processAlgorithm(self, parameters, context, feedback):
        layer = self.parameterAsRasterLayer(parameters, self.LANDCOVER, context)
        rule = 8 if self.parameterAsEnum(parameters, self.RULE, context) == 0 else 4
        depth = self.parameterAsDouble(parameters, self.EDGE_DEPTH, context)
        grid, gt, proj, pixel = read_dsm(layer)
        if abs(abs(gt[1]) - abs(gt[5])) > 0.01 * max(abs(gt[1]), abs(gt[5])):
            feedback.pushWarning(self.tr(
                f"Cells are not square ({abs(gt[1]):g} x {abs(gt[5]):g}); their mean side "
                "is used for every length and area."))
        valid = np.isfinite(grid)
        if not valid.any():
            raise QgsProcessingException("The raster has no valid cell.")
        values = grid[valid]
        if not np.all(values == np.round(values)):
            raise QgsProcessingException(
                "The raster holds non-integer values - landscape metrics need a "
                "categorical raster (one integer per class). Reclassify it first.")
        classes = np.where(valid, grid, 0).astype(np.int64)
        per_unit = _units.GroundUnits(layer.crs(), context.transformContext()).scale(layer.extent())
        cell_m = pixel / per_unit
        n_classes = len(np.unique(classes[valid]))
        feedback.pushInfo(self.tr(
            f"{int(valid.sum()):,} valid cells of {cell_m:.3f} ground m, {n_classes} classes, "
            f"{rule}-neighbour rule, edge depth {depth:g} m."))
        if n_classes > 255:
            raise QgsProcessingException(
                f"{n_classes} classes - this is not a categorical raster.")
        try:
            rows, land, patches = landscape.metrics(classes, valid, cell_m, rule, depth)
        except ValueError as exc:
            raise QgsProcessingException(str(exc))
        feedback.setProgress(80)

        crs = layer.crs()
        cfields = self.make_fields(
            ("class", INT), ("CA_ha", DOUBLE), ("PLAND", DOUBLE), ("NP", INT),
            ("PD", DOUBLE), ("LPI", DOUBLE), ("TE_m", DOUBLE), ("ED", DOUBLE),
            ("AREA_MN", DOUBLE), ("SHAPE_MN", DOUBLE), ("TCA_ha", DOUBLE),
            ("CPLAND", DOUBLE), ("AI", DOUBLE))
        csink, cdest = self.parameterAsSink(
            parameters, self.OUT_CLASS, context, cfields, QgsWkbTypes.Type.NoGeometry, crs)
        for row in rows:
            f = QgsFeature(cfields)
            f.setAttributes([int(row["class"]), _r(row["CA"]), _r(row["PLAND"]), int(row["NP"]),
                             _r(row["PD"]), _r(row["LPI"]), _r(row["TE"], 3), _r(row["ED"]),
                             _r(row["AREA_MN"]), _r(row["SHAPE_MN"]), _r(row["TCA"]),
                             _r(row["CPLAND"]), _r(row["AI"])])
            csink.addFeature(f, QgsFeatureSink.Flag.FastInsert)

        units = {"TA": "ha", "NP": "count", "PD": "per 100 ha", "LPI": "percent",
                 "TE": "m", "ED": "m per ha", "PR": "count", "SHDI": "nats",
                 "SHEI": "0-1", "SIDI": "0-1", "CONTAG": "percent", "AI": "percent",
                 "TCA": "ha"}
        lfields = self.make_fields(("metric", STRING), ("value", DOUBLE), ("unit", STRING))
        lsink, ldest = self.parameterAsSink(
            parameters, self.OUT_LANDSCAPE, context, lfields, QgsWkbTypes.Type.NoGeometry, crs)
        for key, value in land.items():
            f = QgsFeature(lfields)
            f.setAttributes([key, _r(value), units.get(key, "")])
            lsink.addFeature(f, QgsFeatureSink.Flag.FastInsert)
            feedback.pushInfo(f"  {key}: {'undefined' if value is None else f'{value:.6g}'}")

        results = {self.OUT_CLASS: cdest, self.OUT_LANDSCAPE: ldest}
        out_path = self.parameterAsOutputLayer(parameters, self.OUT_PATCHES, context)
        if out_path and parameters.get(self.OUT_PATCHES) is not None:
            from osgeo import gdal
            write_raster(out_path, patches["labels"].astype(np.int32), gt, proj, -1,
                         dtype=gdal.GDT_Int32)
            results[self.OUT_PATCHES] = out_path
        feedback.setProgress(100)
        return results

    def createInstance(self):
        return LandscapeMetricsAlgorithm()
