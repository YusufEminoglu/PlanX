# -*- coding: utf-8 -*-
"""
Random Trees Inside Polygons for PlanX
Generates random point features ("trees") within input polygons,
symbolized by a PNG tree icon sized by a random 'height' attribute.
"""
import os, random, math
from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
    QgsProcessingParameterVectorDestination,
    QgsFeatureSink,
    QgsFields,
    QgsField,
    QgsFeature,
    QgsWkbTypes,
    QgsProcessingException,
    QgsMarkerSymbol,
    QgsRasterMarkerSymbolLayer,
    QgsProperty,
    QgsPointXY,
    QgsGeometry,
    QgsProcessingUtils,
    QgsSingleSymbolRenderer,
    QgsSymbolLayer
)
from qgis import processing

MENU_LABEL = "Random Trees"

class RandomTreesAlgorithm(QgsProcessingAlgorithm):
    INPUT = 'INPUT'
    MIN_HEIGHT = 'MIN_HEIGHT'
    MAX_HEIGHT = 'MAX_HEIGHT'
    DENSITY = 'DENSITY'
    MIN_DISTANCE = 'MIN_DISTANCE'
    OUTPUT = 'OUTPUT'

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT,
                'Input polygon layer',
                [QgsProcessing.TypeVectorPolygon]
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MIN_HEIGHT,
                'Minimum tree height (m)',
                type=QgsProcessingParameterNumber.Double,
                defaultValue=1.0
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MAX_HEIGHT,
                'Maximum tree height (m)',
                type=QgsProcessingParameterNumber.Double,
                defaultValue=5.0
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.DENSITY,
                'Tree density (trees per 500 m²)',
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=1
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MIN_DISTANCE,
                'Minimum distance between trees (m)',
                type=QgsProcessingParameterNumber.Double,
                defaultValue=3.0,
                minValue=0.0
            )
        )
        self.addParameter(
            QgsProcessingParameterVectorDestination(
                self.OUTPUT,
                'Output tree points',
                type=QgsProcessing.TypeVectorPoint
            )
        )

    def name(self):
        return 'random_trees'

    def displayName(self):
        return 'Random Trees Inside Polygons'

    def group(self):
        return 'PlanX Tools'

    def groupId(self):
        return 'planx_tools'

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        minH = self.parameterAsDouble(parameters, self.MIN_HEIGHT, context)
        maxH = self.parameterAsDouble(parameters, self.MAX_HEIGHT, context)
        density = int(self.parameterAsDouble(parameters, self.DENSITY, context))
        minDist = self.parameterAsDouble(parameters, self.MIN_DISTANCE, context)

        fields = QgsFields()
        fields.append(QgsField('orig_fid', QVariant.Int))
        fields.append(QgsField('height', QVariant.Double))
        sink, dest_id = self.parameterAsSink(
            parameters, self.OUTPUT, context,
            fields, QgsWkbTypes.Point, source.sourceCrs()
        )

        total = source.featureCount() or 1
        for i, feat in enumerate(source.getFeatures()):
            if feedback.isCanceled():
                break
            geom = feat.geometry()
            area = geom.area()
            count = int(density * area / 500.0)
            if count <= 0:
                continue
            bbox = geom.boundingBox()
            placed = []
            for _ in range(count):
                for _attempt in range(1000):
                    x = random.uniform(bbox.xMinimum(), bbox.xMaximum())
                    y = random.uniform(bbox.yMinimum(), bbox.yMaximum())
                    pt = QgsPointXY(x, y)
                    if not geom.contains(QgsGeometry.fromPointXY(pt)):
                        continue
                    if any(pt.distance(prev) < minDist for prev in placed):
                        continue
                    placed.append(pt)
                    break
                else:
                    continue
                h = random.uniform(minH, maxH)
                new_feat = QgsFeature(fields)
                new_feat.setGeometry(QgsGeometry.fromPointXY(placed[-1]))
                new_feat['orig_fid'] = feat.id()
                new_feat['height'] = h
                sink.addFeature(new_feat, QgsFeatureSink.FastInsert)
            feedback.setProgress(int((i + 1) / total * 100))

                # Return the generated tree points layer
        return {self.OUTPUT: dest_id}

    def createInstance(self):
        return RandomTreesAlgorithm()

# Entry point

def run_tool():
    processing.execAlgorithmDialog(RandomTreesAlgorithm())
