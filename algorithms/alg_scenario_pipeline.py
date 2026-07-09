# -*- coding: utf-8 -*-
"""Scenario Pipeline: chained CA growth, population allocation and access/walkability evaluation."""
from __future__ import annotations

import numpy as np

from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingMultiStepFeedback,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterMultipleLayers,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
    QgsProcessingUtils,
    QgsVectorLayer,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_REPORT, PlanXAlgorithm, STRING
from ._raster import read_dsm
from ..collect import collect
from ..engine import population
from ..engine import report as rpt
from ..engine import scenario


class ScenarioPipelineAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_REPORT
    ICON = "tool_scenariopipeline.png"
    NAME = "NAME"
    SEED = "SEED"
    SUITABILITY = "SUITABILITY"
    CONSTRAINTS = "CONSTRAINTS"
    DEMAND_HA = "DEMAND_HA"
    ITERATIONS = "ITERATIONS"
    NEIGH_WEIGHT = "NEIGH_WEIGHT"
    BASE = "BASE"
    RNG_SEED = "RNG_SEED"
    POP_GROWTH = "POP_GROWTH"
    DEMAND = "DEMAND"
    POP_FIELD = "POP_FIELD"
    NETWORK = "NETWORK"
    AMENITIES = "AMENITIES"
    THRESHOLD = "THRESHOLD"
    LANDUSE = "LANDUSE"
    CATEGORY_FIELD = "CATEGORY_FIELD"
    OUTPUT_JSON = "OUTPUT_JSON"
    OUT_METRICS = "OUT_METRICS"

    def name(self):
        return "scenariopipeline"

    def displayName(self):
        return self.tr("Scenario Pipeline (LUTI-lite)")

    def shortHelpString(self):
        return self.tr(
            "Weld growth, allocation, and evaluations into one decision pipeline.\n\n"
            "Chains the Urban Growth CA model to simulate city expansion, apportioning "
            "the population growth increment over the newly developed cells proportional "
            "to their suitability values. The pipeline then constructs the grown city's "
            "demand points and re-evaluates 15-minute accessibility and walkability, "
            "producing a scenario snapshot JSON."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterString(
            self.NAME, self.tr("Scenario name"), "Scenario"))
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
            QgsProcessingParameterNumber.Double, 50.0, minValue=0.01))
        self.addParameter(QgsProcessingParameterNumber(
            self.ITERATIONS, self.tr("Growth steps"),
            QgsProcessingParameterNumber.Integer, 5, minValue=1, maxValue=100))
        self.addParameter(QgsProcessingParameterNumber(
            self.NEIGH_WEIGHT, self.tr("Neighbourhood weight (edge growth)"),
            QgsProcessingParameterNumber.Double, 1.0, minValue=0.0, maxValue=10.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.BASE, self.tr("Base term (leapfrog growth)"),
            QgsProcessingParameterNumber.Double, 0.1, minValue=0.0, maxValue=1.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.RNG_SEED, self.tr("Random seed (tie-breaking only)"),
            QgsProcessingParameterNumber.Integer, 0, minValue=0))
        self.addParameter(QgsProcessingParameterNumber(
            self.POP_GROWTH, self.tr("Population growth to allocate"),
            QgsProcessingParameterNumber.Integer, 1000, minValue=0))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.DEMAND, self.tr("Existing demand / origins (optional)"),
            [QgsProcessing.TypeVectorAnyGeometry], optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.POP_FIELD, self.tr("Population field on demand (optional)"),
            parentLayerParameterName=self.DEMAND, optional=True,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("Street network (lines)"),
            [QgsProcessing.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterMultipleLayers(
            self.AMENITIES,
            self.tr("Amenity layers for the access score (optional)"),
            QgsProcessing.TypeVectorAnyGeometry, optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.THRESHOLD, self.tr("Access threshold (minutes)"),
            QgsProcessingParameterNumber.Double, 15.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.LANDUSE, self.tr("Land-use polygons (optional)"),
            [QgsProcessing.TypeVectorPolygon], optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.CATEGORY_FIELD, self.tr("Land-use category field (optional)"),
            parentLayerParameterName=self.LANDUSE, optional=True))
        self.addParameter(QgsProcessingParameterFileDestination(
            self.OUTPUT_JSON, self.tr("Scenario snapshot (JSON)"),
            self.tr("JSON files (*.json)")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_METRICS, self.tr("Audit metrics"),
            type=QgsProcessing.TypeVector))

    def processAlgorithm(self, parameters, context, feedback):
        import processing

        name = self.parameterAsString(parameters, self.NAME, context)
        seed_lyr = self.parameterAsRasterLayer(parameters, self.SEED, context)
        suit_lyr = self.parameterAsRasterLayer(parameters, self.SUITABILITY, context)
        con_lyr = self.parameterAsRasterLayer(parameters, self.CONSTRAINTS, context)
        demand_ha = self.parameterAsDouble(parameters, self.DEMAND_HA, context)
        iterations = self.parameterAsInt(parameters, self.ITERATIONS, context)
        neigh_w = self.parameterAsDouble(parameters, self.NEIGH_WEIGHT, context)
        base = self.parameterAsDouble(parameters, self.BASE, context)
        rng_seed = self.parameterAsInt(parameters, self.RNG_SEED, context)
        pop_growth = self.parameterAsInt(parameters, self.POP_GROWTH, context)
        demand = self.parameterAsVectorLayer(parameters, self.DEMAND, context)
        pop_field = self.parameterAsString(parameters, self.POP_FIELD, context)
        network = self.parameterAsVectorLayer(parameters, self.NETWORK, context)
        amenities = self.parameterAsLayerList(parameters, self.AMENITIES, context)
        threshold = self.parameterAsDouble(parameters, self.THRESHOLD, context)
        landuse = self.parameterAsVectorLayer(parameters, self.LANDUSE, context)
        cat_field = self.parameterAsString(parameters, self.CATEGORY_FIELD, context)
        json_path = self.parameterAsFileOutput(parameters, self.OUTPUT_JSON, context)

        run_access = bool(amenities)
        steps_count = 1 + (1 if run_access else 0) + 1
        steps = QgsProcessingMultiStepFeedback(steps_count, feedback)
        step = 0

        def child(alg_id, params):
            return processing.run(
                alg_id, params, context=context,
                feedback=steps, is_child_algorithm=True
            )

        def as_layer(ref):
            return QgsProcessingUtils.mapLayerFromString(str(ref), context)

        # Step 1: Growth CA simulation
        res_growth = child("planx:growthsim", {
            "SEED": seed_lyr,
            "SUITABILITY": suit_lyr,
            "CONSTRAINTS": con_lyr,
            "DEMAND_HA": demand_ha,
            "ITERATIONS": iterations,
            "NEIGH_WEIGHT": neigh_w,
            "BASE": base,
            "RNG_SEED": rng_seed,
            "OUTPUT": "TEMPORARY_OUTPUT"
        })
        step += 1
        steps.setCurrentStep(step)
        if feedback.isCanceled():
            raise QgsProcessingException("Cancelled.")

        # Read Year of Conversion
        y_arr, gt, proj, pixel = read_dsm(as_layer(res_growth["OUTPUT"]))
        new_mask = np.isfinite(y_arr) & (y_arr > 0)
        rows, cols = np.where(new_mask)

        # Suitability values
        suit_arr, _, _, _ = read_dsm(suit_lyr)
        cell_weights = suit_arr[new_mask]
        cell_weights[~np.isfinite(cell_weights)] = 0.0

        # Population allocation
        allocated_pop = population.allocate_growth(pop_growth, cell_weights)

        # Combine demand points
        crs = network.crs()
        dest_fields = QgsFields()
        pop_field_name = pop_field or "pop"

        if demand is not None:
            for fld in demand.fields():
                dest_fields.append(QgsField(fld))
            if dest_fields.lookupField(pop_field_name) < 0:
                dest_fields.append(QgsField(pop_field_name, QVariant.Double))
        else:
            dest_fields.append(QgsField(pop_field_name, QVariant.Double))

        grown_layer = QgsVectorLayer(f"Point?crs={crs.authid()}", "grown_demand", "memory")
        grown_layer.dataProvider().addAttributes(list(dest_fields))
        grown_layer.updateFields()

        new_feats = []
        if demand is not None:
            xform = None
            if demand.sourceCrs() != crs:
                xform = QgsCoordinateTransform(demand.sourceCrs(), crs, context.transformContext())
            for f in demand.getFeatures():
                nf = QgsFeature(grown_layer.fields())
                g = f.geometry()
                if g is not None and not g.isEmpty():
                    if QgsWkbTypes.flatType(g.wkbType()) == QgsWkbTypes.Point:
                        pt = g.asPoint()
                    else:
                        pt = g.centroid().asPoint()
                    if xform is not None:
                        pt = xform.transform(pt)
                    nf.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(pt.x(), pt.y())))
                attrs = list(f.attributes())
                if len(attrs) < len(grown_layer.fields()):
                    attrs.extend([0.0] * (len(grown_layer.fields()) - len(attrs)))
                nf.setAttributes(attrs)
                new_feats.append(nf)

        x_coords = gt[0] + (cols + 0.5) * gt[1] + (rows + 0.5) * gt[2]
        y_coords = gt[3] + (cols + 0.5) * gt[4] + (rows + 0.5) * gt[5]
        pop_idx = grown_layer.fields().lookupField(pop_field_name)

        for i in range(len(x_coords)):
            nf = QgsFeature(grown_layer.fields())
            nf.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(float(x_coords[i]), float(y_coords[i]))))
            attrs = [0.0] * len(grown_layer.fields())
            attrs[pop_idx] = float(allocated_pop[i])
            nf.setAttributes(attrs)
            new_feats.append(nf)

        grown_layer.dataProvider().addFeatures(new_feats)
        grown_layer.updateExtents()

        metrics = {}
        layers = {"access": None, "balance": None, "facilities": None,
                  "demand": None, "density": None}

        # Step 2: Access score on grown city
        if run_access:
            res_access = child("planx:accessscore", {
                "ORIGINS": grown_layer,
                "NETWORK": network,
                "AMENITIES": amenities,
                "POP_FIELD": pop_field_name,
                "SPEED": 4.8,
                "THRESHOLD": threshold,
                "OUTPUT": "TEMPORARY_OUTPUT"
            })
            layers["access"] = as_layer(res_access["OUTPUT"])
            step += 1
            steps.setCurrentStep(step)
            if feedback.isCanceled():
                raise QgsProcessingException("Cancelled.")

        # Step 3: Walkability on grown city
        walk_params = {
            "NETWORK": network,
            "RADIUS": 400.0,
            "OUT_SEGMENTS": "TEMPORARY_OUTPUT"
        }
        if landuse is not None and cat_field:
            walk_params["LANDUSE"] = landuse
            walk_params["CATEGORY_FIELD"] = cat_field
        if amenities:
            walk_params["POIS"] = amenities[0]

        res_walk = child("planx:walkability", walk_params)
        walk_layer = as_layer(res_walk["OUT_SEGMENTS"])
        if walk_layer is not None:
            scores = [f["walk_score"] for f in walk_layer.getFeatures()
                      if f["walk_score"] is not None]
            if scores:
                metrics["walk_score_mean"] = sum(scores) / len(scores)
                metrics["walk_low_share"] = (
                    100.0 * sum(1 for s in scores if s < 50.0) / len(scores))

        step += 1
        steps.setCurrentStep(step)

        # Access summary and overall PPI
        access_data, _, _, _ = collect(layers)
        a_sum = rpt.access_summary(access_data["scores"]) if access_data else None
        overall = rpt.overall_score(a_sum, None, None)
        metrics.update(scenario.metrics_from_summaries(access=a_sum, overall=overall))

        snap = scenario.snapshot(name, metrics)
        try:
            with open(json_path, "w", encoding="utf-8") as fh:
                fh.write(scenario.to_json(snap))
        except OSError as exc:
            raise QgsProcessingException(f"Could not write the snapshot: {exc}")

        fields = self.make_fields(
            ("metric", STRING), ("metric_key", STRING), ("value", DOUBLE))
        sink, dest = self.parameterAsSink(
            parameters, self.OUT_METRICS, context, fields,
            QgsWkbTypes.NoGeometry, QgsCoordinateReferenceSystem())
        for key in metrics:
            feat = QgsFeature(fields)
            feat.setAttributes([scenario.label_of(key), key,
                                round(float(metrics[key]), 4)])
            sink.addFeature(feat, QgsFeatureSink.FastInsert)

        results = {self.OUTPUT_JSON: json_path, self.OUT_METRICS: dest}
        feedback.pushInfo(self.tr(
            f"Scenario Pipeline complete. Snapshot '{name}' with {len(metrics)} metrics: {json_path}"))
        return results

    def createInstance(self):
        return ScenarioPipelineAlgorithm()
