# -*- coding: utf-8 -*-
"""Seismic collapse / debris-spread / evacuation-corridor algorithm wrapper."""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureSink,
    QgsFields,
    QgsGeometry,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_SEISMIC, INT, PlanXAlgorithm
from ..engine import seismic


class SeismicDebrisAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_SEISMIC
    ICON = "tool_seismicdebris.png"

    BUILDINGS = "BUILDINGS"
    FLOOR_FIELD = "FLOOR_FIELD"
    YEAR_FIELD = "YEAR_FIELD"
    NETWORK_MODE = "NETWORK_MODE"
    NETWORK = "NETWORK"
    NETWORK_LINES = "NETWORK_LINES"
    HIGHWAY_FIELD = "HIGHWAY_FIELD"
    WIDTH_FIELD = "WIDTH_FIELD"
    DEFAULT_WIDTH = "DEFAULT_WIDTH"
    ROI = "ROI"
    BLOCKS = "BLOCKS"
    MAGNITUDE = "MAGNITUDE"
    FLOOR_HEIGHT = "FLOOR_HEIGHT"
    DEBRIS_FACTOR = "DEBRIS_FACTOR"
    SOLID_VOLUME_RATIO = "SOLID_VOLUME_RATIO"
    SEED = "SEED"

    OUT_BUILDINGS = "OUT_BUILDINGS"
    OUT_ENVELOPE = "OUT_ENVELOPE"
    OUT_BLOCKED = "OUT_BLOCKED"
    OUT_CORRIDORS = "OUT_CORRIDORS"

    #: Indices of the NETWORK_MODE enum options.
    MODE_POLYGONS, MODE_OSM_LINES, MODE_WIDTH_LINES, MODE_DIFFERENCE = range(4)

    def name(self):
        return "seismicdebris"

    def displayName(self):
        return self.tr("Seismic Collapse and Debris Spread (Monte Carlo)")

    def shortHelpString(self):
        return self.tr(
            "Screening-quality Monte Carlo model for earthquake-induced building "
            "collapse, road-blocking debris spread, and the resulting evacuation "
            "corridors that stay open.\n\n"
            "For each building, a collapse probability is derived from its "
            "construction year (older stock is more vulnerable) and scaled "
            "exponentially by the scenario's moment magnitude (Mw). A single "
            "seeded random draw decides collapse per building, so the same "
            "seed and inputs always reproduce the identical outcome - change "
            "the seed to sample a different realization of the same scenario.\n\n"
            "Collapsed buildings spread debris outward by a fraction (k) of "
            "their height (Goretti & Sarli, 2006) and contribute a debris "
            "volume from their footprint area, height and a void/solid ratio "
            "(FEMA guidance: ~0.10-0.20 steel/glass, ~0.25-0.35 reinforced "
            "concrete, ~0.35-0.45 unreinforced masonry).\n\n"
            "THE ROAD / OPEN-SPACE NETWORK - the public space debris can block - "
            "can be supplied four ways; pick one under 'Network source' and fill "
            "only the inputs labelled with that letter:\n\n"
            "A - Street / open-space polygons. You already have the street and "
            "open space as polygons (from a zoning plan, cadastre-derived street "
            "space, or a previous run); the layer is used as-is. Most faithful "
            "option: real widths, squares and setbacks are preserved.\n\n"
            "B - OSM highway centerlines. Road lines as downloaded with QuickOSM "
            "(key 'highway'). Each line is buffered by half a typical urban "
            "width for its class: motorway/trunk 25 m, primary 18, secondary 14, "
            "tertiary 10, residential/unclassified 8, service/living_street 5, "
            "pedestrian/footway/cycleway/path 3, steps 2; '_link' ramps inherit "
            "the parent class width; any other class uses the fallback width. "
            "The class field is auto-detected when it is named 'highway'. If a "
            "width field is also selected, a valid per-feature value overrides "
            "the class width.\n\n"
            "C - Centerlines with a width attribute. Any line network with a "
            "road-width column in metres (FULL width, not half). Lines are "
            "buffered by width/2; missing or unparseable values use the fallback "
            "width. Values like 6.5, '6,5' or '6.5 m' are all accepted. Tip: the "
            "Generate Demo City streets work here with no width field - every "
            "street then gets the fallback width.\n\n"
            "D - ROI minus blocks/parcels. Street/open space is computed as the "
            "difference between a region-of-interest polygon and the dissolved "
            "urban blocks. Parcels are dissolved internally, shared boundaries "
            "vanish, so cadastral parcels work directly as a blocks substitute. "
            "If no ROI is given, the convex hull of the blocks expanded by the "
            "fallback width is used - provide an explicit ROI for concave study "
            "areas, otherwise only a hull-shaped perimeter ring is added.\n\n"
            "All widths and debris radii are metric, so the buildings layer must "
            "use a projected CRS; network inputs in a different CRS are "
            "reprojected to the buildings CRS automatically.\n\n"
            "Outputs: annotated building points (height, collapse probability, "
            "collapsed flag, debris radius/volume), the dissolved debris "
            "envelope, the cumulative blockage on the network, and the "
            "remaining open evacuation corridors (network minus blockage).\n\n"
            "How to read the results\n"
            "- One run is ONE realization of the scenario, not the "
            "expected damage: which specific buildings collapse depends "
            "on the seed. The p_collapse field is the stable, "
            "seed-independent number; the collapsed flag is one dice "
            "roll consistent with it. For robust statements, rerun with "
            "10-20 seeds and look at what stays true across them.\n"
            "- The CORRIDORS output is the planning product: streets "
            "that remain passable once debris falls. Narrow streets "
            "with tall, old frontages vanish first - the corridors "
            "that survive EVERY seed are your dependable evacuation "
            "and emergency-access skeleton; corridors that flicker "
            "between seeds are not to be relied on.\n"
            "- Blockage area per street and the debris volume totals "
            "size the clearance problem (equipment, disposal sites) - "
            "screening-grade, but the right order of magnitude for "
            "preparedness planning.\n\n"
            "Using the results: overlay corridors on hospitals, fire "
            "stations and assembly areas - a facility whose every "
            "approach dies in most seeds needs a widened street or a "
            "second access NOW, not after the event; rank districts by "
            "corridor survival to target urban-renewal priorities; "
            "test magnitudes 6.5/7.0/7.5 to see where the network's "
            "resilience cliff sits."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.BUILDINGS, self.tr("Buildings (polygon)"), [QgsProcessing.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterField(
            self.FLOOR_FIELD, self.tr("Floor count field"),
            parentLayerParameterName=self.BUILDINGS, type=QgsProcessingParameterField.Numeric, optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.YEAR_FIELD, self.tr("Construction year field"),
            parentLayerParameterName=self.BUILDINGS, type=QgsProcessingParameterField.Numeric, optional=True))

        self.addParameter(QgsProcessingParameterEnum(
            self.NETWORK_MODE, self.tr("Network source (four alternatives - see help)"),
            options=[
                self.tr("A - Street / open-space polygons: use the polygon layer as-is"),
                self.tr("B - OSM highway centerlines: buffer by highway-class widths"),
                self.tr("C - Centerlines with a width attribute: buffer by width / 2"),
                self.tr("D - ROI minus blocks/parcels: street space by difference"),
            ], defaultValue=0))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("A: Road / open-space polygons (used as-is)"),
            [QgsProcessing.TypeVectorPolygon], optional=True))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK_LINES, self.tr("B, C: Road centerlines (e.g. a QuickOSM 'highway' download)"),
            [QgsProcessing.TypeVectorLine], optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.HIGHWAY_FIELD, self.tr("B: Highway class field (blank = auto-detect 'highway')"),
            parentLayerParameterName=self.NETWORK_LINES, optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.WIDTH_FIELD, self.tr("C: Road width field, full metres (in B: overrides the class width)"),
            parentLayerParameterName=self.NETWORK_LINES, optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.DEFAULT_WIDTH,
            self.tr("B, C: Fallback road width (m); D: expansion of the automatic ROI hull"),
            type=QgsProcessingParameterNumber.Double, minValue=0.5, defaultValue=8.0))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.ROI, self.tr("D: Region of interest (blank = convex hull of the blocks, expanded)"),
            [QgsProcessing.TypeVectorPolygon], optional=True))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.BLOCKS, self.tr("D: Urban blocks or parcels (dissolved internally)"),
            [QgsProcessing.TypeVectorPolygon], optional=True))

        param_mag = QgsProcessingParameterNumber(
            self.MAGNITUDE, self.tr("Scenario moment magnitude (Mw)"),
            type=QgsProcessingParameterNumber.Double, minValue=4.0, maxValue=9.0, defaultValue=7.0)
        self.addParameter(param_mag)
        self.addParameter(QgsProcessingParameterNumber(
            self.FLOOR_HEIGHT, self.tr("Average floor height (m)"),
            type=QgsProcessingParameterNumber.Double, minValue=1.0, defaultValue=3.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.DEBRIS_FACTOR, self.tr("Debris spread coefficient (k, fraction of height)"),
            type=QgsProcessingParameterNumber.Double, minValue=0.0, maxValue=1.0, defaultValue=0.4))
        self.addParameter(QgsProcessingParameterNumber(
            self.SOLID_VOLUME_RATIO, self.tr("Void/solid volume ratio (for debris volume)"),
            type=QgsProcessingParameterNumber.Double, minValue=0.1, maxValue=1.0, defaultValue=0.3))
        self.addParameter(QgsProcessingParameterNumber(
            self.SEED, self.tr("Random seed (Monte Carlo reproducibility)"),
            type=QgsProcessingParameterNumber.Integer, minValue=0, defaultValue=42))

        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_BUILDINGS, self.tr("Annotated buildings (collapse risk and debris)")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_ENVELOPE, self.tr("Debris spread envelope (dissolved)")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_BLOCKED, self.tr("Network blockage from debris")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_CORRIDORS, self.tr("Open evacuation corridors")))

    # ------------------------------------------------------------------ #
    # Network construction (the four sources)
    # ------------------------------------------------------------------ #
    _MODE_NEEDS = {
        0: ("NETWORK", "A: Road / open-space polygons (used as-is)"),
        1: ("NETWORK_LINES", "B, C: Road centerlines"),
        2: ("NETWORK_LINES", "B, C: Road centerlines"),
        3: ("BLOCKS", "D: Urban blocks or parcels"),
    }

    def checkParameterValues(self, parameters, context):
        mode = self.parameterAsEnum(parameters, self.NETWORK_MODE, context)
        param_name, label = self._MODE_NEEDS[mode]
        if self.parameterAsSource(parameters, param_name, context) is None:
            return False, self.tr("The selected network source needs '{0}'.").format(label)
        return super().checkParameterValues(parameters, context)

    def _geoms(self, source, target_crs, context, name):
        """(geometry, feature) pairs of ``source``, transformed to ``target_crs``."""
        xform = None
        crs = source.sourceCrs()
        if crs.isValid() and target_crs.isValid() and crs != target_crs:
            xform = QgsCoordinateTransform(crs, target_crs, context.transformContext())
        pairs = []
        for f in source.getFeatures():
            if not f.hasGeometry():
                continue
            g = QgsGeometry(f.geometry())
            if xform is not None:
                g.transform(xform)
            pairs.append((g, f))
        if not pairs:
            raise QgsProcessingException(f"No usable features found in the {name} layer.")
        return pairs

    def _network_union(self, parameters, context, feedback, mode, default_width, target_crs):
        """Street/open-space geometry for the chosen network source, in ``target_crs``."""
        if mode == self.MODE_POLYGONS:
            src = self.parameterAsSource(parameters, self.NETWORK, context)
            if src is None:
                raise QgsProcessingException(
                    "Network source A needs 'A: Road / open-space polygons'. Pick that "
                    "layer, or switch 'Network source' to B, C or D.")
            geoms = [g.makeValid() for g, _f in self._geoms(src, target_crs, context, "open-space polygon")]
            feedback.pushInfo(f"Network A: {len(geoms)} open-space polygons used as-is.")
            union = QgsGeometry.unaryUnion(geoms)

        elif mode in (self.MODE_OSM_LINES, self.MODE_WIDTH_LINES):
            src = self.parameterAsSource(parameters, self.NETWORK_LINES, context)
            if src is None:
                raise QgsProcessingException(
                    "Network sources B and C need 'B, C: Road centerlines'. Pick that "
                    "line layer, or switch 'Network source'.")
            width_field = self.parameterAsString(parameters, self.WIDTH_FIELD, context)
            width_idx = src.fields().lookupField(width_field) if width_field else -1
            if width_field and width_idx < 0:
                raise QgsProcessingException(
                    f"Width field '{width_field}' not found in the centerline layer.")
            hw_idx = -1
            if mode == self.MODE_OSM_LINES:
                hw_field = self.parameterAsString(parameters, self.HIGHWAY_FIELD, context) or "highway"
                hw_idx = src.fields().lookupField(hw_field)
                if hw_idx < 0:
                    raise QgsProcessingException(
                        f"Network source B: highway-class field '{hw_field}' not found in the "
                        f"centerline layer (fields: {', '.join(src.fields().names()) or 'none'}). "
                        "Choose the class field, or use source C with a width field.")
            elif width_idx < 0:
                feedback.pushInfo(
                    f"Network C: no width field chosen - every centerline gets the "
                    f"fallback width ({default_width:g} m).")
            buffered, n_fallback = [], 0
            for g, f in self._geoms(src, target_crs, context, "road centerline"):
                width = seismic.parse_width_m(f.attributes()[width_idx]) if width_idx >= 0 else None
                if width is None and hw_idx >= 0:
                    width = seismic.highway_width_m(f.attributes()[hw_idx], default_width)
                if width is None:
                    width = float(default_width)
                    n_fallback += 1
                buffered.append(g.buffer(width / 2.0, 8).makeValid())
            label = "B (OSM class widths)" if mode == self.MODE_OSM_LINES else "C (width attribute)"
            note = f", {n_fallback} on the fallback width" if n_fallback else ""
            feedback.pushInfo(f"Network {label}: buffered {len(buffered)} centerlines{note}.")
            union = QgsGeometry.unaryUnion(buffered)

        else:  # MODE_DIFFERENCE
            blocks_src = self.parameterAsSource(parameters, self.BLOCKS, context)
            if blocks_src is None:
                raise QgsProcessingException(
                    "Network source D needs 'D: Urban blocks or parcels'. Pick that "
                    "polygon layer, or switch 'Network source'.")
            blocks = QgsGeometry.unaryUnion(
                [g.makeValid() for g, _f in self._geoms(blocks_src, target_crs, context, "blocks/parcels")]
            ).makeValid()
            roi_src = self.parameterAsSource(parameters, self.ROI, context)
            if roi_src is not None:
                roi = QgsGeometry.unaryUnion(
                    [g.makeValid() for g, _f in self._geoms(roi_src, target_crs, context, "region of interest")]
                ).makeValid()
                feedback.pushInfo("Network D: street space = region of interest minus dissolved blocks.")
            else:
                roi = blocks.convexHull().buffer(float(default_width), 8)
                feedback.pushInfo(
                    f"Network D: no ROI given - using the convex hull of the blocks expanded "
                    f"by {default_width:g} m. Provide an explicit ROI for concave study areas.")
            union = roi.difference(blocks)

        union = union.makeValid()
        if union.isEmpty():
            raise QgsProcessingException(
                "The road / open-space network came out empty - check the layers picked for "
                "the selected network source (source D: does the ROI extend beyond the blocks?).")
        return union

    def processAlgorithm(self, parameters, context, feedback):
        buildings = self.parameterAsSource(parameters, self.BUILDINGS, context)
        if buildings is None:
            raise QgsProcessingException("Please provide a Buildings layer.")
        self.require_projected(buildings, "Buildings")
        floor_field = self.parameterAsString(parameters, self.FLOOR_FIELD, context)
        year_field = self.parameterAsString(parameters, self.YEAR_FIELD, context)
        magnitude = self.parameterAsDouble(parameters, self.MAGNITUDE, context)
        floor_height = self.parameterAsDouble(parameters, self.FLOOR_HEIGHT, context)
        debris_factor = self.parameterAsDouble(parameters, self.DEBRIS_FACTOR, context)
        solid_ratio = self.parameterAsDouble(parameters, self.SOLID_VOLUME_RATIO, context)
        seed = self.parameterAsInt(parameters, self.SEED, context)
        mode = self.parameterAsEnum(parameters, self.NETWORK_MODE, context)
        default_width = self.parameterAsDouble(parameters, self.DEFAULT_WIDTH, context)
        target_crs = buildings.sourceCrs()

        # Build the street/open-space geometry first so a wrong mode/layer
        # combination fails immediately, before the Monte Carlo pass.
        network_union = self._network_union(
            parameters, context, feedback, mode, default_width, target_crs)

        b_feats = [f for f in buildings.getFeatures() if f.hasGeometry()]
        if not b_feats:
            raise QgsProcessingException("No usable building features found.")

        floor_idx = buildings.fields().lookupField(floor_field) if floor_field else -1
        year_idx = buildings.fields().lookupField(year_field) if year_field else -1

        floors = np.ones(len(b_feats), dtype=np.float64)
        years = np.full(len(b_feats), 2000.0, dtype=np.float64)
        areas = np.zeros(len(b_feats), dtype=np.float64)
        geoms = []
        for i, f in enumerate(b_feats):
            g = f.geometry().makeValid()
            geoms.append(g)
            areas[i] = g.area()
            if floor_idx >= 0:
                try:
                    v = f.attributes()[floor_idx]
                    floors[i] = float(v) if v is not None else 1.0
                except (TypeError, ValueError):
                    pass
            if year_idx >= 0:
                try:
                    v = f.attributes()[year_idx]
                    years[i] = float(v) if v is not None else 2000.0
                except (TypeError, ValueError):
                    pass

        heights = floors * floor_height
        p_collapse = seismic.collapse_probability(years, magnitude)
        collapsed = seismic.simulate_collapse(seed, p_collapse)
        radius, volume = seismic.debris_extent(heights, areas, collapsed, debris_factor, solid_ratio)

        out_fields = self.make_fields(
            ("height_m", DOUBLE),
            ("collapse_prob", DOUBLE),
            ("collapsed", INT),
            ("debris_radius_m", DOUBLE),
            ("debris_vol_m3", DOUBLE),
            base=buildings.fields(),
        )
        sink_buildings, dest_buildings = self.parameterAsSink(
            parameters, self.OUT_BUILDINGS, context, out_fields, QgsWkbTypes.Point, target_crs)

        debris_geoms = []
        n_base = len(buildings.fields())
        total = len(b_feats)
        for i, f in enumerate(b_feats):
            if feedback.isCanceled():
                break
            out_feat = QgsFeature(out_fields)
            out_feat.setGeometry(geoms[i].centroid())
            out_feat.setAttributes(list(f.attributes())[:n_base] + [
                float(heights[i]), float(p_collapse[i]), int(collapsed[i]),
                float(radius[i]), float(volume[i]),
            ])
            sink_buildings.addFeature(out_feat, QgsFeatureSink.FastInsert)

            if collapsed[i]:
                debris = geoms[i].buffer(
                    float(radius[i]), 8, QgsGeometry.EndCapStyle.Square, QgsGeometry.JoinStyle.Miter, 2.0
                ).makeValid()
                debris_geoms.append(debris)

            feedback.setProgress(int((i + 1) / total * 100))

        results = {self.OUT_BUILDINGS: dest_buildings}

        sink_envelope, dest_envelope = self.parameterAsSink(
            parameters, self.OUT_ENVELOPE, context, QgsFields(), QgsWkbTypes.MultiPolygon, target_crs)
        sink_blocked, dest_blocked = self.parameterAsSink(
            parameters, self.OUT_BLOCKED, context, QgsFields(), QgsWkbTypes.MultiPolygon, target_crs)
        sink_corridors, dest_corridors = self.parameterAsSink(
            parameters, self.OUT_CORRIDORS, context, QgsFields(), QgsWkbTypes.MultiPolygon, target_crs)

        if debris_geoms:
            envelope = QgsGeometry.unaryUnion(debris_geoms).makeValid()
            env_feat = QgsFeature()
            env_feat.setGeometry(envelope)
            sink_envelope.addFeature(env_feat, QgsFeatureSink.FastInsert)

            blocked = network_union.intersection(envelope).makeValid()
            if not blocked.isEmpty():
                blk_feat = QgsFeature()
                blk_feat.setGeometry(blocked)
                sink_blocked.addFeature(blk_feat, QgsFeatureSink.FastInsert)

            corridors = network_union.difference(blocked).makeValid()
        else:
            corridors = network_union

        if not corridors.isEmpty():
            cor_feat = QgsFeature()
            cor_feat.setGeometry(corridors)
            sink_corridors.addFeature(cor_feat, QgsFeatureSink.FastInsert)

        results[self.OUT_ENVELOPE] = dest_envelope
        results[self.OUT_BLOCKED] = dest_blocked
        results[self.OUT_CORRIDORS] = dest_corridors

        n_collapsed = int(np.sum(collapsed))
        feedback.pushInfo(
            f"Mw {magnitude:g} scenario (seed {seed}): {n_collapsed}/{total} buildings collapsed, "
            f"{float(np.sum(volume)):.1f} m3 estimated debris."
        )

        return results

    def createInstance(self):
        return SeismicDebrisAlgorithm()
