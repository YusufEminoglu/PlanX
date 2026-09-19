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


# --------------------------------------------------------------------------
# Supply balance
# --------------------------------------------------------------------------
#: Inventory reached this zone and holds no spaces: a real deficit.
SUPPLY_COUNTED = "counted"
#: Inventory reached this zone; the zone has none of it in range.
SUPPLY_ZERO = "zero supply found"
#: No inventory in range and the inventory layer does not reach this zone.
SUPPLY_ABSENT = "supply data absent"


def supply_within(costs, spaces, radius):
    """Spaces and inventory features reachable from each zone.

    ``costs`` is a (zones, features) matrix of access costs - metres of
    street network, or straight-line distance, whichever the caller computed.
    A feature counts for a zone when its cost is at or below ``radius``.

    Returns ``(spaces_found, features_found)``, both one value per zone.
    """
    costs = np.atleast_2d(np.asarray(costs, dtype=np.float64))
    spaces = np.asarray(spaces, dtype=np.float64).reshape(-1)
    n_zones = costs.shape[0]
    if costs.shape[1] == 0 or spaces.size == 0:
        return np.zeros(n_zones), np.zeros(n_zones, dtype=np.int64)
    inside = costs <= float(radius)
    features = inside.sum(axis=1).astype(np.int64)
    found = np.where(inside, spaces[None, :], 0.0).sum(axis=1)
    return found, features


def straight_line_costs(zone_xy, supply_xy):
    """Euclidean zone-to-inventory distance matrix, ``(zones, features)``.

    The no-network fallback for :func:`supply_within`. With no network the
    caller has not said what route anyone walks, so the only distance the data
    itself supports is the straight line between the two points.

    The shape is ``(n_zones, n_supply)`` even when there is no inventory, so an
    empty inventory reaches :func:`supply_within` as a matrix of width zero
    rather than as a special case.
    """
    zone_xy = np.atleast_2d(np.asarray(zone_xy, dtype=np.float64))
    supply_xy = np.asarray(supply_xy, dtype=np.float64).reshape(-1, 2)
    if supply_xy.size == 0:
        return np.full((zone_xy.shape[0], 0), np.inf)
    delta = zone_xy[:, None, :] - supply_xy[None, :, :]
    return np.hypot(delta[:, :, 0], delta[:, :, 1])


def nearest_supply_cost(costs):
    """Per-zone cost to the closest inventory feature; inf where none exists."""
    costs = np.atleast_2d(np.asarray(costs, dtype=np.float64))
    if costs.shape[1] == 0:
        return np.full(costs.shape[0], np.inf)
    return costs.min(axis=1)


def classify_supply(features_found, covered):
    """Per-zone supply status - the distinction S3 exists to preserve.

    ``covered`` says whether the inventory layer reaches that zone at all. A
    zone the inventory never surveyed has *no supply data*, which is a
    different claim from a surveyed zone that has *no parking*: reporting the
    first as a deficit turns a coverage gap into a finding.
    """
    features = np.asarray(features_found)
    covered = np.asarray(covered, dtype=bool)
    status = np.where(covered, SUPPLY_ZERO, SUPPLY_ABSENT).astype(object)
    status = np.where(features > 0, SUPPLY_COUNTED, status)
    return [str(item) for item in status]


def balance(demand, spaces_found, status):
    """Supply minus demand per zone; None where the supply is unknown.

    An unknown zone gets no balance rather than a deficit, so that summing
    the column cannot present unsurveyed ground as a parking shortfall.
    """
    demand = np.asarray(demand, dtype=np.float64).reshape(-1)
    supply = np.asarray(spaces_found, dtype=np.float64).reshape(-1)
    out = []
    for i, state in enumerate(status):
        out.append(None if state == SUPPLY_ABSENT
                   else float(supply[i]) - float(demand[i]))
    return out


def balance_summary(demand, spaces_found, status) -> list:
    """[(label, value)] for a deterministic log, sorted by label."""
    demand = np.asarray(demand, dtype=np.float64).reshape(-1)
    supply = np.asarray(spaces_found, dtype=np.float64).reshape(-1)
    known = np.array([state != SUPPLY_ABSENT for state in status])
    counts = {}
    for state in status:
        counts[state] = counts.get(state, 0) + 1
    rows = [(f"zones {key}", float(counts[key])) for key in sorted(counts)]
    rows.append(("parking demand (all zones, spaces)", float(demand.sum())))
    if known.any():
        surplus = supply[known] - demand[known]
        rows.append(("parking supply (surveyed zones, spaces)",
                     float(supply[known].sum())))
        rows.append(("surplus (+) or deficit (-), surveyed zones, spaces",
                     float(surplus.sum())))
        rows.append(("surveyed zones in deficit",
                     float((surplus < 0).sum())))
    rows.sort(key=lambda row: row[0])
    return rows

