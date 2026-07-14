# -*- coding: utf-8 -*-
"""Urban Growth Simulation: constrained cellular-automaton expansion."""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsProcessingException,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterRasterLayer,
)

from .base import GROUP_GROWTH, PlanXAlgorithm
from ._raster import read_dsm, write_raster
from ..engine import growth


class GrowthSimAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_GROWTH
    ICON = "tool_growthsim.png"
    SEED = "SEED"
    SUITABILITY = "SUITABILITY"
    CONSTRAINTS = "CONSTRAINTS"
    DEMAND_HA = "DEMAND_HA"
    ITERATIONS = "ITERATIONS"
    NEIGH_WEIGHT = "NEIGH_WEIGHT"
    BASE = "BASE"
    RNG_SEED = "RNG_SEED"
    OUTPUT = "OUTPUT"

    def name(self):
        return "growthsim"

    def displayName(self):
        return self.tr("Urban Growth Simulation (CA)")

    def shortHelpString(self):
        return self.tr(
            "Where will the city grow if the trend continues? A "
            "constrained CELLULAR-AUTOMATON growth model in the SLEUTH "
            "tradition, deliberately simple and fully deterministic:\n\n"
            "each step, every non-urban unconstrained cell scores\n"
            "suitability x (base + weight x urban share of its 8 "
            "neighbours),\n"
            "and the top-scoring cells convert until the step's share of "
            "the land demand is met. The neighbourhood term makes growth "
            "cling to the existing fabric (edge growth); the base term "
            "lets outstandingly suitable cells leapfrog (spontaneous "
            "growth). Same inputs + same random seed = the same map, in "
            "any process - safe for scenario comparison.\n\n"
            "Inputs: the seed urban mask (any nonzero = urban - e.g. the "
            "urban class of a land-cover raster), a suitability raster "
            "(any scale, normalised internally; take it from Suitability "
            "Lab or your own MCDA), an optional constraints raster "
            "(nonzero = never build: water, parks, hazard zones), the "
            "land demand in hectares (from Housing Needs / Residential "
            "Capacity), and the number of steps.\n\n"
            "Output: a YEAR-OF-CONVERSION raster - 0 for the initial "
            "urban fabric, k for cells converted at step k, NoData for "
            "land still open at the horizon. Style it with a sequential "
            "ramp for the classic growth-ring map.\n\n"
            "How to read the results\n"
            "- This is a WHERE model, not a WHEN forecast: the demand "
            "you typed sets how much converts, the model only chooses "
            "locations. Read step numbers as sequence ('this converts "
            "before that'), not calendar years.\n"
            "- Early-step cells hugging the fabric are trend infill; "
            "isolated early cells are leapfrog seeds - if they appear "
            "where you know pressure exists (a highway exit, a coastal "
            "strip), the suitability surface is speaking; if they look "
            "random, your base term is too high.\n"
            "- The interesting output is CONFLICT: overlay the "
            "converted cells on farmland, flood zones and planned "
            "green wedges - 'the trend consumes 60 ha of the wedge by "
            "step 4' is the sentence that justifies the constraint.\n\n"
            "Using the results: run trend (no constraints) vs plan "
            "(constraints = the plan's no-go areas) with the same "
            "demand - the difference maps exactly what the plan must "
            "resist and where deflected growth lands instead; test "
            "compactness policy by sweeping the neighbourhood weight; "
            "feed the horizon mask back to Sprawl Metrics to score "
            "each scenario's form."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.SEED, self.tr("Seed urban mask (nonzero = urban)")))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.SUITABILITY, self.tr("Development suitability raster")))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.CONSTRAINTS,
            self.tr("Constraints raster (nonzero = never build, optional)"),
            optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.DEMAND_HA, self.tr("Land demand (hectares)"),
            QgsProcessingParameterNumber.Type.Double, 50.0, minValue=0.01))
        self.addParameter(QgsProcessingParameterNumber(
            self.ITERATIONS, self.tr("Growth steps"),
            QgsProcessingParameterNumber.Type.Integer, 5, minValue=1,
            maxValue=100))
        self.addParameter(QgsProcessingParameterNumber(
            self.NEIGH_WEIGHT, self.tr("Neighbourhood weight (edge growth)"),
            QgsProcessingParameterNumber.Type.Double, 1.0, minValue=0.0,
            maxValue=10.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.BASE, self.tr("Base term (leapfrog growth)"),
            QgsProcessingParameterNumber.Type.Double, 0.1, minValue=0.0,
            maxValue=1.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.RNG_SEED, self.tr("Random seed (tie-breaking only)"),
            QgsProcessingParameterNumber.Type.Integer, 0, minValue=0))
        self.addParameter(QgsProcessingParameterRasterDestination(
            self.OUTPUT, self.tr("Year of conversion")))

    def processAlgorithm(self, parameters, context, feedback):
        seed_lyr = self.parameterAsRasterLayer(parameters, self.SEED, context)
        suit_lyr = self.parameterAsRasterLayer(parameters, self.SUITABILITY, context)
        con_lyr = self.parameterAsRasterLayer(parameters, self.CONSTRAINTS, context)
        demand_ha = self.parameterAsDouble(parameters, self.DEMAND_HA, context)
        iterations = self.parameterAsInt(parameters, self.ITERATIONS, context)
        neigh_w = self.parameterAsDouble(parameters, self.NEIGH_WEIGHT, context)
        base = self.parameterAsDouble(parameters, self.BASE, context)
        rng_seed = self.parameterAsInt(parameters, self.RNG_SEED, context)
        out_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        seed_arr, gt, proj, pixel = read_dsm(seed_lyr)
        suit_arr, _g2, _p2, _px2 = read_dsm(suit_lyr)
        if suit_arr.shape != seed_arr.shape:
            raise QgsProcessingException(
                "Seed and suitability rasters differ in size - resample "
                "to one grid first.")
        constraints = None
        if con_lyr is not None:
            con_arr, _g3, _p3, _px3 = read_dsm(con_lyr)
            if con_arr.shape != seed_arr.shape:
                raise QgsProcessingException(
                    "Constraints raster differs in size from the seed.")
            constraints = np.isfinite(con_arr) & (con_arr != 0)

        urban0 = np.isfinite(seed_arr) & (seed_arr != 0)
        cell_ha = pixel * pixel / 10000.0
        demand_cells = int(round(demand_ha / cell_ha))
        open_cells = int((~urban0).sum())
        if demand_cells <= 0:
            raise QgsProcessingException(
                f"The demand of {demand_ha:g} ha is below one cell "
                f"({cell_ha:g} ha) - nothing to grow.")
        if demand_cells > open_cells:
            feedback.pushWarning(self.tr(
                f"Demand of {demand_cells} cells exceeds the {open_cells} "
                "open cells - the growth will saturate."))
        feedback.pushInfo(self.tr(
            f"Seed fabric {float(urban0.sum()) * cell_ha:,.1f} ha; demand "
            f"{demand_ha:g} ha = {demand_cells} cells over {iterations} "
            f"step(s); weight {neigh_w:g}, base {base:g}, seed {rng_seed}."))

        sim = growth.ca_simulate(
            urban0, suit_arr, demand_cells, iterations=iterations,
            constraints=constraints, neigh_weight=neigh_w, base=base,
            rng_seed=rng_seed, cancel=feedback.isCanceled)

        year = sim["year_of"].astype(np.float32)
        write_raster(out_path, year, gt, proj, -1.0)
        for k, n in enumerate(sim["converted"], start=1):
            feedback.pushInfo(self.tr(
                f"Step {k}: {n} cell(s) converted "
                f"({n * cell_ha:,.2f} ha)."))
        grown = float(sum(sim["converted"])) * cell_ha
        feedback.pushInfo(self.tr(
            f"Final urban fabric "
            f"{float(sim['masks'][-1].sum()) * cell_ha:,.1f} ha "
            f"(+{grown:,.1f} ha)."))
        return {self.OUTPUT: out_path}

    def createInstance(self):
        return GrowthSimAlgorithm()
