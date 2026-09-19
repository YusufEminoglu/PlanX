# -*- coding: utf-8 -*-
"""Ground-motion prediction, after Akkar, Sandikkaya & Bommer (2014).

Source of the model: Akkar, S., Sandikkaya, M. A. & Bommer, J. J. (2014),
"Empirical ground-motion models for point- and extended-source crustal
earthquake scenarios in Europe and the Middle East", Bulletin of Earthquake
Engineering 12(1), 359-387, DOI 10.1007/s10518-013-9461-4. It is one of the
four models in the logic tree of Turkey's 2018 national seismic hazard map.

The coefficients live in engine/gmpe_data.py, which records where they came
from. Nothing in this module is recalled: the functional form, the coefficient
names and the applicability ranges are the paper's, and the numbers are the
authors' own.

Three properties of this model are load-bearing and are easy to get wrong:

1. The site term is nonlinear and is conditioned on the ROCK peak ground
   acceleration at the same site, so the rock motion is computed first and the
   site term applied second. This module does that in one pass on purpose.

2. The site term is NOT monotone in Vs30 at short periods. Measured at
   Mw 7, R = 20 km, PGA peaks near Vs30 = 400 m/s and falls away on both
   sides, because the nonlinear term suppresses short-period motion on soft
   soil. That reversal is the model working, not a defect, and a test asserts
   it explicitly so that a future change cannot quietly flatten it.

3. Vs30 above 1000 m/s is capped by the model itself, so 1000 and 1200 m/s
   give identical numbers. predict() reports whether the cap applied rather
   than letting a user believe they got a 1200 m/s answer.

Distance metrics: the paper publishes three coefficient sets - Joyner-Boore
(RJB), epicentral (Repi) and hypocentral (Rhypo) - and no others. There is no
Rrup model, so an extended-rupture scenario is handled through RJB, which for
the near-vertical crustal ruptures this model was built for is the horizontal
distance to the fault trace.
"""
from __future__ import annotations

import numpy as np

from . import gmpe_data

# ---------------------------------------------------------------------- #
# Vocabularies
# ---------------------------------------------------------------------- #

#: Scenario kinds the distance helpers understand.
SCENARIOS = ("point", "fault")

#: The three distance metrics the paper publishes coefficients for.
DISTANCE_METRICS = ("RJB", "Repi", "Rhypo")

METRIC_LABELS = {
    "RJB": "Joyner-Boore - closest horizontal distance to the fault",
    "Repi": "Epicentral - horizontal distance to the epicentre",
    "Rhypo": "Hypocentral - straight-line distance to the focus",
}

_RAW_TABLE = {
    "RJB": gmpe_data.DIST_JB,
    "Repi": gmpe_data.DIST_EPI,
    "Rhypo": gmpe_data.DIST_HYP,
}

#: The published tables as float64 arrays, built once on first use.
_TABLE = {}

#: Which metrics are defined for which scenario. An extended rupture has no
#: single epicentre or hypocentre, so only RJB is offered there - naming one
#: point of a 100 km rupture as "the" epicentre would be a fabrication the
#: output could not show.
METRICS_BY_SCENARIO = {
    "point": ("RJB", "Repi", "Rhypo"),
    "fault": ("RJB",),
}

MECHANISMS = ("SS", "NS", "RS")

MECHANISM_LABELS = {
    "SS": "Strike-slip",
    "NS": "Normal",
    "RS": "Reverse",
}

#: The model's own published validity ranges, as declared by the paper.
#: Outside them the run is reported, never silently extrapolated.
APPLICABILITY = {
    "magnitude": (4.0, 8.0),
    "distance_km": (0.0, 200.0),
    "vs30": (150.0, 1200.0),
}

#: Shallow-crustal convention. The paper has no depth term, so this is not a
#: model range; it is the depth below which "crustal earthquake" stops being
#: an honest description of the scenario. Reported as a caveat, not a refusal.
SHALLOW_DEPTH_KM = 30.0

V_REF = float(gmpe_data.CONSTANTS["v_ref"])
SITE_VS30_CAP = float(gmpe_data.CONSTANTS["v_con"])
M_REF = float(gmpe_data.CONSTANTS["c_1"])

PERIODS = gmpe_data.PERIODS
INDEX_PGA = gmpe_data.INDEX_PGA
INDEX_PGV = gmpe_data.INDEX_PGV
N_ROWS = gmpe_data.N_ROWS


# ---------------------------------------------------------------------- #
# Coefficients
# ---------------------------------------------------------------------- #

def table(metric):
    """The coefficient table for a distance metric, as float64 arrays."""
    key = str(metric)
    if key in _TABLE:
        return _TABLE[key]
    try:
        raw = _RAW_TABLE[key]
    except KeyError:
        raise ValueError(
            f"Unknown distance metric {metric!r}; the model publishes "
            f"{', '.join(DISTANCE_METRICS)}."
        ) from None
    _TABLE[key] = {name: np.asarray(values, dtype=np.float64)
                   for name, values in raw.items()}
    return _TABLE[key]


