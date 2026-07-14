# -*- coding: utf-8 -*-
"""Building Form Metrics: per-building morphology indicators."""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsFeature,
    QgsFeatureSink,
    QgsProcessing,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsSpatialIndex,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_MORPHOLOGY, INT, PlanXAlgorithm
from ..engine import morphology


def _main_rings(geometry):
    """Largest part's (exterior, interiors) as coordinate arrays."""
    if geometry.isMultipart():
        parts = geometry.asMultiPolygon()
        if not parts:
            return None, []
        part = max(parts, key=lambda p: morphology.ring_area(
            np.asarray([(q.x(), q.y()) for q in p[0]])) if p else 0.0)
    else:
        part = geometry.asPolygon()
    if not part or len(part[0]) < 4:
        return None, []
    ext = np.asarray([(q.x(), q.y()) for q in part[0]], dtype=np.float64)
    ints = [np.asarray([(q.x(), q.y()) for q in ring], dtype=np.float64)
            for ring in part[1:] if len(ring) >= 4]
    return ext, ints


class BuildingFormMetricsAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_MORPHOLOGY
    ICON = "tool_buildingmetrics.png"
    BUILDINGS = "BUILDINGS"
    OUTPUT = "OUTPUT"

    def name(self):
        return "buildingmetrics"

    def displayName(self):
        return self.tr("Building Form Metrics")

    def shortHelpString(self):
        return self.tr(
            "Computes the standard urban-morphology shape indicators for "
            "every building footprint (the momepy-style toolkit, embedded):\n"
            "- area, perimeter, courtyard area and courtyard index\n"
            "- compactness (isoperimetric quotient), convexity, "
            "rectangularity, elongation\n"
            "- orientation of the long axis (degrees, 0-180)\n"
            "- fractal dimension, corner count\n"
            "- shared-wall ratio: how much of the perimeter touches "
            "neighbouring buildings (attached vs detached fabric)\n\n"
            "All metrics are computed on the largest part of each footprint "
            "in map units - use a projected CRS.\n\n"
            "How to read the results\n"
            "- compact (0-1, 1 = circle): low values flag complex, "
            "wing-heavy footprints - costlier envelopes, more facade per "
            "floor area. rectang near 1 with 4 corners = simple slab.\n"
            "- elongation near 0 = square plan; near 1 = long thin bar "
            "(row housing, industrial sheds). orient_deg maps the "
            "prevailing grain of the fabric - style by it to see where "
            "street-aligned blocks give way to free-standing towers.\n"
            "- court_idx > 0 marks perimeter-block/courtyard typologies; "
            "combined with high sharedwall it separates traditional "
            "closed blocks from modernist slabs.\n"
            "- sharedwall: ~0 detached, 0.1-0.3 semi-detached, >0.3 "
            "terraced/attached fabric - the quickest typology classifier.\n"
            "- fractal and corners rise with ornament and annexes - handy "
            "for dating fabric or spotting digitising noise (hundreds of "
            "corners on a simple house = over-digitised data).\n\n"
            "Using the results: cluster on (compact, elongation, "
            "sharedwall, court_idx) to map building typologies; feed "
            "area_m2/perim_m into energy or cost models; use orient_deg "
            "against street bearing to find buildings that ignore the "
            "grid (often post-war estates)."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.BUILDINGS, self.tr("Buildings (polygons)"),
            [QgsProcessing.SourceType.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Building metrics")))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.BUILDINGS, context)
        self.require_projected(source, "Buildings")

        fields = self.make_fields(
            ("area_m2", DOUBLE), ("perim_m", DOUBLE), ("compact", DOUBLE),
            ("convexity", DOUBLE), ("rectang", DOUBLE), ("elongation", DOUBLE),
            ("orient_deg", DOUBLE), ("court_m2", DOUBLE), ("court_idx", DOUBLE),
            ("fractal", DOUBLE), ("corners", INT), ("sharedwall", DOUBLE),
            base=source.fields())
        sink, dest = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields,
            QgsWkbTypes.Type.MultiPolygon, source.sourceCrs())

        feats = [f for f in source.getFeatures()
                 if f.geometry() is not None and not f.geometry().isEmpty()]
        index = QgsSpatialIndex()
        for f in feats:
            index.addFeature(f)
        by_id = {f.id(): f for f in feats}

        n_src = len(source.fields())
        total = len(feats)
        for done, f in enumerate(feats):
            if feedback.isCanceled():
                break
            if done % 200 == 0:
                feedback.setProgress(int(100.0 * done / max(1, total)))
            g = f.geometry()
            ext, ints = _main_rings(g)
            if ext is None:
                continue
            m = morphology.shape_metrics(ext, ints)

            # Shared walls: boundary intersection length with neighbours.
            shared = 0.0
            boundary = None
            for nid in index.intersects(g.boundingBox()):
                if nid == f.id():
                    continue
                other = by_id[nid]
                if not g.intersects(other.geometry()):
                    continue
                if boundary is None:
                    boundary = QgsGeometryBoundary(g)
                inter = boundary.intersection(QgsGeometryBoundary(other.geometry()))
                if inter is not None and not inter.isEmpty():
                    shared += inter.length()
            ratio = shared / m["perimeter"] if m["perimeter"] > 0 else 0.0

            out = QgsFeature(fields)
            out.setGeometry(g)
            out.setAttributes(list(f.attributes())[:n_src] + [
                m["area"], m["perimeter"], m["ipq"], m["convexity"],
                m["rectangularity"], m["elongation"], m["orientation"],
                m["courtyard_area"], m["courtyard_index"],
                m["fractal_dimension"], int(m["corners"]),
                min(1.0, ratio)])
            sink.addFeature(out, QgsFeatureSink.Flag.FastInsert)
        return {self.OUTPUT: dest}

    def createInstance(self):
        return BuildingFormMetricsAlgorithm()


def QgsGeometryBoundary(g):
    b = g.constGet().boundary()
    from qgis.core import QgsGeometry
    return QgsGeometry(b) if b is not None else QgsGeometry()
