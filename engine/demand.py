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

    # Deterrence matrix
    if kind == "power":
        F = np.power(np.maximum(cost, 1e-6), -beta)
    else:
        F = np.exp(-beta * cost)

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
