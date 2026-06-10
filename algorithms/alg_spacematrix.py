# -*- coding: utf-8 -*-
"""Spacematrix Density: GSI / FSI / OSR / L per block."""
from __future__ import annotations

from qgis.core import (
    QgsFeature,
    QgsFeatureSink,
    QgsProcessing,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsSpatialIndex,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_MORPHOLOGY, INT, PlanXAlgorithm, STRING


def spacematrix_class(fsi: float, gsi: float, levels: float) -> str:
    if fsi <= 0 or gsi <= 0:
        return "Unbuilt"
    if levels < 3:
        height = "Low-rise"
    elif levels <= 6:
        height = "Mid-rise"
    else:
        height = "High-rise"
    if gsi >= 0.35:
        fabric = "compact"
    elif gsi >= 0.15:
        fabric = "moderate"
    else:
        fabric = "spacious"
    return f"{height} {fabric}"


class SpacematrixDensityAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_MORPHOLOGY
    BUILDINGS = "BUILDINGS"
    LEVELS_FIELD = "LEVELS_FIELD"
    DEFAULT_LEVELS = "DEFAULT_LEVELS"
    BLOCKS = "BLOCKS"
    OUTPUT = "OUTPUT"

    def name(self):
        return "spacematrix"

    def displayName(self):
        return self.tr("Spacematrix Density")

    def shortHelpString(self):
        return self.tr(
            "Computes the Spacematrix density indicators (Berghauser Pont "
            "and Haupt) per block, tessellation cell or any polygon unit:\n"
            "- GSI (coverage): footprint area / block area\n"
            "- FSI (floor space index / FAR): gross floor area / block area\n"
            "- OSR (spaciousness): (1 - GSI) / FSI\n"
            "- L: mean number of floors (FSI / GSI)\n"
            "plus building count and a readable Spacematrix class label "
            "(e.g. 'Mid-rise compact').\n\n"
            "Floor counts come from a numeric field on the buildings; "
            "footprints crossing block borders are split by intersection "
            "area. Pair with Morphological Tessellation when no block layer "
            "exists."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.BUILDINGS, self.tr("Buildings (polygons)"),
            [QgsProcessing.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterField(
            self.LEVELS_FIELD, self.tr("Floor count field (empty = constant)"),
            parentLayerParameterName=self.BUILDINGS, optional=True,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.DEFAULT_LEVELS, self.tr("Default floor count"),
            QgsProcessingParameterNumber.Double, 2.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.BLOCKS, self.tr("Blocks / analysis units (polygons)"),
            [QgsProcessing.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Spacematrix blocks")))

    def processAlgorithm(self, parameters, context, feedback):
        buildings = self.parameterAsSource(parameters, self.BUILDINGS, context)
        blocks = self.parameterAsSource(parameters, self.BLOCKS, context)
        levels_field = self.parameterAsString(parameters, self.LEVELS_FIELD, context)
        default_levels = self.parameterAsDouble(parameters, self.DEFAULT_LEVELS, context)
        self.require_projected(blocks, "Blocks")

        lvl_idx = buildings.fields().lookupField(levels_field) if levels_field else -1
        bld = []
        index = QgsSpatialIndex()
        for f in buildings.getFeatures():
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
            lv = default_levels
            if lvl_idx >= 0:
                try:
                    lv = float(f.attributes()[lvl_idx])
                except (TypeError, ValueError):
                    lv = default_levels
            i = len(bld)
            bld.append((g, max(0.0, lv)))
            pf = QgsFeature(i)
            pf.setGeometry(g)
            index.addFeature(pf)

        fields = self.make_fields(
            ("b_count", INT), ("fp_m2", DOUBLE), ("gfa_m2", DOUBLE),
            ("gsi", DOUBLE), ("fsi", DOUBLE), ("osr", DOUBLE), ("levels", DOUBLE),
            ("smx_class", STRING), base=blocks.fields())
        sink, dest = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields,
            QgsWkbTypes.MultiPolygon, blocks.sourceCrs())

        n_src = len(blocks.fields())
        total = blocks.featureCount() or 1
        for done, f in enumerate(blocks.getFeatures()):
            if feedback.isCanceled():
                break
            feedback.setProgress(int(100.0 * done / total))
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
            block_area = g.area()
            fp = gfa = 0.0
            count = 0
            for bid in index.intersects(g.boundingBox()):
                bg, lv = bld[bid]
                inter = g.intersection(bg)
                if inter is None or inter.isEmpty():
                    continue
                a = inter.area()
                if a <= 0:
                    continue
                fp += a
                gfa += a * lv
                count += 1
            gsi = fp / block_area if block_area > 0 else 0.0
            fsi = gfa / block_area if block_area > 0 else 0.0
            osr = (1.0 - gsi) / fsi if fsi > 0 else 0.0
            levels = fsi / gsi if gsi > 0 else 0.0
            out = QgsFeature(fields)
            out.setGeometry(g)
            out.setAttributes(list(f.attributes())[:n_src] + [
                count, fp, gfa, gsi, fsi, osr, levels,
                spacematrix_class(fsi, gsi, levels)])
            sink.addFeature(out, QgsFeatureSink.FastInsert)
        return {self.OUTPUT: dest}

    def createInstance(self):
        return SpacematrixDensityAlgorithm()
