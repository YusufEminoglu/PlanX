# -*- coding: utf-8 -*-
"""Public Transport Accessibility Level (PTAL), after Transport for London.

PTAL rates a place by the public transport *service* it can walk to - how
near the stops are, how often the services run - not by where those services
go. The calculation follows TfL's *Assessing transport connectivity in
London* (2015), which descends from the London Borough of Hammersmith &
Fulham method of 1992:

1. A **service access point** (SAP) is a stop within the walk catchment:
   8 minutes (640 m at 80 m/min) for buses and trams, 12 minutes (960 m)
   for rail, metro and other fixed-guideway modes.
2. Each **route** is counted once, at its *nearest* SAP. Its frequency is
   the number of departures in the analysis window divided by the window's
   length in hours (TfL uses the 08:15-09:15 AM peak).
3. Scheduled waiting time ``SWT = 0.5 * 60 / f`` minutes, plus a
   reliability allowance ``K`` (2.0 min for buses, 0.75 min for rail-type
   modes) gives the average waiting time ``AWT = SWT + K``.
4. Total access time ``TAT = walk + AWT``; equivalent doorstep frequency
   ``EDF = 30 / TAT``.
5. Per mode, ``AI_mode = EDF_max + 0.5 * sum(other EDFs)`` - the best route
   counts in full, every other one at half weight, because a second route is
   worth less than the first.
6. ``AI = sum over modes of AI_mode``, mapped to the nine bands below.

======= ============== =======
Band    AI range       Reading
======= ============== =======
0       0              no service within the catchments
1a      0.01 - 2.50    very poor
1b      2.51 - 5.00    very poor
2       5.01 - 10.00   poor
3       10.01 - 15.00  moderate
4       15.01 - 20.00  good
5       20.01 - 25.00  very good
6a      25.01 - 40.00  excellent
6b      40.01 and more excellent
======= ============== =======

What differs from TfL's own tool, stated rather than hidden: walk distances
are measured on the street network supplied, not on TfL's curated walk
network; route direction is not distinguished (a route's frequency is the
departures at its nearest SAP, which on a two-way corridor is one side of
the street - the same thing TfL's "one direction" rule approximates); and
GTFS ``route_type`` decides which catchment and reliability allowance a
route gets.
"""
from __future__ import annotations

import numpy as np

#: (upper bound inclusive, band label). AI above the last bound is 6b.
BANDS = ((0.0, "0"), (2.5, "1a"), (5.0, "1b"), (10.0, "2"), (15.0, "3"),
         (20.0, "4"), (25.0, "5"), (40.0, "6a"))

#: GTFS route_type codes (basic and the common extended ones) that TfL would
#: treat as rail-type: walk catchment 12 minutes, reliability 0.75 minute.
RAIL_TYPES = frozenset({1, 2, 12, 100, 101, 102, 103, 106, 109, 400, 401,
                        402, 403, 405})
#: Tram/light rail: bus catchment (8 min) but rail reliability (0.75 min),
#: as TfL treats London Trams.
TRAM_TYPES = frozenset({0, 900, 901, 902, 903, 904, 905, 906})

WALK_SPEED_M_PER_MIN = 80.0
BUS_CATCHMENT_MIN = 8.0
RAIL_CATCHMENT_MIN = 12.0
BUS_RELIABILITY_MIN = 2.0
RAIL_RELIABILITY_MIN = 0.75


def band(ai):
    """PTAL band label for an accessibility index value."""
    ai = float(ai)
    if ai <= 0.0:
        return "0"
    for upper, label in BANDS[1:]:
        if ai <= upper:
            return label
    return "6b"


def band_rank(label):
    """Ordinal 0..8 for a band label (0, 1a, 1b, 2, 3, 4, 5, 6a, 6b)."""
    order = ["0", "1a", "1b", "2", "3", "4", "5", "6a", "6b"]
    return order.index(label)


def mode_class(route_type):
    """'rail', 'tram' or 'bus' for a GTFS route_type."""
    rt = int(route_type)
    if rt in RAIL_TYPES:
        return "rail"
    if rt in TRAM_TYPES:
        return "tram"
    return "bus"


