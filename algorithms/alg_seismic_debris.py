# -*- coding: utf-8 -*-
"""Seismic damage / debris-spread / evacuation-corridor algorithm wrapper."""
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

from .base import DOUBLE, GROUP_SEISMIC, INT, STRING, PlanXAlgorithm
from ..engine import seismic
from ..engine import uncertainty


def _float_or(value, fallback):
    """``float(value)`` with a fallback for nulls and non-numeric text."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


class SeismicDebrisAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_SEISMIC
    ICON = "tool_seismicdebris.png"

    BUILDINGS = "BUILDINGS"
    FLOOR_FIELD = "FLOOR_FIELD"
    YEAR_FIELD = "YEAR_FIELD"
    PGA_FIELD = "PGA_FIELD"
    BUILDING_TYPE = "BUILDING_TYPE"
    NETWORK_MODE = "NETWORK_MODE"
    NETWORK = "NETWORK"
    NETWORK_LINES = "NETWORK_LINES"
    HIGHWAY_FIELD = "HIGHWAY_FIELD"
    WIDTH_FIELD = "WIDTH_FIELD"
    DEFAULT_WIDTH = "DEFAULT_WIDTH"
    ROI = "ROI"
    BLOCKS = "BLOCKS"
    MAGNITUDE = "MAGNITUDE"
    REFERENCE_PGA = "REFERENCE_PGA"
    FLOOR_HEIGHT = "FLOOR_HEIGHT"
    DEBRIS_FACTOR = "DEBRIS_FACTOR"
    SOLID_VOLUME_RATIO = "SOLID_VOLUME_RATIO"
    VOID_RATIO = "VOID_RATIO"
    DEBRIS_DENSITY = "DEBRIS_DENSITY"
    MIN_CLEAR_WIDTH = "MIN_CLEAR_WIDTH"
    SIMULATIONS = "SIMULATIONS"
    SEED = "SEED"

    OUT_BUILDINGS = "OUT_BUILDINGS"
    OUT_ENVELOPE = "OUT_ENVELOPE"
    OUT_BLOCKED = "OUT_BLOCKED"
    OUT_CORRIDORS = "OUT_CORRIDORS"
    OUT_NAVIGABLE = "OUT_NAVIGABLE"

    #: Indices of the NETWORK_MODE enum options.
    MODE_POLYGONS, MODE_OSM_LINES, MODE_WIDTH_LINES, MODE_DIFFERENCE = range(4)

    def name(self):
        return "seismicdebris"

    def displayName(self):
        return self.tr("Seismic Collapse and Debris Spread (Monte Carlo)")

    def shortHelpString(self):
        return self.tr(
            "Screening-quality Monte Carlo model for earthquake-induced building "
            "damage, the debris it throws onto the street, and the evacuation "
            "corridors that stay open.\n\n"
            "HOW DAMAGE IS ESTIMATED\n"
            "Each building gets a full damage distribution - none, slight, "
            "moderate, extensive, complete - from lognormal fragility curves, "
            "not a single collapse yes/no. The curves are the equivalent-PGA "
            "structural fragilities of the Hazus Earthquake Model Technical "
            "Manual 6.1 (Tables 5-37 to 5-40), which give a median ground "
            "acceleration per damage state for each building type and seismic "
            "design level. The design level comes from the construction year: "
            "1985 and older -> Pre-Code, 1986-2000 -> Low-Code, 2001-2018 -> "
            "Moderate-Code, newer -> High-Code. Building height class (low / "
            "mid / high rise) is derived from the floor-count field when one "
            "is given.\n\n"
            "These are US curves: Hazus ties its design levels to US code "
            "eras and its reference spectrum to a western United States "
            "earthquake. Pinning them to Turkish regulation years is an "
            "analogy, not a calibration. Treat the output as comparative "
            "screening; do not quote it as a Turkish loss estimate.\n\n"
            "GROUND MOTION\n"
            "Best: give a PGA field in g on the buildings layer (join a "
            "ShakeMap, USGS or AFAD raster). The model then uses real site "
            "shaking, and distance and site effects come for free.\n"
            "If you have no PGA field, the scenario magnitude (Mw) scales a "
            "nominal reference PGA exponentially from Mw 7.0. That fallback "
            "carries no distance, site class or fault term - it is a knob, "
            "not a ground-motion prediction. It no longer saturates the way "
            "the older model did: probabilities rise smoothly with magnitude "
            "instead of pinning to 1.0 above roughly Mw 7.2.\n\n"
            "DAMAGE -> DEBRIS\n"
            "A damaged building sheds a share of its material: nothing for "
            "slight damage, a little for moderate, a large part for "
            "extensive, everything for complete. That covers the common case "
            "the old binary model missed - a building left standing but "
            "stripping its facade and infill into the street.\n"
            "Three quantities come out. 'Solid' is material volume: footprint "
            "x height x the void/solid ratio of the building itself (FEMA "
            "guidance: ~0.10-0.20 steel/glass, ~0.25-0.35 reinforced "
            "concrete, ~0.35-0.45 unreinforced masonry). 'Pile' is the bulk "
            "volume the rubble occupies once the air between fragments is "
            "counted. 'Mass' is the tonnage to haul away. The pile is what "
            "takes up street space; the mass is what sizes the clearance "
            "operation.\n"
            "Debris reaches out by a fraction (k) of building height (Goretti "
            "& Sarli, 2006), scaled by how much of the building actually came "
            "down.\n\n"
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
            "OUTPUTS\n"
            "- Annotated building points: height, collapse probability, the "
            "sampled damage state, debris radius, and the three debris "
            "quantities.\n"
            "- Debris spread envelope (dissolved).\n"
            "- Network blockage: the part of the street space debris covers.\n"
            "- Open evacuation corridors: street space minus blockage.\n"
            "- Navigable core: the corridors narrowed by the minimum clear "
            "width, so a sliver of pavement that no vehicle fits through no "
            "longer counts as an evacuation route. The gap between the two "
            "layers is the street space lost to pinching, and it is reported "
            "with the run.\n\n"
            "How to read the results\n"
            "- One run is ONE realization of the scenario, not the "
            "expected damage: which specific buildings collapse depends "
            "on the seed. The collapse_prob field is the stable, "
            "seed-independent number; the damage_state is one dice roll "
            "consistent with it.\n"
            "- Set 'Simulation runs' above 0 to let the tool do the "
            "repeat-and-compare for you: it reruns the scenario under "
            "N seeds and writes collapse_freq per building (the share of "
            "runs a building collapsed in) plus summary statistics in the "
            "log. That is what the corridor-survival advice below means in "
            "practice; leave it at 0 for a fast single realization.\n"
            "- The CORRIDORS output is the planning product: streets "
            "that remain passable once debris falls. Narrow streets "
            "with tall, old frontages vanish first - the corridors "
            "that survive EVERY seed are your dependable evacuation "
            "and emergency-access skeleton; corridors that flicker "
            "between seeds are not to be relied on. Cross-check them "
            "against the NAVIGABLE layer before calling a route usable.\n"
            "- Blockage area per street and the debris mass totals "
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
            self.BUILDINGS, self.tr("Buildings (polygon)"), [QgsProcessing.SourceType.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterField(
            self.FLOOR_FIELD, self.tr("Floor count field"),
            parentLayerParameterName=self.BUILDINGS, type=QgsProcessingParameterField.DataType.Numeric, optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.YEAR_FIELD, self.tr("Construction year field"),
            parentLayerParameterName=self.BUILDINGS, type=QgsProcessingParameterField.DataType.Numeric, optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.PGA_FIELD, self.tr("Peak ground acceleration field, in g (recommended - replaces the magnitude estimate)"),
            parentLayerParameterName=self.BUILDINGS, type=QgsProcessingParameterField.DataType.Numeric, optional=True))
        self.addParameter(QgsProcessingParameterEnum(
            self.BUILDING_TYPE, self.tr("Building type (Hazus type; height class comes from the floor field)"),
            options=[self.tr("{0} - {1}").format(code, label) for code, label in seismic.BUILDING_TYPES],
            defaultValue=0))

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
            [QgsProcessing.SourceType.TypeVectorPolygon], optional=True))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK_LINES, self.tr("B, C: Road centerlines (e.g. a QuickOSM 'highway' download)"),
            [QgsProcessing.SourceType.TypeVectorLine], optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.HIGHWAY_FIELD, self.tr("B: Highway class field (blank = auto-detect 'highway')"),
            parentLayerParameterName=self.NETWORK_LINES, optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.WIDTH_FIELD, self.tr("C: Road width field, full metres (in B: overrides the class width)"),
            parentLayerParameterName=self.NETWORK_LINES, optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.DEFAULT_WIDTH,
            self.tr("B, C: Fallback road width (m); D: expansion of the automatic ROI hull"),
            type=QgsProcessingParameterNumber.Type.Double, minValue=0.5, defaultValue=8.0))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.ROI, self.tr("D: Region of interest (blank = convex hull of the blocks, expanded)"),
            [QgsProcessing.SourceType.TypeVectorPolygon], optional=True))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.BLOCKS, self.tr("D: Urban blocks or parcels (dissolved internally)"),
            [QgsProcessing.SourceType.TypeVectorPolygon], optional=True))

        param_mag = QgsProcessingParameterNumber(
            self.MAGNITUDE, self.tr("Scenario moment magnitude (Mw)"),
            type=QgsProcessingParameterNumber.Type.Double, minValue=4.0, maxValue=9.0, defaultValue=7.0)
        self.addParameter(param_mag)
        self.addParameter(QgsProcessingParameterNumber(
            self.REFERENCE_PGA,
            self.tr("Nominal site PGA at Mw 7.0, in g (used only when no PGA field is given)"),
            type=QgsProcessingParameterNumber.Type.Double, minValue=0.01, maxValue=2.0,
            defaultValue=seismic.DEFAULT_REFERENCE_PGA))
        self.addParameter(QgsProcessingParameterNumber(
            self.FLOOR_HEIGHT, self.tr("Average floor height (m)"),
            type=QgsProcessingParameterNumber.Type.Double, minValue=1.0, defaultValue=3.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.DEBRIS_FACTOR, self.tr("Debris spread coefficient (k, fraction of height)"),
            type=QgsProcessingParameterNumber.Type.Double, minValue=0.0, maxValue=1.0, defaultValue=0.4))
        self.addParameter(QgsProcessingParameterNumber(
            self.SOLID_VOLUME_RATIO, self.tr("Void/solid volume ratio (material share of the building)"),
            type=QgsProcessingParameterNumber.Type.Double, minValue=0.1, maxValue=1.0, defaultValue=0.3))
        self.addParameter(QgsProcessingParameterNumber(
            self.VOID_RATIO, self.tr("Void fraction of the debris pile (air between fragments)"),
            type=QgsProcessingParameterNumber.Type.Double, minValue=0.0, maxValue=0.9,
            defaultValue=seismic.DEFAULT_VOID_RATIO))
        self.addParameter(QgsProcessingParameterNumber(
            self.DEBRIS_DENSITY, self.tr("Debris material density (tonnes per m3)"),
            type=QgsProcessingParameterNumber.Type.Double, minValue=0.1, maxValue=5.0,
            defaultValue=seismic.DEFAULT_DEBRIS_DENSITY))
        self.addParameter(QgsProcessingParameterNumber(
            self.MIN_CLEAR_WIDTH,
            self.tr("Minimum clear width for a usable route (m, emergency-vehicle access)"),
            type=QgsProcessingParameterNumber.Type.Double, minValue=0.1, maxValue=30.0, defaultValue=3.5))
        self.addParameter(QgsProcessingParameterNumber(
            self.SIMULATIONS,
            self.tr("Simulation runs (0 = one realization; 5-20 repeats to see what survives)"),
            type=QgsProcessingParameterNumber.Type.Integer, minValue=0, maxValue=100, defaultValue=0))
        self.addParameter(QgsProcessingParameterNumber(
            self.SEED, self.tr("Random seed (Monte Carlo reproducibility)"),
            type=QgsProcessingParameterNumber.Type.Integer, minValue=0, defaultValue=42))

        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_BUILDINGS, self.tr("Annotated buildings (damage risk and debris)")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_ENVELOPE, self.tr("Debris spread envelope (dissolved)")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_BLOCKED, self.tr("Network blockage from debris")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_CORRIDORS, self.tr("Open evacuation corridors")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_NAVIGABLE, self.tr("Navigable street core (corridors narrowed by the minimum clear width)")))

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
        # Everything this tool produces downstream is areal - blockage,
        # corridors, the navigable core. A zero-area network therefore yields a
        # run that looks successful and means nothing, and the commonest way to
        # get one is binding centre lines to source A, which wants polygons.
        if union.area() <= 0.0:
            raise QgsProcessingException(
                "The road / open-space network has no area. Source A takes street or "
                "open-space POLYGONS, and the layer given is a line or point layer. Use "
                "source B or C for centerlines (they are buffered to their road width), "
                "or source D to build street space from a region of interest minus blocks.")
        return union

    # ------------------------------------------------------------------ #
    # Run helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _debris_geometry(geoms, radius):
        """Buffered debris footprint per building, skipping the zeros."""
        debris = []
        for geom, reach in zip(geoms, radius):
            if reach <= 0.0:
                continue
            debris.append(geom.buffer(
                float(reach), 8, QgsGeometry.EndCapStyle.Square,
                QgsGeometry.JoinStyle.Miter, 2.0).makeValid())
        return debris

    @staticmethod
    def _blocked_area(blocked):
        """Planar area of a possibly empty or null geometry."""
        if blocked is None or blocked.isEmpty():
            return 0.0
        return float(blocked.area())

    @staticmethod
    def output_fields(base=None):
        """The columns appended to the incoming building schema, in order.

        The order is load-bearing. ``PlanXAlgorithm._apply_default_renderer``
        colours the layer by the LAST numeric field whose name contains one of
        its preference tokens, so whatever sits at the end of the matching run
        decides what the map shows. Here that is ``collapse_prob`` - the
        seed-independent number, and the one worth colouring. Reordering these
        fields to put, say, ``collapse_freq`` later would repaint every result
        without failing a single output-count check, so tests/smoke_plugin.py
        asserts the choice against this method rather than a hand-copied list.
        """
        return PlanXAlgorithm.make_fields(
            ("height_m", DOUBLE),
            ("collapse_prob", DOUBLE),
            ("collapsed", INT),
            ("damage_state", STRING),
            ("debris_radius_m", DOUBLE),
            ("debris_vol_m3", DOUBLE),
            ("debris_pile_m3", DOUBLE),
            ("debris_mass_t", DOUBLE),
            ("collapse_freq", DOUBLE),
            base=base,
        )

    def processAlgorithm(self, parameters, context, feedback):
        buildings = self.parameterAsSource(parameters, self.BUILDINGS, context)
        if buildings is None:
            raise QgsProcessingException("Please provide a Buildings layer.")
        self.require_projected(buildings, "Buildings")
        floor_field = self.parameterAsString(parameters, self.FLOOR_FIELD, context)
        year_field = self.parameterAsString(parameters, self.YEAR_FIELD, context)
        pga_field = self.parameterAsString(parameters, self.PGA_FIELD, context)
        type_index = self.parameterAsEnum(parameters, self.BUILDING_TYPE, context)
        building_type = seismic.BUILDING_TYPES[type_index][0]
        magnitude = self.parameterAsDouble(parameters, self.MAGNITUDE, context)
        reference_pga = self.parameterAsDouble(parameters, self.REFERENCE_PGA, context)
        floor_height = self.parameterAsDouble(parameters, self.FLOOR_HEIGHT, context)
        debris_factor = self.parameterAsDouble(parameters, self.DEBRIS_FACTOR, context)
        solid_ratio = self.parameterAsDouble(parameters, self.SOLID_VOLUME_RATIO, context)
        void_ratio = self.parameterAsDouble(parameters, self.VOID_RATIO, context)
        density = self.parameterAsDouble(parameters, self.DEBRIS_DENSITY, context)
        clear_width = self.parameterAsDouble(parameters, self.MIN_CLEAR_WIDTH, context)
        runs = self.parameterAsInt(parameters, self.SIMULATIONS, context)
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
        pga_idx = buildings.fields().lookupField(pga_field) if pga_field else -1

        n = len(b_feats)
        floors = np.ones(n, dtype=np.float64)
        years = np.full(n, 2000.0, dtype=np.float64)
        areas = np.zeros(n, dtype=np.float64)
        pga_raw = np.full(n, np.nan, dtype=np.float64)
        geoms = []
        for i, f in enumerate(b_feats):
            g = f.geometry().makeValid()
            geoms.append(g)
            areas[i] = g.area()
            attributes = f.attributes()
            if floor_idx >= 0:
                floors[i] = _float_or(attributes[floor_idx], 1.0)
            if year_idx >= 0:
                years[i] = _float_or(attributes[year_idx], 2000.0)
            if pga_idx >= 0:
                pga_raw[i] = _float_or(attributes[pga_idx], np.nan)

        heights = floors * floor_height
        levels = seismic.design_level(years)
        labels = seismic.resolve_building_type(building_type, floors)

        nominal_pga = seismic.effective_pga(magnitude, reference_pga)
        if pga_idx >= 0:
            usable = np.isfinite(pga_raw) & (pga_raw > 0.0)
            intensity = np.where(usable, pga_raw, nominal_pga)
            n_missing = int(n - np.count_nonzero(usable))
            feedback.pushInfo(
                f"Hazard: PGA field '{pga_field}' drives the fragility"
                + (f"; {n_missing} building(s) without a usable value fell back to the "
                   f"Mw {magnitude:g} nominal {nominal_pga:.3f} g." if n_missing else ".")
            )
        else:
            intensity = nominal_pga
            feedback.pushInfo(
                f"Hazard: no PGA field given - using the nominal Mw {magnitude:g} ground motion "
                f"of {nominal_pga:.3f} g (reference PGA {reference_pga:.3f} g at Mw 7.0). This "
                "fallback has no distance, site or fault term; join a PGA raster for real results."
            )

        probabilities = seismic.damage_probabilities(intensity, levels, labels)
        state_index = seismic.sample_damage_state(seed, probabilities)
        state_factor = seismic.material_factor(state_index)
        radius, solid, pile, mass = seismic.debris_extent(
            heights, areas, state_factor, debris_factor, solid_ratio, void_ratio, density)
        collapsed = state_index == len(seismic.DAMAGE_STATES) - 1

        collapse_freq = None
        if runs > 0:
            frequency = np.zeros(n, dtype=np.float64)
            blocked_samples = []
            for run in range(runs):
                if feedback.isCanceled():
                    break
                run_states = seismic.sample_damage_state(seed + run, probabilities)
                frequency += (run_states == len(seismic.DAMAGE_STATES) - 1).astype(np.float64)
                run_debris = self._debris_geometry(
                    geoms, seismic.debris_extent(
                        heights, areas, seismic.material_factor(run_states),
                        debris_factor, solid_ratio, void_ratio, density)[0])
                envelope = QgsGeometry.unaryUnion(run_debris).makeValid() if run_debris else None
                blocked_samples.append(0.0 if envelope is None else self._blocked_area(
                    network_union.intersection(envelope).makeValid()))
                feedback.setProgress(int((run + 1) / runs * 70))
            collapse_freq = frequency / max(1, runs)
            summary = uncertainty.summarize_samples(np.asarray(blocked_samples, dtype=np.float64))
            feedback.pushInfo(
                f"Simulation runs: {runs} seeds from {seed}. Blocked street area (m2) - "
                f"mean {summary['mean']:.1f}, sd {summary['std']:.1f}, "
                f"p05 {summary['p05']:.1f}, p50 {summary['p50']:.1f}, p95 {summary['p95']:.1f}."
            )

        out_fields = self.output_fields(buildings.fields())
        sink_buildings, dest_buildings = self.parameterAsSink(
            parameters, self.OUT_BUILDINGS, context, out_fields, QgsWkbTypes.Type.Point, target_crs)

        n_base = len(buildings.fields())
        n_navigable = 0
        for i, f in enumerate(b_feats):
            if feedback.isCanceled():
                break
            out_feat = QgsFeature(out_fields)
            out_feat.setGeometry(geoms[i].centroid())
            out_feat.setAttributes(list(f.attributes())[:n_base] + [
                float(heights[i]), float(probabilities["complete"][i]), int(collapsed[i]),
                seismic.DAMAGE_STATES[int(state_index[i])],
                float(radius[i]), float(solid[i]), float(pile[i]), float(mass[i]),
                None if collapse_freq is None else float(collapse_freq[i]),
            ])
            sink_buildings.addFeature(out_feat, QgsFeatureSink.Flag.FastInsert)
            feedback.setProgress(int((i + 1) / n * 100))

        results = {self.OUT_BUILDINGS: dest_buildings}

        sink_envelope, dest_envelope = self.parameterAsSink(
            parameters, self.OUT_ENVELOPE, context, QgsFields(), QgsWkbTypes.Type.MultiPolygon, target_crs)
        sink_blocked, dest_blocked = self.parameterAsSink(
            parameters, self.OUT_BLOCKED, context, QgsFields(), QgsWkbTypes.Type.MultiPolygon, target_crs)
        sink_corridors, dest_corridors = self.parameterAsSink(
            parameters, self.OUT_CORRIDORS, context, QgsFields(), QgsWkbTypes.Type.MultiPolygon, target_crs)
        sink_navigable, dest_navigable = self.parameterAsSink(
            parameters, self.OUT_NAVIGABLE, context, QgsFields(), QgsWkbTypes.Type.MultiPolygon, target_crs)

        debris_geoms = self._debris_geometry(geoms, radius)
        blocked = None
        if debris_geoms:
            envelope = QgsGeometry.unaryUnion(debris_geoms).makeValid()
            env_feat = QgsFeature()
            env_feat.setGeometry(envelope)
            sink_envelope.addFeature(env_feat, QgsFeatureSink.Flag.FastInsert)

            blocked = network_union.intersection(envelope).makeValid()
            if not blocked.isEmpty():
                blk_feat = QgsFeature()
                blk_feat.setGeometry(blocked)
                sink_blocked.addFeature(blk_feat, QgsFeatureSink.Flag.FastInsert)

            corridors = network_union.difference(blocked).makeValid()
        else:
            corridors = network_union

        if not corridors.isEmpty():
            cor_feat = QgsFeature()
            cor_feat.setGeometry(corridors)
            sink_corridors.addFeature(cor_feat, QgsFeatureSink.Flag.FastInsert)
            navigable = self._navigable_core(corridors, clear_width)
            if not navigable.isEmpty():
                n_navigable = 1
                nav_feat = QgsFeature()
                nav_feat.setGeometry(navigable)
                sink_navigable.addFeature(nav_feat, QgsFeatureSink.Flag.FastInsert)

        results[self.OUT_ENVELOPE] = dest_envelope
        results[self.OUT_BLOCKED] = dest_blocked
        results[self.OUT_CORRIDORS] = dest_corridors
        results[self.OUT_NAVIGABLE] = dest_navigable

        n_collapsed = int(np.sum(collapsed))
        feedback.pushInfo(
            f"Mw {magnitude:g} scenario (seed {seed}): {n_collapsed}/{n} buildings in complete "
            f"damage, {float(np.sum(solid)):.1f} m3 of material in {float(np.sum(pile)):.1f} m3 "
            f"of pile ({float(np.sum(mass)) / 1000.0:.2f} kt)."
        )
        if n_navigable:
            corridor_area = float(corridors.area())
            navigable_area = float(navigable.area())
            feedback.pushInfo(
                f"Navigable core: corridors opened at {clear_width:g} m clear width - "
                f"{navigable_area:.1f} m2 of street stays reachable where the open corridors "
                f"covered {corridor_area:.1f} m2, a difference of "
                f"{corridor_area - navigable_area:.1f} m2 pinched below vehicle width."
            )
        else:
            feedback.pushInfo(
                f"Navigable core: no street left at {clear_width:g} m clear width - every corridor "
                "is narrower than an emergency vehicle once debris is down. Lower the minimum clear "
                "width, or widen the study-area streets."
            )

        return results

    @staticmethod
    def _navigable_core(corridors, clear_width):
        """Corridors narrowed to the minimum clear width.

        Morphological opening - erode by half the clear width, then regrow by
        the same amount - which drops every part of the network too narrow for
        the gap to survive the erosion. A 0.5 m sliver left beside a debris
        pile stops counting as an evacuation route.
        """
        half = float(clear_width) / 2.0
        if half <= 0.0:
            return corridors
        return corridors.buffer(-half, 8).buffer(half, 8).makeValid()

    def createInstance(self):
        return SeismicDebrisAlgorithm()
