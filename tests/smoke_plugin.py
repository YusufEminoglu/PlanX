"""Headless QGIS smoke test for every registered PlanX algorithm."""
from __future__ import annotations

import contextlib
import os
import shutil
import sys
import tempfile
import traceback

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


def _assert_ground_units():
    """Areas and lengths come out in ground metres, on three different CRSs.

    Two defects are invisible in every other check in this suite, because both
    of them scale a number by a constant rather than making it absurd. A
    projected layer's coordinate unit is not always the metre (state plane:
    0.3048), and a conformal projection's own scale is not always 1 (EPSG:3857
    away from the equator: 1/cos(lat), so 1.757 in area at 41 N). The runtime
    matrix cannot see either, because its fixture city sits at the EPSG:3857
    origin - the one place on the grid where the scale is exactly 1.

    Each expectation here is written out from the CRS definition rather than
    read back from the code under test: a 20-unit box at 41 N is a box of
    20*cos(41) ground metres a side, and a foot is 0.3048 of a metre. The 1 per
    cent tolerance is for the difference between the sphere EPSG:3857 is
    defined on and the WGS84 ellipsoid QGIS measures on, which is 0.09 per cent
    at 41 N and 0.67 per cent at the equator.
    """
    import math

    from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                           QgsCoordinateTransformContext, QgsGeometry,
                           QgsPointXY, QgsRectangle)
    from planx.algorithms import _units

    context = QgsCoordinateTransformContext()
    web = QgsCoordinateReferenceSystem("EPSG:3857")
    centre = QgsCoordinateTransform(
        QgsCoordinateReferenceSystem("EPSG:4326"), web, context
    ).transform(QgsPointXY(29.0, 41.0))
    side = 20.0
    box = QgsGeometry.fromRect(QgsRectangle(
        centre.x() - side / 2, centre.y() - side / 2,
        centre.x() + side / 2, centre.y() + side / 2))

    ground = _units.GroundUnits(web, context)
    expected = (side * math.cos(math.radians(41.0))) ** 2
    measured = ground.area(box)
    if abs(measured - expected) > 0.01 * expected:
        raise AssertionError(
            f"a 20 unit box at 41 N on EPSG:3857 measures {measured:.3f} m2, "
            f"not the {expected:.3f} m2 of ground it stands for (the layer's own "
            f"area() is {box.area():.3f})")

    # The same idea, on a CRS whose unit is the US survey foot. Placed at a real
    # location - Los Angeles, in the California zone 5 projection - rather than
    # near the false origin, because a conformal projection carries its own
    # scale factor as well: the expectation is the unit factor to within 2 per
    # cent, which the defect this guards against misses by 3.28x in length and
    # 10.76x in area.
    feet = QgsCoordinateReferenceSystem("EPSG:2229")
    foot = 0.30480060960122
    la = QgsCoordinateTransform(
        QgsCoordinateReferenceSystem("EPSG:4326"), feet, context
    ).transform(QgsPointXY(-118.25, 34.05))
    side_ft = 100.0
    foot_box = QgsGeometry.fromRect(QgsRectangle(
        la.x() - side_ft / 2, la.y() - side_ft / 2,
        la.x() + side_ft / 2, la.y() + side_ft / 2))
    foot_ground = _units.GroundUnits(feet, context)
    foot_expected = (side_ft * foot) ** 2
    foot_measured = foot_ground.area(foot_box)
    if abs(foot_measured - foot_expected) > 0.02 * foot_expected:
        raise AssertionError(
            f"a 100 foot square in the California zone 5 CRS measures "
            f"{foot_measured:.3f} m2, not the {foot_expected:.3f} m2 of ground it "
            f"stands for (the layer's own area() is {foot_box.area():.3f})")
    line = QgsGeometry.fromPolylineXY(
        [QgsPointXY(la.x(), la.y() - 500.0), QgsPointXY(la.x(), la.y() + 500.0)])
    per_metre = foot_ground.per_metre(line)
    if abs(per_metre - 1.0 / foot) > 0.02 / foot:
        raise AssertionError(
            f"a metre is {per_metre:.4f} layer units in the California zone 5 CRS, "
            f"not {1.0 / foot:.4f}")

    # A metre-projected CRS in a UTM zone: the factor is the projection's own,
    # 1/0.9996 at the central meridian, so it must stay near 1 rather than be
    # corrected away.
    utm = QgsCoordinateReferenceSystem("EPSG:32635")
    utm_box = QgsGeometry.fromRect(QgsRectangle(500000.0, 4540000.0,
                                                501000.0, 4541000.0))
    utm_measured = _units.GroundUnits(utm, context).area(utm_box)
    if not 0.99 * 1e6 < utm_measured < 1.01 * 1e6:
        raise AssertionError(
            f"a 1000 m square on EPSG:32635 measures {utm_measured:.1f} m2, which "
            f"is not a metre-projected CRS left alone")


