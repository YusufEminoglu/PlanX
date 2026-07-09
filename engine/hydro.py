# -*- coding: utf-8 -*-
"""Hydrology and hazard screening engine functions."""
from __future__ import annotations

import heapq
import numpy as np


def fill_depressions(dem: np.ndarray) -> np.ndarray:
    """Deterministic priority-flood depression filling algorithm (Wang & Liu, 2006)."""
    rows, cols = dem.shape
    filled = np.copy(dem)
    visited = ~np.isfinite(dem)
    pq = []

    # Push boundary cells into priority queue
    for r in range(rows):
        for c in (0, cols - 1):
            if np.isfinite(filled[r, c]) and not visited[r, c]:
                heapq.heappush(pq, (filled[r, c], r, c))
                visited[r, c] = True
    for c in range(cols):
        for r in (0, rows - 1):
            if np.isfinite(filled[r, c]) and not visited[r, c]:
                heapq.heappush(pq, (filled[r, c], r, c))
                visited[r, c] = True

    while pq:
        val, r, c = heapq.heappop(pq)
        # 8-connectivity
        for dr, dc in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols:
                if not visited[nr, nc]:
                    visited[nr, nc] = True
                    if filled[nr, nc] < val:
                        filled[nr, nc] = val
                    heapq.heappush(pq, (filled[nr, nc], nr, nc))

    return filled


def d8_flow(dem: np.ndarray) -> np.ndarray:
    """Compute D8 steepest-descent flow direction grid.

    Ties are broken in the fixed neighbor order:
    East (1), Southeast (2), South (4), Southwest (8),
    West (16), Northwest (32), North (64), Northeast (128).
    """
    rows, cols = dem.shape
    dirs = np.zeros_like(dem, dtype=np.uint8)

    neighbors = [
        (0, 1, 1.0, 1),                    # East
        (1, 1, 1.4142135623730951, 2),     # Southeast
        (1, 0, 1.0, 4),                    # South
        (1, -1, 1.4142135623730951, 8),    # Southwest
        (0, -1, 1.0, 16),                  # West
        (-1, -1, 1.4142135623730951, 32),  # Northwest
        (-1, 0, 1.0, 64),                  # North
        (-1, 1, 1.4142135623730951, 128)   # Northeast
    ]

    for r in range(rows):
        for c in range(cols):
            if not np.isfinite(dem[r, c]):
                continue
            max_slope = 0.0
            flow_dir = 0
            for dr, dc, dist, code in neighbors:
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols:
                    if not np.isfinite(dem[nr, nc]):
                        continue
                    drop = dem[r, c] - dem[nr, nc]
                    slope = drop / dist
                    if slope > max_slope:
                        max_slope = slope
                        flow_dir = code
            dirs[r, c] = flow_dir

    return dirs


def flow_accumulation(dirs: np.ndarray) -> np.ndarray:
    """Compute D8 flow accumulation grid using Kahn's topological sort."""
    rows, cols = dirs.shape
    in_degree = np.zeros_like(dirs, dtype=int)

    dir_to_offset = {
        1: (0, 1),
        2: (1, 1),
        4: (1, 0),
        8: (1, -1),
        16: (0, -1),
        32: (-1, -1),
        64: (-1, 0),
        128: (-1, 1)
    }

    # Count in-degrees
    for r in range(rows):
        for c in range(cols):
            code = dirs[r, c]
            if code in dir_to_offset:
                dr, dc = dir_to_offset[code]
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols:
                    in_degree[nr, nc] += 1

    # Find nodes with 0 in-degree
    queue = []
    for r in range(rows):
        for c in range(cols):
            if in_degree[r, c] == 0:
                queue.append((r, c))

    accumulation = np.ones_like(dirs, dtype=np.float32)

    # Process queue topologically
    head = 0
    while head < len(queue):
        r, c = queue[head]
        head += 1
        code = dirs[r, c]
        if code in dir_to_offset:
            dr, dc = dir_to_offset[code]
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols:
                accumulation[nr, nc] += accumulation[r, c]
                in_degree[nr, nc] -= 1
                if in_degree[nr, nc] == 0:
                    queue.append((nr, nc))

    return accumulation


