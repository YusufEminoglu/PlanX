# -*- coding: utf-8 -*-
"""Flood exposure analysis algorithm wrapper."""
from __future__ import annotations

from qgis.core import (
    QgsFeature,
    QgsFeatureSink,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterRasterLayer,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_HAZARD, PlanXAlgorithm, STRING
from ._raster import read_dsm
from ..engine import hydro


class FloodExposureAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_HAZARD
    ICON = "tool_floodexposure.png"
    INUNDATION = "INUNDATION"
    BUILDINGS = "BUILDINGS"
    DEMAND = "DEMAND"
    POP_FIELD = "POP_FIELD"
    OUTPUT = "OUTPUT"
    OUT_DEMAND = "OUT_DEMAND"

    def name(self):
        return "floodexposure"

    def displayName(self):
        return self.tr("Flood Exposure")

    def shortHelpString(self):
        return self.tr(
            "Screening-quality flood exposure analysis.\n\n"
            "Intersects a binary inundation mask raster with buildings footprints and/or "
            "demand points. For buildings, computes the count and share of exposed buildings. "
            "For demand points, computes the sum and share of exposed population, and outputs "
            "a vector layer of demand points annotated with 'wet' or 'dry'.\n\n"
            "Outputs a summary table containing counts and percentages of exposure.\n\n"
            "How to read the results\n"
            "- The summary turns a blue polygon into policy numbers: "
            "'1,240 residents and 310 buildings in the 2 m scenario' "
            "is what a risk chapter, an insurance question or a "
            "relocation debate actually needs.\n"
            "- Run it once per depth scenario and read the CURVE of "
            "exposed population vs depth: a city where exposure "
            "explodes between 1 m and 2 m has its growth sitting just "
            "above the everyday flood - the classic creeping-risk "
            "signature.\n"
            "- On the annotated points, 'wet' clusters in one "
            "neighbourhood mean concentrated (defendable) risk; salt- "
            "and-pepper wet points mean the drainage network, not a "
            "river, is the problem.\n"
            "- Screening caveats carry over from the mask: no defences, "
            "no depth-damage - counts, not losses.\n\n"
            "Using the results: check exposed SHARE of new development "
            "vs existing fabric - a plan adding growth into the wet "
            "zone is manufacturing tomorrow's risk; overlay wet "
            "critical facilities (schools, clinics, fire stations) "
            "first - they anchor the emergency-planning map; rerun on "
            "the plan's land-use scenario to test 'risk-informed' "
            "claims with a number."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.INUNDATION, self.tr("Inundation mask raster (projected CRS)")))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.BUILDINGS, self.tr("Buildings vector layer (optional)"),
            [QgsProcessing.SourceType.TypeVectorPolygon], optional=True))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.DEMAND, self.tr("Demand points vector layer (optional)"),
            [QgsProcessing.SourceType.TypeVectorAnyGeometry], optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.POP_FIELD, self.tr("Population field (optional)"),
            parentLayerParameterName=self.DEMAND, optional=True,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Summary table")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_DEMAND, self.tr("Annotated demand points"), optional=True,
            createByDefault=False))

    def processAlgorithm(self, parameters, context, feedback):
        inund_layer = self.parameterAsRasterLayer(parameters, self.INUNDATION, context)
        buildings = self.parameterAsSource(parameters, self.BUILDINGS, context)
        demand = self.parameterAsSource(parameters, self.DEMAND, context)
        pop_f = self.parameterAsString(parameters, self.POP_FIELD, context)

        inund, gt, proj, pixel = read_dsm(inund_layer)
        crs = inund_layer.crs()

        if buildings is None and demand is None:
            raise QgsProcessingException("Please provide at least a Buildings or Demand layer.")

        bld_coords = []
        if buildings is not None:
            bld_xy, _ = self.source_points(buildings, crs, context.transformContext())
            bld_coords = [(float(x), float(y)) for x, y in bld_xy]

        pop_coords = []
        pop_vals = []
        pop_feats = []
        pop_xy = None
        if demand is not None:
            pop_xy, pop_feats = self.source_points(demand, crs, context.transformContext())
            pop_coords = [(float(x), float(y)) for x, y in pop_xy]
            pop_i = demand.fields().lookupField(pop_f) if pop_f else -1
            for f in pop_feats:
                p = 1.0
                if pop_i >= 0:
                    try:
                        p = max(0.0, float(f.attributes()[pop_i]))
                    except (TypeError, ValueError):
                        p = 0.0
                pop_vals.append(p)

        res = hydro.exposure(inund, bld_coords, pop_coords, pop_vals, gt)

        summary_fields = self.make_fields(
            ("exposed_bld", DOUBLE),
            ("total_bld", DOUBLE),
            ("pct_bld", DOUBLE),
            ("exposed_pop", DOUBLE),
            ("total_pop", DOUBLE),
            ("pct_pop", DOUBLE)
        )
        sink_summary, dest_summary = self.parameterAsSink(
            parameters, self.OUTPUT, context, summary_fields,
            QgsWkbTypes.Type.NoGeometry)

        row_feat = QgsFeature(summary_fields)
        row_feat.setAttributes([
            res["exposed_bld"],
            res["total_bld"],
            res["pct_bld"],
            res["exposed_pop"],
            res["total_pop"],
            res["pct_pop"]
        ])
        sink_summary.addFeature(row_feat, QgsFeatureSink.Flag.FastInsert)

        results = {self.OUTPUT: dest_summary}

        if demand is not None:
            demand_fields = self.make_fields(("wet_dry", STRING), base=demand.fields())
            sink_demand, dest_demand = self.parameterAsSink(
                parameters, self.OUT_DEMAND, context, demand_fields,
                QgsWkbTypes.Type.Point, crs)
            if sink_demand is not None:
                rows, cols = inund.shape
                n_base = len(demand.fields())
                for i, feat in enumerate(pop_feats):
                    x, y = pop_xy[i]
                    col = int((x - gt[0]) / gt[1])
                    row = int((y - gt[3]) / gt[5])
                    is_wet = False
                    if 0 <= row < rows and 0 <= col < cols:
                        is_wet = inund[row, col] > 0.5
                    status_str = "wet" if is_wet else "dry"

                    out_feat = QgsFeature(demand_fields)
                    out_feat.setGeometry(QgsGeometry.fromPointXY(
                        QgsPointXY(float(x), float(y))))
                    out_feat.setAttributes(list(feat.attributes())[:n_base] + [status_str])
                    sink_demand.addFeature(out_feat, QgsFeatureSink.Flag.FastInsert)
                results[self.OUT_DEMAND] = dest_demand

        return results

    def createInstance(self):
        return FloodExposureAlgorithm()
