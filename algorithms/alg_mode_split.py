# -*- coding: utf-8 -*-
"""Mode Split algorithm wrapper."""
from __future__ import annotations

import numpy as np

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
    QgsProcessingParameterString,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_DEMAND, PlanXAlgorithm
from ..engine import demand


class ModeSplitAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_DEMAND
    ICON = "tool_modesplit.png"
    FLOWS = "FLOWS"
    FLOW_FIELD = "FLOW_FIELD"
    MODE_TIMES = "MODE_TIMES"
    MODE_BETAS = "MODE_BETAS"
    MODE_ASCS = "MODE_ASCS"
    MODE_NAMES = "MODE_NAMES"
    OUTPUT = "OUTPUT"

    def name(self):
        return "modesplit"

    def displayName(self):
        return self.tr("Mode Split")

    def shortHelpString(self):
        return self.tr(
            "Screening-quality mode split travel demand model.\n\n"
            "Calculates shares and flows for each transportation mode using a multinomial "
            "logit model based on travel times, coefficients (betas), and alternative-specific "
            "constants (ASCs).\n\n"
            "Outputs the original features annotated with shares and flows for each mode.\n\n"
            "How to read the results\n"
            "- share_<mode> is the probability the average traveller "
            "picks that mode given the TIMES you supplied; flow_<mode> "
            "scales it by the OD volume. Read shares comparatively "
            "along corridors: where transit share collapses despite "
            "similar distances, the time matrix is telling you where "
            "service is uncompetitive.\n"
            "- The logit responds to time DIFFERENCES: with beta -0.1, "
            "a 10-minute penalty roughly triples the odds against a "
            "mode. So the scenario lever is minutes saved, and the "
            "output converts minutes into share points.\n"
            "- ASCs carry everything time does not (comfort, cost, "
            "habit): without calibration to an observed split, treat "
            "absolute shares as screening and DIFFERENCES between "
            "scenarios as the finding.\n\n"
            "Using the results: run base vs project times (a new tram, "
            "a bus lane) and report the flow_transit gain on the "
            "affected pairs; multiply flow_car changes by trip length "
            "for a first VKT/emissions estimate; large flows where no "
            "mode is under 30 minutes are the pairs land-use policy "
            "(not transport) must fix."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.FLOWS, self.tr("OD flows layer"), [QgsProcessing.TypeVectorLine, QgsProcessing.TypeVectorPoint]))
        self.addParameter(QgsProcessingParameterField(
            self.FLOW_FIELD, self.tr("Total flow field"), parentLayerParameterName=self.FLOWS,
            type=QgsProcessingParameterField.Numeric))
        self.addParameter(QgsProcessingParameterString(
            self.MODE_TIMES, self.tr("Mode travel time fields (comma-separated)"),
            defaultValue="time_car,time_transit"))
        self.addParameter(QgsProcessingParameterString(
            self.MODE_BETAS, self.tr("Mode utility time coefficients (comma-separated, typically negative)"),
            defaultValue="-0.1,-0.1"))
        self.addParameter(QgsProcessingParameterString(
            self.MODE_ASCS, self.tr("Mode alternative-specific constants (comma-separated)"),
            defaultValue="0.0,0.0"))
        self.addParameter(QgsProcessingParameterString(
            self.MODE_NAMES, self.tr("Mode names (comma-separated, optional)"),
            defaultValue="car,transit"))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Annotated OD flows")))

    def processAlgorithm(self, parameters, context, feedback):
        flows = self.parameterAsSource(parameters, self.FLOWS, context)
        flow_field = self.parameterAsString(parameters, self.FLOW_FIELD, context)
        mode_times_str = self.parameterAsString(parameters, self.MODE_TIMES, context)
        mode_betas_str = self.parameterAsString(parameters, self.MODE_BETAS, context)
        mode_ascs_str = self.parameterAsString(parameters, self.MODE_ASCS, context)
        mode_names_str = self.parameterAsString(parameters, self.MODE_NAMES, context)

        time_fields = [t.strip() for t in mode_times_str.replace(";", ",").split(",") if t.strip()]
        betas = [float(b.strip()) for b in mode_betas_str.replace(";", ",").split(",") if b.strip()]
        ascs = [float(a.strip()) for a in mode_ascs_str.replace(";", ",").split(",") if a.strip()]

        K = len(time_fields)
        if len(betas) != K or len(ascs) != K:
            raise QgsProcessingException("Number of betas and ASCs must match number of mode time fields.")

        names = []
        if mode_names_str:
            names = [n.strip() for n in mode_names_str.replace(";", ",").split(",") if n.strip()]
        if len(names) < K:
            names = names + [f"mode{i+1}" for i in range(len(names), K)]
        else:
            names = names[:K]

        # Build output fields
        extra_specs = []
        for name in names:
            extra_specs.append((f"share_{name}", DOUBLE))
            extra_specs.append((f"flow_{name}", DOUBLE))

        out_fields = self.make_fields(*extra_specs, base=flows.fields())

        sink, dest = self.parameterAsSink(
            parameters, self.OUTPUT, context, out_fields,
            flows.wkbType(), flows.sourceCrs())

        flow_idx = flows.fields().lookupField(flow_field)
        time_idxs = [flows.fields().lookupField(fld) for fld in time_fields]
        for k, idx in enumerate(time_idxs):
            if idx < 0:
                raise QgsProcessingException(f"Time field '{time_fields[k]}' not found in flows layer.")

        feats = []
        flow_vals = []
        mode_times_data = [[] for _ in range(K)]

        for f in flows.getFeatures():
            feats.append(f)
            try:
                fl = float(f.attributes()[flow_idx] or 0.0)
            except (TypeError, ValueError):
                fl = 0.0
            flow_vals.append(fl)

            for k in range(K):
                try:
                    t = float(f.attributes()[time_idxs[k]] or 0.0)
                except (TypeError, ValueError):
                    t = 0.0
                mode_times_data[k].append(t)

        times_arr = [np.array(mode_times_data[k], dtype=np.float64) for k in range(K)]
        shares_arr = demand.mode_split(times_arr, betas, ascs)

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

        n_base = len(flows.fields())
        for i, f in enumerate(feats):
            if feedback.isCanceled():
                break
            out_feat = QgsFeature(out_fields)
            out_feat.setGeometry(rebuild_geom(f.geometry()))

            extra_attrs = []
            for k in range(K):
                sh = float(shares_arr[k][i])
                fl = float(sh * flow_vals[i])
                extra_attrs.extend([round(sh, 4), round(fl, 2)])

            out_feat.setAttributes(list(f.attributes())[:n_base] + extra_attrs)
            sink.addFeature(out_feat, QgsFeatureSink.FastInsert)

        return {self.OUTPUT: dest}

    def createInstance(self):
        return ModeSplitAlgorithm()
