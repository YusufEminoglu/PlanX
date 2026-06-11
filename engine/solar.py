# -*- coding: utf-8 -*-
"""Solar / microclimate kernels (UMEP-lite).

Pure NumPy, no qgis imports:

* :func:`sun_position` - NOAA simplified solar position (accuracy well under
  0.5 degrees for 1900-2100), enough for urban shadow studies.
* :func:`shadow_mask` - DSM shadow casting by iterative array shifting
  (the classic UMEP / Ratti & Richens approach).
* :func:`sky_view_factor` - hemispheric SVF from horizon scans:
  ``SVF = 1 - mean(sin^2(horizon))`` over equally spaced azimuths
  (flat plane -> 1, foot of an infinite wall -> 0.5).
"""
from __future__ import annotations

import math

import numpy as np


# --------------------------------------------------------------------------- #
# Sun position (NOAA simplified)
# --------------------------------------------------------------------------- #
def _julian_day(year, month, day, hour_utc):
    if month <= 2:
        year -= 1
        month += 12
    a = year // 100
    b = 2 - a + a // 4
    jd = (math.floor(365.25 * (year + 4716)) + math.floor(30.6001 * (month + 1))
          + day + b - 1524.5)
    return jd + hour_utc / 24.0


def sun_position(year, month, day, hour_utc, lat_deg, lon_deg):
    """Solar altitude and azimuth (degrees) for a UTC time and WGS84 lonlat.

    Azimuth is compass convention: 0 = North, 90 = East, 180 = South.
    """
    jd = _julian_day(year, month, day, hour_utc)
    t = (jd - 2451545.0) / 36525.0

    mean_long = (280.46646 + t * (36000.76983 + 0.0003032 * t)) % 360.0
    mean_anom = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    ecc = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    m = math.radians(mean_anom)
    eq_center = (math.sin(m) * (1.914602 - t * (0.004817 + 0.000014 * t))
                 + math.sin(2 * m) * (0.019993 - 0.000101 * t)
                 + math.sin(3 * m) * 0.000289)
    true_long = mean_long + eq_center
    omega = 125.04 - 1934.136 * t
    app_long = true_long - 0.00569 - 0.00478 * math.sin(math.radians(omega))

    obliq = (23.0 + (26.0 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60.0) / 60.0)
    obliq_corr = obliq + 0.00256 * math.cos(math.radians(omega))

    decl = math.degrees(math.asin(
        math.sin(math.radians(obliq_corr)) * math.sin(math.radians(app_long))))

    var_y = math.tan(math.radians(obliq_corr / 2.0)) ** 2
    ml = math.radians(mean_long)
    eq_time = 4.0 * math.degrees(
        var_y * math.sin(2 * ml)
        - 2.0 * ecc * math.sin(m)
        + 4.0 * ecc * var_y * math.sin(m) * math.cos(2 * ml)
        - 0.5 * var_y * var_y * math.sin(4 * ml)
        - 1.25 * ecc * ecc * math.sin(2 * m))

    true_solar_min = (hour_utc * 60.0 + eq_time + 4.0 * lon_deg) % 1440.0
    ha = true_solar_min / 4.0 - 180.0
    if ha < -180.0:
        ha += 360.0

    lat = math.radians(lat_deg)
    d = math.radians(decl)
    h = math.radians(ha)
    cos_zen = math.sin(lat) * math.sin(d) + math.cos(lat) * math.cos(d) * math.cos(h)
    cos_zen = max(-1.0, min(1.0, cos_zen))
    zenith = math.degrees(math.acos(cos_zen))
    altitude = 90.0 - zenith

    denom = math.cos(lat) * math.sin(math.radians(zenith))
    if abs(denom) < 1e-12:
        azimuth = 180.0
    else:
        cos_az = (math.sin(lat) * cos_zen - math.sin(d)) / denom
        cos_az = max(-1.0, min(1.0, cos_az))
        az = math.degrees(math.acos(cos_az))
        azimuth = (az + 180.0) % 360.0 if ha > 0 else (180.0 - az) % 360.0
    return altitude, azimuth


# --------------------------------------------------------------------------- #
# Raster helpers
# --------------------------------------------------------------------------- #
def _shift(arr, dy, dx, fill):
    """Shift a 2D array by integer (dy, dx); exposed edges get ``fill``."""
    out = np.full_like(arr, fill)
    h, w = arr.shape
    ys = slice(max(0, dy), min(h, h + dy))
    xs = slice(max(0, dx), min(w, w + dx))
    ys_src = slice(max(0, -dy), min(h, h - dy))
    xs_src = slice(max(0, -dx), min(w, w - dx))
    out[ys, xs] = arr[ys_src, xs_src]
    return out


