# -*- coding: utf-8 -*-
"""
NetCentral: Network Centrality Analysis for Roads and Buildings

Calculates betweenness, closeness, degree, and eigenvector centrality metrics for a road network
and joins them by nearest to one or more target layers (e.g., buildings).
"""

import os
import tempfile
import processing
from osgeo import ogr
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingMultiStepFeedback,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterMultipleLayers,
    QgsProcessingParameterFeatureSink,
    QgsProcessingException,
    QgsProject,
    QgsVectorLayer
)
from qgis.PyQt.QtCore import QCoreApplication

MENU_LABEL = "NetCentral"

class NetCentral(QgsProcessingAlgorithm):
    """
    Performs GRASS v.net.centrality on a dissolved road network,
    exports centrality points, and joins metrics by nearest
    to each specified target layer.
    """

    PARAM_ROADS = 'roads'
    PARAM_TARGETS = 'target_layers'
    PARAM_POINTS = 'centrality_points'

    def tr(self, message):
        return QCoreApplication.translate('NetCentral', message)

    def createInstance(self):
        return NetCentral()

    def name(self):
        return 'netcentral'

    def displayName(self):
        return MENU_LABEL

    def group(self):
        return 'PlanX Tools'

    def groupId(self):
        return 'planx_tools'

    def shortHelpString(self):
        return self.tr(
            "Compute GRASS network centrality on roads, "
            "then join metrics by nearest to each target layer."
        )

    def initAlgorithm(self, config=None):
        # Input road network lines
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.PARAM_ROADS,
                self.tr('Road network (lines)'),
                [QgsProcessing.TypeVectorLine]
            )
        )
        # One or more target layers to join centrality to
        self.addParameter(
            QgsProcessingParameterMultipleLayers(
                self.PARAM_TARGETS,
                self.tr('Target layers for join'),
                layerType=QgsProcessing.TypeVectorAnyGeometry
            )
        )
        # Output centrality points
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.PARAM_POINTS,
                self.tr('Centrality points'),
                type=QgsProcessing.TypeVectorPoint,
                createByDefault=True,
                defaultValue=QgsProcessing.TEMPORARY_OUTPUT
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        feedback = QgsProcessingMultiStepFeedback(5, feedback)
        results = {}

        # Dissolve roads
        feedback.setCurrentStep(0)
        dissolved = processing.run(
            'native:dissolve',
            {
                'INPUT': parameters[self.PARAM_ROADS],
                'FIELD': [],
                'SEPARATE_DISJOINT': False,
                'OUTPUT': 'memory:'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        )['OUTPUT']

        # Multipart to singleparts
        feedback.setCurrentStep(1)
        single = processing.run(
            'native:multiparttosingleparts',
            {'INPUT': dissolved, 'OUTPUT': 'memory:'},
            context=context, feedback=feedback, is_child_algorithm=True
        )['OUTPUT']

        # GRASS centrality
        feedback.setCurrentStep(2)
        temp_gpkg = os.path.join(tempfile.gettempdir(), next(tempfile._get_candidate_names()) + '.gpkg')
        grass_res = processing.run(
            'grass7:v.net.centrality',
            {
                'input': single,
                'betweenness': 'betweenness',
                'closeness': 'closeness',
                'degree': 'degree',
                'eigenvector': 'eigenvector',
                '-a': True,
                '-g': False,
                'output': temp_gpkg
            },
            context=context, feedback=feedback, is_child_algorithm=True
        )['output']

        # Read layer name
        ds = ogr.Open(temp_gpkg)
        if not ds or ds.GetLayerCount() < 1:
            raise QgsProcessingException(self.tr('Centrality tool failed to produce output'))
        layer_name = ds.GetLayer(0).GetName()
        ds = None
        central_uri = f"{temp_gpkg}|layername={layer_name}"

        # Save centrality points
        feedback.setCurrentStep(3)
        pts_out = processing.run(
            'native:savefeatures',
            {'INPUT': central_uri, 'OUTPUT': parameters[self.PARAM_POINTS]},
            context=context, feedback=feedback, is_child_algorithm=True
        )['OUTPUT']
        results[self.PARAM_POINTS] = pts_out
        # add to project
        pts_layer = QgsVectorLayer(pts_out, MENU_LABEL + ' Points', 'ogr')
        if pts_layer.isValid():
            QgsProject.instance().addMapLayer(pts_layer)

        # Join by nearest to each target
        feedback.setCurrentStep(4)
        targets = parameters.get(self.PARAM_TARGETS) or []
        for idx, tgt in enumerate(targets, start=1):
            joined = processing.run(
                'native:joinbynearest',
                {
                    'INPUT': tgt,
                    'INPUT_2': pts_out,
                    'NEIGHBORS': 1,
                    'PREFIX': '',
                    'OUTPUT': 'memory:'
                },
                context=context, feedback=feedback, is_child_algorithm=True
            )['OUTPUT']
            results[f'joined_{idx}'] = joined
            jl = QgsVectorLayer(joined, f"{MENU_LABEL} Joined {idx}", 'memory')
            if jl.isValid():
                QgsProject.instance().addMapLayer(jl)

        return results

# single algorithm instance
_algorithm = NetCentral()

# entry point for PlanX loader
def run_tool():
    processing.execAlgorithmDialog(_algorithm)
