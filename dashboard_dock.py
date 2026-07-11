# -*- coding: utf-8 -*-
"""PlanX Plan Dashboard dock: live score cards + one-click HTML report.

Reads the output layers of the PlanX analytics straight from the project
(auto-detected by their field signatures), shows the plan score cards and
exports the same one-file HTML Plan Performance Report as the
``planx:performancereport`` algorithm.
"""
from __future__ import annotations

import os

from qgis.PyQt.QtCore import Qt, QUrl
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
from .engine import scenario as scn

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

from .collect import collect as _collect_layers  # noqa: E402
from .collect import layer_rows, matches as _matches  # noqa: F401,E402

_ROLES = (
    ("access", "Access scores"),
    ("balance", "Balance table"),
    ("facilities", "Facility adequacy"),
    ("demand", "Demand coverage"),
    ("density", "Density grid"),
)


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

        scn_row = QHBoxLayout()
        scn_row.addWidget(QLabel("Scenario:"))
        self.snap_a_btn = QPushButton("Save A")
        self.snap_a_btn.setToolTip("Snapshot the current score cards as "
                                   "scenario A (JSON next to the project)")
        self.snap_a_btn.clicked.connect(lambda: self.save_snapshot("a"))
        scn_row.addWidget(self.snap_a_btn)
        self.snap_b_btn = QPushButton("Save B")
        self.snap_b_btn.setToolTip("Snapshot the current score cards as "
                                   "scenario B (JSON next to the project)")
        self.snap_b_btn.clicked.connect(lambda: self.save_snapshot("b"))
        scn_row.addWidget(self.snap_b_btn)
        self.compare_btn = QPushButton("Compare A/B")
        self.compare_btn.setToolTip("Diff the two saved snapshots metric by "
                                    "metric (also available headless as the "
                                    "planx:scenariocompare algorithm)")
        self.compare_btn.clicked.connect(self.compare_snapshots)
        scn_row.addWidget(self.compare_btn)
        self.audit_btn = QPushButton("Audit...")
        self.audit_btn.setToolTip("Open the Batch Plan Auditor - run the "
                                  "whole PlanX battery and snapshot it")
        self.audit_btn.clicked.connect(self.open_auditor)
        scn_row.addWidget(self.audit_btn)
        self.rank_btn = QPushButton("Rank...")
        self.rank_btn.setToolTip("Open Scenario Ranking - rank any number of saved scenario snapshots.")
        self.rank_btn.clicked.connect(self.open_rank)
        scn_row.addWidget(self.rank_btn)
        outer.addLayout(scn_row)

        self.history_label = QLabel("")
        self.history_label.setWordWrap(True)
        self.history_label.setVisible(False)
        outer.addWidget(self.history_label)

        self.cards_host = QWidget()
        cards_col = QVBoxLayout(self.cards_host)
        cards_col.setContentsMargins(0, 6, 0, 0)
        cards_col.setSpacing(6)
        grid_host = QWidget()
        self.cards_grid = QGridLayout(grid_host)
        self.cards_grid.setContentsMargins(0, 0, 0, 0)
        self.cards_grid.setSpacing(6)
        cards_col.addWidget(grid_host)
        self.compare_label = QLabel("")
        self.compare_label.setWordWrap(True)
        self.compare_label.setTextFormat(Qt.TextFormat.RichText)
        self.compare_label.setVisible(False)
        cards_col.addWidget(self.compare_label)
        cards_col.addStretch(1)
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
        return _collect_layers({role: self._layer(role)
                                for role in self.combos})

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
    def _snapshot_dir(self) -> str:
        home = QgsProject.instance().homePath()
        if home and os.path.isdir(home):
            return home
        import tempfile
        return tempfile.gettempdir()

    def snapshot_path(self, side: str) -> str:
        return os.path.join(self._snapshot_dir(),
                            f"planx_scenario_{side.lower()}.json")

    def _current_metrics(self):
        access, balance, adequacy, density = self._collect()
        a_sum = rpt.access_summary(access["scores"]) if access else None
        b_sum = rpt.balance_summary(balance) if balance is not None else None
        q_sum = (rpt.adequacy_summary(adequacy["facilities"], adequacy["demand"])
                 if adequacy else None)
        d_sum = rpt.density_summary(density["values"]) if density else None
        overall = rpt.overall_score(a_sum, b_sum, q_sum)
        return scn.metrics_from_summaries(a_sum, b_sum, q_sum, d_sum, overall)

    def save_snapshot(self, side: str):
        try:
            metrics = self._current_metrics()
        except Exception as exc:
            self.iface.messageBar().pushWarning(
                "PlanX", f"Could not read layers: {exc}")
            return
        if not metrics:
            self.iface.messageBar().pushWarning(
                "PlanX", "Nothing to snapshot - select at least one PlanX "
                "output layer first.")
            return
        name = (self.title_edit.text() or "Urban Plan") + f" {side.upper()}"
        snap = scn.snapshot(name, metrics)
        path = self.snapshot_path(side)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(scn.to_json(snap))
        except OSError as exc:
            self.iface.messageBar().pushWarning(
                "PlanX", f"Could not write the snapshot: {exc}")
            return
        self._append_history(name, metrics)
        self.iface.messageBar().pushSuccess(
            "PlanX", f"Scenario {side.upper()} saved ({len(metrics)} "
            f"metrics): {path}")

    # ------------------------------------------------------------------ #
    _SPARK = "▁▂▃▄▅▆▇█"

    def history_path(self) -> str:
        return os.path.join(self._snapshot_dir(), "planx_scenario_history.json")

    def _append_history(self, name: str, metrics: dict):
        import json
        ppi = metrics.get("plan_performance_index")
        if ppi is None:
            return
        entries = []
        path = self.history_path()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                entries = json.load(fh)
        except (OSError, ValueError):
            entries = []
        if not isinstance(entries, list):
            entries = []
        entries.append({"name": name, "ppi": round(float(ppi), 2)})
        entries = entries[-24:]
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(entries, fh)
        except OSError:
            return
        self._show_history(entries)

    def _show_history(self, entries):
        vals = [e.get("ppi") for e in entries
                if isinstance(e, dict) and e.get("ppi") is not None][-8:]
        if len(vals) < 2:
            return
        lo, hi = min(vals), max(vals)
        span = (hi - lo) or 1.0
        spark = "".join(
            self._SPARK[min(7, int((v - lo) / span * 7.999))] for v in vals)
        self.history_label.setText(
            f"Index history: {spark}  ({vals[0]:g} → {vals[-1]:g} "
            f"over {len(vals)} snapshots)")
        self.history_label.setVisible(True)

    def open_auditor(self):
        try:
            import processing
            processing.execAlgorithmDialog("planx:planaudit", {})
        except Exception as exc:
            self.iface.messageBar().pushWarning(
                "PlanX", f"Could not open the auditor: {exc}")

    def open_rank(self):
        try:
            import processing
            processing.execAlgorithmDialog("planx:scenariorank", {})
        except Exception as exc:
            self.iface.messageBar().pushWarning(
                "PlanX", f"Could not open Scenario Ranking: {exc}")

    def compare_snapshots(self):
        snaps = []
        for side in ("a", "b"):
            path = self.snapshot_path(side)
            if not os.path.exists(path):
                self.iface.messageBar().pushWarning(
                    "PlanX", f"No scenario {side.upper()} snapshot yet - "
                    f"run the tools for that alternative and press "
                    f"'Save {side.upper()}' first.")
                return
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    snaps.append(scn.from_json(fh.read()))
            except (OSError, ValueError) as exc:
                self.iface.messageBar().pushWarning(
                    "PlanX", f"Could not read scenario {side.upper()}: {exc}")
                return
        snap_a, snap_b = snaps
        rows = scn.compare(snap_a, snap_b)
        self.compare_label.setText(self._compare_html(
            rows, snap_a["name"], snap_b["name"]))
        self.compare_label.setVisible(True)

    @staticmethod
    def _compare_html(rows, name_a: str, name_b: str) -> str:
        from html import escape
        good, bad, grey = (rpt.TONE_COLORS["good"], rpt.TONE_COLORS["bad"],
                           "#90a4ae")
        out = ["<b>Scenario comparison</b><br/>",
               f"<i>{escape(scn.score_line(rows, name_a, name_b))}</i>",
               "<table cellpadding='3' width='100%'>",
               f"<tr><th align='left'>Metric</th>"
               f"<th align='right'>{escape(name_a)}</th>"
               f"<th align='right'>{escape(name_b)}</th>"
               f"<th align='right'>&Delta;</th></tr>"]
        for r in rows:
            delta = r["delta"]
            if delta is None or r["better"] in ("tie", "n/a"):
                color, arrow = grey, ""
            else:
                color = good if r["better"] == "B" else bad
                arrow = "&#9650;" if delta > 0 else "&#9660;"

            def fmt(v):
                return "-" if v is None else f"{v:,.1f}"

            dtxt = "-" if delta is None else f"{arrow} {delta:+,.1f}"
            out.append(
                f"<tr><td>{escape(r['label'])}</td>"
                f"<td align='right'>{fmt(r['a'])}</td>"
                f"<td align='right'>{fmt(r['b'])}</td>"
                f"<td align='right' style='color:{color}'>{dtxt}</td></tr>")
        out.append("</table>")
        return "".join(out)

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
