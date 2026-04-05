# -*- coding: utf-8 -*-
"""
Geometric Interval Classification for PlanX
Converts a numeric field into geometric intervals and applies graduated symbology.
"""
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsProcessingParameterFileDestination,
    QgsProcessingOutputVectorLayer,
    QgsProject,
    QgsVectorLayer,
    QgsField,
    QgsFeature,
    QgsProcessingException,
    QgsSymbol,
    QgsRendererRange,
    QgsGraduatedSymbolRenderer,
    QgsVectorFileWriter
)
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtCore import QVariant
import processing

MENU_LABEL = "Geometric Interval Classification"

class GeometricIntervalClassificationAlgorithm(QgsProcessingAlgorithm):
    """Classify a numeric field into geometric intervals and apply graduated symbology."""
    INPUT = 'INPUT'
    FIELD = 'FIELD'
    CLASSES = 'CLASSES'
    OUTPUT_COLUMN = 'OUTPUT_COLUMN'
    OUTPUT_LAYER_NAME = 'OUTPUT_LAYER_NAME'
    OUTPUT_FILE = 'OUTPUT_FILE'
    OUTPUT = 'OUTPUT'

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT,
                'Input vector layer',
                [QgsProcessing.TypeVectorAnyGeometry]
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.FIELD,
                'Field to classify',
                parentLayerParameterName=self.INPUT,
                type=QgsProcessingParameterField.Numeric
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.CLASSES,
                'Number of classes',
                type=QgsProcessingParameterNumber.Integer,
                minValue=1,
                defaultValue=5
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.OUTPUT_COLUMN,
                'Output classification field',
                defaultValue='geom_interval_class'
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.OUTPUT_LAYER_NAME,
                'Output layer name',
                defaultValue='Geometric_Interval_Classification'
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_FILE,
                'Output vector file',
                fileFilter='GeoPackage (*.gpkg);;ESRI Shapefile (*.shp)',
                optional=True
            )
        )
        self.addOutput(
            QgsProcessingOutputVectorLayer(
                self.OUTPUT,
                'Classified output layer'
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        # Read parameters
        input_source = self.parameterAsSource(parameters, self.INPUT, context)
        field_name = self.parameterAsString(parameters, self.FIELD, context)
        n_classes = self.parameterAsInt(parameters, self.CLASSES, context)
        output_col = self.parameterAsString(parameters, self.OUTPUT_COLUMN, context)
        output_name = self.parameterAsString(parameters, self.OUTPUT_LAYER_NAME, context)
        output_file = self.parameterAsFileOutput(parameters, self.OUTPUT_FILE, context)

        input_layer = self.parameterAsVectorLayer(parameters, self.INPUT, context)
        feedback.pushInfo(f'Loaded layer: {input_layer.name()}')

        # Create output memory layer
        crs = input_layer.crs().authid()
        geom_map = {0: 'Point', 1: 'Line', 2: 'Polygon'}
        layer_type = geom_map.get(input_layer.geometryType(), 'Polygon')
        out_layer = QgsVectorLayer(f'{layer_type}?crs={crs}', output_name, 'memory')
        out_layer.startEditing()

        # Add fields
        out_layer.dataProvider().addAttributes(input_layer.fields())
        out_layer.dataProvider().addAttributes([
            QgsField(output_col, QVariant.String),
            QgsField('class_label', QVariant.String)
        ])
        out_layer.updateFields()

        # Copy features
        features = []
        for feat in input_layer.getFeatures():
            new_feat = QgsFeature(out_layer.fields())
            new_feat.setGeometry(feat.geometry())
            new_feat.setAttributes(feat.attributes())
            features.append(new_feat)
        out_layer.dataProvider().addFeatures(features)
        out_layer.commitChanges()
        feedback.pushInfo(f'{len(features)} features copied')

                # Compute breaks (handle non-positive values by shifting)
        values = [feat[field_name] or 0 for feat in input_layer.getFeatures()]
        if not values:
            raise QgsProcessingException('No numeric values found')
        min_v, max_v = min(values), max(values)
        shift = 0.0
        if min_v <= 0:
            shift = abs(min_v) + 1e-6
            shifted = [v + shift for v in values]
            min_v, max_v = min(shifted), max(shifted)
        max_v += 1e-6
        ratio = (max_v / min_v) ** (1.0 / n_classes)
        breaks = [min_v * (ratio ** i) for i in range(n_classes + 1)]
        # shift breaks back if needed
        if shift:
            breaks = [b - shift for b in breaks]
        feedback.pushInfo(f'Computed breaks: {breaks}')

        # Apply symbology
        ranges = []
        for i in range(n_classes):
            low, high = breaks[i], breaks[i+1]
            sym = QgsSymbol.defaultSymbol(out_layer.geometryType())
            sym.setColor(QColor.fromHsv(int(360 * i / n_classes), 200, 200))
            label = f'{round(low,2)} - {round(high,2)}'
            ranges.append(QgsRendererRange(low, high, sym, label))
        renderer = QgsGraduatedSymbolRenderer(output_col, ranges)
        renderer.setMode(QgsGraduatedSymbolRenderer.Custom)
        out_layer.setRenderer(renderer)

        # Populate classification fields
        out_layer.startEditing()
        idx_val = out_layer.fields().indexFromName(output_col)
        idx_lbl = out_layer.fields().indexFromName('class_label')
        for feat in out_layer.getFeatures():
            val = feat[field_name] or 0
            for i in range(n_classes):
                if breaks[i] <= val < breaks[i+1]:
                    feat[idx_val] = f'class_{i+1}'
                    feat[idx_lbl] = ranges[i].label()
                    out_layer.updateFeature(feat)
                    break
        out_layer.commitChanges()

        # Save to file
        if output_file:
            opts = QgsVectorFileWriter.SaveVectorOptions()
            opts.driverName = 'GPKG' if output_file.endswith('.gpkg') else 'ESRI Shapefile'
            QgsVectorFileWriter.writeAsVectorFormatV3(
                out_layer, output_file, context.transformContext(), opts
            )
            feedback.pushInfo(f'Saved output to {output_file}')

        # Add to project
        QgsProject.instance().addMapLayer(out_layer)
        return {self.OUTPUT: out_layer}

    def name(self):
        return 'geometric_interval_classification'

    def displayName(self):
        return 'Geometric Interval Classification'

    def group(self):
        return 'PlanX Tools'

    def groupId(self):
        return 'planx_tools'

    def createInstance(self):
        return GeometricIntervalClassificationAlgorithm()

# Single instance
_algorithm = GeometricIntervalClassificationAlgorithm()

def run_tool():
    processing.execAlgorithmDialog(_algorithm)
