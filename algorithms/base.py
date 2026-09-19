# -*- coding: utf-8 -*-
"""Shared base class and helpers for PlanX Processing algorithms."""
from __future__ import annotations

import json
import os

import numpy as np

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.PyQt.QtGui import QColor, QIcon
from qgis.core import (
    QgsCoordinateTransform,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProject,
    QgsGraduatedSymbolRenderer,
    QgsRendererRange,
    QgsSymbol,
)

from ..engine.provenance import build_manifest
from ..engine import graphs

PLUGIN_DIR = os.path.dirname(os.path.dirname(__file__))
#: Single definition of the published manual URL. Every Help button
#: (helpUrl() below) and both Studio dock documentation actions resolve
#: through this constant, so it must name the host that is actually live:
#: it moved off yusufeminoglu.github.io and only metadata.txt was updated,
#: which left all 69 deep links returning 404. studio_dock.py imports this
#: rather than repeating the literal.
DOC_BASE_URL = "https://geophilo.com/planx/PLANX_REFERENCE_MANUAL.html"

GROUP_NETWORK = ("Network Analysis", "network")
GROUP_CENTRALITY = ("Centrality and Space Syntax", "centrality")
GROUP_MORPHOLOGY = ("Urban Morphology", "morphology")
GROUP_ACCESS = ("Accessibility", "accessibility")
GROUP_MICRO = ("Microclimate", "microclimate")
GROUP_STANDARDS = ("Plan Standards and QA", "standards")
GROUP_REPORT = ("Reporting and Dashboard", "reporting")
GROUP_OPTIMIZE = ("Optimization", "optimization")
GROUP_EQUITY = ("Equity", "equity")
GROUP_WALK = ("Walkability", "walkability")
GROUP_TRANSIT = ("Transit", "transit")
GROUP_VISIBILITY = ("Visibility", "visibility")
GROUP_POPULATION = ("Population and Housing", "population")
GROUP_GREEN = ("Green Infrastructure", "green")
GROUP_GROWTH = ("Urban Growth", "growth")
GROUP_CYCLE = ("Cycling", "cycling")
GROUP_HAZARD = ("Hazard Screening", "hazard")
GROUP_DEMAND = ("Travel Demand", "demand")
GROUP_SEISMIC = ("Seismic Risk", "seismic")


