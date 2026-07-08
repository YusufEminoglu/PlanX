# -*- coding: utf-8 -*-
"""Plan performance scorecards and the self-contained HTML report.

Pure stdlib (not even numpy): aggregates the outputs of the PlanX
analytics into score cards and renders a single-file HTML report with
inline CSS and inline SVG charts (histogram, point map, balance bars).
No qgis imports - unit-testable anywhere.
"""
from __future__ import annotations

import html as _html
from datetime import datetime

# ---------------------------------------------------------------------------
# Colour ramp (bad red -> amber -> good green), used by cards and SVG maps.
# ---------------------------------------------------------------------------
_RAMP = [(214, 69, 65), (245, 176, 65), (39, 174, 96)]

TONE_COLORS = {
    "good": "#27ae60",
    "warn": "#f5b041",
    "bad": "#d64541",
    "info": "#13a0a0",
}


def ramp_color(t: float) -> str:
    """0.0 = bad red, 0.5 = amber, 1.0 = good green."""
    t = 0.0 if t != t else min(1.0, max(0.0, float(t)))
    seg = t * (len(_RAMP) - 1)
    i = min(int(seg), len(_RAMP) - 2)
    f = seg - i
    c0, c1 = _RAMP[i], _RAMP[i + 1]
    rgb = tuple(round(a + (b - a) * f) for a, b in zip(c0, c1))
    return "#%02x%02x%02x" % rgb


def _tone(pct, good: float, warn: float) -> str:
    if pct is None:
        return "info"
    if pct >= good:
        return "good"
    if pct >= warn:
        return "warn"
    return "bad"


def _mean(values):
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def _median(values):
    values = sorted(values)
    n = len(values)
    if n == 0:
        return 0.0
    mid = n // 2
    return values[mid] if n % 2 else (values[mid - 1] + values[mid]) / 2.0


# ---------------------------------------------------------------------------
# Summaries: plain rows in, plain dicts out.
# ---------------------------------------------------------------------------
def access_summary(scores) -> dict:
    """Scores are the 0-100 'score' values of the access-score layer."""
    scores = [float(s) for s in scores]
    n = len(scores)
    full = sum(1 for s in scores if s >= 100.0 - 1e-9)
    low = sum(1 for s in scores if s < 50.0)
    return {
        "n": n,
        "mean": _mean(scores),
        "median": _median(scores),
        "share_full": 100.0 * full / n if n else 0.0,
        "share_low": 100.0 * low / n if n else 0.0,
    }


def balance_summary(rows) -> dict:
    """Rows from the Land-Use Balance table.

    Each row needs ``status`` and ``balance_m2`` (and ``category`` for the
    worst-deficit label).
    """
    rows = list(rows)
    with_std = [r for r in rows if r.get("status") != "No standard"]
    deficits = [r for r in with_std if r.get("status") == "Deficit"]
    worst = min(deficits, key=lambda r: float(r.get("balance_m2", 0.0)), default=None)
    n_std = len(with_std)
    met = n_std - len(deficits)
    return {
        "n_categories": len(rows),
        "n_with_standard": n_std,
        "n_deficit": len(deficits),
        "compliance_pct": 100.0 * met / n_std if n_std else None,
        "worst_category": str(worst["category"]) if worst else "",
        "worst_deficit_m2": float(worst["balance_m2"]) if worst else 0.0,
    }


