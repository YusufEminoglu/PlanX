# -*- coding: utf-8 -*-
"""Ground Motion Scenario: peak and spectral intensity measures at receivers.

The model is Akkar, Sandikkaya & Bommer (2014) - see engine/gmpe.py for the
paper, the functional form and the traps. This module is the QGIS surface:
parameters in, one row of intensity measures per receiver out.
"""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsFeature,
    QgsFeatureSink,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsUnitTypes,
    Qgis,
)

from .base import DOUBLE, GROUP_SEISMIC, PlanXAlgorithm, STRING
from ..engine import gmpe

#: Option text for the distance metrics. Kept in the tool rather than in the
#: engine because it is combo-box copy, not model vocabulary; the codes in
#: gmpe.DISTANCE_METRICS and the order of these strings must stay aligned -
#: the index of one is how the other is looked up.
METRIC_OPTIONS = (
    "RJB - closest horizontal distance to the rupture",
    "Repi - horizontal distance to the epicentre",
    "Rhypo - straight-line distance to the focus",
)

SCENARIO_OPTIONS = (
    "A - Point source: one epicentre (depth gives the hypocentral distance)",
    "B - Extended rupture: a fault trace (Joyner-Boore distance only)",
)


def units_per_km(crs) -> float:
    """How many of ``crs``'s linear units make one kilometre.

    The engine works in kilometres; the coordinates it is handed are in
    whatever the layer's projected CRS uses. Assuming metres is right for
    UTM and wrong by a factor of 3.28 for a state-plane CRS in feet, and
    wrong numbers of the right magnitude never announce themselves - so the
    factor is read off the CRS instead.

    ``fromUnitToUnitFactor`` answers the opposite question - metres per unit,
    which is 1.0 for a metre-based projection - so the kilometre is divided
    *by* it, not through it. Getting that the wrong way round multiplies a
    demo city 750 m across into 472 000 km, which is how this was first
    written; the matrix's value check caught it on the next run.
    """
    metres_per_unit = float(QgsUnitTypes.fromUnitToUnitFactor(
        crs.mapUnits(), Qgis.DistanceUnit.Meters))
    if not metres_per_unit > 0.0:
        raise QgsProcessingException(
            f"The receivers' CRS ({crs.authid()}) does not declare a linear "
            f"unit, so a distance in it cannot be converted to kilometres. "
            f"Reproject the layer to a projected CRS with a known unit.")
    return 1000.0 / metres_per_unit


class GroundMotionAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_SEISMIC
    ICON = "tool_groundmotion.png"
    #: pga_g matches none of the renderer's preference tokens, so it is named
    #: explicitly rather than by renaming the field to satisfy a substring.
    RENDER_FIELD = "pga_g"

    SCENARIO = "SCENARIO"
    MAGNITUDE = "MAGNITUDE"
    EPICENTRE = "EPICENTRE"
    DEPTH_KM = "DEPTH_KM"
    FAULT_TRACE = "FAULT_TRACE"
    DISTANCE_METRIC = "DISTANCE_METRIC"
    FAULT_MECHANISM = "FAULT_MECHANISM"
    VS30 = "VS30"
    VS30_FIELD = "VS30_FIELD"
    SPECTRAL_PERIODS = "SPECTRAL_PERIODS"
    EPSILON = "EPSILON"
    RECEIVERS = "RECEIVERS"
    OUTPUT = "OUTPUT"

    def name(self):
        return "groundmotion"

    def displayName(self):
        return self.tr("Ground Motion Scenario")

    def shortHelpString(self):
        return self.tr(
            "How hard does the ground shake at each site in one earthquake "
            "scenario? Gives peak ground acceleration, peak ground velocity and "
            "any spectral accelerations you ask for, at every receiver, from an "
            "explicit magnitude - distance - site scenario.\n\n"
            "Model: Akkar, Sandikkaya & Bommer (2014), Bulletin of Earthquake "
            "Engineering 12(1), 359-387 - one of the four models in the logic "
            "tree of Turkey's 2018 national seismic hazard map. The coefficients "
            "are the authors' own. It is a shallow-crustal model for Europe and "
            "the Middle East.\n\n"
            "Scenario. A - one epicentre and a focal depth: hypocentral distance "
            "is computed from the depth, and for this geometry the Joyner-Boore "
            "and epicentral distances are the same horizontal distance, because "
            "a point has no rupture surface. B - a fault trace as a line: an "
            "extended rupture has no single epicentre or hypocentre, so only the "
            "Joyner-Boore distance is offered. It is measured to the trace, "
            "which for the near-vertical crustal ruptures this model was built "
            "for is the rupture's surface projection; on a shallow-dipping "
            "thrust the real Joyner-Boore distance is shorter, so the shaking "
            "here is understated. Distances are in kilometres whatever the "
            "receivers' CRS uses: its linear unit is read off the layer and "
            "converted, and the epicentre or fault trace is reprojected into "
            "it first.\n\n"
            "Site. Vs30 is the only site term the model has. The default 750 m/s "
            "is the model's own reference velocity, at which the site term is "
            "exactly zero - so the default answer is the rock-reference motion, "
            "and any soil amplification in the result is a choice you made. Give "
            "a Vs30 field to use real site values; receivers whose field is "
            "empty fall back to the constant and are marked in 'caveat'. Above "
            "1000 m/s the model caps Vs30, and the row says so.\n\n"
            "How to read the results\n"
            "- These are MEDIAN values, not design levels and not a code check. "
            "epsilon = 1 gives the 84th-percentile motion instead, which is the "
            "usual way to pin a scenario to a rarer level.\n"
            "- The model carries no basin term and no directivity, so deep "
            "soft-soil amplification and forward-directivity pulses are not "
            "represented.\n"
            "- A row whose 'caveat' column is not empty is outside the range the "
            "paper publishes its coefficients for. The number is still computed "
            "- read the caveat before you use it.\n"
            "- This is a scenario, not a hazard. It is not a substitute for the "
            "national hazard map, and one scenario is not a probability.\n\n"
            "Using the results: feed 'pga_g' back into the Seismic Debris tool's "
            "PGA field to replace its magnitude estimate with real ground motion; "
            "rank districts by spectral acceleration at the period that matters "
            "for their buildings (about 0.3 s for low-rise, 1 s and up for "
            "tall); or test whether a scenario puts a hospital, a school or a "
            "bridge approach past a threshold you care about."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterEnum(
            self.SCENARIO, self.tr("Scenario geometry (see help)"),
            options=[self.tr(text) for text in SCENARIO_OPTIONS], defaultValue=0))
        self.addParameter(QgsProcessingParameterNumber(
            self.MAGNITUDE, self.tr("Moment magnitude (Mw)"),
            QgsProcessingParameterNumber.Type.Double, 7.0,
            minValue=3.0, maxValue=9.5))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.EPICENTRE, self.tr("Epicentre (one point; geometry B ignores this)"),
            [QgsProcessing.SourceType.TypeVectorPoint], optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.DEPTH_KM, self.tr("Focal depth, km (hypocentral distance only)"),
            QgsProcessingParameterNumber.Type.Double, 10.0,
            minValue=0.0, maxValue=200.0))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.FAULT_TRACE, self.tr("Fault trace (line; geometry A ignores this)"),
            [QgsProcessing.SourceType.TypeVectorLine], optional=True))
        self.addParameter(QgsProcessingParameterEnum(
            self.DISTANCE_METRIC, self.tr("Distance metric (written to every row)"),
            options=[self.tr(text) for text in METRIC_OPTIONS], defaultValue=0))
        self.addParameter(QgsProcessingParameterEnum(
            self.FAULT_MECHANISM, self.tr("Fault mechanism"),
            options=[self.tr("{0} - {1}").format(code, gmpe.MECHANISM_LABELS[code])
                     for code in gmpe.MECHANISMS],
            defaultValue=0))
        self.addParameter(QgsProcessingParameterNumber(
            self.VS30, self.tr("Vs30, m/s (default = the model's reference velocity)"),
            QgsProcessingParameterNumber.Type.Double, gmpe.V_REF,
            minValue=100.0, maxValue=2000.0))
        self.addParameter(QgsProcessingParameterString(
            self.SPECTRAL_PERIODS,
            self.tr("Spectral periods in seconds, comma-separated (empty = PGA and PGV only)"),
            defaultValue="", optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.EPSILON, self.tr("Epsilon (standard deviations from the median; 0 = median)"),
            QgsProcessingParameterNumber.Type.Double, 0.0,
            minValue=-3.0, maxValue=3.0))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.RECEIVERS, self.tr("Receivers - the layer to evaluate (any geometry)"),
            [QgsProcessing.SourceType.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterField(
            self.VS30_FIELD, self.tr("Vs30 field (optional; overrides the constant)"),
            parentLayerParameterName=self.RECEIVERS, optional=True,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Receivers with ground motion")))

    def processAlgorithm(self, parameters, context, feedback):
        scenario = gmpe.SCENARIOS[self.parameterAsEnum(parameters, self.SCENARIO, context)]
        magnitude = self.parameterAsDouble(parameters, self.MAGNITUDE, context)
        depth_km = self.parameterAsDouble(parameters, self.DEPTH_KM, context)
        metric = gmpe.DISTANCE_METRICS[
            self.parameterAsEnum(parameters, self.DISTANCE_METRIC, context)]
        mechanism = gmpe.MECHANISMS[
            self.parameterAsEnum(parameters, self.FAULT_MECHANISM, context)]
        vs30_constant = self.parameterAsDouble(parameters, self.VS30, context)
        epsilon = self.parameterAsDouble(parameters, self.EPSILON, context)
        periods_text = self.parameterAsString(parameters, self.SPECTRAL_PERIODS, context)
        receivers = self.parameterAsSource(parameters, self.RECEIVERS, context)
        vs30_field = self.parameterAsString(parameters, self.VS30_FIELD, context)
        epicentre = self.parameterAsSource(parameters, self.EPICENTRE, context)
        fault = self.parameterAsSource(parameters, self.FAULT_TRACE, context)

        complaint = gmpe.check_metric(metric, scenario)
        if complaint:
            raise QgsProcessingException(complaint)

        try:
            periods = gmpe.parse_periods(periods_text)
        except ValueError as exc:
            raise QgsProcessingException(str(exc)) from None
        period_indices = [gmpe.period_index(period) for period in periods]

        self.require_projected(receivers, "Receivers")
        crs = receivers.sourceCrs()
        transform_context = context.transformContext()
        scale = units_per_km(crs)
        site_xy, features = self.source_points(receivers, crs, transform_context)
        n = len(features)
        if not n:
            raise QgsProcessingException(
                f"No usable features in '{receivers.sourceName()}'.")

        # ---------------------------------------------------------- distances
        if scenario == "point":
            if epicentre is None:
                raise QgsProcessingException(
                    "Geometry A needs an epicentre layer: one point, the "
                    "surface position of the earthquake. Raise the focal depth "
                    "rather than moving the point to represent a deep event - "
                    "the depth is what makes the hypocentral distance larger "
                    "than the epicentral one.")
            epi_xy, epi_feats = self.source_points(epicentre, crs, transform_context)
            if len(epi_feats) > 1:
                raise QgsProcessingException(
                    f"The epicentre layer has {len(epi_feats)} features. One run "
                    f"is one earthquake, so give a layer holding a single point "
                    f"- or select the one you mean and re-run on the selection.")
            distances = gmpe.distances("point", site_xy, scale,
                                       epicentre_xy=epi_xy[0], depth_km=depth_km)
            source_text = (f"point source at ({epi_xy[0][0]:.1f}, {epi_xy[0][1]:.1f}) "
                           f"in {crs.authid()}, focal depth {depth_km:g} km")
        else:
            if fault is None:
                raise QgsProcessingException(
                    "Geometry B needs a fault trace as a line layer. If the "
                    "rupture is better described as a point, use geometry A "
                    "with an epicentre and a focal depth.")
            polylines, _ = self.source_polylines(
                fault, feedback, target_crs=crs,
                transform_context=transform_context)
            distances = gmpe.distances("fault", site_xy, scale, polylines=polylines)
            length_km = 0.0
            for line in polylines:
                steps = np.diff(np.asarray(line, dtype=np.float64), axis=0)
                length_km += float(np.hypot(steps[:, 0], steps[:, 1]).sum()) / scale
            source_text = (f"fault trace of {length_km:.1f} km in {crs.authid()}, "
                           f"distance measured to the trace")

        r_km = np.asarray(distances[metric], dtype=np.float64)

        # ---------------------------------------------------------------- site
        vs30, empty_vs30 = self._site_velocity(receivers, features, vs30_field,
                                               vs30_constant)
        n_missing = int(np.count_nonzero(empty_vs30))
        if n_missing:
            feedback.pushWarning(self.tr(
                f"Vs30: {n_missing} of {n} receiver(s) had an empty or "
                f"non-positive Vs30 field and were given the constant "
                f"{vs30_constant:g} m/s. Those rows carry 'vs30_missing' in the "
                f"'caveat' column."))

        # --------------------------------------------------------------- model
        result = gmpe.predict(metric, np.full(n, magnitude), r_km, vs30,
                              np.full(n, mechanism), epsilon=epsilon)
        pga = result["pga_g"]
        depth_note = depth_km if scenario == "point" else None
        caveats = gmpe.envelope_flags(np.full(n, magnitude), r_km, vs30, depth_note)
        for index in range(n):
            if empty_vs30[index]:
                caveats[index].append("vs30_missing")
            if result["vs30_capped"][index]:
                caveats[index].append("vs30_capped")

        # ------------------------------------------------------------ outputs
        specs = [("pga_g", DOUBLE), ("pgv_cms", DOUBLE)]
        specs += [(f"sa_{period:g}_g", DOUBLE) for period in periods]
        specs += [("r_km", DOUBLE), ("dist_metric", STRING), ("vs30", DOUBLE),
                  ("pga_rock_g", DOUBLE), ("sigma_pga", DOUBLE), ("caveat", STRING)]
        fields = self.make_fields(*specs, base=receivers.fields())
        sink, dest = self.parameterAsSink(parameters, self.OUTPUT, context, fields,
                                          receivers.wkbType(), crs)
        if sink is None:
            raise QgsProcessingException(
                "No output layer was created. Give a destination for the "
                "receivers-with-ground-motion layer.")

        n_base = len(receivers.fields())
        sigma_pga = float(result["sigma_total"][gmpe.INDEX_PGA])
        for index, feature in enumerate(features):
            if feedback.isCanceled():
                break
            if not np.isfinite(pga[index]):
                raise QgsProcessingException(
                    f"Receiver {index + 1} produced a non-finite acceleration. "
                    f"Check the scenario values: Mw {magnitude:g}, distance "
                    f"{r_km[index]:g} km, Vs30 {vs30[index]:g} m/s.")
            row = [round(float(pga[index]), 4),
                   round(float(result["pgv_cms"][index]), 3)]
            row += [round(float(result["im"][index, row_index]), 4)
                    for row_index in period_indices]
            row += [round(float(r_km[index]), 3), metric,
                    round(float(vs30[index]), 1),
                    round(float(result["rock_pga_g"][index]), 4),
                    round(sigma_pga, 4),
                    ";".join(caveats[index])]
            out = QgsFeature(fields)
            out.setGeometry(feature.geometry())
            out.setAttributes(list(feature.attributes())[:n_base] + row)
            sink.addFeature(out, QgsFeatureSink.Flag.FastInsert)
        results = {self.OUTPUT: dest}

        # -------------------------------------------------------------- report
        feedback.pushInfo(self.tr(
            f"Scenario: Mw {magnitude:g}, {gmpe.MECHANISM_LABELS[mechanism].lower()} "
            f"mechanism, {gmpe.METRIC_LABELS[metric].split(' - ')[0]} distance, "
            f"{source_text}."))
        if scenario == "fault":
            feedback.pushInfo(self.tr(
                "The model has no Rrup term, so an extended rupture is evaluated "
                "at the Joyner-Boore distance. On a shallow-dipping thrust the "
                "real distance is shorter and the shaking here is understated."))
        if epsilon:
            feedback.pushInfo(self.tr(
                f"Epsilon {epsilon:+g}: every value is {abs(epsilon):g} total "
                "standard deviation(s) "
                f"{'above' if epsilon > 0 else 'below'} the median, not the "
                "median itself."))
        feedback.pushInfo(self.tr(
            "Model: ASB2014 (Akkar, Sandikkaya & Bommer 2014). Median intensity "
            "measures, not design levels; no basin term and no directivity."))
        feedback.pushInfo(self.tr(
            f"Receivers: {n}. Distance {float(np.min(r_km)):.3f} to "
            f"{float(np.max(r_km)):.3f} km; PGA {float(np.min(pga)):.4f} to "
            f"{float(np.max(pga)):.4f} g (median {float(np.median(pga)):.4f} g, "
            f"sigma_total {sigma_pga:.4f} in ln units)."))
        if periods:
            feedback.pushInfo(self.tr(
                "Spectral periods written: "
                + ", ".join(f"T = {period:g} s" for period in periods) + "."))
        else:
            feedback.pushInfo(self.tr(
                "No spectral periods requested, so only PGA and PGV are written. "
                "Name periods in the 'Spectral periods' parameter to add Sa "
                "columns; the model is tabulated at fixed periods and this tool "
                "does not interpolate between them."))
        pinned = int(np.count_nonzero(result["vs30_capped"]))
        if pinned:
            feedback.pushInfo(self.tr(
                f"Vs30 cap: {pinned} receiver(s) were above the model's "
                f"{gmpe.SITE_VS30_CAP:g} m/s ceiling and were evaluated at that "
                f"ceiling. Their rows carry 'vs30_capped' in 'caveat'."))
        for note in gmpe.envelope_report(np.full(n, magnitude), r_km, vs30, depth_note):
            feedback.pushWarning(self.tr("Outside the model's envelope - ") + note)
        return results

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _site_velocity(receivers, features, vs30_field, fallback):
        """Vs30 per receiver, plus a mask of the rows that fell back.

        A field that exists is not a field that holds anything: an empty or
        zero cell is counted and flagged rather than quietly becoming a rock
        site, which is the reading a silent 0 would produce.
        """
        values = np.full(len(features), float(fallback), dtype=np.float64)
        empty = np.zeros(len(features), dtype=bool)
        index = receivers.fields().lookupField(vs30_field) if vs30_field else -1
        if index < 0:
            return values, empty
        for position, feature in enumerate(features):
            try:
                value = float(feature.attributes()[index])
            except (TypeError, ValueError):
                value = float("nan")
            if not np.isfinite(value) or value <= 0.0:
                empty[position] = True
                continue
            values[position] = value
        return values, empty

    def createInstance(self):
        return GroundMotionAlgorithm()
