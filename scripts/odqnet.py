"""
ODQNet: Origin-Destination Matrix Generator using QNEAT
"""
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingMultiStepFeedback,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterString,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterNumber,
    QgsProcessingParameterDefinition,
    QgsCoordinateReferenceSystem,
    QgsProcessingParameterCrs,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterField
)
import processing
import statistics

class ODQNet(QgsProcessingAlgorithm):
    def initAlgorithm(self, config=None):
        param = QgsProcessingParameterVectorLayer(
            'origins',
            'Origin Points',
            types=[QgsProcessing.TypeVectorPoint],
            defaultValue=None
        )
        param.setHelp('Point layer representing the start locations for OD analysis.')
        param.setFlags(param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(param)
        param = QgsProcessingParameterVectorLayer(
            'destinations',
            'Destination Points',
            types=[QgsProcessing.TypeVectorPoint],
            defaultValue=None
        )
        param.setHelp('Point layer representing the end locations for OD analysis.')
        param.setFlags(param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(param)
        param = QgsProcessingParameterString(
            'id_field',
            'Unique ID Field',
            multiLine=False,
            defaultValue='fid'
        )
        param.setHelp('Field with unique values for each origin/destination (e.g., "fid" or "id").')
        self.addParameter(param)
        param = QgsProcessingParameterVectorLayer(
            'network',
            'Network Layer',
            types=[QgsProcessing.TypeVectorLine, QgsProcessing.TypeVectorPolygon],
            defaultValue=None
        )
        param.setHelp('Line or polygon layer representing the travel network (e.g., roads).')
        param.setFlags(param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(param)
        # Output selection checkboxes
        self.addParameter(QgsProcessingParameterBoolean('out_prepared_network', 'Output Prepared Network Segments', defaultValue=True))
        self.addParameter(QgsProcessingParameterBoolean('out_straight_line', 'Output OD Matrix (Straight Line)', defaultValue=True))
        self.addParameter(QgsProcessingParameterBoolean('out_route', 'Output OD Matrix (Route)', defaultValue=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            'prepared_network',
            'Prepared Network Segments',
            type=QgsProcessing.TypeVectorLine,
            createByDefault=True,
            supportsAppend=True,
            defaultValue=None
        ))
        self.addParameter(QgsProcessingParameterFeatureSink(
            'straight_line_matrix',
            'OD Matrix (Straight Line)',
            type=QgsProcessing.TypeVectorAnyGeometry,
            createByDefault=True,
            defaultValue='TEMPORARY_OUTPUT'
        ))
        self.addParameter(QgsProcessingParameterFeatureSink(
            'route_matrix',
            'OD Matrix (Route)',
            type=QgsProcessing.TypeVectorAnyGeometry,
            createByDefault=True,
            defaultValue=None
        ))
        param = QgsProcessingParameterNumber(
            'segment_length',
            'Segment Length (meters)',
            type=QgsProcessingParameterNumber.Double,
            minValue=1,
            maxValue=200,
            defaultValue=50
        )
        param.setHelp('Maximum length (in meters) for splitting network lines. Shorter segments improve routing accuracy but increase processing time.')
        param.setFlags(param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(param)
        param = QgsProcessingParameterCrs(
            'target_crs',
            'Target CRS',
            defaultValue='EPSG:5253'
        )
        param.setHelp('Coordinate Reference System for all processing. Must match your network and point data for accurate results.')
        self.addParameter(param)
        # QNEAT3 parameters
        param = QgsProcessingParameterNumber('default_speed', 'Default Speed (km/h)', type=QgsProcessingParameterNumber.Double, minValue=1, maxValue=200, defaultValue=5)
        param.setHelp('Used only for fastest path (time) calculations. For walking, use 5 km/h. For driving, use typical road speeds. Not used for shortest path (distance).')
        self.addParameter(param)
        self.addParameter(QgsProcessingParameterEnum('direction', 'Direction', options=['Forward', 'Backward', 'Both'], defaultValue=2))
        self.addParameter(QgsProcessingParameterEnum('strategy', 'Routing Strategy', options=['Shortest Path (distance)', 'Fastest Path (time)'], defaultValue=0))
        # Future: Add more advanced options as needed

    def processAlgorithm(self, parameters, context, model_feedback):
        feedback = QgsProcessingMultiStepFeedback(10, model_feedback)
        results = {}
        outputs = {}
        # Output selection
        out_prepared = parameters['out_prepared_network']
        out_straight = parameters['out_straight_line']
        out_route = parameters['out_route']
        # QNEAT3 params
        default_speed = parameters['default_speed']
        direction = [1, 0, 2][parameters['direction']]  # Forward=1, Backward=0, Both=2
        strategy = parameters['strategy']  # 0=Shortest, 1=Fastest
        # Field selection removed

        # Reproject origins
        alg_params = {
            'CONVERT_CURVED_GEOMETRIES': False,
            'INPUT': parameters['origins'],
            'OPERATION': None,
            'TARGET_CRS': parameters['target_crs'],
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['reprojected_origins'] = processing.run('native:reprojectlayer', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
        feedback.setCurrentStep(1)
        if feedback.isCanceled():
            return {}

        # Reproject network
        alg_params = {
            'CONVERT_CURVED_GEOMETRIES': False,
            'INPUT': parameters['network'],
            'OPERATION': None,
            'TARGET_CRS': parameters['target_crs'],
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['reprojected_network'] = processing.run('native:reprojectlayer', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
        feedback.setCurrentStep(2)
        if feedback.isCanceled():
            return {}

        # Reproject destinations
        alg_params = {
            'CONVERT_CURVED_GEOMETRIES': False,
            'INPUT': parameters['destinations'],
            'OPERATION': None,
            'TARGET_CRS': parameters['target_crs'],
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['reprojected_destinations'] = processing.run('native:reprojectlayer', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
        feedback.setCurrentStep(3)
        if feedback.isCanceled():
            return {}

        # Dissolve network
        alg_params = {
            'FIELD': [''],
            'INPUT': outputs['reprojected_network']['OUTPUT'],
            'SEPARATE_DISJOINT': False,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['dissolved_network'] = processing.run('native:dissolve', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
        feedback.setCurrentStep(4)
        if feedback.isCanceled():
            return {}

        # Multipart to singlepart
        alg_params = {
            'INPUT': outputs['dissolved_network']['OUTPUT'],
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['singlepart_network'] = processing.run('native:multiparttosingleparts', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
        feedback.setCurrentStep(5)
        if feedback.isCanceled():
            return {}

        # Split lines by maximum length
        alg_params = {
            'INPUT': outputs['singlepart_network']['OUTPUT'],
            'LENGTH': parameters['segment_length'],
            'OUTPUT': parameters['prepared_network'] if out_prepared else QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['split_network'] = processing.run('native:splitlinesbylength', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
        if out_prepared:
            results['prepared_network'] = outputs['split_network']['OUTPUT']
        feedback.setCurrentStep(6)
        if feedback.isCanceled():
            return {}

        # OD Matrix (straight line)
        if out_straight:
            alg_params = {
                'DEFAULT_DIRECTION': direction,
                'DEFAULT_SPEED': default_speed,
                'DIRECTION_FIELD': None,
                'ENTRY_COST_CALCULATION_METHOD': 0,
                'FROM_ID_FIELD': parameters['id_field'],
                'FROM_POINT_LAYER': outputs['reprojected_origins']['OUTPUT'],
                'INPUT': outputs['split_network']['OUTPUT'],
                'MATRIX_GEOMETRY_TYPE': 0,
                'SPEED_FIELD': None,
                'STRATEGY': strategy,
                'TOLERANCE': 0.00015,
                'TO_ID_FIELD': parameters['id_field'],
                'TO_POINT_LAYER': outputs['reprojected_destinations']['OUTPUT'],
                'VALUE_BACKWARD': None,
                'VALUE_BOTH': None,
                'VALUE_FORWARD': None,
                'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
            }
            outputs['od_matrix_straight'] = processing.run('qneat3:OdMatrixFromLayersAsLines', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
            feedback.setCurrentStep(7)
            if feedback.isCanceled():
                return {}
            # Execute SQL (straight line)
            alg_params = {
                'INPUT_DATASOURCES': outputs['od_matrix_straight']['OUTPUT'],
                'INPUT_GEOMETRY_CRS': parameters['target_crs'],
                'INPUT_GEOMETRY_FIELD': 'geometry',
                'INPUT_GEOMETRY_TYPE': 0,
                'INPUT_QUERY': 'select origin_id, destination_id, min(total_cost) as shortest_distance, geometry\nfrom input1 group by origin_id',
                'INPUT_UID_FIELD': None,
                'OUTPUT': parameters['straight_line_matrix']
            }
            outputs['sql_straight'] = processing.run('qgis:executesql', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
            results['straight_line_matrix'] = outputs['sql_straight']['OUTPUT']
            # Add summary statistics
            try:
                from qgis.core import QgsVectorLayer, QgsProject
                layer = QgsVectorLayer(outputs['sql_straight']['OUTPUT'], 'OD Matrix (Straight Line)', 'ogr')
                QgsProject.instance().addMapLayer(layer)
                layer.setName('OD Matrix (Straight Line)')
                values = [f['shortest_distance'] for f in layer.getFeatures() if f['shortest_distance'] is not None]
                if values:
                    results['straight_line_matrix_min'] = min(values)
                    results['straight_line_matrix_max'] = max(values)
                    results['straight_line_matrix_mean'] = statistics.mean(values)
            except Exception:
                pass

        # OD Matrix (route)
        if out_route:
            alg_params = {
                'DEFAULT_DIRECTION': direction,
                'DEFAULT_SPEED': default_speed,
                'DIRECTION_FIELD': None,
                'ENTRY_COST_CALCULATION_METHOD': 0,
                'FROM_ID_FIELD': parameters['id_field'],
                'FROM_POINT_LAYER': outputs['reprojected_origins']['OUTPUT'],
                'INPUT': outputs['split_network']['OUTPUT'],
                'MATRIX_GEOMETRY_TYPE': 1,
                'SPEED_FIELD': None,
                'STRATEGY': strategy,
                'TOLERANCE': 0.00015,
                'TO_ID_FIELD': parameters['id_field'],
                'TO_POINT_LAYER': outputs['reprojected_destinations']['OUTPUT'],
                'VALUE_BACKWARD': None,
                'VALUE_BOTH': None,
                'VALUE_FORWARD': None,
                'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
            }
            outputs['od_matrix_route'] = processing.run('qneat3:OdMatrixFromLayersAsLines', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
            feedback.setCurrentStep(8)
            if feedback.isCanceled():
                return {}
            # Execute SQL (route)
            alg_params = {
                'INPUT_DATASOURCES': outputs['od_matrix_route']['OUTPUT'],
                'INPUT_GEOMETRY_CRS': parameters['target_crs'],
                'INPUT_GEOMETRY_FIELD': 'geometry',
                'INPUT_GEOMETRY_TYPE': 0,
                'INPUT_QUERY': 'select origin_id, destination_id, min(total_cost) as shortest_distance, geometry\nfrom input1 group by origin_id',
                'INPUT_UID_FIELD': None,
                'OUTPUT': parameters['route_matrix']
            }
            outputs['sql_route'] = processing.run('qgis:executesql', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
            results['route_matrix'] = outputs['sql_route']['OUTPUT']
            # Add summary statistics
            try:
                from qgis.core import QgsVectorLayer, QgsProject
                layer = QgsVectorLayer(outputs['sql_route']['OUTPUT'], 'OD Matrix (Route)', 'ogr')
                QgsProject.instance().addMapLayer(layer)
                layer.setName('OD Matrix (Route)')
                values = [f['shortest_distance'] for f in layer.getFeatures() if f['shortest_distance'] is not None]
                if values:
                    results['route_matrix_min'] = min(values)
                    results['route_matrix_max'] = max(values)
                    results['route_matrix_mean'] = statistics.mean(values)
            except Exception:
                pass

        return results

    def name(self):
        return 'odqnet'

    def displayName(self):
        return 'ODQNet'

    def group(self):
        return 'PlanX Tools'

    def groupId(self):
        return 'planx_tools'

    def shortHelpString(self):
        return """
        ODQNet generates origin-destination (OD) matrices using QNEAT3. It outputs:
        - Prepared Network Segments: The network split into segments for routing.
        - OD Matrix (Straight Line): Direct lines between origins and destinations.
        - OD Matrix (Route): Shortest-path routes along the network.

        Parameters:
        - Origin Points / Destination Points: Point layers for OD analysis.
        - Network Layer: Line/polygon layer (e.g., roads).
        - Unique ID Field: Must be unique for each origin/destination.
        - Segment Length: Shorter segments = more accurate routing, but slower.
        - Target CRS: All layers are reprojected for consistency.
        - Default Speed (km/h): Used only for fastest path (time) calculations. For walking, use 5 km/h. For driving, use typical road speeds. Not used for shortest path (distance).
        - Direction: Choose routing direction (forward, backward, both).
        - Routing Strategy: Shortest path (distance) or fastest path (time).

        Why choose these parameters?
        - Segment Length: Shorter segments allow more precise routing, especially in dense or complex networks, but increase processing time. Use a value that balances accuracy and speed for your network.
        - Target CRS: Ensures all layers are in the same projection for accurate distance and routing calculations.
        - Unique ID Field: Required for matching origins and destinations in the OD matrix.
        - Default Speed: Only used for fastest path (time). For walking, use 5 km/h.

        SQL Efficiency:
        - The final OD matrices are generated using SQL queries for efficiency. For very large datasets, consider filtering your origins/destinations to improve performance.
        """

    def createInstance(self):
        return ODQNet()

def run_tool():
    from qgis import processing
    processing.execAlgorithmDialog(ODQNet()) 