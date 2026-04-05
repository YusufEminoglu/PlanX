from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterDefinition,
    QgsProcessingParameterCrs,
    QgsCoordinateReferenceSystem,
    QgsProcessingMultiStepFeedback
)
import processing

class LineProximityRasterizer(QgsProcessingAlgorithm):
    """
    Line Proximity Rasterizer
    ------------------------
    This advanced geoprocessing tool transforms line vector features into a proximity raster, efficiently calculating the distance from each raster cell to the nearest line within a user-defined boundary. The tool supports custom output resolution, proximity distance, and coordinate reference system, ensuring seamless integration into diverse spatial analysis workflows. Ideal for hydrological modeling, infrastructure planning, and spatial accessibility studies, it leverages QGIS and GDAL's robust processing capabilities for high-performance, reproducible results.
    """

    def shortHelpString(self):
        return (
            '<b>Line Proximity Rasterizer</b><br>'
            'Transforms line vector features into a proximity raster, calculating the distance from each raster cell to the nearest line within a user-defined polygon boundary.\n'
            'You can specify the output raster resolution, maximum proximity distance, and the output CRS.\n'
            'This tool is ideal for hydrological modeling, infrastructure planning, and spatial accessibility studies.'
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterVectorLayer(
            'alansiniri',
            'Boundary Polygon Layer',
            types=[QgsProcessing.TypeVectorPolygon],
            defaultValue=None
        ))
        self.addParameter(QgsProcessingParameterVectorLayer(
            'linevector',
            'Input Line Layer',
            types=[QgsProcessing.TypeVectorLine],
            defaultValue=None
        ))
        self.addParameter(QgsProcessingParameterCrs(
            'output_crs',
            'Output CRS',
            defaultValue='EPSG:5253'
        ))
        self.addParameter(QgsProcessingParameterRasterDestination(
            'Proximity_line',
            'Proximity Raster Output',
            createByDefault=True,
            defaultValue=None
        ))
        self.addParameter(QgsProcessingParameterRasterDestination(
            'Rasterize_line',
            'Rasterized Line Output',
            createByDefault=True,
            defaultValue=None
        ))
        param = QgsProcessingParameterNumber(
            'cozunurlukmetre',
            'Raster Resolution (meters)',
            type=QgsProcessingParameterNumber.Integer,
            minValue=1,
            maxValue=500,
            defaultValue=15
        )
        param.setFlags(param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(param)
        param = QgsProcessingParameterNumber(
            'yakinlikmetre',
            'Maximum Proximity Distance (meters)',
            type=QgsProcessingParameterNumber.Integer,
            minValue=1,
            maxValue=100000,
            defaultValue=20000
        )
        param.setFlags(param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(param)

    def processAlgorithm(self, parameters, context, model_feedback):
        feedback = QgsProcessingMultiStepFeedback(5, model_feedback)
        results = {}
        outputs = {}

        # Input validation
        if not parameters['alansiniri'] or not parameters['linevector']:
            raise QgsProcessingException('Both boundary polygon and line vector layers must be provided.')

        output_crs = self.parameterAsCrs(parameters, 'output_crs', context)

        # Reproject boundary polygon
        alg_params = {
            'CONVERT_CURVED_GEOMETRIES': False,
            'INPUT': parameters['alansiniri'],
            'OPERATION': None,
            'TARGET_CRS': output_crs,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['AlansiniriReprojected'] = processing.run(
            'native:reprojectlayer', alg_params, context=context, feedback=feedback, is_child_algorithm=True
        )

        feedback.setCurrentStep(1)
        if feedback.isCanceled():
            return {}

        # Reproject line vector
        alg_params = {
            'CONVERT_CURVED_GEOMETRIES': False,
            'INPUT': parameters['linevector'],
            'OPERATION': None,
            'TARGET_CRS': output_crs,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['LineReprojected'] = processing.run(
            'native:reprojectlayer', alg_params, context=context, feedback=feedback, is_child_algorithm=True
        )

        feedback.setCurrentStep(2)
        if feedback.isCanceled():
            return {}

        # Clip line by boundary
        alg_params = {
            'INPUT': outputs['LineReprojected']['OUTPUT'],
            'OVERLAY': outputs['AlansiniriReprojected']['OUTPUT'],
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['ClippedLine'] = processing.run(
            'native:clip', alg_params, context=context, feedback=feedback, is_child_algorithm=True
        )

        feedback.setCurrentStep(3)
        if feedback.isCanceled():
            return {}

        # Rasterize clipped line
        alg_params = {
            'BURN': 1,
            'DATA_TYPE': 5,  # Float32
            'EXTENT': outputs['AlansiniriReprojected']['OUTPUT'],
            'EXTRA': None,
            'FIELD': None,
            'HEIGHT': parameters['cozunurlukmetre'],
            'INIT': None,
            'INPUT': outputs['ClippedLine']['OUTPUT'],
            'INVERT': False,
            'NODATA': None,
            'OPTIONS': None,
            'UNITS': 1,  # Georeferenced units
            'USE_Z': False,
            'WIDTH': parameters['cozunurlukmetre'],
            'OUTPUT': parameters['Rasterize_line']
        }
        outputs['RasterizeVectorToRaster'] = processing.run(
            'gdal:rasterize', alg_params, context=context, feedback=feedback, is_child_algorithm=True
        )
        results['Rasterize_line'] = outputs['RasterizeVectorToRaster']['OUTPUT']

        feedback.setCurrentStep(4)
        if feedback.isCanceled():
            return {}

        # Proximity raster
        alg_params = {
            'BAND': 1,
            'DATA_TYPE': 5,  # Float32
            'EXTRA': None,
            'INPUT': outputs['RasterizeVectorToRaster']['OUTPUT'],
            'MAX_DISTANCE': parameters['yakinlikmetre'],
            'NODATA': None,
            'OPTIONS': None,
            'REPLACE': 0,
            'UNITS': 0,  # Georeferenced coordinates
            'VALUES': None,
            'OUTPUT': parameters['Proximity_line']
        }
        outputs['ProximityRasterDistance'] = processing.run(
            'gdal:proximity', alg_params, context=context, feedback=feedback, is_child_algorithm=True
        )
        results['Proximity_line'] = outputs['ProximityRasterDistance']['OUTPUT']
        return results

    def name(self):
        return 'line_proximity_rasterizer'

    def displayName(self):
        return 'Line Proximity Rasterizer'

    def group(self):
        return 'Raster Tools'

    def groupId(self):
        return 'raster_tools'

    def createInstance(self):
        return LineProximityRasterizer()

# For PlanX menu integration:
MENU_LABEL = "Line Proximity Rasterizer"
ICON_PATH = "../icons/line_proximity_rasterizer.png"

def run_tool():
    from qgis import processing
    processing.execAlgorithmDialog(LineProximityRasterizer()) 
