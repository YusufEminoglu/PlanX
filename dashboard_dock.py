# -*- coding: utf-8 -*-
"""PlanX Plan Dashboard dock: live score cards + one-click HTML report.

Reads the output layers of the PlanX analytics straight from the project
(auto-detected by their field signatures), shows the plan score cards and
exports the same one-file HTML Plan Performance Report as the
``planx:performancereport`` algorithm.
"""
from __future__ import annotations

import os

from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsProject, QgsVectorLayer

from .engine import report as rpt

PLUGIN_DIR = os.path.dirname(__file__)

_QSS = """
QLabel#planxHeader {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #0f6b6b, stop:1 #13a0a0);
    color: white; font-weight: bold; font-size: 13px;
    padding: 10px 12px; border-radius: 6px;
}
QFrame.planxCard {
    background: white; border: 1px solid #e0e6e8; border-radius: 8px;
}
QLabel.cardLabel { color: #7f8c8d; font-size: 10px; font-weight: bold; }
QLabel.cardValue { font-size: 22px; font-weight: bold; }
QLabel.cardSub { color: #95a5a6; font-size: 9px; }
QPushButton#planxReportBtn {
    background-color: #13a0a0; border: 1px solid #0f6b6b; color: white;
    font-weight: bold; padding: 7px 12px; border-radius: 6px;
}
QPushButton#planxReportBtn:hover { background-color: #0f8a8a; }
"""

# field signatures of the PlanX output layers (all lowercase)
_SIGNATURES = {
    "access": ("score", "n_reach"),
    "balance": ("balance_m2", "m2_capita"),
    "facilities": ("utilization", "assigned"),
    "demand": ("covered", "net_cost"),
    "density": ("dens_ha", "value"),
}

_ROLES = (
    ("access", "Access scores"),
    ("balance", "Balance table"),
    ("facilities", "Facility adequacy"),
    ("demand", "Demand coverage"),
    ("density", "Density grid"),
)


def _field_names(layer) -> set:
    return {f.name().lower() for f in layer.fields()}


def _matches(layer, role: str) -> bool:
    return set(_SIGNATURES[role]) <= _field_names(layer)


def layer_rows(layer, names: dict) -> list:
    """Read fields of a vector layer into plain dict rows (missing -> None)."""
    idx = {key: layer.fields().lookupField(fname) for key, fname in names.items()}
    rows = []
    for f in layer.getFeatures():
        attrs = f.attributes()
        rows.append({key: (attrs[i] if i >= 0 else None) for key, i in idx.items()})
    return rows


