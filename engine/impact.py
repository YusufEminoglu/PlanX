# -*- coding: utf-8 -*-
"""Earthquake consequences for people: casualties and shelter need.

Source: Hazus Earthquake Model Technical Manual 6.1 (FEMA, 2024), Section 12
(casualties) and Section 13 (population displacement and shelter needs). The
equations are transcribed from the manual's own presentation - Equation 12-2
through 12-6 and 13-1 through 13-5 - and the rates from its tables. Nothing
here is recalled or fitted. Where the methodology wants data a Turkish study
area will not have, the term is still computed and its default is stated
rather than quietly replaced.

SCALE: A TRACT MODEL RUN PER BUILDING

Hazus works a Census tract at a time, from tract-level population and
building-stock aggregates. PlanX works a building at a time, so these
equations run per building with that building's own occupancy and population.
The arithmetic is unchanged and two consequences follow, both of which the
output should be read with.

* Table 12-2 distributes a *tract's* population component across occupancies.
  Per building we keep the two multipliers that between them decide how many
  people are in the building and how many are on the pavement outside it, and
  drop the row's secondary components - residents or hotel guests who happen
  to be inside a commercial premises, visitors, and the commuting population
  on the street. Those have no building to belong to here, so casualties come
  from each building's own occupancy rather than from the tract's mixing.
* Section 13 is about dwellings. A building with no dwelling units contributes
  no shelter need, which is what a non-residential occupancy is.

WHAT IS DELIBERATELY NOT HERE

The commuter path over bridges - Equation 12-1, the bridge rows of Tables 12-6
and 12-7 - and the street-population parameters PRFIL, VISIT and CDF. Both
need an inventory PlanX does not model: a bridge layer carrying damage states,
and a count of people on the street. They are left out rather than
approximated, and the tool's help says so.

THE EVENT TREE

Figure 12-1 branches damage state into collapse / no collapse at the Complete
state only, and the manual collapses that tree to a probability of being
killed (Equations 12-2 through 12-6). The same tree is used for all four
injury severities; only the branching rates change. Written out per severity:

    rate =  P(slight)   * r_slight
          + P(moderate) * r_moderate
          + P(extensive)* r_extensive
          + P(complete) * ( (1 - c) * r_complete_intact
                          +      c  * r_complete_collapsed )

with ``c`` the probability of collapse given the Complete state (Table 12-8),
and the four ``r``'s the four severity rates for that damage state. The
outdoor tree drops the slight branch and does not split on collapse: falling
material hurts people outside whether or not floors came down.
"""
from __future__ import annotations

import numpy as np

#: The 36 specific building types the Section 12 casualty tables are keyed
#: by, in the manual's own order. This is Hazus's type list, not the
#: shorter one the fragility tables in Section 5 use - every type
#: ``engine.seismic`` can produce is present here, and
#: ``tests/test_engine.py`` asserts that containment rather than trusting
#: it.
CASUALTY_BUILDING_TYPES = (
    "W1",
    "W2",
    "S1L",
    "S1M",
    "S1H",
    "S2L",
    "S2M",
    "S2H",
    "S3",
    "S4L",
    "S4M",
    "S4H",
    "S5L",
    "S5M",
    "S5H",
    "C1L",
    "C1M",
    "C1H",
    "C2L",
    "C2M",
    "C2H",
    "C3L",
    "C3M",
    "C3H",
    "PC1",
    "PC2L",
    "PC2M",
    "PC2H",
    "RM1L",
    "RM1M",
    "RM2L",
    "RM2M",
    "RM2H",
    "URML",
    "URMM",
    "MH",
)

# Table 12-3, manual p. 12-10. Percent of the indoor occupants of a building
#: in a SLIGHT structural damage state expected to be injured at each
#: severity. Uniform across building types: at low damage levels casualties
#: come from nonstructural components and contents, which do not vary much
#: with structural type (manual p. 12-9).
INDOOR_CASUALTY_RATES = {
    "W1": (0.05, 0.0, 0.0, 0.0),
    "W2": (0.05, 0.0, 0.0, 0.0),
    "S1L": (0.05, 0.0, 0.0, 0.0),
    "S1M": (0.05, 0.0, 0.0, 0.0),
    "S1H": (0.05, 0.0, 0.0, 0.0),
    "S2L": (0.05, 0.0, 0.0, 0.0),
    "S2M": (0.05, 0.0, 0.0, 0.0),
    "S2H": (0.05, 0.0, 0.0, 0.0),
    "S3": (0.05, 0.0, 0.0, 0.0),
    "S4L": (0.05, 0.0, 0.0, 0.0),
    "S4M": (0.05, 0.0, 0.0, 0.0),
    "S4H": (0.05, 0.0, 0.0, 0.0),
    "S5L": (0.05, 0.0, 0.0, 0.0),
    "S5M": (0.05, 0.0, 0.0, 0.0),
    "S5H": (0.05, 0.0, 0.0, 0.0),
    "C1L": (0.05, 0.0, 0.0, 0.0),
    "C1M": (0.05, 0.0, 0.0, 0.0),
    "C1H": (0.05, 0.0, 0.0, 0.0),
    "C2L": (0.05, 0.0, 0.0, 0.0),
    "C2M": (0.05, 0.0, 0.0, 0.0),
    "C2H": (0.05, 0.0, 0.0, 0.0),
    "C3L": (0.05, 0.0, 0.0, 0.0),
    "C3M": (0.05, 0.0, 0.0, 0.0),
    "C3H": (0.05, 0.0, 0.0, 0.0),
    "PC1": (0.05, 0.0, 0.0, 0.0),
    "PC2L": (0.05, 0.0, 0.0, 0.0),
    "PC2M": (0.05, 0.0, 0.0, 0.0),
    "PC2H": (0.05, 0.0, 0.0, 0.0),
    "RM1L": (0.05, 0.0, 0.0, 0.0),
    "RM1M": (0.05, 0.0, 0.0, 0.0),
    "RM2L": (0.05, 0.0, 0.0, 0.0),
    "RM2M": (0.05, 0.0, 0.0, 0.0),
    "RM2H": (0.05, 0.0, 0.0, 0.0),
    "URML": (0.05, 0.0, 0.0, 0.0),
    "URMM": (0.05, 0.0, 0.0, 0.0),
    "MH": (0.05, 0.0, 0.0, 0.0),
}