def adequacy_summary(facility_rows, demand_rows) -> dict:
    """Facility rows need ``status`` (+ ``utilization``); demand rows need
    ``covered`` (0/1) and optionally ``pop`` (defaults to 1 per row)."""
    facility_rows = list(facility_rows)
    demand_rows = list(demand_rows)
    by_status = {"Adequate": 0, "Overloaded": 0, "Unused": 0}
    for r in facility_rows:
        s = str(r.get("status", ""))
        by_status[s] = by_status.get(s, 0) + 1
    used = [float(r.get("utilization", 0.0)) for r in facility_rows
            if str(r.get("status", "")) != "Unused"]
    total_pop = covered_pop = 0.0
    for r in demand_rows:
        try:
            pop = float(r.get("pop", 1.0))
        except (TypeError, ValueError):
            pop = 0.0
        pop = max(0.0, pop)
        total_pop += pop
        if int(r.get("covered", 0) or 0):
            covered_pop += pop
    return {
        "n_facilities": len(facility_rows),
        "n_overloaded": by_status.get("Overloaded", 0),
        "n_unused": by_status.get("Unused", 0),
        "mean_utilization": _mean(used),
        "covered_pop": covered_pop,
        "total_pop": total_pop,
        "covered_share": 100.0 * covered_pop / total_pop if total_pop > 0 else None,
    }


def density_summary(values) -> dict:
    values = [float(v) for v in values]
    return {
        "n_cells": len(values),
        "mean": _mean(values),
        "max": max(values) if values else 0.0,
    }


def overall_score(access=None, balance=None, adequacy=None):
    """Unweighted mean of the available 0-100 components."""
    parts = []
    if access and access.get("n"):
        parts.append(access["mean"])
    if balance and balance.get("compliance_pct") is not None:
        parts.append(balance["compliance_pct"])
    if adequacy and adequacy.get("covered_share") is not None:
        parts.append(adequacy["covered_share"])
    return _mean(parts) if parts else None


# ---------------------------------------------------------------------------
# Score cards
# ---------------------------------------------------------------------------
def report_cards(access=None, balance=None, adequacy=None, density=None) -> list:
    """Build the score-card list from the summary dicts (None = skip)."""
    cards = []
    overall = overall_score(access, balance, adequacy)
    if overall is not None:
        cards.append({
            "label": "Plan Performance Index",
            "value": f"{overall:.0f}",
            "sub": "mean of available components (0-100)",
            "tone": _tone(overall, 75.0, 50.0),
        })
    if access and access.get("n"):
        cards.append({
            "label": "Accessibility Score",
            "value": f"{access['mean']:.0f}",
            "sub": (f"{access['n']} origins - {access['share_full']:.0f}% "
                    "reach every category"),
            "tone": _tone(access["mean"], 75.0, 50.0),
        })
    if balance:
        pct = balance.get("compliance_pct")
        sub = f"{balance['n_with_standard']} categories with a standard"
        if balance.get("n_deficit"):
            sub = (f"{balance['n_deficit']} deficit(s) - worst: "
                   f"{balance['worst_category']}")
        cards.append({
            "label": "Standards Compliance",
            "value": "n/a" if pct is None else f"{pct:.0f}%",
            "sub": sub,
            "tone": _tone(pct, 99.9, 66.0),
        })
    if adequacy:
        share = adequacy.get("covered_share")
        cards.append({
            "label": "Population Covered",
            "value": "n/a" if share is None else f"{share:.0f}%",
            "sub": (f"{adequacy['n_facilities']} facilities - "
                    f"{adequacy['n_overloaded']} overloaded"),
            "tone": _tone(share, 90.0, 70.0),
        })
    if density and density.get("n_cells"):
        cards.append({
            "label": "Density (mean)",
            "value": f"{density['mean']:.1f}/ha",
            "sub": f"max {density['max']:.1f}/ha over {density['n_cells']} cells",
            "tone": "info",
        })
    return cards


