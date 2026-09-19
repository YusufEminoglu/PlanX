# -*- coding: utf-8 -*-
"""Seismic human impact algorithm: casualties and shelter need."""
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
)

from .base import DOUBLE, GROUP_SEISMIC, STRING, PlanXAlgorithm
from . import _units
from ..engine import impact
from ..engine import seismic


def _float_or(value, fallback=0.0):
    """``float(value)`` with a fallback for nulls and non-numeric text."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


class SeismicImpactAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_SEISMIC
    ICON = "tool_seismicimpact.png"

    #: Total expected casualties is the headline number. Named explicitly
    #: rather than left to the renderer's preference-token scan, which has no
    #: token for casualties and would leave the layer in one flat colour.
    RENDER_FIELD = "cas_total"

    BUILDINGS = "BUILDINGS"
    FLOOR_FIELD = "FLOOR_FIELD"
    AREA_FIELD = "AREA_FIELD"
    DAMAGE_STATE_FIELD = "DAMAGE_STATE_FIELD"
    BUILDING_TYPE = "BUILDING_TYPE"
    TIME_OF_DAY = "TIME_OF_DAY"
    OCCUPANCY = "OCCUPANCY"
    OCCUPANCY_FIELD = "OCCUPANCY_FIELD"
    OCCUPANCY_SOURCE = "OCCUPANCY_SOURCE"
    POPULATION_FIELD = "POPULATION_FIELD"
    AREA_PER_OCCUPANT = "AREA_PER_OCCUPANT"
    UNITS_FIELD = "UNITS_FIELD"
    HOUSEHOLD_RATE = "HOUSEHOLD_RATE"
    WEIGHT_INCOME = "WEIGHT_INCOME"
    WEIGHT_ETHNICITY = "WEIGHT_ETHNICITY"
    WEIGHT_OWNERSHIP = "WEIGHT_OWNERSHIP"
    WEIGHT_AGE = "WEIGHT_AGE"
    MOD_INCOME = "MOD_INCOME"
    MOD_ETHNICITY = "MOD_ETHNICITY"
    MOD_OWNERSHIP = "MOD_OWNERSHIP"
    MOD_AGE = "MOD_AGE"
    OUT = "OUT"

    #: Indices of the OCCUPANCY_SOURCE enum.
    SOURCE_FIELD, SOURCE_AREA = range(2)

    #: The four damage-state probability columns this tool reads, as
    #: ``planx:seismicdebris`` writes them: (Hazus state, column name). Columns
    #: are matched case-insensitively because they survive a round trip through
    #: a GeoPackage, a shapefile or a spreadsheet export, and each of those can
    #: change the case.
    PROBABILITY_COLUMNS = (
        ("slight", "prob_slight"),
        ("moderate", "prob_moderate"),
        ("extensive", "prob_extensive"),
        ("complete", "prob_complete"),
    )

    #: Column names tried, in order, when no damage-state field is named.
    DAMAGE_STATE_FALLBACKS = ("damage_state", "damage", "damagestate", "ds")

    #: Column names tried, in order, when no area field is named. The first is
    #: the one ``planx:seismicdebris`` writes, so the debris -> casualties chain
    #: runs without the user picking anything. It matters only when the
    #: buildings arrive as points: the debris tool writes centroids, and a
    #: centroid has no area, so without this the floor-area occupant estimate
    #: is zero for every building and the run reports a population of nobody.
    AREA_FALLBACKS = ("footprint_area", "area_m2", "area", "shape_area")

    #: Floor area per occupant at the run's default density; a screening value
    #: of this tool's own, not a Hazus number. See
    #: ``impact.occupants_from_floor_area``.
    DEFAULT_AREA_PER_OCCUPANT = 30.0

    def name(self):
        return "seismicimpact"

    def displayName(self):
        return self.tr("Seismic Human Impact (Casualties and Shelter)")

    def shortHelpString(self):
        return self.tr(
            "Expected injuries, deaths and shelter need for an earthquake "
            "scenario, per building.\n\n"
            "This is the half of an earthquake assessment the rest of the "
            "toolbox leaves out. Damage and debris are physical; this turns "
            "them into people - how many need a hospital, how many households "
            "lose their home, how many will turn up at a public shelter.\n\n"
            "WHAT IT READS\n"
            "The four damage-state probabilities the Seismic Collapse and "
            "Debris Spread tool writes (prob_slight, prob_moderate, "
            "prob_extensive, prob_complete). Point Buildings at that tool's "
            "output and the scenario chains straight through.\n"
            "Any layer carrying those four columns works too. If the layer "
            "carries a single damage-state text column instead, name it under "
            "'Damage state field' and each building is treated as certainly "
            "being in the state it names. That throws away the distribution "
            "and with it most of what this tool measures; the four columns are "
            "the real input.\n\n"
            "WHAT IT MODELS\n"
            "Hazus 6.1 Section 12 (casualties) and Section 13 (population "
            "displacement and shelter), transcribed from the manual. The "
            "casualty model is the manual's event tree: damage-state "
            "probability, split at Complete damage into collapse and no "
            "collapse, times a casualty rate per severity, times the number of "
            "people in the building. Four severities are reported, from "
            "injuries a paramedic can treat through to instant deaths. People "
            "outside and close to the building are counted separately, on the "
            "manual's own outdoor rates - falling parapets, infill and glazing "
            "are a real cause of injury.\n"
            "The shelter model counts uninhabitable dwellings, converts them "
            "to displaced households, and then to the number of people who "
            "will seek publicly provided shelter.\n\n"
            "WHO IS IN THE BUILDING\n"
            "The scenario time decides. Hazus's three scenarios are 2 a.m. "
            "(night), 2 p.m. (daytime) and 5 p.m. (commute). A residential "
            "building is nearly full at 2 a.m. and about half full at 5 p.m.; "
            "a school holds nobody at 2 a.m.; a hotel holds a fifth of its "
            "guests at 2 p.m. Those shifts come from Hazus Table 12-2 and are "
            "applied to whatever occupant count you supply.\n"
            "The occupant count comes from a population field if you have one, "
            "or from floor area: footprint x storeys divided by an area per "
            "occupant. The area-per-occupant default is this tool's own "
            "screening assumption, not a Hazus figure - set it to something "
            "you can defend, or supply a population field, which is better.\n"
            "The floor-area source reads the footprint from the geometry, so "
            "it needs polygons. If the buildings arrive as points - which is "
            "what planx:seismicdebris writes, as centroids - the footprint "
            "comes from a field instead. That field is found automatically "
            "(the debris tool writes footprint_area), or you can name one. "
            "With neither, the run stops rather than report a population of "
            "zero. A footprint read from the geometry is in ground square "
            "metres, measured on the CRS's ellipsoid; one read from a column is "
            "in whatever unit that column's producer used, which is square "
            "metres for the debris tool's footprint_area.\n\n"
            "THE DEMOGRAPHIC TERMS - READ THIS BEFORE QUOTING A SHELTER "
            "NUMBER\n"
            "Hazus's shelter equation filters the displaced population by "
            "income, ethnicity, tenure and age, because in the data those "
            "predict who actually seeks public shelter. A Turkish study area "
            "rarely has all four. Rather than invent an equivalent or drop the "
            "terms, the structure is implemented and every modifier defaults "
            "to neutral:\n"
            "  alpha = IW*IM + EW*EM + OW*OM + AW*AM\n"
            "with the category weights from Hazus Table 13-2 and the modifiers "
            "defaulting to 1.0. At neutral the modifiers change nothing, alpha "
            "is exactly 1.0, and the answer is an UPPER BOUND: every displaced "
            "person seeks public shelter. Hazus's own factors, calibrated on "
            "Red Cross data, run from 0.13 to 0.62 and pull a real answer well "
            "below this one.\n"
            "If you have income, ethnicity, tenure or age distribution for the "
            "study area, put that category's share-weighted mean factor in and "
            "the estimate becomes filtered. If you do not, leave them at 1.0 "
            "and label the result an upper bound - do not read it as a "
            "forecast.\n\n"
            "WHAT IS NOT MODELLED\n"
            "Casualties on bridges and in the commuting population on the "
            "street. Hazus estimates both, but they need a bridge layer with "
            "damage states and a count of people on the street, neither of "
            "which PlanX has, so they are left out rather than approximated. "
            "Repair cost and downtime are out of scope for the same reason.\n\n"
            "ORDERS OF MAGNITUDE, NOT COUNTS\n"
            "Hazus's casualty rates were fitted to US earthquakes and its "
            "shelter factors to US Red Cross shelter data. The damage "
            "probabilities feeding it carry the same caveat, inherited from the "
            "debris tool. Use the output to compare districts and scenarios and "
            "to size a response, not to announce a death toll.\n\n"
            "OUTPUT\n"
            "One feature per building: the occupancy class and building type "
            "used, the occupant count, expected casualties at each of the four "
            "severities, their total, displaced households, and the number of "
            "people needing public shelter. The run log carries the regional "
            "totals and states which modifiers were in force.\n\n"
            "How to read the results\n"
            "- cas_total is dominated by severity 1, the treatable injuries, "
            "so a map of it is a map of injuries and not of deaths. Map "
            "cas_sev4 on its own when the question is life safety: the two "
            "maps disagree about which districts are worst.\n"
            "- The number is an expectation, not a whole number of people. "
            "0.3 expected severity-4 casualties means a small probability of "
            "one death, not a third of a person. Read district totals and "
            "compare districts, not the per-building fraction.\n"
            "- Run the same buildings at 2 a.m. and at 2 p.m. Time of day "
            "usually moves the answer more than the magnitude does: a school "
            "is empty at 2 a.m. and a hotel is nearly empty at 2 p.m.\n"
            "- public_shelter is an UPPER BOUND while the four shelter "
            "modifiers are neutral, because neutral means every displaced "
            "person seeks public shelter. Say that on the slide. Hazus's own "
            "factors run from 0.13 to 0.62.\n"
            "- displaced_hh and public_shelter are different questions. The "
            "first is how many households lose their home; the second is how "
            "many turn up at a publicly provided shelter. Most displaced "
            "households go to family, friends or a hotel.\n\n"
            "Using the results: rank districts by cas_sev2 against hospital "
            "capacity for the medical response, by cas_sev4 for life safety "
            "and by displaced_hh for the housing recovery plan; overlay the "
            "output on the debris tool's navigable core to find the casualties "
            "rescuers cannot reach; and re-run at the other scenario times to "
            "separate how much of the total is timing from how much is "
            "construction."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.BUILDINGS,
            self.tr("Buildings (the debris tool's output, or any layer with the four damage probabilities)"),
            [QgsProcessing.SourceType.TypeVectorPolygon,
             QgsProcessing.SourceType.TypeVectorPoint]))
        self.addParameter(QgsProcessingParameterField(
            self.FLOOR_FIELD, self.tr("Floor count field (sets the building's height class)"),
            parentLayerParameterName=self.BUILDINGS,
            type=QgsProcessingParameterField.DataType.Numeric, optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.AREA_FIELD,
            self.tr("Footprint area field (only needed for point buildings; "
                    "the debris tool's footprint_area)"),
            parentLayerParameterName=self.BUILDINGS,
            type=QgsProcessingParameterField.DataType.Numeric, optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.DAMAGE_STATE_FIELD,
            self.tr("Damage state field (fallback when the four probability columns are absent)"),
            parentLayerParameterName=self.BUILDINGS, optional=True))
        self.addParameter(QgsProcessingParameterEnum(
            self.BUILDING_TYPE,
            self.tr("Building type (Hazus type; must match the one the damage run used)"),
            options=[self.tr("{0} - {1}").format(code, label)
                     for code, label in seismic.BUILDING_TYPES],
            defaultValue=0))
        self.addParameter(QgsProcessingParameterEnum(
            self.TIME_OF_DAY, self.tr("Scenario time (who is in the building)"),
            options=[self.tr(label) for _key, label in impact.SCENARIO_TIMES],
            defaultValue=0))
        self.addParameter(QgsProcessingParameterEnum(
            self.OCCUPANCY,
            self.tr("Occupancy class for every building without an occupancy field"),
            options=[self.tr(label) for _key, label in impact.OCCUPANCY_CLASSES],
            defaultValue=0))
        self.addParameter(QgsProcessingParameterField(
            self.OCCUPANCY_FIELD,
            self.tr("Occupancy field (text: residential, commercial, school, industrial, hotel)"),
            parentLayerParameterName=self.BUILDINGS, optional=True))

        self.addParameter(QgsProcessingParameterEnum(
            self.OCCUPANCY_SOURCE, self.tr("Occupant count comes from"),
            options=[
                self.tr("A population field on the buildings"),
                self.tr("Floor area divided by an area per occupant"),
            ], defaultValue=1))
        self.addParameter(QgsProcessingParameterField(
            self.POPULATION_FIELD, self.tr("Population field (people in the building)"),
            parentLayerParameterName=self.BUILDINGS,
            type=QgsProcessingParameterField.DataType.Numeric, optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.AREA_PER_OCCUPANT,
            self.tr("Area per occupant (m2 of floor area; this tool's screening value, not a Hazus figure)"),
            type=QgsProcessingParameterNumber.Type.Double, minValue=1.0, maxValue=500.0,
            defaultValue=self.DEFAULT_AREA_PER_OCCUPANT))

        self.addParameter(QgsProcessingParameterField(
            self.UNITS_FIELD,
            self.tr("Dwelling units field (blank: 1 for a residential building, 0 otherwise)"),
            parentLayerParameterName=self.BUILDINGS,
            type=QgsProcessingParameterField.DataType.Numeric, optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.HOUSEHOLD_RATE,
            self.tr("Households per dwelling unit (Hazus occupancy rate)"),
            type=QgsProcessingParameterNumber.Type.Double, minValue=0.1, maxValue=1.0,
            defaultValue=1.0))

        for parameter, key, label in (
            (self.WEIGHT_INCOME, "income", "income"),
            (self.WEIGHT_ETHNICITY, "ethnicity", "ethnicity"),
            (self.WEIGHT_OWNERSHIP, "ownership", "ownership"),
            (self.WEIGHT_AGE, "age", "age"),
        ):
            self.addParameter(QgsProcessingParameterNumber(
                parameter,
                self.tr("Shelter weighting - {0} (Hazus Table 13-2)").format(label),
                type=QgsProcessingParameterNumber.Type.Double, minValue=0.0, maxValue=1.0,
                defaultValue=impact.SHELTER_CATEGORY_WEIGHTS[key]))

        for parameter, label in (
            (self.MOD_INCOME, "income"),
            (self.MOD_ETHNICITY, "ethnicity"),
            (self.MOD_OWNERSHIP, "ownership"),
            (self.MOD_AGE, "age"),
        ):
            self.addParameter(QgsProcessingParameterNumber(
                parameter,
                self.tr("Shelter modifier - {0} (share-weighted mean of Hazus Table 13-3; 1.0 = neutral)").format(label),
                type=QgsProcessingParameterNumber.Type.Double, minValue=0.0, maxValue=2.0,
                defaultValue=impact.NEUTRAL_SHELTER_MODIFIER))

        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT, self.tr("Building impact (casualties and shelter need)")))

    # ------------------------------------------------------------------ #
    # Input resolution
    # ------------------------------------------------------------------ #
    @staticmethod
    def output_fields(base=None):
        """The columns appended to the incoming building schema, in order."""
        return PlanXAlgorithm.make_fields(
            ("occ_class", STRING),
            ("bldg_type", STRING),
            ("occupants", DOUBLE),
            ("cas_sev1", DOUBLE),
            ("cas_sev2", DOUBLE),
            ("cas_sev3", DOUBLE),
            ("cas_sev4", DOUBLE),
            ("cas_total", DOUBLE),
            ("displaced_hh", DOUBLE),
            ("public_shelter", DOUBLE),
            base=base,
        )

    def _damage_columns(self, fields, feedback):
        """Resolve the damage input.

        Returns ``(mode, columns, state_field)`` where ``mode`` is
        ``"distribution"`` when all four probability columns are present and
        ``"certainty"`` when a single damage-state column is used instead.

        The absence of both is an error rather than a silent zero: a casualty
        model run on columns it cannot read produces zeros, and a zero
        casualty count is indistinguishable from a good outcome.
        """
        lookup = {field.name().lower(): field.name() for field in fields}
        present = {state: lookup[name] for state, name in self.PROBABILITY_COLUMNS
                   if name in lookup}
        if len(present) == len(self.PROBABILITY_COLUMNS):
            return "distribution", present, ""

        named = self.parameterAsString(self._parameters, self.DAMAGE_STATE_FIELD,
                                       self._context)
        if named and named not in fields.names():
            raise QgsProcessingException(
                f"Damage state field '{named}' is not in the buildings layer.")
        if not named:
            named = next((lookup[name] for name in self.DAMAGE_STATE_FALLBACKS
                          if name in lookup), "")
        if not named:
            expected = ", ".join(name for _state, name in self.PROBABILITY_COLUMNS)
            raise QgsProcessingException(
                "The buildings layer carries neither all four damage-state "
                f"probability columns ({expected}) nor a damage-state column. "
                "Point this tool at the output of 'Seismic Collapse and Debris "
                "Spread', or name a damage-state column under 'Damage state "
                "field'.")
        if present:
            feedback.pushWarning(
                "Only some of the damage-state probability columns are present "
                f"({', '.join(sorted(present.values()))}); using the damage-state "
                f"column '{named}' as a certainty instead. The distribution is "
                "lost, and with it most of what this tool measures.")
        else:
            feedback.pushInfo(
                f"Damage input: the damage-state column '{named}'. Every building "
                "is treated as certainly being in the state it names; the four "
                "probability columns give the expected distribution instead.")
        return "certainty", {}, named

    def _occupancies(self, fields, features, default, feedback):
        """Per-feature occupancy class, from the selected field when there is one."""
        name = self.parameterAsString(self._parameters, self.OCCUPANCY_FIELD,
                                      self._context)
        if not name:
            return [default] * len(features), False
        if name not in fields.names():
            raise QgsProcessingException(
                f"Occupancy field '{name}' is not in the buildings layer.")
        index = fields.indexFromName(name)
        names, unmatched = [], set()
        for feature in features:
            raw = feature.attributes()[index]
            text = "" if raw is None else str(raw).strip()
            resolved = impact.occupancy_class(text) if text else None
            if resolved is None:
                if text:
                    unmatched.add(text)
                names.append(default)
            else:
                names.append(resolved)
        if unmatched:
            listed = ", ".join(sorted(unmatched)[:8])
            feedback.pushWarning(
                f"Occupancy field '{name}': {len(unmatched)} value(s) matched no "
                f"Hazus occupancy class and fell back to '{default}': {listed}"
                + (" ..." if len(unmatched) > 8 else "")
                + ". Recognised words are residential, commercial, school or "
                  "college, industrial or factory, hotel.")
        return names, True

    @staticmethod
    def _one_hot(features, index, state_field):
        """A certainty distribution read from a damage-state column."""
        probabilities = {state: np.zeros(len(features), dtype=np.float64)
                         for state in seismic.DAMAGE_STATES}
        for i, feature in enumerate(features):
            raw = feature.attributes()[index]
            text = "" if raw is None else str(raw).strip().lower()
            if text not in probabilities:
                raise QgsProcessingException(
                    f"Damage state '{raw}' in column '{state_field}' is not one "
                    f"of {', '.join(seismic.DAMAGE_STATES)}.")
            probabilities[text][i] = 1.0
        return probabilities

    def _index(self, fields, parameter, label):
        """Field index behind a field parameter, validated, or -1 when unset."""
        name = self.parameterAsString(self._parameters, parameter, self._context)
        if not name:
            return -1
        index = fields.indexFromName(name)
        if index < 0:
            raise QgsProcessingException(
                f"{label} field '{name}' is not in the buildings layer.")
        return index

    def _area_column(self, fields):
        """(index, name) of the footprint-area column to fall back on.

        A named parameter wins. With none named, the auto-detection list is
        walked in order, so the debris -> casualties chain runs without the
        user picking anything: ``planx:seismicdebris`` writes ``footprint_area``
        and the tool downstream of it should not need to be told so.

        Returns ``(-1, "")`` when there is no such column, which is the normal
        case for a polygon layer - there the geometry is the footprint.
        """
        name = self.parameterAsString(self._parameters, self.AREA_FIELD,
                                      self._context)
        if name:
            index = fields.indexFromName(name)
            if index < 0:
                raise QgsProcessingException(
                    f"Footprint area field '{name}' is not in the buildings "
                    "layer.")
            return index, name
        for candidate in self.AREA_FALLBACKS:
            index = fields.indexFromName(candidate)
            if index >= 0:
                return index, candidate
        return -1, ""

    @staticmethod
    def _tally(values):
        """Value -> count, for the run log."""
        result = {}
        for value in values:
            key = str(value)
            result[key] = result.get(key, 0) + 1
        return result

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
        buildings = self.parameterAsSource(parameters, self.BUILDINGS, context)
        if buildings is None:
            raise QgsProcessingException("Please provide a Buildings layer.")
        self.require_projected(buildings, "Buildings")

        features = [f for f in buildings.getFeatures() if f.hasGeometry()]
        if not features:
            raise QgsProcessingException("No usable building features found.")
        n = len(features)
        fields = buildings.fields()

        mode, columns, state_field = self._damage_columns(fields, feedback)
        state_index = fields.indexFromName(state_field) if state_field else -1

        default_occupancy = impact.OCCUPANCY_CLASSES_KEYS[
            self.parameterAsEnum(parameters, self.OCCUPANCY, context)]
        occupancies, from_field = self._occupancies(
            fields, features, default_occupancy, feedback)
        if not from_field:
            feedback.pushInfo(
                f"Occupancy: every building is treated as '{default_occupancy}'. A "
                "city is not one occupancy class - give an occupancy field to "
                "separate the housing from the schools, shops and factories.")

        floor_index = self._index(fields, self.FLOOR_FIELD, "Floor count")
        population_index = self._index(fields, self.POPULATION_FIELD, "Population")
        units_index = self._index(fields, self.UNITS_FIELD, "Dwelling units")
        area_index, area_field = self._area_column(fields)
        # Ground square metres for the geometry path: the occupant count is a
        # density times this area, so a raw QgsGeometry.area() would report
        # 1.76x the population on EPSG:3857 at 41 N and 10.76x on a state-plane
        # layer in feet, with every casualty and shelter number scaled to match.
        ground = _units.GroundUnits(buildings.sourceCrs(), context.transformContext())

        floors = np.ones(n, dtype=np.float64)
        areas = np.zeros(n, dtype=np.float64)
        supplied = np.zeros(n, dtype=np.float64)
        units = np.zeros(n, dtype=np.float64)
        area_from_geometry = 0
        area_from_column = 0
        for i, feature in enumerate(features):
            attributes = feature.attributes()
            area = ground.area(feature.geometry())
            if area > 0.0:
                area_from_geometry += 1
            elif area_index >= 0:
                # A point building has no area of its own. planx:seismicdebris
                # writes building centroids, so the field it also writes is the
                # only footprint area left in the chain.
                area = max(0.0, _float_or(attributes[area_index], 0.0))
                if area > 0.0:
                    area_from_column += 1
            areas[i] = area
            if floor_index >= 0:
                floors[i] = max(1.0, _float_or(attributes[floor_index], 1.0))
            if population_index >= 0:
                supplied[i] = max(0.0, _float_or(attributes[population_index], 0.0))
            if units_index >= 0:
                units[i] = max(0.0, _float_or(attributes[units_index], 0.0))
            elif occupancies[i] == "Residential":
                # No dwelling-unit column: a residential building is one
                # dwelling, which is Hazus's RES1. A block of flats needs the
                # column, and the run log says how many units were counted.
                units[i] = 1.0

        if mode == "distribution":
            probabilities = {}
            for state, name in columns.items():
                index = fields.indexFromName(name)
                probabilities[state] = np.array(
                    [max(0.0, _float_or(f.attributes()[index], 0.0))
                     for f in features], dtype=np.float64)
            # The four columns are the damaged states; the undamaged share is
            # their complement. Filling it here rather than leaving the four
            # states on their own is what makes the sum-to-1 check below mean
            # the whole distribution, and it is why the engine can index the
            # distribution by state without a missing-key branch.
            probabilities = impact.fill_undamaged(probabilities)
            total = sum(probabilities[state] for state in seismic.DAMAGE_STATES)
            stray = int(np.count_nonzero(np.abs(total - 1.0) > 1e-6))
            if stray:
                feedback.pushWarning(
                    f"{stray} building(s) carry damage-state probabilities that do "
                    "not sum to 1.0. They are used as given, so those buildings' "
                    "casualty counts are scaled accordingly.")
        else:
            probabilities = self._one_hot(features, state_index, state_field)

        source = self.parameterAsEnum(parameters, self.OCCUPANCY_SOURCE, context)
        if source == self.SOURCE_FIELD:
            if population_index < 0:
                raise QgsProcessingException(
                    "'Occupant count comes from' is set to the population field but "
                    "no field is selected. Pick one, or switch to the floor-area "
                    "source.")
            occupants = supplied
            missing = int(np.count_nonzero(supplied <= 0.0))
            feedback.pushInfo(
                f"Occupants: population field '{fields[population_index].name()}'"
                + (f"; {missing} building(s) carry no usable population and are "
                   "counted as empty." if missing else "."))
        else:
            area_per_occupant = self.parameterAsDouble(
                parameters, self.AREA_PER_OCCUPANT, context)
            usable = int(np.count_nonzero(areas > 0.0))
            if not usable:
                raise QgsProcessingException(
                    "Not one building carries a footprint area, so the floor-area "
                    "occupant estimate would be zero everywhere and the run would "
                    "report a city of nobody. Areas come from the geometry, and "
                    "point buildings - which is what planx:seismicdebris writes, "
                    "as building centroids - have none. Either give a footprint "
                    "area field (the debris tool writes footprint_area), or set "
                    "'Occupant count comes from' to a population field.")
            if usable < n:
                feedback.pushWarning(
                    f"{n - usable} of {n} building(s) carry no footprint area and "
                    "are counted as empty. Point buildings have no area of their "
                    "own; give a footprint area field to read one from a column.")
            if area_from_column:
                feedback.pushInfo(
                    f"Footprint area: {area_from_geometry} building(s) from their "
                    f"geometry, {area_from_column} from column '{area_field}'.")
            occupants = impact.occupants_from_floor_area(
                areas, floors, area_per_occupant)
            feedback.pushWarning(
                "Occupants are derived from floor area (footprint x storeys / "
                f"{area_per_occupant:g} m2 per occupant). That divisor is this "
                "tool's screening assumption, not a Hazus figure. A population "
                "field gives a real answer; this gives a plausible one.")

        building_type = seismic.BUILDING_TYPES[
            self.parameterAsEnum(parameters, self.BUILDING_TYPE, context)][0]
        labels = seismic.resolve_building_type(building_type, floors)
        time_key = impact.SCENARIO_TIMES[
            self.parameterAsEnum(parameters, self.TIME_OF_DAY, context)][0]

        weights = tuple(self.parameterAsDouble(parameters, parameter, context)
                        for parameter in (self.WEIGHT_INCOME, self.WEIGHT_ETHNICITY,
                                          self.WEIGHT_OWNERSHIP, self.WEIGHT_AGE))
        modifiers = tuple(self.parameterAsDouble(parameters, parameter, context)
                          for parameter in (self.MOD_INCOME, self.MOD_ETHNICITY,
                                            self.MOD_OWNERSHIP, self.MOD_AGE))
        alpha = impact.shelter_alpha(weights, modifiers)
        if abs(sum(weights) - 1.0) > 1e-9:
            feedback.pushWarning(
                f"The four shelter category weights sum to {sum(weights):.3f}, not "
                "1.0. Hazus requires them to sum to 1.0 for alpha to be a share of "
                "the displaced population; as given, the shelter estimate is "
                f"scaled by {alpha:.3f}.")

        household_rate = self.parameterAsDouble(parameters, self.HOUSEHOLD_RATE, context)
        casualty = impact.casualties(probabilities, labels, occupants,
                                     occupancies, time_key)
        shelter = impact.shelter(probabilities, occupants, units,
                                 household_rate, alpha)

        out_fields = self.output_fields(fields)
        sink, dest = self.parameterAsSink(
            parameters, self.OUT, context, out_fields, buildings.wkbType(),
            buildings.sourceCrs())
        if sink is None:
            raise QgsProcessingException("Could not create the output layer.")

        n_base = len(fields)
        totals = casualty["total"]
        for i, feature in enumerate(features):
            if feedback.isCanceled():
                break
            out_feature = QgsFeature(out_fields)
            out_feature.setGeometry(feature.geometry())
            out_feature.setAttributes(list(feature.attributes())[:n_base] + [
                occupancies[i], str(labels[i]), float(occupants[i]),
                float(totals[i][0]), float(totals[i][1]),
                float(totals[i][2]), float(totals[i][3]),
                float(totals[i].sum()),
                float(shelter["displaced_households"][i]),
                float(shelter["public_shelter"][i]),
            ])
            sink.addFeature(out_feature, QgsFeatureSink.Flag.FastInsert)
            feedback.setProgress(int((i + 1) / n * 100))

        self._report(feedback, n, mode, state_field, labels, occupants,
                     occupancies, time_key, totals, shelter, alpha, modifiers,
                     units, from_field)
        return {self.OUT: dest}

    def _report(self, feedback, n, mode, state_field, labels, occupants,
                occupancies, time_key, totals, shelter, alpha, modifiers,
                units, from_field):
        """Say what was modelled, and how much of it is assumption."""
        feedback.pushInfo(
            "Impact model: Hazus 6.1 Section 12 (casualties) and Section 13 "
            f"(shelter), run per building on {n} feature(s). Scenario time "
            f"{dict(impact.SCENARIO_TIMES)[time_key]}."
        )
        feedback.pushInfo(
            f"Damage input: {mode} ("
            + (f"damage-state column '{state_field}'" if mode == "certainty"
               else "the four probability columns")
            + "). Casualty rates in use: "
            + ", ".join(f"{label} x{count}" for label, count in
                        sorted(self._tally(labels).items()))
            + ". This type must match the one the damage run used, or the rates "
              "belong to a different building."
        )
        feedback.pushInfo(
            f"Population modelled: {float(np.sum(occupants)):,.0f} people across "
            f"{n} feature(s); "
            + ", ".join(f"{name} x{count}" for name, count in
                        sorted(self._tally(occupancies).items()))
            + ("" if from_field else " (one occupancy class for the whole run)")
            + "."
        )
        feedback.pushInfo(
            "Expected casualties: "
            + ", ".join(f"severity {index + 1} {totals[:, index].sum():,.1f}"
                        for index in range(4))
            + f"; total {totals.sum():,.1f}."
        )
        feedback.pushInfo(
            f"Shelter: {float(np.sum(shelter['displaced_households'])):,.1f} "
            f"displaced household(s) from {float(np.sum(units)):,.0f} dwelling "
            f"unit(s); {float(np.sum(shelter['public_shelter'])):,.1f} person(s) "
            f"seeking public shelter at alpha {alpha:.3f}."
        )
        if all(abs(modifier - impact.NEUTRAL_SHELTER_MODIFIER) < 1e-12
               for modifier in modifiers):
            feedback.pushInfo(
                "Shelter modifiers are all neutral (1.0), so every displaced "
                "person is assumed to seek public shelter. That is an upper "
                "bound, not a forecast: Hazus's own Table 13-3 factors run from "
                "0.13 to 0.62. Supply a share-weighted mean for any category you "
                "have real distribution data for."
            )

    def createInstance(self):
        return SeismicImpactAlgorithm()
