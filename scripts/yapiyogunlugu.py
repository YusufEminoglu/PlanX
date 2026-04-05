# -*- coding: utf-8 -*-
"""
YapiYogunlugu: Estimate Building Density and Population (Block Scale)

This tool calculates total building area, estimated population, and density status for each block (polygon) using the provided average flat size, household size, and maximum residential ratio for mixed-use areas. The output includes all original fields plus calculated results.

Parameters:
- Input block layer: Polygon layer with land use and FAR/KAKS fields.
- Average flat size (m²): Typical apartment size (default: 120).
- Average household size: Typical household size (default: 2.77).
- Max residential ratio for mixed-use areas (%): Used for blocks with mixed land use (default: 30).

Output fields:
- All original fields
- Total_Building_Area: Total construction area (m²)
- Estimated_Population: Estimated population
- Area_per_Capita: Building area per person (m²)
- Density_Status: 'Critically Low', 'Normal', or 'Critically High' (based on IQR)
- Used_FAR: The FAR/KAKS value used for calculation

Usage notes:
- The tool automatically chooses the most appropriate FAR/KAKS field.
- Density status is determined using the interquartile range (IQR) of area per capita.
- Output is automatically added to the QGIS Layers panel.
"""
from qgis.PyQt.QtCore import QVariant, QCoreApplication
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterNumber,
    QgsFeature,
    QgsFields,
    QgsField,
    QgsWkbTypes,
    QgsFeatureSink
)

class YapiYogunluguAlgorithm(QgsProcessingAlgorithm):
    INPUT = 'INPUT'
    OUTPUT = 'OUTPUT'
    FLAT_SIZE = 'FLAT_SIZE'
    HOUSEHOLD_SIZE = 'HOUSEHOLD_SIZE'
    RES_RATIO = 'RES_RATIO'

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT,
            QCoreApplication.translate('Processing', 'Input block layer (must include land use and FAR/KAKS fields)'),
            [QgsProcessing.TypeVectorPolygon]
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.FLAT_SIZE,
            QCoreApplication.translate('Processing', 'Average flat size (m²)'),
            QgsProcessingParameterNumber.Double,
            120.0
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.HOUSEHOLD_SIZE,
            QCoreApplication.translate('Processing', 'Average household size'),
            QgsProcessingParameterNumber.Double,
            2.77
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.RES_RATIO,
            QCoreApplication.translate('Processing', 'Max residential ratio for mixed-use areas (%)'),
            QgsProcessingParameterNumber.Double,
            30.0,
            minValue=0.0,
            maxValue=100.0
        ))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT,
            QCoreApplication.translate('Processing', 'Estimated Building Density and Population Layer')
        ))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        avg_flat = round(self.parameterAsDouble(parameters, self.FLAT_SIZE, context), 2)
        avg_hh = round(self.parameterAsDouble(parameters, self.HOUSEHOLD_SIZE, context), 2)
        res_ratio = self.parameterAsDouble(parameters, self.RES_RATIO, context) / 100.0

        fields = source.fields()
        field_names = [f.name() for f in fields]
        if "Total_Building_Area" not in field_names:
            fields.append(QgsField("Total_Building_Area", QVariant.Double))
        if "Estimated_Population" not in field_names:
            fields.append(QgsField("Estimated_Population", QVariant.Double))
        if "Area_per_Capita" not in field_names:
            fields.append(QgsField("Area_per_Capita", QVariant.Double))
        if "Density_Status" not in field_names:
            fields.append(QgsField("Density_Status", QVariant.String))
        if "Used_FAR" not in field_names:
            fields.append(QgsField("Used_FAR", QVariant.Double))

        area_per_capita_list = []
        features = []
        for feat in source.getFeatures():
            uip = str(feat["uipfonksiyon"]).strip().upper() if "uipfonksiyon" in field_names else ""
            emsal_raw = str(feat["emsal"]) if "emsal" in field_names and feat["emsal"] is not None else None
            kaks_raw = str(feat["kaks"]) if "kaks" in field_names and feat["kaks"] is not None else None
            def convert_value(val):
                try:
                    return round(float(val.replace(",", ".")), 2)
                except:
                    return None
            emsal_val = convert_value(emsal_raw) if emsal_raw else None
            kaks_val = convert_value(kaks_raw) if kaks_raw else None
            # Use whichever is available, or the closest to 1.6 if both are present
            if emsal_val is not None and kaks_val is not None:
                if abs(emsal_val - 1.6) < abs(kaks_val - 1.6):
                    used_far = emsal_val
                else:
                    used_far = kaks_val
            elif emsal_val is not None:
                used_far = emsal_val
            elif kaks_val is not None:
                used_far = kaks_val
            else:
                continue  # Skip if neither is available
            try:
                area = feat.geometry().area()
                total_building_area = round(used_far * area, 2)
                flats = total_building_area / avg_flat
                est_pop = flats * avg_hh
                # Land use restrictions
                if any(x in uip for x in ['YERLEŞİK KONUT ALANI', 'GELİŞME KONUT ALANI']):
                    est_pop = est_pop
                elif any(x in uip for x in ['TİCARET-TURİZM-KONUT ALANI', 'TİCARET - KONUT ALANI']):
                    est_pop *= res_ratio
                else:
                    est_pop = 0
                est_pop = round(est_pop, 2)
                if est_pop > 0:
                    area_per_capita = round(total_building_area / est_pop, 2)
                    area_per_capita_list.append(area_per_capita)
                else:
                    area_per_capita = 0
                new_feat = QgsFeature(fields)
                new_feat.setGeometry(feat.geometry())
                for name in field_names:
                    new_feat.setAttribute(name, feat[name])
                new_feat.setAttribute("Used_FAR", used_far)
                new_feat.setAttribute("Total_Building_Area", total_building_area)
                new_feat.setAttribute("Estimated_Population", est_pop)
                new_feat.setAttribute("Area_per_Capita", area_per_capita)
                features.append(new_feat)
            except Exception:
                continue
        # IQR for density status
        if area_per_capita_list:
            sorted_apc = sorted(area_per_capita_list)
            n = len(sorted_apc)
            q1 = sorted_apc[int(n * 0.25)]
            q3 = sorted_apc[int(n * 0.75)]
            iqr = q3 - q1
            lower_bound = q1 - 1.5 * iqr
            upper_bound = q3 + 1.5 * iqr
        else:
            lower_bound = upper_bound = None
        (sink, dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            fields,
            QgsWkbTypes.Polygon,
            source.sourceCrs()
        )
        for feat in features:
            area_per_capita = feat["Area_per_Capita"]
            if area_per_capita_list and area_per_capita > 0 and lower_bound is not None:
                if area_per_capita < lower_bound:
                    density_status = "Critically Low"
                elif area_per_capita > upper_bound:
                    density_status = "Critically High"
                else:
                    density_status = "Normal"
            else:
                density_status = "No Population"
            feat.setAttribute("Density_Status", density_status)
            sink.addFeature(feat, QgsFeatureSink.FastInsert)
        return {self.OUTPUT: dest_id}

    def name(self):
        return 'yapiyogunlugu'

    def displayName(self):
        return 'Yapı Yoğunluğu ve Nüfus Hesapla (Ada Ölçeği)'

    def group(self):
        return QCoreApplication.translate('Processing', 'Urban Calculations')

    def groupId(self):
        return 'urban_calculations'

    def createInstance(self):
        return YapiYogunluguAlgorithm()

def run_tool():
    from qgis import processing
    processing.execAlgorithmDialog(YapiYogunluguAlgorithm()) 