# ---------------------------------------------------------------------------
# SVG helpers
# ---------------------------------------------------------------------------
def svg_histogram(values, vmin=0.0, vmax=100.0, bins=10, width=460, height=150):
    """Bar histogram; bars coloured by the ramp position of their bin."""
    values = [float(v) for v in values]
    counts = [0] * bins
    span = (vmax - vmin) or 1.0
    for v in values:
        i = int((v - vmin) / span * bins)
        counts[min(max(i, 0), bins - 1)] += 1
    peak = max(counts) or 1
    pad, base = 4, height - 18
    bw = (width - 2 * pad) / bins
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
             f'height="{height}" role="img">']
    for i, c in enumerate(counts):
        h = (base - pad) * c / peak
        x = pad + i * bw
        color = ramp_color((i + 0.5) / bins)
        parts.append(f'<rect x="{x:.1f}" y="{base - h:.1f}" width="{bw - 2:.1f}" '
                     f'height="{h:.1f}" fill="{color}" rx="2"/>')
        if c:
            parts.append(f'<text x="{x + bw / 2:.1f}" y="{base - h - 3:.1f}" '
                         f'font-size="9" text-anchor="middle" fill="#555">{c}</text>')
    parts.append(f'<text x="{pad}" y="{height - 5}" font-size="9" '
                 f'fill="#777">{vmin:g}</text>')
    parts.append(f'<text x="{width - pad}" y="{height - 5}" font-size="9" '
                 f'text-anchor="end" fill="#777">{vmax:g}</text>')
    parts.append("</svg>")
    return "".join(parts)


def svg_point_map(points, values, vmin=0.0, vmax=100.0, width=460, height=340,
                  max_points=4000):
    """Scatter map of (x, y) points coloured by value on the ramp.

    Keeps the data aspect ratio; deterministically thins to ``max_points``.
    """
    pts = [(float(x), float(y), float(v)) for (x, y), v in zip(points, values)]
    if not pts:
        return ""
    if len(pts) > max_points:
        step = len(pts) / float(max_points)
        pts = [pts[int(i * step)] for i in range(max_points)]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    dx = (max(xs) - min(xs)) or 1.0
    dy = (max(ys) - min(ys)) or 1.0
    pad = 12
    scale = min((width - 2 * pad) / dx, (height - 2 * pad) / dy)
    x0, y1 = min(xs), max(ys)
    span = (vmax - vmin) or 1.0
    r = max(2.0, min(6.0, 90.0 / (len(pts) ** 0.5)))
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
             f'height="{height}" role="img">',
             f'<rect width="{width}" height="{height}" fill="#f6f8f8" rx="6"/>']
    for x, y, v in pts:
        cx = pad + (x - x0) * scale
        cy = pad + (y1 - y) * scale
        parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" '
                     f'fill="{ramp_color((v - vmin) / span)}" fill-opacity="0.85"/>')
    parts.append("</svg>")
    return "".join(parts)


def svg_balance_bars(rows, width=560, bar_h=16):
    """Provided vs required horizontal bars per category with a standard."""
    rows = [r for r in rows if r.get("status") != "No standard"]
    if not rows:
        return ""
    peak = max(max(float(r["area_m2"]), float(r["required_m2"])) for r in rows) or 1.0
    label_w, gap, pad = 170, 6, 4
    row_h = 2 * bar_h + gap + 8
    height = pad * 2 + row_h * len(rows)
    chart_w = width - label_w - 60
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
             f'height="{height}" role="img">']
    for i, r in enumerate(rows):
        y = pad + i * row_h
        cat = _html.escape(str(r["category"]))
        provided = float(r["area_m2"])
        required = float(r["required_m2"])
        color = TONE_COLORS["bad" if r.get("status") == "Deficit" else "good"]
        parts.append(f'<text x="0" y="{y + bar_h + 2}" font-size="11" '
                     f'fill="#333">{cat}</text>')
        for j, (val, fill) in enumerate(((provided, color), (required, "#b0bec5"))):
            by = y + j * (bar_h + 2)
            bwid = chart_w * val / peak
            parts.append(f'<rect x="{label_w}" y="{by}" width="{bwid:.1f}" '
                         f'height="{bar_h - 4}" fill="{fill}" rx="2"/>')
            parts.append(f'<text x="{label_w + bwid + 4:.1f}" y="{by + bar_h - 7}" '
                         f'font-size="9" fill="#666">{val:,.0f} m2'
                         f'{"" if j == 0 else " req."}</text>')
    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------
