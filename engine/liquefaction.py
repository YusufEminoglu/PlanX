# -*- coding: utf-8 -*-
"""Liquefaction screening engine functions.

Two independent models live here, and the difference between them is the
difference between the two tools the algorithm offers:

* **Zhu et al. (2015)** - a logistic regression on shaking, topography and
  shear-wave velocity. It runs from layers a user actually has (a DEM, a PGA
  field) and gives a *probability at a point*.
* **Hazus 6.1 Section 4.2.2.1** - a susceptibility-category model. It needs a
  map unit layer somebody else classified, and it gives a probability *and* an
  expected settlement for that unit.

Every number below is transcribed from a named table in a named document, and
the table number is in the comment (rule R1: a coefficient written from memory
is indistinguishable from a correct one until it is wrong). Nothing here is
calibrated against Turkish data; see ``UNCALIBRATED`` below and rule R6.

Licence note (R2): the USGS ``gfail`` implementation of Zhu et al. is CC0 and
was read as a cross-check on the coefficients, not copied; liquepy is MIT and
was read for orientation only. No code from either is reproduced here, and no
AGPL source was consulted.
"""
from __future__ import annotations

import math

# ---------------------------------------------------------------------- #
# Zhu et al. (2015)
# ---------------------------------------------------------------------- #

#: Coefficients of the global geospatial model of Zhu, Daley, Baise, Thompson,
#: Wald & Knudsen (2015), *Earthquake Spectra* 31(3), 1813-1837 (its Table 3
#: lists the model equations, the global one alongside three Christchurch
#: regional ones). The paper is paywalled and this set was **not** read off it:
#: it was read from the USGS ``gfail`` implementation, ``models/zhu_2015.py``
#: (CC0, by the same institution that wrote the model), which carries these six
#: numbers, the same percent-g division and the same clips - and then checked
#: against an independent published reproduction of the same equation, Geyin,
#: Baird & Maurer (2020), *Earthquake Spectra* 36(3), 1386-1411, whose Table 3
#: gives ``24.10 + 2.067 ln(PGAM) + 0.355 CTI - 0.4784 ln(Vs30)`` for the model
#: both papers call GGM1. That table also identifies ``PGAM`` as the
#: magnitude-weighted PGA of Youd et al. (2001) - which is what makes the
#: ``Mw^2.56 / 10^2.24`` factor in the log a *name* rather than a fitted
#: constant: it is that paper's magnitude scaling factor ``10^2.24 / Mw^2.56``
#: (its Equation 24) appearing as a divisor.
#:
#: That last coefficient is printed **0.4784** in the literature and is
#: **4.784** in gfail, and the difference is not cosmetic: the two differ by a
#: factor of ten, and ln(Vs30) spans about 5.2 to 6.6 over real sites, so the
#: smaller value removes at most 0.7 logit units of site term where the larger
#: removes up to 6.7. With 0.4784 the intercept of 24.10 dominates and the
#: logistic returns a probability of essentially 1 at every site - which is why
#: 4.784 is the value used here, and why a test pins the sensitivity rather
#: than trusting the transcription.
ZHU = {
    "intercept": 24.10,
    "ln_pga_magnitude": 2.067,
    "cti": 0.355,
    "ln_vs30": -4.784,
    "magnitude_exponent": 2.56,
    "magnitude_divisor": 10.0 ** 2.24,
}

#: Calibration clips, transcribed. The source clips CTI to (0, 15) and PGA to
#: (0, 270) **on a ShakeMap %g layer** - so 270 is 2.7 g. Our PGA field is in
#: g, which is why the clip below reads 2.7 and not 270, and why the /100 that
#: appears in the published term is *absent* from :func:`zhu_logit`. Applying
#: the /100 to a g-valued field would move the logit by
#: ``2.067 * ln(100) = 9.52`` and turn a 2 % probability into 0.9999. See the
#: test named after that trap.
ZHU_CTI_CLIP = (0.0, 15.0)
ZHU_PGA_CLIP_G = (0.0, 2.7)

