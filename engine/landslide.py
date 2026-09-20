# -*- coding: utf-8 -*-
"""Coseismic landslide screening engine functions.

Two halves that compose, and the composition is the whole tool:

* **Jibson (2007) Equation 7** turns a critical acceleration, a peak ground
  acceleration and a magnitude into a Newmark displacement - the distance a
  slope is expected to slide. It takes exactly the two quantities the seismic
  chain already produces (PGA and Mw) and nothing else, which is why it is the
  displacement model here.
* **Hazus 6.1 Section 4.2.2.2** turns a geological group, a groundwater state
  and a slope angle into a critical acceleration - which is the number
  Equation 7 needs and that almost nobody has as a layer.

Every number below is transcribed from a named table in a named document and
the table number is in the comment above it (rule R1: a coefficient written
from memory is indistinguishable from a correct one until it is wrong). The
tables are also mutually checked - the category table, the acceleration table,
the lower-bound table and the area table are four independent readings of one
schema, so a mistyped cell usually contradicts a neighbour. Those checks live
in ``tests/test_engine.py`` and are what make a transcription error fail a test
instead of shipping.

Nothing here is calibrated against Turkish data; see ``UNCALIBRATED`` below and
rule R6.

Licence note (R2): Hazus is a FEMA publication of the United States federal
government and carries no copyright. Jibson (2007) is paywalled and was **not**
read directly - the coefficients were read from an open-access, peer-reviewed
reproduction of the equation that prints it and cites it, and then
cross-checked against a second independent implementation of the sibling form
of the same paper. See :data:`JIBSON_2007` for the provenance in full. No code
was copied from any source, and no AGPL source was consulted.
"""
from __future__ import annotations

import math

# ---------------------------------------------------------------------- #
# Jibson (2007) Equation 7 - Newmark displacement
# ---------------------------------------------------------------------- #

#: Coefficients of the Newmark-displacement regression of Jibson (2007),
#: *Engineering Geology* 91(2-4), 209-218, DOI 10.1016/j.enggeo.2007.01.013,
#: "Regression models for estimating coseismic landslide displacement", its
#: **Equation 7** - the form that carries a magnitude term::
#:
#:     log D_N = -2.71 + log[(1 - a_c/a_max)^2.335 * (a_c/a_max)^-1.478] + 0.424 M
#:
#: with ``D_N`` in **centimetres**, ``a_c`` and ``a_max`` both in g, ``M`` the
#: moment magnitude, the log base 10, and the paper's stated applicability
#: range 5.3 <= M <= 7.6.
#:
#: The paper is paywalled and the USGS publication page offers no free full
#: text, so these five numbers were **not** read off it. They were read from an
#: open-access, peer-reviewed article that prints the equation and lists Jibson
#: (2007) as its reference [26] - Yiğit, *Pamukkale Üniversitesi Mühendislik
#: Bilimleri Dergisi* 32(1), 191-199, 2026, DOI 10.5505/pajes.2025.29499, as
#: its own Equation 8 - Yiğit's numbering, which differs from the paper's. Two
#: things argue against a garbled transcription there: that
#: article's own refit of the same functional form on Turkish records prints
#: visibly *different* exponents (1.3593), so the two are not one number copied
#: twice; and its reference [26] gives the same journal, volume and page range
#: Crossref returns for the paper.
#:
#: The equation *number* is confirmed against Jibson's own numbering by an
#: independent implementation rather than by the transcription: the USGS
#: ``groundfailure`` package documents its ``J_PGA_M`` model as "PGA and
#: M-based model, equation 7 from Jibson (2007)", carries the same four
#: constants (-2.71, 2.335, -1.478, 0.424) and returns
#: ``logDnstd = 0.454``. This number was previously written as Equation 8 in
#: this codebase, which is wrong: Equation 8 of that paper is not a regression
#: at all but the symbolic template ``log D_N = A log I_a + B log a_c + C +/- s``
#: from which the Arias-intensity fits were generated. The paper's own closing
#: sentence lists its four regressions as Eqs. (6), (7), (9) and (10).
#:
#: The magnitude term is the reason this form was chosen over the Arias-
#: intensity forms. Jibson's Equation 10 and the public-domain USGS Open-File
#: Report 98-113 regression (Jibson, Harp & Michael 1998) both need Arias
#: intensity, which this plugin's ground-motion tool does not produce -
#: deriving one would mean a GMPE, which is a different release and a different
#: set of coefficients to transcribe.
JIBSON_2007 = {
    "intercept": -2.71,
    "one_minus_ratio_exponent": 2.335,
    "ratio_exponent": -1.478,
    "magnitude": 0.424,
}

