# -*- coding: utf-8 -*-
"""Scenario snapshots and A/B comparison of plan score metrics.

Pure stdlib. A *snapshot* captures the Plan Dashboard's score metrics for
one plan alternative as plain floats (name + timestamp + metric dict);
``compare`` diffs two snapshots metric by metric using a direction
registry that knows which way is better for each metric. No qgis imports
- unit-testable anywhere.
"""
from __future__ import annotations

import json
from datetime import datetime

#: metric key -> (human label, direction) with direction +1 = higher is
#: better, -1 = lower is better, 0 = neutral / context-dependent.
METRICS = {
    "plan_performance_index": ("Plan Performance Index", 1),
    "access_mean": ("Accessibility score (mean)", 1),
    "access_median": ("Accessibility score (median)", 1),
    "access_share_full": ("Share reaching every category (%)", 1),
    "access_share_low": ("Share scoring below 50 (%)", -1),
    "origins": ("Scored origins", 0),
    "standards_compliance_pct": ("Standards compliance (%)", 1),
    "standards_deficits": ("Categories in deficit", -1),
    "standards_categories": ("Categories with a standard", 0),
    "covered_share": ("Population covered (%)", 1),
    "covered_pop": ("Covered population", 1),
    "total_pop": ("Total population", 0),
    "facilities": ("Facilities", 0),
    "facilities_overloaded": ("Overloaded facilities", -1),
    "facilities_unused": ("Unused facilities", -1),
    "mean_utilization": ("Mean facility utilization", 0),
    "walk_score_mean": ("Walkability score (mean)", 1),
    "walk_low_share": ("Streets below 50 walk score (pct)", -1),
    "green_coverage_worst": ("Green coverage, weakest class (pct)", 1),
    "access_gini": ("Access inequality (Gini)", -1),
    "density_mean": ("Density mean (/ha)", 0),
    "density_max": ("Density max (/ha)", 0),
    "density_cells": ("Occupied density cells", 0),
}

_ORDER = list(METRICS.keys())


def metrics_from_summaries(access=None, balance=None, adequacy=None,
                           density=None, overall=None) -> dict:
    """Flatten the report summary dicts into one {metric_key: float} dict.

    Accepts the dicts produced by ``report.access_summary`` /
    ``balance_summary`` / ``adequacy_summary`` / ``density_summary`` (any
    may be None) plus the precomputed ``overall`` score. Metrics whose
    inputs are missing are simply absent from the result.
    """
    out = {}
    if overall is not None:
        out["plan_performance_index"] = float(overall)
    if access and access.get("n"):
        out["access_mean"] = float(access["mean"])
        out["access_median"] = float(access["median"])
        out["access_share_full"] = float(access["share_full"])
        out["access_share_low"] = float(access["share_low"])
        out["origins"] = float(access["n"])
    if balance:
        if balance.get("compliance_pct") is not None:
            out["standards_compliance_pct"] = float(balance["compliance_pct"])
        out["standards_deficits"] = float(balance.get("n_deficit", 0))
        out["standards_categories"] = float(balance.get("n_with_standard", 0))
    if adequacy:
        if adequacy.get("covered_share") is not None:
            out["covered_share"] = float(adequacy["covered_share"])
        out["covered_pop"] = float(adequacy.get("covered_pop", 0.0))
        out["total_pop"] = float(adequacy.get("total_pop", 0.0))
        out["facilities"] = float(adequacy.get("n_facilities", 0))
        out["facilities_overloaded"] = float(adequacy.get("n_overloaded", 0))
        out["facilities_unused"] = float(adequacy.get("n_unused", 0))
        out["mean_utilization"] = float(adequacy.get("mean_utilization", 0.0))
    if density and density.get("n_cells"):
        out["density_mean"] = float(density["mean"])
        out["density_max"] = float(density["max"])
        out["density_cells"] = float(density["n_cells"])
    return out


def snapshot(name, metrics, generated=None) -> dict:
    """Build a scenario snapshot dict from a metric mapping."""
    clean = {}
    for key, val in dict(metrics).items():
        try:
            f = float(val)
        except (TypeError, ValueError):
            continue
        if f == f:  # drop NaN
            clean[str(key)] = f
    return {
        "kind": "planx-scenario-snapshot",
        "version": 1,
        "name": str(name) or "Scenario",
        "generated": generated or datetime.now().strftime("%Y-%m-%d %H:%M"),
        "metrics": clean,
    }


def to_json(snap) -> str:
    return json.dumps(snap, indent=2, sort_keys=True)


