# -*- coding: utf-8 -*-
"""Walkability Audit: composite street-segment walk scores."""
from __future__ import annotations

import math

import numpy as np

from qgis.core import (
    QgsFeature,
    QgsFeatureSink,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterString,
    QgsSpatialIndex,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_WALK, INT, PlanXAlgorithm
from ..engine import graphs, walkability


def _midpoint(coords: np.ndarray):
    """Point at half the length of a polyline given as (k, 2) coords."""
    seg = np.diff(coords, axis=0)
    seg_len = np.hypot(seg[:, 0], seg[:, 1])
    total = float(seg_len.sum())
    if total <= 0:
        return float(coords[0, 0]), float(coords[0, 1])
    half = total / 2.0
    cum = 0.0
    for i, sl in enumerate(seg_len):
        if cum + sl >= half:
            t = (half - cum) / sl if sl > 0 else 0.0
            x = coords[i, 0] + t * (coords[i + 1, 0] - coords[i, 0])
            y = coords[i, 1] + t * (coords[i + 1, 1] - coords[i, 1])
            return float(x), float(y)
        cum += sl
    return float(coords[-1, 0]), float(coords[-1, 1])


class WalkabilityAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_WALK
    ICON = "tool_walkability.png"
    NETWORK = "NETWORK"
    LANDUSE = "LANDUSE"
    CATEGORY_FIELD = "CATEGORY_FIELD"
    POIS = "POIS"
    DEM = "DEM"
    RADIUS = "RADIUS"
    WEIGHTS = "WEIGHTS"
    OUT_SEGMENTS = "OUT_SEGMENTS"

    def name(self):
        return "walkability"

    def displayName(self):
        return self.tr("Walkability Audit")

    def shortHelpString(self):
        return self.tr(
            "Scores every street segment 0-100 for WALKABILITY - the audit "
            "layer of the walkable-city agenda, computed from the classic "
            "ingredients of the walkability-index literature (Frank et al. "
            "2010; Ewing & Cervero's D-variables):\n\n"
            "- INTERSECTIONS: street junctions (3+ legs) per km2 around the "
            "segment - the connectivity term; 120/km2 scores 100 by default;\n"
            "- LAND-USE MIX: normalised Shannon entropy of the land-use "
            "areas within the radius (needs the land-use layer + category "
            "field);\n"
            "- DESTINATIONS: points of interest within the radius (shops, "
            "schools, stops...); 25 POIs score 100 by default;\n"
            "- BLOCK LENGTH: mean street-segment length around the segment - "
            "shorter blocks mean more route choice; 80 m scores 100, 400 m "
            "scores 0;\n"
            "- SLOPE: segment gradient from an optional DEM; 0 percent "
            "scores 100, 10 percent scores 0.\n\n"
            "The total is the weighted mean of the available components "
            "(weights of missing inputs are renormalised away). Weights are "
            "editable as free text, e.g. "
            "'intersections=0.3, mix=0.25, destinations=0.25, "
            "blocklength=0.1, slope=0.1'.\n\n"
            "Output: the exploded street segments with the total walk score, "
            "every sub-score and the raw ingredient values - style by "
            "'walk_score' for the audit map, or feed it to Pedestrian Route "
            "Quality. Use a projected CRS; the radius is in map units."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("Street network (lines)"),
            [QgsProcessing.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.LANDUSE, self.tr("Land-use polygons (optional, for the mix)"),
            [QgsProcessing.TypeVectorPolygon], optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.CATEGORY_FIELD, self.tr("Land-use category field"),
            parentLayerParameterName=self.LANDUSE, optional=True))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.POIS, self.tr("Destinations / POIs (optional)"),
            [QgsProcessing.TypeVectorPoint], optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.DEM, self.tr("DEM for slope (optional)"), optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.RADIUS, self.tr("Audit radius around each segment (map units)"),
            QgsProcessingParameterNumber.Double, 400.0, minValue=10.0))
        self.addParameter(QgsProcessingParameterString(
            self.WEIGHTS, self.tr("Component weights"),
            "intersections=0.3, mix=0.25, destinations=0.25, "
            "blocklength=0.1, slope=0.1"))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_SEGMENTS, self.tr("Walkability segments")))

    def processAlgorithm(self, parameters, context, feedback):
        network = self.parameterAsSource(parameters, self.NETWORK, context)
        landuse = self.parameterAsSource(parameters, self.LANDUSE, context)
        cat_field = self.parameterAsString(parameters, self.CATEGORY_FIELD, context)
        pois = self.parameterAsSource(parameters, self.POIS, context)
        dem = self.parameterAsRasterLayer(parameters, self.DEM, context)
        radius = self.parameterAsDouble(parameters, self.RADIUS, context)
        weights_text = self.parameterAsString(parameters, self.WEIGHTS, context)
        self.require_projected(network, "Street network")

        weights = {}
        for token in str(weights_text).replace(";", ",").split(","):
            token = token.strip()
            if not token:
                continue
            key, _, val = token.partition("=")
            key = key.strip().lower()
            try:
                value = float(val.strip())
            except ValueError:
                feedback.pushWarning(self.tr(
                    f"Weight '{token}' has no number - ignored."))
                continue
            if key not in walkability.DEFAULT_WEIGHTS:
                feedback.pushWarning(self.tr(
                    f"Unknown component '{key}' - ignored (use "
                    f"{', '.join(walkability.DEFAULT_WEIGHTS)})."))
                continue
            weights[key] = value

        polylines, line_feats = self.source_polylines(network)
        graph = graphs.build_node_graph(polylines)
        n_seg = len(polylines)
        feedback.pushInfo(self.tr(
            f"{n_seg} street segments, {graph.num_nodes} nodes; "
            f"audit radius {radius:g}."))

        mids = np.asarray([_midpoint(c) for c in polylines])
        junctions = graph.node_xy[graph.degrees() >= 3]
        r2 = radius * radius
        area_km2 = math.pi * radius * radius / 1e6

        crs = network.sourceCrs()
        xform = context.transformContext()
        poi_xy = None
        if pois is not None:
            poi_xy, _ = self.source_points(pois, crs, xform)

        lu_feats, lu_index, lu_cat_idx = [], None, -1
        if landuse is not None and cat_field:
            lu_cat_idx = landuse.fields().lookupField(cat_field)
            lu_index = QgsSpatialIndex()
            for i, f in enumerate(landuse.getFeatures()):
                g = f.geometry()
                if g is None or g.isEmpty():
                    continue
                qf = QgsFeature(len(lu_feats))
                qf.setGeometry(g)
                lu_index.insertFeature(qf)
                lu_feats.append(f)
        elif landuse is not None:
            feedback.pushWarning(self.tr(
                "Land-use layer given without a category field - the mix "
                "component is skipped."))

        provider = dem.dataProvider() if dem is not None else None
        bad_samples = 0

        inter_density = np.zeros(n_seg)
        block_len = np.zeros(n_seg)
        mix = np.zeros(n_seg) if lu_index is not None else None
        dest_count = np.zeros(n_seg) if poi_xy is not None else None
        slope_pct = np.zeros(n_seg) if provider is not None else None

        for s in range(n_seg):
            if feedback.isCanceled():
                break
            mx, my = mids[s]
            if len(junctions):
                d2 = (junctions[:, 0] - mx) ** 2 + (junctions[:, 1] - my) ** 2
                inter_density[s] = float((d2 <= r2).sum()) / area_km2
            near = ((mids[:, 0] - mx) ** 2 + (mids[:, 1] - my) ** 2) <= r2
            block_len[s] = float(graph.edge_len[near].mean())
            if dest_count is not None and len(poi_xy):
                d2 = (poi_xy[:, 0] - mx) ** 2 + (poi_xy[:, 1] - my) ** 2
                dest_count[s] = float((d2 <= r2).sum())
            if mix is not None:
                buf = QgsGeometry.fromPointXY(QgsPointXY(mx, my)).buffer(radius, 12)
                areas = {}
                for fid in lu_index.intersects(buf.boundingBox()):
                    g = lu_feats[fid].geometry()
                    inter = g.intersection(buf)
                    if inter is None or inter.isEmpty():
                        continue
                    cat = str(lu_feats[fid].attributes()[lu_cat_idx])
                    areas[cat] = areas.get(cat, 0.0) + float(inter.area())
                mix[s] = walkability.shannon_mix(areas.values())
            if slope_pct is not None:
                coords = polylines[s]
                z0, ok0 = provider.sample(QgsPointXY(*coords[0]), 1)
                z1, ok1 = provider.sample(QgsPointXY(*coords[-1]), 1)
                seg_len = float(graph.edge_len[s])
                if ok0 and ok1 and seg_len > 0:
                    slope_pct[s] = abs(z1 - z0) / seg_len * 100.0
                else:
                    bad_samples += 1
            feedback.setProgress(90.0 * (s + 1) / n_seg)
        if bad_samples:
            feedback.pushWarning(self.tr(
                f"{bad_samples} segment(s) had no DEM value - treated as flat."))

        scores = walkability.walk_scores(
            inter_density, mix=mix, dest_count=dest_count,
            block_len=block_len, slope_pct=slope_pct, weights=weights)
        total = scores["total"]

        fields = self.make_fields(
            ("walk_score", DOUBLE), ("s_inter", DOUBLE), ("s_mix", DOUBLE),
            ("s_dest", DOUBLE), ("s_block", DOUBLE), ("s_slope", DOUBLE),
            ("int_km2", DOUBLE), ("mix_ent", DOUBLE), ("n_pois", INT),
            ("blk_len", DOUBLE), ("slope_pct", DOUBLE),
            base=network.fields())
        sink, dest = self.parameterAsSink(
            parameters, self.OUT_SEGMENTS, context, fields,
            QgsWkbTypes.LineString, crs)
        n_base = len(network.fields())

        def opt(arr, i, digits=2):
            return None if arr is None else round(float(arr[i]), digits)

        for s in range(n_seg):
            if feedback.isCanceled():
                break
            out = QgsFeature(fields)
            out.setGeometry(QgsGeometry.fromPolylineXY(
                [QgsPointXY(x, y) for x, y in polylines[s]]))
            out.setAttributes(
                list(line_feats[s].attributes())[:n_base] + [
                    round(float(total[s]), 2),
                    round(float(scores["s_intersections"][s]), 2),
                    opt(scores.get("s_mix"), s),
                    opt(scores.get("s_destinations"), s),
                    opt(scores.get("s_blocklength"), s),
                    opt(scores.get("s_slope"), s),
                    round(float(inter_density[s]), 3),
                    opt(mix, s, 4),
                    None if dest_count is None else int(dest_count[s]),
                    round(float(block_len[s]), 2),
                    opt(slope_pct, s, 3),
                ])
            sink.addFeature(out, QgsFeatureSink.FastInsert)

        mean_score = float(total.mean()) if n_seg else 0.0
        low = float((total < 50.0).sum()) / n_seg * 100.0 if n_seg else 0.0
        parts = ["intersections", "block length"]
        if mix is not None:
            parts.insert(1, "land-use mix")
        if dest_count is not None:
            parts.insert(-1, "destinations")
        if slope_pct is not None:
            parts.append("slope")
        feedback.pushInfo(self.tr(
            f"Components used: {', '.join(parts)}."))
        feedback.pushInfo(self.tr(
            f"Mean walk score {mean_score:.1f}; {low:.1f} percent of "
            f"segments score below 50."))
        return {self.OUT_SEGMENTS: dest}

    def createInstance(self):
        return WalkabilityAlgorithm()