#: Dispersion of Equation 7, in log10 units: ``0.454``, from Table 1 of the
#: same article (which lists ``Jibson2007/1  0.87  0.454`` - R-squared and
#: model sigma - alongside the same figures for every other regression it
#: reviews; that table's column header reads ``s (cm)``, which mislabels a
#: log10 dispersion as a length, so it is read as the log10 figure the paper
#: itself prints). The USGS ``groundfailure`` implementation of the same
#: equation returns the same ``0.454``. This is what makes the displacement a
#: *distribution* rather than a number, and the tool reports the 90th
#: percentile alongside the median so that the spread is visible rather than
#: implied.
JIBSON_2007_SIGMA = 0.454

#: The 90th percentile of a standard normal. A mathematical constant, not a
#: fitted one, and written here so the percentile column cannot be mistaken
#: for a coefficient read out of a table.
NORMAL_P90_FACTOR = 1.2815515655446004

#: A *reporting* threshold, not a published limit. The second term of Equation
#: 7, ``(a_c/a_max)^-1.478``, grows without bound as the ratio falls, so the
#: regression returns larger and larger displacements as the material loses
#: strength, without limit. Every row below this ratio is counted and named in
#: the run log rather than passed off as an ordinary prediction.
#:
#: The value is the smallest critical acceleration Table 4-16 can produce
#: (0.05 g, category X) read against a 1.0 g peak acceleration - that is, the
#: point past which this tool's *own* tables stop describing anything. Nothing
#: published says the regression is invalid below it; what is published is that
#: this term has no ceiling.
JIBSON_LOW_RATIO = 0.05


def jibson_displacement(ac_g: float, pga_g: float, magnitude: float) -> dict:
    """Newmark displacement from Equation 7, in centimetres.

    Returns a dict: ``disp_cm`` (the median, because the regression predicts
    the mean of ``log D_N`` and the log is taken base 10), ``p90_cm`` (the 90th
    percentile, from the published sigma), ``ratio`` (``a_c / a_max``),
    ``log10_disp``, ``moving`` and a list of ``notes``.

    Raises ``ValueError`` for inputs the equation cannot be evaluated on. Two
    of those are identities rather than opinions: a critical acceleration of
    zero sends the second term to infinity - an unconfined material is not a
    slope, it is a flow, and that is the ground-failure question
    ``planx:liquefaction`` exists for - and a peak acceleration of zero makes
    the ratio infinite. Neither has a substitute value, and rule R7 says refuse
    rather than substitute.
    """
    if pga_g is None or not pga_g > 0.0:
        raise ValueError(
            "the peak ground acceleration must be greater than zero: Equation "
            "8 takes a_c/a_max, and with no shaking there is no ratio to take")
    if ac_g is None or ac_g < 0.0:
        raise ValueError("the critical acceleration cannot be negative")
    if ac_g == 0.0:
        raise ValueError(
            "a critical acceleration of zero has no finite answer: the "
            "(a_c/a_max)^-1.478 term of Equation 7 diverges. A material with "
            "no strength to mobilise is not a slope with a displacement, it is "
            "a flow - that is the liquefaction question, not this one")

    ratio = ac_g / pga_g
    notes: list[str] = []

    # At and above unity the sliding block never yields, and the equation is
    # not merely small there - (1 - ratio) is negative and a fractional power
    # of it is undefined. Zero is the physical answer, not a fallback.
    if ratio >= 1.0:
        notes.append(
            f"a_c/PGA is {ratio:.3f}: the critical acceleration meets or "
            "exceeds the peak ground acceleration, so the block does not move "
            "and the displacement is zero. This is the model's answer, not "
            "missing data")
        return {
            "disp_cm": 0.0,
            "p90_cm": 0.0,
            "log10_disp": None,
            "ratio": ratio,
            "moving": False,
            "notes": notes,
        }

    log10_disp = (
        JIBSON_2007["intercept"]
        + JIBSON_2007["one_minus_ratio_exponent"] * math.log10(1.0 - ratio)
        + JIBSON_2007["ratio_exponent"] * math.log10(ratio)
        + JIBSON_2007["magnitude"] * magnitude
    )
    disp_cm = 10.0 ** log10_disp
    p90_cm = 10.0 ** (log10_disp + NORMAL_P90_FACTOR * JIBSON_2007_SIGMA)

    if ratio < JIBSON_LOW_RATIO:
        notes.append(
            f"a_c/PGA is {ratio:.3f}, below {JIBSON_LOW_RATIO:g}: the "
            "displacement term grows without bound as this ratio falls, so the "
            "number is an extrapolation rather than an interpolation. It is "
            "reported as the equation gives it and not clipped - but it is not "
            "a displacement a slope can be built on")

    return {
        "disp_cm": disp_cm,
        "p90_cm": p90_cm,
        "log10_disp": log10_disp,
        "ratio": ratio,
        "moving": True,
        "notes": notes,
    }


