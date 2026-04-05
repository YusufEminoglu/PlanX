from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterNumber,
    QgsProcessingParameterDefinition,
    QgsProcessingParameterCrs,
    QgsCoordinateReferenceSystem,
    QgsProcessingMultiStepFeedback,
    QgsProcessingException
)
import processing

class ServiceAreaBufferGenerator(QgsProcessingAlgorithm):
    """
    Service Area & Buffer Generator
    ------------------------------
    The Service Area & Buffer Generator is a comprehensive spatial analysis tool designed for advanced accessibility and reachability studies in urban planning, facility siting, and network analysis. This tool enables users to generate both Euclidean (bird's eye) buffer polygons and network-based service area polygons for a set of facility points (such as schools, parks, or hospitals) using a road network.

    Key features include:
    - Custom Output CRS: All outputs are generated in the user's chosen coordinate reference system.
    - Dual Distance Analysis: Specify separate distances for straight-line (Euclidean) buffers and network-based service areas (along roads).
    - Per-Facility Service Areas: Each facility point receives its own service area polygon, accurately reflecting real-world accessibility.
    - Optional Advanced Outputs:
      * Dissolved Buffer Polygon: A single merged buffer for all facilities.
      * Dissolved Service Area Polygon: A single merged service area for all facilities.
      * Analysis-Ready Roads: A road network layer that is reprojected, dissolved, split into singleparts, and segmented by user-defined length—ideal for further network or accessibility analysis.
    - Flexible Workflow: Optional outputs are only generated if requested, ensuring efficient processing tailored to your needs.

    This tool is ideal for planners, GIS professionals, and researchers who require both simple and advanced accessibility metrics, all within a single, user-friendly QGIS processing algorithm.
    """

    def shortHelpString(self):
        return (
            '<b>Service Area & Buffer Generator</b><br>'
            'Generates both Euclidean (bird\'s eye) buffer polygons and network-based service area polygons for each facility point.<br>'
            'Optionally outputs dissolved buffers, dissolved service areas, and analysis-ready roads (reprojected, dissolved, singlepart, and split by user-defined length).<br>'
            'All outputs are in the selected CRS. Perfect for accessibility, urban planning, and network analysis.'
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterVectorLayer(
            'points',
            'Facility Points Layer',
            types=[QgsProcessing.TypeVectorPoint],
            defaultValue=None
        ))
        self.addParameter(QgsProcessingParameterVectorLayer(
            'roads',
            'Roads Layer',
            types=[QgsProcessing.TypeVectorLine],
            defaultValue=None
        ))
        self.addParameter(QgsProcessingParameterCrs(
            'output_crs',
            'Output CRS',
            defaultValue='EPSG:5253'
        ))
        self.addParameter(QgsProcessingParameterNumber(
            'buffer_distance',
            'Buffer Distance (meters, Euclidean)',
            type=QgsProcessingParameterNumber.Double,
            minValue=1,
            maxValue=5000,
            defaultValue=500
        ))
        self.addParameter(QgsProcessingParameterNumber(
            'service_area_distance',
            'Service Area Distance (meters, along roads)',
            type=QgsProcessingParameterNumber.Double,
            minValue=1,
            maxValue=5000,
            defaultValue=500
        ))
        self.addParameter(QgsProcessingParameterFeatureSink(
            'buffer_polygons',
            'Buffer Polygons (Euclidean)',
            type=QgsProcessing.TypeVectorPolygon,
            createByDefault=True,
            defaultValue=None
        ))
        self.addParameter(QgsProcessingParameterFeatureSink(
            'service_area_polygons',
            'Service Area Polygons (Network-based)',
            type=QgsProcessing.TypeVectorPolygon,
            createByDefault=True,
            defaultValue=None
        ))
        # New optional outputs
        self.addParameter(QgsProcessingParameterFeatureSink(
            'dissolved_buffer',
            'Dissolved Buffer Polygon (Optional)',
            type=QgsProcessing.TypeVectorPolygon,
            optional=True,
            defaultValue=None
        ))
        self.addParameter(QgsProcessingParameterFeatureSink(
            'dissolved_service_area',
            'Dissolved Service Area Polygon (Optional)',
            type=QgsProcessing.TypeVectorPolygon,
            optional=True,
            defaultValue=None
        ))
        self.addParameter(QgsProcessingParameterFeatureSink(
            'analysis_ready_roads',
            'Analysis-Ready Roads (Optional)',
            type=QgsProcessing.TypeVectorLine,
            optional=True,
            defaultValue=None
        ))
        self.addParameter(QgsProcessingParameterNumber(
            'split_length',
            'Split Length for Analysis-Ready Roads (meters)',
            type=QgsProcessingParameterNumber.Double,
            minValue=1,
            maxValue=10000,
            defaultValue=10,
            optional=True
        ))

    def processAlgorithm(self, parameters, context, model_feedback):
        feedback = QgsProcessingMultiStepFeedback(10, model_feedback)
        results = {}
        outputs = {}

        # Input validation
        if not parameters['points'] or not parameters['roads']:
            raise QgsProcessingException('Both facility points and roads layers must be provided.')

        output_crs = self.parameterAsCrs(parameters, 'output_crs', context)

        # Reproject points
        alg_params = {
            'CONVERT_CURVED_GEOMETRIES': False,
            'INPUT': parameters['points'],
            'OPERATION': None,
            'TARGET_CRS': output_crs,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['PointsReprojected'] = processing.run(
            'native:reprojectlayer', alg_params, context=context, feedback=feedback, is_child_algorithm=True
        )
        feedback.setCurrentStep(1)
        if feedback.isCanceled():
            return {}

        # Reproject roads
        alg_params = {
            'CONVERT_CURVED_GEOMETRIES': False,
            'INPUT': parameters['roads'],
            'OPERATION': None,
            'TARGET_CRS': output_crs,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['RoadsReprojected'] = processing.run(
            'native:reprojectlayer', alg_params, context=context, feedback=feedback, is_child_algorithm=True
        )
        feedback.setCurrentStep(2)
        if feedback.isCanceled():
            return {}

        # Fix geometries (roads)
        alg_params = {
            'INPUT': outputs['RoadsReprojected']['OUTPUT'],
            'METHOD': 1,  # Structure
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['RoadsFixed'] = processing.run(
            'native:fixgeometries', alg_params, context=context, feedback=feedback, is_child_algorithm=True
        )
        feedback.setCurrentStep(3)
        if feedback.isCanceled():
            return {}

        # Buffer (Euclidean)
        alg_params = {
            'DISSOLVE': False,
            'DISTANCE': parameters['buffer_distance'],
            'END_CAP_STYLE': 0,  # Round
            'INPUT': outputs['PointsReprojected']['OUTPUT'],
            'JOIN_STYLE': 0,  # Round
            'MITER_LIMIT': 2,
            'SEGMENTS': 100,
            'SEPARATE_DISJOINT': False,
            'OUTPUT': parameters['buffer_polygons']
        }
        outputs['Buffer'] = processing.run(
            'native:buffer', alg_params, context=context, feedback=feedback, is_child_algorithm=True
        )
        results['buffer_polygons'] = outputs['Buffer']['OUTPUT']
        feedback.setCurrentStep(4)
        if feedback.isCanceled():
            return {}

        # Dissolve buffer (optional)
        if parameters['dissolved_buffer']:
            alg_params = {
                'FIELD': [],
                'INPUT': outputs['Buffer']['OUTPUT'],
                'SEPARATE_DISJOINT': False,
                'OUTPUT': parameters['dissolved_buffer']
            }
            outputs['DissolvedBuffer'] = processing.run(
                'native:dissolve', alg_params, context=context, feedback=feedback, is_child_algorithm=True
            )
            results['dissolved_buffer'] = outputs['DissolvedBuffer']['OUTPUT']

        # Service Area (network-based)
        alg_params = {
            'DEFAULT_DIRECTION': 2,  # Both directions
            'DEFAULT_SPEED': 5,
            'DIRECTION_FIELD': None,
            'INCLUDE_BOUNDS': False,
            'INPUT': outputs['RoadsFixed']['OUTPUT'],
            'SPEED_FIELD': None,
            'START_POINTS': outputs['PointsReprojected']['OUTPUT'],
            'STRATEGY': 0,  # Shortest
            'TOLERANCE': 0.00015,
            'TRAVEL_COST2': parameters['service_area_distance'],
            'VALUE_BACKWARD': None,
            'VALUE_BOTH': None,
            'VALUE_FORWARD': None,
            'OUTPUT_LINES': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['ServiceLines'] = processing.run(
            'native:serviceareafromlayer', alg_params, context=context, feedback=feedback, is_child_algorithm=True
        )
        feedback.setCurrentStep(5)
        if feedback.isCanceled():
            return {}

        # Minimum bounding geometry (convex hull) for service area
        alg_params = {
            'FIELD': 'start',  # Group by facility point
            'INPUT': outputs['ServiceLines']['OUTPUT_LINES'],
            'TYPE': 3,  # Convex Hull
            'OUTPUT': parameters['service_area_polygons']
        }
        outputs['ServiceAreaPolygons'] = processing.run(
            'qgis:minimumboundinggeometry', alg_params, context=context, feedback=feedback, is_child_algorithm=True
        )
        results['service_area_polygons'] = outputs['ServiceAreaPolygons']['OUTPUT']
        feedback.setCurrentStep(6)
        if feedback.isCanceled():
            return {}

        # Dissolve service area polygons (optional)
        if parameters['dissolved_service_area']:
            alg_params = {
                'FIELD': [],
                'INPUT': outputs['ServiceAreaPolygons']['OUTPUT'],
                'SEPARATE_DISJOINT': False,
                'OUTPUT': parameters['dissolved_service_area']
            }
            outputs['DissolvedServiceArea'] = processing.run(
                'native:dissolve', alg_params, context=context, feedback=feedback, is_child_algorithm=True
            )
            results['dissolved_service_area'] = outputs['DissolvedServiceArea']['OUTPUT']

        # Analysis-ready roads (optional)
        if parameters['analysis_ready_roads']:
            # Dissolve roads
            alg_params = {
                'FIELD': [],
                'INPUT': outputs['RoadsFixed']['OUTPUT'],
                'SEPARATE_DISJOINT': False,
                'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
            }
            outputs['DissolvedRoads'] = processing.run(
                'native:dissolve', alg_params, context=context, feedback=feedback, is_child_algorithm=True
            )
            # Multipart to singlepart
            alg_params = {
                'INPUT': outputs['DissolvedRoads']['OUTPUT'],
                'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
            }
            outputs['SinglepartRoads'] = processing.run(
                'native:multiparttosingleparts', alg_params, context=context, feedback=feedback, is_child_algorithm=True
            )
            # Split by length
            split_length = parameters['split_length'] if parameters['split_length'] else 10
            alg_params = {
                'INPUT': outputs['SinglepartRoads']['OUTPUT'],
                'LENGTH': split_length,
                'OUTPUT': parameters['analysis_ready_roads']
            }
            outputs['SplitRoads'] = processing.run(
                'native:splitlinesbylength', alg_params, context=context, feedback=feedback, is_child_algorithm=True
            )
            results['analysis_ready_roads'] = outputs['SplitRoads']['OUTPUT']

        feedback.setCurrentStep(10)
        return results

    def name(self):
        return 'service_area_buffer_generator'

    def displayName(self):
        return 'Service Area & Buffer Generator'

    def group(self):
        return 'Accessibility Tools'

    def groupId(self):
        return 'accessibility_tools'

    def createInstance(self):
        return ServiceAreaBufferGenerator()

# For PlanX menu integration:
MENU_LABEL = "Service Area & Buffer Generator"
ICON_PATH = "../icons/service_area_buffer_generator.png"

def run_tool():
    from qgis import processing
    processing.execAlgorithmDialog(ServiceAreaBufferGenerator()) 
