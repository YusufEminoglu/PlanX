# -*- coding: utf-8 -*-
"""
DuzenlemeOrtaklik: Regulation Partnership Table Generator

This tool generates two summary tables for urban plan analysis:
1. Regulation Partnership Table: Area, count, and share of each function in the plan.
2. DOP Table: Road area, DOP percent, total public and private area.

Parameters:
- Plan approval boundary: Polygon layer (boundary of the plan)
- Plan layer: Polygon layer with land use functions
- Plan population: Integer (total population for the plan)

Outputs:
- Regulation Partnership Table: Function, count, total area, m2 per person, percent of plan
- DOP Table: Road area, DOP percent, total public area, total private area

Usage notes:
- The tool automatically clips the plan layer to the approval boundary.
- Output tables are attribute-only (no geometry) and added to the QGIS Layers panel.
"""
from qgis.PyQt.QtCore import QVariant, QCoreApplication
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFeatureSink,
    QgsFeature,
    QgsFields,
    QgsField,
    QgsWkbTypes,
    QgsFeatureSink
)
import processing

class DuzenlemeOrtaklikAlgorithm(QgsProcessingAlgorithm):
    PLAN_BOUNDARY = 'PLAN_BOUNDARY'
    PLAN_LAYER = 'PLAN_LAYER'
    PLAN_POP = 'PLAN_POP'
    OUT_TABLE = 'OUT_TABLE'
    DOP_TABLE = 'DOP_TABLE'

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.PLAN_BOUNDARY,
            QCoreApplication.translate('Processing', 'Plan approval boundary (polygon)'),
            [QgsProcessing.TypeVectorPolygon]
        ))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.PLAN_LAYER,
            QCoreApplication.translate('Processing', 'Plan layer (functions, polygons)'),
            [QgsProcessing.TypeVectorPolygon]
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.PLAN_POP,
            QCoreApplication.translate('Processing', 'Plan population'),
            QgsProcessingParameterNumber.Integer,
            minValue=1
        ))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_TABLE,
            QCoreApplication.translate('Processing', 'Regulation Partnership Table')
        ))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.DOP_TABLE,
            QCoreApplication.translate('Processing', 'DOP Table')
        ))

    def processAlgorithm(self, parameters, context, feedback):
        # Get source strings for processing.run
        plan_layer_source = self.parameterAsString(parameters, self.PLAN_LAYER, context)
        boundary_layer_source = self.parameterAsString(parameters, self.PLAN_BOUNDARY, context)
        plan_pop = self.parameterAsInt(parameters, self.PLAN_POP, context)

        # For reading features
        plan_layer = self.parameterAsSource(parameters, self.PLAN_LAYER, context)
        boundary_layer = self.parameterAsSource(parameters, self.PLAN_BOUNDARY, context)

        # Get approval boundary geometry (first feature)
        boundary_geom = next(boundary_layer.getFeatures()).geometry()
        plan_area = boundary_geom.area()

        # Clip plan layer to boundary using source strings
        clipped_result = processing.run(
            'native:clip',
            {
                'INPUT': plan_layer_source,
                'OVERLAY': boundary_layer_source,
                'OUTPUT': 'memory:'
            },
            context=context,
            feedback=feedback
        )
        clipped_layer = clipped_result['OUTPUT']

        # Functions considered as private area
        private_functions = {
            'TİCARET - KONUT ALANI', 'TİCARET-TURİZM-KONUT ALANI', 'GELİŞME KONUT ALANI',
            'YERLEŞİK KONUT ALANI', 'TİCARET ALANI', 'T1 TİCARET ALANI', 'T2 TİCARET ALANI',
            'T3 TİCARET ALANI', 'TOPTAN TİCARET ALANI', 'TOPLU İŞYERLERİ', 'ÖZEL ANAOKULU ALANI',
            'ÖZEL EĞİTİM ALANI', 'ÖZEL SAĞLIK TESİSİ ALANI', 'ÖZEL AÇIK SPOR TESİSİ ALANI',
            'ÖZEL KAPALI SPOR TESİSİ ALANI', 'ÖZEL KREŞ, GÜNDÜZ BAKIMEVİ', 'ÖZEL KÜLTÜREL TESİS ALANI',
            'ÖZEL SOSYAL TESİS ALANI', 'ÖZEL YURT ALANI'
        }

        stats = {}
        total_area = 0
        private_area = 0

        for feat in clipped_layer.getFeatures():
            func = feat['uipfonksiyon'] if 'uipfonksiyon' in feat.fields().names() else 'UNKNOWN'
            area = feat.geometry().area()
            total_area += area
            if func in private_functions:
                private_area += area
            if func not in stats:
                stats[func] = {'area': 0.0, 'count': 0}
            stats[func]['area'] += area
            stats[func]['count'] += 1

        # Table 1: Regulation Partnership Table
        table1_fields = QgsFields()
        table1_fields.append(QgsField('Function', QVariant.String))
        table1_fields.append(QgsField('Count', QVariant.Int))
        table1_fields.append(QgsField('Total_Area_m2', QVariant.Double))
        table1_fields.append(QgsField('Area_per_Person', QVariant.Double))
        table1_fields.append(QgsField('Percent_of_Plan', QVariant.Double))

        (sink1, _) = self.parameterAsSink(parameters, self.OUT_TABLE, context,
                                          table1_fields, QgsWkbTypes.NoGeometry, plan_layer.sourceCrs())

        for func, data in stats.items():
            area = data['area']
            count = data['count']
            f = QgsFeature(table1_fields)
            f.setAttributes([
                func,
                count,
                round(area, 2),
                round(area / plan_pop, 2),
                round((area / plan_area) * 100, 2)
            ])
            sink1.addFeature(f, QgsFeatureSink.FastInsert)

        # Table 2: DOP Table
        road_area = plan_area - total_area
        public_area = total_area - private_area + road_area
        dop_percent = public_area / plan_area * 100 if plan_area > 0 else 0

        table2_fields = QgsFields()
        table2_fields.append(QgsField('Road_Area_m2', QVariant.Double))
        table2_fields.append(QgsField('DOP_Percent', QVariant.Double))
        table2_fields.append(QgsField('Total_Public_Area_m2', QVariant.Double))
        table2_fields.append(QgsField('Total_Private_Area_m2', QVariant.Double))

        (sink2, _) = self.parameterAsSink(parameters, self.DOP_TABLE, context,
                                          table2_fields, QgsWkbTypes.NoGeometry, plan_layer.sourceCrs())

        f2 = QgsFeature(table2_fields)
        f2.setAttributes([
            round(road_area, 2),
            round(dop_percent, 2),
            round(public_area, 2),
            round(private_area, 2)
        ])
        sink2.addFeature(f2, QgsFeatureSink.FastInsert)

        return {
            self.OUT_TABLE: sink1,
            self.DOP_TABLE: sink2
        }

    def name(self):
        return 'duzenlemeortaklik'

    def displayName(self):
        return 'Regulation Partnership Table'

    def group(self):
        return QCoreApplication.translate('Processing', 'Plan Analysis Tools')

    def groupId(self):
        return 'plan_analysis_tools'

    def createInstance(self):
        return DuzenlemeOrtaklikAlgorithm()

def run_tool():
    from qgis import processing
    processing.execAlgorithmDialog(DuzenlemeOrtaklikAlgorithm()) 