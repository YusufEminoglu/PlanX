# -*- coding: utf-8 -*-
"""Urban Green Connectivity: patch components, PC index and patch importance."""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsFeatureSink,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
    QgsSpatialIndex,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_GREEN, INT, PlanXAlgorithm, STRING
from ..engine import green


class GreenConnectivityAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_GREEN
    ICON = "tool_greenconnectivity.png"
    GREENS = "GREENS"
    MAX_GAP = "MAX_GAP"
    OUT_PATCHES = "OUT_PATCHES"
    OUT_SUMMARY = "OUT_SUMMARY"

    def name(self):
        return "greenconnectivity"

    def displayName(self):
        return self.tr("Urban Green Connectivity")

    def shortHelpString(self):
        return self.tr(
            "How well does the green network HANG TOGETHER - and which "
            "patch holds it together? Two patches are considered linked "
            "when the gap between them is at most the maximum gap "
            "distance (what your target species or your pedestrians can "
            "cross); linked patches form components.\n\n"
            "The connectivity score is the binary Probability-of-"
            "Connectivity index (Saura & Pascual-Hortal): the chance that "
            "two random points of green sit in the SAME connected "
            "component - 1.0 when everything connects, 1/n for n equal "
            "isolated patches. Each patch's importance dPC is the share "
            "of that index lost if the patch (and its links) were removed "
            "- small stepping-stone patches often carry surprisingly "
            "large dPC values, which is exactly the planning argument "
            "for keeping them.\n\n"
            "Outputs the patches with their component id, component area "
            "and dPC (style by dpc to spotlight the critical links), and "
            "a one-row summary (patches, components, PC index, the most "
            "critical patch).\n\n"
            "Use a projected CRS; gaps are measured edge to edge.\n\n"
            "How to read the results\n"
            "- dPC is the protection-priority list: the patch with the "
            "highest dPC is the one whose loss most fragments the "
            "network. The planning surprise is usually a SMALL patch "
            "with a big dPC - a stepping stone bridging two large "
            "components; its hectares understate its role completely, "
            "which is the argument that saves it from redevelopment.\n"
            "- PC itself is scenario currency: rerun with a candidate "
            "corridor/pocket park added and the PC gain measures the "
            "connection, not just the added area. Compare 'new 2 ha "
            "park' vs '0.2 ha stepping stone' - the stone often wins.\n"
            "- The max gap parameter IS the species/user model: 100 m "
            "may suit pedestrians, 50 m a hedgehog, 500 m birds. State "
            "it with every result; run 2-3 gaps to test robustness.\n\n"
            "Using the results: overlay high-dPC patches on development "
            "pressure to find the conflicts worth fighting; component "
            "ids show which 'green corridors' on the plan are actually "
            "several disconnected fragments; pair with Green Space "
            "Access - connectivity serves ecology and continuous "
            "walking routes, access serves proximity, and a good plan "
            "needs both."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.GREENS, self.tr("Green patches (polygons)"),
            [QgsProcessing.SourceType.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterNumber(
            self.MAX_GAP, self.tr("Maximum gap to count as linked (map units)"),
            QgsProcessingParameterNumber.Type.Double, 100.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_PATCHES, self.tr("Patches with connectivity")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_SUMMARY, self.tr("Connectivity summary"),
            type=QgsProcessing.SourceType.TypeVector))

    def processAlgorithm(self, parameters, context, feedback):
        greens = self.parameterAsSource(parameters, self.GREENS, context)
        max_gap = self.parameterAsDouble(parameters, self.MAX_GAP, context)
        self.require_projected(greens, "Green patches")

        feats, geoms, areas = [], [], []
        index = QgsSpatialIndex()
        for f in greens.getFeatures():
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
            qf = QgsFeature(len(geoms))
            qf.setGeometry(g)
            index.insertFeature(qf)
            feats.append(f)
            geoms.append(g)
            areas.append(g.area())
        if len(feats) < 2:
            raise QgsProcessingException(
                "At least two green patches are needed.")
        if len(feats) > 400:
            raise QgsProcessingException(
                f"{len(feats)} patches - the per-patch importance loop is "
                "O(n^2); dissolve or filter below 400 first.")

        edges = []
        for i in range(len(geoms)):
            if feedback.isCanceled():
                break
            bbox = geoms[i].boundingBox().buffered(max_gap)
            for j in index.intersects(bbox):
                if j <= i:
                    continue
                if geoms[i].distance(geoms[j]) <= max_gap:
                    edges.append((i, j))
            feedback.setProgress(40.0 * (i + 1) / len(geoms))
        feedback.pushInfo(self.tr(
            f"{len(feats)} patches, {len(edges)} links within "
            f"{max_gap:g} map units."))

        conn = green.connectivity(areas, edges)

        fields = self.make_fields(
            ("comp_id", INT), ("area_m2", DOUBLE), ("comp_m2", DOUBLE),
            ("dpc", DOUBLE), base=greens.fields())
        sink, dest = self.parameterAsSink(
            parameters, self.OUT_PATCHES, context, fields,
            greens.wkbType(), greens.sourceCrs())
        n_base = len(greens.fields())
        for i, f in enumerate(feats):
            out = QgsFeature(fields)
            out.setGeometry(f.geometry())
            out.setAttributes(list(f.attributes())[:n_base] + [
                int(conn["labels"][i]) + 1, round(float(areas[i]), 1),
                round(float(conn["component_area"][i]), 1),
                round(float(conn["dpc"][i]), 3)])
            sink.addFeature(out, QgsFeatureSink.Flag.FastInsert)

        top = int(np.argmax(conn["dpc"]))
        s_fields = self.make_fields(
            ("metric", STRING), ("value", DOUBLE))
        s_sink, s_dest = self.parameterAsSink(
            parameters, self.OUT_SUMMARY, context, s_fields,
            QgsWkbTypes.Type.NoGeometry, QgsCoordinateReferenceSystem())
        for metric, value in (
                ("Patches", float(len(feats))),
                ("Links", float(len(edges))),
                ("Components", float(conn["n_components"])),
                ("PC index", float(conn["pc"])),
                ("Largest component (m2)",
                 float(conn["component_area"].max())),
                ("Top patch dPC", float(conn["dpc"][top]))):
            feat = QgsFeature(s_fields)
            feat.setAttributes([metric, round(value, 4)])
            s_sink.addFeature(feat, QgsFeatureSink.Flag.FastInsert)

        feedback.pushInfo(self.tr(
            f"{conn['n_components']} component(s); PC index "
            f"{conn['pc']:.4f}; most critical patch loses "
            f"{conn['dpc'][top]:.1f} percent of PC if removed."))
        return {self.OUT_PATCHES: dest, self.OUT_SUMMARY: s_dest}

    def createInstance(self):
        return GreenConnectivityAlgorithm()
