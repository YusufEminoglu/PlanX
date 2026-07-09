# -*- coding: utf-8 -*-
"""Population Allocation algorithm wrapper."""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsFeature,
    QgsFeatureSink,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsWkbTypes,
)

from .base import GROUP_POPULATION, INT, PlanXAlgorithm
from ..engine import population


class PopAllocateAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_POPULATION
    ICON = "tool_popallocate.png"
    PARCELS = "PARCELS"
    INCREMENT = "INCREMENT"
    CAPACITY_FIELD = "CAPACITY_FIELD"
    WEIGHT_FIELD = "WEIGHT_FIELD"
    OUTPUT = "OUTPUT"

    def name(self):
        return "popallocate"

    def displayName(self):
        return self.tr("Allocate Population Growth")

    def shortHelpString(self):
        return self.tr(
            "Distributes a population growth increment over parcels/zones.\n\n"
            "Allocates a target population increment using deterministic largest-remainder "
            "apportionment (Hare-Niemeyer method). Allocation weights are proportional to remaining "
            "zoning capacity or a custom weight field. If neither is specified, uniform allocation is used."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.PARCELS, self.tr("Parcels or zones layer"),
            [QgsProcessing.TypeVectorPolygon, QgsProcessing.TypeVectorPoint]))
        self.addParameter(QgsProcessingParameterNumber(
            self.INCREMENT, self.tr("Population increment to allocate"),
            QgsProcessingParameterNumber.Integer, defaultValue=100, minValue=0))
        self.addParameter(QgsProcessingParameterField(
            self.CAPACITY_FIELD, self.tr("Capacity field (optional)"),
            parentLayerParameterName=self.PARCELS, optional=True,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterField(
            self.WEIGHT_FIELD, self.tr("Weight field (optional)"),
            parentLayerParameterName=self.PARCELS, optional=True,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Allocated parcels or zones")))

    def processAlgorithm(self, parameters, context, feedback):
        parcels = self.parameterAsSource(parameters, self.PARCELS, context)
        inc = self.parameterAsInt(parameters, self.INCREMENT, context)
        cap_f = self.parameterAsString(parameters, self.CAPACITY_FIELD, context)
        weight_f = self.parameterAsString(parameters, self.WEIGHT_FIELD, context)

        cap_idx = parcels.fields().lookupField(cap_f) if cap_f else -1
        weight_idx = parcels.fields().lookupField(weight_f) if weight_f else -1

        weights = []
        feats = []
        for f in parcels.getFeatures():
            feats.append(f)
            val = 0.0
            if weight_idx >= 0:
                try:
                    val = float(f.attributes()[weight_idx] or 0.0)
                except (TypeError, ValueError):
                    val = 0.0
            elif cap_idx >= 0:
                try:
                    val = float(f.attributes()[cap_idx] or 0.0)
                except (TypeError, ValueError):
                    val = 0.0
            else:
                val = 1.0
            weights.append(max(0.0, val))

        allocated = population.allocate_growth(inc, np.array(weights, dtype=np.float64))

        out_fields = self.make_fields(
            ("allocated", INT),
            base=parcels.fields()
        )

        sink, dest = self.parameterAsSink(
            parameters, self.OUTPUT, context, out_fields,
            parcels.wkbType(), parcels.sourceCrs())

        def rebuild_geom(g):
            if g is None or g.isEmpty():
                return QgsGeometry()
            if g.isMultipart():
                return QgsGeometry(g)
            wkb = g.wkbType()
            flat = QgsWkbTypes.flatType(wkb)
            if flat == QgsWkbTypes.Point:
                pt = g.asPoint()
                return QgsGeometry.fromPointXY(QgsPointXY(pt.x(), pt.y()))
            elif flat == QgsWkbTypes.LineString:
                pts = g.asPolyline()
                return QgsGeometry.fromPolylineXY([QgsPointXY(p.x(), p.y()) for p in pts])
            elif flat == QgsWkbTypes.Polygon:
                rings = g.asPolygon()
                new_rings = []
                for ring in rings:
                    new_rings.append([QgsPointXY(p.x(), p.y()) for p in ring])
                return QgsGeometry.fromPolygonXY(new_rings)
            else:
                return QgsGeometry(g)

        n_base = len(parcels.fields())
        for i, f in enumerate(feats):
            if feedback.isCanceled():
                break
            out_feat = QgsFeature(out_fields)
            out_feat.setGeometry(rebuild_geom(f.geometry()))
            out_feat.setAttributes(list(f.attributes())[:n_base] + [int(allocated[i])])
            sink.addFeature(out_feat, QgsFeatureSink.FastInsert)

        return {self.OUTPUT: dest}

    def createInstance(self):
        return PopAllocateAlgorithm()
