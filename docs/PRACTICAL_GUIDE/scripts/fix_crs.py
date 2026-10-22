#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bring the whole Utrecht study set onto one projected CRS (EPSG:28992) and
rebuild the derived layers. The WFS GeoJSON responses are always WGS84, so
every PDOK layer has to be reprojected before PlanX can use it.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from osgeo import gdal, ogr

gdal.UseExceptions()
ogr.UseExceptions()

ROOT = Path("/mnt/c/Users/YE/Downloads/planx_nl_data") if os.name != "nt" \
    else Path(r"C:\Users\YE\Downloads\planx_nl_data")
OUT = ROOT / "out"
RD = "EPSG:28992"


def sh(p):
    return str(p).replace("/", "\\") if os.name == "nt" else str(p)


def run(cmd, timeout=3600):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode and r.stderr:
        tail = [x for x in r.stderr.strip().splitlines() if x.strip()]
        if tail:
            print("    !", tail[-1][:140])
    return r.returncode == 0


def crs_of(path):
    try:
        ds = ogr.Open(sh(path))
        lyr = ds.GetLayer(0)
        s = lyr.GetSpatialRef()
        code = s.GetAuthorityCode(None) if s else None
        ds = None
        return code
    except Exception:
        return None


def reproject(path, nlt=None):
    p = OUT / path
    if not p.exists():
        return
    code = crs_of(p)
    if code == "28992":
        print(f"  [skip] {path} already RD")
        return
    tmp = OUT / (p.stem + "_rd.gpkg")
    if tmp.exists():
        tmp.unlink()
    cmd = ["ogr2ogr", "-f", "GPKG", sh(tmp), sh(p), "-t_srs", RD,
           "-skipfailures", "-makevalid"]
    if nlt:
        cmd += ["-nlt", nlt]
    run(cmd)
    if tmp.exists():
        p.unlink()
        tmp.rename(p)
        print(f"  [ok] {path} -> EPSG:28992")


if __name__ == "__main__":
    print("=== reproject the PDOK (WFS) layers to EPSG:28992 ===")
    reproject("bag_pand.gpkg", "MULTIPOLYGON")
    reproject("bag_adres.gpkg", "POINT")
    reproject("cbs_buurten.gpkg", "MULTIPOLYGON")
    reproject("cbs_wijken.gpkg", "MULTIPOLYGON")
    reproject("postcode_pop.gpkg", "MULTIPOLYGON")
    reproject("bodemgebruik_2010.gpkg", "MULTIPOLYGON")
    reproject("bodemgebruik_2017.gpkg", "MULTIPOLYGON")
    reproject("_bag_raw.gpkg", "POINT")
    reproject("buildings.gpkg", "MULTIPOLYGON")
    reproject("demand.gpkg", "POINT")
    reproject("neighbourhoods.gpkg", "MULTIPOLYGON")

    print("\n=== rebuild the derived layers on the RD grid ===")
    src = open(OUT.parent / "final_build.py", encoding="utf-8").read()
    src = src.replace('if __name__ == "__main__":\n    thematic()\n    heights_from_ahn()\n    demand_points()', '')
    exec(src)
    heights_from_ahn()
    demand_points()

    print("\n=== downsample the rasters to 2 m (PlanX raster work is heavy) ===")
    for name in ("dem", "dsm"):
        src_tif = OUT / f"{name}.tif"
        if not src_tif.exists():
            continue
        tmp = OUT / f"{name}_2m.tif"
        run(["gdalwarp", "-t_srs", RD, "-tr", "2", "2", "-r", "bilinear",
             "-of", "GTiff", "-co", "COMPRESS=DEFLATE", "-co", "TILED=YES",
             sh(src_tif), sh(tmp)])
        if tmp.exists():
            src_tif.unlink()
            tmp.rename(src_tif)
            ds = gdal.Open(sh(src_tif))
            b = ds.GetRasterBand(1)
            st = b.ComputeStatistics(False)
            print(f"  [ok] {name}.tif {ds.RasterXSize}x{ds.RasterYSize} "
                  f"elev {st[0]:.1f}..{st[2]:.1f} m")
            ds = None

    print("\n=== final CRS check ===")
    import glob
    for f in sorted(glob.glob(str(OUT / "*.gpkg"))):
        name = os.path.basename(f)
        if name.startswith(("_", "osm_")):
            continue
        code = crs_of(f)
        flag = "OK " if code == "28992" else "!! "
        print(f"  {flag}{name:26s} EPSG:{code}")
