#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Write nan-safe 5 m versions of the DEM and DSM for the solar tools."""
import os
from pathlib import Path

import numpy as np
from osgeo import gdal, osr

gdal.UseExceptions()

ROOT = Path("/mnt/c/Users/YE/Downloads/planx_nl_data") if os.name != "nt" \
    else Path(r"C:\Users\YE\Downloads\planx_nl_data")
OUT = ROOT / "out"
BBOX = (135206.6, 454196.8, 138361.3, 457368.2)
NODATA = -9999.0
FACTOR = 2          # 2 m -> 4 m (integer block average)


def sh(p):
    return str(p).replace("/", "\\") if os.name == "nt" else str(p)


def downsample(arr, factor):
    """Block-average, ignoring nodata cells."""
    a = arr.astype("float32")
    a = np.where(a <= NODATA + 1, np.nan, a)
    h, w = a.shape
    h2, w2 = h // factor, w // factor
    a = a[:h2 * factor, :w2 * factor]
    a = a.reshape(h2, factor, w2, factor)
    with np.errstate(invalid="ignore"):
        out = np.nanmean(a, axis=(1, 3))
    out = np.where(np.isnan(out), NODATA, out)
    return out.astype("float32")


def main():
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(28992)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    for name in ("dem", "dsm"):
        src = OUT / f"{name}.tif"
        ds = gdal.Open(sh(src))
        arr = ds.GetRasterBand(1).ReadAsArray()
        gt = ds.GetGeoTransform()
        ds = None
        out = downsample(arr, FACTOR)
        cell = abs(gt[1]) * FACTOR
        gt_new = (gt[0], cell, 0.0, gt[3], 0.0, -cell)
        dest = OUT / f"{name}5.tif"
        drv = gdal.GetDriverByName("GTiff")
        d = drv.Create(sh(dest), out.shape[1], out.shape[0], 1, gdal.GDT_Float32,
                       options=["COMPRESS=DEFLATE", "TILED=YES"])
        d.SetGeoTransform(gt_new)
        d.SetProjection(srs.ExportToWkt())
        b = d.GetRasterBand(1)
        b.SetNoDataValue(NODATA)
        b.WriteArray(out)
        d.FlushCache()
        d = None
        v = out[out > NODATA + 1]
        print(f"  [ok] {name}5.tif {out.shape[1]}x{out.shape[0]} @ {cell:.0f} m | "
              f"{100*v.size/out.size:.1f}% valid | {v.min():.1f}..{v.max():.1f} m")


if __name__ == "__main__":
    main()