def from_json(text):
    """Parse and validate a snapshot; raises ValueError on bad input."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("metrics"), dict):
        raise ValueError("not a PlanX scenario snapshot (no 'metrics' object)")
    metrics = {}
    for key, val in data["metrics"].items():
        try:
            metrics[str(key)] = float(val)
        except (TypeError, ValueError):
            continue
    return {
        "kind": "planx-scenario-snapshot",
        "version": int(data.get("version", 1)),
        "name": str(data.get("name", "Scenario")),
        "generated": str(data.get("generated", "")),
        "metrics": metrics,
    }


def label_of(key: str) -> str:
    return METRICS.get(key, (key.replace("_", " ").title(), 0))[0]


def direction_of(key: str) -> int:
    return METRICS.get(key, ("", 0))[1]


def compare(snap_a, snap_b) -> list:
    """Diff two snapshots metric by metric.

    Returns a list of row dicts ordered by the metric registry (unknown
    metrics last, alphabetically): ``key``, ``label``, ``a``, ``b`` (float
    or None when a side lacks the metric), ``delta`` / ``delta_pct``
    (B minus A; None when either side is missing, pct also None when A is
    0), ``direction`` (+1/-1/0) and ``better`` - which scenario wins this
    metric: "A", "B", "tie" (equal), or "n/a" (neutral direction or a
    missing side).
    """
    ma = dict(snap_a.get("metrics", {}))
    mb = dict(snap_b.get("metrics", {}))
    keys = set(ma) | set(mb)
    known = [k for k in _ORDER if k in keys]
    extra = sorted(k for k in keys if k not in METRICS)
    rows = []
    for key in known + extra:
        a = ma.get(key)
        b = mb.get(key)
        direction = direction_of(key)
        delta = delta_pct = None
        better = "n/a"
        if a is not None and b is not None:
            delta = b - a
            if a != 0:
                delta_pct = 100.0 * delta / abs(a)
            if direction == 0:
                better = "n/a"
            elif delta == 0:
                better = "tie"
            elif direction > 0:
                better = "B" if delta > 0 else "A"
            else:
                better = "B" if delta < 0 else "A"
        rows.append({
            "key": key,
            "label": label_of(key),
            "a": a,
            "b": b,
            "delta": delta,
            "delta_pct": delta_pct,
            "direction": direction,
            "better": better,
        })
    return rows


def score_line(rows, name_a="A", name_b="B") -> str:
    """One-sentence verdict: how many decided metrics each scenario wins."""
    wins_a = sum(1 for r in rows if r["better"] == "A")
    wins_b = sum(1 for r in rows if r["better"] == "B")
    ties = sum(1 for r in rows if r["better"] == "tie")
    if wins_a == wins_b:
        head = "Even result"
    else:
        head = f"'{name_b if wins_b > wins_a else name_a}' leads"
    return (f"{head}: {name_b} wins {wins_b}, {name_a} wins {wins_a}, "
            f"{ties} tied, over {len(rows)} compared metrics.")


def parse_weights(text):
    """Parse 'key=weight, key=weight' free text into a dict.

    Returns (weights: dict[str, float], unknown: list[str]) where ``unknown``
    lists keys not present in METRICS (they still apply if the snapshots
    carry them - the caller decides how to report them). Accepts ';' as a
    separator like the other PlanX free-text parsers. Empty/whitespace text
    -> ({}, []). A malformed token or a weight <= 0 raises ValueError with
    the offending token in the message.
    """
    if text is None or not str(text).strip():
        return {}, []

    weights = {}
    unknown = []

    # split by either ; or ,
    for token in str(text).replace(";", ",").split(","):
        token = token.strip()
        if not token:
            continue
        key, sep, value = token.partition("=")
        key = key.strip()
        if sep != "=":
            raise ValueError(f"weights need 'key=weight' entries: '{token}'")
        if not key:
            raise ValueError(f"empty key in token: '{token}'")
        try:
            val = float(value.strip())
        except ValueError as exc:
            raise ValueError(f"weight for key '{key}' needs a numeric value: '{token}'") from exc

        if val <= 0:
            raise ValueError(f"weight must be positive: '{token}'")

        weights[key] = val
        if key not in METRICS:
            if key not in unknown:
                unknown.append(key)

    return weights, unknown


def rank(snapshots, weights=None):
    """Rank any number of scenario snapshots by a weighted composite score.

    ``snapshots``: list of snapshot dicts (from ``snapshot``/``from_json``).
    ``weights``: optional {metric_key: float > 0}; default weight is 1.0.

    Raises ValueError when fewer than 2 snapshots are given or when two
    snapshots share the same name (names key the result tables).

    SCORED metrics are those that are (a) present in EVERY snapshot,
    (b) have a non-zero direction in METRICS (unknown keys have direction 0
    via direction_of and are therefore never scored), and (c) are not
    constant across the snapshots. Everything else is skipped
    with a reason: 'neutral' (direction 0 / unknown), 'not-shared' (missing
    in at least one snapshot), 'constant' (shared but max == min). Reason
    precedence: neutral > not-shared > constant.

    Per scored metric k with values v_s over scenarios s:
        norm_s = (v_s - min) / (max - min)          if direction(k) == +1
        norm_s = (max - v_s) / (max - min)          if direction(k) == -1
    so 1.0 is always BEST. Composite per scenario:
        score_s = 100 * sum_k(w_k * norm_k_s) / sum_k(w_k)
    Ranks use competition ranking on descending score (equal scores share a
    rank; the next rank is skipped: 1, 2, 2, 4). ``wins_s`` counts the scored
    metrics where scenario s holds the strictly best norm (exact ties on a
    metric award no win).

    Returns {
      "scenarios": [ {"name", "score", "rank", "wins", "n_metrics"} ... ]
                   sorted by (rank, name),
      "metrics":   [ {"key", "label", "direction", "weight",
                      "values": {name: v}, "norms": {name: n}} ... ]
                   ordered by the METRICS registry order (unknown keys never
                   appear here - they are always skipped),
      "skipped":   [ {"key", "reason"} ... ] ordered registry-first then
                   alphabetically, deterministic,
    }
    "n_metrics" is len(result["metrics"]) (same for every scenario, kept per
    row for table readability). All floats stay full precision - no rounding
    in the engine.
    """
    if len(snapshots) < 2:
        raise ValueError("At least 2 snapshots are required to rank.")

    names = [s.get("name") for s in snapshots]
    if len(names) != len(set(names)):
        raise ValueError("Snapshot names must be unique.")

    if weights is None:
        weights = {}

    # Gather all unique keys present across all snapshots
    all_keys = set()
    for snap in snapshots:
        all_keys.update(snap.get("metrics", {}).keys())

    known = [k for k in _ORDER if k in all_keys]
    extra = sorted(k for k in all_keys if k not in METRICS)
    all_keys_ordered = known + extra

    scored_keys = []
    skipped_list = []

    for key in all_keys_ordered:
        direction = direction_of(key)
        if direction == 0:
            skipped_list.append({"key": key, "reason": "neutral"})
            continue

        missing = False
        values_list = []
        for snap in snapshots:
            metrics_dict = snap.get("metrics", {})
            if key not in metrics_dict:
                missing = True
                break
            values_list.append(metrics_dict[key])

        if missing:
            skipped_list.append({"key": key, "reason": "not-shared"})
            continue

        min_v = min(values_list)
        max_v = max(values_list)
        if min_v == max_v:
            skipped_list.append({"key": key, "reason": "constant"})
            continue

        scored_keys.append(key)

    # Compute scores and metrics details
    scores = {snap["name"]: 0.0 for snap in snapshots}
    wins = {snap["name"]: 0 for snap in snapshots}
    metric_results = []

    for k in scored_keys:
        direction = direction_of(k)
        weight = weights.get(k, 1.0)

        values_k = {snap["name"]: snap.get("metrics", {})[k] for snap in snapshots}
        min_k = min(values_k.values())
        max_k = max(values_k.values())

        norms_k = {}
        for name, v in values_k.items():
            if direction == 1:
                norm = (v - min_k) / (max_k - min_k)
            else:
                norm = (max_k - v) / (max_k - min_k)
            norms_k[name] = norm

        best_scenarios = [name for name, norm in norms_k.items() if norm == 1.0]
        if len(best_scenarios) == 1:
            wins[best_scenarios[0]] += 1

        metric_results.append({
            "key": k,
            "label": label_of(k),
            "direction": direction,
            "weight": weight,
            "values": values_k,
            "norms": norms_k,
        })

    n_metrics = len(metric_results)
    total_weight = sum(weights.get(k, 1.0) for k in scored_keys)

    for snap in snapshots:
        name = snap["name"]
        if total_weight > 0:
            weighted_norm_sum = sum(
                weights.get(k, 1.0) * norms_k[name]
                for k, norms_k in ((mr["key"], mr["norms"]) for mr in metric_results)
            )
            score = 100.0 * weighted_norm_sum / total_weight
        else:
            score = 0.0
        scores[name] = score

    # Competition ranking
    sorted_snaps = sorted(snapshots, key=lambda s: scores[s["name"]], reverse=True)
    ranks = {}
    current_rank = 1
    for i, s in enumerate(sorted_snaps):
        name = s["name"]
        if i > 0:
            prev_name = sorted_snaps[i - 1]["name"]
            if scores[name] != scores[prev_name]:
                current_rank = i + 1
        ranks[name] = current_rank

    scenarios_list = []
    for snap in snapshots:
        name = snap["name"]
        scenarios_list.append({
            "name": name,
            "score": scores[name],
            "rank": ranks[name],
            "wins": wins[name],
            "n_metrics": n_metrics,
        })
    scenarios_list.sort(key=lambda s: (s["rank"], s["name"]))

    return {
        "scenarios": scenarios_list,
        "metrics": metric_results,
        "skipped": skipped_list,
    }