class PlanXAlgorithm(QgsProcessingAlgorithm):
    """Base: per-tool icon, translation helper and geometry extraction."""

    GROUP = GROUP_NETWORK
    #: per-tool icon file under icons/ (falls back to the plugin icon)
    ICON = ""

    #: Optional name of the output field the default renderer must colour.
    #: Left None, the renderer falls back to its preference-token heuristic,
    #: which is what every tool written before this attribute existed relies
    #: on. Set it where the field worth colouring does not happen to contain
    #: one of those tokens - naming a ground-motion field "risk" to satisfy a
    #: substring search would put the heuristic's vocabulary into the data.
    RENDER_FIELD = None

    def __init__(self):
        super().__init__()
        self._planx_existing_layers = set()
        self._planx_audit = None

    def tr(self, text: str) -> str:
        return QCoreApplication.translate(self.__class__.__name__, text)

    def icon(self) -> QIcon:
        if self.ICON:
            path = os.path.join(PLUGIN_DIR, "icons", self.ICON)
            if os.path.exists(path):
                return QIcon(path)
        path = os.path.join(PLUGIN_DIR, "icons", "icon.png")
        return QIcon(path) if os.path.exists(path) else super().icon()

    def group(self) -> str:
        return self.GROUP[0]

    def groupId(self) -> str:
        return self.GROUP[1]

    def helpUrl(self) -> str:
        return DOC_BASE_URL + "#" + self.name()

    # ------------------------------------------------------------------ #
    # Shared result audit and presentation
    # ------------------------------------------------------------------ #
    def prepareAlgorithm(self, parameters, context, feedback):
        store = context.temporaryLayerStore()
        self._planx_existing_layers = set(store.mapLayers()) | set(QgsProject.instance().mapLayers())
        clean_parameters = {}
        inputs = []
        for key, value in parameters.items():
            definition = self.parameterDefinition(str(key))
            if (definition is not None and hasattr(definition, "isDestination")
                    and definition.isDestination()):
                clean_parameters[str(key)] = "<output>"
                continue
            layer_value = value
            if isinstance(value, str):
                candidate = context.getMapLayer(value)
                if candidate is not None:
                    layer_value = candidate
            if hasattr(layer_value, "sourceCrs") and hasattr(layer_value, "source"):
                extent = layer_value.extent()
                layer_input = {
                    "parameter": str(key), "source": str(layer_value.source()),
                    "crs": layer_value.sourceCrs().authid(),
                    "extent": [extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum()],
                }
                if hasattr(layer_value, "featureCount"):
                    layer_input["feature_count"] = int(layer_value.featureCount())
                if hasattr(layer_value, "fields"):
                    layer_input["fields"] = [field.name() for field in layer_value.fields()]
                inputs.append(layer_input)
                clean_parameters[str(key)] = {"layer": str(layer_value.sourceName())}
            else:
                clean_parameters[str(key)] = self._audit_value(value)
        self._planx_audit = build_manifest(self.id(), clean_parameters, inputs, self._plugin_version())
        return True

    def postProcessAlgorithm(self, context, feedback):
        candidates = {}
        candidates.update(context.temporaryLayerStore().mapLayers())
        candidates.update(QgsProject.instance().mapLayers())
        for layer_id, layer in candidates.items():
            if layer_id in self._planx_existing_layers or layer is None:
                continue
            self._decorate_layer(layer)
        return {}

    @staticmethod
    def _audit_value(value):
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, (list, tuple)):
            return [PlanXAlgorithm._audit_value(item) for item in value]
        return str(value)

    @staticmethod
    def _plugin_version():
        try:
            with open(os.path.join(PLUGIN_DIR, "metadata.txt"), encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("version="):
                        return line.split("=", 1)[1].strip()
        except OSError:
            return ""
        return ""

    def _decorate_layer(self, layer):
        if self._planx_audit:
            layer.setCustomProperty("planx/algorithm_id", self.id())
            layer.setCustomProperty("planx/analysis_fingerprint", self._planx_audit["analysis_fingerprint"])
            layer.setCustomProperty("planx/provenance_json", json.dumps(self._planx_audit, ensure_ascii=False, sort_keys=True))
        fields = layer.fields() if hasattr(layer, "fields") else []
        for index, field in enumerate(fields):
            label = field.name().replace("_", " ").strip().title()
            try:
                layer.setFieldAlias(index, label)
            except (AttributeError, TypeError):
                pass
        self._apply_default_renderer(layer, fields, getattr(self, "RENDER_FIELD", None))

    @staticmethod
    def _apply_default_renderer(layer, fields, preferred_field=None):
        if not fields or not hasattr(layer, "geometryType"):
            return
        preferred = ("score", "risk", "access", "criticality", "centrality", "coverage", "prob", "index", "cost")
        numeric = [field.name() for field in fields if field.isNumeric()]
        if preferred_field:
            field_name = preferred_field if preferred_field in numeric else None
        else:
            field_name = next((name for name in reversed(numeric) if any(token in name.lower() for token in preferred)), None)
        if field_name is None:
            return
        values = [feature[field_name] for feature in layer.getFeatures() if feature[field_name] is not None]
        try:
            values = sorted(float(value) for value in values)
        except (TypeError, ValueError):
            return
        if len(values) < 2 or values[0] == values[-1]:
            return
        colors = ("#e8f5e9", "#a5d6a7", "#fff59d", "#ffb74d", "#d32f2f")
        ranges = []
        for index, color in enumerate(colors):
            lo = values[int(index * (len(values) - 1) / len(colors))]
            hi = values[int((index + 1) * (len(values) - 1) / len(colors))]
            symbol = QgsSymbol.defaultSymbol(layer.geometryType())
            if symbol is None:
                return
            symbol.setColor(QColor(color))
            ranges.append(QgsRendererRange(lo, hi, symbol, f"{lo:.3g} – {hi:.3g}"))
        layer.setRenderer(QgsGraduatedSymbolRenderer(field_name, ranges))
        layer.triggerRepaint()

    # ------------------------------------------------------------------ #
    # Geometry helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def require_projected(source, name: str):
        crs = source.sourceCrs()
        if crs.isValid() and crs.isGeographic():
            raise QgsProcessingException(
                f"'{name}' uses a geographic CRS ({crs.authid()}). PlanX "
                "analytics need metric coordinates - reproject the layer to "
                "a projected CRS (e.g. the local UTM zone) first."
            )

    @staticmethod
    def source_polylines(source, feedback=None, min_length: float = 1e-6,
                         target_crs=None, transform_context=None):
        """Explode a line source into single-part polylines.

        Returns (polylines, features): ``polylines`` is a list of (k, 2)
        float arrays; ``features`` is the parent QgsFeature for each part.

        Coordinates come back in the source layer's own CRS unless
        ``target_crs`` is given, in which case every geometry is transformed
        into it first. Pass it whenever the polylines are to be measured
        against something else - a distance in the layer's own units is only
        that layer's units, and mixing two projected CRSs (or a projected CRS
        in feet) yields numbers that are wrong without ever looking wrong.
        Callers that only want the geometry in place can leave both unset.
        """
        xform = None
        if target_crs is not None and source.sourceCrs() != target_crs:
            xform = QgsCoordinateTransform(source.sourceCrs(), target_crs,
                                           transform_context)
        polylines, features = [], []
        for f in source.getFeatures():
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
            g = QgsGeometry(g)
            if xform is not None:
                g.transform(xform)
            parts = g.asMultiPolyline() if g.isMultipart() else [g.asPolyline()]
            for part in parts:
                if len(part) < 2:
                    continue
                arr = np.asarray([(p.x(), p.y()) for p in part], dtype=np.float64)
                seg = np.diff(arr, axis=0)
                if float(np.hypot(seg[:, 0], seg[:, 1]).sum()) <= min_length:
                    continue
                polylines.append(arr)
                features.append(f)
        if not polylines:
            raise QgsProcessingException("No usable line geometry found in the network layer.")
        return polylines, features

    @classmethod
    def network_graph(cls, source, cost_field="", feedback=None,
                      min_length: float = 1e-6, use_prepared_costs=True):
        """Build a graph and honour fields produced by Prepare Network.

        ``dir_code`` uses -1/0/1 for reverse/both/forward.  If callers do
        not choose a cost field, the standardized ``cost_fwd`` and
        ``cost_rev`` columns are used automatically.  A selected legacy
        cost field remains symmetric while still respecting one-way rules.
        """
        polylines, features = cls.source_polylines(source, feedback, min_length)
        names = {field.name().lower(): field.name() for field in source.fields()}

        def standard_name(field_name):
            base = str(field_name).lower()
            matches = []
            for key, actual in names.items():
                if key == base:
                    matches.append((1, actual))
                elif key.startswith(base + "_") and key[len(base) + 1:].isdigit():
                    matches.append((int(key[len(base) + 1:]), actual))
            return max(matches, default=(0, None))[1]

        def values(field_name, fallback=None, standardized=False):
            actual = (standard_name(field_name) if standardized
                      else names.get(str(field_name).lower()))
            if not actual:
                return fallback
            index = source.fields().lookupField(actual)
            result = []
            for feature in features:
                try:
                    result.append(float(feature.attributes()[index]))
                except (TypeError, ValueError):
                    result.append(0.0)
            return result

        directions = values("dir_code", standardized=True)
        if directions is not None:
            directions = [int(value) if value in (-1.0, 0.0, 1.0) else 0
                          for value in directions]
        if cost_field:
            costs = values(cost_field)
            reverse = costs
        elif use_prepared_costs:
            costs = values("cost_fwd", standardized=True)
            reverse = values("cost_rev", standardized=True)
        else:
            costs = reverse = None
        graph = graphs.build_node_graph(
            polylines, costs=costs, reverse_costs=reverse,
            directions=directions)
        return graph, polylines, features

    @staticmethod
    def source_points(source, target_crs, transform_context):
        """Read a vector source as representative points in ``target_crs``.

        Works for point, line and polygon sources (point-on-surface).
        Returns (xy array (M, 2), features list).
        """
        xform = None
        if target_crs is not None and source.sourceCrs() != target_crs:
            xform = QgsCoordinateTransform(source.sourceCrs(), target_crs, transform_context)
        pts, feats = [], []
        for f in source.getFeatures():
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
            g = QgsGeometry(g)
            if xform is not None:
                g.transform(xform)
            p = g.pointOnSurface().asPoint()
            pts.append((p.x(), p.y()))
            feats.append(f)
        if not pts:
            raise QgsProcessingException(f"No usable features in '{source.sourceName()}'.")
        return np.asarray(pts, dtype=np.float64), feats

    @staticmethod
    def make_fields(*specs, base=None) -> QgsFields:
        """Build QgsFields from (name, QVariant.type) tuples, optionally
        appended to a copy of ``base`` fields (name collisions get suffix)."""
        fields = QgsFields()
        existing = set()
        if base is not None:
            for fld in base:
                fields.append(QgsField(fld))
                existing.add(fld.name().lower())
        for name, vtype in specs:
            final = name
            i = 1
            while final.lower() in existing:
                i += 1
                final = f"{name}_{i}"
            fields.append(QgsField(final, vtype))
            existing.add(final.lower())
        return fields


DOUBLE = QVariant.Double
INT = QVariant.Int
LONG = QVariant.LongLong
STRING = QVariant.String
