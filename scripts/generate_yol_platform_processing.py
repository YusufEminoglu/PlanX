from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterFeatureSink,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsWkbTypes,
    QgsFeatureSink,
    QgsVectorLayer,
    QgsProcessing,
    QgsProject,
    QgsProcessingUtils
)

class GenerateYolPlatform(QgsProcessingAlgorithm):
    """
    QGIS Processing Algorithm to generate road platform lines (center, median, sidewalk) from a road centerline layer.
    All input parameter names and logic are preserved as in the original script.
    """
    INPUT = 'INPUT'
    OUTPUT = 'OUTPUT'

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT,
            'Road Centerline Layer',
            [QgsProcessing.TypeVectorLine]
        ))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT,
            'Road Platform Layer'
        ))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)

        # Define output fields
        fields = QgsFields()
        fields.append(QgsField("source_fid", QVariant.Int))
        fields.append(QgsField("yolTipi", QVariant.String))
        fields.append(QgsField("type", QVariant.String))     # center, refuj, kaldirim
        fields.append(QgsField("side", QVariant.String))     # left_outer, left_inner, right_outer, right_inner, none

        (sink, dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            fields,
            QgsWkbTypes.MultiLineString,
            source.sourceCrs()
        )

        def offset_geometry(geom: QgsGeometry, offset: float) -> QgsGeometry:
            """
            Returns a geometry offset by the specified distance.
            """
            return geom.offsetCurve(offset, 8, QgsGeometry.JoinStyleRound, 2.0)

        for feat in source.getFeatures():
            fid = feat["fid"]
            yol_tipi = feat["yolTipi"]

            # Skip: BICYCLE ROAD
            if yol_tipi == "BİSİKLET YOLU":
                continue

            geom: QgsGeometry = feat.geometry()
            refuj = feat["refujGenislik"] or 0
            kaldirim = feat["kaldirimGenislik"] or 0
            yol_genislik2 = feat["yolGenislik2"] or 0

            # Center line feature
            center_feat = QgsFeature()
            center_feat.setFields(fields)
            center_feat.setAttribute("source_fid", fid)
            center_feat.setAttribute("yolTipi", yol_tipi)
            center_feat.setAttribute("type", "center")
            center_feat.setAttribute("side", "none")
            center_feat.setGeometry(geom)
            sink.addFeature(center_feat, QgsFeatureSink.FastInsert)

            # Median (refuj) features
            if refuj > 0:
                for side, direction in [("left", -1), ("right", 1)]:
                    offset = direction * (refuj / 2.0)
                    refuj_geom = offset_geometry(geom, offset)
                    if refuj_geom and not refuj_geom.isEmpty():
                        refuj_feat = QgsFeature()
                        refuj_feat.setFields(fields)
                        refuj_feat.setAttribute("source_fid", fid)
                        refuj_feat.setAttribute("yolTipi", yol_tipi)
                        refuj_feat.setAttribute("type", "refuj")
                        refuj_feat.setAttribute("side", side)
                        refuj_feat.setGeometry(refuj_geom)
                        sink.addFeature(refuj_feat, QgsFeatureSink.FastInsert)

            # Sidewalk (kaldirim) features
            for side, direction in [("left", -1), ("right", 1)]:
                outer_offset = direction * (yol_genislik2 / 2.0)
                outer_geom = offset_geometry(geom, outer_offset)

                if outer_geom and not outer_geom.isEmpty():
                    outer_feat = QgsFeature()
                    outer_feat.setFields(fields)
                    outer_feat.setAttribute("source_fid", fid)
                    outer_feat.setAttribute("yolTipi", yol_tipi)
                    outer_feat.setAttribute("type", "kaldirim")
                    outer_feat.setAttribute("side", f"{side}_outer")
                    outer_feat.setGeometry(outer_geom)
                    sink.addFeature(outer_feat, QgsFeatureSink.FastInsert)

                # If not PEDESTRIAN ROAD AND AREA, generate inner sidewalk lines
                if yol_tipi != "YAYA YOLU VE BÖLGESİ":
                    inner_offset = outer_offset + (direction * -1) * kaldirim
                    inner_geom = offset_geometry(geom, inner_offset)

                    if inner_geom and not inner_geom.isEmpty():
                        inner_feat = QgsFeature()
                        inner_feat.setFields(fields)
                        inner_feat.setAttribute("source_fid", fid)
                        inner_feat.setAttribute("yolTipi", yol_tipi)
                        inner_feat.setAttribute("type", "kaldirim")
                        inner_feat.setAttribute("side", f"{side}_inner")
                        inner_feat.setGeometry(inner_geom)
                        sink.addFeature(inner_feat, QgsFeatureSink.FastInsert)

        return {self.OUTPUT: dest_id}

    def name(self):
        return 'generate_yol_platform'

    def displayName(self):
        return 'Generate Road Platform'

    def group(self):
        return 'Road Operations'

    def groupId(self):
        return 'road_operations'

    def createInstance(self):
        return GenerateYolPlatform()

MENU_LABEL = "Generate Road Platform"

def run_tool():
    from qgis import processing
    processing.execAlgorithmDialog(GenerateYolPlatform())
