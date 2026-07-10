# -*- coding: utf-8 -*-
"""Seismic collapse and debris-spread engine functions.

Pure-NumPy, QGIS-free core for a Monte Carlo earthquake screening model:
per-building collapse probability from construction year and event
magnitude, and the resulting debris spread radius / volume. Geometry
operations (buffering, union, intersection with the road network) stay
in the algorithm wrapper; everything that is pure arithmetic lives here
so it can be unit-tested without a QGIS session.
"""
from __future__ import annotations

import numpy as np

# Vulnerability tiers by construction-year cutoff, oldest first: (max_year, base_probability).
# Buildings built after the last cutoff get the final tier's probability.
YEAR_TIERS = (
    (1985, 0.85),
    (2000, 0.60),
    (2018, 0.25),
)
DEFAULT_BASE_PROBABILITY = 0.05


def magnitude_factor(magnitude: float) -> float:
    """Exponential scaling of baseline fragility with moment magnitude (Mw), centred at 7.0."""
    return float(np.exp(0.8 * (magnitude - 7.0)))


def base_probability(year: np.ndarray) -> np.ndarray:
    """Vectorized per-tier baseline collapse probability from construction year."""
    year = np.asarray(year, dtype=np.float64)
    result = np.full(year.shape, DEFAULT_BASE_PROBABILITY, dtype=np.float64)
    # Apply from newest to oldest cutoff so the first (oldest/highest-risk) match wins.
    for max_year, prob in reversed(YEAR_TIERS):
        result = np.where(year <= max_year, prob, result)
    return result


def collapse_probability(year: np.ndarray, magnitude: float) -> np.ndarray:
    """Per-building collapse probability, clamped to [0, 1]."""
    p = base_probability(year) * magnitude_factor(magnitude)
    return np.clip(p, 0.0, 1.0)


def simulate_collapse(seed: int, p_collapse: np.ndarray) -> np.ndarray:
    """Deterministic Monte Carlo draw: True where the building collapses.

    A single seeded generator draws one uniform sample per building, so the
    same (seed, inputs) pair always reproduces the identical collapse set,
    and changing the seed samples a different stochastic realization.
    """
    p_collapse = np.asarray(p_collapse, dtype=np.float64)
    rng = np.random.default_rng(seed)
    draws = rng.random(p_collapse.shape)
    return draws < p_collapse


# --------------------------------------------------------------------------- #
# Street-space width helpers (network sources B and C of the debris algorithm)
# --------------------------------------------------------------------------- #

# Typical full carriageway widths (m) per OSM ``highway`` class, applied when
# the road network arrives as centerlines without a usable width attribute.
# Screening quality: the Monte Carlo debris-radius uncertainty dominates any
# nominal-width error at this scale.
OSM_HIGHWAY_WIDTHS_M = {
    "motorway": 25.0,
    "trunk": 25.0,
    "primary": 18.0,
    "secondary": 14.0,
    "tertiary": 10.0,
    "residential": 8.0,
    "unclassified": 8.0,
    "road": 8.0,
    "service": 5.0,
    "living_street": 5.0,
    "track": 4.0,
    "pedestrian": 3.0,
    "footway": 3.0,
    "cycleway": 3.0,
    "path": 3.0,
    "steps": 2.0,
}


def parse_width_m(value):
    """Lenient road-width parser for attribute values.

    Accepts numbers and strings such as "6.5", "6,5" or "6.5 m" and returns
    the width as float metres. Returns None when the value is missing,
    non-numeric or non-positive - the caller then falls back to a class or
    default width.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        width = float(value)
        return width if np.isfinite(width) and width > 0.0 else None
    text = str(value).strip().lower()
    if not text:
        return None
    for unit in ("meters", "metres", "meter", "metre", "m"):
        if text.endswith(unit):
            text = text[: -len(unit)].strip()
            break
    try:
        width = float(text.replace(",", "."))
    except ValueError:
        return None
    return width if np.isfinite(width) and width > 0.0 else None


def highway_width_m(highway_class, fallback: float) -> float:
    """Full carriageway width (m) for an OSM ``highway`` class value.

    Matching is case- and whitespace-tolerant; "_link" ramp variants inherit
    the parent class width; unknown or missing classes get ``fallback``.
    """
    if highway_class is None:
        return float(fallback)
    key = str(highway_class).strip().lower()
    if key.endswith("_link"):
        key = key[: -len("_link")]
    return float(OSM_HIGHWAY_WIDTHS_M.get(key, fallback))


def debris_extent(
    height: np.ndarray, area: np.ndarray, collapsed: np.ndarray,
    debris_factor: float, solid_volume_ratio: float,
) -> tuple:
    """Debris spread radius (m) and volume (m3) for each building.

    ``debris_factor`` (k) is the fraction of building height thrown
    horizontally onto surrounding ground (Goretti & Sarli, 2006).
    ``solid_volume_ratio`` converts gross building volume to actual
    (void-corrected) debris volume. Non-collapsed buildings get 0/0.
    """
    height = np.asarray(height, dtype=np.float64)
    area = np.asarray(area, dtype=np.float64)
    collapsed = np.asarray(collapsed, dtype=bool)

    radius = np.where(collapsed, height * debris_factor, 0.0)
    volume = np.where(collapsed, area * height * solid_volume_ratio, 0.0)
    return radius, volume
