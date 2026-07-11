# -*- coding: utf-8 -*-
"""Walking Slope Comfort: street segment profile statistics against a DEM."""
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
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_WALK, INT, PlanXAlgorithm, STRING
from ..engine import comfort


class WalkingSlopeAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_WALK
    ICON = "tool_walkingslope.png"
    NETWORK = "NETWORK"
    DEM = "DEM"
    SAMPLE_STEP = "SAMPLE_STEP"
    BREAKS = "BREAKS"
    OUTPUT = "OUTPUT"

    def name(self):
        return "walkingslope"

    def displayName(self):
        return self.tr("Walking Slope Comfort")

    def shortHelpString(self):
        return self.tr(
            "Profiles every street segment against a DEM to compute slope "
            "statistics, comfort classes, and direction-aware walking times "
            "based on Tobler's hiking speed.\n\n"
            "The Tobler speed is calculated as speed = 6·e^(−3.5·|m+0.05|) km/h, "
            "peaking slightly downhill at a −5% grade. For each segment, the tool "
            "measures length-weighted mean and maximum slope, total vertical climb "
            "and descent, and estimated forward and reverse walking travel times.\n\n"
            "Comfort breakpoints are illustrative: 5% ≈ comfortable, 8% ≈ short-ramp "
            "standards, and 12%+ ≈ stairs-preferred (local standards should override).\n\n"
            "How to read the results\n"
            "- slope_pct is the primary comfort driver for active travel.\n"
            "- time_fwd_min vs time_rev_min asymmetry captures the uphill time penalty "
            "that pedestrians actually experience. Routing tools that ignore this "
            "overestimate uphill catchments.\n"
            "- Comfort class >= 3 segments represent barrier locations that break "
            "wheelchair or stroller continuity.\n\n"
            "Using the results\n"
            "- Feed time_fwd_min as the cost field into OD, Nearest-Facility, or "
            "15-minute tools to enable slope-aware catchment analysis.\n"
            "- Overlay comfort class >= 3 segments with Walkability Audit slope scores to "
            "confirm steep sections.\n"
            "- Rank sidewalk and ramp interventions by climb_m × pedestrian volume."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("Street network (lines)"),
            [QgsProcessing.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.DEM, self.tr("DEM (elevation)")))
        self.addParameter(QgsProcessingParameterNumber(
            self.SAMPLE_STEP, self.tr("Profile sample spacing (m)"),
            QgsProcessingParameterNumber.Double, 10.0, minValue=0.5))
        self.addParameter(QgsProcessingParameterString(
            self.BREAKS, self.tr("Comfort class breakpoints, mean |slope| % (ILLUSTRATIVE defaults)"),
            defaultValue="5,8,12"))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Slope-profiled segments")))

    def processAlgorithm(self, parameters, context, feedback):
        network = self.parameterAsSource(parameters, self.NETWORK, context)
        dem = self.parameterAsRasterLayer(parameters, self.DEM, context)
        step = self.parameterAsDouble(parameters, self.SAMPLE_STEP, context)
        breaks_str = self.parameterAsString(parameters, self.BREAKS, context)
        self.require_projected(network, "Street network")

        if dem is None:
            raise QgsProcessingException("A valid DEM raster layer is required.")

        try:
            breaks = comfort.parse_breaks(breaks_str)
        except ValueError as e:
            raise QgsProcessingException(str(e))

        provider = dem.dataProvider()
        if provider is None:
            raise QgsProcessingException("Could not read DEM raster provider.")

        fields = self.make_fields(
            ("slope_pct", DOUBLE), ("max_pct", DOUBLE), ("climb_m", DOUBLE), ("descent_m", DOUBLE),
            ("tobler_fwd_kmh", DOUBLE), ("tobler_rev_kmh", DOUBLE),
            ("time_fwd_min", DOUBLE), ("time_rev_min", DOUBLE),
            ("comfort_class", INT), ("class_label", STRING),
            base=network.fields()
        )

        sink, dest_id = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields,
            QgsWkbTypes.LineString, network.sourceCrs()
        )

        bad_dem_count = 0
        all_slopes = []
        class_ge_3_count = 0
        worst_slope = 0.0
        worst_seg_id = -1

        polylines, line_feats = self.source_polylines(network)
        n_seg = len(polylines)
        n_base = len(network.fields())

        for s in range(n_seg):
            if feedback.isCanceled():
                break
            feedback.setProgress(int(100.0 * s / max(1, n_seg)))

            geom = QgsGeometry.fromPolylineXY(
                [QgsPointXY(x, y) for x, y in polylines[s]])
            length = geom.length()

            # Determine sample distances
            dists = []
            d_curr = 0.0
            while d_curr < length - 1e-9:
                dists.append(d_curr)
                d_curr += step
            if not dists or dists[-1] < length - 1e-9:
                dists.append(length)
            else:
                dists[-1] = length

            # Sample the DEM at distances
            z = []
            d = []
            for dist_val in dists:
                pt = geom.interpolate(dist_val).asPoint()
                val, ok = provider.sample(pt, 1)
                if ok and np.isfinite(val):
                    z.append(val)
                    d.append(dist_val)

            # Analyze grade stats
            if len(z) < 2:
                mean_abs, max_abs, climb, descent = 0.0, 0.0, 0.0, 0.0
                bad_dem_count += 1
                time_fwd = time_rev = comfort.profile_time_min([0.0], [length])
            else:
                mean_abs, max_abs, climb, descent = comfort.grade_stats(z, d)

                # Setup grades and lengths for travel time
                z_arr = np.asarray(z, dtype=np.float64)
                d_arr = np.asarray(d, dtype=np.float64)
                dz = z_arr[1:] - z_arr[:-1]
                dd = d_arr[1:] - d_arr[:-1]
                mask = dd > 0
                if np.any(mask):
                    grades = dz[mask] / dd[mask]
                    lengths = dd[mask]
                    time_fwd = comfort.profile_time_min(grades, lengths)
                    time_rev = comfort.profile_time_min(-grades[::-1], lengths[::-1])
                else:
                    time_fwd = time_rev = comfort.profile_time_min([0.0], [length])

            slope_pct_val = mean_abs * 100.0
            max_pct_val = max_abs * 100.0

            if length > 0 and time_fwd > 0:
                tobler_fwd_kmh = (length / 1000.0) / (time_fwd / 60.0)
            else:
                tobler_fwd_kmh = 0.0

            if length > 0 and time_rev > 0:
                tobler_rev_kmh = (length / 1000.0) / (time_rev / 60.0)
            else:
                tobler_rev_kmh = 0.0

            comfort_class_val = comfort.class_of(slope_pct_val, breaks)
            if len(breaks) == 3:
                labels = ["Comfortable", "Moderate", "Steep", "Severe"]
                class_label = labels[comfort_class_val - 1]
            else:
                class_label = f"Class {comfort_class_val}"

            # Track stats for log
            all_slopes.append(slope_pct_val)
            if comfort_class_val >= 3:
                class_ge_3_count += 1
            if slope_pct_val > worst_slope:
                worst_slope = slope_pct_val
                worst_seg_id = line_feats[s].id()

            out_feat = QgsFeature(fields)
            out_feat.setGeometry(geom)

            orig_attrs = list(line_feats[s].attributes())[:n_base]
            out_feat.setAttributes(orig_attrs + [
                slope_pct_val, max_pct_val, climb, descent,
                tobler_fwd_kmh, tobler_rev_kmh,
                time_fwd, time_rev,
                comfort_class_val, class_label
            ])
            sink.addFeature(out_feat, QgsFeatureSink.FastInsert)

        if bad_dem_count > 0:
            feedback.pushWarning(self.tr(
                f"{bad_dem_count} segment(s) with insufficient DEM coverage - treated as flat."
            ))

        mean_slope = float(np.mean(all_slopes)) if all_slopes else 0.0
        share_ge_3 = float(class_ge_3_count / len(all_slopes)) if all_slopes else 0.0
        feedback.pushInfo(self.tr(f"Mean slope_pct: {mean_slope:.2f}%"))
        feedback.pushInfo(self.tr(f"Share of comfort class >= 3: {share_ge_3 * 100.0:.1f}%"))
        feedback.pushInfo(self.tr(f"Worst segment slope_pct: {worst_slope:.2f}% (fid {worst_seg_id})"))

        return {self.OUTPUT: dest_id}

    def createInstance(self):
        return WalkingSlopeAlgorithm()
