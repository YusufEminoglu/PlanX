# -*- coding: utf-8 -*-
"""Travel demand modeling engine routines."""
from __future__ import annotations

import numpy as np


def trip_generation(pop: np.ndarray, jobs: np.ndarray,
                    p_rate: float, a_rate: float) -> tuple[np.ndarray, np.ndarray]:
    """Calculate productions and attractions from zone population and jobs."""
    P = (pop * p_rate).astype(np.float64)
    A = (jobs * a_rate).astype(np.float64)
    return P, A


def gravity(P: np.ndarray, A: np.ndarray, cost: np.ndarray, beta: float,
            kind: str = "exp", max_iter: int = 100, tol: float = 1e-4) -> tuple[np.ndarray, int, float]:
    """Doubly constrained gravity model using Furness/IPF balancing.

    Returns:
        flow_matrix: 2D array of shape (N, M)
        iterations: number of iterations run
        error: final maximum absolute difference from P/A totals
    """
    N, M = cost.shape
    if P.sum() == 0 or A.sum() == 0:
        return np.zeros((N, M), dtype=np.float64), 0, 0.0

    # Scale A to match P to ensure convergence
    P_sum = P.sum()
    A_sum = A.sum()
    A = A * (P_sum / A_sum)

    # Deterrence matrix. An unreachable pair (inf or nan cost) deters
    # completely: it must exchange no trips. The algorithm wrapper used to
    # encode it as a large finite cost, which the exponential form does turn
    # into zero but the power form does not - 1e9 ** -0.1 is 0.126, a quarter
    # of the deterrence of a 1 km trip, so disconnected zones traded trips.
    reachable = np.isfinite(cost)
    safe_cost = np.where(reachable, cost, 0.0)
    if kind == "power":
        F = np.power(np.maximum(safe_cost, 1e-6), -beta)
    else:
        F = np.exp(-beta * safe_cost)
    F = np.where(reachable, F, 0.0)

    # Balancing
    r = np.ones(N, dtype=np.float64)
    s = np.ones(M, dtype=np.float64)

    iters = 0
    diff = 1.0

    for iters in range(1, max_iter + 1):
        denom_r = F @ s
        denom_r[denom_r < 1e-12] = 1e-12
        r = P / denom_r

        denom_s = F.T @ r
        denom_s[denom_s < 1e-12] = 1e-12
        s = A / denom_s

        T = (r[:, None] * F) * s[None, :]

        row_diff = np.abs(T.sum(axis=1) - P).max()
        col_diff = np.abs(T.sum(axis=0) - A).max()
        diff = max(row_diff, col_diff)

        if diff < tol:
            break

    return T, iters, float(diff)


def mean_trip_cost(T: np.ndarray, cost: np.ndarray, interzonal_only: bool = True) -> float:
    """Flow-weighted mean cost of the modelled trips.

    ``interzonal_only`` leaves the diagonal out: an intrazonal trip's cost is
    whatever the zone's centroid-to-itself cost happens to be (zero when both
    ends snap to one node), which says nothing about trip length.
    """
    T = np.asarray(T, dtype=np.float64)
    cost = np.asarray(cost, dtype=np.float64)
    mask = np.isfinite(cost)
    if interzonal_only and T.shape[0] == T.shape[1]:
        mask &= ~np.eye(T.shape[0], dtype=bool)
    total = float(T[mask].sum())
    return float((T[mask] * cost[mask]).sum() / total) if total > 0 else float("nan")


def calibrate_beta(P: np.ndarray, A: np.ndarray, cost: np.ndarray, target: float,
                   kind: str = "exp", max_iter: int = 100, tol: float = 1e-4,
                   lo: float = 1e-8, hi: float = 50.0, steps: int = 60):
    """Deterrence coefficient whose modelled mean trip cost equals ``target``.

    The mean interzonal trip cost falls as beta rises (a stronger deterrent
    keeps trips short), so the root is bracketed and found by bisection on
    log(beta) - slower than Hyman's (1969) secant iteration but it cannot
    overshoot into a negative beta, which the secant can on a lumpy cost
    matrix. Returns ``(beta, achieved_mean, evaluations, feasible)``;
    ``feasible`` is False when the target lies outside what any beta in
    [lo, hi] can produce, and the bound nearest to it is returned.
    """
    def mean_at(beta):
        T, _, _ = gravity(P, A, cost, beta, kind, max_iter, tol)
        return mean_trip_cost(T, cost)

    m_lo, m_hi = mean_at(lo), mean_at(hi)
    if not (np.isfinite(m_lo) and np.isfinite(m_hi)):
        return lo, m_lo, 2, False
    if target >= m_lo:
        return lo, m_lo, 2, target == m_lo
    if target <= m_hi:
        return hi, m_hi, 2, target == m_hi
    a, b = np.log(lo), np.log(hi)
    mid_mean = m_lo
    for k in range(steps):
        mid = 0.5 * (a + b)
        mid_mean = mean_at(float(np.exp(mid)))
        if mid_mean > target:
            a = mid
        else:
            b = mid
        if abs(mid_mean - target) <= 1e-6 * max(1.0, abs(target)):
            break
    return float(np.exp(0.5 * (a + b))), mid_mean, k + 3, True


def mode_split(times: list[np.ndarray], betas: list[float], asc: list[float]) -> list[np.ndarray]:
    """Compute multinomial logit shares per OD pair."""
    K = len(times)
    utils = []
    for k in range(K):
        u = asc[k] + betas[k] * times[k]
        utils.append(u)

    max_util = np.maximum.reduce(utils)

    exps = []
    for k in range(K):
        exps.append(np.exp(utils[k] - max_util))

    total_exp = sum(exps)
    total_exp[total_exp < 1e-12] = 1e-12

    shares = []
    for k in range(K):
        shares.append(exps[k] / total_exp)

    return shares