# ---------------------------------------------------------------------- #
# Hazus 6.1 Section 4.2.2.2 - critical acceleration from geology
# ---------------------------------------------------------------------- #
#
# Hazus is explicit that the chain below is an inference and not a
# measurement: "At the present time, a generally accepted relationship or
# simplified methodology for estimating ac has not been developed"
# (Section 4.2.2.2.1), and the correlation it does use is described as
# conservative, "representing the most landslide-susceptible geologic types
# likely to be found in the geologic group". A critical acceleration that comes
# out of it is a screening value derived from a map unit, and the tool says so
# on every row through ``ac_src``.

#: Slope-angle bands of Table 4-14, in degrees, as half-open intervals
#: ``[low, high)``. The manual prints them as column headings
#: ``0-10 / 10-15 / 15-20 / 20-30 / 30-40 / >40``; reading the upper edge as
#: exclusive is the only choice that tiles the line without overlap, and it is
#: what makes a cell at exactly 10 degrees land in one band and not two.
HAZUS_LANDSLIDE_BANDS_DEG = (
    (0.0, 10.0),
    (10.0, 15.0),
    (15.0, 20.0),
    (20.0, 30.0),
    (30.0, 40.0),
    (40.0, math.inf),
)

#: The manual's own headings for those bands, for the run log and the row notes.
HAZUS_LANDSLIDE_BAND_LABELS = (
    "0-10", "10-15", "15-20", "20-30", "30-40", ">40",
)

#: The three geologic groups of Table 4-14, in the manual's own order, with the
#: strength pair each group is defined by. The pair is not decoration: it is
#: the reason a user with real shear-strength data should not use this route at
#: all but should supply a critical acceleration directly.
HAZUS_LANDSLIDE_GROUPS = (
    ("A", "Strongly Cemented Rocks", "c' = 300 psf, Phi' = 35 deg"),
    ("B", "Weakly Cemented Rocks and Soils", "c' = 0, Phi' = 35 deg"),
    ("C", "Argillaceous Rocks", "c' = 0, Phi' = 20 deg"),
)

#: The groundwater states of Table 4-14. Two, and the manual names the two
#: physical conditions rather than a depth: dry is "groundwater below the level
#: of the slide", wet is "groundwater level at ground surface". There is no
#: intermediate and no default - a third of the table's cells change, so
#: choosing one silently would be choosing the answer (rule R3).
HAZUS_LANDSLIDE_MOISTURE = ("dry", "wet")

#: Table 4-14, "Landslide Susceptibility of Geologic Groups". Rows are
#: ``(group, moisture)``; the tuple is one category per slope band, in the band
#: order above. Read from the manual's Part (a) DRY block and Part (b) WET
#: block, three groups each.
HAZUS_LANDSLIDE_CATEGORY = {
    ("A", "dry"): ("None", "None", "I", "II", "IV", "VI"),
    ("B", "dry"): ("None", "III", "IV", "V", "VI", "VII"),
    ("C", "dry"): ("V", "VI", "VII", "IX", "IX", "IX"),
    ("A", "wet"): ("None", "III", "VI", "VII", "VIII", "VIII"),
    ("B", "wet"): ("V", "VIII", "IX", "IX", "IX", "X"),
    ("C", "wet"): ("VII", "IX", "X", "X", "X", "X"),
}

#: Table 4-15, "Lower Bounds for Slope Angles", in degrees, by
#: ``(group, moisture)``. Below the bound the manual establishes no
#: susceptibility at all: "To avoid calculating the occurrence of landslide for
#: very low or zero slope angles and critical accelerations, lower bounds for
#: slope angles and critical accelerations are established."
#:
#: This table and Table 4-14 overlap, and the overlap is checked in the test
#: suite rather than assumed: for groups A and B every band at or above the
#: bound already carries a category, and for group C (and B wet) the bound
#: cuts inside the 0-10 band, which is a resolution Table 4-14's six columns
#: cannot express on their own. That is what this table is for.
HAZUS_LANDSLIDE_SLOPE_BOUND_DEG = {
    ("A", "dry"): 15.0, ("A", "wet"): 10.0,
    ("B", "dry"): 10.0, ("B", "wet"): 5.0,
    ("C", "dry"): 5.0, ("C", "wet"): 3.0,
}

