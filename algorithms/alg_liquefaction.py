# -*- coding: utf-8 -*-
"""Liquefaction Screening: where is the ground likely to liquefy?

Two models behind one interface, because they answer the same planning
question from two different sets of inputs:

* **Regression** - Zhu et al. (2015). Needs a DEM (slope -> Vs30 and a
  wetness index) and a shaking level. Runs from layers a user has.
* **Susceptibility** - Hazus 6.1 Section 4.2.2.1. Needs a map-unit polygon
  layer somebody classified, and refuses to run without one (rule R7: a
  missing susceptibility map means no result, not no hazard).

The engineering is in ``engine/liquefaction.py``; this module is the QGIS
surface. Both models are described by their source tables there, not here.
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
    QgsUnitTypes,
    Qgis,
)

from .base import DOUBLE, GROUP_SEISMIC, PlanXAlgorithm, STRING
from ._raster import read_dsm
from ..engine import hydro
from ..engine import liquefaction as liq

#: Option text for the two modes. Kept in the tool rather than in the engine
#: because it is combo-box copy, not model vocabulary; the order must stay
#: aligned with MODE_REGRESSION / MODE_SUSCEPTIBILITY below.
MODE_OPTIONS = (
    "Regression - Zhu et al. (2015): from a DEM and a shaking level",
    "Susceptibility - Hazus 6.1: from a classified map-unit layer",
)

MODE_REGRESSION = 0
MODE_SUSCEPTIBILITY = 1

#: Option text for the tectonic setting. Index 0 is a sentinel, not a setting:
#: slope-to-Vs30 is a *choice*, and the two columns of the source table differ
#: by up to a factor of two in velocity at the same slope - about 3.3 logit
#: units here - so picking one silently would be picking the answer (rule R3).
TECTONIC_OPTIONS = (
    "Choose - this tool does not assume it for you",
    "Active tectonic - e.g. Turkiye, California (Allen & Wald Table 2)",
    "Stable continental - e.g. central Europe, eastern North America",
)

TECTONIC_SENTINEL = 0


def metres_per_unit(crs) -> float:
    """How many metres one of ``crs``'s linear units is.

    A DEM's pixel size is in its own CRS's units, and the wetness index takes
    the logarithm of an area - so a DEM in feet inflates CTI by ln(3.2808) =
    1.19 everywhere, which the Zhu CTI coefficient turns into ~0.42 logit
    units of pure unit error. Gradients are unit-free; catchments are not.
    """
    metres = float(QgsUnitTypes.fromUnitToUnitFactor(
        crs.mapUnits(), Qgis.DistanceUnit.Meters))
    if not metres > 0.0:
        raise QgsProcessingException(
            f"The DEM's CRS ({crs.authid()}) does not declare a linear unit, so "
            "its pixel size cannot be converted to metres. A wetness index is "
            "the log of a metric area; reproject the DEM to a projected CRS "
            "with a known unit.")
    return metres


class LiquefactionAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_SEISMIC
    ICON = "tool_liquefaction.png"
    #: liq_prob already contains the renderer's "prob" token, but it is named
    #: explicitly anyway: the next column added to this table is one rename
    #: away from silently taking the colour scale off the probability.
    RENDER_FIELD = "liq_prob"

    MODE = "MODE"
    DEM = "DEM"
    TARGET = "TARGET"
    CATEGORY_FIELD = "CATEGORY_FIELD"
    PGA_G = "PGA_G"
    PGA_FIELD = "PGA_FIELD"
    MAGNITUDE = "MAGNITUDE"
    TECTONIC = "TECTONIC"
    VS30_MS = "VS30_MS"
    VS30_FIELD = "VS30_FIELD"
    VS30_RASTER = "VS30_RASTER"
    GROUNDWATER_M = "GROUNDWATER_M"
    OUTPUT = "OUTPUT"

    def name(self):
        return "liquefaction"

    def displayName(self):
        return self.tr("Liquefaction Screening")

    def shortHelpString(self):
        return self.tr(
            "Where is the ground likely to liquefy in an earthquake, and by "
            "how much will it settle? Two models answer it from two different "
            "sets of inputs.\n\n"
            "REGRESSION (the default) - Zhu, Daley, Baise, Thompson, Wald & "
            "Knudsen (2015), Earthquake Spectra 31(3), 1813-1837 (its Table 3). "
            "A logistic regression on shaking, a wetness index and "
            "shear-wave velocity: it needs a DEM and a PGA, and nothing else. "
            "The wetness index (CTI) and the slope come out of one D8 pass on "
            "the DEM, and Vs30 comes from the slope through the table in USGS "
            "Open-File Report 2007-1357 (Allen & Wald 2007) - or from your own "
            "Vs30 field or raster, which is better if you have one.\n\n"
            "SUSCEPTIBILITY - Hazus 6.1 Earthquake Model Technical Manual, "
            "Section 4.2.2.1, Equations 4-9 to 4-11 and Tables 4-10 to 4-13. "
            "It needs a polygon layer of map units already classified as Very "
            "High / High / Moderate / Low / Very Low / None, and it produces "
            "the probability for each unit plus the expected settlement. This "
            "mode REFUSES to run without that layer: Hazus itself assumes no "
            "ground failure when it has no input, and an empty map of nowhere-"
            "liquefies is the most dangerous answer this family of tools can "
            "give. A category it does not recognise is refused too, rather "
            "than read as zero - 'very high' in any case is accepted, 'VH' and "
            "'1' are not.\n\n"
            "Shaking. Give PGA in g either as a constant or as a field. A "
            "field wins. A row whose PGA is empty or zero stops the run: the "
            "model takes ln(PGA), and there is no reference shaking level the "
            "way there is a reference velocity, so there is nothing honest to "
            "fall back to. Use Ground Motion Scenario to fill that field.\n\n"
            "The tectonic setting has no default. It decides how topographic "
            "slope maps to Vs30, and the two columns of the source table "
            "differ by up to a factor of two in velocity at the same slope - "
            "over 3 logit units here, which is not a rounding difference. "
            "The run log says which one was used, and whether it affected any "
            "row at all.\n\n"
            "How to read the results\n"
            "- liq_prob is a probability at the sampled point, not a loss and "
            "not a design level. liq_area_frac is 0.81 times it: the separate "
            "reading Zhu et al. (2017) publish for the proportion of *area* "
            "affected. That factor does not belong on the point probability, "
            "so the two are separate columns and neither can be mistaken for "
            "the other.\n"
            "- CTI and PGA are clipped to the ranges the coefficients were "
            "fitted on, and every row where a clip bit says so in liq_notes. A "
            "clipped row is not a wrong row, but it is a row where the model "
            "stopped being the model.\n"
            "- One sample per feature, taken at the feature's point on its "
            "surface. On a large map unit that is a point sample of a large "
            "unit; subdivide it if the terrain inside it varies.\n"
            "- In susceptibility mode, liq_settle_in is the probability times "
            "the Table 4-13 amplitude, which is the manual's own definition. "
            "Those amplitudes carry a stated uncertainty of one-half to two "
            "times their value, which is not propagated: read the column as a "
            "midpoint with a range.\n"
            "- A probability of zero is never evidence that a place cannot "
            "liquefy. It can mean the shaking is below the category's "
            "zero-probability threshold, or the water table is deep, or the "
            "map unit was never classified - and the log separates those.\n"
            "- UNCALIBRATED for Turkiye. Both models are US calibrations and "
            "no Turkish liquefaction inventory was used to fit or to check "
            "them. They rank places against each other; they do not predict "
            "what will happen at a given address.\n"
            "- This is a screening tool for planning. It is not a substitute "
            "for a geotechnical investigation, and it is not a code check.\n\n"
            "Using the results: rank districts by liq_prob to decide where a "
            "geotechnical campaign is worth paying for, and where a "
            "post-earthquake response plan should expect ground failure on "
            "top of the shaking damage; in susceptibility mode, liq_settle_in "
            "sizes the differential settlement that cracks pipelines, roads "
            "and foundations even where nothing collapses; run the same layer "
            "at two or three shaking levels and read where the ranking "
            "changes, because a unit that only matters at the highest PGA is "
            "a different kind of problem from one that is already high at "
            "0.1 g. Overlay the result on the debris and casualty layers: a "
            "district that is high on all three is where the hazards "
            "compound: the response network those tools plan is laid on "
            "ground that may not be there."
        )

    # ------------------------------------------------------------------ #
    # Parameters
    # ------------------------------------------------------------------ #
    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterEnum(
            self.MODE, self.tr("Model (see help)"),
            options=[self.tr(text) for text in MODE_OPTIONS],
            defaultValue=MODE_REGRESSION))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.DEM, self.tr("DEM - drives slope, Vs30 and the wetness index "
                              "(regression mode only)"),
            optional=True))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.TARGET,
            self.tr("Layer to evaluate (any geometry; one sample per feature)"),
            [QgsProcessing.SourceType.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterField(
            self.CATEGORY_FIELD,
            self.tr("Susceptibility category field (susceptibility mode: "
                    "required)"),
            parentLayerParameterName=self.TARGET, optional=True,
            type=QgsProcessingParameterField.DataType.String))
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
        self.addParameter(QgsProcessingParameterEnum(
            self.TECTONIC, self.tr("Tectonic setting (regression mode; no "
                                   "default - see help)"),
            options=[self.tr(text) for text in TECTONIC_OPTIONS],
            defaultValue=TECTONIC_SENTINEL))
        self.addParameter(QgsProcessingParameterNumber(
            self.VS30_MS, self.tr("Vs30, m/s (0 = not supplied; a field or "
                                  "raster wins over it)"),
            QgsProcessingParameterNumber.Type.Double, 0.0,
            minValue=0.0, maxValue=2000.0))
        self.addParameter(QgsProcessingParameterField(
            self.VS30_FIELD, self.tr("Vs30 field, m/s (optional; wins over "
                                     "the slope estimate)"),
            parentLayerParameterName=self.TARGET, optional=True,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.VS30_RASTER, self.tr("Vs30 raster, m/s (optional; used where "
                                      "the field is empty)"),
            optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.GROUNDWATER_M,
            self.tr("Groundwater depth, m (susceptibility mode; Hazus's own "
                    "reference is 1.524 m = 5 ft)"),
            QgsProcessingParameterNumber.Type.Double, 1.524,
            minValue=0.0, maxValue=100.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Liquefaction screening")))

    # ------------------------------------------------------------------ #
    # Output schema
    # ------------------------------------------------------------------ #
    @staticmethod
    def output_fields(base=None):
        """The columns appended to the incoming schema, in order.

        One schema for both modes, with the columns a mode does not compute
        left empty, rather than a schema that changes shape with a combo box.
        A saved Processing model that reads ``liq_prob`` keeps working when the
        mode changes; a model that reads a column that is empty can see that it
        is empty, which a missing column cannot tell it.
        """
        return PlanXAlgorithm.make_fields(
            ("liq_prob", DOUBLE),
            ("liq_area_frac", DOUBLE),
            ("liq_cond_prob", DOUBLE),
            ("liq_cat", STRING),
            ("k_m", DOUBLE),
            ("k_w", DOUBLE),
            ("liq_pga_t", DOUBLE),
            ("liq_settle_in", DOUBLE),
            ("pga_g", DOUBLE),
            ("mw", DOUBLE),
            ("cti", DOUBLE),
            ("slope_deg", DOUBLE),
            ("vs30_ms", DOUBLE),
            ("vs30_src", STRING),
            ("liq_notes", STRING),
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
        """Field index for a parameter that names a column, -1 when unset.

        Checks the column exists before believing it: a parameter can name a
        field the layer no longer has, and indexing with -1 would silently read
        the last column instead.
        """
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
        """PGA in g per feature, refusing rather than substituting."""
        if index < 0:
            if not constant > 0.0:
                raise QgsProcessingException(
                    "No shaking level was given: neither a PGA field nor a "
                    "non-zero PGA constant. The model takes ln(PGA), and a "
                    "zero here returns a zero probability - 'no shaking' is "
                    "not 'no liquefaction hazard'. Use Ground Motion Scenario "
                    "to compute a PGA field, or type a scenario PGA.")
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
                "and the model takes ln(PGA). There is no reference shaking "
                "level to fall back to - the way there is a reference velocity "
                "- so substituting one would move the answer by orders of "
                "magnitude. Fill those rows (Ground Motion Scenario writes this "
                "column), or clear the field to use the constant instead.")
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
        mode = self.parameterAsEnum(parameters, self.MODE, context)
        target = self.parameterAsSource(parameters, self.TARGET, context)
        if target is None:
            raise QgsProcessingException("Please provide a layer to evaluate.")
        self.require_projected(target, "The layer to evaluate")

        magnitude = self.parameterAsDouble(parameters, self.MAGNITUDE, context)
        pga_constant = self.parameterAsDouble(parameters, self.PGA_G, context)
        groundwater = self.parameterAsDouble(parameters, self.GROUNDWATER_M, context)

        fields = target.fields()
        pga_index, pga_name = self._column(
            fields, self.PGA_FIELD, context, parameters, "PGA")
        category_index, category_name = self._column(
            fields, self.CATEGORY_FIELD, context, parameters, "category")
        vs30_index, vs30_name = self._column(
            fields, self.VS30_FIELD, context, parameters, "Vs30")

        features = [f for f in target.getFeatures() if f.hasGeometry()]
        if not features:
            raise QgsProcessingException(
                "No usable features found in the layer to evaluate.")
        feedback.pushInfo(
            f"{len(features)} feature(s) evaluated in "
            f"{'regression' if mode == MODE_REGRESSION else 'susceptibility'} "
            f"mode; Mw {magnitude:g}.")

        pga_values = self._pga(features, pga_index, pga_name, pga_constant, feedback)

        if mode == MODE_REGRESSION:
            rows = self._regression(
                parameters, context, feedback, target, features, category_name,
                vs30_index, vs30_name, pga_values, magnitude)
        else:
            rows = self._susceptibility(
                feedback, features, category_index, pga_values, magnitude,
                groundwater)

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
    # Regression mode - Zhu et al. (2015)
    # ------------------------------------------------------------------ #
    def _regression(self, parameters, context, feedback, target, features,
                    category_name, vs30_index, vs30_name, pga_values, magnitude):
        dem_layer = self.parameterAsRasterLayer(parameters, self.DEM, context)
        if dem_layer is None:
            raise QgsProcessingException(
                "Regression mode needs a DEM: the wetness index, and the slope "
                "that gives Vs30, both come from it. Supply one, or switch to "
                "susceptibility mode if you have a classified map-unit layer "
                "instead.")
        setting_index = self.parameterAsEnum(parameters, self.TECTONIC, context)
        if setting_index == TECTONIC_SENTINEL:
            raise QgsProcessingException(
                "Choose a tectonic setting. It decides how topographic slope "
                "maps to Vs30, and the active and stable-continent columns of "
                "the source table differ by up to a factor of two in velocity "
                "at the same slope. The tool will not pick one for you.")
        setting = liq.TECTONIC_SETTINGS[setting_index - 1]

        if category_name:
            feedback.pushInfo(
                f"Note: '{category_name}' is a susceptibility-mode input and is "
                "ignored here - Zhu et al. (2015) takes no category.")

        dem, gt, _proj, pixel = read_dsm(dem_layer)
        pixel_metres = pixel * metres_per_unit(dem_layer.crs())
        feedback.pushInfo(
            f"CTI: a {dem.shape[1]}x{dem.shape[0]} DEM at {pixel_metres:g} m "
            "pixel. The wetness index is ln(specific catchment area / tan beta) "
            "from one D8 pass; flat and undrained cells have no downhill "
            f"neighbour and come back as +inf, which the model's own ceiling of "
            f"{liq.ZHU_CTI_CLIP[1]:g} then clips.")
        cti_grid, gradient = hydro.cti(dem, pixel_metres)

        dem_crs = dem_layer.crs()
        transform = None
        if target.sourceCrs() != dem_crs:
            transform = QgsCoordinateTransform(
                target.sourceCrs(), dem_crs, context.transformContext())
        vs30_layer = self.parameterAsRasterLayer(parameters, self.VS30_RASTER, context)
        vs30_array = vs30_gt = None
        vs30_transform = None
        if vs30_layer is not None:
            vs30_array, vs30_gt, _p, _pixel = read_dsm(vs30_layer)
            if target.sourceCrs() != vs30_layer.crs():
                vs30_transform = QgsCoordinateTransform(
                    target.sourceCrs(), vs30_layer.crs(), context.transformContext())
        vs30_constant = self.parameterAsDouble(parameters, self.VS30_MS, context)
        if vs30_name:
            feedback.pushInfo(
                f"Vs30: the field '{vs30_name}' wins where it is filled; empty "
                "rows fall back to the raster, then the constant, then the "
                "slope estimate, and 'vs30_src' says which happened on each row.")

        rows = []
        sources: dict[str, int] = {}
        clipped_cti = clipped_pga = clamped_slope = undrained = 0
        for index, feature in enumerate(features):
            if feedback.isCanceled():
                break
            pga = pga_values[index]
            point = feature.geometry().pointOnSurface().asPoint()
            # Three answers, and conflating any two of them is a silent error.
            # Off the grid and on a nodata cell are both *missing* terrain, so
            # the run stops (rule R7). A cell with no downslope neighbour is
            # not missing: its wetness index is genuinely +inf, which is what
            # the index says about flat ground, and the model's own ceiling is
            # what clips it. Refusing an undrained cell would have meant the
            # tool declining to answer anywhere the terrain is flat, which in a
            # city is most of it.
            cell, point_gradient = self._sample_pair(
                cti_grid, gradient, gt, transform, point)
            if cell is None or np.isnan(cell):
                raise QgsProcessingException(
                    f"Feature {index + 1} falls outside the DEM, or on a nodata "
                    "cell, so it has no wetness index. A missing terrain input "
                    "is not a missing hazard - clip the layer to the DEM, or "
                    "enlarge the DEM.")
            if np.isinf(cell):
                undrained += 1
            if point_gradient is None or not np.isfinite(point_gradient) \
                    or point_gradient < 0.0:
                point_gradient = 0.0
            slope_deg = float(np.degrees(np.arctan(point_gradient)))

            vs30, source_key, clamped = self._resolve_vs30(
                feature, vs30_index, vs30_constant, vs30_array, vs30_gt,
                vs30_transform, point, point_gradient, setting)
            sources[source_key] = sources.get(source_key, 0) + 1
            if clamped:
                clamped_slope += 1

            result = liq.zhu_probability(pga, magnitude, cell, vs30)
            clipped_cti += 1 if result["cti_clipped"] else 0
            clipped_pga += 1 if result["pga_clipped"] else 0
            rows.append([
                float(result["probability"]), float(result["coverage"]),
                None, None, None, None, None, None,
                float(pga), float(magnitude), float(cell), slope_deg,
                float(vs30), source_key, "; ".join(result["notes"]),
            ])

        self._report_regression(
            feedback, len(features), setting, sources, clipped_cti, clipped_pga,
            clamped_slope, undrained, magnitude)
        return rows

    @staticmethod
    def _sample_pair(primary, secondary, gt, transform, point):
        """Sample two co-registered grids at one point, or (None, None)."""
        x, y = point.x(), point.y()
        if transform is not None:
            transformed = transform.transform(x, y)
            x, y = transformed.x(), transformed.y()
        rows, cols = primary.shape
        col = int((x - gt[0]) / gt[1])
        row = int((y - gt[3]) / gt[5])
        if not (0 <= row < rows and 0 <= col < cols):
            return None, None
        return float(primary[row, col]), float(secondary[row, col])

    @staticmethod
    def _sample(array, gt, transform, point):
        """Sample one grid at a point, or None when the point is off it."""
        primary, _ = LiquefactionAlgorithm._sample_pair(
            array, array, gt, transform, point)
        return primary

    def _resolve_vs30(self, feature, index, constant, array, gt, transform,
                      point, gradient, setting):
        """Vs30 in m/s, the name of its source, and whether it was clamped.

        The order is field, raster, constant, slope. A field row that is empty
        falls through rather than stopping the run - unlike PGA, every fallback
        here is within a factor of a few of the truth, and the row carries the
        name of the one it used, so the substitution is visible rather than
        silent.
        """
        if index >= 0:
            number = self._numeric(feature.attributes()[index])
            if number is not None and number > 0.0:
                return number, "field", False
        if array is not None:
            sampled = self._sample(array, gt, transform, point)
            if sampled is not None and np.isfinite(sampled) and sampled > 0.0:
                return sampled, "raster", False
        if constant > 0.0:
            return constant, "constant", False
        vs30, clamped = liq.vs30_from_slope(gradient, setting)
        return vs30, f"slope:{setting}", clamped

    def _report_regression(self, feedback, n, setting, sources, clipped_cti,
                           clipped_pga, clamped_slope, undrained, magnitude):
        feedback.pushInfo(
            "Model: Zhu et al. (2015) logistic regression (Earthquake "
            "Spectra 31(3), Table 3). "
            f"Mw {magnitude:g}, tectonic setting '{setting}' (Allen & Wald "
            "2007, USGS OFR 2007-1357, Table 2)."
        )
        used_slope = any(key.startswith("slope") for key in sources)
        feedback.pushInfo(
            "Vs30 source: "
            + ", ".join(f"{key} x{count}" for key, count in sorted(sources.items()))
            + ("" if used_slope else
               ". The tectonic setting did not affect this run: every row took "
               "its velocity from a field, a raster or the constant.")
        )
        if used_slope:
            feedback.pushInfo(
                "Slope-derived Vs30 is the model's weakest link: a 30 m average "
                "velocity inferred from topographic slope is an inference, not a "
                "measurement. A Vs30 field or raster beats it wherever you have "
                "one."
            )
        if undrained:
            feedback.pushInfo(
                f"Wetness index: {undrained} row(s) have no downslope neighbour "
                "at all, so their index is +inf and the model's ceiling of "
                f"{liq.ZHU_CTI_CLIP[1]:g} is what they were evaluated at. That "
                "is flat or ponded ground, and a D8 wetness index carries no "
                "information there - a DEM with more vertical relief, or a "
                "coarser one, would say more than this one does."
            )
        if clipped_cti or clipped_pga:
            feedback.pushInfo(
                f"Clips applied: CTI on {clipped_cti} row(s) at "
                f"{liq.ZHU_CTI_CLIP[1]:g}, PGA on {clipped_pga} row(s) at "
                f"{liq.ZHU_PGA_CLIP_G[1]:g} g. Those rows are outside the range "
                "the coefficients were fitted on, and each one says so in "
                "'liq_notes'."
            )
        if clamped_slope:
            feedback.pushInfo(
                f"Slope-to-Vs30: {clamped_slope} row(s) fell outside the slope "
                "nodes of Allen & Wald Table 2 and were held at the table's own "
                "endpoint (180 m/s at the low end, 760 m/s at the high end)."
            )
        feedback.pushInfo(
            f"{n} row(s). 'liq_prob' is the site probability; 'liq_area_frac' is "
            "0.81 times it - the separate proportion-of-area reading. Both are "
            "UNCALIBRATED for Turkiye: they rank places against each other, they "
            "do not predict addresses."
        )

    # ------------------------------------------------------------------ #
    # Susceptibility mode - Hazus 6.1 Section 4.2.2.1
    # ------------------------------------------------------------------ #
    def _susceptibility(self, feedback, features, category_index, pga_values,
                        magnitude, groundwater):
        if category_index < 0:
            raise QgsProcessingException(
                "Susceptibility mode needs a map-unit layer with a category "
                "column, and this run has none. That layer is the model: "
                "without it there is no result to give, and 'the ground does "
                "not liquefy here' is not an answer this tool is allowed to "
                "invent. Classify your map units (Very High / High / Moderate "
                "/ Low / Very Low / None) and name the column, or switch to "
                "regression mode, which needs no classification.")
        feedback.pushInfo(
            "Model: Hazus 6.1 Section 4.2.2.1, Equation 4-9 with Tables 4-10 to "
            f"4-13. Mw {magnitude:g}; groundwater at {groundwater:g} m "
            f"({groundwater / 0.3048:.2f} ft) drives the K_W correction of "
            "Equation 4-11."
        )

        # Resolve every category first: an unrecognised one stops the run
        # before a single row is written, because a run that half-succeeds is
        # the one a reader will quote from.
        categories, unknown = [], {}
        for feature in features:
            raw = feature.attributes()[category_index]
            category = liq.normalise_category(raw)
            categories.append(category)
            if category is None:
                key = "<NULL>" if raw is None else str(raw)
                unknown[key] = unknown.get(key, 0) + 1
        if unknown:
            listed = ", ".join(f"'{key}' x{count}" for key, count
                               in sorted(unknown.items())[:5])
            raise QgsProcessingException(
                f"The category column holds {len(unknown)} value(s) this model "
                f"does not define: {listed}. It accepts "
                + ", ".join(liq.HAZUS_CATEGORIES)
                + " (case and separators are ignored; nothing else is). Reading "
                  "an unrecognised category as zero would report 'no "
                  "liquefaction hazard' for a unit nobody classified, so the "
                  "run stops instead. Recode the column, or drop those units.")

        rows, below_threshold, zero_probability = [], 0, 0
        for index, feature in enumerate(features):
            if feedback.isCanceled():
                break
            category = categories[index]
            pga = pga_values[index]
            result = liq.hazus_probability(category, pga, magnitude, groundwater)
            notes = []
            threshold = result["pga_threshold"]
            if threshold is not None and pga < threshold:
                below_threshold += 1
                notes.append(
                    f"PGA {pga:.3g} g is below this category's zero-probability "
                    f"threshold of {threshold:g} g (Hazus Table 4-12)")
            if result["probability"] <= 0.0 and category != "None":
                zero_probability += 1
            rows.append([
                float(result["probability"]), None,
                float(result["conditional"]), category,
                float(result["k_m"]), float(result["k_w"]),
                None if threshold is None else float(threshold),
                float(result["settlement_in"]),
                float(pga), float(magnitude),
                None, None, None, None,
                "; ".join(notes),
            ])

        self._report_susceptibility(
            feedback, len(features), magnitude, categories, below_threshold,
            zero_probability)
        return rows

    def _report_susceptibility(self, feedback, n, magnitude, categories,
                               below_threshold, zero_probability):
        tally: dict[str, int] = {}
        for category in categories:
            tally[category] = tally.get(category, 0) + 1
        feedback.pushInfo(
            "Categories present: "
            + ", ".join(f"{name} x{count}" for name, count in sorted(tally.items()))
            + "."
        )
        feedback.pushInfo(
            "The published correction polynomials do not pass exactly through "
            "unity at the conditions they are referenced to: K_M(7.5) = "
            f"{liq.hazus_magnitude_factor(7.5):.4f} and K_W(5 ft) = "
            f"{liq.hazus_groundwater_factor(1.524):.4f}. They are applied as "
            "printed - renormalising would move every number away from the "
            "published method by about 5 % to fix a cosmetic inconsistency in "
            "the source."
        )
        feedback.pushInfo(
            "'liq_settle_in' is the probability times the Table 4-13 amplitude, "
            "which is the manual's own definition. Those amplitudes carry a "
            "stated uncertainty of one-half to two times their value, and the "
            "multiplier is not propagated here: read the column as a midpoint "
            "with a range, not as a prediction."
        )
        if below_threshold:
            feedback.pushInfo(
                f"{below_threshold} unit(s) are below their category's "
                "zero-probability threshold (Table 4-12), so their probability "
                "comes out at zero. That is the model's answer at this shaking "
                "level, not evidence that the unit cannot liquefy."
            )
        if zero_probability:
            feedback.pushInfo(
                f"{zero_probability} unit(s) have a susceptible category but a "
                "zero probability at this magnitude and water-table depth. Raise "
                "the magnitude or lower the water table before reading that as a "
                "clean bill of health."
            )
        feedback.pushInfo(
            f"{n} row(s), UNCALIBRATED for Turkiye. Hazus's susceptibility "
            "categories describe US regional geology; a Turkish unit inherits "
            "the class somebody assigned it, and that assignment is the weakest "
            "link in this mode."
        )

    def createInstance(self):
        return LiquefactionAlgorithm()