#: Zhu, Baise & Thompson (2017), *BSSA* 107(3), 1365-1385, report that the 2015
#: model over-predicts the *area* affected by roughly 19 %, and publish 0.81 as
#: the coverage correction - which is how gfail's own ``calculate_coverage``
#: cites it ("correction factor to coverage found in Zhu et al 2017 paper"). It
#: applies to the area reading, not to the site probability: ``gfail`` sets
#: ``prob_units = "Proportion of area affected"`` and applies the factor in
#: ``calculate_coverage``, separate from the logistic. Both are reported by
#: the tool, as two named columns, because conflating them is a silent 19 %
#: error in whichever one the reader had in mind.
ZHU_COVERAGE_FACTOR = 0.81


def logistic(value: float) -> float:
    """1 / (1 + e^-x), written so that large |x| cannot overflow.

    ``1 / (1 + math.exp(-800))`` raises OverflowError; ``tanh`` saturates
    instead and the two agree to the last bit everywhere that matters. The
    result is never clipped to [0, 1]: it is bounded there already, and a
    clamp would hide a logit that had gone somewhere absurd.
    """
    return 0.5 * (1.0 + math.tanh(0.5 * value))


def clip_cti(value: float) -> tuple[float, bool]:
    """Clip CTI to the range the Zhu coefficients were fitted on."""
    low, high = ZHU_CTI_CLIP
    return min(max(value, low), high), not (low <= value <= high)


def clip_pga_g(value: float) -> tuple[float, bool]:
    """Clip PGA, in g, to the range the Zhu coefficients were fitted on."""
    low, high = ZHU_PGA_CLIP_G
    return min(max(value, low), high), not (low <= value <= high)


def zhu_logit(pga_g: float, magnitude: float, cti: float, vs30: float) -> float:
    """The Zhu et al. (2015) logit, with the magnitude term *inside* the log.

    ``X = c0 + c1*ln(PGA * Mw^2.56 / 10^2.24) + c2*CTI + c3*ln(Vs30)``

    The trap this function exists to not fall into: the magnitude scaling is
    folded *inside* the logarithm, not added beside it. The obvious reading of
    the published form - ``c1*ln(PGA) + 2.56*ln(Mw) + ...`` - is smooth,
    monotone in every input, bounded in (0, 1) after the logistic, and wrong:
    it scales the magnitude term by 1 instead of by 2.067, so it under-predicts
    the jump from Mw 6 to Mw 8 by a factor of two. Nothing downstream would
    notice. See ``test_zhu_magnitude_sensitivity_is_the_coefficient_times_the_exponent``.

    Inputs are taken unclipped; :func:`zhu_probability` is the clipped entry
    point and the one the tool calls.
    """
    if not pga_g > 0.0:
        raise ValueError(
            "PGA must be greater than zero: the model takes ln(PGA * ...), and "
            "a zero here returns a zero probability - 'no shaking' is not "
            "'no liquefaction hazard'.")
    if not vs30 > 0.0:
        raise ValueError("Vs30 must be greater than zero (the model takes ln(Vs30)).")
    if not magnitude > 0.0:
        raise ValueError("Magnitude must be greater than zero (it is raised to 2.56).")

    shaking = pga_g * (magnitude ** ZHU["magnitude_exponent"]) / ZHU["magnitude_divisor"]
    return (ZHU["intercept"]
            + ZHU["ln_pga_magnitude"] * math.log(shaking)
            + ZHU["cti"] * cti
            + ZHU["ln_vs30"] * math.log(vs30))


