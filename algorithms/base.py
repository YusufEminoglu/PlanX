# -*- coding: utf-8 -*-
"""Shared base class and helpers for PlanX Processing algorithms."""
from __future__ import annotations

import os

import numpy as np

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    QgsCoordinateTransform,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsProcessingAlgorithm,
    QgsProcessingException,
)

PLUGIN_DIR = os.path.dirname(os.path.dirname(__file__))

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


class PlanXAlgorithm(QgsProcessingAlgorithm):
    """Base: per-tool icon, translation helper and geometry extraction."""

    GROUP = GROUP_NETWORK
    #: per-tool icon file under icons/ (falls back to the plugin icon)
    ICON = ""

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
        return "https://github.com/YusufEminoglu/PlanX"

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
    def source_polylines(source, feedback=None, min_length: float = 1e-6):
        """Explode a line source into single-part polylines.

        Returns (polylines, features): ``polylines`` is a list of (k, 2)
        float arrays; ``features`` is the parent QgsFeature for each part.
        """
        polylines, features = [], []
        for f in source.getFeatures():
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
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
