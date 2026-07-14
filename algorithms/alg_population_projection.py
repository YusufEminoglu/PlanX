# -*- coding: utf-8 -*-
"""Population Projection: cohort-component (Leslie matrix) from a rate table."""
from __future__ import annotations

import math

import numpy as np

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsFeatureSink,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_POPULATION, INT, PlanXAlgorithm, STRING
from ..engine import population


class PopulationProjectionAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_POPULATION
    ICON = "tool_populationprojection.png"
    INPUT = "INPUT"
    AGE_FIELD = "AGE_FIELD"
    POP_FIELD = "POP_FIELD"
    SURVIVAL_FIELD = "SURVIVAL_FIELD"
    FERTILITY_FIELD = "FERTILITY_FIELD"
    MIGRATION_FIELD = "MIGRATION_FIELD"
    STEPS = "STEPS"
    STEP_YEARS = "STEP_YEARS"
    OUT_PROJECTION = "OUT_PROJECTION"
    OUT_TOTALS = "OUT_TOTALS"

    def name(self):
        return "populationprojection"

    def displayName(self):
        return self.tr("Population Projection (Cohort-Component)")

    def shortHelpString(self):
        return self.tr(
            "Projects an age-structured population forward with the "
            "COHORT-COMPONENT method (a Leslie matrix): each step, every "
            "age group survives into the next at its survival rate, births "
            "(per-capita fertility summed over the groups) refill the "
            "youngest group, and net migration is added on top.\n\n"
            "Feed it a table with one row per age group - ordered youngest "
            "to oldest, equal widths (e.g. 5-year groups, projected in "
            "5-year steps):\n"
            "- population: the start count;\n"
            "- survival: share surviving INTO the next group per step (the "
            "last row's value keeps people in the open-ended final group);\n"
            "- fertility: births per person per step attributed to that "
            "group (0 outside childbearing ages);\n"
            "- net migration (optional): people added (or removed) per "
            "step.\n\n"
            "The projection is single-sex (total population) - the "
            "standard screening form; run it twice with sex-specific rates "
            "for a two-sex projection. Rates stay constant over the "
            "horizon.\n\n"
            "Outputs one row per step x age group, and a per-step totals "
            "table (population, growth, natural change vs migration). "
            "Feed the horizon-year totals to Housing Needs Assessment.\n\n"
            "How to read the results\n"
            "- The AGE STRUCTURE at the horizon matters more than the "
            "total: a flat total can hide a school-age bulge arriving "
            "in step 2 (classrooms needed now) or an over-65 wave "
            "(care, accessibility, smaller households). Chart each "
            "step's rows as a pyramid.\n"
            "- The totals table splits growth into natural change vs "
            "migration - policy can barely move the first and mostly "
            "argues about the second, so scenario-test migration, not "
            "fertility.\n"
            "- Constant rates make this a 'what current trends imply' "
            "projection, not a forecast: run low/mid/high migration "
            "variants and plan to the range, not the line.\n\n"
            "Using the results: the horizon total feeds Housing Needs; "
            "the 5-14 rows size school demand per step (feed Facility "
            "Adequacy); the 65+ trajectory drives accessibility and "
            "health-facility standards; when a plan claims a population "
            "target, check which migration assumption would actually "
            "deliver it - that is usually the debate."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT, self.tr("Age-group table (youngest to oldest)"),
            [QgsProcessing.SourceType.TypeVector]))
        self.addParameter(QgsProcessingParameterField(
            self.AGE_FIELD, self.tr("Age-group label field"),
            parentLayerParameterName=self.INPUT))
        self.addParameter(QgsProcessingParameterField(
            self.POP_FIELD, self.tr("Population field"),
            parentLayerParameterName=self.INPUT,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterField(
            self.SURVIVAL_FIELD, self.tr("Survival rate field (per step)"),
            parentLayerParameterName=self.INPUT,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterField(
            self.FERTILITY_FIELD, self.tr("Fertility field (births per person per step)"),
            parentLayerParameterName=self.INPUT,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterField(
            self.MIGRATION_FIELD,
            self.tr("Net migration field (per step, optional)"),
            parentLayerParameterName=self.INPUT, optional=True,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.STEPS, self.tr("Projection steps"),
            QgsProcessingParameterNumber.Type.Integer, 4, minValue=1, maxValue=40))
        self.addParameter(QgsProcessingParameterNumber(
            self.STEP_YEARS, self.tr("Years per step (labels only)"),
            QgsProcessingParameterNumber.Type.Integer, 5, minValue=1, maxValue=25))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_PROJECTION, self.tr("Projection (step x age group)"),
            type=QgsProcessing.SourceType.TypeVector))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_TOTALS, self.tr("Per-step totals"),
            type=QgsProcessing.SourceType.TypeVector))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        age_f = self.parameterAsString(parameters, self.AGE_FIELD, context)
        pop_f = self.parameterAsString(parameters, self.POP_FIELD, context)
        sur_f = self.parameterAsString(parameters, self.SURVIVAL_FIELD, context)
        fer_f = self.parameterAsString(parameters, self.FERTILITY_FIELD, context)
        mig_f = self.parameterAsString(parameters, self.MIGRATION_FIELD, context)
        steps = self.parameterAsInt(parameters, self.STEPS, context)
        step_years = self.parameterAsInt(parameters, self.STEP_YEARS, context)

        fields = source.fields()
        idx = {k: fields.lookupField(v) for k, v in
               (("age", age_f), ("pop", pop_f), ("sur", sur_f),
                ("fer", fer_f))}
        mig_idx = fields.lookupField(mig_f) if mig_f else -1

        labels, pop, sur, fer, mig = [], [], [], [], []
        for f in source.getFeatures():
            attrs = f.attributes()

            def num(i, default=None):
                try:
                    v = float(attrs[i])
                    return v if math.isfinite(v) else default
                except (TypeError, ValueError):
                    return default

            p = num(idx["pop"])
            s = num(idx["sur"])
            b = num(idx["fer"])
            if p is None or s is None or b is None:
                raise QgsProcessingException(
                    "Every age-group row needs numeric population, survival "
                    "and fertility values.")
            labels.append(str(attrs[idx["age"]]))
            pop.append(max(0.0, p))
            sur.append(min(1.0, max(0.0, s)))
            fer.append(max(0.0, b))
            mig.append(num(mig_idx, 0.0) if mig_idx >= 0 else 0.0)
        if len(pop) < 2:
            raise QgsProcessingException(
                "At least two age-group rows are needed.")

        migration = np.asarray(mig) if mig_idx >= 0 else None
        proj = population.cohort_projection(pop, sur, fer,
                                            migration=migration, steps=steps)

        p_fields = self.make_fields(
            ("step", INT), ("year_offset", INT), ("age_group", STRING),
            ("population", DOUBLE))
        p_sink, p_dest = self.parameterAsSink(
            parameters, self.OUT_PROJECTION, context, p_fields,
            QgsWkbTypes.Type.NoGeometry, QgsCoordinateReferenceSystem())
        for s in range(proj.shape[0]):
            for a, lab in enumerate(labels):
                feat = QgsFeature(p_fields)
                feat.setAttributes([s, s * step_years, lab,
                                    round(float(proj[s, a]), 2)])
                p_sink.addFeature(feat, QgsFeatureSink.Flag.FastInsert)

        t_fields = self.make_fields(
            ("step", INT), ("year_offset", INT), ("population", DOUBLE),
            ("growth_pct", DOUBLE), ("net_migration", DOUBLE))
        t_sink, t_dest = self.parameterAsSink(
            parameters, self.OUT_TOTALS, context, t_fields,
            QgsWkbTypes.Type.NoGeometry, QgsCoordinateReferenceSystem())
        totals = proj.sum(axis=1)
        mig_total = float(migration.sum()) if migration is not None else 0.0
        for s in range(proj.shape[0]):
            growth = (100.0 * (totals[s] / totals[s - 1] - 1.0)
                      if s > 0 and totals[s - 1] > 0 else 0.0)
            feat = QgsFeature(t_fields)
            feat.setAttributes([s, s * step_years,
                                round(float(totals[s]), 2),
                                round(growth, 3),
                                mig_total if s > 0 else 0.0])
            t_sink.addFeature(feat, QgsFeatureSink.Flag.FastInsert)

        feedback.pushInfo(self.tr(
            f"{len(labels)} age groups projected {steps} step(s) "
            f"({steps * step_years} years): {totals[0]:,.0f} -> "
            f"{totals[-1]:,.0f} "
            f"({100.0 * (totals[-1] / totals[0] - 1.0):+.1f} percent)."
            if totals[0] > 0 else "Projection complete."))
        oldest_share = proj[-1, -1] / totals[-1] * 100.0 if totals[-1] > 0 else 0.0
        feedback.pushInfo(self.tr(
            f"Share of the oldest group at the horizon: {oldest_share:.1f} "
            "percent."))
        return {self.OUT_PROJECTION: p_dest, self.OUT_TOTALS: t_dest}

    def createInstance(self):
        return PopulationProjectionAlgorithm()
