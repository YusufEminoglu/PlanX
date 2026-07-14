# -*- coding: utf-8 -*-
"""Urban Sprawl Metrics: SDG 11.3.1 LCRPGR + patch structure."""
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
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterLayer,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_GROWTH, PlanXAlgorithm, STRING
from ._raster import read_dsm
from ..engine import growth


class SprawlMetricsAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_GROWTH
    ICON = "tool_sprawlmetrics.png"
    URBAN_T1 = "URBAN_T1"
    URBAN_T2 = "URBAN_T2"
    POP_T1 = "POP_T1"
    POP_T2 = "POP_T2"
    OUT_SUMMARY = "OUT_SUMMARY"

    def name(self):
        return "sprawlmetrics"

    def displayName(self):
        return self.tr("Urban Sprawl Metrics")

    def shortHelpString(self):
        return self.tr(
            "Is the city consuming land faster than it grows people? "
            "Computes the SDG indicator 11.3.1 - the LAND CONSUMPTION "
            "RATE to POPULATION GROWTH RATE ratio:\n\n"
            "LCRPGR = ln(Urban2 / Urban1) / ln(Pop2 / Pop1)\n\n"
            "1.0 means land and population grow in step; above 1 the "
            "footprint outpaces the people - the sprawl signature; below "
            "1 the city densifies.\n\n"
            "Feed two urban-extent rasters (any nonzero = urban; the "
            "urban class of your land-cover maps) and the two population "
            "figures. On top of the SDG ratio it reports the shape of "
            "the horizon-year fabric:\n"
            "- patches: how many separate urban islands;\n"
            "- largest-patch share: how much sits in the contiguous "
            "core (low = fragmentation);\n"
            "- edge density: boundary metres per urban hectare (high = "
            "ragged, scattered growth).\n\n"
            "Everything lands in a metric/value table for the plan "
            "report. Pair with Land-Cover Change Analysis for the full "
            "transition accounting.\n\n"
            "How to read the results\n"
            "- LCRPGR ~1 = land and people in step; 1.5-2 = the common "
            "sprawl range (many cities consume land at twice the pace "
            "of growth); < 1 = densification. Mind the edge cases: with "
            "near-zero population growth the ratio explodes - report "
            "the two raw rates alongside it.\n"
            "- The shape metrics say HOW the land was consumed: rising "
            "patch count + falling largest-share = leapfrog "
            "fragmentation; stable patches + rising edge density = "
            "ragged edge growth; both healthy = compact extension.\n"
            "- Fragmented growth is the expensive kind - every isolated "
            "patch needs its own roads, pipes and bus route; edge "
            "density is a fair proxy for that per-hectare "
            "infrastructure burden.\n\n"
            "Using the results: this is the SDG 11.3.1 reporting tool - "
            "quote LCRPGR with its period and data source; score growth "
            "scenarios from the CA simulation by their horizon "
            "LCRPGR/fragmentation to rank plan alternatives by form, "
            "not just quantity; a compact-growth policy should show up "
            "as falling edge density between successive plan reviews."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.URBAN_T1, self.tr("Urban extent at time 1 (nonzero = urban)")))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.URBAN_T2, self.tr("Urban extent at time 2 (nonzero = urban)")))
        self.addParameter(QgsProcessingParameterNumber(
            self.POP_T1, self.tr("Population at time 1"),
            QgsProcessingParameterNumber.Type.Double, 100000.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.POP_T2, self.tr("Population at time 2"),
            QgsProcessingParameterNumber.Type.Double, 120000.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_SUMMARY, self.tr("Sprawl metrics"),
            type=QgsProcessing.SourceType.TypeVector))

    def processAlgorithm(self, parameters, context, feedback):
        lyr1 = self.parameterAsRasterLayer(parameters, self.URBAN_T1, context)
        lyr2 = self.parameterAsRasterLayer(parameters, self.URBAN_T2, context)
        pop1 = self.parameterAsDouble(parameters, self.POP_T1, context)
        pop2 = self.parameterAsDouble(parameters, self.POP_T2, context)

        a1, _g1, _p1, pixel1 = read_dsm(lyr1)
        a2, _g2, _p2, pixel2 = read_dsm(lyr2)
        if a1.shape != a2.shape:
            raise QgsProcessingException(
                f"The rasters differ in size ({a1.shape} vs {a2.shape}) - "
                "resample to a common grid first.")
        m1 = np.isfinite(a1) & (a1 != 0)
        m2 = np.isfinite(a2) & (a2 != 0)
        if not m1.any() or not m2.any():
            raise QgsProcessingException(
                "One of the rasters contains no urban cell.")
        if m2.sum() >= 40000:
            feedback.pushInfo(self.tr(
                "Large urban mask - the patch labelling may take a while."))

        sm = growth.sprawl_metrics(m1, m2, pop1, pop2, pixel=pixel1)

        fields = self.make_fields(("metric", STRING), ("value", DOUBLE))
        sink, dest = self.parameterAsSink(
            parameters, self.OUT_SUMMARY, context, fields,
            QgsWkbTypes.Type.NoGeometry, QgsCoordinateReferenceSystem())
        rows = [
            ("Urban area t1 (ha)", sm["area_t1"] / 10000.0),
            ("Urban area t2 (ha)", sm["area_t2"] / 10000.0),
            ("Urban growth (pct)",
             100.0 * (sm["area_t2"] / sm["area_t1"] - 1.0)),
            ("Population t1", pop1),
            ("Population t2", pop2),
            ("Population growth (pct)", 100.0 * (pop2 / pop1 - 1.0)),
            ("Land consumption rate (LCR)", sm["lcr"]),
            ("Population growth rate (PGR)", sm["pgr"]),
            ("LCRPGR (SDG 11.3.1)", sm["lcrpgr"]),
            ("Urban patches (t2)", float(sm["n_patches"])),
            ("Largest patch share", sm["largest_share"]),
            ("Edge density (m per ha)",
             sm["edge_length"] / (sm["area_t2"] / 10000.0)),
        ]
        for metric, value in rows:
            feat = QgsFeature(fields)
            feat.setAttributes([
                metric,
                None if not math.isfinite(value) else round(float(value), 4)])
            sink.addFeature(feat, QgsFeatureSink.Flag.FastInsert)

        if math.isfinite(sm["lcrpgr"]):
            verdict = ("land outpaces people - sprawl signature"
                       if sm["lcrpgr"] > 1.0 else "densifying")
            feedback.pushInfo(self.tr(
                f"LCRPGR {sm['lcrpgr']:.3f} ({verdict}); "
                f"{sm['n_patches']} patch(es), largest holds "
                f"{100.0 * sm['largest_share']:.1f} percent."))
        else:
            feedback.pushWarning(self.tr(
                "LCRPGR undefined (zero growth on one side)."))
        return {self.OUT_SUMMARY: dest}

    def createInstance(self):
        return SprawlMetricsAlgorithm()
