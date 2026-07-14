# -*- coding: utf-8 -*-
"""Road Noise Screening: RLS-90-style emission + geometric spreading grid."""
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
from ..engine import noise


class NoiseScreenAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_MICRO
    ICON = "tool_noisescreen.png"
    ROADS = "ROADS"
    VOLUME_FIELD = "VOLUME_FIELD"
    HOURLY_FACTOR = "HOURLY_FACTOR"
    HEAVY_FIELD = "HEAVY_FIELD"
    HEAVY_PCT = "HEAVY_PCT"
    BUILDINGS = "BUILDINGS"
    SCREEN_DB = "SCREEN_DB"
    EXTENT = "EXTENT"
    CELL = "CELL"
    CUTOFF = "CUTOFF"
    RECEIVERS = "RECEIVERS"
    POP_FIELD = "POP_FIELD"
    OUTPUT = "OUTPUT"
    OUT_RECEIVERS = "OUT_RECEIVERS"

    def name(self):
        return "noisescreen"

    def displayName(self):
        return self.tr("Road Noise Screening")

    def shortHelpString(self):
        return self.tr(
            "Where is traffic noise a problem? A SCREENING-quality road "
            "noise grid - it ranks exposure and finds hotspots; it is NOT "
            "a legal noise map (no ground effect, no meteorology, no "
            "reflections - use a licensed engine for compliance).\n\n"
            "Model: each road segment emits at the RLS-90-style mean "
            "level 37.3 + 10 lg(M (1 + 0.082 p)) dB(A) at the 25 m "
            "reference, with M the hourly volume (multiply your field by "
            "the hourly factor, e.g. 1/24 for AADT) and p the heavy-"
            "vehicle share in percent. Roads are sampled as point sources "
            "calibrated to reproduce the line level; the receiver level is "
            "the energetic sum with 20 lg r spreading, and paths blocked "
            "by a building lose a fixed insertion loss (default 10 dB).\n\n"
            "Outputs the dB(A) grid, and - given receiver points with a "
            "population field - each receiver's level plus a population "
            "exposure table by 5 dB bands (the classic 55/65 dB counts in "
            "the log).\n\n"
            "Keep the cutoff moderate (default 300 m): distant roads "
            "rarely dominate a screening and cost most of the runtime. "
            "Use a projected CRS.\n\n"
            "How to read the results\n"
            "- Anchor on the two classic thresholds: 55 dB(A) is where "
            "annoyance and sleep disturbance start in most guidance; "
            "65 dB(A) is seriously noisy - residential facades above it "
            "need mitigation. The log's population counts at these bands "
            "are the headline exposure numbers.\n"
            "- dB is logarithmic: +3 dB = twice the sound energy, +10 dB "
            "is perceived as roughly twice as loud. A 5 dB improvement "
            "from a measure is substantial, not marginal.\n"
            "- The quiet side of screening buildings (the fixed insertion "
            "loss) shows the value of perimeter blocks: courtyard levels "
            "10 dB below the street mean the same flat sleeps well or "
            "badly depending on which side its bedroom faces.\n\n"
            "Using the results: locate noise-sensitive uses (housing, "
            "schools, hospitals) in cells under 55; where housing must "
            "face a loud road, argue closed street walls and courtyard "
            "layouts with the before/after grid; rank road segments by "
            "exposed population to prioritise speed reduction or "
            "resurfacing - then confirm any legal question with a "
            "compliant engine."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.ROADS, self.tr("Roads (lines)"),
            [QgsProcessing.SourceType.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterField(
            self.VOLUME_FIELD, self.tr("Traffic volume field"),
            parentLayerParameterName=self.ROADS,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.HOURLY_FACTOR,
            self.tr("Hourly factor (multiply the volume field, 1/24 for AADT)"),
            QgsProcessingParameterNumber.Type.Double, 1.0, minValue=0.0001,
            maxValue=10.0))
        self.addParameter(QgsProcessingParameterField(
            self.HEAVY_FIELD,
            self.tr("Heavy-vehicle share field (percent, optional)"),
            parentLayerParameterName=self.ROADS, optional=True,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.HEAVY_PCT, self.tr("Default heavy share (percent)"),
            QgsProcessingParameterNumber.Type.Double, 5.0, minValue=0.0,
            maxValue=100.0))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.BUILDINGS, self.tr("Buildings for screening (optional)"),
            [QgsProcessing.SourceType.TypeVectorPolygon], optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.SCREEN_DB, self.tr("Insertion loss behind buildings (dB)"),
            QgsProcessingParameterNumber.Type.Double, 10.0, minValue=0.0,
            maxValue=30.0))
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
            self.OUTPUT, self.tr("Noise level grid dB(A)")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_RECEIVERS, self.tr("Receiver levels"), optional=True,
            createByDefault=False))

    def processAlgorithm(self, parameters, context, feedback):
        roads = self.parameterAsSource(parameters, self.ROADS, context)
        vol_f = self.parameterAsString(parameters, self.VOLUME_FIELD, context)
        hourly = self.parameterAsDouble(parameters, self.HOURLY_FACTOR, context)
        heavy_f = self.parameterAsString(parameters, self.HEAVY_FIELD, context)
        heavy_default = self.parameterAsDouble(parameters, self.HEAVY_PCT, context)
        buildings = self.parameterAsSource(parameters, self.BUILDINGS, context)
        screen_db = self.parameterAsDouble(parameters, self.SCREEN_DB, context)
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

        vol_i = roads.fields().lookupField(vol_f)
        heavy_i = roads.fields().lookupField(heavy_f) if heavy_f else -1
        step = max(cell, 5.0)

        src_pts, src_lvls = [], []
        for f in roads.getFeatures():
            if feedback.isCanceled():
                break
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
            attrs = f.attributes()
            try:
                m = float(attrs[vol_i]) * hourly
            except (TypeError, ValueError):
                continue
            heavy = heavy_default
            if heavy_i >= 0:
                try:
                    heavy = float(attrs[heavy_i])
                except (TypeError, ValueError):
                    heavy = heavy_default
            lm25 = float(noise.emission_rls(m, heavy))
            if not math.isfinite(lm25):
                continue
            length = g.length()
            n_seg = max(1, int(round(length / step)))
            seg_len = length / n_seg
            lvl = float(noise.sample_level(lm25, seg_len))
            for k in range(n_seg):
                p = g.interpolate((k + 0.5) * seg_len).asPoint()
                src_pts.append((p.x(), p.y()))
                src_lvls.append(lvl)
        if not src_pts:
            raise QgsProcessingException(
                "No road with a usable traffic volume found.")
        src_xy = np.asarray(src_pts)
        src_lvl = np.asarray(src_lvls)
        feedback.pushInfo(self.tr(
            f"{len(src_pts)} road samples (every ~{step:g} map units)."))

        bl_geoms, bl_index = [], None
        if buildings is not None:
            bl_index = QgsSpatialIndex()
            for f in buildings.getFeatures():
                g = f.geometry()
                if g is None or g.isEmpty():
                    continue
                qf = QgsFeature(len(bl_geoms))
                qf.setGeometry(g)
                bl_index.insertFeature(qf)
                bl_geoms.append(g)
            feedback.pushInfo(self.tr(
                f"Screening against {len(bl_geoms)} building(s), "
                f"insertion loss {screen_db:g} dB."))

        def blocked_mask(rx, ry, keep_idx):
            if bl_index is None or not len(keep_idx):
                return None
            out = np.zeros(len(keep_idx), dtype=bool)
            for n_pos, si in enumerate(keep_idx):
                sight = QgsGeometry.fromPolylineXY(
                    [QgsPointXY(float(src_xy[si, 0]), float(src_xy[si, 1])),
                     QgsPointXY(rx, ry)])
                for fid in bl_index.intersects(sight.boundingBox()):
                    if bl_geoms[fid].intersects(sight):
                        out[n_pos] = True
                        break
            return out

        def level_at(rx, ry):
            d = np.hypot(src_xy[:, 0] - rx, src_xy[:, 1] - ry)
            keep = np.where(d <= cutoff)[0]
            if not len(keep):
                return -np.inf
            return noise.receiver_level(
                src_xy[keep], src_lvl[keep], rx, ry,
                blocked=blocked_mask(rx, ry, keep), screen_db=screen_db,
                min_dist=max(1.0, cell / 2.0))

        cols = max(2, int(math.ceil(extent.width() / cell)))
        rows = max(2, int(math.ceil(extent.height() / cell)))
        if rows * cols > 300000:
            raise QgsProcessingException(
                f"{rows * cols} grid cells - enlarge the cell size or "
                "shrink the extent.")
        x0, y1 = extent.xMinimum(), extent.yMaximum()
        grid = np.full((rows, cols), -1.0, dtype=np.float32)
        rxs = x0 + (np.arange(cols) + 0.5) * cell
        min_dist = max(1.0, cell / 2.0)
        for r in range(rows):
            if feedback.isCanceled():
                break
            cy = y1 - (r + 0.5) * cell

            # Broadcast distance calculations for the entire row at once
            dx = src_xy[:, 0][:, None] - rxs[None, :]
            dy = src_xy[:, 1][:, None] - cy
            d_row = np.hypot(dx, dy)

            for c in range(cols):
                rx = rxs[c]
                d = d_row[:, c]
                keep = np.where(d <= cutoff)[0]
                if not len(keep):
                    lv = -np.inf
                else:
                    d_keep = np.maximum(d[keep], min_dist)
                    contrib = src_lvl[keep] - 20.0 * np.log10(d_keep)
                    blocked = blocked_mask(rx, cy, keep)
                    if blocked is not None:
                        contrib = contrib - np.where(blocked, float(screen_db), 0.0)
                    lv = float(10.0 * np.log10(np.sum(10.0 ** (contrib / 10.0))))
                grid[r, c] = lv if math.isfinite(lv) else -1.0
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
                f"Grid levels: mean {float(valid.mean()):.1f}, max "
                f"{float(valid.max()):.1f} dB(A)."))

        if receivers is not None:
            r_xy, r_feats = self.source_points(
                receivers, crs, context.transformContext())
            pop_i = receivers.fields().lookupField(pop_f) if pop_f else -1
            fields = self.make_fields(
                ("db", DOUBLE), ("band", STRING), base=receivers.fields())
            sink, dest = self.parameterAsSink(
                parameters, self.OUT_RECEIVERS, context, fields,
                QgsWkbTypes.Type.Point, crs)
            if sink is not None:
                levels, pops = [], []
                for i, feat in enumerate(r_feats):
                    if feedback.isCanceled():
                        break
                    lv = level_at(float(r_xy[i, 0]), float(r_xy[i, 1]))
                    levels.append(lv if math.isfinite(lv) else -1.0)
                    p = 1.0
                    if pop_i >= 0:
                        try:
                            p = max(0.0, float(feat.attributes()[pop_i]))
                        except (TypeError, ValueError):
                            p = 0.0
                    pops.append(p)
                labels, totals = noise.exposure_bands(levels, weights=pops)
                n_base = len(receivers.fields())
                for i, feat in enumerate(r_feats):
                    band_lab = ""
                    for j in range(len(labels)):
                        lo = -np.inf if j == 0 else 45.0 + 5.0 * (j - 1)
                        hi = np.inf if j == len(labels) - 1 else 45.0 + 5.0 * j
                        if lo <= levels[i] < hi:
                            band_lab = labels[j]
                            break
                    out = QgsFeature(fields)
                    out.setGeometry(QgsGeometry.fromPointXY(
                        QgsPointXY(*r_xy[i])))
                    out.setAttributes(list(feat.attributes())[:n_base] + [
                        round(levels[i], 1), band_lab])
                    sink.addFeature(out, QgsFeatureSink.Flag.FastInsert)
                results[self.OUT_RECEIVERS] = dest
                arr = np.asarray(levels)
                w = np.asarray(pops)
                feedback.pushInfo(self.tr(
                    f"Receivers: {float(w[arr >= 55.0].sum()):g} people at "
                    f">= 55 dB, {float(w[arr >= 65.0].sum()):g} at >= 65 dB "
                    f"(of {float(w.sum()):g})."))
        return results

    def createInstance(self):
        return NoiseScreenAlgorithm()
