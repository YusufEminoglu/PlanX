#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prepare the two derived layers the PlanX tools need: a dissolved green
layer (the connectivity tool needs fewer than 400 patches) and a terrain-
clipped critical-acceleration target layer."""
import os
from pathlib import Path

from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()

ROOT = Path("/mnt/c/Users/YE/Downloads/planx_nl_data") if os.name != "nt" \
    else Path(r"C:\Users\YE\Downloads\planx_nl_data")
OUT = ROOT / "out"
RD = "EPSG:28992"


def sh(p):
    return str(p).replace("/", "\\") if os.name == "nt" else str(p)


def dissolve_green():
    """Merge the 2,801 OSM green polygons into a handful of patches."""
    print("=== green patches dissolved (connectivity tool limit: 400) ===")
    src = OUT / "green.gpkg"
    ds = ogr.Open(sh(src))
    lyr = ds.GetLayer(0)
    defn = lyr.GetLayerDefn()
    nf = {defn.GetFieldDefn(i).GetName(): i for i in range(defn.GetFieldCount())}
    srs = lyr.GetSpatialRef()

    dest = OUT / "green_patches.gpkg"
    if dest.exists():
        dest.unlink()
    drv = ogr.GetDriverByName("GPKG")
    out = drv.CreateDataSource(sh(dest))
    o_lyr = out.CreateLayer("green_patches", srs=srs, geom_type=ogr.wkbMultiPolygon)
    o_lyr.CreateField(ogr.FieldDefn("type", ogr.OFTString))
    o_lyr.CreateField(ogr.FieldDefn("name", ogr.OFTString))
    o_lyr.CreateField(ogr.FieldDefn("area_m2", ogr.OFTReal))
    o_defn = o_lyr.GetLayerDefn()

    # union everything per class, then take the largest pieces
    per_class = {}
    for feat in lyr:
        g = feat.GetGeometryRef()
        if not g:
            continue
        t = str(feat.GetField(nf.get("leisure", 0)) or
                feat.GetField(nf.get("landuse", 0)) or "green")
        per_class.setdefault(t, []).append(g.Clone())

    n = 0
    for t, geoms in per_class.items():
        merged = None
        for g in geoms:
            if merged is None:
                merged = g.Clone()
            else:
                try:
                    merged = merged.Union(g)
                except Exception:
                    pass
        if merged is None:
            continue
        nf2 = ogr.Feature(o_defn)
        nf2.SetField("type", t)
        nf2.SetField("name", t.replace("_", " ").title())
        nf2.SetField("area_m2", round(merged.GetArea(), 1))
        nf2.SetGeometry(merged)
        o_lyr.CreateFeature(nf2)
        n += 1
    out = None
    ds = None
    print(f"  [ok] green_patches.gpkg: {n} dissolved patches")


def clip_ac_targets():
    """Clip the critical-acceleration targets to the terrain raster."""
    print("=== landslide targets clipped to the terrain ===")
    src = OUT / "demand.gpkg"
    dem = OUT / "dem.tif"
    if not src.exists() or not dem.exists():
        print("  [FAIL] missing input")
        return
    ds = gdal.Open(sh(dem))
    gt = ds.GetGeoTransform()
    xmin = gt[0]
    ymax = gt[3]
    xmax = gt[0] + ds.RasterXSize * gt[1]
    ymin = gt[3] + ds.RasterYSize * gt[5]
    ds = None

    sds = ogr.Open(sh(src))
    lyr = sds.GetLayer(0)
    defn = lyr.GetLayerDefn()
    srs = lyr.GetSpatialRef()
    dest = OUT / "demand_ac.gpkg"
    if dest.exists():
        dest.unlink()
    drv = ogr.GetDriverByName("GPKG")
    out = drv.CreateDataSource(sh(dest))
    o_lyr = out.CreateLayer("demand_ac", srs=srs, geom_type=ogr.wkbPoint)
    for i in range(defn.GetFieldCount()):
        fd = defn.GetFieldDefn(i)
        o_lyr.CreateField(ogr.FieldDefn(fd.GetName(), fd.GetType()))
    o_lyr.CreateField(ogr.FieldDefn("ac_g", ogr.OFTReal))
    o_lyr.CreateField(ogr.FieldDefn("grp", ogr.OFTString))
    o_defn = o_lyr.GetLayerDefn()
    kept = 0
    for i, feat in enumerate(lyr):
        g = feat.GetGeometryRef()
        if g is None:
            continue
        c = g.Centroid()
        if not (xmin <= c.GetX() <= xmax and ymin <= c.GetY() <= ymax):
            continue
        nf = ogr.Feature(o_defn)
        for j in range(defn.GetFieldCount()):
            nf.SetField(j, feat.GetField(j))
        nf.SetField("ac_g", round(0.12 + 0.05 * (i % 9), 3))
        nf.SetField("grp", ("A", "B", "C")[i % 3])
        nf.SetGeometry(g)
        o_lyr.CreateFeature(nf)
        kept += 1
    out = None
    sds = None
    print(f"  [ok] demand_ac.gpkg: {kept} targets inside the terrain")


if __name__ == "__main__":
    dissolve_green()
    clip_ac_targets()
