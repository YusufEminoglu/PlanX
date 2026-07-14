# -*- coding: utf-8 -*-
"""Residential Capacity: dwelling units the zoning can still deliver."""
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


class ResidentialCapacityAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_POPULATION
    ICON = "tool_residentialcapacity.png"
    PARCELS = "PARCELS"
    FAR_FIELD = "FAR_FIELD"
    EXISTING_FIELD = "EXISTING_FIELD"
    DISTRICT_FIELD = "DISTRICT_FIELD"
    UNIT_SIZE = "UNIT_SIZE"
    EFFICIENCY = "EFFICIENCY"
    OUT_PARCELS = "OUT_PARCELS"
    OUT_DISTRICTS = "OUT_DISTRICTS"

    def name(self):
        return "residentialcapacity"

    def displayName(self):
        return self.tr("Residential Capacity")

    def shortHelpString(self):
        return self.tr(
            "Can the zoning DELIVER the housing need? Per parcel:\n\n"
            "buildable floorspace = max(0, parcel area x FAR - existing "
            "floorspace); capacity = buildable x efficiency / unit size "
            "(rounded down to whole dwellings).\n\n"
            "- FAR (floor area ratio) comes from a field - your zoning "
            "layer's density rule;\n"
            "- existing floorspace (optional field) subtracts what already "
            "stands, so the result is REMAINING capacity;\n"
            "- efficiency discounts common areas (0.85 = 15 percent goes "
            "to cores and corridors);\n"
            "- unit size is the average dwelling you expect the market to "
            "build.\n\n"
            "Outputs every parcel with its buildable floorspace and unit "
            "capacity (style by cap_units to see where the plan's supply "
            "sits) and an optional district roll-up. Compare the total "
            "against the Housing Needs Assessment: if capacity < need, "
            "the plan cannot house its own projection. The parcel output "
            "also feeds the Land-Use Allocation Optimizer as a target "
            "source.\n\n"
            "Use a projected CRS (areas in square map units).\n\n"
            "How to read the results\n"
            "- The total is THEORETICAL zoning capacity - what the "
            "rules allow, not what the market will build. Standard "
            "practice discounts it (often to 50-70 percent over a plan "
            "horizon: ownership fragmentation, holdouts, unviable "
            "sites). Quote both numbers.\n"
            "- The parcel map shows WHERE supply hides: capacity "
            "concentrated in a few big parcels is fragile (one "
            "landowner can stall the plan); capacity spread as one "
            "unit per plot across old fabric mostly never happens.\n"
            "- cap_units = 0 parcels with old FAR already exceeded "
            "are your built-out districts - growth there means "
            "upzoning, not vacant supply.\n\n"
            "Using the results: compare the (discounted) total against "
            "the Housing Needs 'need' - the gap sizes the upzoning or "
            "expansion decision; use the district roll-up to phase "
            "infrastructure where capacity actually sits; feed "
            "cap_units to Allocate Population Growth so scenario "
            "population lands where zoning can absorb it."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.PARCELS, self.tr("Parcels (polygons)"),
            [QgsProcessing.SourceType.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterField(
            self.FAR_FIELD, self.tr("FAR / floor-area-ratio field"),
            parentLayerParameterName=self.PARCELS,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterField(
            self.EXISTING_FIELD,
            self.tr("Existing floorspace field (m2, optional)"),
            parentLayerParameterName=self.PARCELS, optional=True,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterField(
            self.DISTRICT_FIELD, self.tr("District field for the roll-up (optional)"),
            parentLayerParameterName=self.PARCELS, optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.UNIT_SIZE, self.tr("Average dwelling size (m2)"),
            QgsProcessingParameterNumber.Type.Double, 90.0, minValue=10.0,
            maxValue=1000.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.EFFICIENCY, self.tr("Net-to-gross efficiency"),
            QgsProcessingParameterNumber.Type.Double, 0.85, minValue=0.1,
            maxValue=1.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_PARCELS, self.tr("Parcel capacity")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_DISTRICTS, self.tr("District roll-up"),
            type=QgsProcessing.SourceType.TypeVector))

    def processAlgorithm(self, parameters, context, feedback):
        parcels = self.parameterAsSource(parameters, self.PARCELS, context)
        far_f = self.parameterAsString(parameters, self.FAR_FIELD, context)
        exist_f = self.parameterAsString(parameters, self.EXISTING_FIELD, context)
        dist_f = self.parameterAsString(parameters, self.DISTRICT_FIELD, context)
        unit_size = self.parameterAsDouble(parameters, self.UNIT_SIZE, context)
        efficiency = self.parameterAsDouble(parameters, self.EFFICIENCY, context)
        self.require_projected(parcels, "Parcels")

        fields = parcels.fields()
        far_i = fields.lookupField(far_f)
        ex_i = fields.lookupField(exist_f) if exist_f else -1
        d_i = fields.lookupField(dist_f) if dist_f else -1

        feats, areas, fars, exists, dists = [], [], [], [], []
        bad = 0
        for f in parcels.getFeatures():
            if feedback.isCanceled():
                break
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
            attrs = f.attributes()

            def num(i, default=0.0):
                try:
                    v = float(attrs[i])
                    return v if math.isfinite(v) else default
                except (TypeError, ValueError):
                    return default

            far = num(far_i, -1.0)
            if far < 0:
                bad += 1
                far = 0.0
            feats.append(f)
            areas.append(g.area())
            fars.append(far)
            exists.append(num(ex_i, 0.0) if ex_i >= 0 else 0.0)
            dists.append(str(attrs[d_i]) if d_i >= 0 else "(all)")
        if not feats:
            raise QgsProcessingException("No parcels with geometry found.")
        if bad:
            feedback.pushWarning(self.tr(
                f"{bad} parcel(s) had no usable FAR - counted as 0."))

        buildable, units = population.residential_capacity(
            areas, fars, existing_floor=exists if ex_i >= 0 else None,
            unit_size=unit_size, efficiency=efficiency)

        p_fields = self.make_fields(
            ("buildable_m2", DOUBLE), ("cap_units", INT),
            base=parcels.fields())
        p_sink, p_dest = self.parameterAsSink(
            parameters, self.OUT_PARCELS, context, p_fields,
            parcels.wkbType(), parcels.sourceCrs())
        n_base = len(parcels.fields())
        for i, f in enumerate(feats):
            out = QgsFeature(p_fields)
            out.setGeometry(f.geometry())
            out.setAttributes(list(f.attributes())[:n_base] + [
                round(float(buildable[i]), 1), int(units[i])])
            p_sink.addFeature(out, QgsFeatureSink.Flag.FastInsert)

        rollup = {}
        for i, d in enumerate(dists):
            rec = rollup.setdefault(d, [0.0, 0.0, 0])
            rec[0] += areas[i]
            rec[1] += float(buildable[i])
            rec[2] += int(units[i])
        d_fields = self.make_fields(
            ("district", STRING), ("area_m2", DOUBLE),
            ("buildable_m2", DOUBLE), ("cap_units", INT))
        d_sink, d_dest = self.parameterAsSink(
            parameters, self.OUT_DISTRICTS, context, d_fields,
            QgsWkbTypes.Type.NoGeometry, QgsCoordinateReferenceSystem())
        for d in sorted(rollup):
            area_sum, build_sum, unit_sum = rollup[d]
            feat = QgsFeature(d_fields)
            feat.setAttributes([d, round(area_sum, 1), round(build_sum, 1),
                                unit_sum])
            d_sink.addFeature(feat, QgsFeatureSink.Flag.FastInsert)

        total_units = int(units.sum())
        feedback.pushInfo(self.tr(
            f"{len(feats)} parcels: {float(np.asarray(buildable).sum()):,.0f} "
            f"m2 buildable -> {total_units:,} dwelling(s) at "
            f"{unit_size:g} m2 net {efficiency:g} efficiency."))
        return {self.OUT_PARCELS: p_dest, self.OUT_DISTRICTS: d_dest}

    def createInstance(self):
        return ResidentialCapacityAlgorithm()