def check_metric(metric, scenario):
    """Return a complaint if ``metric`` is not defined for ``scenario``."""
    metric = str(metric)
    if metric not in DISTANCE_METRICS:
        return (f"Unknown distance metric {metric!r}. The model publishes "
                f"{', '.join(DISTANCE_METRICS)}.")
    allowed = METRICS_BY_SCENARIO.get(str(scenario), ())
    if metric not in allowed:
        return (f"{metric} is not defined for a {scenario} scenario. An "
                f"extended fault trace has no single epicentre or hypocentre, "
                f"so only {', '.join(allowed)} can be used there. Switch the "
                f"distance metric, or model the event as a point source with "
                f"an explicit depth.")
    return None


def period_index(period):
    """Row index of a published spectral period, or ``None``.

    The model is tabulated at a fixed set of periods and is not
    interpolated here: writing a number the paper never tabulated would put
    a value in the output that no source supports. Callers report the
    published set instead.
    """
    value = float(period)
    for offset, published in enumerate(PERIODS):
        if abs(value - published) <= 1e-9:
            return 2 + offset
    return None


def nearest_periods(period, count=3):
    """The published periods closest to ``period``, for an error message."""
    value = float(period)
    ordered = sorted(PERIODS, key=lambda p: abs(p - value))
    return ordered[:count]


def parse_periods(text):
    """The published spectral periods named in a comma-separated string.

    Returns an ascending list of periods. Empty text means "none", which is
    not an error - PGA and PGV are computed either way. A period the model
    does not tabulate is refused, with the nearest published values named,
    because interpolating one would put a number in the output that no
    source supports.
    """
    wanted = []
    for chunk in str(text).replace(";", ",").split(","):
        token = chunk.strip()
        if not token:
            continue
        try:
            value = float(token)
        except ValueError:
            raise ValueError(
                f"{token!r} is not a number. Give spectral periods in seconds, "
                f"separated by commas - for example 0.3, 1.0."
            ) from None
        if period_index(value) is None:
            near = ", ".join(f"{p:g}" for p in sorted(nearest_periods(value, 3)))
            raise ValueError(
                f"The model is not tabulated at T = {value:g} s, and this tool "
                f"does not interpolate: an interpolated value would be one no "
                f"source supports. Nearest published periods: {near} s."
            )
        if value not in wanted:
            wanted.append(value)
    return sorted(wanted)


# ---------------------------------------------------------------------- #
# The model
# ---------------------------------------------------------------------- #

def _ln_median(metric, magnitude, distance_km, vs30, mechanism):
    """ln of the median intensity measure, and the rock PGA it was built on.

    Returns ``(ln_median, pga_rock)`` shaped ``(N, N_ROWS)`` and ``(N,)``.
    Magnitude, distance, Vs30 and mechanism broadcast over sites.
    """
    t = table(metric)
    k = gmpe_data.CONSTANTS

    mag = np.asarray(magnitude, dtype=np.float64).reshape(-1, 1)
    dist = np.asarray(distance_km, dtype=np.float64).reshape(-1, 1)
    vs = np.asarray(vs30, dtype=np.float64).reshape(-1, 1)
    mech = np.asarray(mechanism).reshape(-1)
    if mech.shape[0] != mag.shape[0]:
        raise ValueError("mechanism must have one entry per site")

    # Reference (rock) motion. The magnitude term changes coefficient at the
    # reference magnitude: a2 below it, a7 above, which is the paper's
    # saturation behaviour above Mw 6.75.
    ln = (t["a_1"]
          + t["a_3"] * (8.5 - mag) ** 2
          + (t["a_4"] + k["a_5"] * (mag - M_REF))
          * np.log(np.sqrt(dist ** 2 + k["a_6"] ** 2)))
    slope = np.where(mag <= M_REF, k["a_2"], k["a_7"])
    ln = ln + slope * (mag - M_REF)

    # Strike-slip is the reference the other two mechanisms are offset from.
    # The masks are reshaped to (N, 1) deliberately: a (N,) mask against a
    # (N_ROWS,) coefficient broadcasts to (N, N_ROWS) only when the site axis
    # is the first one, and getting that wrong is silent - the arithmetic
    # still runs and only some of the values move.
    ln = ln + (mech == "NS")[:, None] * t["a_8"] + (mech == "RS")[:, None] * t["a_9"]

    pga_rock = np.exp(ln[:, INDEX_PGA])

    # Nonlinear site term, conditioned on that rock PGA.
    ratio = vs / V_REF
    site_soft = (t["b_1"] * np.log(ratio)
                 + t["b_2"] * np.log((pga_rock[:, None] + k["c"] * ratio ** k["n"])
                                     / ((pga_rock[:, None] + k["c"]) * ratio ** k["n"])))
    site_hard = t["b_1"] * np.log(np.minimum(vs, SITE_VS30_CAP) / V_REF)
    ln = ln + np.where(vs <= V_REF, site_soft, site_hard)

    return ln, pga_rock


