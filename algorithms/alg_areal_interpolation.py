# -*- coding: utf-8 -*-
"""Areal Interpolation: move counts and rates between incompatible zones."""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureSink,
    QgsGeometry,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsSpatialIndex,
    QgsWkbTypes,
)

from . import _units
from .base import DOUBLE, GROUP_POPULATION, INT, PlanXAlgorithm
from ..engine import interpolation


def _polygons(source, target_crs, transform_context):
    """Valid polygon geometries of a source in ``target_crs``, with features."""
    xform = None
    if source.sourceCrs() != target_crs:
        xform = QgsCoordinateTransform(source.sourceCrs(), target_crs, transform_context)
    geoms, feats = [], []
    for f in source.getFeatures():
        g = f.geometry()
        if g is None or g.isEmpty():
            continue
        g = QgsGeometry(g)
        if xform is not None:
            g.transform(xform)
        if not g.isGeosValid():
            g = g.makeValid()
        geoms.append(g)
        feats.append(f)
    return geoms, feats


def _number(feature, index):
    try:
        value = float(feature.attributes()[index])
    except (TypeError, ValueError):
        return np.nan
    return value if np.isfinite(value) else np.nan


class ArealInterpolationAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_POPULATION
    ICON = "tool_arealinterpolation.png"
    RENDER_FIELD = "cover_share"

    SOURCE = "SOURCE"
    EXTENSIVE = "EXTENSIVE"
    INTENSIVE = "INTENSIVE"
    TARGET = "TARGET"
    ANCILLARY = "ANCILLARY"
    OUTPUT = "OUTPUT"

    def name(self):
        return "arealinterpolation"

    def displayName(self):
        return self.tr("Areal Interpolation (Area-Weighted and Dasymetric)")

    def shortHelpString(self):
        return self.tr(
            "Moves counts and rates from one set of polygons to another that "
            "does not line up with it - census tracts to planning zones, "
            "neighbourhoods to school catchments, any zones to a hexagon grid.\n\n"
            "Extensive fields (counts: population, jobs, dwellings) are split "
            "in proportion to the area each source shares with each target, so "
            "totals are preserved. Intensive fields (rates, densities, shares) "
            "are averaged over the covered part of each target, weighted by "
            "the shared area - a rate is never split. Give an ancillary layer "
            "(residential land, building footprints) and the weights become the "
            "ancillary area inside each piece instead: people live on the "
            "residential part of a tract, not in its park. A source with no "
            "ancillary land falls back to plain area weights and is counted in "
            "the log.\n\n"
            "Every target keeps its own fields and gains one <field>_est per "
            "interpolated field, cover_share (the share of its area the sources "
            "cover) and n_sources. Areas are measured in ground metres.\n\n"
            "How to read the results\n"
            "- The log prints, per count field, the target total against the "
            "total the method must reproduce; they agree unless a geometry is "
            "broken.\n"
            "- cover_share below 1 means part of the target lies outside every "
            "source: its counts are understated by that part, its rates "
            "describe the covered part only.\n"
            "- Area weighting assumes the variable is spread evenly over each "
            "source; that is the method's error, and the dasymetric option is "
            "the standard way to reduce it.\n\n"
            "Using the results: bring census counts onto the plan's own zones "
            "before Trip Generation, Housing Needs or Facility Adequacy; build "
            "a hexagon grid and interpolate onto it to map several sources on "
            "one comparable surface."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.SOURCE, self.tr("Source zones (polygons with the data)"),
            [QgsProcessing.SourceType.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterField(
            self.EXTENSIVE, self.tr("Count fields (extensive: split by area)"),
            parentLayerParameterName=self.SOURCE, allowMultiple=True, optional=True,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterField(
            self.INTENSIVE, self.tr("Rate fields (intensive: area-weighted mean)"),
            parentLayerParameterName=self.SOURCE, allowMultiple=True, optional=True,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.TARGET, self.tr("Target zones (polygons)"),
            [QgsProcessing.SourceType.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.ANCILLARY, self.tr("Ancillary mask for dasymetric weights (optional)"),
            [QgsProcessing.SourceType.TypeVectorPolygon], optional=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Target zones with estimates"),
            type=QgsProcessing.SourceType.TypeVectorPolygon))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.SOURCE, context)
        target = self.parameterAsSource(parameters, self.TARGET, context)
        ancillary = self.parameterAsSource(parameters, self.ANCILLARY, context)
        ext_fields = self.parameterAsFields(parameters, self.EXTENSIVE, context)
        int_fields = self.parameterAsFields(parameters, self.INTENSIVE, context)
        if not ext_fields and not int_fields:
            raise QgsProcessingException("Choose at least one count or rate field to interpolate.")
        self.require_projected(target, "Target zones")
        crs = target.sourceCrs()
        ctx = context.transformContext()
        units = _units.GroundUnits(crs, ctx)

        s_geoms, s_feats = _polygons(source, crs, ctx)
        t_geoms, t_feats = _polygons(target, crs, ctx)
        if not s_geoms or not t_geoms:
            raise QgsProcessingException("Both layers need at least one polygon.")
        s_area = np.asarray([units.area(g) for g in s_geoms])
        t_area = np.asarray([units.area(g) for g in t_geoms])

        mask = None
        if ancillary is not None:
            a_geoms, _ = _polygons(ancillary, crs, ctx)
            if a_geoms:
                mask = QgsGeometry.unaryUnion(a_geoms)
                if not mask.isGeosValid():
                    mask = mask.makeValid()
                feedback.pushInfo(self.tr(
                    f"Dasymetric weights from {len(a_geoms)} ancillary polygon(s)."))

        index = QgsSpatialIndex()
        for i, g in enumerate(s_geoms):
            f = QgsFeature(i)
            f.setGeometry(g)
            index.addFeature(f)

        pairs, weights = [], []
        for t, tg in enumerate(t_geoms):
            if feedback.isCanceled():
                break
            for s in index.intersects(tg.boundingBox()):
                sg = s_geoms[s]
                if not sg.intersects(tg):
                    continue
                piece = sg.intersection(tg)
                a = units.area(piece)
                if a <= 0:
                    continue
                pairs.append((int(s), int(t), a))
                if mask is not None:
                    weights.append(units.area(piece.intersection(mask)))
            feedback.setProgress(int(70.0 * (t + 1) / len(t_geoms)))
        s_weight = None
        if mask is not None:
            s_weight = np.asarray([units.area(g.intersection(mask)) for g in s_geoms])

        out_specs = []
        estimates = []
        report = []
        fallback_sources = set()
        for kind, names in (("extensive", ext_fields), ("intensive", int_fields)):
            for name in names:
                idx = source.fields().lookupField(name)
                values = np.asarray([_number(f, idx) for f in s_feats])
                est, info = interpolation.interpolate(
                    pairs, values, len(t_geoms), s_area, kind,
                    weight_area=weights if mask is not None else None,
                    source_weight=s_weight)
                fallback_sources.update(info["fallback"])
                out_specs.append((f"{name}_est", DOUBLE))
                estimates.append(est)
                if kind == "extensive":
                    want = interpolation.expected_total(
                        values, info["covered_share"], s_weight, pairs,
                        weights if mask is not None else None)
                    report.append(f"{name}: targets {float(np.nansum(est)):,.3f} against "
                                  f"{want:,.3f} the method must reproduce "
                                  f"(sources {float(np.nansum(values)):,.3f})")
        if fallback_sources:
            feedback.pushWarning(self.tr(
                f"{len(fallback_sources)} source zone(s) contain no ancillary land and were "
                "spread by plain area instead."))

        covered = np.zeros(len(t_geoms))
        n_src = np.zeros(len(t_geoms), dtype=np.int64)
        for s, t, a in pairs:
            covered[t] += a
            n_src[t] += 1
        fields = self.make_fields(*out_specs, ("cover_share", DOUBLE), ("n_sources", INT),
                                  base=target.fields())
        sink, dest = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields, QgsWkbTypes.Type.MultiPolygon, crs)
        nb = len(target.fields())
        for t, feat in enumerate(t_feats):
            out = QgsFeature(fields)
            geom = QgsGeometry(t_geoms[t])
            geom.convertToMultiType()
            out.setGeometry(geom)
            vals = [None if not np.isfinite(e[t]) else round(float(e[t]), 6) for e in estimates]
            share = min(1.0, covered[t] / t_area[t]) if t_area[t] > 0 else 0.0
            out.setAttributes(list(feat.attributes())[:nb] + vals + [round(share, 6), int(n_src[t])])
            sink.addFeature(out, QgsFeatureSink.Flag.FastInsert)
        for line in report:
            feedback.pushInfo(line)
        feedback.pushInfo(self.tr(
            f"{len(pairs)} source-target piece(s); {int((covered <= 0).sum())} target(s) "
            "touch no source."))
        return {self.OUTPUT: dest}

    def createInstance(self):
        return ArealInterpolationAlgorithm()