_CSS = """
body { font-family: 'Segoe UI', Arial, sans-serif; color: #2c3e50;
       margin: 0; background: #eef2f3; }
.wrap { max-width: 1060px; margin: 0 auto; padding: 24px; }
header { background: linear-gradient(90deg, #0f6b6b, #13a0a0); color: #fff;
         border-radius: 10px; padding: 22px 26px; margin-bottom: 18px; }
header h1 { margin: 0 0 4px 0; font-size: 24px; }
header .meta { opacity: 0.85; font-size: 13px; }
.cards { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 18px; }
.card { background: #fff; border-radius: 10px; padding: 14px 18px;
        min-width: 170px; flex: 1; border-top: 4px solid #13a0a0;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.card .label { font-size: 12px; text-transform: uppercase;
               letter-spacing: 0.4px; color: #7f8c8d; }
.card .value { font-size: 30px; font-weight: 700; margin: 2px 0; }
.card .sub { font-size: 11px; color: #95a5a6; }
section { background: #fff; border-radius: 10px; padding: 18px 22px;
          margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
section h2 { margin: 0 0 10px 0; font-size: 17px; color: #0f6b6b; }
table { border-collapse: collapse; width: 100%; font-size: 12px; }
th { text-align: left; padding: 6px 8px; background: #f0f4f4;
     color: #546e7a; }
td { padding: 5px 8px; border-bottom: 1px solid #eceff1; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.badge { display: inline-block; padding: 1px 8px; border-radius: 9px;
         color: #fff; font-size: 11px; }
.flex { display: flex; flex-wrap: wrap; gap: 18px; align-items: flex-start; }
footer { text-align: center; font-size: 11px; color: #90a4ae;
         padding: 8px 0 20px 0; }
"""


def _badge(status: str) -> str:
    tone = {"Meets standard": "good", "Adequate": "good",
            "Deficit": "bad", "Overloaded": "bad", "Unused": "warn",
            "No standard": "info"}.get(status, "info")
    return (f'<span class="badge" style="background:{TONE_COLORS[tone]}">'
            f"{_html.escape(status)}</span>")


def _cards_html(cards) -> str:
    out = ['<div class="cards">']
    for c in cards:
        color = TONE_COLORS.get(c.get("tone", "info"), TONE_COLORS["info"])
        out.append(
            f'<div class="card" style="border-top-color:{color}">'
            f'<div class="label">{_html.escape(c["label"])}</div>'
            f'<div class="value" style="color:{color}">{_html.escape(c["value"])}</div>'
            f'<div class="sub">{_html.escape(c["sub"])}</div></div>')
    out.append("</div>")
    return "".join(out)


def _access_section(access_data, summary) -> str:
    scores = access_data.get("scores", [])
    points = access_data.get("points") or []
    parts = ["<section><h2>Accessibility - 15-Minute City</h2>"]
    parts.append(
        f"<p>{summary['n']} origins scored. Mean score "
        f"<b>{summary['mean']:.1f}</b>, median {summary['median']:.1f}; "
        f"{summary['share_full']:.1f}% reach every amenity category and "
        f"{summary['share_low']:.1f}% score below 50.</p>")
    parts.append('<div class="flex">')
    parts.append("<div><h3 style='font-size:13px;margin:4px 0'>Score "
                 "distribution</h3>" + svg_histogram(scores) + "</div>")
    if points:
        parts.append("<div><h3 style='font-size:13px;margin:4px 0'>Score map "
                     "(red = low, green = high)</h3>"
                     + svg_point_map(points, scores) + "</div>")
    parts.append("</div></section>")
    return "".join(parts)


