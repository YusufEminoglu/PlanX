# -*- coding: utf-8 -*-
"""Morphological Tessellation: Voronoi-based plot proxies around buildings."""
from __future__ import annotations

from qgis.core import (
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureSink,
    QgsGeometry,
    QgsMultiPoint,
    QgsPoint,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
    QgsSpatialIndex,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_MORPHOLOGY, LONG, PlanXAlgorithm


class MorphologicalTessellationAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_MORPHOLOGY
    ICON = "tool_tessellation.png"
    BUILDINGS = "BUILDINGS"
    STUDY_AREA = "STUDY_AREA"
    SHRINK = "SHRINK"
    DENSIFY = "DENSIFY"
    LIMIT = "LIMIT"
    OUTPUT = "OUTPUT"

    def name(self):
        return "tessellation"

    def displayName(self):
        return self.tr("Morphological Tessellation")

    def shortHelpString(self):
        return self.tr(
            "Partitions urban space into cells around buildings - a parcel "
            "proxy when cadastral plots are unavailable (Fleischmann et al. "
            "2020, the momepy method, embedded with native QGIS Voronoi).\n\n"
            "Each footprint is slightly shrunk, its boundary densified, and "
            "the Voronoi diagram of those points is dissolved per building "
            "and clipped to the study area (or to a buffered convex hull of "
            "all buildings when no study area is given).\n\n"
            "Use the cells as analysis units: join population, run "
            "Spacematrix Density on them, or measure coverage ratios. "
            "Smaller densify spacing = smoother cell borders but slower.\n\n"
            "How to read the results\n"
            "- Each cell is the ground a building 'controls' - the best "
            "available stand-in for its plot. Cell area distribution "
            "reads like plot-size distribution: uniform small cells = "
            "fine-grained fabric; a few giant cells = campuses, malls, "
            "estates.\n"
            "- Building area / cell area approximates plot coverage "
            "without owning cadastral data; sudden cell-size jumps mark "
            "morphological boundaries between neighbourhood types.\n"
            "- Cells at the study-area edge are artificially clipped - "
            "exclude the outer ring from statistics.\n\n"
            "Using the results: treat cells as the unit for Spacematrix "
            "Density, dasymetric population, and typology clustering; "
            "compare cell-size variance between districts to quantify "
            "grain (an input regulating plans often prescribe implicitly)."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.BUILDINGS, self.tr("Buildings (polygons)"),
            [QgsProcessing.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.STUDY_AREA, self.tr("Study area (polygon, optional)"),
            [QgsProcessing.TypeVectorPolygon], optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.SHRINK, self.tr("Footprint shrink (map units)"),
            QgsProcessingParameterNumber.Double, 0.4, minValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.DENSIFY, self.tr("Boundary densify spacing (map units)"),
            QgsProcessingParameterNumber.Double, 2.0, minValue=0.1))
        self.addParameter(QgsProcessingParameterNumber(
            self.LIMIT, self.tr("Hull buffer when no study area (map units)"),
            QgsProcessingParameterNumber.Double, 100.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Tessellation cells")))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.BUILDINGS, context)
        study = self.parameterAsSource(parameters, self.STUDY_AREA, context)
        shrink = self.parameterAsDouble(parameters, self.SHRINK, context)
        densify = self.parameterAsDouble(parameters, self.DENSIFY, context)
        limit = self.parameterAsDouble(parameters, self.LIMIT, context)
        self.require_projected(source, "Buildings")
        crs = source.sourceCrs()

        # 1) Seed points: shrunken, densified footprint boundaries.
        # Quantize + dedupe: near-coincident seeds (buffer arc vertices) make
        # GEOS Voronoi emit invalid, overlapping cells.
        quant = max(densify / 4.0, 1e-3)
        seeds = []          # (x, y, building_key)
        seen = set()
        feats = []
        for f in source.getFeatures():
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
            shrunk = g.buffer(-shrink, 4) if shrink > 0 else QgsGeometry(g)
            if shrunk.isEmpty():
                shrunk = QgsGeometry(g)
            dense = shrunk.densifyByDistance(densify)
            key = len(feats)
            feats.append(f)
            for v in dense.vertices():
                x = round(v.x() / quant) * quant
                y = round(v.y() / quant) * quant
                if (x, y) in seen:
                    continue
                seen.add((x, y))
                seeds.append((x, y, key))
        if len(feats) < 3:
            raise QgsProcessingException("Tessellation needs at least 3 buildings.")
        feedback.pushInfo(self.tr(f"{len(feats)} buildings -> {len(seeds)} seed points"))

        # 2) Study area mask.
        if study is not None:
            mask_geoms = [QgsGeometry(f.geometry()) for f in study.getFeatures()
                          if f.geometry() is not None and not f.geometry().isEmpty()]
            if study.sourceCrs() != crs:
                xf = QgsCoordinateTransform(study.sourceCrs(), crs, context.transformContext())
                for g in mask_geoms:
                    g.transform(xf)
            mask = QgsGeometry.unaryUnion(mask_geoms)
        else:
            pts = QgsGeometry.fromMultiPointXY(
                [QgsPointXY(s[0], s[1]) for s in seeds])
            mask = pts.convexHull().buffer(limit, 8)

        # 3) Voronoi of all seed points.
        mp = QgsMultiPoint()
        for x, y, _ in seeds:
            mp.addGeometry(QgsPoint(x, y))
        extent_geom = QgsGeometry.fromRect(mask.boundingBox().buffered(limit))
        vor = QgsGeometry(mp).voronoiDiagram(extent=extent_geom, tolerance=0.0)
        if vor.isEmpty():
            raise QgsProcessingException("Voronoi computation failed.")
        cells = [QgsGeometry(part.clone()) for part in vor.constGet()]
        feedback.pushInfo(self.tr(f"{len(cells)} Voronoi cells"))

        # 4) Assign each cell to its generating building via point lookup.
        pt_index = QgsSpatialIndex()
        pt_feats = []
        for i, (x, y, key) in enumerate(seeds):
            pf = QgsFeature(i)
            pf.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
            pt_index.addFeature(pf)
            pt_feats.append(key)
        per_building = {}
        for cell in cells:
            if feedback.isCanceled():
                break
            hits = pt_index.intersects(cell.boundingBox())
            for hid in hits:
                # cheap containment check; a Voronoi cell contains exactly
                # its generators
                x, y, key = seeds[hid]
                if cell.contains(QgsGeometry.fromPointXY(QgsPointXY(x, y))):
                    per_building.setdefault(pt_feats[hid], []).append(cell)
                    break

        # 5) Dissolve per building, clip to mask, write.
        fields = self.make_fields(("cell_id", LONG), ("cell_m2", DOUBLE),
                                  base=source.fields())
        sink, dest = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields,
            QgsWkbTypes.MultiPolygon, crs)
        n_src = len(source.fields())
        written = 0
        for key, cell_list in per_building.items():
            if feedback.isCanceled():
                break
            # GEOS Voronoi cells can be borderline-invalid; heal before union.
            union = QgsGeometry.unaryUnion([c.makeValid() for c in cell_list])
            if union.isEmpty():
                union = QgsGeometry.collectGeometry(cell_list).buffer(0.0, 1)
            merged = union.intersection(mask)
            if merged.isEmpty():
                continue
            out = QgsFeature(fields)
            out.setGeometry(merged)
            out.setAttributes(list(feats[key].attributes())[:n_src] +
                              [key, float(merged.area())])
            sink.addFeature(out, QgsFeatureSink.FastInsert)
            written += 1
        feedback.pushInfo(self.tr(f"Wrote {written} tessellation cells."))
        return {self.OUTPUT: dest}

    def createInstance(self):
        return MorphologicalTessellationAlgorithm()
