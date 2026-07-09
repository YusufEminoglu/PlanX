# -*- coding: utf-8 -*-
"""GTFS reading and transit accessibility kernels.

Pure stdlib (zipfile + csv) with NumPy arrays for the timetable. Three
layers:

* :func:`read_gtfs` - parse a GTFS zip into plain dicts/arrays, with clear
  validation errors (the front door for malformed feeds).
* :func:`stop_frequencies` - departures per stop for a service day and
  time window (the service-intensity view).
* :func:`compile_day` + :func:`earliest_arrival` - a RAPTOR round-based
  earliest-arrival computation (Delling et al. 2012, simplified: walking
  legs happen outside on the street network, transfers occur by arriving
  and re-boarding at the same stop).

GTFS times can exceed 24:00:00 (services past midnight): all times are
plain seconds since midnight of the service day, never datetimes.
"""
from __future__ import annotations

import csv
import io
import zipfile
from datetime import date as _date

import numpy as np

INF = float("inf")

REQUIRED_FILES = ("stops.txt", "routes.txt", "trips.txt", "stop_times.txt")

ROUTE_TYPES = {
    0: "Tram", 1: "Metro", 2: "Rail", 3: "Bus", 4: "Ferry",
    5: "Cable tram", 6: "Aerial lift", 7: "Funicular",
    11: "Trolleybus", 12: "Monorail",
}

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday",
             "saturday", "sunday")


def parse_time(text) -> int:
    """GTFS ``H:MM:SS`` / ``HH:MM:SS`` to seconds since midnight.

    Hours may exceed 23 (``25:10:00`` is 1:10 the next morning, kept as
    90600 s). Raises ValueError on malformed input.
    """
    parts = str(text).strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"not a GTFS time: '{text}'")
    h, m, s = (int(p) for p in parts)
    if not (0 <= m < 60 and 0 <= s < 60 and h >= 0):
        raise ValueError(f"not a GTFS time: '{text}'")
    return h * 3600 + m * 60 + s


def _read_csv(zf: zipfile.ZipFile, name: str):
    with zf.open(name) as fh:
        text = io.TextIOWrapper(fh, encoding="utf-8-sig", newline="")
        for row in csv.DictReader(text):
            yield {k.strip(): (v.strip() if v is not None else "")
                   for k, v in row.items() if k is not None}


