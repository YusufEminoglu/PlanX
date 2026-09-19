# -*- coding: utf-8 -*-
"""Seismic damage, collapse and debris-spread engine functions.

Pure-NumPy, QGIS-free core for a Monte Carlo earthquake screening model:
a multi-state damage distribution per building from construction year
(Hazus design level), building type and ground motion, plus the resulting
debris spread radius, solid volume, bulked pile volume and mass. Geometry
operations (buffering, union, intersection with the road network) stay in
the algorithm wrapper; everything that is pure arithmetic lives here so it
can be unit-tested without a QGIS session.

Fragility model
---------------
Damage is driven by peak ground acceleration and evaluated with the Hazus
lognormal fragility function (Hazus Earthquake Model Technical Manual 6.1,
Section 5.4, Equation 5-2)::

    P(DS >= ds | PGA) = Phi( ln(PGA / theta_ds) / beta_ds )

with ``theta_ds`` the median equivalent PGA of damage state ``ds`` and
``beta_ds`` the dispersion of its natural logarithm. Discrete damage-state
probabilities follow by differencing the exceedance curves. The medians
are transcribed from the published manual (see the table below); the
dispersion is the single tabulated value ``beta_SPGA``.

What is calibrated and what is not
----------------------------------
The curves are calibrated for **US construction practice**: Hazus maps its
design levels onto US code eras and its reference demand spectrum onto a
large-magnitude western-United States earthquake at a soil site. The
design levels here are attached to Turkish regulation years instead (see
``YEAR_TIERS``). That remapping, the default reference PGA used when no
PGA field is supplied, and the material/void/density screening constants
are all **uncalibrated** and are marked as such at each definition. They
are defensible for comparative screening; they are not a Türkiye-specific
seismic loss model.
"""
from __future__ import annotations

import math

import numpy as np

from . import HAS_SCIPY

if HAS_SCIPY:  # pragma: no cover - depends on host install
    from scipy.special import ndtr as _ndtr
else:  # pragma: no cover - depends on host install
    _ndtr = None

#: Standard normal CDF, evaluated through SciPy when it is installed and
#: through ``math.erf`` otherwise. Both paths are exact; the fallback is
#: simply slower because it evaluates one scalar at a time.
_ERF = np.vectorize(math.erf, otypes=[np.float64])
_INV_SQRT2 = 1.0 / math.sqrt(2.0)

#: Damage-state ladder, lightest first. Index into every per-state array.
DAMAGE_STATES = ("none", "slight", "moderate", "extensive", "complete")

#: The four damage states Hazus tabulates, in its own order.
HAZUS_DAMAGE_STATES = ("slight", "moderate", "extensive", "complete")

#: Total dispersion of the equivalent-PGA structural curves. Hazus models it
#: as the SRSS of the damage-state threshold uncertainty, beta_M(SPGA) = 0.4
#: for all building types and states, and the spatial variability of
#: long-period ground-motion demand, beta_D(V) = 0.5; sqrt(0.4^2 + 0.5^2)
#: = 0.64, which is the value printed in all four tables. It is a single
#: number because damage-state variability is not adjusted for spectrum
#: shape (manual p. 5-66).
HAZUS_PGA_BETA = 0.64

#: Lowest PGA substituted into the log term, so a zero or null ground motion
#: yields P(no damage) = 1 instead of a domain error.
_PGA_FLOOR = 1e-9


def normal_cdf(z):
    """Standard normal cumulative distribution function, elementwise."""
    values = np.asarray(z, dtype=np.float64)
    if _ndtr is not None:
        return np.asarray(_ndtr(values), dtype=np.float64)
    return 0.5 * (1.0 + _ERF(values * _INV_SQRT2))


