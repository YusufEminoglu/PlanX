#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Download AHN (Dutch national height model) 0.5 m DSM + DTM for the study area
as GeoTIFF, by tiling the area into sub-extents that stay under the WCS
MAXSIZE=4000 pixel limit, then mosaicking the tiles with GDAL.
"""
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from osgeo import gdal

gdal.UseExceptions()

ROOT = Path("/mnt/c/Users/YE/Downloads/planx_nl_data") if os.name != "nt" \
    else Path(r"C:\Users\YE\Downloads\planx_nl_data")
RAW = ROOT / "raw" / "ahn_tiles"
OUT = ROOT / "out"
RAW.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)

BASE = "https://service.pdok.nl/rws/actueel-hoogtebestand-nederland/wcs/v1_0"
UA = {"User-Agent": "Mozilla/5.0 (PlanX data pipeline)"}

BBOX = (135206.6, 454196.8, 138361.3, 457368.2)   # RD, from the pipeline
TILE = 1600.0        # metres per tile -> 3200 px at 0.5 m (< MAXSIZE 4000)


def sh(p):
    return str(p).replace("/", "\\") if os.name == "nt" else str(p)


def fetch_tile(coverage, x0, y0, x1, y1, dest):
    if dest.exists() and dest.stat().st_size > 1000:
        return True
    params = {
        "service": "WCS", "version": "2.0.1", "request": "GetCoverage",
        "coverageid": coverage, "format": "image/tiff",
        "SUBSET": f"x({x0},{x1})",
        "SUBSET": f"y({y0},{y1})",
    }
    # build manually so both SUBSET keys survive
    url = (f"{BASE}?service=WCS&version=2.0.1&request=GetCoverage"
           f"&coverageid={coverage}&format=image/tiff"
           f"&SUBSET=x({x0},{x1})&SUBSET=y({y0},{y1})")
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=1800) as r, open(dest, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
    except Exception as e:
        print(f"    [FAIL] {coverage} {x0:.0f},{y0:.0f}: {str(e)[:110]}")
        if dest.exists():
            dest.unlink()
        return False
    try:
        ds = gdal.Open(sh(dest))
        if ds is None or ds.RasterXSize < 100:
            raise RuntimeError("bad tile")
        ds = None
        print(f"    [ok] {dest.name} ({dest.stat().st_size/1e6:.1f} MB)")
        return True
    except Exception as e:
        print(f"    [FAIL] {dest.name}: {e}")
        if dest.exists():
            dest.unlink()
        return False


def build_coverage(coverage, out_name):
    print(f"  AHN {coverage}:")
    x0, y0, x1, y1 = BBOX
    nx = int((x1 - x0) // TILE) + 1
    ny = int((y1 - y0) // TILE) + 1
    tiles = []
    for i in range(nx):
        for j in range(ny):
            tx0 = x0 + i * TILE
            ty0 = y0 + j * TILE
            tx1 = min(tx0 + TILE, x1)
            ty1 = min(ty0 + TILE, y1)
            d = RAW / f"{coverage}_{i}_{j}.tif"
            if fetch_tile(coverage, tx0, ty0, tx1, ty1, d):
                tiles.append(d)
    if not tiles:
        return False
    dest = OUT / out_name
    if dest.exists():
        dest.unlink()
    vrt = OUT / (out_name.replace(".tif", ".vrt"))
    cmd = ["gdalbuildvrt", "-resolution", "highest", "-overwrite"] + \
          [sh(t) for t in tiles] + [sh(vrt)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode:
        print("    [WARN] buildvrt:", (r.stderr or r.stdout)[:200])
    cmd = ["gdal_translate", "-of", "GTiff", "-co", "COMPRESS=DEFLATE",
           "-co", "TILED=YES", "-a_srs", "EPSG:28992", sh(vrt), sh(dest)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
    if r.returncode:
        print("    [WARN] translate:", (r.stderr or r.stdout)[:200])
    if dest.exists():
        ds = gdal.Open(sh(dest))
        b = ds.GetRasterBand(1)
        st = b.ComputeStatistics(False)
        print(f"    [ok] {out_name}: {ds.RasterXSize}x{ds.RasterYSize} "
              f"px={abs(ds.GetGeoTransform()[1]):.2f} m  "
              f"elev {st[0]:.1f}..{st[2]:.1f} m")
        ds = None
        return True
    return False


if __name__ == "__main__":
    ok1 = build_coverage("dsm_05m", "ahn_dsm.tif")
    ok2 = build_coverage("dtm_05m", "ahn_dtm.tif")
    print("DSM:", ok1, " DTM:", ok2)