# Table 12-4, manual p. 12-12. Moderate structural damage, percent of indoor
#: occupants. Note URML/URMM carry the nonzero Severity 3 and 4 rates the
#: manual attributes to falling unreinforced masonry.
INDOOR_CASUALTY_RATES_MODERATE = {
    "W1": (0.25, 0.03, 0.0, 0.0),
    "W2": (0.2, 0.025, 0.0, 0.0),
    "S1L": (0.2, 0.025, 0.0, 0.0),
    "S1M": (0.2, 0.025, 0.0, 0.0),
    "S1H": (0.2, 0.025, 0.0, 0.0),
    "S2L": (0.2, 0.025, 0.0, 0.0),
    "S2M": (0.2, 0.025, 0.0, 0.0),
    "S2H": (0.2, 0.025, 0.0, 0.0),
    "S3": (0.2, 0.025, 0.0, 0.0),
    "S4L": (0.25, 0.03, 0.0, 0.0),
    "S4M": (0.25, 0.03, 0.0, 0.0),
    "S4H": (0.25, 0.03, 0.0, 0.0),
    "S5L": (0.2, 0.025, 0.0, 0.0),
    "S5M": (0.2, 0.025, 0.0, 0.0),
    "S5H": (0.2, 0.025, 0.0, 0.0),
    "C1L": (0.25, 0.03, 0.0, 0.0),
    "C1M": (0.25, 0.03, 0.0, 0.0),
    "C1H": (0.25, 0.03, 0.0, 0.0),
    "C2L": (0.25, 0.03, 0.0, 0.0),
    "C2M": (0.25, 0.03, 0.0, 0.0),
    "C2H": (0.25, 0.03, 0.0, 0.0),
    "C3L": (0.2, 0.025, 0.0, 0.0),
    "C3M": (0.2, 0.025, 0.0, 0.0),
    "C3H": (0.2, 0.025, 0.0, 0.0),
    "PC1": (0.25, 0.03, 0.0, 0.0),
    "PC2L": (0.25, 0.03, 0.0, 0.0),
    "PC2M": (0.25, 0.03, 0.0, 0.0),
    "PC2H": (0.25, 0.03, 0.0, 0.0),
    "RM1L": (0.2, 0.025, 0.0, 0.0),
    "RM1M": (0.2, 0.025, 0.0, 0.0),
    "RM2L": (0.2, 0.025, 0.0, 0.0),
    "RM2M": (0.2, 0.025, 0.0, 0.0),
    "RM2H": (0.2, 0.025, 0.0, 0.0),
    "URML": (0.35, 0.4, 0.001, 0.001),
    "URMM": (0.35, 0.4, 0.001, 0.001),
    "MH": (0.25, 0.03, 0.0, 0.0),
}

# Table 12-5, manual p. 12-13. Extensive structural damage, percent of indoor
#: occupants.
INDOOR_CASUALTY_RATES_EXTENSIVE = {
    "W1": (1.0, 0.1, 0.001, 0.001),
    "W2": (1.0, 0.1, 0.001, 0.001),
    "S1L": (1.0, 0.1, 0.001, 0.001),
    "S1M": (1.0, 0.1, 0.001, 0.001),
    "S1H": (1.0, 0.1, 0.001, 0.001),
    "S2L": (1.0, 0.1, 0.001, 0.001),
    "S2M": (1.0, 0.1, 0.001, 0.001),
    "S2H": (1.0, 0.1, 0.001, 0.001),
    "S3": (1.0, 0.1, 0.001, 0.001),
    "S4L": (1.0, 0.1, 0.001, 0.001),
    "S4M": (1.0, 0.1, 0.001, 0.001),
    "S4H": (1.0, 0.1, 0.001, 0.001),
    "S5L": (1.0, 0.1, 0.001, 0.001),
    "S5M": (1.0, 0.1, 0.001, 0.001),
    "S5H": (1.0, 0.1, 0.001, 0.001),
    "C1L": (1.0, 0.1, 0.001, 0.001),
    "C1M": (1.0, 0.1, 0.001, 0.001),
    "C1H": (1.0, 0.1, 0.001, 0.001),
    "C2L": (1.0, 0.1, 0.001, 0.001),
    "C2M": (1.0, 0.1, 0.001, 0.001),
    "C2H": (1.0, 0.1, 0.001, 0.001),
    "C3L": (1.0, 0.1, 0.001, 0.001),
    "C3M": (1.0, 0.1, 0.001, 0.001),
    "C3H": (1.0, 0.1, 0.001, 0.001),
    "PC1": (1.0, 0.1, 0.001, 0.001),
    "PC2L": (1.0, 0.1, 0.001, 0.001),
    "PC2M": (1.0, 0.1, 0.001, 0.001),
    "PC2H": (1.0, 0.1, 0.001, 0.001),
    "RM1L": (1.0, 0.1, 0.001, 0.001),
    "RM1M": (1.0, 0.1, 0.001, 0.001),
    "RM2L": (1.0, 0.1, 0.001, 0.001),
    "RM2M": (1.0, 0.1, 0.001, 0.001),
    "RM2H": (1.0, 0.1, 0.001, 0.001),
    "URML": (2.0, 0.2, 0.002, 0.002),
    "URMM": (2.0, 0.2, 0.002, 0.002),
    "MH": (1.0, 0.1, 0.001, 0.001),
}

