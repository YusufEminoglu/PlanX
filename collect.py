# -*- coding: utf-8 -*-
"""Reading PlanX output layers back into the engine's plain-data inputs.

Shared by the Plan Dashboard dock and the Scenario Snapshot algorithm:
detects the PlanX output layers by their field signatures
(``engine.report.SIGNATURES``) and converts them into the summary inputs
of ``engine.report``. Imports only ``qgis.core`` - safe headless.
"""
from __future__ import annotations

from qgis.core import QgsVectorLayer

from .engine.report import SIGNATURES


def field_names(layer) -> set:
    return {f.name().lower() for f in layer.fields()}


def matches(layer, role: str) -> bool:
    return set(SIGNATURES[role]) <= field_names(layer)


def auto_detect(project) -> dict:
    """First matching vector layer per role from a QgsProject (or None)."""
    found = {role: None for role in SIGNATURES}
    if project is None:
        return found
    for lyr in project.mapLayers().values():
        if not isinstance(lyr, QgsVectorLayer):
            continue
        for role in SIGNATURES:
            if found[role] is None and matches(lyr, role):
                found[role] = lyr
    return found


def layer_rows(layer, names: dict) -> list:
    """Read fields of a vector layer into plain dict rows (missing -> None)."""
    idx = {key: layer.fields().lookupField(fname) for key, fname in names.items()}
    rows = []
    for f in layer.getFeatures():
        attrs = f.attributes()
        rows.append({key: (attrs[i] if i >= 0 else None) for key, i in idx.items()})
    return rows


def collect(layers: dict):
    """Convert the selected layers into the report summary inputs.

    ``layers`` maps the SIGNATURES roles to a layer or None. Returns
    ``(access, balance, adequacy, density)`` in the exact structures
    ``engine.report.build_html`` expects.
    """
    access = balance = adequacy = density = None
    lyr = layers.get("access")
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
    lyr = layers.get("balance")
    if lyr is not None:
        balance = layer_rows(lyr, {
            "category": "category", "area_m2": "area_m2",
            "m2_per_capita": "m2_capita", "required_m2": "required",
            "balance_m2": "balance_m2", "status": "status"})
        for r in balance:
            for k in ("area_m2", "m2_per_capita", "required_m2", "balance_m2"):
                r[k] = float(r[k] or 0.0)
            r["status"] = str(r["status"] or "")
    lyr = layers.get("facilities")
    if lyr is not None:
        facilities = layer_rows(lyr, {
            "facility": "facility", "capacity": "capacity",
            "assigned": "assigned", "utilization": "utilization",
            "status": "status"})
        demand = []
        dem = layers.get("demand")
        if dem is not None:
            names = {"covered": "covered"}
            pop_fields = [f.name() for f in dem.fields()
                          if f.name().lower().startswith("pop")
                          and f.isNumeric()]
            if pop_fields:
                names["pop"] = pop_fields[0]
            demand = layer_rows(dem, names)
        adequacy = {"facilities": facilities, "demand": demand}
    lyr = layers.get("density")
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
