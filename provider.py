# -*- coding: utf-8 -*-
"""Processing provider for PlanX - Urban Analytics Studio."""
from __future__ import annotations

import os

from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsProcessingProvider

from .algorithms.alg_prepare_network import PrepareNetworkAlgorithm
from .algorithms.alg_od_matrix import ODCostMatrixAlgorithm
from .algorithms.alg_service_areas import ServiceAreasAlgorithm
from .algorithms.alg_nearest_facility import NearestFacilityAlgorithm
from .algorithms.alg_node_centrality import NetworkCentralityAlgorithm
from .algorithms.alg_space_syntax import SpaceSyntaxAlgorithm
from .algorithms.alg_building_metrics import BuildingFormMetricsAlgorithm
from .algorithms.alg_tessellation import MorphologicalTessellationAlgorithm
from .algorithms.alg_spacematrix import SpacematrixDensityAlgorithm
from .algorithms.alg_street_morphology import StreetNetworkMorphologyAlgorithm
from .algorithms.alg_access_score import MultiAmenityAccessAlgorithm
from .algorithms.alg_shadow_casting import ShadowCastingAlgorithm
from .algorithms.alg_sky_view_factor import SkyViewFactorAlgorithm
from .algorithms.alg_frontal_area import FrontalAreaIndexAlgorithm
from .algorithms.alg_sun_hours import SunHoursAlgorithm
from .algorithms.alg_solar_irradiation import SolarIrradiationAlgorithm
from .algorithms.alg_annual_solar import AnnualSolarAlgorithm
from .algorithms.alg_heat_risk import HeatRiskGridAlgorithm
from .algorithms.alg_landuse_balance import LandUseBalanceAlgorithm
from .algorithms.alg_facility_adequacy import FacilityAdequacyAlgorithm
from .algorithms.alg_density_grid import DensityGridAlgorithm
from .algorithms.alg_performance_report import PlanPerformanceReportAlgorithm
from .algorithms.alg_facility_location import FacilityLocationAlgorithm
from .algorithms.alg_capacitated_allocation import CapacitatedAllocationAlgorithm
from .algorithms.alg_land_allocation import LandUseAllocationAlgorithm
from .algorithms.alg_pareto_allocation import ParetoAllocationAlgorithm
from .algorithms.alg_access_equity import AccessEquityAlgorithm
from .algorithms.alg_inequality_curves import InequalityCurvesAlgorithm


class PlanXProvider(QgsProcessingProvider):
    PROVIDER_ID = "planx"
    PROVIDER_NAME = "PlanX"

    def id(self) -> str:
        return self.PROVIDER_ID

    def name(self) -> str:
        return self.PROVIDER_NAME

    def longName(self) -> str:
        return "PlanX - Urban Analytics Studio"

    def icon(self) -> QIcon:
        icon_path = os.path.join(os.path.dirname(__file__), "icons", "icon.png")
        return QIcon(icon_path) if os.path.exists(icon_path) else super().icon()

    def loadAlgorithms(self) -> None:
        # 1 | Network Analysis
        self.addAlgorithm(PrepareNetworkAlgorithm())
        self.addAlgorithm(ODCostMatrixAlgorithm())
        self.addAlgorithm(ServiceAreasAlgorithm())
        self.addAlgorithm(NearestFacilityAlgorithm())
        # 2 | Centrality & Space Syntax
        self.addAlgorithm(NetworkCentralityAlgorithm())
        self.addAlgorithm(SpaceSyntaxAlgorithm())
        # 3 | Urban Morphology
        self.addAlgorithm(BuildingFormMetricsAlgorithm())
        self.addAlgorithm(MorphologicalTessellationAlgorithm())
        self.addAlgorithm(SpacematrixDensityAlgorithm())
        self.addAlgorithm(StreetNetworkMorphologyAlgorithm())
        # 4 | Accessibility
        self.addAlgorithm(MultiAmenityAccessAlgorithm())
        # 5 | Microclimate
        self.addAlgorithm(ShadowCastingAlgorithm())
        self.addAlgorithm(SkyViewFactorAlgorithm())
        self.addAlgorithm(FrontalAreaIndexAlgorithm())
        self.addAlgorithm(SunHoursAlgorithm())
        self.addAlgorithm(SolarIrradiationAlgorithm())
        self.addAlgorithm(AnnualSolarAlgorithm())
        self.addAlgorithm(HeatRiskGridAlgorithm())
        # 6 | Plan Standards and QA
        self.addAlgorithm(LandUseBalanceAlgorithm())
        self.addAlgorithm(FacilityAdequacyAlgorithm())
        self.addAlgorithm(DensityGridAlgorithm())
        # 7 | Reporting and Dashboard
        self.addAlgorithm(PlanPerformanceReportAlgorithm())
        # 8 | Optimization
        self.addAlgorithm(FacilityLocationAlgorithm())
        self.addAlgorithm(CapacitatedAllocationAlgorithm())
        self.addAlgorithm(LandUseAllocationAlgorithm())
        self.addAlgorithm(ParetoAllocationAlgorithm())
        # 9 | Equity
        self.addAlgorithm(AccessEquityAlgorithm())
        self.addAlgorithm(InequalityCurvesAlgorithm())