# Table 12-6, manual p. 12-14. COMPLETE structural damage WITHOUT collapse,
#: percent of indoor occupants. Hazus assumes only a fraction of the
#: Complete state actually collapses; COLLAPSE_RATE_GIVEN_COMPLETE below is
#: that fraction, and it splits the Complete probability between this table
#: and the next.
INDOOR_CASUALTY_RATES_COMPLETE_INTACT = {
    "W1": (5.0, 1.0, 0.01, 0.01),
    "W2": (5.0, 1.0, 0.01, 0.01),
    "S1L": (5.0, 1.0, 0.01, 0.01),
    "S1M": (5.0, 1.0, 0.01, 0.01),
    "S1H": (5.0, 1.0, 0.01, 0.01),
    "S2L": (5.0, 1.0, 0.01, 0.01),
    "S2M": (5.0, 1.0, 0.01, 0.01),
    "S2H": (5.0, 1.0, 0.01, 0.01),
    "S3": (5.0, 1.0, 0.01, 0.01),
    "S4L": (5.0, 1.0, 0.01, 0.01),
    "S4M": (5.0, 1.0, 0.01, 0.01),
    "S4H": (5.0, 1.0, 0.01, 0.01),
    "S5L": (5.0, 1.0, 0.01, 0.01),
    "S5M": (5.0, 1.0, 0.01, 0.01),
    "S5H": (5.0, 1.0, 0.01, 0.01),
    "C1L": (5.0, 1.0, 0.01, 0.01),
    "C1M": (5.0, 1.0, 0.01, 0.01),
    "C1H": (5.0, 1.0, 0.01, 0.01),
    "C2L": (5.0, 1.0, 0.01, 0.01),
    "C2M": (5.0, 1.0, 0.01, 0.01),
    "C2H": (5.0, 1.0, 0.01, 0.01),
    "C3L": (5.0, 1.0, 0.01, 0.01),
    "C3M": (5.0, 1.0, 0.01, 0.01),
    "C3H": (5.0, 1.0, 0.01, 0.01),
    "PC1": (5.0, 1.0, 0.01, 0.01),
    "PC2L": (5.0, 1.0, 0.01, 0.01),
    "PC2M": (5.0, 1.0, 0.01, 0.01),
    "PC2H": (5.0, 1.0, 0.01, 0.01),
    "RM1L": (5.0, 1.0, 0.01, 0.01),
    "RM1M": (5.0, 1.0, 0.01, 0.01),
    "RM2L": (5.0, 1.0, 0.01, 0.01),
    "RM2M": (5.0, 1.0, 0.01, 0.01),
    "RM2H": (5.0, 1.0, 0.01, 0.01),
    "URML": (10.0, 2.0, 0.02, 0.02),
    "URMM": (10.0, 2.0, 0.02, 0.02),
    "MH": (5.0, 1.0, 0.01, 0.01),
}

# Table 12-7, manual p. 12-15. COMPLETE structural damage WITH collapse,
#: percent of indoor occupants. These are the rates the event tree calls
#: P_killed | Collapse (Equation 12-3).
INDOOR_CASUALTY_RATES_COMPLETE_COLLAPSED = {
    "W1": (40.0, 20.0, 3.0, 5.0),
    "W2": (40.0, 20.0, 5.0, 10.0),
    "S1L": (40.0, 20.0, 5.0, 10.0),
    "S1M": (40.0, 20.0, 5.0, 10.0),
    "S1H": (40.0, 20.0, 5.0, 10.0),
    "S2L": (40.0, 20.0, 5.0, 10.0),
    "S2M": (40.0, 20.0, 5.0, 10.0),
    "S2H": (40.0, 20.0, 5.0, 10.0),
    "S3": (40.0, 20.0, 3.0, 5.0),
    "S4L": (40.0, 20.0, 5.0, 10.0),
    "S4M": (40.0, 20.0, 5.0, 10.0),
    "S4H": (40.0, 20.0, 5.0, 10.0),
    "S5L": (40.0, 20.0, 5.0, 10.0),
    "S5M": (40.0, 20.0, 5.0, 10.0),
    "S5H": (40.0, 20.0, 5.0, 10.0),
    "C1L": (40.0, 20.0, 5.0, 10.0),
    "C1M": (40.0, 20.0, 5.0, 10.0),
    "C1H": (40.0, 20.0, 5.0, 10.0),
    "C2L": (40.0, 20.0, 5.0, 10.0),
    "C2M": (40.0, 20.0, 5.0, 10.0),
    "C2H": (40.0, 20.0, 5.0, 10.0),
    "C3L": (40.0, 20.0, 5.0, 10.0),
    "C3M": (40.0, 20.0, 5.0, 10.0),
    "C3H": (40.0, 20.0, 5.0, 10.0),
    "PC1": (40.0, 20.0, 5.0, 10.0),
    "PC2L": (40.0, 20.0, 5.0, 10.0),
    "PC2M": (40.0, 20.0, 5.0, 10.0),
    "PC2H": (40.0, 20.0, 5.0, 10.0),
    "RM1L": (40.0, 20.0, 5.0, 10.0),
    "RM1M": (40.0, 20.0, 5.0, 10.0),
    "RM2L": (40.0, 20.0, 5.0, 10.0),
    "RM2M": (40.0, 20.0, 5.0, 10.0),
    "RM2H": (40.0, 20.0, 5.0, 10.0),
    "URML": (40.0, 20.0, 5.0, 10.0),
    "URMM": (40.0, 20.0, 5.0, 10.0),
    "MH": (40.0, 20.0, 3.0, 5.0),
}