def _balance_section(rows, summary) -> str:
    parts = ["<section><h2>Land-Use Balance vs Standards</h2>"]
    if summary["compliance_pct"] is None:
        parts.append("<p>No category matched a per-capita standard.</p>")
    else:
        parts.append(
            f"<p>{summary['n_with_standard']} of {summary['n_categories']} "
            f"categories have a standard; <b>{summary['n_deficit']}</b> in "
            f"deficit (compliance {summary['compliance_pct']:.0f}%).</p>")
    bars = svg_balance_bars(rows)
    if bars:
        parts.append("<h3 style='font-size:13px;margin:8px 0 4px'>Provided "
                     "(coloured) vs required (grey)</h3>" + bars)
    parts.append("<table><tr><th>Category</th><th>Area m2</th>"
                 "<th>m2/capita</th><th>Required m2</th><th>Balance m2</th>"
                 "<th>Status</th></tr>")
    for r in rows:
        parts.append(
            "<tr><td>" + _html.escape(str(r["category"])) + "</td>"
            f'<td class="num">{float(r["area_m2"]):,.0f}</td>'
            f'<td class="num">{float(r["m2_per_capita"]):.2f}</td>'
            f'<td class="num">{float(r["required_m2"]):,.0f}</td>'
            f'<td class="num">{float(r["balance_m2"]):,.0f}</td>'
            f'<td>{_badge(str(r["status"]))}</td></tr>')
    parts.append("</table></section>")
    return "".join(parts)


def _adequacy_section(facility_rows, summary) -> str:
    parts = ["<section><h2>Facility Adequacy</h2>"]
    share = summary["covered_share"]
    share_txt = "n/a" if share is None else f"{share:.1f}%"
    parts.append(
        f"<p>Covered population share: <b>{share_txt}</b> "
        f"({summary['covered_pop']:g} of {summary['total_pop']:g}). "
        f"{summary['n_facilities']} facilities - "
        f"{summary['n_overloaded']} overloaded, "
        f"{summary['n_unused']} unused; mean utilization of used "
        f"facilities {summary['mean_utilization']:.2f}.</p>")
    parts.append("<table><tr><th>Facility</th><th>Capacity</th>"
                 "<th>Assigned</th><th>Utilization</th><th>Status</th></tr>")
    for r in sorted(facility_rows, key=lambda x: -float(x.get("utilization", 0.0))):
        parts.append(
            "<tr><td>" + _html.escape(str(r.get("facility", ""))) + "</td>"
            f'<td class="num">{float(r.get("capacity", 0.0)):,.0f}</td>'
            f'<td class="num">{float(r.get("assigned", 0.0)):,.0f}</td>'
            f'<td class="num">{float(r.get("utilization", 0.0)):.2f}</td>'
            f'<td>{_badge(str(r.get("status", "")))}</td></tr>')
    parts.append("</table></section>")
    return "".join(parts)


def _density_section(summary) -> str:
    return ("<section><h2>Density</h2><p>"
            f"{summary['n_cells']} occupied grid cells; mean density "
            f"<b>{summary['mean']:.1f}</b> per hectare, maximum "
            f"{summary['max']:.1f} per hectare.</p></section>")


def _fmt_metric(value) -> str:
    if value is None:
        return "-"
    v = float(value)
    if v == int(v) and abs(v) < 1e9:
        return f"{int(v):,}"
    return f"{v:,.2f}"


def compare_section(rows, name_a="A", name_b="B") -> str:
    """Render the scenario A/B comparison rows as an HTML section.

    ``rows`` come from ``scenario.compare``: dicts with label / a / b /
    delta / delta_pct / direction / better. Deltas are coloured green when
    the change favours B, red when it favours A, grey when neutral.
    """
    ea, eb = _html.escape(str(name_a)), _html.escape(str(name_b))
    parts = ["<section><h2>Scenario Comparison</h2>",
             f"<table><tr><th>Metric</th><th>{ea}</th><th>{eb}</th>"
             f"<th>Delta ({eb} - {ea})</th><th>Better</th></tr>"]
    for r in rows:
        delta = r.get("delta")
        better = r.get("better", "n/a")
        if delta is None or better in ("tie", "n/a"):
            color, arrow = "#90a4ae", ""
        elif better == "B":
            color, arrow = TONE_COLORS["good"], ("&#9650; " if delta > 0 else "&#9660; ")
        else:
            color, arrow = TONE_COLORS["bad"], ("&#9650; " if delta > 0 else "&#9660; ")
        dtxt = "-" if delta is None else f"{arrow}{delta:+,.2f}"
        if r.get("delta_pct") is not None:
            dtxt += f" ({r['delta_pct']:+.1f}%)"
        who = {"A": ea, "B": eb, "tie": "tie"}.get(better, "-")
        parts.append(
            "<tr><td>" + _html.escape(str(r.get("label", r.get("key", "")))) + "</td>"
            f'<td class="num">{_fmt_metric(r.get("a"))}</td>'
            f'<td class="num">{_fmt_metric(r.get("b"))}</td>'
            f'<td class="num" style="color:{color}">{dtxt}</td>'
            f"<td>{who}</td></tr>")
    parts.append("</table></section>")
    return "".join(parts)


