# -*- coding: utf-8 -*-
"""
CoverageFootprint: Generate Building Footprints from Coverage (TAKS) Field

This tool creates building footprint polygons by scaling each input parcel according to a user-selected coverage (TAKS) field. The output layer includes all original attributes, the used coverage value, and the resulting footprint area in square meters.

Parameters:
- Input parcel layer: Polygon layer containing parcels.
- Coverage (TAKS) field: Numeric field in the input layer representing the coverage ratio (e.g., 0.40 for 40%).
- Output footprint layer: The resulting scaled building footprints.

The output layer will have all original fields, plus:
- coverage: The TAKS value used for each feature (float, 2 decimals)
- area_m2: The area of the resulting footprint (float, 2 decimals)

Usage notes:
- The tool scales each parcel polygon about its centroid so that the new area = original area × coverage.
- Works with both singlepart and multipart polygons.
- Output is automatically added to the QGIS Layers panel.
"""
from qgis.PyQt.QtCore import QVariant, QCoreApplication
from qgis.core import (
    QgsProcessing,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterFeatureSink,
    QgsFeatureSink,
    QgsFields,
    QgsField
)
import math

MENU_LABEL = "CoverageFootprint"

class CoverageFootprintAlgorithm(QgsProcessingAlgorithm):
    INPUT_LAYER = 'INPUT_LAYER'
    COVERAGE_FIELD = 'COVERAGE_FIELD'
    OUTPUT_LAYER = 'OUTPUT_LAYER'

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_LAYER,
                QCoreApplication.translate('Processing', 'Input parcel layer'),
                [QgsProcessing.TypeVectorPolygon]
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.COVERAGE_FIELD,
                QCoreApplication.translate('Processing', 'Coverage (TAKS) field'),
                parentLayerParameterName=self.INPUT_LAYER
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_LAYER,
                QCoreApplication.translate('Processing', 'Output footprint layer')
            )
        )

    def name(self):
        return 'coveragefootprint'

    def displayName(self):
        return MENU_LABEL

    def group(self):
        return 'PlanX Tools'

    def groupId(self):
        return 'planx_tools'

    def shortHelpString(self):
        return QCoreApplication.translate('Processing',
            """
            Generates building footprints by scaling each parcel polygon according to a selected coverage (TAKS) field. The output layer includes all original attributes, the used coverage value, and the resulting footprint area in square meters.

            Parameters:
            - Input parcel layer: Polygon layer containing parcels.
            - Coverage (TAKS) field: Numeric field representing the coverage ratio (e.g., 0.40 for 40%).
            - Output footprint layer: The resulting scaled building footprints.

            Output fields:
            - All original fields
            - coverage: The TAKS value used (float, 2 decimals)
            - area_m2: The area of the resulting footprint (float, 2 decimals)
            """
        )

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT_LAYER, context)
        coverage_field = self.parameterAsString(parameters, self.COVERAGE_FIELD, context)

        # Prepare output fields: all original + 'coverage' + 'area_m2'
        fields = QgsFields()
        for f in source.fields():
            fields.append(f)
        fields.append(QgsField('coverage', QVariant.Double, 'double', 20, 2))
        fields.append(QgsField('area_m2', QVariant.Double, 'double', 20, 2))

        sink, dest_id = self.parameterAsSink(
            parameters, self.OUTPUT_LAYER, context,
            fields, source.wkbType(), source.sourceCrs()
        )

        features = source.getFeatures()
        total = source.featureCount() or 1
        for i, feat in enumerate(features):
            if feedback.isCanceled():
                break
            geom = feat.geometry()
            centroid_pt = geom.centroid().asPoint()
            orig_area = geom.area()
            cov_val = feat[coverage_field]
            try:
                coverage = float(cov_val)
            except (TypeError, ValueError):
                coverage = 0.0
            target_area = orig_area * coverage
            sFactor = math.sqrt(target_area / orig_area) if orig_area > 0 and coverage > 0 else 0.0
            # Scale each vertex relative to centroid
            if geom.isMultipart():
                mpoly = geom.asMultiPolygon()
                scaled_mpoly = []
                for poly in mpoly:
                    scaled_poly = []
                    for ring in poly:
                        scaled_ring = []
                        for pt in ring:
                            x_new = centroid_pt.x() + sFactor * (pt.x() - centroid_pt.x())
                            y_new = centroid_pt.y() + sFactor * (pt.y() - centroid_pt.y())
                            scaled_ring.append(QgsPointXY(x_new, y_new))
                        scaled_poly.append(scaled_ring)
                    scaled_mpoly.append(scaled_poly)
                scaled_geom = QgsGeometry.fromMultiPolygonXY(scaled_mpoly)
            else:
                poly = geom.asPolygon()
                scaled_poly = []
                for ring in poly:
                    scaled_ring = []
                    for pt in ring:
                        x_new = centroid_pt.x() + sFactor * (pt.x() - centroid_pt.x())
                        y_new = centroid_pt.y() + sFactor * (pt.y() - centroid_pt.y())
                        scaled_ring.append(QgsPointXY(x_new, y_new))
                    scaled_poly.append(scaled_ring)
                scaled_geom = QgsGeometry.fromPolygonXY(scaled_poly)
            # Create and add new feature
            new_feat = QgsFeature(fields)
            new_feat.setGeometry(scaled_geom)
            attrs = list(feat.attributes()) + [round(coverage, 2), round(scaled_geom.area(), 2)]
            new_feat.setAttributes(attrs)
            sink.addFeature(new_feat, QgsFeatureSink.FastInsert)
            feedback.setProgress(int((i + 1) / total * 100))
        return {self.OUTPUT_LAYER: dest_id}

    def createInstance(self):
        return CoverageFootprintAlgorithm()

def run_tool():
    from qgis import processing
    processing.execAlgorithmDialog(CoverageFootprintAlgorithm())