def zhu_probability(pga_g: float, magnitude: float, cti: float,
                    vs30: float) -> dict:
    """Site probability of liquefaction, and every term that made it.

    Returns a dict, the same shape :func:`hazus_probability` does, so a caller
    can report the intermediate values instead of only the answer: a
    probability on its own cannot be argued with, and ``notes`` is the R4
    applicability report. An empty ``notes`` means every input was inside the
    published calibration range; anything else names the input and the limit
    that was applied. That matters per row, because a clipped row is not a
    wrong row - it is a row where the model stopped being the model, and only
    the reader can decide whether to trust it.
    """
    clipped_pga, pga_bit = clip_pga_g(pga_g)
    clipped_cti, cti_bit = clip_cti(cti)
    notes = []
    if pga_bit:
        notes.append(
            f"PGA {pga_g:.3g} g clipped to {ZHU_PGA_CLIP_G[1]:.3g} g "
            f"(the range the coefficients were fitted on)")
    if cti_bit:
        notes.append(
            f"CTI {cti:.3g} clipped to {ZHU_CTI_CLIP[1]:.3g} "
            f"(the range the coefficients were fitted on)")
    logit = zhu_logit(clipped_pga, magnitude, clipped_cti, vs30)
    probability = logistic(logit)
    return {
        "probability": probability,
        "coverage": probability * ZHU_COVERAGE_FACTOR,
        "logit": logit,
        "pga_g": clipped_pga,
        "cti": clipped_cti,
        "pga_clipped": pga_bit,
        "cti_clipped": cti_bit,
        "notes": notes,
    }


# ---------------------------------------------------------------------- #
# Vs30 from topographic slope - Allen & Wald (2007)
# ---------------------------------------------------------------------- #

#: Allen & Wald, *USGS Open-File Report 2007-1357*, Table 2, read as the
#: (slope, Vs30) pairs where a slope bin boundary sits. The table itself is
#: slope ranges per subdivided NEHRP class; the report's own method statement
#: is "Topographic slope at any site that falls within these windows is
#: assigned a Vs30 by interpolating over the subdivided NEHRP boundaries based
#: on that slope value". So the bin edges are the nodes of a piecewise-linear
#: map, which is what these tuples are - and there is **no** two-branch
#: ``log(Vs30) = a + b*log(slope)`` regression in the report. Anyone who
#: "remembers" one is remembering the Wald & Allen (2007) *BSSA* paper's
#: discussion, not the OFR's method.
#:
#: Slopes are m/m (rise over run), the same quantity the DEM gradient gives.
#: Below the first node and above the last the value is held flat at the
#: table's own endpoint: the report publishes no slope range for NEHRP class E
#: below 1.0e-4 or for class B above 0.138, and extrapolating a piecewise
#: linear fit past its last node is an invention, not an interpolation.
SLOPE_VS30_NODES = {
    # Türkiye is an active tectonic region; the stable-continent column is for
    # continental interiors (central Europe, eastern North America). The choice
    # changes Vs30 by up to a factor of ~2 at a given slope, which the Zhu
    # logit turns into 3.2 logit units - the difference between a screening
    # tool and a different answer. It is therefore an explicit user choice with
    # no default (rule R3), not a setting with a sensible fallback.
    "active": (
        (1.0e-4, 180.0), (2.2e-3, 240.0), (6.3e-3, 300.0), (0.018, 360.0),
        (0.050, 490.0), (0.10, 620.0), (0.138, 760.0),
    ),
    "stable": (
        (2.0e-5, 180.0), (2.0e-3, 240.0), (4.0e-3, 300.0), (7.2e-3, 360.0),
        (0.013, 490.0), (0.018, 620.0), (0.025, 760.0),
    ),
}

#: The two settings the tool accepts, in the order the interface lists them.
TECTONIC_SETTINGS = ("active", "stable")


