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
* :func:`sun_hours` - direct-sun duration per cell over one day (shadow
  sweep at a fixed interval).
* :func:`clear_sky_irradiance` - ASHRAE-style clear-sky beam + diffuse.
* :func:`daily_irradiation` - clear-sky global irradiation per cell over one
  day: shadow-aware beam + SVF-weighted isotropic diffuse.
* :func:`annual_irradiation` - clear-sky irradiation summed over a year from
  twelve representative average-day sweeps (Klein 1977; Duffie & Beckman).
* :func:`heat_risk_index` - normalized 0-100 urban heat island risk from
  built/green/water fractions and building height.
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
    if abs(dy) >= h or abs(dx) >= w:
        return out  # fully shifted off the grid
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
    # Scanning past the raster diagonal is pointless: every further shift
    # falls completely off the grid (also guards very low sun altitudes).
    reach = min(reach, math.hypot(*dsm.shape) * pixel_size)
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
# Daily sweeps: sun hours and clear-sky irradiation
# --------------------------------------------------------------------------- #
def _day_of_year(year, month, day):
    days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0):
        days[1] = 29
    return sum(days[:month - 1]) + day


def sun_hours(dsm, pixel_size, year, month, day, utc_offset, lat_deg, lon_deg,
              interval_min=30.0, max_search=None, progress=None, cancel=None):
    """Hours of direct sun per DSM cell over one day.

    Sweeps the day in ``interval_min`` steps; for every step with the sun
    above the horizon a shadow mask is cast and sunlit cells accumulate
    ``interval_min / 60`` hours. Returns ``(hours, daylight_hours)`` where
    ``daylight_hours`` is the site's total potential (unobstructed) sun.
    """
    dsm = np.asarray(dsm, dtype=np.float64)
    hours = np.zeros(dsm.shape, dtype=np.float64)
    daylight = 0.0
    step_h = interval_min / 60.0
    n_steps = max(1, int(round(24.0 * 60.0 / interval_min)))
    for i in range(n_steps):
        if cancel is not None and cancel():
            break
        local_h = (i + 0.5) * 24.0 / n_steps
        alt, az = sun_position(year, month, day, local_h - utc_offset,
                               lat_deg, lon_deg)
        if alt <= 0.0:
            continue
        daylight += step_h
        shadow = shadow_mask(dsm, alt, az, pixel_size, max_search=max_search)
        hours[~shadow] += step_h
        if progress is not None:
            progress((i + 1) / n_steps)
    hours[np.isnan(dsm)] = np.nan
    return hours, daylight


def clear_sky_irradiance(altitude_deg, day_of_year):
    """Clear-sky direct-horizontal and diffuse-horizontal irradiance (W/m2).

    ASHRAE-style clear-sky model (Masters 2004): beam ``DNI = A exp(-k/sin h)``
    with seasonally varying apparent extraterrestrial flux ``A``, optical
    depth ``k`` and isotropic diffuse ``DHI = C * DNI``. Good for screening,
    not for bankable yield studies.
    """
    if altitude_deg <= 0.0:
        return 0.0, 0.0
    n = day_of_year
    a = 1160.0 + 75.0 * math.sin(2.0 * math.pi * (n - 275) / 365.0)
    k = 0.174 + 0.035 * math.sin(2.0 * math.pi * (n - 100) / 365.0)
    c = 0.095 + 0.04 * math.sin(2.0 * math.pi * (n - 100) / 365.0)
    sin_h = math.sin(math.radians(altitude_deg))
    dni = a * math.exp(-k / sin_h)
    return dni * sin_h, c * dni


def daily_irradiation(dsm, pixel_size, year, month, day, utc_offset,
                      lat_deg, lon_deg, interval_min=30.0, svf=None,
                      max_search=None, progress=None, cancel=None):
    """Clear-sky global irradiation per cell over one day (kWh/m2).

    Per time step: sunlit cells receive the beam (direct-horizontal)
    component, every cell receives the isotropic diffuse component scaled
    by its sky view factor (``svf=None`` treats the sky as fully visible).
    Returns ``(kwh, flat_kwh)`` where ``flat_kwh`` is the unobstructed
    flat-ground total for the same day (useful as a reference).
    """
    dsm = np.asarray(dsm, dtype=np.float64)
    wh = np.zeros(dsm.shape, dtype=np.float64)
    flat_wh = 0.0
    doy = _day_of_year(year, month, day)
    step_h = interval_min / 60.0
    n_steps = max(1, int(round(24.0 * 60.0 / interval_min)))
    for i in range(n_steps):
        if cancel is not None and cancel():
            break
        local_h = (i + 0.5) * 24.0 / n_steps
        alt, az = sun_position(year, month, day, local_h - utc_offset,
                               lat_deg, lon_deg)
        if alt <= 0.0:
            continue
        beam_h, diff_h = clear_sky_irradiance(alt, doy)
        flat_wh += (beam_h + diff_h) * step_h
        shadow = shadow_mask(dsm, alt, az, pixel_size, max_search=max_search)
        contrib = np.where(shadow, 0.0, beam_h)
        if svf is not None:
            contrib = contrib + diff_h * svf
        else:
            contrib = contrib + diff_h
        wh += contrib * step_h
        if progress is not None:
            progress((i + 1) / n_steps)
    wh[np.isnan(dsm)] = np.nan
    return wh / 1000.0, flat_wh / 1000.0


