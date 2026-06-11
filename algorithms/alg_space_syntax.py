# -*- coding: utf-8 -*-
"""Space Syntax: segment angular analysis (integration, choice, NACH, NAIN)."""
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
    QgsProcessingParameterString,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_CENTRALITY, INT, PlanXAlgorithm
from ..engine import graphs, syntax


class SpaceSyntaxAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_CENTRALITY
    ICON = "tool_spacesyntax.png"
    NETWORK = "NETWORK"
    RADII = "RADII"
    OUTPUT = "OUTPUT"

    def name(self):
        return "spacesyntax"

    def displayName(self):
        return self.tr("Space Syntax (Segment Angular Analysis)")

    def shortHelpString(self):
        return self.tr(
            "Segment angular analysis on road centerlines - the modern space "
            "syntax workflow (Hillier and Iida 2005; Turner 2001), computed "
            "entirely by the embedded engine. No depthmapX, no axial map "
            "needed.\n\n"
            "Each segment-to-segment turn costs angle/90 (straight = 0, right "
            "angle = 1); internal polyline curvature is included. For every "
            "radius the tool reports:\n"
            "- NC / TD / MD: node count, angular total and mean depth\n"
            "- NAIN: normalized angular integration (to-movement potential)\n"
            "- CH and NACH: angular choice and its normalization "
            "(through-movement potential), Hillier, Yang and Turner 2012\n\n"
            "Radii are metric (map units) along the network; 'n' = global. "
            "Use 400-800 for pedestrian scale, 2000+ for vehicular structure. "
            "Run 'Prepare Network' first so crossing lines share nodes. "
            "Field suffix per radius, e.g. NACH_800, NAIN_n."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("Street network (lines, prepared)"),
            [QgsProcessing.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterString(
            self.RADII, self.tr("Metric radii (comma separated, 'n' = global)"),
            "800, n"))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Segment analysis")))

    def processAlgorithm(self, parameters, context, feedback):
        network = self.parameterAsSource(parameters, self.NETWORK, context)
        self.require_projected(network, "Street network")
        try:
            radii = syntax.parse_radii(self.parameterAsString(parameters, self.RADII, context))
        except ValueError as exc:
            raise QgsProcessingException(str(exc))

        polylines, line_feats = self.source_polylines(network)
        seg_graph = graphs.build_segment_graph(polylines)
        feedback.pushInfo(self.tr(f"Segment graph: {seg_graph.n} segments"))
        if seg_graph.n > 20000 and any(r is None for r in radii):
            feedback.pushWarning(self.tr(
                "Global radius on a very large segment map can take long - "
                "consider metric radii only."))

        specs = [("connectivity", INT)]
        for r in radii:
            lab = syntax.radius_label(r)
            specs += [(f"NC_{lab}", DOUBLE), (f"TD_{lab}", DOUBLE),
                      (f"MD_{lab}", DOUBLE), (f"NAIN_{lab}", DOUBLE),
                      (f"CH_{lab}", DOUBLE), (f"NACH_{lab}", DOUBLE)]
        fields = self.make_fields(*specs, base=network.fields())

        results = []
        for ri, r in enumerate(radii):
            if feedback.isCanceled():
                break
            feedback.pushInfo(self.tr(f"Radius {syntax.radius_label(r)}..."))
            base = 100.0 * ri / len(radii)
            span = 100.0 / len(radii)
            results.append(syntax.segment_angular_analysis(
                seg_graph, radius=r,
                cancel=feedback.isCanceled,
                progress=lambda p, b=base, s=span: feedback.setProgress(int(b + s * p))))

        sink, dest = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields,
            QgsWkbTypes.LineString, network.sourceCrs())
        n_src = len(network.fields())
        for s in range(seg_graph.n):
            f = QgsFeature(fields)
            f.setGeometry(QgsGeometry.fromPolylineXY(
                [QgsPointXY(x, y) for x, y in polylines[s]]))
            attrs = list(line_feats[s].attributes())[:n_src]
            attrs.append(int(seg_graph.connectivity[s]))
            for res in results:
                attrs += [float(res["nc"][s]), float(res["td"][s]),
                          float(res["md"][s]), float(res["nain"][s]),
                          float(res["choice"][s]), float(res["nach"][s])]
            f.setAttributes(attrs)
            sink.addFeature(f, QgsFeatureSink.FastInsert)
        return {self.OUTPUT: dest}

    def createInstance(self):
        return SpaceSyntaxAlgorithm()