# Table 12-9, manual p. 12-18. Moderate structural damage, percent of the
#: people outside and close to the building. Slight damage generates no
#: outdoor casualties at all (manual p. 12-18), which is why there is no
#: table for it.
OUTDOOR_CASUALTY_RATES_MODERATE = {
    "W1": (0.05, 0.005, 0.0001, 0.0001),
    "W2": (0.05, 0.005, 0.0, 0.0),
    "S1L": (0.05, 0.005, 0.0, 0.0),
    "S1M": (0.05, 0.005, 0.0, 0.0),
    "S1H": (0.05, 0.005, 0.0, 0.0),
    "S2L": (0.05, 0.005, 0.0, 0.0),
    "S2M": (0.05, 0.005, 0.0, 0.0),
    "S2H": (0.05, 0.005, 0.0, 0.0),
    "S3": (0.0, 0.0, 0.0, 0.0),
    "S4L": (0.05, 0.005, 0.0, 0.0),
    "S4M": (0.05, 0.005, 0.0, 0.0),
    "S4H": (0.05, 0.005, 0.0, 0.0),
    "S5L": (0.05, 0.005, 0.0, 0.0),
    "S5M": (0.05, 0.005, 0.0, 0.0),
    "S5H": (0.05, 0.005, 0.0, 0.0),
    "C1L": (0.05, 0.005, 0.0, 0.0),
    "C1M": (0.05, 0.005, 0.0, 0.0),
    "C1H": (0.05, 0.005, 0.0, 0.0),
    "C2L": (0.05, 0.005, 0.0, 0.0),
    "C2M": (0.05, 0.005, 0.0, 0.0),
    "C2H": (0.05, 0.005, 0.0, 0.0),
    "C3L": (0.05, 0.005, 0.0, 0.0),
    "C3M": (0.05, 0.005, 0.0, 0.0),
    "C3H": (0.05, 0.005, 0.0, 0.0),
    "PC1": (0.05, 0.005, 0.0, 0.0),
    "PC2L": (0.05, 0.005, 0.0, 0.0),
    "PC2M": (0.05, 0.005, 0.0, 0.0),
    "PC2H": (0.05, 0.005, 0.0, 0.0),
    "RM1L": (0.05, 0.005, 0.0, 0.0),
    "RM1M": (0.05, 0.005, 0.0, 0.0),
    "RM2L": (0.05, 0.005, 0.0, 0.0),
    "RM2M": (0.05, 0.005, 0.0, 0.0),
    "RM2H": (0.05, 0.005, 0.0, 0.0),
    "URML": (0.15, 0.015, 0.0003, 0.0003),
    "URMM": (0.15, 0.015, 0.0003, 0.0003),
    "MH": (0.0, 0.0, 0.0, 0.0),
}

# Table 12-10, manual p. 12-19. Extensive structural damage, percent of the
#: people outside and close to the building.
OUTDOOR_CASUALTY_RATES_EXTENSIVE = {
    "W1": (0.3, 0.03, 0.0003, 0.0003),
    "W2": (0.3, 0.03, 0.0003, 0.0003),
    "S1L": (0.1, 0.01, 0.0001, 0.0001),
    "S1M": (0.2, 0.02, 0.0002, 0.0002),
    "S1H": (0.3, 0.03, 0.0003, 0.0003),
    "S2L": (0.1, 0.01, 0.0001, 0.0001),
    "S2M": (0.2, 0.02, 0.0002, 0.0002),
    "S2H": (0.3, 0.03, 0.0003, 0.0003),
    "S3": (0.0, 0.0, 0.0, 0.0),
    "S4L": (0.1, 0.01, 0.0001, 0.0001),
    "S4M": (0.2, 0.02, 0.0002, 0.0002),
    "S4H": (0.3, 0.03, 0.0003, 0.0003),
    "S5L": (0.2, 0.02, 0.0002, 0.0002),
    "S5M": (0.4, 0.04, 0.0004, 0.0004),
    "S5H": (0.6, 0.06, 0.0006, 0.0006),
    "C1L": (0.1, 0.01, 0.0001, 0.0001),
    "C1M": (0.2, 0.02, 0.0002, 0.0002),
    "C1H": (0.3, 0.03, 0.0003, 0.0003),
    "C2L": (0.1, 0.01, 0.0001, 0.0001),
    "C2M": (0.2, 0.02, 0.0002, 0.0002),
    "C2H": (0.3, 0.03, 0.0003, 0.0003),
    "C3L": (0.2, 0.02, 0.0002, 0.0002),
    "C3M": (0.4, 0.04, 0.0004, 0.0004),
    "C3H": (0.6, 0.06, 0.0006, 0.0006),
    "PC1": (0.2, 0.02, 0.0002, 0.0002),
    "PC2L": (0.1, 0.01, 0.0001, 0.0001),
    "PC2M": (0.2, 0.02, 0.0002, 0.0002),
    "PC2H": (0.3, 0.03, 0.0003, 0.0003),
    "RM1L": (0.2, 0.02, 0.0002, 0.0002),
    "RM1M": (0.3, 0.03, 0.0003, 0.0003),
    "RM2L": (0.2, 0.02, 0.0002, 0.0002),
    "RM2M": (0.3, 0.03, 0.0003, 0.0003),
    "RM2H": (0.4, 0.04, 0.0004, 0.0004),
    "URML": (0.6, 0.06, 0.0006, 0.0006),
    "URMM": (0.6, 0.06, 0.0006, 0.0006),
    "MH": (0.0, 0.0, 0.0, 0.0),
}

