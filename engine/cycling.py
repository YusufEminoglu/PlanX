# -*- coding: utf-8 -*-
"""Cycling network stress and low-stress connectivity kernels.

Pure NumPy. The LTS classifier is deliberately compact and documented:
it follows the common Mekuria/Furth traffic-stress idea but exposes every
threshold as a plain ``key=value`` table so an agency can re-tune it.
"""
from __future__ import annotations

import numpy as np


DEFAULT_LTS_RULES = {
    "path_lts": 1.0,
    "lane_lts2_speed": 50.0,
    "lane_lts2_lanes": 3.0,
    "lane_lts_low": 2.0,
    "lane_lts_high": 3.0,
    "mixed_lts1_speed": 30.0,
    "mixed_lts1_lanes": 2.0,
    "mixed_lts1_aadt": 1000.0,
    "mixed_lts2_speed": 30.0,
    "mixed_lts2_lanes": 2.0,
    "mixed_lts3_speed": 50.0,
}

DEFAULT_LTS_RULES_TEXT = (
    "path_lts=1, lane_lts2_speed=50, lane_lts2_lanes=3, "
    "lane_lts_low=2, lane_lts_high=3, mixed_lts1_speed=30, "
    "mixed_lts1_lanes=2, mixed_lts1_aadt=1000, "
    "mixed_lts2_speed=30, mixed_lts2_lanes=2, mixed_lts3_speed=50"
)


def parse_lts_rules(text):
    """Parse a free-text ``key=value`` threshold table.

    Unknown keys raise ``ValueError`` so typos do not silently change the
    classification. Empty text returns the defaults.
    """
    rules = dict(DEFAULT_LTS_RULES)
    if text is None or not str(text).strip():
        return rules
    for token in str(text).replace(";", ",").split(","):
        token = token.strip()
        if not token:
            continue
        key, sep, value = token.partition("=")
        key = key.strip().lower()
        if sep != "=" or key not in rules:
            raise ValueError(f"LTS rules need known 'key=value' entries: '{token}'")
        try:
            rules[key] = float(value.strip())
        except ValueError:
            raise ValueError(f"LTS rule '{key}' needs a numeric value")
    return rules


def _text_array(values):
    if isinstance(values, str):
        return np.asarray([values], dtype=object)
    arr = np.asarray(values, dtype=object)
    return arr.reshape(-1)


def _numeric_array(values, n, default):
    if values is None:
        return np.full(n, float(default), dtype=float)
    arr = np.asarray(values, dtype=float)
    if arr.ndim == 0:
        return np.full(n, float(arr), dtype=float)
    arr = arr.reshape(-1)
    if len(arr) != n:
        raise ValueError("all LTS inputs must share one length")
    return arr


def lts_classify(speed, lanes, aadt, infra, rules=None):
    """Classify Level of Traffic Stress (1 low stress, 4 high stress).

    Rules:
    - separated ``path`` infrastructure -> LTS 1;
    - painted ``lane`` -> LTS 2 when speed <= 50 and lanes <= 3, else LTS 3;
    - mixed traffic -> LTS 1 when speed <= 30, lanes <= 2 and AADT < 1000;
      LTS 2 when speed <= 30 and lanes <= 2; LTS 3 when speed <= 50; else
      LTS 4.

    ``rules`` may be a parsed dict from :func:`parse_lts_rules`; omitted
    rules use the defaults above.
    """
    r = dict(DEFAULT_LTS_RULES)
    if rules:
        r.update(rules)
    infra_arr = np.char.lower(np.char.strip(_text_array(infra).astype(str)))
    n = len(infra_arr)
    speed_arr = _numeric_array(speed, n, 50.0)
    lanes_arr = _numeric_array(lanes, n, 2.0)
    aadt_arr = _numeric_array(aadt, n, 0.0)

    out = np.full(n, 4, dtype=np.int16)
    is_path = infra_arr == "path"
    is_lane = infra_arr == "lane"
    mixed = ~(is_path | is_lane)

    out[is_path] = int(round(r["path_lts"]))
    lane_low = is_lane & (speed_arr <= r["lane_lts2_speed"]) & (lanes_arr <= r["lane_lts2_lanes"])
    out[is_lane] = int(round(r["lane_lts_high"]))
    out[lane_low] = int(round(r["lane_lts_low"]))

    mixed_lts1 = (mixed & (speed_arr <= r["mixed_lts1_speed"])
                  & (lanes_arr <= r["mixed_lts1_lanes"])
                  & (aadt_arr < r["mixed_lts1_aadt"]))
    mixed_lts2 = (mixed & ~mixed_lts1
                  & (speed_arr <= r["mixed_lts2_speed"])
                  & (lanes_arr <= r["mixed_lts2_lanes"]))
    mixed_lts3 = mixed & ~(mixed_lts1 | mixed_lts2) & (speed_arr <= r["mixed_lts3_speed"])
    out[mixed_lts1] = 1
    out[mixed_lts2] = 2
    out[mixed_lts3] = 3
    return np.clip(out, 1, 4)


def low_stress_islands(edge_from, edge_to, edge_len, lts, threshold=2):
    """Connected components of the subnetwork with ``LTS <= threshold``.

    Returns node component labels, edge component labels, component lengths
    and the low-stress length share. High-stress edges receive edge label -1.
    """
    edge_from = np.asarray(edge_from, dtype=np.int64)
    edge_to = np.asarray(edge_to, dtype=np.int64)
    edge_len = np.asarray(edge_len, dtype=float)
    lts = np.asarray(lts, dtype=float)
    if not (len(edge_from) == len(edge_to) == len(edge_len) == len(lts)):
        raise ValueError("edge arrays and LTS array must share one length")
    n_nodes = int(max(edge_from.max(initial=-1), edge_to.max(initial=-1)) + 1)
    low = lts <= float(threshold)
    adj = [[] for _ in range(n_nodes)]
    for i in np.where(low)[0]:
        a, b = int(edge_from[i]), int(edge_to[i])
        adj[a].append(b)
        adj[b].append(a)

    node_comp = np.full(n_nodes, -1, dtype=np.int64)
    comp = 0
    for start in range(n_nodes):
        if node_comp[start] >= 0 or not adj[start]:
            continue
        stack = [start]
        node_comp[start] = comp
        while stack:
            u = stack.pop()
            for v in adj[u]:
                if node_comp[v] < 0:
                    node_comp[v] = comp
                    stack.append(v)
        comp += 1

    edge_comp = np.full(len(edge_from), -1, dtype=np.int64)
    edge_comp[low] = node_comp[edge_from[low]]
    comp_len = np.zeros(comp, dtype=float)
    for c in range(comp):
        comp_len[c] = float(edge_len[edge_comp == c].sum())
    total = float(edge_len.sum())
    return {
        "node_labels": node_comp,
        "edge_labels": edge_comp,
        "n_components": comp,
        "component_length": comp_len,
        "edge_component_length": np.asarray([
            comp_len[c] if c >= 0 else 0.0 for c in edge_comp], dtype=float),
        "low_length": float(edge_len[low].sum()),
        "total_length": total,
        "low_share": float(edge_len[low].sum() / total) if total > 0 else 0.0,
    }