def vs30_from_slope(slope_m_per_m: float, setting: str) -> tuple[float, bool]:
    """Vs30 in m/s from a topographic slope (m/m), by Table 2 interpolation.

    Returns ``(vs30, clamped)``. ``clamped`` is True when the slope fell
    outside the published nodes and the value was held at the endpoint.
    """
    if setting not in SLOPE_VS30_NODES:
        raise ValueError(
            f"Unknown tectonic setting {setting!r}; expected one of "
            f"{', '.join(TECTONIC_SETTINGS)}.")
    nodes = SLOPE_VS30_NODES[setting]
    if not math.isfinite(slope_m_per_m):
        return nodes[-1][1] if slope_m_per_m > 0 else nodes[0][1], True
    if slope_m_per_m <= nodes[0][0]:
        return nodes[0][1], slope_m_per_m < nodes[0][0]
    if slope_m_per_m >= nodes[-1][0]:
        return nodes[-1][1], slope_m_per_m > nodes[-1][0]
    for (x0, y0), (x1, y1) in zip(nodes, nodes[1:]):
        if x0 <= slope_m_per_m <= x1:
            share = (slope_m_per_m - x0) / (x1 - x0)
            return y0 + share * (y1 - y0), False
    return nodes[-1][1], True


# ---------------------------------------------------------------------- #
# Hazus 6.1 Section 4.2.2.1 - susceptibility categories
# ---------------------------------------------------------------------- #

#: Hazus 6.1 Earthquake Model Technical Manual, Table 4-10, "Proportion of Map
#: Unit Susceptible to Liquefaction". These are judgments from regional
#: liquefaction studies, not a fitted curve; the manual says so in the two
#: sentences under the table.
HAZUS_PROPORTION = {
    "Very High": 0.25,
    "High": 0.20,
    "Moderate": 0.10,
    "Low": 0.05,
    "Very Low": 0.02,
    "None": 0.00,
}

#: Table 4-11, "Conditional Probability Relationship for Liquefaction
#: Susceptibility Categories", as the (slope, intercept) of a line clipped to
#: [0, 1]:  P[Liquefaction | PGA=a] = clip(m*a + b, 0, 1). The manual prints the
#: six rows in exactly this order and names the clip in each one.
#:
#: Cross-check performed against Figure 4-6 in the same manual: every line's
#: zero crossing (b/m) and its saturation point ((1-b)/m) reads back off the
#: plot, and all five pairs agree - 0.090/0.200, 0.120/0.250, 0.150/0.300,
#: 0.212/0.391, 0.260/0.500. Those same zero crossings are the PGA(t) values
#: in Table 4-12, which is the manual's own internal consistency check, and it
#: passes. That is why these numbers are trusted without the PDF being to hand.
HAZUS_CONDITIONAL = {
    "Very High": (9.09, -0.82),
    "High": (7.67, -0.92),
    "Moderate": (6.67, -1.00),
    "Low": (5.57, -1.18),
    "Very Low": (4.16, -1.08),
    # The sixth row of Table 4-11 is "None 0.0" - the category has no line,
    # it has a constant. Kept in the same dict as a degenerate line so that
    # every category reaches the same code path and "None" cannot fall through
    # into a KeyError at run time, which is how a category the user did supply
    # would turn into a crash rather than a zero.
    "None": (0.0, 0.0),
}

#: Table 4-12, "Threshold Ground Acceleration (PGA(t)) Corresponding to Zero
#: Probability of Liquefaction". In the manual these normalise the lateral
#: spreading curve of Equation 4-12, which this tool does not implement; we
#: report them as what they numerically are - the acceleration at which the
#: Table 4-11 conditional probability reaches zero - and the tool's column is
#: named for that role, not for the displacement one.
HAZUS_PGA_THRESHOLD = {
    "Very High": 0.09,
    "High": 0.12,
    "Moderate": 0.15,
    "Low": 0.21,
    "Very Low": 0.26,
}

#: Table 4-13, "Ground Settlement Amplitudes for Liquefaction Susceptibility
#: Categories", in inches. The manual defines the expected settlement as the
#: product of this amplitude and the Equation 4-9 probability, and warns the
#: amplitude itself is uncertain by a factor of one-half to two - which the
#: tool repeats rather than hides.
HAZUS_SETTLEMENT_IN = {
    "Very High": 12.0,
    "High": 6.0,
    "Moderate": 2.0,
    "Low": 1.0,
    "Very Low": 0.0,
    "None": 0.0,
}

