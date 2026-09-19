# -*- coding: utf-8 -*-
"""Ground metres for one layer's geometries: the unit, and the projection's own scale.

Two different mistakes produce the same kind of damage - a number that is wrong
by a constant factor, and therefore reads as entirely plausible:

**The unit.** A projected layer's coordinates are metres only when the CRS says
so. A state-plane layer in US survey feet has a linear unit of 0.3048 m, so a
footprint read off it with ``QgsGeometry.area()`` and called m2 is 10.76x too
large, and every volume, mass and density built on it inherits that.

**The scale.** A conformal projection measures its own coordinates with a local
scale factor. EPSG:3857's "metre" is the sphere's, defined at the equator, and
its scale is 1/cos(lat) away from it: at 41 N a footprint taken as
``QgsGeometry.area()`` is 1.757x the ground area it stands for - on a layer
whose linear unit is a perfectly ordinary metre, so a unit check finds nothing
wrong.

Neither ``geometry.area()`` nor ``geometry.length()`` is a measurement in
metres. A tool that reports m2, m3, tonnes or km/h therefore has to say which
metres it means, and this module is how it says so. Everything here is measured
on the CRS's own ellipsoid, which is what QGIS means by an ellipsoidal
measurement.

The runtime matrix cannot see either defect on its own: its fixture city sits at
the origin of EPSG:3857, the one place on the grid where the scale factor is
exactly 1 (and where even the sphere-against-ellipsoid difference is 0.67 per
cent). That is what the matrix's north fixture is for, and why it is at a real
latitude rather than at the origin - see TRAPS 5.2.
"""
from __future__ import annotations

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransformContext,
    QgsDistanceArea,
    QgsGeometry,
    QgsPointXY,
    QgsProcessingException,
    QgsRectangle,
)

#: Reference segment length, in layer units, used to read the local scale at a
#: point when no geometry is at hand to measure directly. The ratio it produces
#: is length-independent; 1 km just keeps the arithmetic well-conditioned.
_REFERENCE_UNITS = 1000.0


def _distance_area(crs, transform_context):
    """A ``QgsDistanceArea`` that measures ``crs``'s geometries on the ellipsoid."""
    if crs is None or not crs.isValid():
        raise QgsProcessingException(
            "The layer's CRS is not a valid coordinate reference system, so its "
            "areas and lengths cannot be converted to ground metres.")
    if crs.isGeographic():
        raise QgsProcessingException(
            f"The layer uses a geographic CRS ({crs.authid()}), whose coordinates "
            "are degrees. Project it to a projected CRS with a linear unit (the "
            "local UTM zone) first - areas and buffers in degrees mean nothing.")
    ellipsoid = crs.ellipsoidAcronym() or "WGS84"
    area = QgsDistanceArea()
    area.setSourceCrs(crs, transform_context or QgsCoordinateTransformContext())
    area.setEllipsoid(ellipsoid)
    if not area.ellipsoid() or area.ellipsoid() == "NONE":
        # A CRS that names no ellipsoid would silently fall back to planar
        # measurement - which is exactly the defect this module exists to
        # remove, so it fails here instead.
        raise QgsProcessingException(
            f"The layer's CRS ({crs.authid()}) does not declare an ellipsoid, so "
            "its ground areas and lengths cannot be computed. Reproject to a CRS "
            "with a known datum (e.g. the local UTM zone).")
    return area


class GroundUnits:
    """Lengths and areas of one layer, in ground metres.

    Build one per input layer whose metric quantities are reported, then take
    every length, area and metre-to-coordinate conversion from it. Mixing a
    measurement taken here with a raw ``geometry.area()`` in the same output is
    how the two conventions end up side by side in one table.
    """

    def __init__(self, crs: QgsCoordinateReferenceSystem, transform_context=None):
        self._crs = crs
        self._area = _distance_area(crs, transform_context)

    # ------------------------------------------------------------ measurements
    def area(self, geometry: QgsGeometry) -> float:
        """Planar area of ``geometry`` in square metres on the ellipsoid."""
        if geometry is None or geometry.isEmpty():
            return 0.0
        return float(self._area.measureArea(geometry))

    def length(self, geometry: QgsGeometry) -> float:
        """Length of ``geometry`` in metres on the ellipsoid."""
        if geometry is None or geometry.isEmpty():
            return 0.0
        return float(self._area.measureLength(geometry))

    # ------------------------------------------------- coordinates <-> metres
    def per_metre(self, geometry: QgsGeometry) -> float:
        """How many of the layer's coordinate units make one ground metre.

        Measured along ``geometry`` itself when it has a length, so a
        north-south street and an east-west one each get their own local scale
        rather than one that is right for neither. Geometry in this layer's own
        CRS; the factor is what a buffer radius or any other distance given in
        metres has to be multiplied by before it is handed to a coordinate
        operation.
        """
        planar = geometry.length() if geometry is not None else 0.0
        if planar > 0.0:
            ground = float(self._area.measureLength(geometry))
            if ground > 0.0:
                return planar / ground
        return self.scale(geometry.boundingBox() if geometry is not None else None)

    def scale(self, extent: QgsRectangle | None) -> float:
        """Layer units per ground metre at the centre of ``extent``.

        The one-scale-per-layer answer, for quantities that arrive as numbers
        already summed rather than as geometries - a graph's edge lengths, say.
        It is a single factor for the whole layer, so on a wide extent it takes
        the scale where the middle of the data is; that is worth about 0.4 per
        cent per 100 km at 41 N, well inside a screening tool's honesty budget
        and stated here so nobody has to rediscover it.
        """
        if extent is None or extent.isNull() or extent.isEmpty():
            raise QgsProcessingException(
                "The layer has no extent, so its coordinate units cannot be "
                "converted to ground metres.")
        centre = extent.center()
        half = max(extent.width(), 1.0) / 2.0
        reference = QgsGeometry.fromPolylineXY([
            QgsPointXY(centre.x() - half, centre.y()),
            QgsPointXY(centre.x() + half, centre.y()),
        ])
        planar = reference.length()
        ground = float(self._area.measureLength(reference))
        if planar <= 0.0 or ground <= 0.0:
            raise QgsProcessingException(
                f"The local scale of the layer's CRS ({self._crs.authid()}) could "
                "not be measured, so its coordinate units cannot be converted to "
                "ground metres. Reproject the layer to a projected CRS with a "
                "known unit.")
        return planar / ground
