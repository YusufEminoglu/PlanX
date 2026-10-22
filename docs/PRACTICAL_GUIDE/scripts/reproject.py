#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reproject every OSM-derived layer to EPSG:28992 (RD New) so the whole
Utrecht study set shares one projected CRS, and rebuild the thematic layers.
"""
import os
import subprocess
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
            print("    !", tail[-1][:150])
    return r.returncode == 0


def reproject(src_name, dst_name=None, nlt="MULTIPOLYGON"):
    src = OUT / src_name
    if not src.exists():
        print(f"  [skip] {src_name} missing")
        return
    dst = OUT / (dst_name or src_name)
    tmp = OUT / (dst.stem + "_rd.gpkg")
    if tmp.exists():
        tmp.unlink()
    cmd = ["ogr2ogr", "-f", "GPKG", sh(tmp), sh(src), "-t_srs", RD,
           "-skipfailures", "-makevalid"]
    if nlt:
        cmd += ["-nlt", nlt]
    ok = run(cmd)
    if not tmp.exists():
        print(f"  [FAIL] reproject {src_name}")
        return
    ds = ogr.Open(sh(tmp))
    lyr = ds.GetLayer(0)
    n = lyr.GetFeatureCount()
    gt = lyr.GetGeomType()
    ds = None
    src.unlink()
    tmp.rename(dst)
    print(f"  [ok] {dst.name}: {n} features (geom {ogr.GeometryTypeToName(gt)})")


if __name__ == "__main__":
    print("=== reproject OSM layers to EPSG:28992 ===")
    reproject("osm_lines.gpkg", nlt="MULTILINESTRING")
    reproject("osm_points.gpkg", nlt="POINT")
    reproject("osm_polys.gpkg", nlt="MULTIPOLYGON")
    reproject("buildings_osm.gpkg", nlt="MULTIPOLYGON")
    reproject("pois.gpkg", nlt=None)
    # the pois layer holds three sub-layers; reproject each
