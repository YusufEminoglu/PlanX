# -*- coding: utf-8 -*-
"""Green infrastructure kernels: park hierarchies and patch connectivity.

Pure NumPy. Two views of the green network:

* :func:`parse_hierarchy` - the "minimum size = maximum distance" park
  standards ladder ("0.5=300, 2=800, 10=2000": a pocket park of 0.5 ha
  within 300 m, a district park of 2 ha within 800 m ...), the classic
  accessibility-standard formulation.
* :func:`connectivity` - the patch connectivity graph: patches closer
  than a gap distance form components; the Probability-of-Connectivity
  style index ``PC = sum over same-component pairs (a_i a_j) / A^2``
  (Saura & Pascual-Hortal 2007, binary form) and each patch's importance
  ``dPC`` - the share of PC lost when the patch is removed.
"""
from __future__ import annotations

import numpy as np


def parse_hierarchy(text):
    """Parse "min_ha=max_dist, ..." into a sorted list of (ha, dist).

    Returns classes sorted by size ascending; raises ValueError on
    malformed tokens so the wrapper can report them.
    """
    classes = []
    for token in str(text).replace(";", ",").split(","):
        token = token.strip()
        if not token:
            continue
        size, _, dist = token.partition("=")
        try:
            classes.append((float(size.strip()), float(dist.strip())))
        except ValueError:
            raise ValueError(f"hierarchy needs 'min_ha=max_dist': '{token}'")
    if not classes:
        raise ValueError("no hierarchy classes given")
    return sorted(classes)


def components(n, edges):
    """Connected components over ``n`` nodes: returns (labels, count)."""
    adj = [[] for _ in range(n)]
    for i, j in edges:
        adj[int(i)].append(int(j))
        adj[int(j)].append(int(i))
    labels = np.full(n, -1, dtype=np.int64)
    comp = 0
    for start in range(n):
        if labels[start] >= 0:
            continue
        stack = [start]
        labels[start] = comp
        while stack:
            u = stack.pop()
            for v in adj[u]:
                if labels[v] < 0:
                    labels[v] = comp
                    stack.append(v)
        comp += 1
    return labels, comp


def pc_index(areas, labels, total_area=None):
    """Binary Probability-of-Connectivity index for given components.

    ``PC = sum_c (sum of areas in c)^2 / A^2`` - every pair inside one
    component (including a patch with itself) counts as connected. ``A``
    defaults to the total patch area, giving 1.0 for one fully connected
    system and ``1/n`` in the all-isolated equal-patch case.
    """
    areas = np.asarray(areas, dtype=float)
    labels = np.asarray(labels)
    a_total = float(total_area) if total_area else float(areas.sum())
    if a_total <= 0:
        return 0.0
    pc = 0.0
    for c in np.unique(labels):
        pc += float(areas[labels == c].sum()) ** 2
    return pc / (a_total ** 2)


def connectivity(areas, edges, total_area=None):
    """Connectivity summary of a patch system.

    ``areas`` per patch, ``edges`` = (i, j) pairs closer than the gap.
    Returns dict: ``labels`` (component per patch), ``n_components``,
    ``pc`` (the index), ``dpc`` per patch (percent of PC lost when the
    patch is removed - its links go with it) and ``component_area``
    aligned per patch.
    """
    areas = np.asarray(areas, dtype=float)
    n = len(areas)
    labels, n_comp = components(n, edges)
    pc = pc_index(areas, labels, total_area=total_area)
    a_total = float(total_area) if total_area else float(areas.sum())
    dpc = np.zeros(n)
    for i in range(n):
        keep = [k for k in range(n) if k != i]
        sub_edges = [(a, b) for (a, b) in edges if a != i and b != i]
        remap = {old: new for new, old in enumerate(keep)}
        sub_labels, _ = components(
            n - 1, [(remap[a], remap[b]) for (a, b) in sub_edges])
        sub_pc = pc_index(areas[keep], sub_labels, total_area=a_total)
        dpc[i] = 100.0 * (pc - sub_pc) / pc if pc > 0 else 0.0
    comp_area = np.zeros(n)
    for c in np.unique(labels):
        m = labels == c
        comp_area[m] = areas[m].sum()
    return {
        "labels": labels,
        "n_components": n_comp,
        "pc": pc,
        "dpc": dpc,
        "component_area": comp_area,
    }