# Table 12-11, manual p. 12-20. Complete structural damage, percent of the
#: people outside and close to the building. The outdoor event tree does
#: NOT branch on collapse - falling material hurts people outside whether or
#: not floors came down (manual p. 12-18).
OUTDOOR_CASUALTY_RATES_COMPLETE = {
    "W1": (2.0, 0.5, 0.1, 0.05),
    "W2": (2.0, 0.5, 0.1, 0.05),
    "S1L": (2.0, 0.5, 0.1, 0.1),
    "S1M": (2.2, 0.7, 0.2, 0.2),
    "S1H": (2.5, 1.0, 0.3, 0.3),
    "S2L": (2.0, 0.5, 0.1, 0.1),
    "S2M": (2.2, 0.7, 0.2, 0.2),
    "S2H": (2.5, 1.0, 0.3, 0.3),
    "S3": (0.01, 0.001, 0.001, 0.01),
    "S4L": (2.0, 0.5, 0.1, 0.1),
    "S4M": (2.2, 0.7, 0.2, 0.2),
    "S4H": (2.5, 1.0, 0.3, 0.3),
    "S5L": (2.7, 1.0, 0.2, 0.3),
    "S5M": (3.0, 1.2, 0.3, 0.4),
    "S5H": (3.3, 1.4, 0.4, 0.6),
    "C1L": (2.0, 0.5, 0.1, 0.1),
    "C1M": (2.2, 0.7, 0.2, 0.2),
    "C1H": (2.5, 1.0, 0.3, 0.3),
    "C2L": (2.0, 0.5, 0.1, 0.1),
    "C2M": (2.2, 0.7, 0.2, 0.2),
    "C2H": (2.5, 1.0, 0.3, 0.3),
    "C3L": (2.7, 1.0, 0.2, 0.3),
    "C3M": (3.0, 1.2, 0.3, 0.4),
    "C3H": (3.3, 1.4, 0.4, 0.6),
    "PC1": (2.0, 0.5, 0.1, 0.1),
    "PC2L": (2.7, 1.0, 0.2, 0.3),
    "PC2M": (3.0, 1.2, 0.3, 0.4),
    "PC2H": (3.3, 1.4, 0.4, 0.6),
    "RM1L": (2.0, 0.5, 0.1, 0.1),
    "RM1M": (2.2, 0.7, 0.2, 0.2),
    "RM2L": (2.0, 0.5, 0.1, 0.1),
    "RM2M": (2.2, 0.7, 0.2, 0.2),
    "RM2H": (2.5, 1.0, 0.3, 0.3),
    "URML": (5.0, 2.0, 0.4, 0.6),
    "URMM": (5.0, 2.0, 0.4, 0.6),
    "MH": (0.01, 0.001, 0.001, 0.01),
}

#: Table 12-8, manual p. 12-16. Probability that a building in the Complete
#: damage state has actually collapsed, by specific building type.
#: Fraction, not percent. The manual's footnotes point back to
#: Section 5 for the derivation.
COLLAPSE_RATE_GIVEN_COMPLETE = {
    "W1": 0.03,
    "W2": 0.03,
    "S1L": 0.08,
    "S1M": 0.05,
    "S1H": 0.03,
    "S2L": 0.08,
    "S2M": 0.05,
    "S2H": 0.03,
    "S3": 0.03,
    "S4L": 0.08,
    "S4M": 0.05,
    "S4H": 0.03,
    "S5L": 0.08,
    "S5M": 0.05,
    "S5H": 0.03,
    "C1L": 0.13,
    "C1M": 0.1,
    "C1H": 0.05,
    "C2L": 0.13,
    "C2M": 0.1,
    "C2H": 0.05,
    "C3L": 0.15,
    "C3M": 0.13,
    "C3H": 0.1,
    "PC1": 0.15,
    "PC2L": 0.15,
    "PC2M": 0.13,
    "PC2H": 0.1,
    "RM1L": 0.13,
    "RM1M": 0.1,
    "RM2L": 0.13,
    "RM2M": 0.1,
    "RM2H": 0.05,
    "URML": 0.15,
    "URMM": 0.15,
    "MH": 0.03,
}


# -------------------------------------------------------------------------- #
# Table 12-2: where the people are
# -------------------------------------------------------------------------- #
#: Scenario times Hazus computes, as (key, label). The keys index the table
#: below; the labels are what the algorithm shows.
SCENARIO_TIMES = (
    ("2am", "2:00 a.m. - night"),
    ("2pm", "2:00 p.m. - daytime"),
    ("5pm", "5:00 p.m. - commute time"),
)

#: Hazus's five building occupancy classes, as the algorithm offers them.
OCCUPANCY_CLASSES = (
    ("Residential", "Residential"),
    ("Commercial", "Commercial"),
    ("Educational", "Educational"),
    ("Industrial", "Industrial"),
    ("Hotels", "Hotels"),
)

#: Occupancy class names, in table order.
OCCUPANCY_CLASSES_KEYS = tuple(name for name, _label in OCCUPANCY_CLASSES)

#: Table 12-2 (manual p. 12-5), reduced to the two numbers that matter for a
#: single building: the share of the building's occupant count that is inside,
#: and the share that is outside and close to it. The manual writes each entry
#: as two multipliers - the first splits a population component between
#: indoors and outdoors, the second is the fraction of that component present
#: in the occupancy at all - and the products below are written as the manual
#: prints them rather than evaluated, so a reader can check them against the
#: page.
#:
#: The primary component of each row is used: NRES for residential, COMW for
#: commercial, INDW for industrial, HOTEL for hotels, GRADE for educational.
#: The rows also carry residents, hotel guests and visitors inside commercial
#: premises and a commuting population on the street; those are tract-level
#: mixing with no building to belong to in a per-building model, and are
#: documented as absent in the module docstring.
#:
#: Educational has no entry at all for the 2 a.m. scenario - the table's
#: nighttime column is blank - so a school holds nobody at 2 a.m. Its 5 p.m.
#: entry covers the college population only, the grade-school population
#: having gone home; the grade-school entry at 2 p.m. is the one used for the
#: daytime scenario.
POPULATION_DISTRIBUTION = {
    "Residential": {
        "2am": (0.999 * 0.99, 0.001 * 0.99),
        "2pm": (0.70 * 0.75, 0.30 * 0.75),
        "5pm": (0.70 * 0.50, 0.30 * 0.50),
    },
    "Commercial": {
        "2am": (0.999 * 0.02, 0.001 * 0.02),
        "2pm": (0.99 * 0.98, 0.01 * 0.98),
        "5pm": (0.98 * 0.50, 0.02 * 0.50),
    },
    "Educational": {
        "2am": (0.0, 0.0),
        "2pm": (0.90 * 0.80, 0.10 * 0.80),
        "5pm": (0.80 * 0.50, 0.20 * 0.50),
    },
    "Industrial": {
        "2am": (0.999 * 0.10, 0.001 * 0.10),
        "2pm": (0.90 * 0.80, 0.10 * 0.80),
        "5pm": (0.90 * 0.50, 0.10 * 0.50),
    },
    "Hotels": {
        "2am": (0.999, 0.001),
        "2pm": (0.19, 0.01),
        "5pm": (0.299, 0.001),
    },
}

