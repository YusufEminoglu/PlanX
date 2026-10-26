# -*- coding: utf-8 -*-
"""Jobs-housing balance: local ratios, commute-shed ratios and dissimilarity.

Cervero (1989) gave the planning argument: where jobs and the workers who
fill them are far apart, commutes lengthen whatever the transport network
does. Three views are computed from one zone table:

* **Local ratio** - jobs over resident workers in the zone itself. Sensitive
  to zone size: a small zone is almost never balanced.
* **Commute-shed ratio** - jobs over workers within a network travel budget
  of each zone (the labourshed and the jobshed of Giuliano 1991), which is
  the ratio a resident actually experiences and is much less sensitive to
  where the zone boundaries fall.
* **Balance index** ``1 - |J - W| / (J + W)`` on either view - 1 when jobs
  equal workers, 0 when one side is absent - and the area-wide **index of
  dissimilarity** ``D = 0.5 sum_i |J_i / J - W_i / W|`` (Duncan & Duncan
  1955): the share of jobs (or workers) that would have to move zone for the
  two distributions to match.

``worker_ratio`` converts residents (or dwellings) to workers when the field
holds residents rather than workers; it is applied before every ratio.
"""
from __future__ import annotations

import numpy as np


def balance_index(jobs, workers):
    """1 - |J - W| / (J + W), elementwise; NaN where both are zero."""
    j = np.asarray(jobs, dtype=np.float64)
    w = np.asarray(workers, dtype=np.float64)
    total = j + w
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(total > 0, 1.0 - np.abs(j - w) / np.where(total > 0, total, 1.0), np.nan)


def ratio(jobs, workers):
    """J / W, NaN where there are no workers."""
    j = np.asarray(jobs, dtype=np.float64)
    w = np.asarray(workers, dtype=np.float64)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(w > 0, j / np.where(w > 0, w, 1.0), np.nan)


def dissimilarity(jobs, workers):
    """Duncan index of dissimilarity between the two distributions (0..1)."""
    j = np.asarray(jobs, dtype=np.float64)
    w = np.asarray(workers, dtype=np.float64)
    if j.sum() <= 0 or w.sum() <= 0:
        return float("nan")
    return float(0.5 * np.sum(np.abs(j / j.sum() - w / w.sum())))


def commute_shed(reach, jobs, workers):
    """Jobs and workers within reach of every zone.

    ``reach`` is a boolean (zones x zones) matrix, row i marking the zones
    within the travel budget of zone i (the diagonal included).
    """
    reach = np.asarray(reach, dtype=np.float64)
    return reach @ np.asarray(jobs, dtype=np.float64), reach @ np.asarray(workers, dtype=np.float64)
