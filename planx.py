# -*- coding: utf-8 -*-
"""PlanX - Urban Analytics Studio: plugin shell.

Registers the Processing provider and a lightweight "PlanX Studio" dock
that browses and launches the toolset. All analytics live in Processing
algorithms (see `algorithms/`), all math lives in `engine/`.
"""
from __future__ import annotations

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsApplication

from .provider import PlanXProvider

PLUGIN_DIR = os.path.dirname(__file__)


class PlanX:
    """Plugin entry: Processing provider + PlanX menu + Studio dock."""

    def __init__(self, iface):
        self.iface = iface
        self.provider = None
        self.dock = None
        self.actions = []

    # ------------------------------------------------------------------ #
    def initProcessing(self):
        if self.provider is None:
            self.provider = PlanXProvider()
            QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        self.initProcessing()

        icon = QIcon(os.path.join(PLUGIN_DIR, "icons", "icon.png"))
        action = QAction(icon, "PlanX Studio", self.iface.mainWindow())
        action.setToolTip("Open the PlanX Urban Analytics Studio panel")
        action.triggered.connect(self.toggle_dock)
        self.iface.addPluginToMenu("PlanX", action)
        self.iface.addToolBarIcon(action)
        self.actions.append(action)

    def unload(self):
        for action in self.actions:
            self.iface.removePluginMenu("PlanX", action)
            self.iface.removeToolBarIcon(action)
        self.actions = []
        if self.dock is not None:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None

    # ------------------------------------------------------------------ #
    def toggle_dock(self):
        if self.dock is None:
            try:
                from .studio_dock import PlanXStudioDock
                self.dock = PlanXStudioDock(self.iface)
                self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
            except Exception as exc:  # never break the plugin over the dock
                self.iface.messageBar().pushWarning("PlanX", f"Studio panel unavailable: {exc}")
                return
        self.dock.setVisible(not self.dock.isVisible())