#: The categories in the manual's own order, most to least susceptible. This is
#: also the only set of strings the tool accepts in a category column: a map
#: that says "VH" or "1" is refused with the list of accepted names, because
#: guessing at a recode turns an unrecognised category into a silent zero, and
#: a silent zero here reads as "no liquefaction hazard" (rule R7).
HAZUS_CATEGORIES = ("Very High", "High", "Moderate", "Low", "Very Low", "None")


def normalise_category(text) -> str | None:
    """Match a category string against Table 4-10..4-13's names, or return None.

    Case, surrounding space, and the separators ``,``/``_``/``-`` are ignored;
    nothing else is. In particular "medium" is not accepted for "moderate" and
    "1" is not accepted for "Very High" - see :data:`HAZUS_CATEGORIES`.
    """
    if text is None:
        return None
    cleaned = str(text).strip().lower()
    for separator in (",", "_", "-"):
        cleaned = cleaned.replace(separator, " ")
    cleaned = " ".join(cleaned.split())
    for category in HAZUS_CATEGORIES:
        if cleaned == category.lower():
            return category
    return None


def hazus_conditional(category: str, pga_g: float) -> float:
    """P[Liquefaction | PGA = a] from Table 4-11, clipped to [0, 1]."""
    slope, intercept = HAZUS_CONDITIONAL[category]
    return min(max(slope * pga_g + intercept, 0.0), 1.0)


def hazus_magnitude_factor(magnitude: float) -> float:
    """K_M, Equation 4-10: ``0.0027*M^3 - 0.0267*M^2 - 0.2055*M + 2.9188``.

    The published polynomial does not pass exactly through unity at the
    reference magnitude it was fitted to: K_M(7.5) = 1.0147. We apply it as
    printed rather than dividing by K_M(7.5), because renormalising would move
    every number in the tool away from the published method by ~1.5 % to fix a
    cosmetic inconsistency - and Hazus's own Figure 4-7 plots a marker at
    M = 7.5 that reads 1.01, so the manual is internally consistent about it.
    Nine markers read off Figure 4-7 all reproduce this polynomial.
    """
    return (0.0027 * magnitude ** 3 - 0.0267 * magnitude ** 2
            - 0.2055 * magnitude + 2.9188)


def hazus_groundwater_factor(depth_m: float) -> float:
    """K_W, Equation 4-11: ``0.022*d_w + 0.93`` with d_w in **feet**.

    The manual's variable is feet, so a depth in metres is converted here
    rather than at the call site - the 3.2808 is not a detail anyone should
    have to remember while reading a comment. K_W(5 ft) = 1.04, not 1.00; the
    same reference-value caveat as :func:`hazus_magnitude_factor` applies.
    """
    depth_ft = depth_m / 0.3048
    return 0.022 * depth_ft + 0.93


def hazus_probability(category: str, pga_g: float, magnitude: float,
                      depth_m: float) -> dict[str, float]:
    """Equation 4-9, the whole susceptibility-mode result for one map unit.

    ``P = P[Liquefaction | PGA=a] / (K_M * K_W) * P_ml``

    Returns the probability together with every term that produced it, because
    the intermediate values are what a reviewer checks: a probability on its
    own cannot be argued with.
    """
    conditional = hazus_conditional(category, pga_g)
    k_m = hazus_magnitude_factor(magnitude)
    k_w = hazus_groundwater_factor(depth_m)
    proportion = HAZUS_PROPORTION[category]
    probability = conditional / (k_m * k_w) * proportion
    return {
        "conditional": conditional,
        "k_m": k_m,
        "k_w": k_w,
        "proportion": proportion,
        "probability": min(max(probability, 0.0), 1.0),
        "settlement_in": min(max(probability, 0.0), 1.0)
        * HAZUS_SETTLEMENT_IN[category],
        "pga_threshold": HAZUS_PGA_THRESHOLD.get(category),
    }