#: Equivalent-PGA structural fragility medians, in g, taken VERBATIM from the
#: Hazus Earthquake Model Technical Manual 6.1 (FEMA, 2022) Section 5.4.3,
#: Tables 5-37 to 5-40. Transcribed from the published PDF, not recalled.
#: Every tabulated dispersion is beta_SPGA = 0.64 = sqrt(0.4^2 + 0.5^2), the
#: SRSS of the damage-state threshold uncertainty and the spatial variability
#: of long-period ground-motion demand (manual p. 5-65).
#: Order within each tuple: (slight, moderate, extensive, complete).
#: None = the manual marks the type as not permitted at that design level.
HAZUS_EQUIVALENT_PGA_FRAGILITY = {
    # Table 5-40 Equivalent-PGA Structural Fragility (manual p. 5-71)
    "pre": {
        "W1": (0.18, 0.29, 0.51, 0.77),
        "W2": (0.12, 0.19, 0.37, 0.60),
        "S1L": (0.09, 0.13, 0.22, 0.38),
        "S1M": (0.09, 0.14, 0.23, 0.39),
        "S1H": (0.08, 0.12, 0.22, 0.38),
        "S2L": (0.11, 0.14, 0.23, 0.39),
        "S2M": (0.10, 0.14, 0.28, 0.47),
        "S2H": (0.09, 0.13, 0.29, 0.50),
        "S3": (0.08, 0.10, 0.16, 0.30),
        "S4L": (0.10, 0.13, 0.20, 0.36),
        "S4M": (0.09, 0.13, 0.25, 0.43),
        "S4H": (0.09, 0.14, 0.27, 0.47),
        "S5L": (0.11, 0.14, 0.22, 0.37),
        "S5M": (0.09, 0.14, 0.28, 0.43),
        "S5H": (0.08, 0.14, 0.29, 0.46),
        "C1L": (0.10, 0.12, 0.21, 0.36),
        "C1M": (0.09, 0.13, 0.26, 0.43),
        "C1H": (0.08, 0.12, 0.21, 0.35),
        "C2L": (0.11, 0.15, 0.24, 0.42),
        "C2M": (0.10, 0.15, 0.30, 0.50),
        "C2H": (0.09, 0.15, 0.31, 0.52),
        "C3L": (0.10, 0.14, 0.21, 0.35),
        "C3M": (0.09, 0.14, 0.25, 0.41),
        "C3H": (0.08, 0.13, 0.27, 0.43),
        "PC1": (0.11, 0.14, 0.21, 0.35),
        "PC2L": (0.10, 0.13, 0.19, 0.35),
        "PC2M": (0.09, 0.13, 0.24, 0.42),
        "PC2H": (0.09, 0.13, 0.25, 0.43),
        "RM1L": (0.13, 0.16, 0.24, 0.43),
        "RM1M": (0.11, 0.15, 0.28, 0.50),
        "RM2L": (0.12, 0.15, 0.22, 0.41),
        "RM2M": (0.10, 0.14, 0.26, 0.47),
        "RM2H": (0.09, 0.13, 0.27, 0.50),
        "URML": (0.13, 0.17, 0.26, 0.37),
        "URMM": (0.09, 0.13, 0.21, 0.38),
        "MH": (0.08, 0.11, 0.18, 0.34),
    },
    # Table 5-39 Equivalent-PGA Structural Fragility (manual p. 5-70)
    "low": {
        "W1": (0.20, 0.34, 0.61, 0.95),
        "W2": (0.14, 0.23, 0.48, 0.75),
        "S1L": (0.12, 0.17, 0.30, 0.48),
        "S1M": (0.12, 0.18, 0.29, 0.49),
        "S1H": (0.10, 0.15, 0.28, 0.48),
        "S2L": (0.13, 0.17, 0.30, 0.50),
        "S2M": (0.12, 0.18, 0.35, 0.58),
        "S2H": (0.11, 0.17, 0.36, 0.63),
        "S3": (0.10, 0.13, 0.20, 0.38),
        "S4L": (0.13, 0.16, 0.26, 0.46),
        "S4M": (0.12, 0.17, 0.31, 0.54),
        "S4H": (0.12, 0.17, 0.33, 0.59),
        "S5L": (0.13, 0.17, 0.28, 0.45),
        "S5M": (0.11, 0.18, 0.34, 0.53),
        "S5H": (0.10, 0.18, 0.35, 0.58),
        "C1L": (0.12, 0.15, 0.27, 0.45),
        "C1M": (0.12, 0.17, 0.32, 0.54),
        "C1H": (0.10, 0.15, 0.27, 0.44),
        "C2L": (0.14, 0.19, 0.30, 0.52),
        "C2M": (0.12, 0.19, 0.38, 0.63),
        "C2H": (0.11, 0.19, 0.38, 0.65),
        "C3L": (0.12, 0.17, 0.26, 0.44),
        "C3M": (0.11, 0.17, 0.32, 0.51),
        "C3H": (0.09, 0.16, 0.33, 0.53),
        "PC1": (0.13, 0.17, 0.25, 0.45),
        "PC2L": (0.13, 0.15, 0.24, 0.44),
        "PC2M": (0.11, 0.16, 0.31, 0.52),
        "PC2H": (0.11, 0.16, 0.31, 0.55),
        "RM1L": (0.16, 0.20, 0.29, 0.54),
        "RM1M": (0.14, 0.19, 0.35, 0.63),
        "RM2L": (0.14, 0.18, 0.28, 0.51),
        "RM2M": (0.12, 0.17, 0.34, 0.60),
        "RM2H": (0.11, 0.17, 0.35, 0.62),
        "URML": (0.14, 0.20, 0.32, 0.46),
        "URMM": (0.10, 0.16, 0.27, 0.46),
        "MH": (0.11, 0.18, 0.31, 0.60),
    },
    # Table 5-38 Equivalent-PGA Structural Fragility (manual p. 5-69)
    "moderate": {
        "W1": (0.24, 0.43, 0.91, 1.34),
        "W2": (0.20, 0.35, 0.64, 1.13),
        "S1L": (0.15, 0.22, 0.42, 0.80),
        "S1M": (0.13, 0.21, 0.44, 0.82),
        "S1H": (0.10, 0.18, 0.39, 0.78),
        "S2L": (0.20, 0.26, 0.46, 0.84),
        "S2M": (0.14, 0.22, 0.53, 0.97),
        "S2H": (0.11, 0.19, 0.49, 1.02),
        "S3": (0.13, 0.19, 0.33, 0.60),
        "S4L": (0.19, 0.26, 0.41, 0.78),
        "S4M": (0.14, 0.22, 0.51, 0.92),
        "S4H": (0.12, 0.21, 0.51, 0.97),
        "S5L": None,
        "S5M": None,
        "S5H": None,
        "C1L": (0.16, 0.23, 0.41, 0.77),
        "C1M": (0.13, 0.21, 0.49, 0.89),
        "C1H": (0.11, 0.18, 0.41, 0.74),
        "C2L": (0.18, 0.30, 0.49, 0.87),
        "C2M": (0.15, 0.26, 0.55, 1.02),
        "C2H": (0.12, 0.23, 0.57, 1.07),
        "C3L": None,
        "C3M": None,
        "C3H": None,
        "PC1": (0.18, 0.24, 0.44, 0.71),
        "PC2L": (0.18, 0.25, 0.40, 0.74),
        "PC2M": (0.15, 0.21, 0.45, 0.86),
        "PC2H": (0.12, 0.19, 0.46, 0.90),
        "RM1L": (0.22, 0.30, 0.50, 0.85),
        "RM1M": (0.18, 0.26, 0.51, 1.03),
        "RM2L": (0.20, 0.28, 0.47, 0.81),
        "RM2M": (0.16, 0.23, 0.48, 0.99),
        "RM2H": (0.12, 0.20, 0.48, 1.01),
        "URML": None,
        "URMM": None,
        "MH": (0.11, 0.18, 0.31, 0.60),
    },
    # Table 5-37 Equivalent-PGA Structural Fragility (manual p. 5-68)
    "high": {
        "W1": (0.26, 0.55, 1.28, 2.01),
        "W2": (0.26, 0.56, 1.15, 2.08),
        "S1L": (0.19, 0.31, 0.64, 1.49),
        "S1M": (0.14, 0.26, 0.62, 1.43),
        "S1H": (0.10, 0.21, 0.52, 1.31),
        "S2L": (0.24, 0.41, 0.76, 1.46),
        "S2M": (0.14, 0.27, 0.73, 1.62),
        "S2H": (0.11, 0.22, 0.65, 1.60),
        "S3": (0.15, 0.26, 0.54, 1.00),
        "S4L": (0.24, 0.39, 0.71, 1.33),
        "S4M": (0.16, 0.28, 0.73, 1.56),
        "S4H": (0.13, 0.25, 0.69, 1.63),
        "S5L": None,
        "S5M": None,
        "S5H": None,
        "C1L": (0.21, 0.35, 0.70, 1.37),
        "C1M": (0.15, 0.27, 0.73, 1.61),
        "C1H": (0.11, 0.22, 0.62, 1.35),
        "C2L": (0.24, 0.45, 0.90, 1.55),
        "C2M": (0.17, 0.36, 0.87, 1.95),
        "C2H": (0.12, 0.29, 0.82, 1.87),
        "C3L": None,
        "C3M": None,
        "C3H": None,
        "PC1": (0.20, 0.35, 0.72, 1.25),
        "PC2L": (0.24, 0.36, 0.69, 1.23),
        "PC2M": (0.17, 0.29, 0.67, 1.51),
        "PC2H": (0.12, 0.23, 0.63, 1.49),
        "RM1L": (0.30, 0.46, 0.93, 1.57),
        "RM1M": (0.20, 0.37, 0.81, 1.90),
        "RM2L": (0.26, 0.42, 0.87, 1.49),
        "RM2M": (0.17, 0.33, 0.75, 1.83),
        "RM2H": (0.12, 0.24, 0.67, 1.78),
        "URML": None,
        "URMM": None,
        "MH": (0.11, 0.18, 0.31, 0.60),
    },
}