# --------------------------------------------------------------------------- #
# Annual aggregation: monthly representative days summed to a year
# --------------------------------------------------------------------------- #
MONTH_NAMES = ("January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November",
               "December")

# Recommended average day of each month (Klein 1977; Duffie & Beckman,
# "Solar Engineering of Thermal Processes", Table 1.6.1): the day-of-month
# whose solar declination is closest to the monthly mean, so a single sweep
# of it stands in for the month's mean daily irradiation.
_AVG_MONTH_DAY = (17, 16, 16, 15, 15, 11, 17, 16, 15, 15, 14, 10)


def _days_in_month(year, month):
    days = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    if month == 2 and year % 4 == 0 and (year % 100 != 0 or year % 400 == 0):
        return 29
    return days[month - 1]


def annual_irradiation(dsm, pixel_size, year, utc_offset, lat_deg, lon_deg,
                       interval_min=60.0, svf=None, months=None,
                       max_search=None, keep_monthly=True,
                       progress=None, cancel=None):
    """Clear-sky global solar irradiation summed over a year (kWh/m2/yr).

    For each month one representative "average day" (Klein 1977; Duffie &
    Beckman) is swept with :func:`daily_irradiation` and scaled by the number
    of days in that month; the monthly totals are summed to the annual map.
    This is the standard monthly-average method: 12 day-sweeps stand in for
    365, keeping a year-long clear-sky screening tractable.

    Returns a dict with:
      * ``annual``       - kWh/m2/yr per cell (NaN where the DSM is NaN);
      * ``months``       - the month numbers actually swept (1-12);
      * ``month_mean``   - mean monthly total over valid cells, per month;
      * ``flat_monthly`` - unobstructed flat-ground monthly total, per month;
      * ``flat_annual``  - their sum (flat-ground annual reference);
      * ``monthly``      - list of per-month kWh/m2 maps (``None`` if
        ``keep_monthly`` is False - the means are still returned).
    """
    dsm = np.asarray(dsm, dtype=np.float64)
    if months is None:
        months = list(range(1, 13))
    valid = ~np.isnan(dsm)
    has_valid = bool(valid.any())
    annual = np.zeros(dsm.shape, dtype=np.float64)
    monthly = [] if keep_monthly else None
    month_mean, flat_monthly, swept = [], [], []
    n = max(1, len(months))
    for idx, m in enumerate(months):
        if cancel is not None and cancel():
            break
        rep_day = _AVG_MONTH_DAY[m - 1]
        ndays = _days_in_month(year, m)

        def sub(frac, _i=idx, _n=n):
            if progress is not None:
                progress((_i + frac) / _n)

        day_kwh, flat_day = daily_irradiation(
            dsm, pixel_size, year, m, rep_day, utc_offset, lat_deg, lon_deg,
            interval_min=interval_min, svf=svf, max_search=max_search,
            progress=sub, cancel=cancel)
        month_kwh = day_kwh * ndays                     # NaN cells stay NaN
        annual += np.where(valid, month_kwh, 0.0)
        flat_monthly.append(flat_day * ndays)
        month_mean.append(float(month_kwh[valid].mean()) if has_valid else 0.0)
        swept.append(m)
        if keep_monthly:
            monthly.append(month_kwh)
    annual[~valid] = np.nan
    return {
        "annual": annual,
        "months": swept,
        "month_mean": month_mean,
        "flat_monthly": flat_monthly,
        "flat_annual": float(sum(flat_monthly)),
        "monthly": monthly,
    }


# --------------------------------------------------------------------------- #
# Urban heat island risk (vector grid composite)
# --------------------------------------------------------------------------- #
def heat_risk_index(built_frac, green_frac, water_frac, mean_height,
                    h_ref=20.0, w_built=0.4, w_height=0.2,
                    w_green=0.3, w_water=0.1):
    """Normalized 0-100 urban heat island risk score (vectorized).

    ``raw = w_built*built + w_height*min(h/h_ref, 1) - w_green*green -
    w_water*water`` mapped linearly so the attainable extremes land on 0
    and 100: fully built at reference height -> 100; fully covered by the
    stronger coolant (green and water covers are disjoint, so the minimum
    is ``-max(w_green, w_water)``) -> 0. The mapping is fixed by the
    weights - NOT by the data - so scores stay comparable between runs
    and study areas.
    """
    built = np.clip(np.asarray(built_frac, dtype=np.float64), 0.0, 1.0)
    green = np.clip(np.asarray(green_frac, dtype=np.float64), 0.0, 1.0)
    water = np.clip(np.asarray(water_frac, dtype=np.float64), 0.0, 1.0)
    h = np.asarray(mean_height, dtype=np.float64)
    h_norm = np.clip(h / max(h_ref, 1e-9), 0.0, 1.0)
    raw = w_built * built + w_height * h_norm - w_green * green - w_water * water
    lo = -max(w_green, w_water)
    hi = w_built + w_height
    span = (hi - lo) if hi > lo else 1.0
    return np.clip(100.0 * (raw - lo) / span, 0.0, 100.0)


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