def read_gtfs(path):
    """Parse a GTFS zip. Returns a dict of plain structures:

    - ``stop_ids`` list, ``stop_names`` list, ``stop_lat`` / ``stop_lon``
      float arrays, ``stop_index`` id -> position
    - ``routes``: route_id -> {"short", "long", "type"}
    - ``trips``: trip_id -> (route_id, service_id)
    - ``stop_times``: trip_id -> list of (arr_sec, dep_sec, stop_pos),
      sorted by stop_sequence
    - ``calendar``: service_id -> {"days": 7-bool tuple, "start": "YYYYMMDD",
      "end": "YYYYMMDD"}
    - ``calendar_dates``: list of (service_id, "YYYYMMDD", exception_type)

    Raises ValueError naming every missing required file or field.
    """
    try:
        zf = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError(f"could not open the GTFS zip: {exc}")
    names = {n.split("/")[-1]: n for n in zf.namelist() if not n.endswith("/")}
    missing = [f for f in REQUIRED_FILES if f not in names]
    if missing:
        raise ValueError("GTFS zip is missing required file(s): "
                         + ", ".join(missing))
    if "calendar.txt" not in names and "calendar_dates.txt" not in names:
        raise ValueError("GTFS zip has neither calendar.txt nor "
                         "calendar_dates.txt - cannot resolve service days")

    stop_ids, stop_names, lat, lon = [], [], [], []
    stop_index = {}
    for row in _read_csv(zf, names["stops.txt"]):
        sid = row.get("stop_id", "")
        if not sid:
            continue
        try:
            la = float(row.get("stop_lat", "") or "nan")
            lo = float(row.get("stop_lon", "") or "nan")
        except ValueError:
            raise ValueError(f"stop '{sid}' has a non-numeric lat/lon")
        stop_index[sid] = len(stop_ids)
        stop_ids.append(sid)
        stop_names.append(row.get("stop_name", "") or sid)
        lat.append(la)
        lon.append(lo)
    if not stop_ids:
        raise ValueError("stops.txt contains no stops")

    routes = {}
    for row in _read_csv(zf, names["routes.txt"]):
        rid = row.get("route_id", "")
        if not rid:
            continue
        try:
            rtype = int(row.get("route_type", "") or -1)
        except ValueError:
            rtype = -1
        routes[rid] = {"short": row.get("route_short_name", ""),
                       "long": row.get("route_long_name", ""),
                       "type": rtype}

    trips = {}
    for row in _read_csv(zf, names["trips.txt"]):
        tid = row.get("trip_id", "")
        if not tid:
            continue
        trips[tid] = (row.get("route_id", ""), row.get("service_id", ""))

    raw_st = {}
    for row in _read_csv(zf, names["stop_times.txt"]):
        tid = row.get("trip_id", "")
        sid = row.get("stop_id", "")
        if not tid or tid not in trips or sid not in stop_index:
            continue
        arr_txt = row.get("arrival_time", "") or row.get("departure_time", "")
        dep_txt = row.get("departure_time", "") or arr_txt
        if not arr_txt:
            continue  # untimed intermediate stop - lite reader skips it
        try:
            seq = int(row.get("stop_sequence", "") or 0)
            arr = parse_time(arr_txt)
            dep = parse_time(dep_txt)
        except ValueError as exc:
            raise ValueError(f"stop_times for trip '{tid}': {exc}")
        raw_st.setdefault(tid, []).append((seq, arr, dep, stop_index[sid]))
    stop_times = {}
    for tid, rows in raw_st.items():
        rows.sort(key=lambda r: r[0])
        stop_times[tid] = [(arr, dep, pos) for (_, arr, dep, pos) in rows]

    calendar = {}
    if "calendar.txt" in names:
        for row in _read_csv(zf, names["calendar.txt"]):
            sid = row.get("service_id", "")
            if not sid:
                continue
            days = tuple(row.get(day, "0") == "1" for day in _WEEKDAYS)
            calendar[sid] = {"days": days,
                             "start": row.get("start_date", "00000000"),
                             "end": row.get("end_date", "99999999")}
    calendar_dates = []
    if "calendar_dates.txt" in names:
        for row in _read_csv(zf, names["calendar_dates.txt"]):
            sid = row.get("service_id", "")
            d = row.get("date", "")
            try:
                ex = int(row.get("exception_type", "") or 0)
            except ValueError:
                ex = 0
            if sid and d and ex in (1, 2):
                calendar_dates.append((sid, d, ex))
    zf.close()
    return {
        "stop_ids": stop_ids, "stop_names": stop_names,
        "stop_lat": np.asarray(lat), "stop_lon": np.asarray(lon),
        "stop_index": stop_index, "routes": routes, "trips": trips,
        "stop_times": stop_times, "calendar": calendar,
        "calendar_dates": calendar_dates,
    }


def active_services(gtfs, day: str) -> set:
    """Service ids running on ``day`` ('YYYYMMDD'), honouring exceptions."""
    day = str(day)
    try:
        weekday = _date(int(day[:4]), int(day[4:6]), int(day[6:8])).weekday()
    except (ValueError, IndexError):
        raise ValueError(f"not a GTFS date (YYYYMMDD): '{day}'")
    active = set()
    for sid, cal in gtfs["calendar"].items():
        if cal["days"][weekday] and cal["start"] <= day <= cal["end"]:
            active.add(sid)
    for sid, d, ex in gtfs["calendar_dates"]:
        if d != day:
            continue
        if ex == 1:
            active.add(sid)
        else:
            active.discard(sid)
    return active


def first_service_day(gtfs) -> str:
    """A day the feed actually runs: the earliest calendar start whose
    weekday is served (falling back to the first added exception date)."""
    best = None
    for cal in gtfs["calendar"].values():
        start, end = cal["start"], cal["end"]
        try:
            d = _date(int(start[:4]), int(start[4:6]), int(start[6:8]))
        except (ValueError, IndexError):
            continue
        for _ in range(7):
            key = d.strftime("%Y%m%d")
            if cal["days"][d.weekday()] and key <= end:
                if best is None or key < best:
                    best = key
                break
            d = _date.fromordinal(d.toordinal() + 1)
    if best is None:
        added = sorted(d for (_, d, ex) in gtfs["calendar_dates"] if ex == 1)
        if added:
            best = added[0]
    if best is None:
        raise ValueError("the feed has no active service day at all")
    return best


