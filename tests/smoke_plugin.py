"""Headless QGIS smoke test for every registered PlanX algorithm."""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qgis.core import QgsApplication

def _assert_seismic_renderer_field(algorithms):
    """The seismic tool's map colouring must stay on collapse_prob.

    ``_apply_default_renderer`` colours a result layer by the last numeric
    field whose name matches one of its preference tokens. Adding
    debris_pile_m3, debris_mass_t, collapse_freq and damage_state to this
    algorithm's schema moved that choice, and nothing else in the suite would
    have noticed: every output still verifies, only the map changes colour.
    The field list is read back from the algorithm instead of being copied
    here, so the two cannot drift apart.
    """
    from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsVectorLayer

    algorithm = next(item for item in algorithms if item.name() == "seismicdebris")
    base = QgsVectorLayer(
        "Polygon?crs=EPSG:32635&field=area_m2:double&field=floors:integer",
        "buildings", "memory")
    fields = algorithm.output_fields(base.fields())
    layer = QgsVectorLayer("Point?crs=EPSG:32635", "seismic", "memory")
    layer.dataProvider().addAttributes(list(fields))
    layer.updateFields()
    widths = [0.05, 0.95]
    for index, value in enumerate(widths):
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(index, 0)))
        attributes = [None] * fields.count()
        attributes[fields.lookupField("collapse_prob")] = value
        # A later field carrying a preference token would win instead, which is
        # the drift this asserts against.
        attributes[fields.lookupField("debris_mass_t")] = 1.0 + index
        feature.setAttributes(attributes)
        layer.dataProvider().addFeature(feature)
    algorithm._decorate_layer(layer)
    chosen = layer.renderer().classAttribute()
    if chosen != "collapse_prob":
        raise AssertionError(
            f"Seismic results are now coloured by '{chosen}', not collapse_prob")


def main():
    with tempfile.TemporaryDirectory(prefix="planx-smoke-") as profile:
        print("PlanX smoke: initializing QGIS", flush=True)
        app = QgsApplication([], True, profile, "external")
        app.initQgis()
        print("PlanX smoke: importing provider", flush=True)
        from planx.provider import PlanXProvider
        from planx.algorithms.base import PlanXAlgorithm
        from planx.engine.provenance import build_manifest
        from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsVectorLayer
        provider = PlanXProvider()
        try:
            print("PlanX smoke: loading algorithms", flush=True)
            provider.loadAlgorithms()
            algorithms = provider.algorithms()
            names = [algorithm.name() for algorithm in algorithms]
            if len(algorithms) != 72:
                raise AssertionError(f"Expected 72 algorithms, got {len(algorithms)}")
            if len(names) != len(set(names)):
                raise AssertionError("Duplicate PlanX algorithm ids")
            for algorithm in algorithms:
                algorithm.initAlgorithm()
                keys = [parameter.name() for parameter in algorithm.parameterDefinitions()]
                if len(keys) != len(set(keys)):
                    raise AssertionError(f"Duplicate parameter in {algorithm.name()}")
            layer = QgsVectorLayer(
                "LineString?crs=EPSG:32635&field=dir_code:integer&field=cost_fwd:double&field=cost_rev:double",
                "prepared", "memory")
            feature = QgsFeature(layer.fields())
            feature.setGeometry(QgsGeometry.fromPolylineXY(
                [QgsPointXY(0, 0), QgsPointXY(1, 0)]))
            feature.setAttributes([1, 2.0, 7.0])
            layer.dataProvider().addFeature(feature)
            graph, _, _ = PlanXAlgorithm.network_graph(layer)
            if graph.adj_cost.tolist() != [2.0]:
                raise AssertionError("Prepared-network direction/cost contract failed")
            result_layer = QgsVectorLayer(
                "Point?crs=EPSG:32635&field=access_score:double",
                "result", "memory")
            result_features = []
            for x, score in ((0, 10.0), (1, 90.0)):
                result_feature = QgsFeature(result_layer.fields())
                result_feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, 0)))
                result_feature.setAttributes([score])
                result_features.append(result_feature)
            result_layer.dataProvider().addFeatures(result_features)
            algorithm = algorithms[0]
            algorithm._planx_audit = build_manifest("planx:test", {}, [], "test")
            algorithm._decorate_layer(result_layer)
            if not result_layer.customProperty("planx/analysis_fingerprint", ""):
                raise AssertionError("Output provenance decoration failed")
            if result_layer.renderer().classAttribute() != "access_score":
                raise AssertionError("Default analytical renderer failed")
            _assert_seismic_renderer_field(algorithms)
            print(f"PASS PlanX provider: {len(algorithms)} unique algorithms initialized")
        finally:
            provider.unload()
            app.exitQgis()


if __name__ == "__main__":
    main()
