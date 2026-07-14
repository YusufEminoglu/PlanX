# -*- coding: utf-8 -*-
"""Road Air Quality Screening: emissions dispersion + canyon dispersion grid."""
from __future__ import annotations

import math

import numpy as np

from osgeo import gdal, osr

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
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsSpatialIndex,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_MICRO, PlanXAlgorithm, STRING
from ..engine import air


class AirScreenAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_MICRO
    ICON = "tool_airscreen.png"
    ROADS = "ROADS"
    EMISSION_FIELD = "EMISSION_FIELD"
    WIND_SPEED = "WIND_SPEED"
    ALPHA = "ALPHA"
    BUILDINGS = "BUILDINGS"
    HEIGHT_FIELD = "HEIGHT_FIELD"
    DEFAULT_HEIGHT = "DEFAULT_HEIGHT"
    CANYON_WIDTH = "CANYON_WIDTH"
    CANYON_SEARCH = "CANYON_SEARCH"
    CANYON_BUFFER = "CANYON_BUFFER"
    EXTENT = "EXTENT"
    CELL = "CELL"
    CUTOFF = "CUTOFF"
    RECEIVERS = "RECEIVERS"
    POP_FIELD = "POP_FIELD"
    OUTPUT = "OUTPUT"
    OUT_RECEIVERS = "OUT_RECEIVERS"

    def name(self):
        return "airscreen"

    def displayName(self):
        return self.tr("Air Quality Screening")

    def shortHelpString(self):
        return self.tr(
            "Where is air pollution a screening concern? A SCREENING-quality road "
            "emission dispersion grid - it ranks exposure and locates hotspots; it is NOT "
            "a legal compliance model (no complex chemistry, terrain, or meteorology).\n\n"
            "Model: road segments with emission rates (g/km/day) from the Road Emissions tool "
            "are sampled as line-calibrated point sources. Dispersion follows an alpha-decay "
            "model index ∝ Σ strength / (u * (d + d0)^alpha), where u is wind speed, d is "
            "distance, alpha is the decay parameter, and d0 is half the cell size.\n\n"
            "If buildings are supplied, segments with buildings on both sides are identified "
            "as street canyons. Inside a street-canyon buffer, the concentration is multiplied "
            "by the canyon factor 1 + min(2, H/W), where H is mean building height and W is "
            "street width.\n\n"
            "Outputs the unitless pollution index grid, and - given receiver points with a "
            "population field - each receiver's index plus a population exposure table. "
            "Keep the cutoff moderate (default 300 m). Use a projected CRS.\n\n"
            "How to read the results\n"
            "- The index is RELATIVE, not micrograms: use it to rank "
            "places and compare scenarios, never to check legal limits. "
            "The top decile of cells is your hotspot list.\n"
            "- Canyon-flagged segments deserve first attention: the same "
            "traffic pollutes 2-3x more between continuous walls than on "
            "an open road, so a moderate-traffic canyon can beat a "
            "heavy-traffic open arterial.\n"
            "- The population exposure table turns the map into policy: "
            "people in the top band matter more than peak values on "
            "empty land.\n\n"
            "Using the results: keep schools, kindergartens and clinics "
            "out of top-band cells (or argue setbacks/filtration where "
            "unavoidable); test whether a proposed street wall creates a "
            "new canyon over a busy road before approving it; rank "
            "traffic-calming candidates by exposed population, and "
            "confirm any regulatory question with a compliance model."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.ROADS, self.tr("Roads with emissions (lines)"),
            [QgsProcessing.SourceType.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterField(
            self.EMISSION_FIELD, self.tr("Emission rate field (g/km/day)"),
            "emission", parentLayerParameterName=self.ROADS,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.WIND_SPEED, self.tr("Wind speed (m/s)"),
            QgsProcessingParameterNumber.Type.Double, 2.0, minValue=0.1))
        self.addParameter(QgsProcessingParameterNumber(
            self.ALPHA, self.tr("Decay exponent (alpha)"),
            QgsProcessingParameterNumber.Type.Double, 1.0, minValue=0.1, maxValue=3.0))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.BUILDINGS, self.tr("Buildings for canyon effect (optional)"),
            [QgsProcessing.SourceType.TypeVectorPolygon], optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.HEIGHT_FIELD, self.tr("Building height field (optional)"),
            parentLayerParameterName=self.BUILDINGS, optional=True,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.DEFAULT_HEIGHT, self.tr("Default building height (m)"),
            QgsProcessingParameterNumber.Type.Double, 10.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.CANYON_WIDTH, self.tr("Canyon street width (m)"),
            QgsProcessingParameterNumber.Type.Double, 20.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.CANYON_SEARCH, self.tr("Canyon search distance (m)"),
            QgsProcessingParameterNumber.Type.Double, 30.0, minValue=5.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.CANYON_BUFFER, self.tr("Canyon buffer distance (m)"),
            QgsProcessingParameterNumber.Type.Double, 15.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterExtent(
            self.EXTENT, self.tr("Grid extent (empty = roads extent + cutoff)"),
            optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.CELL, self.tr("Grid cell size (map units)"),
            QgsProcessingParameterNumber.Type.Double, 10.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.CUTOFF, self.tr("Source cutoff distance (map units)"),
            QgsProcessingParameterNumber.Type.Double, 300.0, minValue=25.0))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.RECEIVERS, self.tr("Receiver points (optional, e.g. dwellings)"),
            [QgsProcessing.SourceType.TypeVectorAnyGeometry], optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.POP_FIELD, self.tr("Receiver population field (optional)"),
            parentLayerParameterName=self.RECEIVERS, optional=True,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterRasterDestination(
            self.OUTPUT, self.tr("Air pollution index grid")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_RECEIVERS, self.tr("Receiver index values"), optional=True,
            createByDefault=False))

    def processAlgorithm(self, parameters, context, feedback):
        roads = self.parameterAsSource(parameters, self.ROADS, context)
        em_f = self.parameterAsString(parameters, self.EMISSION_FIELD, context)
        wind_speed = self.parameterAsDouble(parameters, self.WIND_SPEED, context)
        alpha = self.parameterAsDouble(parameters, self.ALPHA, context)
        buildings = self.parameterAsSource(parameters, self.BUILDINGS, context)
        height_f = self.parameterAsString(parameters, self.HEIGHT_FIELD, context)
        height_default = self.parameterAsDouble(parameters, self.DEFAULT_HEIGHT, context)
        canyon_w = self.parameterAsDouble(parameters, self.CANYON_WIDTH, context)
        canyon_search = self.parameterAsDouble(parameters, self.CANYON_SEARCH, context)
        canyon_buffer = self.parameterAsDouble(parameters, self.CANYON_BUFFER, context)
        cell = self.parameterAsDouble(parameters, self.CELL, context)
        cutoff = self.parameterAsDouble(parameters, self.CUTOFF, context)
        receivers = self.parameterAsSource(parameters, self.RECEIVERS, context)
        pop_f = self.parameterAsString(parameters, self.POP_FIELD, context)
        out_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)
        self.require_projected(roads, "Roads")
        crs = roads.sourceCrs()
        extent = self.parameterAsExtent(parameters, self.EXTENT, context, crs)
        if extent is None or extent.isEmpty():
            extent = roads.sourceExtent().buffered(cutoff)

        em_i = roads.fields().lookupField(em_f)
        if em_i < 0:
            raise QgsProcessingException(f"Emission field '{em_f}' was not found.")

        step = max(cell, 5.0)
        d0 = cell / 2.0

        src_pts, src_strengths = [], []
        road_feats = {}
        road_index = QgsSpatialIndex()
        for f in roads.getFeatures():
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
            road_index.insertFeature(f)
            road_feats[f.id()] = f
            attrs = f.attributes()
            try:
                em = float(attrs[em_i])
            except (TypeError, ValueError):
                continue
            if not math.isfinite(em) or em <= 0.0:
                continue
            length = g.length()
            n_seg = max(1, int(round(length / step)))
            seg_len = length / n_seg
            strength = float(air.sample_strength(em, seg_len))
            for k in range(n_seg):
                p = g.interpolate((k + 0.5) * seg_len).asPoint()
                src_pts.append((p.x(), p.y()))
                src_strengths.append(strength)

        if not src_pts:
            raise QgsProcessingException(
                "No road with a positive emission found.")
        src_xy = np.asarray(src_pts)
        src_strength = np.asarray(src_strengths)
        feedback.pushInfo(self.tr(
            f"{len(src_pts)} source samples (every ~{step:g} map units)."))

        bl_index = None
        bl_geoms = []
        bl_heights = []
        if buildings is not None:
            bl_index = QgsSpatialIndex()
            height_i = buildings.fields().lookupField(height_f) if height_f else -1
            for f in buildings.getFeatures():
                g = f.geometry()
                if g is None or g.isEmpty():
                    continue
                h = height_default
                if height_i >= 0:
                    try:
                        h = max(1.0, float(f.attributes()[height_i]))
                    except (TypeError, ValueError):
                        h = height_default
                qf = QgsFeature(len(bl_geoms))
                qf.setGeometry(g)
                bl_index.insertFeature(qf)
                bl_geoms.append(g)
                bl_heights.append(h)

            feedback.pushInfo(self.tr(
                f"Checking canyon effect with {len(bl_geoms)} building(s)."))

        def get_canyon_factor(rx, ry):
            if bl_index is None or not bl_geoms:
                return 1.0
            pt = QgsPointXY(rx, ry)
            nearest_roads = road_index.nearestNeighbor(pt, 1)
            if not nearest_roads:
                return 1.0
            road_feat = road_feats[nearest_roads[0]]
            road_geom = road_feat.geometry()
            dist_to_road = road_geom.distance(QgsGeometry.fromPointXY(pt))
            if dist_to_road > canyon_buffer:
                return 1.0

            np_geom = road_geom.nearestPoint(QgsGeometry.fromPointXY(pt))
            loc = road_geom.lineLocatePoint(np_geom)
            p1 = road_geom.interpolate(max(0.0, loc - 0.1)).asPoint()
            p2 = road_geom.interpolate(min(road_geom.length(), loc + 0.1)).asPoint()
            dx = p2.x() - p1.x()
            dy = p2.y() - p1.y()
            h_val = math.hypot(dx, dy)
            if h_val < 1e-6:
                perp = (0.0, 1.0)
            else:
                perp = (-dy / h_val, dx / h_val)

            l_line = QgsGeometry.fromPolylineXY([
                pt,
                QgsPointXY(rx + canyon_search * perp[0], ry + canyon_search * perp[1])
            ])
            r_line = QgsGeometry.fromPolylineXY([
                pt,
                QgsPointXY(rx - canyon_search * perp[0], ry - canyon_search * perp[1])
            ])

            l_ints = [fid for fid in bl_index.intersects(l_line.boundingBox()) if bl_geoms[fid].intersects(l_line)]
            r_ints = [fid for fid in bl_index.intersects(r_line.boundingBox()) if bl_geoms[fid].intersects(r_line)]

            if l_ints and r_ints:
                h_mean = (np.mean([bl_heights[fid] for fid in l_ints]) + np.mean([bl_heights[fid] for fid in r_ints])) / 2.0
                return float(air.canyon_factor(h_mean, canyon_w))
            return 1.0

        def level_at(rx, ry):
            d = np.hypot(src_xy[:, 0] - rx, src_xy[:, 1] - ry)
            keep = np.where(d <= cutoff)[0]
            if not len(keep):
                return 0.0
            val = air.concentration(
                src_xy[keep], src_strength[keep], rx, ry,
                wind_speed=wind_speed, alpha=alpha, d0=d0)
            return val * get_canyon_factor(rx, ry)

        cols = max(2, int(math.ceil(extent.width() / cell)))
        rows = max(2, int(math.ceil(extent.height() / cell)))
        if rows * cols > 300000:
            raise QgsProcessingException(
                f"{rows * cols} grid cells - enlarge the cell size or "
                "shrink the extent.")
        x0, y1 = extent.xMinimum(), extent.yMaximum()
        grid = np.full((rows, cols), -1.0, dtype=np.float32)
        rxs = x0 + (np.arange(cols) + 0.5) * cell

        for r in range(rows):
            if feedback.isCanceled():
                break
            cy = y1 - (r + 0.5) * cell

            # Broadcast distance calculations for the entire row
            dx = src_xy[:, 0][:, None] - rxs[None, :]
            dy = src_xy[:, 1][:, None] - cy
            d_row = np.hypot(dx, dy)

            for c in range(cols):
                rx = rxs[c]
                d = d_row[:, c]
                keep = np.where(d <= cutoff)[0]
                if not len(keep):
                    lv = 0.0
                else:
                    d_keep = d[keep]
                    contrib = src_strength[keep] / (wind_speed * (d_keep + d0) ** alpha)
                    lv = float(np.sum(contrib))
                cf = get_canyon_factor(rx, cy)
                grid[r, c] = lv * cf
            feedback.setProgress(80.0 * (r + 1) / rows)

        gt = (x0, cell, 0.0, y1, 0.0, -cell)
        srs = osr.SpatialReference()
        srs.ImportFromWkt(crs.toWkt())
        drv = gdal.GetDriverByName("GTiff")
        ds = drv.Create(out_path, cols, rows, 1, gdal.GDT_Float32,
                        options=["COMPRESS=LZW"])
        ds.SetGeoTransform(gt)
        ds.SetProjection(srs.ExportToWkt())
        band = ds.GetRasterBand(1)
        band.SetNoDataValue(-1.0)
        band.WriteArray(grid)
        band.FlushCache()
        ds = None

        results = {self.OUTPUT: out_path}
        valid = grid[grid >= 0]
        if valid.size:
            feedback.pushInfo(self.tr(
                f"Grid levels: mean {float(valid.mean()):.2f}, max "
                f"{float(valid.max()):.2f}."))

        if receivers is not None:
            r_xy, r_feats = self.source_points(
                receivers, crs, context.transformContext())
            pop_i = receivers.fields().lookupField(pop_f) if pop_f else -1
            fields = self.make_fields(
                ("index", DOUBLE), ("band", STRING), base=receivers.fields())
            sink, dest = self.parameterAsSink(
                parameters, self.OUT_RECEIVERS, context, fields,
                QgsWkbTypes.Type.Point, crs)
            if sink is not None:
                levels, pops = [], []
                for i, feat in enumerate(r_feats):
                    if feedback.isCanceled():
                        break
                    lv = level_at(float(r_xy[i, 0]), float(r_xy[i, 1]))
                    levels.append(lv)
                    p = 1.0
                    if pop_i >= 0:
                        try:
                            p = max(0.0, float(feat.attributes()[pop_i]))
                        except (TypeError, ValueError):
                            p = 0.0
                    pops.append(p)
                labels, totals = air.exposure_bands(levels, weights=pops)
                n_base = len(receivers.fields())
                breaks = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
                for i, feat in enumerate(r_feats):
                    band_lab = ""
                    for j in range(len(labels)):
                        lo = -np.inf if j == 0 else breaks[j - 1]
                        hi = np.inf if j == len(labels) - 1 else breaks[j]
                        if lo <= levels[i] < hi:
                            band_lab = labels[j]
                            break
                    out = QgsFeature(fields)
                    out.setGeometry(QgsGeometry.fromPointXY(
                        QgsPointXY(*r_xy[i])))
                    out.setAttributes(list(feat.attributes())[:n_base] + [
                        round(levels[i], 3), band_lab])
                    sink.addFeature(out, QgsFeatureSink.Flag.FastInsert)
                results[self.OUT_RECEIVERS] = dest
                arr = np.asarray(levels)
                w = np.asarray(pops)
                feedback.pushInfo(self.tr(
                    f"Receivers: {float(w[arr >= 20.0].sum()):g} people at "
                    f">= 20 index, {float(w[arr >= 50.0].sum()):g} at >= 50 index "
                    f"(of {float(w.sum()):g})."))
        return results

    def createInstance(self):
        return AirScreenAlgorithm()