def mode_parameters(mode, bus_catch=BUS_CATCHMENT_MIN, rail_catch=RAIL_CATCHMENT_MIN,
                    bus_rel=BUS_RELIABILITY_MIN, rail_rel=RAIL_RELIABILITY_MIN):
    """(walk catchment minutes, reliability minutes) for a mode class."""
    if mode == "rail":
        return rail_catch, rail_rel
    if mode == "tram":
        return bus_catch, rail_rel
    return bus_catch, bus_rel


def route_frequencies(gtfs, services, window):
    """Departures per hour of every route at every stop within ``window``.

    Returns ``{stop_pos: {route_id: per_hour}}``. A departure is a stop_time
    that leaves the stop (a trip's last call does not count), the same rule
    :func:`transit.stop_frequencies` uses.
    """
    lo, hi = float(window[0]), float(window[1])
    if hi <= lo:
        raise ValueError("the analysis window must end after it starts")
    hours = (hi - lo) / 3600.0
    counts = {}
    for tid, (rid, sid) in gtfs["trips"].items():
        if sid not in services:
            continue
        st = gtfs["stop_times"].get(tid)
        if not st:
            continue
        last = len(st) - 1
        for i, (_arr, dep, pos) in enumerate(st):
            if i == last:
                continue
            if lo <= dep < hi:
                per_stop = counts.setdefault(pos, {})
                per_stop[rid] = per_stop.get(rid, 0) + 1
    return {pos: {rid: n / hours for rid, n in routes.items()}
            for pos, routes in counts.items()}


def accessibility_index(stop_walk_min, stop_routes, route_mode,
                        bus_catch=BUS_CATCHMENT_MIN, rail_catch=RAIL_CATCHMENT_MIN,
                        bus_rel=BUS_RELIABILITY_MIN, rail_rel=RAIL_RELIABILITY_MIN):
    """PTAL accessibility index for ONE place.

    ``stop_walk_min``: ``{stop_pos: walk minutes}`` for the stops this place
    can reach (any distance - the catchment is applied here, per mode).
    ``stop_routes``: ``{stop_pos: {route_id: per_hour}}``.
    ``route_mode``: ``{route_id: 'bus' | 'tram' | 'rail'}``.

    Returns a dict with ``ai`` (total), ``ai_by_mode``, ``n_routes`` (routes
    counted), ``n_saps`` (distinct stops used) and ``best`` (the route with
    the highest EDF, or None).
    """
    nearest = {}
    for stop, walk in stop_walk_min.items():
        if not np.isfinite(walk):
            continue
        for rid, freq in stop_routes.get(stop, {}).items():
            if freq <= 0:
                continue
            mode = route_mode.get(rid, "bus")
            catchment, _ = mode_parameters(mode, bus_catch, rail_catch, bus_rel, rail_rel)
            if walk > catchment:
                continue
            # Nearest SAP per route; equal walks keep the higher frequency so
            # the answer does not depend on dict order.
            held = nearest.get(rid)
            if held is None or walk < held[0] or (walk == held[0] and freq > held[1]):
                nearest[rid] = (walk, freq, stop, mode)
    edf_by_mode = {}
    best = None
    for rid in sorted(nearest):
        walk, freq, _stop, mode = nearest[rid]
        _, reliability = mode_parameters(mode, bus_catch, rail_catch, bus_rel, rail_rel)
        awt = 0.5 * 60.0 / freq + reliability
        edf = 30.0 / (walk + awt)
        edf_by_mode.setdefault(mode, []).append(edf)
        if best is None or edf > best[1]:
            best = (rid, edf)
    ai_by_mode = {}
    for mode, edfs in edf_by_mode.items():
        edfs = sorted(edfs, reverse=True)
        ai_by_mode[mode] = edfs[0] + 0.5 * sum(edfs[1:])
    return {
        "ai": float(sum(ai_by_mode.values())),
        "ai_by_mode": ai_by_mode,
        "n_routes": len(nearest),
        "n_saps": len({v[2] for v in nearest.values()}),
        "best": None if best is None else best[0],
    }
