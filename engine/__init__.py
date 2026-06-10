# -*- coding: utf-8 -*-
"""PlanX embedded analytics engine.

Pure NumPy core with an optional SciPy fast path. No qgis imports here:
this package is unit-testable in any Python that has NumPy.
"""
from __future__ import annotations

try:
    import scipy  # noqa: F401
    from scipy.sparse import csr_matrix  # noqa: F401
    from scipy.sparse import csgraph  # noqa: F401
    HAS_SCIPY = True
except Exception:  # pragma: no cover - depends on host install
    HAS_SCIPY = False
