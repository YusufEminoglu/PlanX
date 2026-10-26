# -*- coding: utf-8 -*-
"""Space syntax segment angular analysis.

Implements the segment-map measures of Hillier & Iida (2005) on the dual
graph built by :func:`engine.graphs.build_segment_graph`:

* **Angular total depth / mean depth / integration** - Dijkstra minimizing
  angular cost, optionally pruned at a metric radius.
* **Angular choice** - betweenness with angular cost within metric radius
  (Brandes pass shared with the depth computation).
* **NACH / NAIN** - the normalized measures of Hillier, Yang & Turner (2012):
  ``NACH = log10(CH + 1) / log10(TD + 3)`` and
  ``NAIN = (NC + 2) ** 1.2 / (TD + 2)``.

One Brandes sweep per radius yields *both* integration and choice.
"""
from __future__ import annotations

import numpy as np

from . import centrality

RADIUS_GLOBAL = "n"


def parse_radii(text: str):
    """Parse a radii string like ``"400, 800, n"`` -> [400.0, 800.0, None]."""
    radii = []
    for token in str(text).replace(";", ",").split(","):
        token = token.strip().lower()
        if not token:
            continue
        if token in ("n", "rn", "global", "inf"):
            radii.append(None)
        else:
            value = float(token)
            if value <= 0:
                raise ValueError(f"Radius must be positive: {token}")
            radii.append(value)
    if not radii:
        radii = [None]
    return radii


def radius_label(radius) -> str:
    return RADIUS_GLOBAL if radius is None else f"{radius:g}"


def segment_angular_analysis(seg_graph, radius=None, cancel=None, progress=None):
    """Run one radius. Returns dict of per-segment arrays:
    ``nc`` (node count), ``td`` (angular total depth), ``md`` (mean depth),
    ``nain``, ``choice`` (pair-based), ``nach``.
    """
    g = seg_graph
    node_bc, _, depth = centrality.brandes_betweenness(
        g.indptr, g.adj_seg, g.adj_ang, g.n,
        w_prune=g.adj_metric, radius=radius,
        cancel=cancel, progress=progress, collect_depth=True,
    )
    nc = depth["node_count"]
    td = depth["total_depth"]
    md = np.where(nc > 1, td / np.maximum(nc - 1, 1), 0.0)
    # Undirected Brandes counts each unordered pair twice.
    choice = node_bc / 2.0
    with np.errstate(divide="ignore", invalid="ignore"):
        nain = np.power(nc + 2.0, 1.2) / (td + 2.0)
        nach = np.log10(choice + 1.0) / np.log10(td + 3.0)
    nach = np.nan_to_num(nach, nan=0.0, posinf=0.0, neginf=0.0)
    nain = np.nan_to_num(nain, nan=0.0, posinf=0.0, neginf=0.0)
    return {"nc": nc, "td": td, "md": md, "nain": nain,
            "choice": choice, "nach": nach}


def _r_squared(x, y):
    """Squared Pearson correlation over the finite pairs, None when undefined."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 3:
        return None
    x, y = x[ok], y[ok]
    if x.std() == 0.0 or y.std() == 0.0:
        return None
    r = float(np.corrcoef(x, y)[0, 1])
    return r * r


def intelligibility_synergy(connectivity, nain_by_radius):
    """Hillier's two whole-map summaries of a segment analysis.

    ``nain_by_radius`` maps a radius (None = global) to that radius's NAIN.

    * **Intelligibility** (Hillier et al. 1987; Hillier 1996): r-squared of
      connectivity against integration at the widest radius - how well what
      a person sees from a segment (its immediate connections) predicts how
      the segment sits in the whole. A legible grid scores high; a labyrinth
      of similar-looking junctions scores low.
    * **Synergy**: r-squared of local integration (the smallest radius)
      against the widest - whether the local and the city-wide structure
      agree, i.e. whether the neighbourhood centres lie on the city's
      through routes.

    Returns ``{"intelligibility": float|None, "synergy": float|None,
    "global_radius": r, "local_radius": r}``; synergy is None with fewer than
    two radii. Computed on segments, so the values are not comparable with
    axial-map figures from the older literature.
    """
    if not nain_by_radius:
        return {"intelligibility": None, "synergy": None,
                "global_radius": None, "local_radius": None}
    radii = list(nain_by_radius)
    finite = sorted(r for r in radii if r is not None)
    widest = None if None in radii else finite[-1]
    smallest = finite[0] if finite else None
    out = {"global_radius": widest, "local_radius": smallest,
           "intelligibility": _r_squared(connectivity, nain_by_radius[widest]),
           "synergy": None}
    if len(radii) >= 2 and smallest is not None and smallest != widest:
        out["synergy"] = _r_squared(nain_by_radius[smallest], nain_by_radius[widest])
    return out
