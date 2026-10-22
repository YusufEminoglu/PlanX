#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Two systematic demand samples for the pairwise network algorithms."""
import os
from pathlib import Path

from osgeo import gdal, ogr

gdal.UseExceptions()
ogr.UseExceptions()

ROOT = Path("/mnt/c/Users/YE/Downloads/planx_nl_data") if os.name != "nt" \
    else Path(r"C:\Users\YE\Downloads\planx_nl_data")
OUT = ROOT / "out"


def sh(p):
    return str(p).replace("/", "\\") if os.name == "nt" else str(p)


def sample(src_name, dest_name, step, label):
    ds = ogr.Open(sh(OUT / src_name))
    lyr = ds.GetLayer(0)
    defn = lyr.GetLayerDefn()
    dest = OUT / dest_name
    if dest.exists():
        dest.unlink()
    drv = ogr.GetDriverByName("GPKG")
    out = drv.CreateDataSource(sh(dest))
    o_lyr = out.CreateLayer(dest.stem, srs=lyr.GetSpatialRef(), geom_type=ogr.wkbPoint)
    for i in range(defn.GetFieldCount()):
        fd = defn.GetFieldDefn(i)
        o_lyr.CreateField(ogr.FieldDefn(fd.GetName(), fd.GetType()))
    o_defn = o_lyr.GetLayerDefn()
    n = 0
    for i, feat in enumerate(lyr):
        if i % step:
            continue
        nf = ogr.Feature(o_defn)
        for j in range(defn.GetFieldCount()):
            nf.SetField(j, feat.GetField(j))
        nf.SetGeometry(feat.GetGeometryRef())
        o_lyr.CreateFeature(nf)
        n += 1
    out = None
    ds = None
    print(f"  [ok] {dest_name}: {n} points ({label})")


if __name__ == "__main__":
    sample("demand.gpkg", "demand_od.gpkg", 85, "OD / criticality")
    sample("demand.gpkg", "demand_routes.gpkg", 255, "route pairs")
    sample("demand.gpkg", "demand_sample.gpkg", 12, "general network tools")