#: Hazus design levels, weakest first. The manual's own terms are Pre-Code,
#: Low-Code, Moderate-Code and High-Code.
HAZUS_DESIGN_LEVELS = ("pre", "low", "moderate", "high")

#: Construction-year cutoff -> Hazus design level, oldest first. A building
#: whose year is at or below a cutoff gets that level; anything newer than
#: the last cutoff gets the default.
#:
#: UNCALIBRATED SCREENING MAPPING. Hazus defines its design levels by US
#: code eras; these cutoffs are the Turkish regulation dates (1985, 2000,
#: 2018) placed on the same ladder by analogy only. Hazus medians were
#: never fitted to TBDY-2018 or its predecessors, so this mapping carries
#: the US curve across to a Turkish building stock and must be replaced by
#: a Türkiye-specific calibration before any loss number is quoted.
YEAR_TIERS = (
    (1985, "pre"),
    (2000, "low"),
    (2018, "moderate"),
)
DEFAULT_DESIGN_LEVEL = "high"

#: Hazus building types offered by the algorithm, with the manual's own
#: short description (Table 5-1). Labels are the type WITHOUT a height
#: class; the height class is resolved from the floor count at run time.
#:
#: C3 (concrete frame with unreinforced masonry infill), S5 (steel frame
#: with unreinforced masonry infill) and URM (unreinforced masonry bearing
#: walls) are deliberately absent: Hazus marks them "not permitted by
#: current seismic codes" and prints no Moderate-Code or High-Code curve
#: for them, so no honest value exists for two of the four design levels.
#: The omission is a real limitation for a Turkish stock, where C3-type
#: infilled concrete frames are common at every era.
BUILDING_TYPES = (
    ("C1", "Concrete Moment Frame"),
    ("C2", "Concrete Shear Walls"),
    ("S1", "Steel Moment Frame"),
    ("S2", "Steel Braced Frame"),
    ("S3", "Steel Light Frame"),
    ("S4", "Steel Frame with Concrete Shear Walls"),
    ("W1", "Wood, Light Frame"),
    ("W2", "Wood, Commercial and Industrial"),
    ("RM1", "Reinforced Masonry Bearing Walls, Flexible Diaphragm"),
    ("RM2", "Reinforced Masonry Bearing Walls, Rigid Diaphragm"),
    ("PC1", "Precast Concrete Tilt-Up Walls"),
    ("PC2", "Precast Concrete Frames with Concrete Shear Walls"),
    ("MH", "Mobile Homes"),
)
DEFAULT_BUILDING_TYPE = "C1"

