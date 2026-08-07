# -*- coding: utf-8 -*-
"""PlanX Studio dock: a compact launcher for the analytics toolset."""
from __future__ import annotations

import os

from qgis.PyQt.QtCore import Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices, QIcon
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsApplication

PLUGIN_DIR = os.path.dirname(__file__)
DOC_BASE_URL = "https://yusufeminoglu.github.io/PlanX/PLANX_REFERENCE_MANUAL.html"

_HEADER_QSS = """
QLabel#planxHeader {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #0f6b6b, stop:1 #13a0a0);
    color: white; font-weight: bold; font-size: 13px;
    padding: 10px 12px; border-radius: 6px;
}
QTreeWidget { border: none; font-size: 12px; }
"""


class PlanXStudioDock(QDockWidget):
    """Browses the PlanX provider and launches algorithm dialogs."""

    def __init__(self, iface):
        super().__init__("PlanX Studio")
        self.iface = iface
        self.setObjectName("PlanXStudioDock")

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(8, 8, 8, 8)
        header = QLabel("PlanX - Urban Analytics Studio")
        header.setObjectName("planxHeader")
        layout.addWidget(header)
        hint = QLabel("Double-click a tool to run it. Right-click for documentation.")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # Documentation button row
        btn_row = QHBoxLayout()
        doc_btn = QPushButton("📖 Open Reference Manual")
        doc_btn.setToolTip("Open the comprehensive academic reference manual (GitHub Pages)")
        doc_btn.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl(DOC_BASE_URL)))
        doc_btn.setStyleSheet(
            "QPushButton { background: #13a0a0; color: white; padding: 6px 12px; "
            "border: none; border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #0d7a7a; }")
        btn_row.addWidget(doc_btn)
        layout.addLayout(btn_row)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self.tree)
        body.setStyleSheet(_HEADER_QSS)
        self.setWidget(body)

        self._populate()
        self.tree.itemDoubleClicked.connect(self._launch)

    def _populate(self):
        self.tree.clear()
        provider = QgsApplication.processingRegistry().providerById("planx")
        if provider is None:
            self.tree.addTopLevelItem(QTreeWidgetItem(["PlanX provider not loaded"]))
            return
        fallback = QIcon(os.path.join(PLUGIN_DIR, "icons", "icon.png"))
        groups = {}
        for alg in provider.algorithms():
            groups.setdefault(alg.group(), []).append(alg)
        for group in sorted(groups):
            parent = QTreeWidgetItem([group])
            self.tree.addTopLevelItem(parent)
            for alg in sorted(groups[group], key=lambda a: a.displayName()):
                item = QTreeWidgetItem([alg.displayName()])
                try:
                    icon = alg.icon()  # per-tool icon from PlanXAlgorithm.ICON
                except Exception:
                    icon = fallback
                item.setIcon(0, icon if not icon.isNull() else fallback)
                item.setToolTip(0, alg.shortHelpString())
                item.setData(0, Qt.ItemDataRole.UserRole, alg.id())
                parent.addChild(item)
            parent.setExpanded(True)

    def _launch(self, item, _column):
        alg_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not alg_id:
            return
        try:
            import processing
            processing.execAlgorithmDialog(alg_id, {})
        except Exception as exc:
            self.iface.messageBar().pushWarning("PlanX", f"Could not open tool: {exc}")

    def _context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item:
            return
        alg_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not alg_id:
            return
        from qgis.PyQt.QtWidgets import QMenu
        menu = QMenu(self)
        help_action = menu.addAction("📖 View Documentation")
        help_action.triggered.connect(
            lambda: QDesktopServices.openUrl(
                QUrl(DOC_BASE_URL + "#" + alg_id.split(":")[-1])))
        menu.exec_(self.tree.viewport().mapToGlobal(pos))
