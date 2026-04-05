# -*- coding: utf-8 -*-
"""
ConnectToNearestNode: QGIS Processing Algorithm

For each polygon feature (parcel or building), finds the single closest point on any road feature
and outputs both the connecting line (with distance attribute) and the origin point.

Parameters:
- Polygon Layer: Parcel or building polygons (uses selected features only if any are selected)
- Road Layer: Service roads (line)

Outputs:
- Distance Line Layer: Shortest line from polygon boundary to nearest road (distance in meters)
- Origin Point Layer: Point on polygon boundary closest to the road

Both outputs are automatically added to the QGIS Layers panel.
"""

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingMultiStepFeedback,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterFeatureSink,
    QgsExpression
)
import processing

class ConnectToNearestNode(QgsProcessingAlgorithm):
    """
    QGIS Processing Algorithm to connect each polygon feature to its nearest road segment.
    Outputs the shortest connecting line and the origin point on the polygon.
    """

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterVectorLayer(
            'POLYGON_LAYER',
            'Polygon Layer (Parcel or Building)',
            types=[QgsProcessing.TypeVectorPolygon],
            defaultValue=None))

        self.addParameter(QgsProcessingParameterVectorLayer(
            'ROAD_LAYER',
            'Road Layer (Service Roads)',
            types=[QgsProcessing.TypeVectorLine],
            defaultValue=None))

        self.addParameter(QgsProcessingParameterFeatureSink(
            'DISTANCE_LINE',
            'Distance to Nearest Service Road',
            type=QgsProcessing.TypeVectorAnyGeometry,
            createByDefault=True,
            defaultValue='TEMPORARY_OUTPUT'))

        self.addParameter(QgsProcessingParameterFeatureSink(
            'ORIGIN_POINT',
            'Origin Point (Closest Point on Polygon)',
            type=QgsProcessing.TypeVectorPoint,
            createByDefault=True,
            defaultValue='TEMPORARY_OUTPUT'))

    def processAlgorithm(self, parameters, context, model_feedback):
        feedback = QgsProcessingMultiStepFeedback(7, model_feedback)
        results = {}
        outputs = {}

        # 1. Convert polygons to lines
        alg_params = {
            'INPUT': parameters['POLYGON_LAYER'],
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['PolygonsToLines'] = processing.run(
            'native:polygonstolines', alg_params, context=context,
            feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(1)
        if feedback.isCanceled():
            return {}

        # 2. Explode lines into single segments
        alg_params = {
            'INPUT': outputs['PolygonsToLines']['OUTPUT'],
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['ExplodeLines'] = processing.run(
            'native:explodelines', alg_params, context=context,
            feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(2)
        if feedback.isCanceled():
            return {}

        # 3. Calculate centroids of each exploded line
        alg_params = {
            'ALL_PARTS': False,
            'INPUT': outputs['ExplodeLines']['OUTPUT'],
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['Centroids'] = processing.run(
            'native:centroids', alg_params, context=context,
            feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(3)
        if feedback.isCanceled():
            return {}

        # 4. Find shortest line from centroids to roads
        alg_params = {
            'SOURCE': outputs['Centroids']['OUTPUT'],
            'DESTINATION': parameters['ROAD_LAYER'],
            'METHOD': 0,
            'NEIGHBORS': 1,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['ShortestLine'] = processing.run(
            'native:shortestline', alg_params, context=context,
            feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(4)
        if feedback.isCanceled():
            return {}

        # 5. Add autoincremental field (rank) to sort by distance
        alg_params = {
            'INPUT': outputs['ShortestLine']['OUTPUT'],
            'FIELD_NAME': 'RANK',
            'GROUP_FIELDS': ['fid'],  # Group by unique polygon ID
            'SORT_EXPRESSION': 'distance',
            'SORT_ASCENDING': True,
            'START': 1,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['AddRank'] = processing.run(
            'native:addautoincrementalfield', alg_params, context=context,
            feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(5)
        if feedback.isCanceled():
            return {}

        # 6. Extract only the closest (rank = 1)
        alg_params = {
            'INPUT': outputs['AddRank']['OUTPUT'],
            'FIELD': 'RANK',
            'OPERATOR': 0,  # =
            'VALUE': '1',
            'OUTPUT': parameters['DISTANCE_LINE']
        }
        outputs['ExtractClosest'] = processing.run(
            'native:extractbyattribute', alg_params, context=context,
            feedback=feedback, is_child_algorithm=True)
        results['Distance to Nearest Service Road'] = outputs['ExtractClosest']['OUTPUT']

        feedback.setCurrentStep(6)
        if feedback.isCanceled():
            return {}

        # 7. Extract start point of lines (origin point)
        alg_params = {
            'INPUT': outputs['ExtractClosest']['OUTPUT'],
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['ExtractVertices'] = processing.run(
            'native:extractvertices', alg_params, context=context,
            feedback=feedback, is_child_algorithm=True)

        alg_params = {
            'INPUT': outputs['ExtractVertices']['OUTPUT'],
            'FIELD': 'vertex_index',
            'OPERATOR': 0,  # =
            'VALUE': '0',
            'OUTPUT': parameters['ORIGIN_POINT']
        }
        outputs['FirstVertex'] = processing.run(
            'native:extractbyattribute', alg_params, context=context,
            feedback=feedback, is_child_algorithm=True)
        results['Origin Point (Closest Point on Polygon)'] = outputs['FirstVertex']['OUTPUT']

        return results

    def name(self):
        return 'connect_to_nearest_node'

    def displayName(self):
        return 'Connect to Nearest Node'

    def group(self):
        return 'Network Analysis'

    def groupId(self):
        return 'network_analysis'

    def createInstance(self):
        return ConnectToNearestNode()

# entry point

def run_tool():
    processing.execAlgorithmDialog(ConnectToNearestNode())
