# -*- coding: utf-8 -*-
"""Generate Demo City: deterministic synthetic town generator."""
from __future__ import annotations

import math
import numpy as np

from qgis.core import (
    QgsFeature,
    QgsFeatureSink,
    QgsGeometry,
    QgsPointXY,
    QgsProcessingException,
    QgsProcessingParameterCrs,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_REPORT, INT, LONG, PlanXAlgorithm, STRING
from ._raster import write_raster
from ..engine import demo


class DemoCityAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_REPORT
    ICON = "tool_democity.png"

    SEED = "SEED"
    BLOCKS_X = "BLOCKS_X"
    BLOCKS_Y = "BLOCKS_Y"
    BLOCK_SIZE = "BLOCK_SIZE"
    CRS = "CRS"

    OUTPUT_STREETS = "OUTPUT_STREETS"
    OUTPUT_BUILDINGS = "OUTPUT_BUILDINGS"
    OUTPUT_LANDUSE = "OUTPUT_LANDUSE"
    OUTPUT_POIS = "OUTPUT_POIS"
    OUTPUT_FACILITIES = "OUTPUT_FACILITIES"
    OUTPUT_DEMAND = "OUTPUT_DEMAND"
    OUTPUT_GREEN = "OUTPUT_GREEN"
    OUTPUT_DSM = "OUTPUT_DSM"

    def name(self):
        return "democity"

    def displayName(self):
        return self.tr("Generate Demo City")

    def shortHelpString(self):
        return self.tr(
            "Generates a deterministic synthetic city for testing and demonstration. "
            "Creates a grid of street blocks with a diagonal avenue, building footprints "
            "with random heights, land-use zones, POIs, facilities, demand points with "
            "population, green spaces, and a corresponding DSM raster.\n\n"
            "This tool provides a complete, clean set of spatial layers that are perfectly "
            "compatible with all other PlanX tools, allowing you to try out space syntax, "
            "network centrality, walkability, shadow casting, and access tools in one click.\n\n"
            "Outputs: street network lines, building footprints (with height), land-use polygons "
            "(residential, commercial, green, school), POI points, facilities (with name and capacity), "
            "demand points (with population), green polygons, and a DSM raster.\n\n"
            "How to read the results\n"
            "- Nothing here is real: the town exists so every other tool "
            "has clean, compatible inputs on the first click. Use it to "
            "LEARN a tool's outputs on a city small enough to check by "
            "eye, before trusting it on real data.\n"
            "- The same seed always regenerates the identical town - "
            "handy for reproducible tutorials, bug reports and "
            "documentation figures; change the seed for a different "
            "layout, the size parameters for a bigger test.\n\n"
            "Using the results: the quickstart pair is streets -> Space "
            "Syntax (radii '800, n') and facilities -> Service Areas; "
            "the DSM feeds the Microclimate tools, demand + facilities "
            "feed Adequacy and the Batch Plan Auditor. When a tool "
            "misbehaves on your data but works on the demo city, the "
            "difference (CRS, noding, field types) is the diagnosis."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterNumber(
            self.SEED, self.tr("Random seed"),
            QgsProcessingParameterNumber.Integer, 42, minValue=0))
        self.addParameter(QgsProcessingParameterNumber(
            self.BLOCKS_X, self.tr("Number of blocks in X direction"),
            QgsProcessingParameterNumber.Integer, 4, minValue=1))
        self.addParameter(QgsProcessingParameterNumber(
            self.BLOCKS_Y, self.tr("Number of blocks in Y direction"),
            QgsProcessingParameterNumber.Integer, 4, minValue=1))
        self.addParameter(QgsProcessingParameterNumber(
            self.BLOCK_SIZE, self.tr("Block size (meters)"),
            QgsProcessingParameterNumber.Double, 100.0, minValue=10.0))
        self.addParameter(QgsProcessingParameterCrs(
            self.CRS, self.tr("Projected target CRS"),
            defaultValue="EPSG:3857"))

        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT_STREETS, self.tr("Streets network")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT_BUILDINGS, self.tr("Buildings footprints")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT_LANDUSE, self.tr("Land-use zones")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT_POIS, self.tr("Points of interest (POIs)")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT_FACILITIES, self.tr("Facilities")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT_DEMAND, self.tr("Demand points")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT_GREEN, self.tr("Green spaces")))
        self.addParameter(QgsProcessingParameterRasterDestination(
            self.OUTPUT_DSM, self.tr("Digital surface model (DSM)")))

    def processAlgorithm(self, parameters, context, feedback):
        seed = self.parameterAsInt(parameters, self.SEED, context)
        blocks_x = self.parameterAsInt(parameters, self.BLOCKS_X, context)
        blocks_y = self.parameterAsInt(parameters, self.BLOCKS_Y, context)
        block_size = self.parameterAsDouble(parameters, self.BLOCK_SIZE, context)
        crs = self.parameterAsCrs(parameters, self.CRS, context)

        if crs.isValid() and crs.isGeographic():
            raise QgsProcessingException(
                self.tr("The target CRS must be a projected coordinate system (metric).")
            )

        pixel_size = 2.0
        feedback.pushInfo(self.tr("Generating synthetic city data..."))
        res = demo.generate_demo_city(seed, blocks_x, blocks_y, block_size, pixel_size=pixel_size)

        # 1. Streets
        streets_fields = self.make_fields(("seg_id", LONG), ("length_m", DOUBLE))
        streets_sink, streets_dest = self.parameterAsSink(
            parameters, self.OUTPUT_STREETS, context, streets_fields,
            QgsWkbTypes.LineString, crs)
        if streets_sink is not None:
            for idx, street in enumerate(res["streets"]):
                feat = QgsFeature(streets_fields)
                pts = [QgsPointXY(float(p[0]), float(p[1])) for p in street]
                feat.setGeometry(QgsGeometry.fromPolylineXY(pts))
                length = math.hypot(street[1][0] - street[0][0], street[1][1] - street[0][1])
                feat.setAttributes([idx, float(length)])
                streets_sink.addFeature(feat, QgsFeatureSink.FastInsert)

        # 2. Buildings
        buildings_fields = self.make_fields(("height", DOUBLE))
        buildings_sink, buildings_dest = self.parameterAsSink(
            parameters, self.OUTPUT_BUILDINGS, context, buildings_fields,
            QgsWkbTypes.Polygon, crs)
        if buildings_sink is not None:
            for poly, height in res["buildings"]:
                feat = QgsFeature(buildings_fields)
                pts = [QgsPointXY(float(p[0]), float(p[1])) for p in poly]
                feat.setGeometry(QgsGeometry.fromPolygonXY([pts]))
                feat.setAttributes([float(height)])
                buildings_sink.addFeature(feat, QgsFeatureSink.FastInsert)

        # 3. Land use
        landuse_fields = self.make_fields(("use", STRING))
        landuse_sink, landuse_dest = self.parameterAsSink(
            parameters, self.OUTPUT_LANDUSE, context, landuse_fields,
            QgsWkbTypes.Polygon, crs)
        if landuse_sink is not None:
            for poly, use in res["landuse"]:
                feat = QgsFeature(landuse_fields)
                pts = [QgsPointXY(float(p[0]), float(p[1])) for p in poly]
                feat.setGeometry(QgsGeometry.fromPolygonXY([pts]))
                feat.setAttributes([use])
                landuse_sink.addFeature(feat, QgsFeatureSink.FastInsert)

        # 4. POIs
        pois_fields = self.make_fields(("type", STRING))
        pois_sink, pois_dest = self.parameterAsSink(
            parameters, self.OUTPUT_POIS, context, pois_fields,
            QgsWkbTypes.Point, crs)
        if pois_sink is not None:
            for (px, py), ptype in res["pois"]:
                feat = QgsFeature(pois_fields)
                feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(px, py)))
                feat.setAttributes([ptype])
                pois_sink.addFeature(feat, QgsFeatureSink.FastInsert)

        # 5. Facilities
        facilities_fields = self.make_fields(("name", STRING), ("cap", INT))
        facilities_sink, facilities_dest = self.parameterAsSink(
            parameters, self.OUTPUT_FACILITIES, context, facilities_fields,
            QgsWkbTypes.Point, crs)
        if facilities_sink is not None:
            for (fx, fy), name, cap in res["facilities"]:
                feat = QgsFeature(facilities_fields)
                feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(fx, fy)))
                feat.setAttributes([name, int(cap)])
                facilities_sink.addFeature(feat, QgsFeatureSink.FastInsert)

        # 6. Demand points
        demand_fields = self.make_fields(("pop", INT))
        demand_sink, demand_dest = self.parameterAsSink(
            parameters, self.OUTPUT_DEMAND, context, demand_fields,
            QgsWkbTypes.Point, crs)
        if demand_sink is not None:
            for (dx, dy), pop in res["demand"]:
                feat = QgsFeature(demand_fields)
                feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(dx, dy)))
                feat.setAttributes([int(pop)])
                demand_sink.addFeature(feat, QgsFeatureSink.FastInsert)

        # 7. Green spaces
        green_fields = self.make_fields(("park_id", INT))
        green_sink, green_dest = self.parameterAsSink(
            parameters, self.OUTPUT_GREEN, context, green_fields,
            QgsWkbTypes.Polygon, crs)
        if green_sink is not None:
            for idx, poly in enumerate(res["green"]):
                feat = QgsFeature(green_fields)
                pts = [QgsPointXY(float(p[0]), float(p[1])) for p in poly]
                feat.setGeometry(QgsGeometry.fromPolygonXY([pts]))
                feat.setAttributes([idx])
                green_sink.addFeature(feat, QgsFeatureSink.FastInsert)

        # 8. DSM Raster
        dsm_path = self.parameterAsOutputLayer(parameters, self.OUTPUT_DSM, context)
        H = blocks_y * block_size
        gt = (0.0, pixel_size, 0.0, float(H), 0.0, -pixel_size)
        write_raster(dsm_path, res["dsm"].astype(np.float32), gt, crs.toWkt(), nodata=-1.0)

        feedback.pushInfo(self.tr("Demo City layers generated successfully!"))

        return {
            self.OUTPUT_STREETS: streets_dest,
            self.OUTPUT_BUILDINGS: buildings_dest,
            self.OUTPUT_LANDUSE: landuse_dest,
            self.OUTPUT_POIS: pois_dest,
            self.OUTPUT_FACILITIES: facilities_dest,
            self.OUTPUT_DEMAND: demand_dest,
            self.OUTPUT_GREEN: green_dest,
            self.OUTPUT_DSM: dsm_path,
        }

    def createInstance(self):
        return DemoCityAlgorithm()