#: Text an occupancy field might carry, mapped to a Hazus class. Matched
#: longest-token-first so that "kindergarten" reaches Educational rather than
#: being caught by "ind" on its way to Industrial.
_OCCUPANCY_TOKENS = tuple(sorted((
    ("resident", "Residential"),
    ("res", "Residential"),
    ("house", "Residential"),
    ("apartment", "Residential"),
    ("konut", "Residential"),
    ("commerc", "Commercial"),
    ("comm", "Commercial"),
    ("retail", "Commercial"),
    ("office", "Commercial"),
    ("shop", "Commercial"),
    ("market", "Commercial"),
    ("kindergarten", "Educational"),
    ("school", "Educational"),
    ("college", "Educational"),
    ("universit", "Educational"),
    ("educat", "Educational"),
    ("educ", "Educational"),
    ("industrial", "Industrial"),
    ("factory", "Industrial"),
    ("warehouse", "Industrial"),
    ("workshop", "Industrial"),
    ("industr", "Industrial"),
    ("ind", "Industrial"),
    ("hotel", "Hotels"),
    ("motel", "Hotels"),
    ("hostel", "Hotels"),
    ("lodging", "Hotels"),
), key=lambda pair: -len(pair[0])))


def occupancy_class(value):
    """Hazus occupancy class for a text value, or ``None`` if unrecognised.

    The tool reads occupancy from a field when one is given, because a city is
    not one occupancy class. Returning ``None`` rather than guessing lets the
    caller count the unmatched features and say so, instead of silently
    treating a hospital as a house.
    """
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    for token, name in _OCCUPANCY_TOKENS:
        if token in text:
            return name
    return None


# -------------------------------------------------------------------------- #
# Lookups
# -------------------------------------------------------------------------- #
def _matrix(table):
    """The table as a (36, 4) float array in CASUALTY_BUILDING_TYPES order."""
    return np.array([table[label] for label in CASUALTY_BUILDING_TYPES],
                    dtype=np.float64)


_LABEL_INDEX = {label: index for index, label in enumerate(CASUALTY_BUILDING_TYPES)}
_M_INDOOR_SLIGHT = _matrix(INDOOR_CASUALTY_RATES)
_M_INDOOR_MODERATE = _matrix(INDOOR_CASUALTY_RATES_MODERATE)
_M_INDOOR_EXTENSIVE = _matrix(INDOOR_CASUALTY_RATES_EXTENSIVE)
_M_INDOOR_COMPLETE_INTACT = _matrix(INDOOR_CASUALTY_RATES_COMPLETE_INTACT)
_M_INDOOR_COMPLETE_COLLAPSED = _matrix(INDOOR_CASUALTY_RATES_COMPLETE_COLLAPSED)
_M_OUTDOOR_MODERATE = _matrix(OUTDOOR_CASUALTY_RATES_MODERATE)
_M_OUTDOOR_EXTENSIVE = _matrix(OUTDOOR_CASUALTY_RATES_EXTENSIVE)
_M_OUTDOOR_COMPLETE = _matrix(OUTDOOR_CASUALTY_RATES_COMPLETE)
_M_COLLAPSE = np.array([COLLAPSE_RATE_GIVEN_COMPLETE[label]
                        for label in CASUALTY_BUILDING_TYPES], dtype=np.float64)

#: (probability key, rate matrix, which side of the collapse branch)
_INDOOR_TERMS = (
    ("slight", _M_INDOOR_SLIGHT, None),
    ("moderate", _M_INDOOR_MODERATE, None),
    ("extensive", _M_INDOOR_EXTENSIVE, None),
    ("complete", _M_INDOOR_COMPLETE_INTACT, "intact"),
    ("complete", _M_INDOOR_COMPLETE_COLLAPSED, "collapsed"),
)

_OUTDOOR_TERMS = (
    ("moderate", _M_OUTDOOR_MODERATE),
    ("extensive", _M_OUTDOOR_EXTENSIVE),
    ("complete", _M_OUTDOOR_COMPLETE),
)


def _rows(matrix, labels, shape):
    """(shape + (4,)) block of table rows for an array of building types."""
    flat = np.asarray(labels, dtype=object).ravel().tolist()
    indices = []
    for name in flat:
        try:
            indices.append(_LABEL_INDEX[str(name)])
        except KeyError:
            raise KeyError(
                f"No Hazus casualty rates for building type '{name}'. The "
                f"Section 12 tables cover {len(CASUALTY_BUILDING_TYPES)} types: "
                f"{', '.join(CASUALTY_BUILDING_TYPES)}.") from None
    picked = matrix.take(np.array(indices, dtype=np.intp), axis=0)
    return picked.reshape(tuple(shape) + (matrix.shape[1],))


def _collapse_rates(labels, shape):
    """Probability of collapse given Complete damage, per building."""
    return _rows(_M_COLLAPSE[:, None], labels, shape)[..., 0]


def fill_undamaged(probabilities):
    """Complete a damage distribution with the undamaged share it implies.

    A fragility run writes four columns - slight, moderate, extensive,
    complete - and the share of buildings that are simply not damaged is
    their complement. The event tree indexes the distribution by state, so a
    caller that hands over only the four damaged states has no ``none`` to
    read; what it has is arithmetic that belongs in one place rather than in
    each caller.

    The complement is clipped at zero, so a row whose damaged states already
    sum above 1.0 gets no undamaged share instead of a negative one. That row
    is still a mistake, and the caller that reads these columns warns about
    it - this function is not a place to hide it.

    A distribution that already carries ``none`` is returned as it is, so a
    caller may hand over either shape.
    """
    if "none" in probabilities:
        return dict(probabilities)
    damaged = np.zeros(np.shape(next(iter(probabilities.values()))),
                       dtype=np.float64)
    for values in probabilities.values():
        damaged = damaged + np.asarray(values, dtype=np.float64)
    completed = dict(probabilities)
    completed["none"] = np.clip(1.0 - damaged, 0.0, 1.0)
    return completed


