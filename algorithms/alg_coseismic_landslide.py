# -*- coding: utf-8 -*-
"""Coseismic Landslide Screening: where will the ground slide, and how far?

One model, one chain, three ways to get the number it starts from:

* **Jibson (2007) Equation 7** - the Newmark-displacement regression. Given a
  critical acceleration, the peak ground acceleration and the magnitude, it
  returns the distance a slope is expected to move.
* **Hazus 6.1 Section 4.2.2.2** - three routes to the critical acceleration
  that regression needs, because almost nobody has one as a layer: the manual's
  geological group route, its susceptibility-category route, or a column of
  critical accelerations the user brings.

The engineering is in ``engine/landslide.py``; this module is the QGIS surface.
Both models are described by their source tables there, not here.
"""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureSink,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterLayer,
)

from .base import DOUBLE, GROUP_SEISMIC, PlanXAlgorithm, STRING
from ._raster import read_dsm
from ..engine import hydro
from ..engine import landslide as ls

#: The three routes to a critical acceleration. Index 0 is a sentinel, not a
#: route: the three consume completely different inputs and carry different
#: provenance - one is a geotechnical measurement, one is a table lookup off a
#: geological map, one is a table lookup off somebody else's susceptibility map
#: - so the run log has to be able to say which one produced the number the
#: displacement was computed from. Picking one silently would be picking the
#: answer (rule R3).
AC_SOURCE_OPTIONS = (
    "Choose - this tool does not assume a critical acceleration for you",
    "Field - a critical-acceleration column in g, from your own geotechnical work",
    "Geologic group - Hazus 6.1 Tables 4-14 to 4-17, from a Group A/B/C column",
    "Susceptibility category - Hazus 6.1 Tables 4-16 and 4-17, from a category column",
)

AC_SOURCE_SENTINEL = 0
AC_SOURCE_FIELD = 1
AC_SOURCE_GROUP = 2
AC_SOURCE_CATEGORY = 3

#: Dry or wet, Hazus Table 4-14's two groundwater states. Index 0 is a sentinel
#: for the same reason: a third of the table's cells change between them, and
#: the manual names two physical conditions rather than offering an
#: intermediate.
MOISTURE_OPTIONS = (
    "Choose - this tool does not assume a groundwater state for you",
    "Dry - groundwater below the level of the slide (Hazus Table 4-14a)",
    "Wet - groundwater level at the ground surface (Hazus Table 4-14b)",
)

MOISTURE_SENTINEL = 0
MOISTURE_DRY = 1
MOISTURE_WET = 2
MOISTURE_NAMES = ("dry", "wet")


class CoseismicLandslideAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_SEISMIC
    ICON = "tool_coseismiclandslide.png"
    #: Named explicitly rather than left to the renderer's preference list,
    #: which contains no token any of these columns carries: without this the
    #: tool would write a correct table with no colour scale at all, and the
    #: next column added would not change that.
    RENDER_FIELD = "nw_disp_cm"

    AC_SOURCE = "AC_SOURCE"
    AC_FIELD = "AC_FIELD"
    GROUP_FIELD = "GROUP_FIELD"
    CATEGORY_FIELD = "CATEGORY_FIELD"
    MOISTURE = "MOISTURE"
    TERRAIN = "TERRAIN"
    TARGET = "TARGET"
    PGA_G = "PGA_G"
    PGA_FIELD = "PGA_FIELD"
    MAGNITUDE = "MAGNITUDE"
    OUTPUT = "OUTPUT"

    def name(self):
        return "coseismiclandslide"

    def displayName(self):
        return self.tr("Coseismic Landslide Screening")

    def shortHelpString(self):
        return self.tr(
            "Where is a slope likely to fail in an earthquake, and how far "
            "will it move? A Newmark sliding-block calculation, driven by the "
            "shaking you already have from the seismic chain.\n\n"
            "THE DISPLACEMENT - Jibson (2007), Engineering Geology 91(2-4), "
            "209-218, Equation 7: "
            "log D = -2.71 + log[(1 - a_c/PGA)^2.335 (a_c/PGA)^-1.478] + 0.424 M "
            "with D in centimetres, a_c and PGA in g and M the moment "
            "magnitude. This is the form of the paper that carries a magnitude "
            "term and needs no Arias intensity, so it runs on exactly the two "
            "quantities Ground Motion Scenario and the Mw box already give you. "
            "Its dispersion is 0.454 in log10 units, which is why the output "
            "carries a 90th percentile beside the median: a median displacement "
            "with no spread looks like a measurement, and this is a "
            "distribution.\n\n"
            "Jibson describes the regression as a tool for regional-scale "
            "screening and rapid preliminary assessment, not for site-specific "
            "design. That is exactly what this is. It is not a slope stability "
            "analysis, it does not know about your retaining walls, and a "
            "result of zero centimetres is not a certificate that a slope is "
            "stable.\n\n"
            "THE CRITICAL ACCELERATION - the number the regression needs and "
            "the number almost nobody has. Pick one of three routes; the tool "
            "will not pick for you, and 'ac_src' on every row records which "
            "route produced the value:\n"
            "- FIELD: a column of critical accelerations in g. This is the "
            "best route whenever you have it, because it is your data rather "
            "than an inference from a map unit.\n"
            "- GEOLOGIC GROUP: Hazus 6.1 Section 4.2.2.2, Tables 4-14 to 4-17. "
            "Name a column holding the group letter A (strongly cemented "
            "rocks, c' = 300 psf, Phi' = 35 degrees), B (weakly cemented rocks "
            "and soils, c' = 0, Phi' = 35) or C (argillaceous rocks, c' = 0, "
            "Phi' = 20), and choose the groundwater state. The group letter "
            "and the slope angle together give a susceptibility category, the "
            "category gives the critical acceleration, and Table 4-17 gives "
            "the fraction of that map unit Hazus expects to be susceptible "
            "deposit at all - reported separately, never folded into the "
            "displacement.\n"
            "- SUSCEPTIBILITY CATEGORY: you already have somebody's landslide "
            "susceptibility map, categorised I to X. Table 4-16 gives the "
            "acceleration. Roman numerals only: a numeric column would not say "
            "whether 1 meant the least susceptible, as Hazus counts it, or the "
            "most, and guessing wrong reverses the whole map.\n\n"
            "A GROUP ROUTE IS AN INFERENCE, and Hazus says so itself: it states "
            "that no generally accepted relationship for estimating a_c has "
            "been developed, and describes the one it uses as conservative, "
            "representing the most susceptible material likely to be in the "
            "group. If you have real strength data, use the field route.\n\n"
            "THE TERRAIN is required in all three routes, because the slope "
            "angle is as much part of reading the answer as the acceleration "
            "is: a 20 centimetre displacement on a 3 degree slope and the same "
            "displacement on a 35 degree slope are different problems. Slope "
            "is measured with the same D8 steepest-descent pass the wetness "
            "index uses, and is sampled at the feature's point on its surface. "
            "On a large map unit that is a point sample of a large unit - a "
            "parcel whose point on surface lands on the flat bench above the "
            "scarp will read as not susceptible, so clip your units to "
            "terrain-homogeneous areas or evaluate them separately.\n\n"
            "How to read the results\n"
            "- nw_disp_cm is the median displacement in centimetres and "
            "nw_disp_p90_cm is the 90th percentile of the same prediction: "
            "10^(1.2816 x 0.454) = 3.8 times the median. They are a "
            "distribution, not a range of confidence about one true value.\n"
            "- ac_ratio is a_c divided by PGA and it is the number the "
            "regression actually turns on. At or above 1.0 the block does not "
            "move and the displacement is zero - that is the model's answer, "
            "not a missing value, and ls_notes says so on the row. Below 0.05 "
            "the second term of the equation grows without bound, so a large "
            "number there is an extrapolation and the row says that too.\n"
            "- A zero can also mean Hazus assigned no landslide-susceptible "
            "deposit at all, because the slope is below the group's lower "
            "bound. That case has an empty ac_g rather than a zero, so the two "
            "kinds of zero are distinguishable in the file.\n"
            "- ls_area_frac is the Table 4-17 fraction of the map unit Hazus "
            "expects to be susceptible deposit. It is not a probability that "
            "the slope moves and it is not multiplied into the displacement.\n"
            "- UNCALIBRATED for Turkiye, and for everywhere outside the United "
            "States: both models are US calibrations and no Turkish landslide "
            "inventory was used to fit or to check them. They rank places "
            "against each other; they do not predict what will happen at a "
            "given address.\n"
            "- This is a screening tool for planning. It is not a substitute "
            "for a geotechnical investigation, and it is not a code check.\n\n"
            "Using the results: rank districts by nw_disp_cm to decide where a "
            "slope stability campaign is worth paying for; use nw_disp_p90_cm "
            "rather than the median when deciding what infrastructure to "
            "protect, because a plan built on the median is wrong half the "
            "time; overlay it on the debris, casualty and liquefaction layers, "
            "because a hillside district that is high on all four is where the "
            "hazards compound and the response network those tools plan has to "
            "reach ground that may have moved. Run it at two shaking levels: a "
            "slope that only moves at the strongest scenario is a different "
            "kind of problem from one that is already moving at the weakest."
        )

    # ------------------------------------------------------------------ #
    # Parameters
    # ------------------------------------------------------------------ #
    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterEnum(
            self.AC_SOURCE, self.tr("Critical acceleration from (see help; no "
                                    "default)"),
            options=[self.tr(text) for text in AC_SOURCE_OPTIONS],
            defaultValue=AC_SOURCE_SENTINEL))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.TARGET,
            self.tr("Layer to evaluate (any geometry; one sample per feature)"),
            [QgsProcessing.SourceType.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.TERRAIN,
            self.tr("Terrain DEM - drives the slope angle, which is required in "
                    "every route")))
        self.addParameter(QgsProcessingParameterField(
            self.AC_FIELD,
            self.tr("Critical acceleration field, g (field route: required)"),
            parentLayerParameterName=self.TARGET, optional=True,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterField(
            self.GROUP_FIELD,
            self.tr("Geologic group field, A/B/C (geologic-group route: "
                    "required)"),
            parentLayerParameterName=self.TARGET, optional=True,
            type=QgsProcessingParameterField.DataType.String))
        self.addParameter(QgsProcessingParameterField(
            self.CATEGORY_FIELD,
            self.tr("Susceptibility category field, I to X (category route: "
                    "required)"),
            parentLayerParameterName=self.TARGET, optional=True,
            type=QgsProcessingParameterField.DataType.String))
        self.addParameter(QgsProcessingParameterEnum(
            self.MOISTURE,
            self.tr("Groundwater state (geologic-group route; no default - see "
                    "help)"),
            options=[self.tr(text) for text in MOISTURE_OPTIONS],
            defaultValue=MOISTURE_SENTINEL))
        self.addParameter(QgsProcessingParameterNumber(
            self.PGA_G, self.tr("PGA, g (constant; a field overrides it)"),
            QgsProcessingParameterNumber.Type.Double, 0.0,
            minValue=0.0, maxValue=5.0))
        self.addParameter(QgsProcessingParameterField(
            self.PGA_FIELD, self.tr("PGA field, g (optional; wins over the "
                                    "constant)"),
            parentLayerParameterName=self.TARGET, optional=True,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.MAGNITUDE, self.tr("Moment magnitude (Mw)"),
            QgsProcessingParameterNumber.Type.Double, 7.5,
            minValue=3.0, maxValue=9.5))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Landslide screening")))

    # ------------------------------------------------------------------ #
    # Output schema
    # ------------------------------------------------------------------ #
    @staticmethod
    def output_fields(base=None):
        """The columns appended to the incoming schema, in order.

        One schema for all three routes, with the columns a route does not
        compute left empty rather than absent. A saved Processing model that
        reads ``nw_disp_cm`` keeps working when the route changes; a model that
        reads a column that is empty can see that it is empty, which a missing
        column cannot tell it.
        """
        return PlanXAlgorithm.make_fields(
            ("nw_disp_cm", DOUBLE),
            ("nw_disp_p90_cm", DOUBLE),
            ("ls_log_disp", DOUBLE),
            ("ac_g", DOUBLE),
            ("ac_src", STRING),
            ("ac_ratio", DOUBLE),
            ("ls_category", STRING),
            ("ls_area_frac", DOUBLE),
            ("pga_g", DOUBLE),
            ("mw", DOUBLE),
            ("slope_deg", DOUBLE),
            ("ls_notes", STRING),
            base=base,
        )

    # ------------------------------------------------------------------ #
    # Input resolution
    # ------------------------------------------------------------------ #
    @staticmethod
    def _numeric(value):
        """A finite float from a QVariant, or None."""
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if np.isfinite(number) else None

    def _column(self, fields, parameter, context, parameters, label):
        """Field index for a parameter that names a column, -1 when unset."""
        name = self.parameterAsString(parameters, parameter, context)
        if not name:
            return -1, ""
        index = fields.indexFromName(name)
        if index < 0:
            raise QgsProcessingException(
                f"The {label} field '{name}' is not in the layer. Pick a "
                "column that is there, or leave the field empty.")
        return index, name

    def _pga(self, features, index, name, constant, feedback):
        """PGA in g per feature, refusing rather than substituting.

        Same contract as the liquefaction screen, and for the same reason: the
        regression is a function of ``a_c / PGA``, so there is no reference
        shaking level to fall back on and a substituted one would move the
        answer by whatever factor it happened to be.
        """
        if index < 0:
            if not constant > 0.0:
                raise QgsProcessingException(
                    "No shaking level was given: neither a PGA field nor a "
                    "non-zero PGA constant. The displacement is a function of "
                    "a_c/PGA - with no shaking there is no slope movement to "
                    "predict, and a zero here is not a result. Use Ground "
                    "Motion Scenario to compute a PGA field, or type a "
                    "scenario PGA.")
            feedback.pushInfo(
                f"Shaking: a constant PGA of {constant:g} g for every feature. "
                "One shaking level for a whole city is a scenario assumption, "
                "not a measurement.")
            return [constant] * len(features)
        values, empty = [], 0
        for feature in features:
            number = self._numeric(feature.attributes()[index])
            if number is None or number <= 0.0:
                empty += 1
            values.append(number)
        if empty:
            raise QgsProcessingException(
                f"{empty} feature(s) have no usable PGA in the '{name}' column, "
                "and the displacement is a function of a_c/PGA. There is no "
                "reference shaking level to fall back to, so substituting one "
                "would move the answer by orders of magnitude. Fill those rows "
                "(Ground Motion Scenario writes this column), or clear the "
                "field to use the constant instead.")
        return values

    # ------------------------------------------------------------------ #
    # Run
    # ------------------------------------------------------------------ #
    def processAlgorithm(self, parameters, context, feedback):
        self._parameters, self._context = parameters, context
        try:
            return self._run(parameters, context, feedback)
        finally:
            self._parameters = self._context = None

    def _run(self, parameters, context, feedback):
        route = self.parameterAsEnum(parameters, self.AC_SOURCE, context)
        if route == AC_SOURCE_SENTINEL:
            raise QgsProcessingException(
                "Choose where the critical acceleration comes from. The three "
                "routes consume different inputs and carry different "
                "provenance - the field route is your own geotechnical data, "
                "the geologic-group route is a table lookup off a geological "
                "map, and the category route is a table lookup off somebody "
                "else's susceptibility map. The tool will not pick one for you.")

        target = self.parameterAsSource(parameters, self.TARGET, context)
        if target is None:
            raise QgsProcessingException("Please provide a layer to evaluate.")
        self.require_projected(target, "The layer to evaluate")

        terrain_layer = self.parameterAsRasterLayer(
            parameters, self.TERRAIN, context)
        if terrain_layer is None:
            raise QgsProcessingException(
                "A terrain DEM is required in every route: the slope angle is "
                "part of reading any of these displacements, and the "
                "geologic-group route takes its susceptibility category from "
                "the slope as much as from the group.")

        magnitude = self.parameterAsDouble(parameters, self.MAGNITUDE, context)
        pga_constant = self.parameterAsDouble(parameters, self.PGA_G, context)

        fields = target.fields()
        pga_index, pga_name = self._column(
            fields, self.PGA_FIELD, context, parameters, "PGA")
        ac_index, ac_name = self._column(
            fields, self.AC_FIELD, context, parameters, "critical acceleration")
        group_index, group_name = self._column(
            fields, self.GROUP_FIELD, context, parameters, "geologic group")
        category_index, category_name = self._column(
            fields, self.CATEGORY_FIELD, context, parameters, "susceptibility "
            "category")

        moisture = ""
        if route == AC_SOURCE_GROUP:
            state = self.parameterAsEnum(parameters, self.MOISTURE, context)
            if state == MOISTURE_SENTINEL:
                raise QgsProcessingException(
                    "Choose the groundwater state. It changes a third of the "
                    "cells of Hazus Table 4-14, and at the same slope and "
                    "geologic group the dry and wet columns are up to four "
                    "susceptibility categories apart - which is a factor of "
                    "eight in the critical acceleration. The tool will not "
                    "pick one for you.")
            moisture = MOISTURE_NAMES[state - MOISTURE_DRY]
            if group_index < 0:
                raise QgsProcessingException(
                    "The geologic-group route needs a column holding the group "
                    "letter A, B or C (Hazus Table 4-14). Name one, or switch "
                    "to the field route if you have critical accelerations of "
                    "your own, or to the category route if you have a "
                    "susceptibility map already classified I to X. A missing "
                    "geological map is not a missing hazard: filling in a group "
                    "on the user's behalf would be inventing a shear strength.")
        elif route == AC_SOURCE_CATEGORY and category_index < 0:
            raise QgsProcessingException(
                "The susceptibility-category route needs a column holding a "
                "category from I to X (Hazus Table 4-16). Name one, or switch "
                "to the field route if you have critical accelerations of your "
                "own, or to the geologic-group route if you have a geological "
                "map instead.")
        elif route == AC_SOURCE_FIELD and ac_index < 0:
            raise QgsProcessingException(
                "The field route needs a column of critical accelerations in "
                "g. Name one, or switch to a Hazus route to have the tool "
                "derive one from a geological or susceptibility map. A zero "
                "critical acceleration has no finite displacement, so there is "
                "nothing this tool could substitute.")

        features = [f for f in target.getFeatures() if f.hasGeometry()]
        if not features:
            raise QgsProcessingException(
                "No usable features found in the layer to evaluate.")
        feedback.pushInfo(
            f"{len(features)} feature(s) evaluated; Mw {magnitude:g}, "
            f"critical acceleration from the "
            f"{ls_source_label(route)} route.")

        pga_values = self._pga(features, pga_index, pga_name, pga_constant,
                               feedback)
        conditions = self._site_conditions(
            route, features, moisture, ac_index, ac_name, group_index,
            group_name, category_index, category_name)
        rows = self._evaluate(
            route, context, feedback, terrain_layer, target, features,
            pga_values, magnitude, conditions, moisture, ac_name)

        out_fields = self.output_fields(fields)
        sink, dest = self.parameterAsSink(
            parameters, self.OUTPUT, context, out_fields, target.wkbType(),
            target.sourceCrs())
        if sink is None:
            raise QgsProcessingException("Could not create the output layer.")

        n_base = len(fields)
        for index, feature in enumerate(features):
            if feedback.isCanceled():
                break
            out_feature = QgsFeature(out_fields)
            out_feature.setGeometry(feature.geometry())
            out_feature.setAttributes(
                list(feature.attributes())[:n_base] + rows[index])
            sink.addFeature(out_feature, QgsFeatureSink.Flag.FastInsert)
            feedback.setProgress(int((index + 1) / len(features) * 100))
        return {self.OUTPUT: dest}

    # ------------------------------------------------------------------ #
    # The chain
    # ------------------------------------------------------------------ #
    def _site_conditions(self, route, features, moisture, ac_index, ac_name,
                         group_index, group_name, category_index,
                         category_name):
        """One ``(kind, value)`` per feature, or a refusal.

        Every value the model cannot read is collected here and refused before
        a single output row exists, rather than skipped row by row: a hazard
        map missing the rows the model could not read says those places are
        safe, which is the one thing this family of tools must never say by
        accident. The returned list is aligned with ``features`` - that
        alignment is why the refusal cannot be a ``continue`` inside the
        writing loop.
        """
        conditions = []
        groups: dict[str, int] = {}
        categories: dict[str, int] = {}
        bad_ac = 0
        for feature in features:
            if route == AC_SOURCE_GROUP:
                raw = feature.attributes()[group_index]
                group = ls.normalise_group(raw)
                if group is None:
                    groups[str(raw)] = groups.get(str(raw), 0) + 1
                    conditions.append(None)
                    continue
                conditions.append(("group", group))
            elif route == AC_SOURCE_CATEGORY:
                raw = feature.attributes()[category_index]
                category = ls.normalise_susceptibility(raw)
                if category is None:
                    categories[str(raw)] = categories.get(str(raw), 0) + 1
                    conditions.append(None)
                    continue
                conditions.append(("category", category))
            else:
                ac_g = self._numeric(feature.attributes()[ac_index])
                if ac_g is None or ac_g <= 0.0:
                    bad_ac += 1
                    conditions.append(None)
                    continue
                conditions.append(("ac", ac_g))
        if groups or categories or bad_ac:
            self._refuse(groups, categories, bad_ac, ac_name, group_name,
                         category_name)
        return conditions

    def _evaluate(self, route, context, feedback, terrain_layer, target,
                  features, pga_values, magnitude, conditions, moisture,
                  ac_name):
        dem, gt, _proj, pixel = read_dsm(terrain_layer)
        # The pixel is deliberately left in the DEM's own CRS units rather than
        # converted to metres the way the wetness index converts it. A slope is
        # a ratio of a vertical difference to a horizontal one, so it is only
        # right when both are in one unit; GDAL records no vertical unit, and
        # converting the horizontal one alone would silently rescale every
        # slope on a DEM whose elevation is in feet. Reading both in the CRS's
        # units is the assumption-free choice, and the run log states it.
        feedback.pushInfo(
            f"Terrain: a {dem.shape[1]}x{dem.shape[0]} DEM at {pixel:g} "
            "CRS unit(s) per cell. Slope is the D8 steepest-descent gradient - "
            "the same pass the wetness index uses - so it is the steepest of "
            "the eight neighbours rather than a 3x3 plane fit, and it assumes "
            "the DEM's elevations are in the same unit as its coordinates. A "
            "DEM whose vertical unit differs from its horizontal one has every "
            "slope off by that ratio.")
        slope_grid = np.degrees(hydro.slope_radians(dem, pixel))

        dem_crs = terrain_layer.crs()
        transform = None
        if target.sourceCrs() != dem_crs:
            transform = QgsCoordinateTransform(
                target.sourceCrs(), dem_crs, context.transformContext())

        rows = []
        sources: dict[str, int] = {}
        slope_samples: list[float] = []
        below_bound = floor_applied = not_moving = extrapolated = 0
        displacements: list[float] = []

        for index, feature in enumerate(features):
            if feedback.isCanceled():
                break
            point = feature.geometry().pointOnSurface().asPoint()
            slope_deg = self._sample(slope_grid, gt, transform, point)
            if slope_deg is None or not np.isfinite(slope_deg):
                raise QgsProcessingException(
                    f"Feature {index + 1} falls outside the terrain DEM, or on "
                    "a nodata cell, so it has no slope angle. A missing "
                    "terrain input is not a missing hazard - clip the layer to "
                    "the DEM, or enlarge the DEM.")
            slope_samples.append(slope_deg)

            kind, value = conditions[index]
            category = None
            area_fraction = None
            floor = False
            group = None
            if kind == "group":
                group = value
                result = ls.hazus_susceptibility(group, moisture, slope_deg)
                category = result["category"]
                area_fraction = result["area_fraction"]
                ac_g = result["ac_g"]
                floor = result["floor_applied"]
                below_bound += 1 if result["below_bound"] else 0
                source = f"hazus:{group}:{moisture}:{category}"
            elif kind == "category":
                category = value
                area_fraction = ls.HAZUS_LANDSLIDE_AREA_FRACTION[category]
                ac_g = ls.HAZUS_LANDSLIDE_AC_G.get(category)
                source = f"hazus-cat:{category}"
            else:
                ac_g = value
                source = f"field:{ac_name}"
            if floor:
                source += ":floor"
            floor_applied += 1 if floor else 0
            sources[source] = sources.get(source, 0) + 1

            pga = pga_values[index]
            if ac_g is None:
                # Hazus assigns no susceptible deposit here. The acceleration
                # is left empty rather than zeroed, because zero is the value
                # the regression diverges on - the safest answer in the model
                # must not arrive looking like its loudest.
                rows.append([
                    0.0, 0.0, None, None, source, None, category,
                    area_fraction, float(pga), float(magnitude),
                    float(slope_deg),
                    "Hazus assigns no landslide-susceptible deposit on this "
                    "map unit: the slope is below the group's lower bound of "
                    f"{ls.HAZUS_LANDSLIDE_SLOPE_BOUND_DEG[(group, moisture)]:g} "
                    "degrees for this geologic group and groundwater state. "
                    "Zero displacement here means the model never started, not "
                    "that the slope was computed to be stable",
                ])
                continue

            try:
                moving_result = ls.jibson_displacement(ac_g, pga, magnitude)
            except ValueError as error:
                raise QgsProcessingException(
                    f"Feature {index + 1}: {error}") from error

            notes = list(moving_result["notes"])
            if floor:
                notes.append(
                    f"a_c was held at the Table 4-15 lower bound of "
                    f"{ls.HAZUS_LANDSLIDE_AC_BOUND_G[(group, moisture)]:g} g "
                    "for this group and groundwater state; the category's own "
                    "Table 4-16 value is lower")
            if moving_result["moving"]:
                displacements.append(moving_result["disp_cm"])
            else:
                not_moving += 1
            extrapolated += 1 if any(
                "grows without bound" in note for note in notes) else 0

            rows.append([
                float(moving_result["disp_cm"]),
                float(moving_result["p90_cm"]),
                (None if moving_result["log10_disp"] is None
                 else float(moving_result["log10_disp"])),
                float(ac_g),
                source,
                float(moving_result["ratio"]),
                category,
                area_fraction,
                float(pga), float(magnitude), float(slope_deg),
                "; ".join(notes),
            ])

        self._report(feedback, route, moisture, sources, slope_samples,
                     displacements, below_bound, floor_applied, not_moving,
                     extrapolated, magnitude)
        return rows

    def _refuse(self, groups, categories, bad_ac, ac_name, group_name,
                category_name):
        """Refuse a column the model cannot read, naming what was found.

        These are all the same refusal: a value the model does not define. It
        is raised rather than skipped because every one of them has a
        plausible-looking wrong reading - an unrecognised group could be taken
        as the least susceptible, an unrecognised category as zero, a zero
        acceleration as a stable slope - and a row silently dropped from a
        hazard map reads as a row with no hazard.
        """
        parts = []
        if groups:
            listed = ", ".join(
                f"'{key}' x{count}" for key, count in sorted(groups.items()))
            parts.append(
                f"the geologic group column '{group_name}' holds value(s) this "
                f"model does not define: {listed}. Hazus Table 4-14 defines "
                "three groups - A (strongly cemented rocks), B (weakly "
                "cemented rocks and soils) and C (argillaceous rocks) - and "
                "'ac_src' records which one each row used. A group the tool "
                "guessed at would be a shear strength it invented.")
        if categories:
            listed = ", ".join(
                f"'{key}' x{count}" for key, count in sorted(categories.items()))
            parts.append(
                f"the susceptibility category column '{category_name}' holds "
                f"value(s) this model does not define: {listed}. Hazus Table "
                "4-16 defines the Roman numerals I to X - I the least "
                "susceptible - plus the word None. Digits are refused on "
                "purpose: Hazus counts up from the least susceptible, and a "
                "numeric column was as likely written the other way round.")
        if bad_ac:
            parts.append(
                f"{bad_ac} feature(s) have no positive critical acceleration in "
                f"'{ac_name}'. A critical acceleration of zero sends the "
                "regression's (a_c/a_max)^-1.478 term to infinity - a material "
                "with no strength to mobilise is a flow rather than a slope, "
                "and that is the ground-failure question planx:liquefaction "
                "answers, not this one.")
        raise QgsProcessingException(
            "The run stopped because " + "; and ".join(parts)
            + ". Nothing was written: a hazard map missing the rows the model "
            "could not read is a map that says those places are safe.")

    @staticmethod
    def _sample(array, gt, transform, point):
        """Sample a grid at a point, or None when the point is off it."""
        x, y = point.x(), point.y()
        if transform is not None:
            transformed = transform.transform(x, y)
            x, y = transformed.x(), transformed.y()
        rows, cols = array.shape
        col = int((x - gt[0]) / gt[1])
        row = int((y - gt[3]) / gt[5])
        if not (0 <= row < rows and 0 <= col < cols):
            return None
        return float(array[row, col])

    def _report(self, feedback, route, moisture, sources, slope_samples,
                displacements, below_bound, floor_applied, not_moving,
                extrapolated, magnitude):
        spread = 10.0 ** (ls.NORMAL_P90_FACTOR * ls.JIBSON_2007_SIGMA)
        feedback.pushInfo(
            "Model: Jibson (2007) Equation 7, Engineering Geology 91(2-4), "
            "209-218 (log D = -2.71 + log[(1 - a_c/PGA)^2.335 "
            "(a_c/PGA)^-1.478] + 0.424 M, D in cm). Sigma is "
            f"{ls.JIBSON_2007_SIGMA} in log10 units, so the 90th percentile is "
            f"{spread:.2f} times the median.")
        feedback.pushInfo(
            "Critical acceleration route: " + ls_source_label(route)
            + (f", groundwater state '{moisture}'" if moisture else "")
            + ". Sources: "
            + ", ".join(f"{key} x{count}"
                        for key, count in sorted(sources.items()))
            + ". 'ac_src' on each row names the route, and for the Hazus "
            "routes the group, the groundwater state and the category.")
        if route == AC_SOURCE_GROUP:
            feedback.pushInfo(
                "The geologic-group route is an inference, not a measurement, "
                "and Hazus says so itself: it states that no generally "
                "accepted relationship for estimating a_c has been developed, "
                "and describes the one it uses as conservative - the most "
                "susceptible material likely to be in the group. A critical "
                "acceleration from your own strength data beats it.")
        if slope_samples:
            ordered = sorted(slope_samples)
            feedback.pushInfo(
                f"Slope angle sampled at each feature: min "
                f"{ordered[0]:.1f}, median {ordered[len(ordered) // 2]:.1f}, "
                f"max {ordered[-1]:.1f} degrees. The slope is as much part of "
                "reading a displacement as the acceleration is.")
        if below_bound:
            feedback.pushInfo(
                f"{below_bound} row(s) have no susceptible deposit at all: "
                "their slope is below the group's lower bound, so Hazus "
                "assigns category None and the displacement is zero with an "
                "empty 'ac_g'. That zero means the model never started, not "
                "that the slope was computed to be stable.")
        if floor_applied:
            feedback.pushInfo(
                f"{floor_applied} row(s) had a_c lifted to the Table 4-15 "
                "lower bound for their group and groundwater state. That bound "
                "changes exactly one cell of the two tables - group B, wet, "
                "above 40 degrees - and those rows say so in 'ls_notes'.")
        if not_moving:
            feedback.pushInfo(
                f"{not_moving} row(s) have a_c/PGA at or above 1.0: the block "
                "does not move and the displacement is zero. That is the "
                "model's answer rather than missing data, and it is the "
                "expected result for a stiff site under weak shaking.")
        if extrapolated:
            feedback.pushInfo(
                f"{extrapolated} row(s) have a_c/PGA below "
                f"{ls.JIBSON_LOW_RATIO:g}. The second term of the regression "
                "grows without bound as that ratio falls, so those numbers are "
                "extrapolations - they are reported as the equation gives them "
                "and not clipped, but they are not displacements a slope can "
                "be built on. Material with that little strength to mobilise "
                "is closer to a flow than to a slide.")
        if displacements:
            ordered = sorted(displacements)
            feedback.pushInfo(
                f"Displacement among the {len(displacements)} row(s) that "
                "move: "
                f"median {ordered[len(ordered) // 2]:.2f} cm, 90th percentile "
                f"{ordered[int(0.9 * (len(ordered) - 1))]:.2f} cm, maximum "
                f"{ordered[-1]:.2f} cm. 'nw_disp_cm' is the per-row median and "
                "'nw_disp_p90_cm' its 90th percentile.")
        feedback.pushInfo(
            f"{len(slope_samples)} row(s). UNCALIBRATED for Turkiye: this is a "
            "United States calibration and no Turkish landslide inventory was "
            "used to fit or to check it. It ranks places against each other; "
            "it does not predict what will happen at a given address. Jibson "
            "describes the regression as a screening and preliminary "
            "assessment tool, not a basis for site-specific design - and this "
            "is not a substitute for a geotechnical investigation."
        )

    def createInstance(self):
        return CoseismicLandslideAlgorithm()


def ls_source_label(route: int) -> str:
    """The route's name as the run log spells it."""
    return {
        AC_SOURCE_FIELD: "critical-acceleration field",
        AC_SOURCE_GROUP: "Hazus geologic group",
        AC_SOURCE_CATEGORY: "Hazus susceptibility category",
    }.get(route, f"unknown ({route})")