def shadow_mask(dsm, sun_altitude_deg, sun_azimuth_deg, pixel_size,
                max_search=None, progress=None):
    """Boolean array: True where the DSM cell is in cast shadow.

    Iteratively shifts the DSM toward the sun, lowering it by
    ``step * tan(altitude)``; a cell is shadowed when any shifted surface
    stands above it. ``max_search`` (map units) caps the scan distance and
    defaults to what the DSM relief can possibly cast.
    """
    if sun_altitude_deg <= 0.0:
        return np.ones(dsm.shape, dtype=bool)  # sun below horizon
    dsm = np.asarray(dsm, dtype=np.float64)
    tan_alt = math.tan(math.radians(sun_altitude_deg))
    relief = float(np.nanmax(dsm) - np.nanmin(dsm))
    if relief <= 0:
        return np.zeros(dsm.shape, dtype=bool)
    reach = relief / tan_alt
    if max_search is not None:
        reach = min(reach, float(max_search))
    steps = max(1, int(math.ceil(reach / pixel_size)))

    # Unit vector pointing TOWARD the sun: compass azimuth A -> (east, north)
    # = (sin A, cos A). Rows grow southward, so drow = -i*uy.
    az = math.radians(sun_azimuth_deg)
    ux = math.sin(az)
    uy = math.cos(az)
    base = np.where(np.isnan(dsm), -np.inf, dsm)
    highest = np.full(dsm.shape, -np.inf)
    for i in range(1, steps + 1):
        dcol = int(round(i * ux))
        drow = -int(round(i * uy))
        if dcol == 0 and drow == 0:
            continue
        dist = math.hypot(dcol, drow) * pixel_size
        # out[r, c] = base[r + drow, c + dcol]  (terrain toward the sun)
        shifted = _shift(base, -drow, -dcol, -np.inf) - dist * tan_alt
        np.maximum(highest, shifted, out=highest)
        if progress is not None and i % 32 == 0:
            progress(i / steps)
    return highest > base + 0.01


def sky_view_factor(dsm, pixel_size, directions=16, max_radius=100.0,
                    progress=None):
    """SVF in [0, 1] per cell from ``directions`` horizon scans."""
    dsm = np.asarray(dsm, dtype=np.float64)
    base = np.where(np.isnan(dsm), -np.inf, dsm)
    steps = max(1, int(math.ceil(max_radius / pixel_size)))
    sin2_sum = np.zeros(dsm.shape, dtype=np.float64)
    for d in range(directions):
        az = 2.0 * math.pi * d / directions
        ux, uy = math.sin(az), math.cos(az)
        max_tan = np.zeros(dsm.shape, dtype=np.float64)
        seen = set()
        for i in range(1, steps + 1):
            dcol = int(round(i * ux))
            drow = -int(round(i * uy))
            if (dcol, drow) in seen or (dcol == 0 and drow == 0):
                continue
            seen.add((dcol, drow))
            dist = math.hypot(dcol, drow) * pixel_size
            shifted = _shift(base, -drow, -dcol, -np.inf)
            with np.errstate(invalid="ignore"):
                tan_h = (shifted - base) / dist
            np.maximum(max_tan, tan_h, out=max_tan)
        # sin^2(atan(t)) == t^2 / (1 + t^2)
        t2 = max_tan * max_tan
        sin2_sum += t2 / (1.0 + t2)
        if progress is not None:
            progress((d + 1) / directions)
    svf = 1.0 - sin2_sum / directions
    svf[np.isnan(dsm)] = np.nan
    return np.clip(svf, 0.0, 1.0)


# --------------------------------------------------------------------------- #
# Frontal area (vector, per building)
# --------------------------------------------------------------------------- #
def projected_width(ring, wind_azimuth_deg):
    """Width of a footprint ring projected perpendicular to the wind.

    The frontal area of a building is ``projected_width * height``.
    """
    r = np.asarray(ring, dtype=np.float64)
    az = math.radians(wind_azimuth_deg)
    # Perpendicular axis to the wind direction (wind blows FROM azimuth).
    px, py = math.cos(az), -math.sin(az)
    proj = r[:, 0] * px + r[:, 1] * py
    return float(proj.max() - proj.min())