def predict(metric, magnitude, distance_km, vs30, mechanism, epsilon=0.0):
    """Median intensity measures at each site.

    ``epsilon`` shifts every measure by that many total standard deviations,
    which is how a scenario is pinned to a hazard level rather than to the
    median. The default of 0 reports the median.

    Returns a dict of ``(N, ...)`` arrays: ``ln_median``, ``im`` (the
    dispersion-adjusted intensity measure), ``pga_g``, ``pgv_cms``, ``sa_g``,
    ``periods``, ``sigma_within``, ``sigma_between``, ``sigma_total``,
    ``rock_pga_g`` and ``vs30_capped``.
    """
    ln, pga_rock = _ln_median(metric, magnitude, distance_km, vs30, mechanism)
    t = table(metric)
    shift = float(epsilon) * t["sd_total"]
    im = np.exp(ln + shift)
    vs = np.asarray(vs30, dtype=np.float64).reshape(-1)
    return {
        "ln_median": ln,
        "im": im,
        "pga_g": im[:, INDEX_PGA],
        "pgv_cms": im[:, INDEX_PGV],
        "sa_g": im[:, 2:],
        "periods": PERIODS,
        "sigma_within": t["sd_within"],
        "sigma_between": t["sd_between"],
        "sigma_total": t["sd_total"],
        "rock_pga_g": pga_rock,
        "vs30_capped": vs > SITE_VS30_CAP,
    }


def sigma_invariant_worst(metric):
    """Worst |sigma_total - sqrt(between^2 + within^2)| in a table.

    The published dispersion components satisfy that identity up to the
    four-decimal rounding of the coefficients themselves, so this is a
    transcription check: it catches a mis-typed digit without needing any
    external reference.
    """
    t = table(metric)
    total = np.sqrt(t["sd_between"] ** 2 + t["sd_within"] ** 2)
    return float(np.max(np.abs(total - t["sd_total"])))


# ---------------------------------------------------------------------- #
# Applicability
# ---------------------------------------------------------------------- #

#: Compact codes for the ways a receiver can leave the published envelope.
#: They are written into the output row so an out-of-range result is visible
#: where it is used, not only in a log line the user may never open.
FLAG_CODES = ("mag_below", "mag_above", "dist_above",
              "vs30_below", "vs30_above", "depth_above")

FLAG_LABELS = {
    "mag_below": "magnitude below the model's range",
    "mag_above": "magnitude above the model's range",
    "dist_above": "distance beyond the model's range",
    "vs30_below": "Vs30 below the model's range",
    "vs30_above": "Vs30 above the model's range",
    "depth_above": "deeper than the shallow-crustal convention",
}


def envelope_flags(magnitude, distance_km, vs30, depth_km=None):
    """Per-receiver codes for every published range the scenario leaves.

    Returns a list with one list of codes per receiver; an empty inner list
    means that receiver is inside the envelope. This is the primitive;
    ``envelope_report`` summarises the same codes for the log, so the two
    cannot disagree about what is out of range.
    """
    arrays = [np.asarray(values, dtype=np.float64).reshape(-1)
              for values in (magnitude, distance_km, vs30)]
    size = max(values.size for values in arrays)
    if size == 0:
        return []
    mag, dist, vs = [values if values.size == size
                     else np.full(size, float(values[0])) for values in arrays]

    flags = []
    for index in range(size):
        found = []
        if mag[index] < APPLICABILITY["magnitude"][0]:
            found.append("mag_below")
        if mag[index] > APPLICABILITY["magnitude"][1]:
            found.append("mag_above")
        if dist[index] > APPLICABILITY["distance_km"][1]:
            found.append("dist_above")
        if vs[index] < APPLICABILITY["vs30"][0]:
            found.append("vs30_below")
        if vs[index] > APPLICABILITY["vs30"][1]:
            found.append("vs30_above")
        if depth_km is not None and float(depth_km) > SHALLOW_DEPTH_KM:
            found.append("depth_above")
        flags.append(found)
    return flags