def _shape_of(probabilities):
    return np.shape(probabilities["complete"])


def _probability(probabilities, key, shape):
    values = np.asarray(probabilities[key], dtype=np.float64)
    return np.broadcast_to(values, shape)


# -------------------------------------------------------------------------- #
# Casualties
# -------------------------------------------------------------------------- #
def indoor_rates(probabilities, labels):
    """Indoor casualty rate per severity, per building.

    Shape ``(..., 4)``: severity 1, 2, 3, 4 in Hazus's order (Table 12-1 - the
    fourth is "instantaneously killed or mortally injured"). Each value is the
    probability that one occupant of the building is hurt at that severity, so
    multiplying by the number of occupants indoors gives expected casualties.
    """
    shape = _shape_of(probabilities)
    collapse = _collapse_rates(labels, shape)
    total = np.zeros(tuple(shape) + (4,), dtype=np.float64)
    for key, matrix, branch in _INDOOR_TERMS:
        weight = _probability(probabilities, key, shape)
        if branch == "intact":
            weight = weight * (1.0 - collapse)
        elif branch == "collapsed":
            weight = weight * collapse
        total += weight[..., None] * _rows(matrix, labels, shape)
    return total / 100.0


def outdoor_rates(probabilities, labels):
    """Outdoor casualty rate per severity, per building. Shape ``(..., 4)``.

    Falling material - parapets, infill, glazing, signage - hurts people on
    the pavement beside the building. Slight damage contributes nothing: the
    manual drops that branch from the outdoor tree entirely, and there is no
    table for it. Complete damage is not split by collapse here either, so the
    Complete probability enters once.
    """
    shape = _shape_of(probabilities)
    total = np.zeros(tuple(shape) + (4,), dtype=np.float64)
    for key, matrix in _OUTDOOR_TERMS:
        weight = _probability(probabilities, key, shape)
        total += weight[..., None] * _rows(matrix, labels, shape)
    return total / 100.0


def population_distribution(occupancy, time_of_day):
    """(indoor, outdoor) shares of a building's occupant count, Table 12-2.

    ``occupancy`` is a sequence of Hazus occupancy class names and
    ``time_of_day`` one of the keys of SCENARIO_TIMES. Both returned arrays
    match the input length.
    """
    names = np.atleast_1d(np.asarray(occupancy, dtype=object))
    for name in names.ravel().tolist():
        if str(name) not in POPULATION_DISTRIBUTION:
            raise KeyError(
                f"Unknown occupancy class '{name}'. Expected one of "
                f"{', '.join(OCCUPANCY_CLASSES_KEYS)}.")
    if time_of_day not in POPULATION_DISTRIBUTION["Residential"]:
        raise KeyError(
            f"Unknown scenario time '{time_of_day}'. Expected one of "
            f"{', '.join(key for key, _label in SCENARIO_TIMES)}.")
    indoor = np.empty(names.shape, dtype=np.float64)
    outdoor = np.empty(names.shape, dtype=np.float64)
    for index, name in enumerate(names.ravel().tolist()):
        pair = POPULATION_DISTRIBUTION[str(name)][time_of_day]
        indoor.ravel()[index] = pair[0]
        outdoor.ravel()[index] = pair[1]
    return indoor, outdoor


def casualties(probabilities, labels, occupants, occupancy, time_of_day):
    """Expected casualties per severity, indoors and out.

    ``occupants`` is each building's occupant count - the number of people the
    building holds when it is occupied at all, not the number present at the
    scenario time. Table 12-2 scales it: a school holds nobody at 2 a.m. and a
    hotel holds a fifth of its guests at 2 p.m.

    Returns ``{"indoor": (..., 4), "outdoor": (..., 4), "total": (..., 4)}``
    in counts of people. Every entry is bounded by the number of occupants the
    scenario time puts in the building, which is the conservation property the
    tests assert.
    """
    shape = _shape_of(probabilities)
    occupants = np.broadcast_to(np.asarray(occupants, dtype=np.float64), shape)
    indoor_share, outdoor_share = population_distribution(
        occupancy, time_of_day)

    indoor = indoor_rates(probabilities, labels) * (occupants * indoor_share)[..., None]
    outdoor = outdoor_rates(probabilities, labels) * (occupants * outdoor_share)[..., None]
    return {"indoor": indoor, "outdoor": outdoor, "total": indoor + outdoor}


def occupants_from_floor_area(areas, floors, area_per_occupant):
    """Occupants of a building from its footprint and storey count.

    Not a Hazus relationship. Hazus's area-per-occupant figures live in the
    Hazus Inventory Technical Manual, which this module does not carry, so the
    divisor is the caller's - a label on a screening assumption, in the same
    spirit as the nominal reference PGA the damage model falls back to. Use a
    population field instead whenever one exists.
    """
    if area_per_occupant <= 0.0:
        raise ValueError("area_per_occupant must be positive")
    return (np.asarray(areas, dtype=np.float64)
            * np.asarray(floors, dtype=np.float64) / float(area_per_occupant))


# -------------------------------------------------------------------------- #
# Shelter
# -------------------------------------------------------------------------- #
#: Table 13-1 (manual p. 13-3), default displaced-household damage-state
#: weighting factors. Single-family Complete and multi-family Extensive and
#: Complete are the states that displace a household; the manual's reasoning is
#: that a single-family occupant tolerates most damage, while a *renter* in a
#: moderately or extensively damaged block may read it as uninhabitable.
DISPLACED_HOUSEHOLD_WEIGHTS = {
    "single_moderate": 0.0,
    "single_extensive": 0.0,
    "single_complete": 1.0,
    "multi_moderate": 0.0,
    "multi_extensive": 0.9,
    "multi_complete": 1.0,
}

