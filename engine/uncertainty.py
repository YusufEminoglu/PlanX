# -*- coding: utf-8 -*-
"""Reusable Monte Carlo, rank-stability and calibration diagnostics."""
from __future__ import annotations

import numpy as np


def summarize_samples(samples, axis=0) -> dict:
    values = np.asarray(samples, dtype=float)
    return {
        "mean": np.mean(values, axis=axis),
        "std": np.std(values, axis=axis),
        "p05": np.percentile(values, 5, axis=axis),
        "p50": np.percentile(values, 50, axis=axis),
        "p95": np.percentile(values, 95, axis=axis),
    }


def tornado(base_value: float, low_values, high_values, labels) -> list[dict]:
    rows = []
    for label, low, high in zip(labels, low_values, high_values):
        rows.append({
            "parameter": str(label), "low": float(low), "high": float(high),
            "swing": abs(float(high) - float(low)),
            "base": float(base_value),
        })
    return sorted(rows, key=lambda row: row["swing"], reverse=True)


def rank_stability(rank_function, snapshots, weights: dict, simulations=200,
                   variation=0.20, seed=42) -> dict:
    """Perturb decision weights and summarize alternative rank stability."""
    baseline = rank_function(snapshots, weights)
    names = [item["name"] for item in baseline["scenarios"]]
    metrics = [item["key"] for item in baseline["metrics"]]
    rng = np.random.default_rng(seed)
    rank_samples = {name: [] for name in names}
    first = {name: 0 for name in names}
    for _ in range(max(1, int(simulations))):
        perturbed = {}
        for key in metrics:
            base = max(0.0, float(weights.get(key, 1.0)))
            perturbed[key] = base * float(rng.uniform(max(0.0, 1.0 - variation), 1.0 + variation))
        result = rank_function(snapshots, perturbed)
        for item in result["scenarios"]:
            rank_samples[item["name"]].append(item["rank"])
            if item["rank"] == 1:
                first[item["name"]] += 1
    return {
        "baseline": baseline,
        "simulations": max(1, int(simulations)),
        "variation": float(variation),
        "scenarios": {
            name: {
                "mean_rank": float(np.mean(rank_samples[name])),
                "rank_std": float(np.std(rank_samples[name])),
                "p_best": first[name] / max(1, int(simulations)),
            }
            for name in names
        },
    }


def validation_metrics(observed, predicted) -> dict:
    observed = np.asarray(observed, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    valid = np.isfinite(observed) & np.isfinite(predicted)
    if not np.any(valid):
        raise ValueError("No paired finite observed/predicted values.")
    observed, predicted = observed[valid], predicted[valid]
    residual = predicted - observed
    denominator = np.sum((observed - np.mean(observed)) ** 2)
    return {
        "n": int(len(observed)), "mae": float(np.mean(np.abs(residual))),
        "rmse": float(np.sqrt(np.mean(residual ** 2))),
        "bias": float(np.mean(residual)),
        "r2": float(1.0 - np.sum(residual ** 2) / denominator) if denominator > 0 else 0.0,
    }