class PlanXDashboardDock(QDockWidget):
    """Score cards over the PlanX output layers + HTML report export."""

    def __init__(self, iface):
        super().__init__("PlanX Dashboard")
        self.iface = iface
        self.setObjectName("PlanXDashboardDock")
        self.combos = {}

        body = QWidget()
        outer = QVBoxLayout(body)
        outer.setContentsMargins(8, 8, 8, 8)
        header = QLabel("PlanX - Plan Performance Dashboard")
        header.setObjectName("planxHeader")
        outer.addWidget(header)
        hint = QLabel("Run the PlanX tools first (access score, land-use "
                      "balance, facility adequacy, density grid), then pick "
                      "their output layers - or just Refresh: layers are "
                      "auto-detected by their fields.")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        form = QFormLayout()
        form.setVerticalSpacing(4)
        self.title_edit = QLineEdit("Urban Plan")
        form.addRow("Report title", self.title_edit)
        self.pop_edit = QLineEdit("")
        self.pop_edit.setPlaceholderText("planned population (optional)")
        form.addRow("Population", self.pop_edit)
        for role, label in _ROLES:
            combo = QComboBox()
            self.combos[role] = combo
            form.addRow(label, combo)
        outer.addLayout(form)

        btn_row = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.setToolTip("Re-scan project layers and recompute the cards")
        refresh.clicked.connect(self.refresh)
        btn_row.addWidget(refresh)
        report_btn = QPushButton("Save HTML Report...")
        report_btn.setObjectName("planxReportBtn")
        report_btn.setToolTip("Write the one-file Plan Performance Report "
                              "and open it in the browser")
        report_btn.clicked.connect(self.save_report)
        btn_row.addWidget(report_btn)
        outer.addLayout(btn_row)

        self.cards_host = QWidget()
        self.cards_grid = QGridLayout(self.cards_host)
        self.cards_grid.setContentsMargins(0, 6, 0, 0)
        self.cards_grid.setSpacing(6)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.cards_host)
        outer.addWidget(scroll, 1)

        body.setStyleSheet(_QSS)
        self.setWidget(body)

        project = QgsProject.instance()
        project.layersAdded.connect(lambda *_: self._populate_combos())
        project.layersRemoved.connect(lambda *_: self._populate_combos())
        for combo in self.combos.values():
            combo.currentIndexChanged.connect(lambda *_: self._update_cards())
        self.refresh()

    # ------------------------------------------------------------------ #
    def _vector_layers(self):
        return [lyr for lyr in QgsProject.instance().mapLayers().values()
                if isinstance(lyr, QgsVectorLayer)]

    def _populate_combos(self):
        layers = self._vector_layers()
        for role, combo in self.combos.items():
            current = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("(none)", None)
            candidates = [lyr for lyr in layers if _matches(lyr, role)]
            for lyr in candidates:
                combo.addItem(lyr.name(), lyr.id())
            pick = 0
            if current:
                pick = max(0, combo.findData(current))
            elif candidates:
                pick = 1  # auto-select the first matching layer
            combo.setCurrentIndex(pick)
            combo.blockSignals(False)

    def _layer(self, role):
        layer_id = self.combos[role].currentData()
        return QgsProject.instance().mapLayer(layer_id) if layer_id else None

    def refresh(self):
        self._populate_combos()
        self._update_cards()

    # ------------------------------------------------------------------ #
    def _collect(self):
        """Read the selected layers into the engine's plain-data inputs."""
        access = balance = adequacy = density = None
        lyr = self._layer("access")
        if lyr is not None:
            idx = lyr.fields().lookupField("score")
            scores, points = [], []
            for f in lyr.getFeatures():
                try:
                    scores.append(float(f.attributes()[idx]))
                except (TypeError, ValueError):
                    continue
                g = f.geometry()
                if g is not None and not g.isEmpty():
                    p = g.pointOnSurface().asPoint()
                    points.append((p.x(), p.y()))
                else:
                    points.append((0.0, 0.0))
            if scores:
                access = {"scores": scores, "points": points}
        lyr = self._layer("balance")
        if lyr is not None:
            balance = layer_rows(lyr, {
                "category": "category", "area_m2": "area_m2",
                "m2_per_capita": "m2_capita", "required_m2": "required",
                "balance_m2": "balance_m2", "status": "status"})
            for r in balance:
                for k in ("area_m2", "m2_per_capita", "required_m2", "balance_m2"):
                    r[k] = float(r[k] or 0.0)
                r["status"] = str(r["status"] or "")
        lyr = self._layer("facilities")
        if lyr is not None:
            facilities = layer_rows(lyr, {
                "facility": "facility", "capacity": "capacity",
                "assigned": "assigned", "utilization": "utilization",
                "status": "status"})
            demand = []
            dem = self._layer("demand")
            if dem is not None:
                names = {"covered": "covered"}
                pop_fields = [f.name() for f in dem.fields()
                              if f.name().lower().startswith("pop")
                              and f.isNumeric()]
                if pop_fields:
                    names["pop"] = pop_fields[0]
                demand = layer_rows(dem, names)
            adequacy = {"facilities": facilities, "demand": demand}
        lyr = self._layer("density")
        if lyr is not None:
            idx = lyr.fields().lookupField("dens_ha")
            values = []
            for f in lyr.getFeatures():
                try:
                    values.append(float(f.attributes()[idx]))
                except (TypeError, ValueError):
                    continue
            if values:
                density = {"values": values}
        return access, balance, adequacy, density

    def _update_cards(self):
        while self.cards_grid.count():
            item = self.cards_grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        try:
            access, balance, adequacy, density = self._collect()
        except Exception as exc:
            self.cards_grid.addWidget(QLabel(f"Could not read layers: {exc}"), 0, 0)
            return
        a_sum = rpt.access_summary(access["scores"]) if access else None
        b_sum = rpt.balance_summary(balance) if balance is not None else None
        q_sum = (rpt.adequacy_summary(adequacy["facilities"], adequacy["demand"])
                 if adequacy else None)
        d_sum = rpt.density_summary(density["values"]) if density else None
        cards = rpt.report_cards(a_sum, b_sum, q_sum, d_sum)
        if not cards:
            empty = QLabel("No PlanX output layers found yet - run a tool, "
                           "then Refresh.")
            empty.setWordWrap(True)
            self.cards_grid.addWidget(empty, 0, 0)
            return
        for i, card in enumerate(cards):
            self.cards_grid.addWidget(self._card_widget(card), i // 2, i % 2)

    def _card_widget(self, card) -> QFrame:
        frame = QFrame()
        frame.setProperty("class", "planxCard")
        color = rpt.TONE_COLORS.get(card.get("tone", "info"), "#13a0a0")
        frame.setStyleSheet(
            "QFrame { background: white; border: 1px solid #e0e6e8;"
            f" border-top: 3px solid {color}; border-radius: 8px; }}"
            "QLabel { border: none; }")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(1)
        label = QLabel(card["label"].upper())
        label.setProperty("class", "cardLabel")
        value = QLabel(card["value"])
        value.setProperty("class", "cardValue")
        value.setStyleSheet(f"color: {color}; font-size: 22px; font-weight: bold;")
        sub = QLabel(card["sub"])
        sub.setProperty("class", "cardSub")
        sub.setWordWrap(True)
        for w in (label, value, sub):
            lay.addWidget(w)
        return frame

    # ------------------------------------------------------------------ #
    def save_report(self):
        try:
            access, balance, adequacy, density = self._collect()
        except Exception as exc:
            self.iface.messageBar().pushWarning("PlanX", f"Could not read layers: {exc}")
            return
        if access is None and balance is None and adequacy is None:
            self.iface.messageBar().pushWarning(
                "PlanX", "Nothing to report - select at least one PlanX "
                "output layer (access scores, balance table or facility "
                "adequacy).")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Plan Performance Report",
            os.path.join(os.path.expanduser("~"), "plan_performance_report.html"),
            "HTML files (*.html)")
        if not path:
            return
        try:
            population = float(self.pop_edit.text().replace(",", "."))
        except ValueError:
            population = None
        from .algorithms.alg_performance_report import _plugin_version
        html = rpt.build_html(
            self.title_edit.text() or "Urban Plan", population=population,
            access=access, balance=balance, adequacy=adequacy,
            density=density, plugin_version=_plugin_version())
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(html)
        except OSError as exc:
            self.iface.messageBar().pushWarning("PlanX", f"Could not write report: {exc}")
            return
        self.iface.messageBar().pushSuccess(
            "PlanX", f"Plan Performance Report saved: {path}")
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
