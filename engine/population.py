# -*- coding: utf-8 -*-
"""Population projection and housing arithmetic.

Pure NumPy. Three small kernels of the demographic side of plan-making:

* :func:`cohort_projection` - the cohort-component method as a Leslie
  matrix (Leslie 1945): age groups of equal width, per-step survival into
  the next group, per-capita fertility contributing births to the first
  group, optional net migration added after each step. Single-sex (total
  population) - the standard screening simplification; run twice with
  sex-specific rates for a two-sex projection.
* :func:`housing_needs` - the standard needs identity: future households
  grossed up by a vacancy allowance, minus the surviving stock, plus
  replacement losses and the current backlog.
* :func:`residential_capacity` - zoning arithmetic per parcel: buildable
  floorspace from FAR minus what stands, converted to dwelling units.
"""
from __future__ import annotations

import numpy as np


def leslie_matrix(survival, fertility):
    """Build the (k, k) Leslie matrix.

    ``survival[a]`` is the share of group ``a`` surviving into group
    ``a+1`` per step; the last entry keeps the open-ended final group in
    place (survival on the diagonal). ``fertility[a]`` is births per
    person of group ``a`` per step (they land in group 0).
    """
    s = np.asarray(survival, dtype=float).ravel()
    f = np.asarray(fertility, dtype=float).ravel()
    if s.shape != f.shape or s.size == 0:
        raise ValueError("survival and fertility must share one length")
    k = s.size
    m = np.zeros((k, k))
    m[0, :] = f
    for a in range(k - 1):
        m[a + 1, a] = s[a]
    m[k - 1, k - 1] += s[k - 1]
    return m


def cohort_projection(pop, survival, fertility, migration=None, steps=1):
    """Project ``pop`` forward ``steps`` steps. Returns (steps+1, k).

    Row 0 is the start population; each further row is one step (of the
    age-group width, e.g. 5 years). ``migration`` (per step, per group,
    may be negative) is added after the survival/birth update; results
    are floored at zero.
    """
    p = np.asarray(pop, dtype=float).ravel()
    m = leslie_matrix(survival, fertility)
    if p.size != m.shape[0]:
        raise ValueError("pop length must match the rate vectors")
    mig = None
    if migration is not None:
        mig = np.asarray(migration, dtype=float).ravel()
        if mig.shape != p.shape:
            raise ValueError("migration length must match pop")
    out = np.empty((int(steps) + 1, p.size))
    out[0] = p
    for i in range(1, int(steps) + 1):
        p = m @ p
        if mig is not None:
            p = p + mig
        p = np.clip(p, 0.0, None)
        out[i] = p
    return out


def housing_needs(pop_future, household_size, existing_dwellings,
                  vacancy_target=0.05, replacement_units=0.0,
                  backlog_units=0.0):
    """Dwelling units to add by the horizon (negative = surplus).

    ``target stock = households x (1 + vacancy)``; the need is the target
    minus the existing stock, plus units lost to replacement/demolition
    over the period and the current backlog (overcrowded / unfit units to
    absorb). Returns a dict with every intermediate for reporting.
    """
    if household_size <= 0:
        raise ValueError("household size must be positive")
    households = float(pop_future) / float(household_size)
    target = households * (1.0 + max(0.0, float(vacancy_target)))
    need = (target - float(existing_dwellings)
            + max(0.0, float(replacement_units))
            + max(0.0, float(backlog_units)))
    return {
        "households": households,
        "target_stock": target,
        "existing": float(existing_dwellings),
        "replacement": float(replacement_units),
        "backlog": float(backlog_units),
        "need": need,
    }


def residential_capacity(area, far, existing_floor=None, unit_size=90.0,
                         efficiency=0.85):
    """Per-parcel dwelling capacity from zoning.

    ``buildable = max(0, area x FAR - existing floorspace)``;
    ``units = floor(buildable x efficiency / unit size)``. Arrays in,
    arrays out: returns (buildable_floor, units).
    """
    area = np.asarray(area, dtype=float).ravel()
    far = np.asarray(far, dtype=float).ravel()
    if far.shape != area.shape:
        raise ValueError("area and FAR must share one length")
    if unit_size <= 0:
        raise ValueError("unit size must be positive")
    potential = area * np.clip(far, 0.0, None)
    if existing_floor is not None:
        existing = np.asarray(existing_floor, dtype=float).ravel()
        if existing.shape != area.shape:
            raise ValueError("existing floorspace length must match area")
        potential = potential - np.clip(existing, 0.0, None)
    buildable = np.clip(potential, 0.0, None)
    units = np.floor(buildable * float(efficiency) / float(unit_size))
    return buildable, units.astype(np.int64)
