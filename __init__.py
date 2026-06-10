# -*- coding: utf-8 -*-
"""QGIS plugin entry point for PlanX - Urban Analytics Studio."""
from __future__ import annotations


def classFactory(iface):
    """Factory function loaded by QGIS to instantiate the plugin."""
    from .planx import PlanX
    return PlanX(iface)