#: Height-class boundaries in storeys, from Hazus Table 5-1: low-rise is
#: 1-3 storeys, mid-rise 4-7, high-rise 8 or more.
HEIGHT_CLASS_BOUNDARIES = (3, 7)
DEFAULT_HEIGHT_CLASS = "M"

#: Types Hazus breaks into low/mid/high rise, and the single type that is
#: only low/mid rise (RM1 has no high-rise class in Table 5-1).
_THREE_CLASS_TYPES = frozenset({"C1", "C2", "S1", "S2", "S4", "PC2", "RM2"})
_TWO_CLASS_TYPES = frozenset({"RM1"})

#: Fallback ground motion, in g, used only when the buildings carry no PGA
#: attribute. The value is attached to the Mw 7.0 reference magnitude and
#: scaled exponentially from there.
#:
#: UNCALIBRATED SCREENING DEFAULT. It is a single nominal site value, not a
#: ground-motion prediction: it carries no distance, site class or fault
#: term. Any real analysis should join a PGA field (a ShakeMap, USGS or
#: AFAD raster) and leave this unused. Making it a named constant keeps the
#: assumption visible instead of burying it in a formula.
DEFAULT_REFERENCE_PGA = 0.35

#: Exponent of the magnitude scaling applied to the reference PGA. Screening
#: rule of thumb carried over from the original model, centred on Mw 7.0 so
#: that a Mw 7.0 event reproduces the reference PGA exactly.
MAGNITUDE_EXPONENT = 0.8