#: Table 4-15's second half, critical accelerations in g, by
#: ``(group, moisture)`` - the value of the Wilson & Keefer relationship at the
#: bound slope angle above. It is applied as a *floor* on the Table 4-16 value,
#: which is how the manual uses it ("lower bounds for slope angles and critical
#: accelerations"); across the whole table it changes exactly one cell, group B
#: wet above 40 degrees, where Table 4-16 gives category X at 0.05 g and this
#: floor lifts it to 0.10 g. The suite asserts that count of one, so a
#: transcription error in either table changes a number that is written down.
HAZUS_LANDSLIDE_AC_BOUND_G = {
    ("A", "dry"): 0.20, ("A", "wet"): 0.15,
    ("B", "dry"): 0.15, ("B", "wet"): 0.10,
    ("C", "dry"): 0.10, ("C", "wet"): 0.05,
}

#: Table 4-16, "Critical Accelerations (ac) for Susceptibility Categories", in
#: g. The manual prints the category row as
#: ``None  I  II  III  IV  V  VI  VII  VIII  IX  X`` against
#: ``None 0.60 0.50 0.40 0.35 0.30 0.25 0.20 0.15 0.10 0.05``. The leading
#: "None" is the word the manual prints in the value row, not a value, so
#: category None is absent from this dict rather than mapped to zero - a
#: critical acceleration of zero would send Equation 7 to infinity, and that is
#: the one thing a missing entry must never be allowed to become.
HAZUS_LANDSLIDE_AC_G = {
    "I": 0.60,
    "II": 0.50,
    "III": 0.40,
    "IV": 0.35,
    "V": 0.30,
    "VI": 0.25,
    "VII": 0.20,
    "VIII": 0.15,
    "IX": 0.10,
    "X": 0.05,
}

#: The susceptibility categories in the manual's own order, least susceptible
#: first. Category order is the one thing a reader is entitled to assume and
#: nothing in the arithmetic enforces it - two transposed entries would give a
#: plausible map with the colours in the wrong order - so the ordering is
#: tested in both directions.
HAZUS_LANDSLIDE_CATEGORIES = ("None",) + tuple(HAZUS_LANDSLIDE_AC_G)

#: Table 4-17, "Percentage of Map Area Having a Landslide-Susceptible Deposit",
#: as a fraction. This is the manual's second-order honesty: because the
#: Wilson & Keefer correlation is conservative, Hazus does not claim the whole
#: of a category-X map unit will fail, it claims 30 per cent of it is the kind
#: of deposit that could. Reported as its own column, never multiplied into the
#: displacement, because the two answer different questions and the manual
#: keeps them apart.
HAZUS_LANDSLIDE_AREA_FRACTION = {
    "None": 0.00,
    "I": 0.01,
    "II": 0.02,
    "III": 0.03,
    "IV": 0.05,
    "V": 0.08,
    "VI": 0.10,
    "VII": 0.15,
    "VIII": 0.20,
    "IX": 0.25,
    "X": 0.30,
}

#: Spellings accepted for the geologic group. The single letter, and the
#: manual's own name for the group, normalised. Nothing else: a geology column
#: of rock-type words is not this, and guessing which word is group B would be
#: picking a strength out of a dictionary.
HAZUS_LANDSLIDE_GROUP_ALIASES = {
    "a": "A",
    "strongly cemented": "A",
    "strongly cemented rocks": "A",
    "b": "B",
    "weakly cemented": "B",
    "weakly cemented rocks and soils": "B",
    "c": "C",
    "argillaceous": "C",
    "argillaceous rocks": "C",
}


def _normalise_word(value) -> str:
    """Lower-case, collapse whitespace, drop trailing punctuation."""
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().split()).rstrip(".")


def normalise_group(value):
    """A geologic group letter, or None when the value is not one.

    Accepts ``A``/``B``/``C`` in any case and the manual's own name for each
    group. Returns None rather than guessing: a critical acceleration comes out
    the other end of this, and the three groups span a factor of four in it.
    """
    return HAZUS_LANDSLIDE_GROUP_ALIASES.get(_normalise_word(value))


def normalise_moisture(value):
    """``"dry"`` or ``"wet"``, or None."""
    word = _normalise_word(value)
    return word if word in HAZUS_LANDSLIDE_MOISTURE else None


