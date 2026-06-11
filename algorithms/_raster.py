# -*- coding: utf-8 -*-
"""Shared raster I/O helpers for the microclimate algorithms (GDAL)."""
from __future__ import annotations

import numpy as np

from osgeo import gdal
from qgis.core import QgsProcessingException

gdal.UseExceptions()


def read_dsm(layer):
    """Read band 1 of a raster layer as float64 with NaN nodata.

    Returns (array, geotransform, projection_wkt, pixel_size).
    """
    if layer is None:
        raise QgsProcessingException("No DSM layer.")
    if layer.crs().isValid() and layer.crs().isGeographic():
        raise QgsProcessingException(
            "The DSM uses a geographic CRS. Reproject it to a projected CRS "
            "(metric pixels) first - shadow/SVF math needs metres.")
    ds = gdal.Open(layer.source(), gdal.GA_ReadOnly)
    if ds is None:
        raise QgsProcessingException(f"GDAL could not open '{layer.source()}'.")
    band = ds.GetRasterBand(1)
    arr = band.ReadAsArray().astype(np.float64)
    nodata = band.GetNoDataValue()
    if nodata is not None:
        arr[arr == nodata] = np.nan
    gt = ds.GetGeoTransform()
    proj = ds.GetProjection()
    pixel = (abs(gt[1]) + abs(gt[5])) / 2.0
    ds = None
    return arr, gt, proj, pixel


def write_raster(path, arr, gt, proj, nodata, dtype=gdal.GDT_Float32):
    drv = gdal.GetDriverByName("GTiff")
    out = drv.Create(path, arr.shape[1], arr.shape[0], 1, dtype,
                     options=["COMPRESS=LZW"])
    out.SetGeoTransform(gt)
    if proj:
        out.SetProjection(proj)
    band = out.GetRasterBand(1)
    band.SetNoDataValue(nodata)
    band.WriteArray(arr)
    band.FlushCache()
    out = None
    return path


def raster_center_lonlat(layer):
    """Raster extent center as WGS84 (lon, lat)."""
    from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject
    center = layer.extent().center()
    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
    xform = QgsCoordinateTransform(layer.crs(), wgs84, QgsProject.instance())
    pt = xform.transform(center)
    return pt.x(), pt.y()
