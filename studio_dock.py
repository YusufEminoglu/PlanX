# -*- coding: utf-8 -*-
"""PlanX Studio: searchable, persistent and workflow-aware tool launcher."""
from __future__ import annotations

import json
import os

from qgis.PyQt.QtCore import QSettings, Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices, QIcon
from qgis.PyQt.QtWidgets import (
    QCheckBox, QComboBox, QDockWidget, QHBoxLayout, QLabel, QLineEdit,
    QMenu, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)
from qgis.core import QgsApplication

from .algorithms.base import DOC_BASE_URL

PLUGIN_DIR = os.path.dirname(__file__)

TOOL_PRESETS = {
    "planx:preparenetwork": {"CREATE_INDEX": True, "MIN_LENGTH": 0.05},
    "planx:networkcentrality": {"RADIUS": 800.0},
    "planx:accessscore": {"THRESHOLD": 15.0},
    "planx:walkability": {"LOW_THRESHOLD": 50.0},
}

GUIDED_WORKFLOWS = {
    "Network → centrality → accessibility → equity": (
        "planx:preparenetwork", "planx:networkcentrality", "planx:accessscore", "planx:accessequity",
    ),
    "Population → housing → capacity → allocation": (
        "planx:populationprojection", "planx:housingneeds", "planx:residentialcapacity", "planx:landallocation",
    ),
    "GTFS → frequency → transit access → equity": (
        "planx:gtfsimport", "planx:transitfrequency", "planx:transitaccess", "planx:accessequity",
    ),
    "Growth → population → access → compare": (
        "planx:growthsim", "planx:popallocate", "planx:accessscore", "planx:scenariocompare",
    ),
    "Hydrology → HAND → flood exposure": (
        "planx:flowaccumulation", "planx:handindex", "planx:floodexposure",
    ),
    "Walkability → cycling → route quality": (
        "planx:walkability", "planx:cyclingstress", "planx:routequality",
    ),
}

_QSS = """
QWidget#planxDockBody { background: #f4f7fb; }
QLabel#planxHeader { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #0f6b6b,stop:1 #13a0a0);
 color:white; font-weight:bold; font-size:13px; padding:10px 12px; border-radius:6px; }
QTreeWidget { background:#ffffff; color:#111827; border:1px solid #cbd5e1; font-size:12px; }
QTreeWidget::item:selected { background:#d9f3f2; color:#0f6b6b; }
QLineEdit,QComboBox { background:#ffffff; color:#111827; border:1px solid #94a3b8; border-radius:4px; padding:5px; }
QPushButton { background:#e2e8f0; color:#111827; border:1px solid #94a3b8; border-radius:4px; padding:5px 8px; }
QPushButton:hover { background:#cbd5e1; }
QCheckBox,QLabel { color:#111827; }
QPushButton#planxDoc { background:#13a0a0; color:white; border:none; font-weight:bold; }
QPushButton#planxRate { background:#cf9836; color:white; border:none; font-weight:bold; }
QPushButton#planxRate:hover { background:#b8862d; }
"""


