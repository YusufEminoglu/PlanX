# -*- coding: utf-8 -*-
"""Street Environment Comfort: segment-level walk comfort scoring from assets, barriers, and rasters."""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsFeature,
    QgsFeatureSink,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterMultipleLayers,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterEnum,
    QgsProcessingParameterString,
    QgsSpatialIndex,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_WALK, INT, PlanXAlgorithm
from ..engine import comfort


class StreetComfortAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_WALK
    ICON = "tool_streetcomfort.png"
    NETWORK = "NETWORK"
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    WEIGHT_FIELD = "WEIGHT_FIELD"
    RASTER_PLUS = "RASTER_PLUS"
    RASTER_MINUS = "RASTER_MINUS"
    BANDWIDTH = "BANDWIDTH"
    KERNEL = "KERNEL"
    SAMPLE_STEP = "SAMPLE_STEP"
    WEIGHTS = "WEIGHTS"
    OUTPUT = "OUTPUT"

    def name(self):
        return "streetcomfort"

    def displayName(self):
        return self.tr("Street Environment Comfort")

    def shortHelpString(self):
        return self.tr(
            "Scores street segments 0–100 by aggregating kernel densities of comfort "
            "assets (trees, benches, lights) and barriers (potholes, blank walls) "
            "plus optional raster factors (sunlight, heat, noise).\n\n"
            "Kernel weights use u = d/h against the bandwidth h: uniform 1, "
            "triangular 1 − u, Epanechnikov 1 − u², Gaussian e^(−4.5·u²), all zero "
            "beyond h. The calculation combines min-max normalized components into a "
            "weighted comfort index: index = 100 · Σ w·oriented_norm / Σ w. Midpoint "
            "sampling offsets avoid double-counting at shared junctions.\n\n"
            "Kernel bandwidth defines the perception radius (e.g. 50 m ≈ typical block scale).\n\n"
            "How to read the results\n"
            "- comfort score (0-100) is relative, calibrated to the minimum and maximum "
            "conditions within this analyzed network.\n"
            "- pos_den and neg_den are raw density values. A low comfort score with a high "
            "neg_den flags obstacle problems, while a low pos_den signals asset gaps.\n"
            "- Segment sample spacing determines resolution; very short segments "
            "get a single midpoint sample.\n\n"
            "Using the results\n"
            "- Target sidewalk improvements or tree planting on segments with high "
            "pedestrian flow (from OD matrix bundles) and low comfort scores.\n"
            "- Feed comfort scores directly into the Pedestrian Route Quality tool as "
            "the custom score field for comfort-aware routing."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("Street network (lines)"),
            [QgsProcessing.SourceType.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterMultipleLayers(
            self.POSITIVE, self.tr("Comfort assets (point layers: trees, lamps, benches...)"),
            QgsProcessing.SourceType.TypeVectorPoint, optional=True))
        self.addParameter(QgsProcessingParameterMultipleLayers(
            self.NEGATIVE, self.tr("Comfort barriers (point layers: obstacles, potholes...)"),
            QgsProcessing.SourceType.TypeVectorPoint, optional=True))
        self.addParameter(QgsProcessingParameterString(
            self.WEIGHT_FIELD,
            self.tr("Per-feature weight field name (used when a layer has it; empty or missing field = weight 1)"),
            defaultValue="", optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.RASTER_PLUS, self.tr("Raster raising comfort (e.g. winter sun hours)"),
            optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.RASTER_MINUS, self.tr("Raster lowering comfort (e.g. heat risk, noise)"),
            optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.BANDWIDTH, self.tr("Kernel bandwidth (m)"),
            QgsProcessingParameterNumber.Type.Double, 50.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterEnum(
            self.KERNEL, self.tr("Kernel shape"),
            ["Uniform", "Triangular", "Epanechnikov", "Gaussian"],
            defaultValue=2))
        self.addParameter(QgsProcessingParameterNumber(
            self.SAMPLE_STEP, self.tr("Segment sample spacing (m)"),
            QgsProcessingParameterNumber.Type.Double, 10.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterString(
            self.WEIGHTS, self.tr("Component weights 'positive=1, negative=1, raster_plus=1, raster_minus=1' (empty = equal)"),
            defaultValue="", optional=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Comfort-scored segments")))

    def processAlgorithm(self, parameters, context, feedback):
        network = self.parameterAsSource(parameters, self.NETWORK, context)
        pos_layers = self.parameterAsLayerList(parameters, self.POSITIVE, context) or []
        neg_layers = self.parameterAsLayerList(parameters, self.NEGATIVE, context) or []
        weight_field = self.parameterAsString(parameters, self.WEIGHT_FIELD, context)
        raster_plus = self.parameterAsRasterLayer(parameters, self.RASTER_PLUS, context)
        raster_minus = self.parameterAsRasterLayer(parameters, self.RASTER_MINUS, context)
        bandwidth = self.parameterAsDouble(parameters, self.BANDWIDTH, context)
        kernel_enum = self.parameterAsEnum(parameters, self.KERNEL, context)
        step = self.parameterAsDouble(parameters, self.SAMPLE_STEP, context)
        weights_str = self.parameterAsString(parameters, self.WEIGHTS, context)
        self.require_projected(network, "Street network")

        has_pos = len(pos_layers) > 0
        has_neg = len(neg_layers) > 0
        has_rplus = raster_plus is not None
        has_rminus = raster_minus is not None

        if not has_pos and not has_neg and not has_rplus and not has_rminus:
            raise QgsProcessingException("provide at least one comfort component")

        # Parse component weights
        allowed_keys = {"positive", "negative", "raster_plus", "raster_minus"}
        parsed_weights = {}
        if weights_str:
            tokens = weights_str.replace(";", ",").split(",")
            for token in tokens:
                token = token.strip()
                if not token:
                    continue
                if "=" not in token:
                    raise QgsProcessingException(self.tr(f"Invalid weight format: '{token}'"))
                key, _, val = token.partition("=")
                key = key.strip().lower()
                if key not in allowed_keys:
                    raise QgsProcessingException(self.tr(
                        f"Unknown component weight: '{key}'. "
                        "Allowed: positive, negative, raster_plus, raster_minus"))
                try:
                    value = float(val.strip())
                except ValueError:
                    raise QgsProcessingException(self.tr(f"Weight value for '{key}' is not numeric: '{val}'"))
                if value <= 0:
                    raise QgsProcessingException(self.tr(f"Weight value for '{key}' must be greater than 0, got {value}"))
                parsed_weights[key] = value

        # Validate weights of absent components
        for key in list(parsed_weights.keys()):
            if key == "positive" and not has_pos:
                feedback.pushWarning(self.tr(f"Weight for absent component '{key}' ignored."))
                parsed_weights.pop(key)
            elif key == "negative" and not has_neg:
                feedback.pushWarning(self.tr(f"Weight for absent component '{key}' ignored."))
                parsed_weights.pop(key)
            elif key == "raster_plus" and not has_rplus:
                feedback.pushWarning(self.tr(f"Weight for absent component '{key}' ignored."))
                parsed_weights.pop(key)
            elif key == "raster_minus" and not has_rminus:
                feedback.pushWarning(self.tr(f"Weight for absent component '{key}' ignored."))
                parsed_weights.pop(key)

        crs = network.sourceCrs()
        transform_context = context.transformContext()

        # Build positive points index
        pos_pts_all = np.empty((0, 2), dtype=np.float64)
        pos_w_all = np.empty(0, dtype=np.float64)
        if has_pos:
            pts_list = []
            w_list = []
            for layer in pos_layers:
                pts, feats = self.source_points(layer, crs, transform_context)
                if len(pts) > 0:
                    pts_list.append(pts)
                    w_idx = layer.fields().lookupField(weight_field) if weight_field else -1
                    for f in feats:
                        w_val = 1.0
                        if w_idx >= 0:
                            val = f.attributes()[w_idx]
                            if val is not None:
                                try:
                                    fval = float(val)
                                    if fval > 0:
                                        w_val = fval
                                except (ValueError, TypeError):
                                    pass
                        w_list.append(w_val)
            if pts_list:
                pos_pts_all = np.concatenate(pts_list, axis=0)
                pos_w_all = np.asarray(w_list, dtype=np.float64)

        pos_index = QgsSpatialIndex()
        for idx in range(len(pos_pts_all)):
            mock_f = QgsFeature(idx)
            mock_f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(pos_pts_all[idx, 0], pos_pts_all[idx, 1])))
            pos_index.addFeature(mock_f)

        # Build negative points index
        neg_pts_all = np.empty((0, 2), dtype=np.float64)
        neg_w_all = np.empty(0, dtype=np.float64)
        if has_neg:
            pts_list = []
            w_list = []
            for layer in neg_layers:
                pts, feats = self.source_points(layer, crs, transform_context)
                if len(pts) > 0:
                    pts_list.append(pts)
                    w_idx = layer.fields().lookupField(weight_field) if weight_field else -1
                    for f in feats:
                        w_val = 1.0
                        if w_idx >= 0:
                            val = f.attributes()[w_idx]
                            if val is not None:
                                try:
                                    fval = float(val)
                                    if fval > 0:
                                        w_val = fval
                                except (ValueError, TypeError):
                                    pass
                        w_list.append(w_val)
            if pts_list:
                neg_pts_all = np.concatenate(pts_list, axis=0)
                neg_w_all = np.asarray(w_list, dtype=np.float64)

        neg_index = QgsSpatialIndex()
        for idx in range(len(neg_pts_all)):
            mock_f = QgsFeature(idx)
            mock_f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(neg_pts_all[idx, 0], neg_pts_all[idx, 1])))
            neg_index.addFeature(mock_f)

        rplus_provider = raster_plus.dataProvider() if has_rplus else None
        rminus_provider = raster_minus.dataProvider() if has_rminus else None

        kernels = ["uniform", "triangular", "epanechnikov", "gaussian"]
        kernel_str = kernels[kernel_enum]

        polylines, line_feats = self.source_polylines(network)
        n_seg = len(polylines)

        pos_den = np.zeros(n_seg) if has_pos else None
        neg_den = np.zeros(n_seg) if has_neg else None
        rplus_mean = np.zeros(n_seg) if has_rplus else None
        rminus_mean = np.zeros(n_seg) if has_rminus else None
        n_samples = np.zeros(n_seg, dtype=np.int32)

        for s in range(n_seg):
            if feedback.isCanceled():
                break
            feedback.setProgress(int(90.0 * s / max(1, n_seg)))

            geom = QgsGeometry.fromPolylineXY(
                [QgsPointXY(x, y) for x, y in polylines[s]])
            length = geom.length()

            # Segment samples
            sample_dists = []
            if length < step:
                sample_dists.append(length / 2.0)
            else:
                d_curr = step / 2.0
                while d_curr < length:
                    sample_dists.append(d_curr)
                    d_curr += step

            n_samples[s] = len(sample_dists)
            samples_xy = []
            for dist_val in sample_dists:
                pt = geom.interpolate(dist_val).asPoint()
                samples_xy.append((pt.x(), pt.y()))
            samples_xy = np.asarray(samples_xy, dtype=np.float64)

            # Compute point components density
            if has_pos:
                bbox = geom.boundingBox()
                bbox.grow(bandwidth)
                candidate_ids = pos_index.intersects(bbox)
                if candidate_ids:
                    pos_den[s] = comfort.segment_density(
                        samples_xy, pos_pts_all[candidate_ids], pos_w_all[candidate_ids], bandwidth, kernel_str
                    )
                else:
                    pos_den[s] = 0.0

            if has_neg:
                bbox = geom.boundingBox()
                bbox.grow(bandwidth)
                candidate_ids = neg_index.intersects(bbox)
                if candidate_ids:
                    neg_den[s] = comfort.segment_density(
                        samples_xy, neg_pts_all[candidate_ids], neg_w_all[candidate_ids], bandwidth, kernel_str
                    )
                else:
                    neg_den[s] = 0.0

            # Compute raster components mean
            if has_rplus:
                vals = []
                for pt_xy in samples_xy:
                    val, ok = rplus_provider.sample(QgsPointXY(*pt_xy), 1)
                    if ok and np.isfinite(val):
                        vals.append(val)
                rplus_mean[s] = float(np.mean(vals)) if vals else float('nan')

            if has_rminus:
                vals = []
                for pt_xy in samples_xy:
                    val, ok = rminus_provider.sample(QgsPointXY(*pt_xy), 1)
                    if ok and np.isfinite(val):
                        vals.append(val)
                rminus_mean[s] = float(np.mean(vals)) if vals else float('nan')

        if has_rplus:
            n_nan = int(np.isnan(rplus_mean).sum())
            if n_nan:
                feedback.pushWarning(self.tr(f"{n_nan} segment(s) outside raster_plus coverage - neutral"))

        if has_rminus:
            n_nan = int(np.isnan(rminus_mean).sum())
            if n_nan:
                feedback.pushWarning(self.tr(f"{n_nan} segment(s) outside raster_minus coverage - neutral"))

        components = {
            "positive": pos_den,
            "negative": neg_den,
            "raster_plus": rplus_mean,
            "raster_minus": rminus_mean,
        }
        directions = {
            "positive": +1,
            "negative": -1,
            "raster_plus": +1,
            "raster_minus": -1,
        }

        try:
            comfort_index, used, dropped = comfort.combine_components(
                components, directions, weights=parsed_weights
            )
        except ValueError as e:
            raise QgsProcessingException(str(e))

        for d_comp in dropped:
            feedback.pushWarning(self.tr(f"Component '{d_comp}' is constant across segments and was dropped."))

        comp_weights = [f"{name}={parsed_weights.get(name, 1.0)}" for name in used]
        feedback.pushInfo(self.tr(f"Used components: {', '.join(comp_weights)}"))

        mean_comfort = float(np.mean(comfort_index)) if len(comfort_index) > 0 else 0.0
        low_comfort_count = int(np.sum(comfort_index < 25.0)) if len(comfort_index) > 0 else 0
        feedback.pushInfo(self.tr(f"Mean comfort score: {mean_comfort:.2f}"))
        feedback.pushInfo(self.tr(f"Comfort score < 25 count: {low_comfort_count}"))

        fields = self.make_fields(
            ("pos_den", DOUBLE), ("neg_den", DOUBLE),
            ("rplus_mean", DOUBLE), ("rminus_mean", DOUBLE),
            ("comfort", DOUBLE), ("n_samples", INT),
            base=network.fields()
        )

        sink, dest_id = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields,
            QgsWkbTypes.Type.LineString, network.sourceCrs()
        )

        def opt(arr, i, digits=4):
            if arr is None:
                return None
            val = float(arr[i])
            if np.isnan(val):
                return None
            return round(val, digits)

        for s in range(n_seg):
            if feedback.isCanceled():
                break
            out = QgsFeature(fields)
            out.setGeometry(QgsGeometry.fromPolylineXY(
                [QgsPointXY(x, y) for x, y in polylines[s]]))

            orig_attrs = list(line_feats[s].attributes())[:len(network.fields())]
            out.setAttributes(orig_attrs + [
                opt(pos_den, s),
                opt(neg_den, s),
                opt(rplus_mean, s),
                opt(rminus_mean, s),
                round(float(comfort_index[s]), 2),
                int(n_samples[s])
            ])
            sink.addFeature(out, QgsFeatureSink.Flag.FastInsert)

        return {self.OUTPUT: dest_id}

    def createInstance(self):
        return StreetComfortAlgorithm()