def stop_frequencies(gtfs, day: str, window=(6 * 3600, 22 * 3600)):
    """Departures per stop within ``window`` (seconds) on ``day``.

    A departure is any stop_time that leaves the stop (the trip's final
    arrival does not count). Returns dict with per-stop arrays aligned to
    ``stop_ids``: ``departures``, ``per_hour``, ``headway_min`` (mean
    scheduled gap = window / departures; 0 where no service) and
    ``n_routes`` (distinct routes serving the stop in the window), plus
    ``route_trips``: route_id -> trips touching the window.
    """
    services = active_services(gtfs, day)
    lo, hi = float(window[0]), float(window[1])
    if hi <= lo:
        raise ValueError("window end must be after window start")
    n = len(gtfs["stop_ids"])
    deps = np.zeros(n, dtype=np.int64)
    routes_at = [set() for _ in range(n)]
    route_trips = {}
    for tid, (rid, sid) in gtfs["trips"].items():
        if sid not in services:
            continue
        st = gtfs["stop_times"].get(tid)
        if not st:
            continue
        touched = False
        for i, (arr, dep, pos) in enumerate(st):
            if i == len(st) - 1:
                continue
            if lo <= dep < hi:
                deps[pos] += 1
                routes_at[pos].add(rid)
                touched = True
        if touched:
            route_trips[rid] = route_trips.get(rid, 0) + 1
    hours = (hi - lo) / 3600.0
    per_hour = deps / hours
    with np.errstate(divide="ignore"):
        headway = np.where(deps > 0, (hi - lo) / 60.0 / np.maximum(deps, 1), 0.0)
    return {
        "departures": deps,
        "per_hour": per_hour,
        "headway_min": headway,
        "n_routes": np.asarray([len(r) for r in routes_at], dtype=np.int64),
        "route_trips": route_trips,
    }


def compile_day(gtfs, day: str):
    """Compile the timetable of ``day`` into RAPTOR patterns.

    Returns ``(patterns, stop_patterns)``: ``patterns`` is a list of dicts
    with ``stops`` (tuple of stop positions), ``arr`` and ``dep`` -
    (n_trips, n_stops) arrays sorted by first departure; ``stop_patterns``
    maps a stop position to a list of (pattern index, position on it).
    """
    services = active_services(gtfs, day)
    grouped = {}
    for tid, (rid, sid) in gtfs["trips"].items():
        if sid not in services:
            continue
        st = gtfs["stop_times"].get(tid)
        if not st or len(st) < 2:
            continue
        seq = tuple(pos for (_, _, pos) in st)
        arr = [a for (a, _, _) in st]
        dep = [d for (_, d, _) in st]
        grouped.setdefault((rid, seq), []).append((dep[0], arr, dep))
    patterns = []
    stop_patterns = {}
    for (rid, seq), trips in sorted(grouped.items()):
        trips.sort(key=lambda t: t[0])
        arr = np.asarray([t[1] for t in trips], dtype=np.float64)
        dep = np.asarray([t[2] for t in trips], dtype=np.float64)
        p_idx = len(patterns)
        patterns.append({"route": rid, "stops": seq, "arr": arr, "dep": dep})
        for pos_on, stop in enumerate(seq):
            stop_patterns.setdefault(stop, []).append((p_idx, pos_on))
    return patterns, stop_patterns


def earliest_arrival(patterns, stop_patterns, n_stops, access,
                     max_transfers=2):
    """RAPTOR earliest arrival at every stop.

    ``access`` maps a stop position to the earliest second one can stand
    on its platform (departure time + access walk). ``max_transfers`` is
    the number of re-boardings allowed (0 = single ride). Returns a float
    array of arrival seconds (INF where unreachable). A stop reachable by
    access walk alone reports its access time.
    """
    best = np.full(n_stops, INF)
    marked = set()
    for stop, t in access.items():
        if t < best[stop]:
            best[stop] = float(t)
            marked.add(int(stop))
    for _ in range(int(max_transfers) + 1):
        prev = best.copy()
        touched = {}
        for stop in marked:
            for p_idx, pos in stop_patterns.get(stop, ()):
                if p_idx not in touched or pos < touched[p_idx]:
                    touched[p_idx] = pos
        new_marked = set()
        for p_idx, start_pos in touched.items():
            pat = patterns[p_idx]
            arr, dep, seq = pat["arr"], pat["dep"], pat["stops"]
            trip = -1
            for i in range(start_pos, len(seq)):
                stop = seq[i]
                if trip >= 0 and arr[trip, i] < best[stop]:
                    best[stop] = arr[trip, i]
                    new_marked.add(stop)
                if prev[stop] < INF and (trip < 0 or prev[stop] <= dep[trip, i]):
                    cand = int(np.searchsorted(dep[:, i], prev[stop]))
                    if cand < len(dep) and (trip < 0 or cand < trip):
                        trip = cand
        marked = new_marked
        if not marked:
            break
    return best