#: Fraction of the building's material volume released as debris, by damage
#: state. Full collapse releases the structure; extensive damage sheds a
#: large part of it; moderate damage sheds a small part; slight damage and
#: no damage shed nothing that reaches the street.
#:
#: UNCALIBRATED SCREENING DEFAULTS. These are not measured loss ratios and
#: no source is claimed for them; they exist so that a partly damaged
#: building contributes a pile instead of contributing nothing, which is
#: what the binary collapse model did. Treat them as an ordering, not a
#: quantity.
DAMAGE_MATERIAL_FACTOR = {
    "none": 0.0,
    "slight": 0.0,
    "moderate": 0.10,
    "extensive": 0.35,
    "complete": 1.0,
}

#: Void fraction of a debris pile: the share of the pile's bulk volume that
#: is air rather than material, so the pile occupies V_solid / (1 - void).
#: Rubble piles are commonly reported in the 0.3-0.5 range; the default sits
#: mid-range. UNCALIBRATED SCREENING DEFAULT.
DEFAULT_VOID_RATIO = 0.35

#: Bulk density of the debris material in tonnes per cubic metre, applied to
#: the SOLID volume (not the bulked pile). Concrete rubble screens around
#: 1.4-1.9 t/m3. UNCALIBRATED SCREENING DEFAULT.
DEFAULT_DEBRIS_DENSITY = 1.8


