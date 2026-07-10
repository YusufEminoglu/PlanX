# -*- coding: utf-8 -*-
"""Deterministic synthetic city generator.

Pure NumPy engine functions to create a toy city with streets, buildings,
land uses, POIs, facilities, demand points, and a DSM.
"""
from __future__ import annotations

import math
import numpy as np


def generate_demo_city(seed: int, blocks_x: int, blocks_y: int, block_size: float, pixel_size: float = 2.0) -> dict:
    rng = np.random.default_rng(seed)

    w = blocks_x * block_size
    h = blocks_y * block_size

    # 1. Streets
    # Grid lines and diagonal avenue.
    # Collect vertical line x coordinates:
    v_xs = [c * block_size for c in range(blocks_x + 1)]
    # Collect horizontal line y coordinates:
    h_ys = [r * block_size for r in range(blocks_y + 1)]

    diag_slope = h / w if w > 0 else 0.0

    streets = []

    # Vertical lines: x = cx
    for cx in v_xs:
        # Intersections with horizontal lines
        nodes = [(cx, ry) for ry in h_ys]
        # Intersection with diagonal line
        diag_y = diag_slope * cx
        if 0.0 <= diag_y <= h:
            nodes.append((cx, diag_y))

        # Sort nodes by y coordinate and drop duplicates (within tolerance)
        nodes = sorted(list(set(nodes)), key=lambda p: p[1])
        # Connect adjacent nodes
        for i in range(len(nodes) - 1):
            p1, p2 = nodes[i], nodes[i+1]
            if p2[1] - p1[1] > 1e-5:
                streets.append(np.array([p1, p2], dtype=np.float64))

    # Horizontal lines: y = ry
    for ry in h_ys:
        # Intersections with vertical lines
        nodes = [(cx, ry) for cx in v_xs]
        # Intersection with diagonal line
        if diag_slope > 0:
            diag_x = ry / diag_slope
            if 0.0 <= diag_x <= w:
                nodes.append((diag_x, ry))

        # Sort nodes by x coordinate and drop duplicates
        nodes = sorted(list(set(nodes)), key=lambda p: p[0])
        # Connect adjacent nodes
        for i in range(len(nodes) - 1):
            p1, p2 = nodes[i], nodes[i+1]
            if p2[0] - p1[0] > 1e-5:
                streets.append(np.array([p1, p2], dtype=np.float64))

    # Diagonal avenue nodes:
    diag_nodes = []
    for cx in v_xs:
        diag_nodes.append((cx, diag_slope * cx))
    for ry in h_ys:
        if diag_slope > 0:
            diag_nodes.append((ry / diag_slope, ry))

    # Sort diagonal nodes by x and drop duplicates
    diag_nodes = sorted(list(set(diag_nodes)), key=lambda p: p[0])
    for i in range(len(diag_nodes) - 1):
        p1, p2 = diag_nodes[i], diag_nodes[i+1]
        dist = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        if dist > 1e-5:
            streets.append(np.array([p1, p2], dtype=np.float64))

    # 2. Blocks and Land Use
    uses_pool = ["residential", "commercial", "green", "school"]
    uses_p = [0.6, 0.2, 0.15, 0.05]

    block_uses = np.empty((blocks_x, blocks_y), dtype=object)
    for cx in range(blocks_x):
        for ry in range(blocks_y):
            # Guarantee representatives for the first blocks if layout allows
            if cx == 0 and ry == 0:
                block_uses[cx, ry] = "residential"
            elif cx == 0 and ry == 1 and blocks_y > 1:
                block_uses[cx, ry] = "commercial"
            elif cx == 1 and ry == 0 and blocks_x > 1:
                block_uses[cx, ry] = "green"
            elif cx == 1 and ry == 1 and blocks_x > 1 and blocks_y > 1:
                block_uses[cx, ry] = "school"
            else:
                block_uses[cx, ry] = rng.choice(uses_pool, p=uses_p)

    landuse = []
    green_polys = []
    buildings = []
    pois = []
    facilities = []
    demand = []

    for cx in range(blocks_x):
        x_min, x_max = cx * block_size, (cx + 1) * block_size
        for ry in range(blocks_y):
            y_min, y_max = ry * block_size, (ry + 1) * block_size
            use = block_uses[cx, ry]

            # Closed block polygon
            poly = np.array([
                [x_min, y_min],
                [x_max, y_min],
                [x_max, y_max],
                [x_min, y_max],
                [x_min, y_min]
            ], dtype=np.float64)
            landuse.append((poly, use))

            if use == "green":
                green_polys.append(poly)
                # Facility: Park
                fx, fy = (x_min + x_max) / 2.0, (y_min + y_max) / 2.0
                facilities.append(((fx, fy), f"Park_{cx}_{ry}", 1000))
            elif use == "school":
                # Facility: School
                fx, fy = (x_min + x_max) / 2.0, (y_min + y_max) / 2.0
                facilities.append(((fx, fy), f"School_{cx}_{ry}", 500))
            elif use == "commercial":
                # Add 2 POIs in the block
                px1 = float(rng.uniform(x_min + 15, x_max - 15))
                py1 = float(rng.uniform(y_min + 15, y_max - 15))
                px2 = float(rng.uniform(x_min + 15, x_max - 15))
                py2 = float(rng.uniform(y_min + 15, y_max - 15))
                pois.append(((px1, py1), "Shop"))
                pois.append(((px2, py2), "Cafe"))

            # Place buildings inside block (green space stays free of footprints)
            if use == "green":
                continue

            margin = 0.1 * block_size
            b_w = 0.35 * block_size
            gap = 0.1 * block_size

            # Place 2x2 grid of buildings
            for bx in range(2):
                bx_min = x_min + margin + bx * (b_w + gap)
                bx_max = bx_min + b_w
                for by in range(2):
                    by_min = y_min + margin + by * (b_w + gap)
                    by_max = by_min + b_w

                    bcx = (bx_min + bx_max) / 2.0
                    bcy = (by_min + by_max) / 2.0

                    # Check overlap with diagonal avenue
                    if diag_slope > 0:
                        dist_to_diag = abs(diag_slope * bcx - bcy) / math.sqrt(diag_slope**2 + 1)
                        if dist_to_diag < b_w * 0.7:
                            continue

                    # Closed building footprint
                    b_poly = np.array([
                        [bx_min, by_min],
                        [bx_max, by_min],
                        [bx_max, by_max],
                        [bx_min, by_max],
                        [bx_min, by_min]
                    ], dtype=np.float64)

                    height = float(rng.uniform(3.0, 40.0))
                    buildings.append((b_poly, height))

                    # If residential, add demand point
                    if use == "residential":
                        b_area = b_w * b_w
                        pop = max(1, int(b_area * height * 0.005))
                        demand.append(((bcx, bcy), pop))

    # 3. DSM GeoTIFF Rasterization
    rows = int(np.ceil(h / pixel_size))
    cols = int(np.ceil(w / pixel_size))
    dsm = np.zeros((rows, cols), dtype=np.float64)

    for b_poly, height in buildings:
        bx_min = b_poly[:, 0].min()
        bx_max = b_poly[:, 0].max()
        by_min = b_poly[:, 1].min()
        by_max = b_poly[:, 1].max()

        c1 = int(np.floor(bx_min / pixel_size))
        c2 = int(np.ceil(bx_max / pixel_size))
        r1 = int(np.floor((h - by_max) / pixel_size))
        r2 = int(np.ceil((h - by_min) / pixel_size))

        c1_c = max(0, min(cols, c1))
        c2_c = max(0, min(cols, c2))
        r1_c = max(0, min(rows, r1))
        r2_c = max(0, min(rows, r2))

        if c2_c > c1_c and r2_c > r1_c:
            dsm[r1_c:r2_c, c1_c:c2_c] = height

    return {
        "streets": streets,
        "buildings": buildings,
        "landuse": landuse,
        "pois": pois,
        "facilities": facilities,
        "demand": demand,
        "green": green_polys,
        "dsm": dsm,
    }
