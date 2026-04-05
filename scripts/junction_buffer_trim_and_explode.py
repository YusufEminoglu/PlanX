from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterNumber,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsWkbTypes,
    QgsFeatureSink,
    QgsSpatialIndex,
    QgsProcessingException,
    QgsLineString,
    QgsPointXY,
    QgsProject
)
import os

class JunctionBufferTrimAndExplode(QgsProcessingAlgorithm):
    """
    QGIS Processing Algorithm to trim and explode road platform lines at junction buffer areas.
    Operates on the output of the Generate Road Platform tool.
    All parameter names and logic are preserved from the original script.
    """
    INPUT = 'INPUT'
    OUTPUT = 'OUTPUT'
    RADIUS = 'RADIUS'

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT,
                'Road Platform Layer',
                [QgsProcessing.TypeVectorLine]
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                name=self.RADIUS,
                description='Junction Area Diameter (meters)',
                type=QgsProcessingParameterNumber.Double,
                defaultValue=8.0
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                'Trimmed Layer'
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        radius = self.parameterAsDouble(parameters, self.RADIUS, context)

        fields = source.fields()
        fields.append(QgsField("parent_fid", QVariant.Int))
        fields.append(QgsField("type_link", QVariant.String))
        fields.append(QgsField("parca_no", QVariant.Int))
        fields.append(QgsField("junction_id", QVariant.Int))
        fields.append(QgsField("length_m", QVariant.Double))
        fields.append(QgsField("eligibility", QVariant.Int))

        (sink, dest_id) = self.parameterAsSink(parameters, self.OUTPUT, context, fields, QgsWkbTypes.LineString, source.sourceCrs())

        centers = [f for f in source.getFeatures() if f['type'] == 'center']
        center_index = QgsSpatialIndex()
        for f in centers:
            center_index.insertFeature(f)

        features_by_type = {
            'refuj': [],
            'kaldirim': [],
        }

        all_features = [f for f in source.getFeatures()]

        for f in all_features:
            if f['type'] == 'center':
                f_copy = QgsFeature(fields)
                f_copy.setGeometry(f.geometry())
                length = f.geometry().length()
                eligible = 1 if length <= 10 else 0
                f_copy.setAttributes(f.attributes() + [f.id(), 'center', 0, -1, length, eligible])
                sink.addFeature(f_copy)
            elif f['type'] in features_by_type:
                features_by_type[f['type']].append(f)

        junction_buffers = []
        outer_buffers = []
        for i, f1 in enumerate(centers):
            for f2 in centers[i + 1:]:
                if f1.geometry().intersects(f2.geometry()):
                    point = f1.geometry().intersection(f2.geometry()).centroid().asPoint()
                    inner_buf = QgsGeometry.fromPointXY(point).buffer((radius + 1) / 2.0, 8)
                    outer_buf = QgsGeometry.fromPointXY(point).buffer((radius + 5 + 1) / 2.0, 8)
                    junction_buffers.append((len(junction_buffers), inner_buf))
                    outer_buffers.append((len(outer_buffers), outer_buf))

        trimmed_feats = []

        for feature_type in ['refuj', 'kaldirim']:
            for f in features_by_type[feature_type]:
                orig_geom = f.geometry()
                source_id = f['source_fid']
                yol_tipi = f['yolTipi']

                if feature_type == 'kaldirim' and 'inner' in f['side'] and yol_tipi == 'YAYA YOLU VE BÖLGESİ':
                    continue

                trimmed_inner = QgsGeometry(orig_geom)
                for jid, buf in junction_buffers:
                    if trimmed_inner.intersects(buf):
                        trimmed_inner = trimmed_inner.difference(buf)

                trimmed_final_parts = []
                outside_parts = []

                for oid, obuf in outer_buffers:
                    if trimmed_inner.intersects(obuf):
                        intersection = trimmed_inner.intersection(obuf)
                        if not intersection.isEmpty():
                            trimmed_final_parts.append(intersection)
                        trimmed_inner = trimmed_inner.difference(obuf)

                if not trimmed_final_parts and not trimmed_inner.isEmpty():
                    trimmed_final_parts.append(trimmed_inner)
                else:
                    if not trimmed_inner.isEmpty():
                        trimmed_final_parts.append(trimmed_inner)

                for part in trimmed_final_parts:
                    parts = part.asGeometryCollection() if part.isMultipart() else [part]
                    for i, subpart in enumerate(parts):
                        part_line = subpart.constGet()
                        if isinstance(part_line, QgsLineString) and len(part_line.points()) > 1:
                            junc_id = -1
                            for jid, buf in junction_buffers:
                                if subpart.intersects(buf):
                                    junc_id = jid
                                    break

                            length = subpart.length()
                            eligible = 1 if length <= 10 else 0

                            f_trim = QgsFeature(fields)
                            f_trim.setGeometry(subpart)
                            f_trim.setAttributes(f.attributes() + [f.id(), 'original', i + 1, junc_id, length, eligible])
                            sink.addFeature(f_trim)
                            trimmed_feats.append(f_trim)

        result = {self.OUTPUT: dest_id}

        # Apply QML style to the output layer by name 'Trimmed Layer'
        qml_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'styles', 'junction.qml')
        output_layer_name = 'Trimmed Layer'
        for lyr in QgsProject.instance().mapLayers().values():
            if lyr.name() == output_layer_name:
                if os.path.exists(qml_path):
                    lyr.loadNamedStyle(qml_path)
                    lyr.triggerRepaint()
                break

        return result

    def name(self):
        return 'junction_buffer_trim_and_explode'

    def displayName(self):
        return 'Junction Buffer Trim and Explode'

    def group(self):
        return 'Road Operations'

    def groupId(self):
        return 'road_operations'

    def createInstance(self):
        return JunctionBufferTrimAndExplode()

# For PlanX menu integration:
MENU_LABEL = "Junction Buffer Trim and Explode"

def run_tool():
    from qgis import processing
    processing.execAlgorithmDialog(JunctionBufferTrimAndExplode()) 