#: Table 13-2 (manual p. 13-6), shelter category weighting factors. They sum
#: to 1.00, which is what makes a neutral run come out at exactly 1.0.
SHELTER_CATEGORY_WEIGHTS = {
    "income": 0.73,
    "ethnicity": 0.27,
    "ownership": 0.0,
    "age": 0.0,
}

#: Table 13-3 (manual p. 13-6), shelter modification factors: the share of each
#: sub-category that seeks public shelter, from the Red Cross/GWU work Hazus
#: cites. Quoted so that a planner can see what the methodology's own
#: US-calibrated answer looks like, and so the manual's numbers are in the code
#: rather than only in a document. They are NOT the defaults - see below.
SHELTER_MODIFICATION_FACTORS = {
    "income": {"under_10k": 0.62, "10k_to_20k": 0.42, "20k_to_30k": 0.29,
               "30k_to_40k": 0.22, "over_40k": 0.13},
    "ethnicity": {"white": 0.24, "black": 0.48, "hispanic": 0.47,
                  "asian": 0.26, "native_american": 0.26},
    "ownership": {"owner": 0.40, "renter": 0.40},
    "age": {"under_16": 0.40, "16_to_65": 0.40, "over_65": 0.40},
}

#: The modification factor a run with no local demographic data uses.
#:
#: Exactly 1.0, and that is the point: Hazus's Equation 13-5 is
#:
#:     alpha = IW*IM + EW*EM + OW*OM + AW*AM
#:
#: with the shares within each category summing to one. At a neutral factor
#: every category's share-weighted mean is 1.0, so alpha collapses to
#: IW + EW + OW + AW = 1.0 whatever the shares are - every displaced person
#: seeks public shelter. That is an upper bound, not Hazus's expectation:
#: Hazus's own Table 13-3 factors run from 0.13 to 0.62 and pull a real
#: estimate well below the neutral one. A planner who has income, ethnicity,
#: tenure or age distribution for the study area should put the category's
#: share-weighted mean factor in and get a filtered answer; a planner who does
#: not gets an unfiltered one, which is the honest outcome, not an American
#: one.
NEUTRAL_SHELTER_MODIFIER = 1.0


def shelter_alpha(weights=None, modifiers=None):
    """The constant alpha of Equations 13-4 and 13-5.

    ``weights`` is (income, ethnicity, ownership, age) - Table 13-2's IW, EW,
    OW, AW - and ``modifiers`` is the matching set of category factors. The
    manual's expansion of alpha over five income classes, five ethnicities,
    two tenure classes and three age classes is a share-weighted mean inside
    each category, collapsed here to the mean itself so that the tool asks for
    four numbers instead of fifteen. With neutral modifiers the result is
    exactly 1.0 for any weights that sum to 1.0.
    """
    if weights is None:
        weights = tuple(SHELTER_CATEGORY_WEIGHTS[name]
                        for name in ("income", "ethnicity", "ownership", "age"))
    if modifiers is None:
        modifiers = (NEUTRAL_SHELTER_MODIFIER,) * 4
    return float(sum(float(weight) * float(modifier)
                     for weight, modifier in zip(weights, modifiers)))


def displaced_households(probabilities, units, occupancy_rate=1.0):
    """Displaced households per building, Equations 13-1 to 13-3.

    ``units`` is the building's dwelling units and ``occupancy_rate`` the
    manual's ``#HH / (#SFU + #MFU)`` - households per dwelling unit, 1.0 when
    every unit is lived in. A building of one unit is treated as single-family
    and a building of two or more as multi-family, which is how Hazus splits
    its residential occupancy classes (RES1 against RES3).

    A non-residential building has no dwelling units, so it passes zero and
    drops out of the sum: the equations still hold, they just have nothing to
    count.
    """
    shape = _shape_of(probabilities)
    units = np.broadcast_to(np.asarray(units, dtype=np.float64), shape)
    complete = _probability(probabilities, "complete", shape)
    extensive = _probability(probabilities, "extensive", shape)
    single = units <= 1.0
    pct_single = DISPLACED_HOUSEHOLD_WEIGHTS["single_complete"] * complete
    pct_multi = (DISPLACED_HOUSEHOLD_WEIGHTS["multi_extensive"] * extensive
                 + DISPLACED_HOUSEHOLD_WEIGHTS["multi_complete"] * complete)
    uninhabitable = np.where(single, units * pct_single, units * pct_multi)
    return uninhabitable * float(occupancy_rate)


def shelter_need(displaced, occupants, units, occupancy_rate=1.0, alpha=1.0):
    """People needing public short-term shelter, Equations 13-4 and 13-5.

    ``#DH * (POP / #HH) * alpha`` per building, with POP the people in the
    building and #HH its households. The double sum of Equation 13-4 reduces
    to this product because the category shares each sum to one; the argument
    is in ``shelter_alpha``.
    """
    units = np.broadcast_to(np.asarray(units, dtype=np.float64), _shape_of(
        {"complete": displaced}))
    households = units * float(occupancy_rate)
    people = np.broadcast_to(np.asarray(occupants, dtype=np.float64), households.shape)
    # A building with no households has no displaced household either, so the
    # ratio is undefined there and the product is zero by construction rather
    # than by a guard that lets a NaN through.
    per_household = np.divide(people, households,
                              out=np.zeros_like(households), where=households > 0.0)
    return np.asarray(displaced, dtype=np.float64) * per_household * float(alpha)


def shelter(probabilities, occupants, units, occupancy_rate=1.0, alpha=1.0):
    """Both Section 13 outputs: displaced households and public shelter need."""
    displaced = displaced_households(probabilities, units, occupancy_rate)
    return {
        "displaced_households": displaced,
        "public_shelter": shelter_need(displaced, occupants, units,
                                       occupancy_rate, alpha),
    }
