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
