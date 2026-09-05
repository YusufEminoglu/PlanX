# -*- coding: utf-8 -*-
"""Small, dependency-free EPW climate reader for microclimate tools."""
from __future__ import annotations

import csv
import math


def read_epw(path: str) -> dict:
    """Read hourly EPW weather and return monthly screening summaries."""
    monthly = [{"ghi_kwh_m2": 0.0, "temperatures": [], "winds": []}
               for _ in range(12)]
    rows = 0
    with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        for _ in range(8):
            next(reader, None)
        for row in reader:
            if len(row) < 23:
                continue
            try:
                month = int(row[1])
                temperature = float(row[6])
                ghi = float(row[13])
                wind = float(row[21])
            except (TypeError, ValueError):
                continue
            if not 1 <= month <= 12:
                continue
            item = monthly[month - 1]
            if math.isfinite(ghi) and 0.0 <= ghi < 9999.0:
                item["ghi_kwh_m2"] += ghi / 1000.0
            if math.isfinite(temperature) and temperature < 99.0:
                item["temperatures"].append(temperature)
            if math.isfinite(wind) and wind < 99.0:
                item["winds"].append(wind)
            rows += 1
    if rows < 24:
        raise ValueError("EPW contains fewer than 24 usable hourly records.")
    return {
        "hours": rows,
        "monthly_ghi": [item["ghi_kwh_m2"] for item in monthly],
        "monthly_temperature": [
            sum(item["temperatures"]) / len(item["temperatures"])
            if item["temperatures"] else float("nan") for item in monthly],
        "monthly_wind": [
            sum(item["winds"]) / len(item["winds"])
            if item["winds"] else float("nan") for item in monthly],
    }


def monthly_solar_factors(epw_summary, clear_sky_monthly) -> list[float]:
    """Measured GHI / clear-sky horizontal irradiation per month."""
    observed = epw_summary["monthly_ghi"]
    if len(observed) != len(clear_sky_monthly):
        raise ValueError("EPW and modeled monthly series must have equal length.")
    return [max(0.0, float(obs)) / max(float(clear), 1e-9)
            for obs, clear in zip(observed, clear_sky_monthly)]
