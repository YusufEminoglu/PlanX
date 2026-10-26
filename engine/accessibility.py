# -*- coding: utf-8 -*-
"""Place-based accessibility: decay functions, Hansen potential and 2SFCA.

Accessibility measures the *opportunities* a place can reach, weighted by how
hard they are to reach. Three families are implemented on one engine:

* **Cumulative opportunities** (Wachs & Kumagai 1973) - how many jobs, school
  seats or beds lie within a travel-time threshold. The decay is a step.
* **Gravity / potential accessibility** (Hansen 1959) -
  ``A_i = sum_j W_j f(c_ij)``, every opportunity counted with a weight that
  falls with travel cost.
* **Two-step floating catchment area** (Radke & Mu 2000; Luo & Wang 2003),
  with a distance-decayed catchment (Luo & Qi 2009, "E2SFCA"):

      R_j = S_j / sum_k P_k f(c_kj)          (supply-to-demand ratio at j)
      A_i = sum_j R_j f(c_ij)                (what i can claim of it)

  The Hansen measure ignores competition: a clinic counted by 50 000 people
  is counted 50 000 times. 2SFCA divides each facility's capacity among the
  population that can reach it, so ``A_i`` is supply per head and the
  population-weighted sum of ``A_i`` equals total supply reachable by anyone
  (the conservation property the tests check).

Decay functions (``kind``; ``c`` is travel cost in minutes, ``T`` the cutoff,
``p`` the kind's own parameter):

=========== ================================ ===============================
cumulative  1 if c <= T else 0               Wachs & Kumagai 1973
linear      max(0, 1 - c/T)                  cone; used by many 2SFCA papers
exponential exp(-p c)                        p = beta per minute
gaussian    exp(-c^2 / (2 p^2)) (c <= T)     p = sigma, minutes (Kwan 1998)
power       min(1, c^-p)                     p = beta; c < 1 min reads as 1
logistic    1 / (1 + exp((c - p) * k))       p = half-weight time; k = 4/p
=========== ================================ ===============================

Every kind is set to exactly zero beyond the cutoff ``T``. Without a cutoff
an exponential or power decay never reaches zero, so a destination across a
region would still contribute a sliver - and a 2SFCA catchment would cover
the whole region. The cutoff is what keeps the measure local, and it also
bounds the Dijkstra searches.
"""
from __future__ import annotations

import numpy as np

DECAY_KINDS = ("cumulative", "linear", "exponential", "gaussian", "power",
               "logistic")


def decay(cost, kind, param, cutoff):
    """Weight in [0, 1] for travel costs ``cost`` (minutes).

    Unreachable costs (inf/nan) and costs above ``cutoff`` weigh zero.
    ``param`` is the kind's own parameter (see the module table); it must be
    positive for exponential, gaussian, power and logistic.
    """
    c = np.asarray(cost, dtype=np.float64)
    ok = np.isfinite(c) & (c <= cutoff)
    cc = np.where(ok, np.maximum(c, 0.0), 0.0)
    if kind == "cumulative":
        w = np.ones_like(cc)
    elif kind == "linear":
        w = 1.0 - cc / float(cutoff) if cutoff > 0 else np.zeros_like(cc)
    elif kind == "exponential":
        w = np.exp(-float(param) * cc)
    elif kind == "gaussian":
        if param <= 0:
            raise ValueError("gaussian decay needs a positive sigma")
        w = np.exp(-(cc * cc) / (2.0 * float(param) ** 2))
    elif kind == "power":
        if param <= 0:
            raise ValueError("power decay needs a positive beta")
        w = np.power(np.maximum(cc, 1.0), -float(param))
    elif kind == "logistic":
        if param <= 0:
            raise ValueError("logistic decay needs a positive half-weight time")
        slope = 4.0 / float(param)
        z = np.clip((cc - float(param)) * slope, -700.0, 700.0)
        w = 1.0 / (1.0 + np.exp(z))
    else:
        raise ValueError(f"unknown decay kind '{kind}'")
    return np.where(ok, np.clip(w, 0.0, 1.0), 0.0)


def half_weight_time(kind, param, cutoff):
    """The cost at which the decay first reaches 0.5 (None if it never does).

    A single number a planner can quote to compare decays: "an opportunity
    10 minutes away counts half".
    """
    if kind == "cumulative":
        return None
    if kind == "linear":
        return 0.5 * cutoff
    if kind == "exponential":
        t = np.log(2.0) / param if param > 0 else None
    elif kind == "gaussian":
        t = param * np.sqrt(2.0 * np.log(2.0))
    elif kind == "power":
        t = 2.0 ** (1.0 / param) if param > 0 else None
    elif kind == "logistic":
        t = float(param)
    else:
        raise ValueError(f"unknown decay kind '{kind}'")
    if t is None or t > cutoff:
        return None
    return float(t)


class AccessAccumulator:
    """Chunk-wise Hansen and 2SFCA sums over a destination-by-origin cost block.

    The full origin-destination cost matrix is never held: the caller feeds
    blocks of destinations (``add_block``), each with its costs to every
    origin, and the sums are complete when the last block is in. 2SFCA can be
    built this way because each facility's ratio ``R_j`` needs only its own
    column.
    """

    def __init__(self, n_origins, population, kind, param, cutoff):
        self.population = np.asarray(population, dtype=np.float64)
        if len(self.population) != n_origins:
            raise ValueError("population needs one value per origin")
        self.kind, self.param, self.cutoff = kind, float(param), float(cutoff)
        self.hansen = np.zeros(n_origins)
        self.cumulative = np.zeros(n_origins)
        self.fca = np.zeros(n_origins)
        self.nearest = np.full(n_origins, np.inf)
        self.n_reached = np.zeros(n_origins, dtype=np.int64)
        self.ratios = []
        self.catchment_pop = []

    def add_block(self, cost_dest_by_origin, supply):
        """Costs shaped (block, n_origins) and the block's supply weights."""
        cost = np.asarray(cost_dest_by_origin, dtype=np.float64)
        supply = np.asarray(supply, dtype=np.float64)
        w = decay(cost, self.kind, self.param, self.cutoff)
        inside = np.isfinite(cost) & (cost <= self.cutoff)
        self.hansen += supply @ w
        self.cumulative += supply @ inside.astype(np.float64)
        self.n_reached += inside.sum(axis=0)
        if cost.size:
            finite = np.where(np.isfinite(cost), cost, np.inf)
            self.nearest = np.minimum(self.nearest, finite.min(axis=0))
        demand = w @ self.population
        ratio = np.where(demand > 0, supply / np.where(demand > 0, demand, 1.0), 0.0)
        self.fca += ratio @ w
        self.ratios.extend(ratio.tolist())
        self.catchment_pop.extend(demand.tolist())


def two_step_fca(cost_dest_by_origin, supply, population, kind, param, cutoff):
    """Whole-matrix 2SFCA, for tests and small problems.

    Returns ``(access_per_origin, ratio_per_destination)``.
    """
    cost = np.asarray(cost_dest_by_origin, dtype=np.float64)
    acc = AccessAccumulator(cost.shape[1], population, kind, param, cutoff)
    acc.add_block(cost, supply)
    return acc.fca, np.asarray(acc.ratios)


def hansen(cost_dest_by_origin, supply, kind, param, cutoff):
    """Whole-matrix Hansen potential, for tests and small problems."""
    cost = np.asarray(cost_dest_by_origin, dtype=np.float64)
    acc = AccessAccumulator(cost.shape[1], np.zeros(cost.shape[1]), kind, param, cutoff)
    acc.add_block(cost, supply)
    return acc.hansen