def main():
    """Run the checks, then leave without letting QGIS shut down.

    QGIS's shutdown is a hazard on this runtime once a provider has been
    loaded. Measured, not guessed: this module printed its verdict and then
    never returned when run by hand, while the same module under ``pf verify``
    finished normally - and the difference is the QGIS profile. Both give
    ``QgsApplication`` a throwaway profile of their own; only ``pf verify``
    also sets ``QGIS_CUSTOM_CONFIG_PATH`` (TRAPS 4.6), so a profile folder
    passed to the constructor does not keep the shutdown away from the real
    user profile. ``exitQgis`` is the other half, and can block for minutes.
    So the application is deliberately still a live local of this frame when
    ``os._exit`` runs: shutdown is short-circuited rather than waited out, as
    in the runtime matrix, and the verdict is the exit code on every runtime
    and either environment.
    """
    profile = tempfile.mkdtemp(prefix="planx-smoke-")
    app = None
    try:
        print("PlanX smoke: initializing QGIS", flush=True)
        app = QgsApplication([], True, profile, "external")
        app.initQgis()
        print("PlanX smoke: importing provider", flush=True)
        from planx.provider import PlanXProvider
        from planx.algorithms.base import PlanXAlgorithm
        from planx.engine.provenance import build_manifest
        from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsVectorLayer
        provider = PlanXProvider()
        print("PlanX smoke: loading algorithms", flush=True)
        provider.loadAlgorithms()
        algorithms = provider.algorithms()
        names = [algorithm.name() for algorithm in algorithms]
        if len(algorithms) != 74:
            raise AssertionError(f"Expected 74 algorithms, got {len(algorithms)}")
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
        _assert_ground_units()
        print(f"PASS PlanX provider: {len(algorithms)} unique algorithms initialized")

        # A failure never unwinds this frame either, so the QgsApplication is
        # never destroyed and the exit code is the verdict.
        _teardown(provider, app)
        sys.stdout.flush()
        # Best effort: QGIS still holds the profile open, so this may not
        # clear everything. It is a temporary directory either way.
        shutil.rmtree(profile, ignore_errors=True)
        os._exit(0)
    except BaseException:
        traceback.print_exc()
        sys.stdout.flush()
        shutil.rmtree(profile, ignore_errors=True)
        os._exit(1)


def _teardown(provider, application):
    """Hand the provider back, and shut QGIS down everywhere but Windows.

    ``exitQgis`` is one half of the hazard this module's ``main`` works around:
    once a provider has been loaded it can block for minutes here, and the
    matrix suite skips it on Windows for the same reason. The unload itself is
    cheap and worth doing, so it always runs.
    """
    with contextlib.suppress(Exception):
        provider.unload()
    if os.name == "nt":
        return
    with contextlib.suppress(Exception):
        application.exitQgis()


if __name__ == "__main__":
    main()