def magnitude_factor(magnitude: float) -> float:
    """Exponential scaling of ground motion demand with moment magnitude (Mw).

    Centred on Mw 7.0, the magnitude of the reference demand spectrum the
    Hazus equivalent-PGA tables were built for, so that a Mw 7.0 event
    reproduces the reference PGA exactly.
    """
    return float(np.exp(MAGNITUDE_EXPONENT * (float(magnitude) - 7.0)))


def effective_pga(magnitude: float, reference_pga: float = DEFAULT_REFERENCE_PGA) -> float:
    """Nominal ground motion (g) for a magnitude, when no PGA field is given.

    Screening only: scales the reference PGA exponentially with magnitude
    and carries no distance, site or fault term.
    """
    return float(reference_pga) * magnitude_factor(magnitude)


def design_level(year) -> np.ndarray:
    """Hazus design level for each construction year.

    Returns an array of level names shaped like the input. Values that are
    not finite numbers fall to the default (newest) level.
    """
    years = np.asarray(year, dtype=np.float64)
    result = np.full(years.shape, DEFAULT_DESIGN_LEVEL, dtype="<U8")
    # Apply from newest to oldest cutoff so the first (oldest) match wins.
    for max_year, level in reversed(YEAR_TIERS):
        result = np.where(years <= max_year, level, result)
    return result


def height_class(floors) -> np.ndarray:
    """Height class letter ("L", "M" or "H") for each storey count."""
    counts = np.asarray(floors, dtype=np.float64)
    low, mid = HEIGHT_CLASS_BOUNDARIES
    # Start at the tallest class and step down, so a storey count above the
    # last boundary keeps "H" instead of silently falling to the default.
    result = np.full(counts.shape, "H", dtype="<U1")
    result = np.where(counts <= mid, "M", result)
    result = np.where(counts <= low, "L", result)
    return np.where(np.isfinite(counts), result, DEFAULT_HEIGHT_CLASS)


def resolve_building_type(base_type, floors=None) -> np.ndarray:
    """Hazus label for a base type and storey count, e.g. C1 + 5 -> "C1M".

    Types Hazus does not split by height are returned unchanged. When no
    floor count is available the default mid-rise class is used.
    """
    base = np.asarray(base_type)
    if base.ndim == 0:
        if base == "" or base is None:
            base = DEFAULT_BUILDING_TYPE
        base = np.full(np.shape(floors) if floors is not None else (), str(base), dtype=object)
    if floors is None:
        classes = np.full(base.shape, DEFAULT_HEIGHT_CLASS, dtype="<U1")
    else:
        classes = height_class(floors)

    out = np.empty(base.shape, dtype=object)
    flat_base, flat_class = base.ravel(), classes.ravel()
    flat_out = out.ravel()
    for index, (name, cls) in enumerate(zip(flat_base, flat_class)):
        key = str(name).strip().upper()
        if key in _THREE_CLASS_TYPES:
            flat_out[index] = key + str(cls)
        elif key in _TWO_CLASS_TYPES:
            flat_out[index] = key + ("L" if str(cls) == "L" else "M")
        else:
            flat_out[index] = key
    return out


def damage_medians(design_levels, building_types) -> np.ndarray:
    """Median equivalent PGA (g) per damage state, state on axis 0.

    Returns an array of shape ``(4,) + input_shape`` holding the Slight,
    Moderate, Extensive and Complete medians for each building. Raises
    ValueError for a type the manual does not tabulate at that design level.
    """
    # Broadcast first: a scalar building type against a per-building level
    # array is the common call, and zip() would silently truncate it to one.
    levels, types = np.broadcast_arrays(np.asarray(design_levels), np.asarray(building_types))
    rows = []
    for level, btype in zip(levels.ravel(), types.ravel()):
        curve = HAZUS_EQUIVALENT_PGA_FRAGILITY.get(str(level), {}).get(str(btype).upper())
        if curve is None:
            raise ValueError(
                f"No Hazus equivalent-PGA curve for building type '{btype}' at "
                f"design level '{level}'."
            )
        rows.append(curve)
    stacked = np.asarray(rows, dtype=np.float64)          # (n, 4)
    return stacked.reshape(levels.shape + (4,)).T         # (4,) + shape