def normalise_susceptibility(value):
    """A susceptibility category from Table 4-16, or None.

    Accepts the Roman numerals ``I`` to ``X`` in any case and the word
    ``None``. It does **not** accept digits, and that refusal is deliberate:
    Hazus counts from I as the *least* susceptible, while a GIS column of
    1..10 was as likely written the other way round, and reading one as the
    other reverses the hazard. A refusal that lists what it found is the only
    answer that does not guess.
    """
    word = _normalise_word(value)
    if word == "none":
        return "None"
    upper = word.upper()
    return upper if upper in HAZUS_LANDSLIDE_AC_G else None


def hazard_rank(category: str) -> int:
    """Position of a category in Table 4-16's order; ``None`` ranks 0.

    The rank, not the acceleration: it is what the ordering checks compare, and
    it exists so that "more susceptible" is one integer rather than a float
    comparison against a table.
    """
    return HAZUS_LANDSLIDE_CATEGORIES.index(category)


def slope_band(slope_deg: float) -> int:
    """Index of the Table 4-14 band a slope angle falls in."""
    for index, (low, high) in enumerate(HAZUS_LANDSLIDE_BANDS_DEG):
        if low <= slope_deg < high:
            return index
    return len(HAZUS_LANDSLIDE_BANDS_DEG) - 1


def hazus_susceptibility(group: str, moisture: str, slope_deg: float) -> dict:
    """Table 4-14 through Table 4-17 for one site condition.

    Returns ``category``, ``ac_g`` (None when the manual assigns no
    susceptible deposit), ``area_fraction``, ``band`` and ``band_label`` for
    the slope, ``slope_bound_deg``, ``below_bound``, ``floor_applied`` and
    ``ac_floor_g``.

    ``ac_g`` is None rather than zero when the category is None, and that
    distinction is load-bearing: zero is what the displacement equation
    diverges on, so a "no susceptible deposit here" that arrived as a zero
    would turn the model's safest answer into its loudest one.
    """
    if (group, moisture) not in HAZUS_LANDSLIDE_CATEGORY:
        raise KeyError(f"no Table 4-14 row for group {group!r} {moisture!r}")

    bound = HAZUS_LANDSLIDE_SLOPE_BOUND_DEG[(group, moisture)]
    below_bound = slope_deg < bound
    index = slope_band(slope_deg)
    category = "None" if below_bound else HAZUS_LANDSLIDE_CATEGORY[
        (group, moisture)][index]

    ac_g = HAZUS_LANDSLIDE_AC_G.get(category)
    floor = HAZUS_LANDSLIDE_AC_BOUND_G[(group, moisture)]
    floor_applied = ac_g is not None and ac_g < floor
    if floor_applied:
        ac_g = floor

    return {
        "category": category,
        "ac_g": ac_g,
        "area_fraction": HAZUS_LANDSLIDE_AREA_FRACTION[category],
        "band": None if below_bound else index,
        "band_label": None if below_bound else HAZUS_LANDSLIDE_BAND_LABELS[index],
        "slope_bound_deg": bound,
        "below_bound": below_bound,
        "floor_applied": floor_applied,
        "ac_floor_g": floor,
    }


def ac_table_floor_conflicts() -> list:
    """Every ``(group, moisture, band)`` where Table 4-15's floor would bite.

    Written as a function rather than a constant so the suite can assert the
    *count*: across the two tables the floor changes exactly one cell, so a
    mistyped acceleration in either table moves a number the tests state
    outright. Returns a list of ``(group, moisture, band_index, ac_table,
    floor)``.
    """
    conflicts = []
    for group, _name, _strength in HAZUS_LANDSLIDE_GROUPS:
        for moisture in HAZUS_LANDSLIDE_MOISTURE:
            floor = HAZUS_LANDSLIDE_AC_BOUND_G[(group, moisture)]
            row = HAZUS_LANDSLIDE_CATEGORY[(group, moisture)]
            # The bands the slope bound leaves standing: a band whose *upper*
            # edge is above the bound still describes ground the bound does not
            # exclude, and its acceleration is the table's to floor. A band
            # that ends at or below the bound carries no category at all.
            bound = HAZUS_LANDSLIDE_SLOPE_BOUND_DEG[(group, moisture)]
            for index, category in enumerate(row):
                if HAZUS_LANDSLIDE_BANDS_DEG[index][1] <= bound:
                    continue
                value = HAZUS_LANDSLIDE_AC_G.get(category)
                if value is not None and value < floor:
                    conflicts.append((group, moisture, index, value, floor))
    return conflicts
