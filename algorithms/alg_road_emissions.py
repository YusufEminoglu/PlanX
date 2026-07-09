# -*- coding: utf-8 -*-
"""Road emissions calculation wrapper."""
from __future__ import annotations


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

from .base import DOUBLE, GROUP_MICRO, PlanXAlgorithm
from ..engine import air


class RoadEmissionsAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_MICRO
    ICON = "tool_roademissions.png"
    ROADS = "ROADS"
    VOLUME_FIELD = "VOLUME_FIELD"
    HOURLY_FACTOR = "HOURLY_FACTOR"
    EF_GKM = "EF_GKM"
    OUTPUT = "OUTPUT"

    def name(self):
        return "roademissions"

    def displayName(self):
        return self.tr("Road Emissions")

    def shortHelpString(self):
        return self.tr(
            "Calculates road segment emissions (g/km/day) for air quality screening "
            "from a traffic volume field and an emission factor.\n\n"
            "Model: each road segment's emission is computed as AADT * EF (g/km). "
            "The default emission factor 0.5 g/km per vehicle is a generic NOx-proxy "
            "screening value - replace it with a fleet-specific factor when you have one. "
            "By default, the traffic volume field is multiplied by the hourly/daily factor. "
            "If your volume field is already daily volume (AADT), keep the factor as 1.0. "
            "If it is hourly volume, set the factor to 24.0.\n\n"
            "Outputs the road network with calculated emissions (g/km/day). Use a projected CRS."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.ROADS, self.tr("Roads (lines)"),
            [QgsProcessing.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterField(
            self.VOLUME_FIELD, self.tr("Traffic volume field (e.g. AADT)"),
            parentLayerParameterName=self.ROADS,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.HOURLY_FACTOR,
            self.tr("Volume multiplier (to daily volume, e.g. 24.0 if volume is hourly, 1.0 if AADT)"),
            QgsProcessingParameterNumber.Double, 1.0, minValue=0.0001,
            maxValue=1000.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.EF_GKM,
            self.tr("Emission factor (g/km per vehicle, default is generic NOx-proxy)"),
            QgsProcessingParameterNumber.Double, 0.5, minValue=0.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Roads with emissions (g/km/day)")))

    def processAlgorithm(self, parameters, context, feedback):
        roads = self.parameterAsSource(parameters, self.ROADS, context)
        vol_f = self.parameterAsString(parameters, self.VOLUME_FIELD, context)
        mult = self.parameterAsDouble(parameters, self.HOURLY_FACTOR, context)
        ef_gkm = self.parameterAsDouble(parameters, self.EF_GKM, context)
        self.require_projected(roads, "Roads")

        vol_i = roads.fields().lookupField(vol_f)

        fields_in = roads.fields()
        out_fields = self.make_fields(
            ("emission", DOUBLE), ("vol_used", DOUBLE),
            base=fields_in)

        sink, dest = self.parameterAsSink(
            parameters, self.OUTPUT, context, out_fields,
            QgsWkbTypes.LineString, roads.sourceCrs())

        polylines, feats = self.source_polylines(roads, feedback)
        n_base = len(fields_in)

        for e, feat in enumerate(feats):
            if feedback.isCanceled():
                break
            attrs = feat.attributes()
            try:
                m = float(attrs[vol_i]) * mult
            except (TypeError, ValueError):
                m = 0.0

            em = float(air.road_emission(m, ef_gkm))

            out = QgsFeature(out_fields)
            out.setGeometry(QgsGeometry.fromPolylineXY(
                [QgsPointXY(float(x), float(y)) for x, y in polylines[e]]))
            out.setAttributes(list(attrs)[:n_base] + [
                round(em, 2), round(m, 1)])
            sink.addFeature(out, QgsFeatureSink.FastInsert)

        return {self.OUTPUT: dest}

    def createInstance(self):
        return RoadEmissionsAlgorithm()