class PlanXStudioDock(QDockWidget):
    def __init__(self, iface):
        super().__init__("PlanX Studio")
        self.iface = iface
        self.setObjectName("PlanXStudioDock")
        body = QWidget()
        body.setObjectName("planxDockBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(8, 8, 8, 8)
        header = QLabel("PlanX - Urban Analytics Studio")
        header.setObjectName("planxHeader")
        layout.addWidget(header)
        hint = QLabel("Search, favorite, and chain planning tools. Double-click to run; right-click for options.")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search planning tools…")
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)

        flow = QHBoxLayout()
        self.workflow_combo = QComboBox()
        self.workflow_combo.addItems(GUIDED_WORKFLOWS)
        flow.addWidget(self.workflow_combo, 1)
        run = QPushButton("Run workflow")
        run.clicked.connect(self._launch_workflow)
        flow.addWidget(run)
        layout.addLayout(flow)

        self.compatible_only = QCheckBox("Show tools compatible with active layer")
        self.compatible_only.toggled.connect(self._populate)
        layout.addWidget(self.compatible_only)

        button_row = QHBoxLayout()
        docs = QPushButton("Open Manual")
        docs.setObjectName("planxDoc")
        docs.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(DOC_BASE_URL)))
        button_row.addWidget(docs)

        rate_btn = QPushButton("★ Rate on GeoPhilo")
        rate_btn.setObjectName("planxRate")
        rate_btn.setToolTip("Submit verified rating & feedback on GeoPhilo")
        rate_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://geophilo.com/feedback/?plugin=planx&v=4.11.0")))
        button_row.addWidget(rate_btn)
        layout.addLayout(button_row)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.itemDoubleClicked.connect(self._launch)
        layout.addWidget(self.tree, 1)
        body.setStyleSheet(_QSS)
        self.setWidget(body)
        self._populate()

    @staticmethod
    def _settings():
        return QSettings("PlanX", "UrbanAnalyticsStudio")

    def _stored_ids(self, key):
        try:
            value = json.loads(str(self._settings().value(key, "[]")))
            return [item for item in value if isinstance(item, str)][:20]
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    def _save_ids(self, key, values):
        self._settings().setValue(key, json.dumps(list(dict.fromkeys(values))[:20]))

    def _populate(self):
        self.tree.clear()
        provider = QgsApplication.processingRegistry().providerById("planx")
        if provider is None:
            self.tree.addTopLevelItem(QTreeWidgetItem(["PlanX provider not loaded"]))
            return
        fallback = QIcon(os.path.join(PLUGIN_DIR, "icons", "icon.png"))
        # Read the count off the provider rather than keeping a literal here: the
        # number is in the manual, the README and metadata.txt already, and a
        # fourth copy nobody checks is a fourth copy that goes stale. A late
        # release shipped this reading "Search 71 planning tools" against 72.
        self.search.setPlaceholderText(
            f"Search {len(provider.algorithms())} planning tools…")
        self._shortcut_group(provider, "★ Favorites", self._stored_ids("favorites"), fallback)
        self._shortcut_group(provider, "↻ Recent", self._stored_ids("recent"), fallback)
        groups = {}
        for alg in provider.algorithms():
            if self.compatible_only.isChecked() and not self._compatible(alg):
                continue
            groups.setdefault(alg.group(), []).append(alg)
        for group in sorted(groups):
            parent = QTreeWidgetItem([group])
            self.tree.addTopLevelItem(parent)
            for alg in sorted(groups[group], key=lambda item: item.displayName()):
                self._add_algorithm_item(parent, alg, fallback)
            parent.setExpanded(True)
        self._filter(self.search.text())

    @staticmethod
    def _add_algorithm_item(parent, alg, fallback):
        item = QTreeWidgetItem([alg.displayName()])
        icon = alg.icon()
        item.setIcon(0, icon if not icon.isNull() else fallback)
        item.setToolTip(0, alg.shortHelpString())
        item.setData(0, Qt.ItemDataRole.UserRole, alg.id())
        parent.addChild(item)

    def _shortcut_group(self, provider, label, identifiers, fallback):
        algorithms = [provider.algorithm(item.split(":", 1)[-1]) for item in identifiers]
        algorithms = [item for item in algorithms if item is not None]
        if not algorithms:
            return
        parent = QTreeWidgetItem([label])
        self.tree.addTopLevelItem(parent)
        for alg in algorithms:
            self._add_algorithm_item(parent, alg, fallback)
        parent.setExpanded(True)

    def _compatible(self, alg):
        layer = self.iface.activeLayer()
        if layer is None:
            return True
        source_params = [item for item in alg.parameterDefinitions() if hasattr(item, "dataTypes")]
        if not source_params:
            return True
        return any(parameter.checkValueIsAcceptable(layer) for parameter in source_params)

    def _launch(self, item, _column):
        alg_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not alg_id:
            return
        try:
            import processing
            self._save_ids("recent", [alg_id] + self._stored_ids("recent"))
            processing.execAlgorithmDialog(alg_id, dict(TOOL_PRESETS.get(alg_id, {})))
            self._populate()
        except Exception as exc:
            self.iface.messageBar().pushWarning("PlanX", f"Could not open tool: {exc}")

    def _context_menu(self, pos):
        item = self.tree.itemAt(pos)
        alg_id = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not alg_id:
            return
        menu = QMenu(self)
        favorites = self._stored_ids("favorites")
        action = menu.addAction("Remove from Favorites" if alg_id in favorites else "Add to Favorites")
        action.triggered.connect(lambda: self._toggle_favorite(alg_id))
        if alg_id in TOOL_PRESETS:
            preset = menu.addAction("Launch with Recommended Preset")
            preset.triggered.connect(lambda: self._launch_preset(alg_id))
        help_action = menu.addAction("View Documentation")
        help_action.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(DOC_BASE_URL + "#" + alg_id.split(":")[-1])))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _toggle_favorite(self, alg_id):
        favorites = self._stored_ids("favorites")
        favorites.remove(alg_id) if alg_id in favorites else favorites.insert(0, alg_id)
        self._save_ids("favorites", favorites)
        self._populate()

    @staticmethod
    def _launch_preset(alg_id):
        import processing
        processing.execAlgorithmDialog(alg_id, dict(TOOL_PRESETS.get(alg_id, {})))

    def _launch_workflow(self):
        import processing
        workflow = self.workflow_combo.currentText()
        for index, alg_id in enumerate(GUIDED_WORKFLOWS.get(workflow, ())):
            parameters = dict(TOOL_PRESETS.get(alg_id, {}))
            self.iface.messageBar().pushInfo("PlanX", f"Step {index + 1}/{len(GUIDED_WORKFLOWS[workflow])}: {alg_id}")
            if processing.execAlgorithmDialog(alg_id, parameters) is None:
                break

    def _filter(self, text):
        needle = text.strip().lower()
        for index in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(index)
            visible = False
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                matched = not needle or needle in child.text(0).lower()
                child.setHidden(not matched)
                visible = visible or matched
            parent.setHidden(not visible)
            if needle:
                parent.setExpanded(True)
