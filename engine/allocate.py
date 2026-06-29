# -*- coding: utf-8 -*-
"""Land-use allocation: assign parcels to land uses to maximise suitability.

Pure NumPy. A capacitated assignment / generalized-assignment heuristic:
given per-parcel-per-use suitability scores, parcel areas and a target area
to fill for each use, assign each parcel (whole) to at most one use so that
the area allocated to a use does not exceed its target and the total
area-weighted suitability is maximised. Parcels not needed to meet the
targets are left unassigned; uses that cannot be filled report a shortfall.

Method: greedy construction (best per-unit suitability first) + a local
search of single-parcel reassignments and capacity-respecting pairwise
swaps - fast and explainable, not a global optimum (the problem is
NP-hard). ``locked`` parcels are fixed to a use up front and consume that
use's target area. Suitability is treated as a non-negative good
(negatives are clipped to zero).
"""
from __future__ import annotations

import numpy as np


def parse_targets(text):
    """``"residential=50000, green=30000"`` -> [("residential", 50000.0), ...].

    Separators: comma or semicolon; keys are lower-cased. Raises ValueError
    on malformed entries.
    """
    targets = []
    for token in str(text).replace(";", ",").split(","):
        token = token.strip()
        if not token:
            continue
        if "=" not in token:
            raise ValueError(f"Target entry needs name=area: '{token}'")
        key, _, value = token.partition("=")
        key = key.strip().lower()
        try:
            area = float(value.strip())
        except ValueError:
            raise ValueError(f"Not a number in '{token}'")
        if not key or area < 0:
            raise ValueError(f"Invalid target entry: '{token}'")
        targets.append((key, area))
    if not targets:
        raise ValueError("No targets given (expected e.g. 'residential=50000').")
    return targets


def _objective(suit, area, assign):
    total = 0.0
    for p, u in enumerate(assign):
        if u >= 0:
            total += area[p] * suit[p, u]
    return float(total)


def allocate_land_use(suit, area, targets, locked=None, max_iter=50,
                      swap_limit=1200):
    """Assign parcels to uses to maximise area-weighted suitability.

    Parameters
    ----------
    suit : (P, U) array - per-unit suitability of each parcel for each use.
    area : (P,) array - parcel areas (consumed from a use's target budget).
    targets : (U,) array - area budget (capacity) per use.
    locked : (P,) int array or None - parcels fixed to a use index up front
        (``-1`` = free).
    max_iter : int - outer local-search iterations.
    swap_limit : int - skip the O(P^2) pairwise-swap pass when there are
        more free parcels than this (reassignment still runs).

    Returns dict:
      ``assign``     (P,) use index per parcel, ``-1`` = unassigned
      ``objective``  total area-weighted suitability (including locked)
      ``allocated``  (U,) area assigned to each use
      ``n_parcels``  (U,) parcels assigned to each use
      ``swaps``      improving swaps applied
      ``reassigned`` improving reassignments applied
    """
    suit = np.clip(np.asarray(suit, dtype=float), 0.0, None)
    area = np.asarray(area, dtype=float)
    targets = np.asarray(targets, dtype=float)
    if suit.ndim != 2:
        raise ValueError("suit must be 2-D (parcels x uses).")
    n_parc, n_use = suit.shape
    if area.shape[0] != n_parc:
        raise ValueError("len(area) must match the parcel rows of suit.")
    if targets.shape[0] != n_use:
        raise ValueError("len(targets) must match the use columns of suit.")

    assign = np.full(n_parc, -1, dtype=np.int64)
    remaining = targets.astype(float).copy()
    locked_mask = np.zeros(n_parc, dtype=bool)
    if locked is not None:
        locked = np.asarray(locked, dtype=np.int64)
        for p in range(n_parc):
            u = int(locked[p])
            if 0 <= u < n_use:
                assign[p] = u
                remaining[u] -= area[p]
                locked_mask[p] = True

    free = np.where(~locked_mask)[0]

    # ---- greedy construction over free parcels, best suitability first ----
    if len(free):
        pairs_p = np.repeat(free, n_use)
        pairs_u = np.tile(np.arange(n_use), len(free))
        pairs_s = suit[pairs_p, pairs_u]
        for k in np.lexsort((pairs_u, pairs_p, -pairs_s)):
            p, u = int(pairs_p[k]), int(pairs_u[k])
            if assign[p] != -1:
                continue
            if remaining[u] + 1e-9 >= area[p]:
                assign[p] = u
                remaining[u] -= area[p]

    # ---- local search: reassignment + capacity-respecting pairwise swaps ----
    swaps = reassigned = 0
    do_swaps = len(free) <= int(swap_limit)
    for _ in range(int(max_iter)):
        improved = False
        for p in free:
            p = int(p)
            cur = int(assign[p])
            cur_s = suit[p, cur] if cur >= 0 else 0.0
            best_u, best_gain = cur, 1e-12
            for u in range(n_use):
                if u == cur:
                    continue
                room = remaining[u] + (area[p] if cur == u else 0.0)
                if room + 1e-9 < area[p]:
                    continue
                gain = area[p] * (suit[p, u] - cur_s)
                if gain > best_gain:
                    best_gain, best_u = gain, u
            if best_u != cur:
                if cur >= 0:
                    remaining[cur] += area[p]
                remaining[best_u] -= area[p]
                assign[p] = best_u
                reassigned += 1
                improved = True
        if do_swaps:
            placed = [int(p) for p in free if assign[p] >= 0]
            for a_i in range(len(placed)):
                p = placed[a_i]
                up = int(assign[p])
                for b_i in range(a_i + 1, len(placed)):
                    q = placed[b_i]
                    uq = int(assign[q])
                    if up == uq:
                        continue
                    if (remaining[uq] + area[q] + 1e-9 < area[p]
                            or remaining[up] + area[p] + 1e-9 < area[q]):
                        continue
                    gain = (area[p] * (suit[p, uq] - suit[p, up])
                            + area[q] * (suit[q, up] - suit[q, uq]))
                    if gain > 1e-12:
                        remaining[up] += area[p] - area[q]
                        remaining[uq] += area[q] - area[p]
                        assign[p], assign[q] = uq, up
                        up = uq
                        swaps += 1
                        improved = True
        if not improved:
            break

    allocated = np.zeros(n_use)
    counts = np.zeros(n_use, dtype=np.int64)
    for p in range(n_parc):
        u = int(assign[p])
        if u >= 0:
            allocated[u] += area[p]
            counts[u] += 1
    return {
        "assign": assign,
        "objective": _objective(suit, area, assign),
        "allocated": allocated,
        "n_parcels": counts,
        "swaps": swaps,
        "reassigned": reassigned,
    }
