# -*- coding: utf-8 -*-
"""Deterministic, non-executable audit manifests for PlanX results."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone


SCHEMA = "planx-analysis-manifest-v1"


def stable_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def build_manifest(algorithm_id: str, parameters: dict, inputs: list, version: str = "") -> dict:
    core = {
        "schema": SCHEMA,
        "algorithm_id": str(algorithm_id),
        "plugin_version": str(version),
        "parameters": dict(parameters),
        "inputs": list(inputs),
    }
    return {
        **core,
        "analysis_fingerprint": fingerprint(core),
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }


def validate_manifest(manifest: dict) -> bool:
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        return False
    core = {key: manifest.get(key) for key in ("schema", "algorithm_id", "plugin_version", "parameters", "inputs")}
    return manifest.get("analysis_fingerprint") == fingerprint(core)
