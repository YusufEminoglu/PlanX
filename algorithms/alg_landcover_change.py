# -*- coding: utf-8 -*-
"""Land-Cover Change Analysis: the transition matrix of two class rasters."""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsFeatureSink,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterString,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_GROWTH, INT, PlanXAlgorithm, STRING
from ._raster import read_dsm
from ..engine import growth


def parse_class_names(text):
    names = {}
    for token in str(text).replace(";", ",").split(","):
        token = token.strip()
        if not token:
            continue
        code, _, label = token.partition("=")
        try:
            names[int(float(code.strip()))] = label.strip() or code.strip()
        except ValueError:
            raise ValueError(f"class names need 'code=label': '{token}'")
    return names


class LandCoverChangeAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_GROWTH
    ICON = "tool_landcoverchange.png"
    RASTER_T1 = "RASTER_T1"
    RASTER_T2 = "RASTER_T2"
    CLASS_NAMES = "CLASS_NAMES"
    OUT_MATRIX = "OUT_MATRIX"
    OUT_CLASSES = "OUT_CLASSES"

    def name(self):
        return "landcoverchange"

    def displayName(self):
        return self.tr("Land-Cover Change Analysis")

    def shortHelpString(self):
        return self.tr(
            "What became what between two dates? Cross-tabulates two "
            "land-cover class rasters cell by cell into the classic "
            "TRANSITION MATRIX - the accounting table behind every "
            "urban-expansion or deforestation figure.\n\n"
            "The rasters must share extent and cell size (resample first "
            "if not; the tool checks). NoData in either date drops the "
            "cell. Class codes may be labelled ('1=Urban, 2=Forest, "
            "3=Water') for readable outputs.\n\n"
            "Outputs:\n"
            "- Transitions: one row per from-class x to-class pair with "
            "cell count and hectares (the diagonal is persistence);\n"
            "- Class summary: per class the area at both dates, gains, "
            "losses, persistence and net change in hectares.\n\n"
            "The log names the single largest conversion - usually the "
            "headline of the study. Feed the same rasters to Urban Sprawl "
            "Metrics for the SDG 11.3.1 view, or use the urban class as "
            "the seed of the Urban Growth Simulation.\n\n"
            "How to read the results\n"
            "- Read the matrix by its biggest OFF-DIAGONAL cells: those "
            "are the actual land conversions ('farmland -> urban, 412 "
            "ha' is the sentence the study exists for). The diagonal is "
            "stability - a small diagonal share means the landscape is "
            "churning.\n"
            "- In the class summary, gains and losses can both be large "
            "while net is ~0: that is displacement (forest lost here, "
            "planted there), a very different story from simple loss - "
            "never report net alone.\n"
            "- Impossible transitions (water -> forest in five years, "
            "urban -> farmland at scale) are usually CLASSIFICATION "
            "error, not change: their share of the matrix estimates "
            "your data's noise floor - read real findings against it.\n\n"
            "Using the results: compare where growth actually went "
            "(urban gains) against where the plan intended it - the "
            "mismatch maps plan violation or leapfrog pressure; use "
            "persistence of protected classes as an enforcement audit; "
            "the urban row/column feeds Sprawl Metrics and the growth "
            "simulation directly."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.RASTER_T1, self.tr("Land cover at time 1 (class raster)")))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.RASTER_T2, self.tr("Land cover at time 2 (class raster)")))
        self.addParameter(QgsProcessingParameterString(
            self.CLASS_NAMES,
            self.tr("Class labels 'code=label, ...' (optional)"),
            "", optional=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_MATRIX, self.tr("Transitions"),
            type=QgsProcessing.SourceType.TypeVector))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_CLASSES, self.tr("Class summary"),
            type=QgsProcessing.SourceType.TypeVector))

    def processAlgorithm(self, parameters, context, feedback):
        lyr1 = self.parameterAsRasterLayer(parameters, self.RASTER_T1, context)
        lyr2 = self.parameterAsRasterLayer(parameters, self.RASTER_T2, context)
        names_text = self.parameterAsString(parameters, self.CLASS_NAMES, context)
        try:
            labels = parse_class_names(names_text) if names_text.strip() else {}
        except ValueError as exc:
            raise QgsProcessingException(str(exc))

        a1, gt1, _p1, pixel1 = read_dsm(lyr1)
        a2, gt2, _p2, pixel2 = read_dsm(lyr2)
        if a1.shape != a2.shape:
            raise QgsProcessingException(
                f"The rasters differ in size ({a1.shape} vs {a2.shape}) - "
                "resample to a common grid first.")
        if abs(pixel1 - pixel2) > 1e-6:
            feedback.pushWarning(self.tr(
                "Cell sizes differ - areas use the time-1 cell size."))
        nan1 = ~np.isfinite(a1)
        nan2 = ~np.isfinite(a2)
        i1 = np.rint(np.where(nan1, -2 ** 31, a1)).astype(np.int64)
        i2 = np.rint(np.where(nan2, -2 ** 31, a2)).astype(np.int64)
        cm = growth.change_matrix(i1, i2, nodata=-2 ** 31)
        cell_ha = pixel1 * pixel1 / 10000.0

        def lab(code):
            return labels.get(int(code), str(int(code)))

        m_fields = self.make_fields(
            ("from_class", STRING), ("to_class", STRING), ("cells", INT),
            ("area_ha", DOUBLE), ("kind", STRING))
        m_sink, m_dest = self.parameterAsSink(
            parameters, self.OUT_MATRIX, context, m_fields,
            QgsWkbTypes.Type.NoGeometry, QgsCoordinateReferenceSystem())
        best = (0, "", "")
        for i, cf in enumerate(cm["classes"]):
            for j, ct in enumerate(cm["classes"]):
                n = int(cm["matrix"][i, j])
                if n == 0:
                    continue
                kind = "Persistence" if i == j else "Conversion"
                if i != j and n > best[0]:
                    best = (n, lab(cf), lab(ct))
                feat = QgsFeature(m_fields)
                feat.setAttributes([lab(cf), lab(ct), n,
                                    round(n * cell_ha, 3), kind])
                m_sink.addFeature(feat, QgsFeatureSink.Flag.FastInsert)

        c_fields = self.make_fields(
            ("class", STRING), ("t1_ha", DOUBLE), ("t2_ha", DOUBLE),
            ("persisted_ha", DOUBLE), ("lost_ha", DOUBLE),
            ("gained_ha", DOUBLE), ("net_ha", DOUBLE))
        c_sink, c_dest = self.parameterAsSink(
            parameters, self.OUT_CLASSES, context, c_fields,
            QgsWkbTypes.Type.NoGeometry, QgsCoordinateReferenceSystem())
        for i, c in enumerate(cm["classes"]):
            t1_cells = int(cm["matrix"][i, :].sum())
            t2_cells = int(cm["matrix"][:, i].sum())
            feat = QgsFeature(c_fields)
            feat.setAttributes([
                lab(c), round(t1_cells * cell_ha, 3),
                round(t2_cells * cell_ha, 3),
                round(int(cm["persisted"][i]) * cell_ha, 3),
                round(int(cm["lost"][i]) * cell_ha, 3),
                round(int(cm["gained"][i]) * cell_ha, 3),
                round(int(cm["net"][i]) * cell_ha, 3)])
            c_sink.addFeature(feat, QgsFeatureSink.Flag.FastInsert)

        feedback.pushInfo(self.tr(
            f"{len(cm['classes'])} classes over "
            f"{int(cm['matrix'].sum())} shared cells."))
        if best[0]:
            feedback.pushInfo(self.tr(
                f"Largest conversion: {best[1]} -> {best[2]} "
                f"({best[0] * cell_ha:,.2f} ha)."))
        return {self.OUT_MATRIX: m_dest, self.OUT_CLASSES: c_dest}

    def createInstance(self):
        return LandCoverChangeAlgorithm()