def damage_probabilities(im, design_levels, building_types,
                         beta: float = HAZUS_PGA_BETA) -> dict:
    """Discrete damage-state probabilities for each building.

    ``im`` is the intensity measure in g - either a scalar or an array
    broadcastable against the level/type arrays. Returns a dict keyed by
    every entry of ``DAMAGE_STATES`` whose values sum to 1 per building.
    """
    medians = damage_medians(design_levels, building_types)
    # A null or negative ground motion is no demand, not a domain error, and
    # it must not propagate NaN into the result. The wrapper counts how many
    # buildings arrived without a usable PGA so the fallback is visible.
    demand = np.maximum(np.nan_to_num(np.asarray(im, dtype=np.float64), nan=0.0,
                                      posinf=0.0, neginf=0.0), _PGA_FLOOR)
    exceedance = normal_cdf(np.log(demand / medians) / float(beta))   # (4,)+shape

    # Hazus medians increase from Slight to Complete, so the exceedance
    # curves are already nested; differencing them gives the exclusive state
    # probabilities and makes the five states sum to exactly one. The clip
    # is a guard against a pathological table, not an expected correction.
    return {
        "none": np.clip(1.0 - exceedance[0], 0.0, 1.0),
        "slight": np.clip(exceedance[0] - exceedance[1], 0.0, 1.0),
        "moderate": np.clip(exceedance[1] - exceedance[2], 0.0, 1.0),
        "extensive": np.clip(exceedance[2] - exceedance[3], 0.0, 1.0),
        "complete": np.clip(exceedance[3], 0.0, 1.0),
    }


def collapse_probability(year, magnitude, building_type=DEFAULT_BUILDING_TYPE,
                         reference_pga: float = DEFAULT_REFERENCE_PGA) -> np.ndarray:
    """Per-building total-collapse probability.

    Thin wrapper over the Hazus curves: the complete damage state evaluated
    at the nominal ground motion for ``magnitude``. Kept as the named entry
    point so callers that only want a collapse rate stay one call long.
    """
    levels = design_level(year)
    labels = resolve_building_type(building_type, None)
    return damage_probabilities(effective_pga(magnitude, reference_pga), levels, labels)["complete"]


def simulate_collapse(seed: int, p_collapse: np.ndarray) -> np.ndarray:
    """Deterministic Monte Carlo draw: True where the building collapses.

    A single seeded generator draws one uniform sample per building, so the
    same (seed, inputs) pair always reproduces the identical collapse set,
    and changing the seed samples a different stochastic realization.
    """
    p_collapse = np.asarray(p_collapse, dtype=np.float64)
    rng = np.random.default_rng(seed)
    draws = rng.random(p_collapse.shape)
    return draws < p_collapse


def sample_damage_state(seed: int, probabilities: dict) -> np.ndarray:
    """Sample one damage state per building, as an index into DAMAGE_STATES.

    Inverse-transform sampling on the discrete distribution, so the same
    seed and probabilities always return the same states.
    """
    shape = np.asarray(probabilities["complete"], dtype=np.float64).shape
    rng = np.random.default_rng(seed)
    draws = rng.random(shape)
    index = np.zeros(shape, dtype=np.int64)
    cumulative = np.zeros(shape, dtype=np.float64)
    for position, state in enumerate(DAMAGE_STATES[:-1]):
        cumulative = cumulative + np.asarray(probabilities[state], dtype=np.float64)
        index = np.where(draws >= cumulative, position + 1, index)
    return np.clip(index, 0, len(DAMAGE_STATES) - 1)


def material_factor(state_index) -> np.ndarray:
    """Released-material fraction for each sampled damage state."""
    lookup = np.asarray([DAMAGE_MATERIAL_FACTOR[state] for state in DAMAGE_STATES],
                        dtype=np.float64)
    return lookup[np.clip(np.asarray(state_index, dtype=np.int64), 0, len(DAMAGE_STATES) - 1)]