def hand(dem: np.ndarray, dirs: np.ndarray, drainage_mask: np.ndarray) -> np.ndarray:
    """Compute Height Above Nearest Drainage (HAND) grid."""
    rows, cols = dem.shape
    hand_arr = np.full_like(dem, -1.0, dtype=float)

    dir_to_offset = {
        1: (0, 1),
        2: (1, 1),
        4: (1, 0),
        8: (1, -1),
        16: (0, -1),
        32: (-1, -1),
        64: (-1, 0),
        128: (-1, 1)
    }

    drainage_cells = {}

    for r in range(rows):
        for c in range(cols):
            if not np.isfinite(dem[r, c]):
                continue
            curr_r, curr_c = r, c
            path = []
            visited_in_path = set()
            while True:
                if (curr_r, curr_c) in drainage_cells:
                    dr, dc = drainage_cells[(curr_r, curr_c)]
                    for pr, pc in path:
                        drainage_cells[(pr, pc)] = (dr, dc)
                    break
                if drainage_mask[curr_r, curr_c]:
                    dr, dc = curr_r, curr_c
                    drainage_cells[(curr_r, curr_c)] = (dr, dc)
                    for pr, pc in path:
                        drainage_cells[(pr, pc)] = (dr, dc)
                    break
                code = dirs[curr_r, curr_c]
                if code not in dir_to_offset:
                    dr, dc = curr_r, curr_c
                    drainage_cells[(curr_r, curr_c)] = (dr, dc)
                    for pr, pc in path:
                        drainage_cells[(pr, pc)] = (dr, dc)
                    break

                off_r, off_c = dir_to_offset[code]
                nr, nc = curr_r + off_r, curr_c + off_c
                if not (0 <= nr < rows and 0 <= nc < cols):
                    dr, dc = curr_r, curr_c
                    drainage_cells[(curr_r, curr_c)] = (dr, dc)
                    for pr, pc in path:
                        drainage_cells[(pr, pc)] = (dr, dc)
                    break

                if (nr, nc) in visited_in_path:
                    dr, dc = curr_r, curr_c
                    drainage_cells[(curr_r, curr_c)] = (dr, dc)
                    for pr, pc in path:
                        drainage_cells[(pr, pc)] = (dr, dc)
                    break

                path.append((curr_r, curr_c))
                visited_in_path.add((curr_r, curr_c))
                curr_r, curr_c = nr, nc

    for r in range(rows):
        for c in range(cols):
            if not np.isfinite(dem[r, c]):
                continue
            dr, dc = drainage_cells[(r, c)]
            hand_arr[r, c] = dem[r, c] - dem[dr, dc]

    return hand_arr


def inundation(hand_grid: np.ndarray, depth: float) -> np.ndarray:
    """Compute binary inundation mask where HAND <= depth."""
    inund = (hand_grid <= depth).astype(np.float32)
    inund[hand_grid < 0.0] = 0.0
    return inund


def exposure(inundation_grid: np.ndarray,
             bld_coords: list[tuple[float, float]],
             pop_coords: list[tuple[float, float]],
             pop_vals: list[float],
             gt: tuple[float, float, float, float, float, float]) -> dict[str, float]:
    """Calculate building and population exposure statistics from inundation grid."""
    rows, cols = inundation_grid.shape

    exposed_bld = 0
    total_bld = len(bld_coords)
    for x, y in bld_coords:
        col = int((x - gt[0]) / gt[1])
        row = int((y - gt[3]) / gt[5])
        if 0 <= row < rows and 0 <= col < cols:
            if inundation_grid[row, col] > 0.5:
                exposed_bld += 1

    exposed_pop = 0.0
    total_pop = sum(pop_vals)
    for (x, y), p in zip(pop_coords, pop_vals):
        col = int((x - gt[0]) / gt[1])
        row = int((y - gt[3]) / gt[5])
        if 0 <= row < rows and 0 <= col < cols:
            if inundation_grid[row, col] > 0.5:
                exposed_pop += p

    pct_bld = 100.0 * exposed_bld / total_bld if total_bld > 0 else 0.0
    pct_pop = 100.0 * exposed_pop / total_pop if total_pop > 0 else 0.0

    return {
        "exposed_bld": float(exposed_bld),
        "total_bld": float(total_bld),
        "pct_bld": pct_bld,
        "exposed_pop": exposed_pop,
        "total_pop": total_pop,
        "pct_pop": pct_pop
    }
