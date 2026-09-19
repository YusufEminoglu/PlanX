# -*- coding: utf-8 -*-
"""Parking demand generation rates: parsing and per-zone computation.

Rates are configurable text, never hard-coded regulation values. Each entry
is ``category=basis:rate``::

    "residential=unit:1.5, office=sqm:2.5, restaurant=seat:0.2"

The basis states what one rate unit counts against, because parking
standards are not written on one common denominator - residential standards
count dwellings, commercial standards count floor area, assembly standards
count seats::

    unit   spaces per dwelling unit      demand = rate * size
    sqm    spaces per 1000 m2 GFA        demand = rate * size / 1000
    seat   spaces per seat               demand = rate * size

Keywords match land-use category names case-insensitively by containment,
first hit wins - the same rule ``engine.standards.match_standard`` uses, so
the two rate-table tools in the plugin behave alike.
"""
from __future__ import annotations

import numpy as np

#: Gross floor area one ``sqm`` rate unit counts against.
SQM_PER_RATE_UNIT = 1000.0

BASES = ("unit", "sqm", "seat")


def parse_rates(text: str):
    """``"residential=unit:1.5, office=sqm:2.5"`` -> [("residential", "unit", 1.5), ...].

    Separators: comma or semicolon. Raises ValueError on malformed entries.
    """
    rates = []
    for token in str(text).replace(";", ",").split(","):
        token = token.strip()
        if not token:
            continue
        if "=" not in token:
            raise ValueError(f"Rate entry needs category=basis:rate: '{token}'")
        category, _, spec = token.partition("=")
        category = category.strip().lower()
        if ":" not in spec:
            raise ValueError(
                f"Rate entry needs a basis as basis:rate, one of "
                f"{', '.join(BASES)}: '{token}'")
        basis, _, value = spec.partition(":")
        basis = basis.strip().lower()
        if basis not in BASES:
            raise ValueError(
                f"Unknown basis '{basis}' in '{token}' - expected one of "
                f"{', '.join(BASES)}")
        try:
            rate = float(value.strip())
        except ValueError:
            raise ValueError(f"Not a number in '{token}'")
        if not category or rate < 0:
            raise ValueError(f"Invalid rate entry: '{token}'")
        rates.append((category, basis, rate))
    if not rates:
        raise ValueError(
            "No rates given (expected e.g. 'residential=unit:1.5, office=sqm:2.5')")
    return rates


def match_rate(category, rates):
    """First rate row whose keyword is contained in the category name."""
    cat = str(category).lower()
    for keyword, basis, rate in rates:
        if keyword in cat:
            return keyword, basis, rate
    return None, None, None


def demand_for_size(basis: str, rate: float, size: float) -> float:
    """Parking spaces one zone demands at this basis, rate and size."""
    size = float(size)
    if basis == "sqm":
        return float(rate) * size / SQM_PER_RATE_UNIT
    return float(rate) * size


def parking_demand(categories, sizes, rates) -> np.ndarray:
    """Per-zone parking demand in spaces.

    A zone whose category matches no rate row demands 0. The caller reports
    the unmatched categories rather than treating them as an error: a rate
    table that does not cover a category is a coverage gap, and silently
    folding it into the total would present an undercount as a real figure.
    """
    sizes = np.asarray(sizes, dtype=np.float64)
    demand = np.zeros(len(categories), dtype=np.float64)
    for i, category in enumerate(categories):
        _, basis, rate = match_rate(category, rates)
        if basis is None:
            continue
        demand[i] = demand_for_size(basis, rate, sizes[i])
    return demand


def unmatched_categories(categories, rates):
    """Sorted, de-duplicated categories the rate table did not cover."""
    missing = {str(c) for c in categories if match_rate(c, rates)[0] is None}
    return sorted(missing)


def category_subtotals(categories, demand) -> list:
    """[(category, spaces)] sorted by category, for a deterministic log line."""
    totals = {}
    for category, value in zip(categories, demand):
        key = str(category)
        totals[key] = totals.get(key, 0.0) + float(value)
    return [(key, totals[key]) for key in sorted(totals)]