def debris_extent(
    height: np.ndarray, area: np.ndarray, state_factor: np.ndarray,
    debris_factor: float, solid_volume_ratio: float,
    void_ratio: float = DEFAULT_VOID_RATIO,
    density: float = DEFAULT_DEBRIS_DENSITY,
) -> tuple:
    """Debris radius and the three volume/mass quantities per building.

    ``debris_factor`` (k) is the fraction of building height thrown
    horizontally onto surrounding ground (Goretti & Sarli, 2006) for a
    total collapse. ``solid_volume_ratio`` is the fraction of the gross
    building volume that is material rather than void. ``state_factor`` is
    the released-material fraction for the building's damage state: it
    scales the radius, the volume and the mass linearly, so a building that
    keeps three quarters of its structure throws a correspondingly smaller
    pile. Scaling the radius linearly rather than by the cube root of the
    volume is the conservative choice for a screening tool, where
    over-stating a blockage is safer than under-stating it.

    Returns ``(radius_m, solid_m3, pile_m3, mass_t)``. ``solid_m3`` is the
    material volume, ``pile_m3`` the bulk volume the pile occupies once its
    voids are counted, and ``mass_t`` the tonnage to haul away.
    """
    height = np.asarray(height, dtype=np.float64)
    area = np.asarray(area, dtype=np.float64)
    factor = np.clip(np.asarray(state_factor, dtype=np.float64), 0.0, 1.0)

    radius = height * float(debris_factor) * factor
    solid = area * height * float(solid_volume_ratio) * factor
    pile = solid / max(1e-9, 1.0 - float(void_ratio))
    mass = solid * float(density)
    return radius, solid, pile, mass


# --------------------------------------------------------------------------- #
# Street-space width helpers (network sources B and C of the debris algorithm)
# --------------------------------------------------------------------------- #

# Typical full carriageway widths (m) per OSM ``highway`` class, applied when
# the road network arrives as centerlines without a usable width attribute.
# Screening quality: the Monte Carlo debris-radius uncertainty dominates any
# nominal-width error at this scale.
OSM_HIGHWAY_WIDTHS_M = {
    "motorway": 25.0,
    "trunk": 25.0,
    "primary": 18.0,
    "secondary": 14.0,
    "tertiary": 10.0,
    "residential": 8.0,
    "unclassified": 8.0,
    "road": 8.0,
    "service": 5.0,
    "living_street": 5.0,
    "track": 4.0,
    "pedestrian": 3.0,
    "footway": 3.0,
    "cycleway": 3.0,
    "path": 3.0,
    "steps": 2.0,
}


def parse_width_m(value):
    """Lenient road-width parser for attribute values.

    Accepts numbers and strings such as "6.5", "6,5" or "6.5 m" and returns
    the width as float metres. Returns None when the value is missing,
    non-numeric or non-positive - the caller then falls back to a class or
    default width.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        width = float(value)
        return width if np.isfinite(width) and width > 0.0 else None
    text = str(value).strip().lower()
    if not text:
        return None
    for unit in ("meters", "metres", "meter", "metre", "m"):
        if text.endswith(unit):
            text = text[: -len(unit)].strip()
            break
    try:
        width = float(text.replace(",", "."))
    except ValueError:
        return None
    return width if np.isfinite(width) and width > 0.0 else None


def highway_width_m(highway_class, fallback: float) -> float:
    """Full carriageway width (m) for an OSM ``highway`` class value.

    Matching is case- and whitespace-tolerant; "_link" ramp variants inherit
    the parent class width; unknown or missing classes get ``fallback``.
    """
    if highway_class is None:
        return float(fallback)
    key = str(highway_class).strip().lower()
    if key.endswith("_link"):
        key = key[: -len("_link")]
    return float(OSM_HIGHWAY_WIDTHS_M.get(key, fallback))
