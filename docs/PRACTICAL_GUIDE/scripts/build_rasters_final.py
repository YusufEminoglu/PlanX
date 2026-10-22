#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build the final DEM and DSM for Utrecht from the AHN national height model.

  DTM  = AHN bare-earth model, gaps filled with SRTM
  DSM  = AHN surface model (buildings included), gaps filled with the DTM

Both are written at 2 m in EPSG:28992 over the study area.
"""
import os
import subprocess
from pathlib import Path

import numpy as np
from osgeo import gdal, osr

gdal.UseExceptions()

ROOT = Path("/mnt/c/Users/YE/Downloads/planx_nl_data") if os.name != "nt" \
    else Path(r"C:\Users\YE\Downloads\planx_nl_data")
OUT = ROOT / "out"
RD = "EPSG:28992"
BBOX = (135206.6, 454196.8, 138361.3, 457368.2)
CELL = 2.0
AHN_NODATA = 3.4028234663852886e+38
NODATA = -9999.0


def sh(p):
    return str(p).replace("/", "\\") if os.name == "nt" else str(p)


def run(cmd, timeout=3600):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode and r.stderr:
        tail = [x for x in r.stderr.strip().splitlines() if x.strip()]
        if tail:
            print("    !", tail[-1][:150])
    return r.returncode == 0


def read(p):
    ds = gdal.Open(sh(p))
    b = ds.GetRasterBand(1)
    a = b.ReadAsArray().astype("float32")
    gt = ds.GetGeoTransform()
    srs = ds.GetSpatialRef()
    ds = None
    return a, gt, srs


def write(p, a, gt, srs):
    h, w = a.shape
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(sh(p), w, h, 1, gdal.GDT_Float32,
                    options=["COMPRESS=DEFLATE", "TILED=YES"])
    ds.SetGeoTransform(gt)
    ds.SetProjection(srs.ExportToWkt())
    b = ds.GetRasterBand(1)
    b.SetNoDataValue(NODATA)
    b.WriteArray(a)
    ds.FlushCache()
    ds = None


def crop_to_grid(a, gt, srs, cell=CELL):
    """Resample an arbitrary grid onto the study-area grid."""
    h, w = a.shape
    xs = gt[0] + (np.arange(w) + 0.5) * gt[1]
    ys = gt[3] + (np.arange(h) + 0.5) * gt[5]
    W = int(round((BBOX[2] - BBOX[0]) / cell))
    H = int(round((BBOX[3] - BBOX[1]) / cell))
    gx = BBOX[0] + (np.arange(W) + 0.5) * cell
    gy = BBOX[3] - (np.arange(H) + 0.5) * cell
    # nearest-neighbour resample by index (both rasters are in RD, axis aligned)
    sx = np.clip(((gx - gt[0]) / gt[1]).astype(int), 0, w - 1)
    sy = np.clip(((gy - gt[3]) / gt[5]).astype(int), 0, h - 1)
    return a[np.ix_(sy, sx)]


if __name__ == "__main__":
    print("=== DEM / DSM from AHN (2 m) ===")
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(28992)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    # --- DTM
    dtm_raw, gt, _ = read(OUT / "ahn_dtm.tif")
    dtm = crop_to_grid(dtm_raw, gt, srs)
    dtm = np.where(dtm >= 1e30, NODATA, dtm)
    dtm = np.where(dtm <= NODATA + 1, NODATA, dtm)
    print(f"  AHN DTM on grid: {100*(dtm>NODATA+1).mean():.1f}% valid")

    # --- DSM
    dsm_raw, gt, _ = read(OUT / "ahn_dsm.tif")
    dsm = crop_to_grid(dsm_raw, gt, srs)
    dsm = np.where(dsm >= 1e30, NODATA, dsm)
    dsm = np.where(dsm <= NODATA + 1, NODATA, dsm)
    print(f"  AHN DSM on grid: {100*(dsm>NODATA+1).mean():.1f}% valid")

    # --- SRTM for the DTM gaps
    srtm = OUT / "srtm_dem.tif"
    if srtm.exists():
        up = OUT / "_srtm_grid.tif"
        run(["gdalwarp", "-t_srs", RD, "-te", str(BBOX[0]), str(BBOX[1]),
             str(BBOX[2]), str(BBOX[3]), "-tr", str(CELL), str(CELL), "-r", "cubic",
             "-of", "GTiff", "-co", "COMPRESS=DEFLATE", sh(srtm), sh(up)])
        if up.exists():
            s2, g2, _ = read(up)
            if s2.shape == dtm.shape:
                dtm = np.where(dtm <= NODATA + 1, s2, dtm)
                print(f"  DTM after SRTM fill: {100*(dtm>NODATA+1).mean():.1f}% valid")
            up.unlink()

    # --- DSM gaps = bare ground
    dsm = np.where(dsm <= NODATA + 1, dtm, dsm)

    gt_new = (BBOX[0], CELL, 0.0, BBOX[3], 0.0, -CELL)
    write(OUT / "dem.tif", dtm.astype("float32"), gt_new, srs)
    write(OUT / "dsm.tif", dsm.astype("float32"), gt_new, srs)
    for name, arr in (("dem", dtm), ("dsm", dsm)):
        v = arr[arr > NODATA + 1]
        print(f"  [ok] {name}.tif {arr.shape[1]}x{arr.shape[0]} @ {CELL:.0f} m | "
              f"{100*v.size/arr.size:.1f}% valid | {v.min():.1f}..{v.max():.1f} m")
