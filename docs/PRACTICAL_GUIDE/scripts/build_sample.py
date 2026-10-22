#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Create a sampled demand layer for the pairwise network algorithms.

The full BAG address layer has 51,000 points; an OD matrix over
51,000 x 944 facilities is 48 million cells, which is neither useful nor
fast. This writes a systematic sample (every Nth address, population
preserved) that still covers the whole study area.
"""
import os
from pathlib import Path

from osgeo import gdal, ogr

gdal.UseExceptions()
ogr.UseExceptions()

ROOT = Path("/mnt/c/Users/YE/Downloads/planx_nl_data") if os.name != "nt" \
    else Path(r"C:\Users\YE\Downloads\planx_nl_data")
OUT = ROOT / "out"
STEP = 12          # 51,000 / 12 -> ~4,250 points


def sh(p):
    return str(p).replace("/", "\\") if os.name == "nt" else str(p)


def main():
    src = OUT / "demand.gpkg"
    ds = ogr.Open(sh(src))
    lyr = ds.GetLayer(0)
    defn = lyr.GetLayerDefn()
    nf = {defn.GetFieldDefn(i).GetName(): i for i in range(defn.GetFieldCount())}

    dest = OUT / "demand_sample.gpkg"
    if dest.exists():
        dest.unlink()
    drv = ogr.GetDriverByName("GPKG")
    out = drv.CreateDataSource(sh(dest))
    o_lyr = out.CreateLayer("demand_sample", srs=lyr.GetSpatialRef(),
                            geom_type=ogr.wkbPoint)
    for i in range(defn.GetFieldCount()):
        fd = defn.GetFieldDefn(i)
        o_lyr.CreateField(ogr.FieldDefn(fd.GetName(), fd.GetType()))
    o_defn = o_lyr.GetLayerDefn()

    n = 0
    total_pop = 0.0
    pop_field = "pop" if "pop" in nf else None
    for i, feat in enumerate(lyr):
        if i % STEP:
            continue
        nf2 = ogr.Feature(o_defn)
        for j in range(defn.GetFieldCount()):
            nf2.SetField(j, feat.GetField(j))
        if pop_field:
            try:
                total_pop += float(feat.GetField(nf[pop_field]) or 0)
            except (TypeError, ValueError):
                pass
        nf2.SetGeometry(feat.GetGeometryRef())
        o_lyr.CreateFeature(nf2)
        n += 1
    out = None
    ds = None
    print(f"  [ok] demand_sample.gpkg: {n} points (every {STEP}th address), "
          f"population {total_pop:.0f}")


if __name__ == "__main__":
    main()
