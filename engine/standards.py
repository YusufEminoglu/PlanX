# -*- coding: utf-8 -*-
"""Per-capita planning standards: parsing and balance computation.

Standards are configurable text, never hard-coded regulation values:
``"green=10, education=4, health=1.5"`` means 10 m2 of green space per
capita and so on. Keywords match land-use category names case-insensitively
by containment, first hit wins.
"""
from __future__ import annotations


def parse_standards(text: str):
    """``"green=10, park=10"`` -> [("green", 10.0), ("park", 10.0)].

    Separators: comma or semicolon. Raises ValueError on malformed entries.
    """
    standards = []
    for token in str(text).replace(";", ",").split(","):
        token = token.strip()
        if not token:
            continue
        if "=" not in token:
            raise ValueError(f"Standard entry needs keyword=value: '{token}'")
        key, _, value = token.partition("=")
        key = key.strip().lower()
        try:
            per_capita = float(value.strip())
        except ValueError:
            raise ValueError(f"Not a number in '{token}'")
        if not key or per_capita < 0:
            raise ValueError(f"Invalid standard entry: '{token}'")
        standards.append((key, per_capita))
    if not standards:
        raise ValueError("No standards given (expected e.g. 'green=10, education=4').")
    return standards


def match_standard(category: str, standards):
    """First standard whose keyword is contained in the category name."""
    cat = str(category).lower()
    for key, per_capita in standards:
        if key in cat:
            return key, per_capita
    return None, None


def balance_rows(category_areas: dict, population: float, standards):
    """Compute the land-use balance table.

    ``category_areas``: {category name: total area m2}. Returns a list of
    dict rows with actual/required per-capita figures and surplus/deficit.
    """
    rows = []
    for category in sorted(category_areas):
        area = float(category_areas[category])
        key, per_capita = match_standard(category, standards)
        row = {
            "category": str(category),
            "area_m2": area,
            "m2_per_capita": area / population if population > 0 else 0.0,
            "standard_key": key or "",
            "std_m2_capita": per_capita if per_capita is not None else 0.0,
            "required_m2": (per_capita * population) if per_capita is not None else 0.0,
        }
        if per_capita is None:
            row["balance_m2"] = 0.0
            row["status"] = "No standard"
        else:
            row["balance_m2"] = area - row["required_m2"]
            row["status"] = "Meets standard" if row["balance_m2"] >= 0 else "Deficit"
        rows.append(row)
    return rows