def build_compare_html(title, rows, name_a="A", name_b="B", verdict="",
                       generated=None, plugin_version="") -> str:
    """One-file HTML page for a scenario A/B comparison."""
    when = generated or datetime.now().strftime("%Y-%m-%d %H:%M")
    body = ["<header><h1>", _html.escape(title), "</h1>",
            '<div class="meta">Scenario Comparison - ',
            _html.escape(f"{name_a} vs {name_b} - {when}"), "</div></header>"]
    if verdict:
        body.append("<section><p>" + _html.escape(verdict) + "</p></section>")
    body.append(compare_section(rows, name_a, name_b))
    version = f" {plugin_version}" if plugin_version else ""
    body.append(f"<footer>Generated by PlanX{version} - Urban Analytics "
                "Studio (embedded engine, computed inside QGIS)</footer>")
    return ("<!DOCTYPE html><html><head><meta charset='utf-8'>"
            f"<title>{_html.escape(title)}</title><style>{_CSS}</style></head>"
            "<body><div class='wrap'>" + "".join(body) + "</div></body></html>")


def build_html(title, population=None, access=None, balance=None,
               adequacy=None, density=None, generated=None,
               plugin_version="") -> str:
    """Render the one-file Plan Performance Report.

    ``access``  : {"scores": [...], "points": [(x, y), ...] (optional)}
    ``balance`` : list of land-use balance rows (dicts)
    ``adequacy``: {"facilities": [rows], "demand": [rows]}
    ``density`` : {"values": [...]}
    """
    a_sum = access_summary(access["scores"]) if access else None
    b_sum = balance_summary(balance) if balance is not None else None
    q_sum = (adequacy_summary(adequacy.get("facilities", []),
                              adequacy.get("demand", []))
             if adequacy else None)
    d_sum = density_summary(density["values"]) if density else None
    cards = report_cards(a_sum, b_sum, q_sum, d_sum)

    when = generated or datetime.now().strftime("%Y-%m-%d %H:%M")
    meta = [when]
    if population:
        meta.append(f"planned population {population:,.0f}")
    body = ['<header><h1>', _html.escape(title), "</h1>",
            '<div class="meta">Plan Performance Report - ',
            _html.escape(" - ".join(meta)), "</div></header>",
            _cards_html(cards)]
    if access and a_sum and a_sum["n"]:
        body.append(_access_section(access, a_sum))
    if balance is not None and b_sum:
        body.append(_balance_section(list(balance), b_sum))
    if adequacy and q_sum:
        body.append(_adequacy_section(adequacy.get("facilities", []), q_sum))
    if density and d_sum and d_sum["n_cells"]:
        body.append(_density_section(d_sum))
    version = f" {plugin_version}" if plugin_version else ""
    body.append(f"<footer>Generated by PlanX{version} - Urban Analytics "
                "Studio (embedded engine, computed inside QGIS)</footer>")
    return ("<!DOCTYPE html><html><head><meta charset='utf-8'>"
            f"<title>{_html.escape(title)}</title><style>{_CSS}</style></head>"
            "<body><div class='wrap'>" + "".join(body) + "</div></body></html>")