def envelope_report(magnitude, distance_km, vs30, depth_km=None):
    """Every way the scenario falls outside the published ranges, as prose.

    Returns a list of sentences. An empty list means the run is inside the
    envelope. The caller decides whether a violation is fatal; this function
    only reports, so an out-of-range probe is still computable and can be
    shown to be out of range rather than hidden.
    """
    arrays = [np.asarray(values, dtype=np.float64).reshape(-1)
              for values in (magnitude, distance_km, vs30)]
    flags = envelope_flags(magnitude, distance_km, vs30, depth_km)
    units = {"magnitude": "Mw", "distance_km": "km", "vs30": "m/s"}
    bounds = {"mag": "magnitude", "dist": "distance_km", "vs30": "vs30"}

    notes = []
    total = len(flags)
    for code in ("mag_below", "mag_above", "dist_above",
                 "vs30_below", "vs30_above"):
        inside = [index for index, found in enumerate(flags) if code in found]
        if not inside:
            continue
        key = bounds[code.rsplit("_", 1)[0]]
        low, high = APPLICABILITY[key]
        hit = arrays[("magnitude", "distance_km", "vs30").index(key)][inside]
        label = {"magnitude": "Magnitude", "distance_km": "Distance",
                 "vs30": "Vs30"}[key]
        plural = "" if total == 1 else "s"
        notes.append(
            f"{label}: {len(inside)} of {total} receiver{plural} outside the model's "
            f"published range {low:g}-{high:g} {units[key]} "
            f"(those span {float(np.min(hit)):.4g} to {float(np.max(hit)):.4g} "
            f"{units[key]})."
        )
    if total and "depth_above" in flags[0]:
        notes.append(
            f"Depth: {float(depth_km):g} km is deeper than the {SHALLOW_DEPTH_KM:g} km "
            f"shallow-crustal convention this model is used for. The model has no "
            f"depth term at all."
        )
    return notes


# ---------------------------------------------------------------------- #
# Distances
# ---------------------------------------------------------------------- #

def point_distances(site_xy, epicentre_xy, units_per_km, depth_km=10.0):
    """RJB, Repi and Rhypo for a point source, in kilometres.

    A point source has no rupture surface, so its Joyner-Boore and epicentral
    distances are the same horizontal distance; the hypocentral distance is
    that plus the focal depth.

    ``units_per_km`` is how many of the coordinate system's linear units make
    one kilometre - 1000.0 for a metre-based projection. It has no default on
    purpose: a distance silently off by a factor of 1000 still returns a
    number, still renders, and is wrong everywhere, so the caller is made to
    state the unit rather than inherit one.
    """
    site = np.asarray(site_xy, dtype=np.float64).reshape(-1, 2)
    epi = np.asarray(epicentre_xy, dtype=np.float64).reshape(2)
    horizontal = (np.hypot(site[:, 0] - epi[0], site[:, 1] - epi[1])
                  / float(units_per_km))
    return {
        "RJB": horizontal,
        "Repi": horizontal,
        "Rhypo": np.sqrt(horizontal ** 2 + float(depth_km) ** 2),
    }


def _distance_to_segment(site, start, end):
    ab = end - start
    denom = float(ab[0] * ab[0] + ab[1] * ab[1])
    if denom <= 0.0:
        return np.hypot(site[:, 0] - start[0], site[:, 1] - start[1])
    t = np.clip(((site - start) @ ab) / denom, 0.0, 1.0)
    proj = start + t[:, None] * ab
    return np.hypot(site[:, 0] - proj[:, 0], site[:, 1] - proj[:, 1])


def trace_distances(site_xy, polylines, units_per_km):
    """RJB for an extended rupture, as the distance to its fault trace, in km.

    ASB2014 is a model for shallow crustal earthquakes, whose ruptures are
    near-vertical, and for those the surface projection of the rupture IS the
    trace - so the distance to the trace is the Joyner-Boore distance. On a
    shallow-dipping thrust the projection extends beyond the trace and this
    would overstate RJB; the help text says so.

    ``units_per_km`` is the caller's, for the reason given on
    ``point_distances``. The trace must be in the same coordinate system as
    the sites.
    """
    site = np.asarray(site_xy, dtype=np.float64).reshape(-1, 2)
    best = None
    for line in polylines:
        points = np.asarray(line, dtype=np.float64)
        for index in range(len(points) - 1):
            distance = _distance_to_segment(site, points[index], points[index + 1])
            best = distance if best is None else np.minimum(best, distance)
    if best is None:
        raise ValueError("No fault trace geometry to measure from.")
    return {"RJB": best / float(units_per_km)}


def distances(scenario, site_xy, units_per_km, **kwargs):
    """Distance in kilometres for every published metric, for this scenario.

    ``units_per_km`` is required and has no default - see ``point_distances``.
    """
    if str(scenario) == "point":
        return point_distances(site_xy, kwargs["epicentre_xy"], units_per_km,
                               kwargs.get("depth_km", 10.0))
    if str(scenario) == "fault":
        return trace_distances(site_xy, kwargs["polylines"], units_per_km)
    raise ValueError(f"Unknown scenario {scenario!r}; expected one of {', '.join(SCENARIOS)}.")
