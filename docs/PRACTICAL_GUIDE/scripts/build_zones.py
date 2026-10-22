#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Join the trip-generation productions/attractions onto the CBS neighbourhood
polygons, so the gravity model has a zonal table that still carries geometry."""
import os
from pathlib import Path

from osgeo import gdal, ogr

gdal.UseExceptions()
ogr.UseExceptions()

ROOT = Path("/mnt/c/Users/YE/Downloads/planx_nl_data") if os.name != "nt" \
    else Path(r"C:\Users\YE\Downloads\planx_nl_data")
OUT = ROOT / "out"
WORK = Path(r"C:\Users\YE\PyCharmMiscProject\qgis_plugins\planx\docs\PRACTICAL_GUIDE"
            r"\work_utrecht") if os.name == "nt" else Path(
    "/mnt/c/Users/YE/PyCharmMiscProject/qgis_plugins/planx/docs/PRACTICAL_GUIDE"
    "/work_utrecht")


def sh(p):
    return str(p).replace("/", "\\") if os.name == "nt" else str(p)


def main():
    nb = OUT / "neighbourhoods.gpkg"
    tg = WORK / "tripgeneration__OUTPUT.gpkg"
    if not nb.exists():
        print("  [FAIL] neighbourhoods missing")
        return
    prod = {}
    if tg.exists():
        ds = ogr.Open(sh(tg))
        lyr = ds.GetLayer(0)
        d = lyr.GetLayerDefn()
        n = {d.GetFieldDefn(i).GetName(): i for i in range(d.GetFieldCount())}
        for f in lyr:
            code = str(f.GetField(n["cbs_code"]) or "").strip() \
                if "cbs_code" in n else ""
            try:
                prod[code] = (f.GetField(n["production"]) or 0,
                              f.GetField(n["attraction"]) or 0)
            except (TypeError, ValueError, KeyError):
                pass
        ds = None
    print(f"  trip-generation values for {len(prod)} zones")

    ds = ogr.Open(sh(nb))
    lyr = ds.GetLayer(0)
    defn = lyr.GetLayerDefn()
    nf = {defn.GetFieldDefn(i).GetName(): i for i in range(defn.GetFieldCount())}
    dest = OUT / "zones.gpkg"
    if dest.exists():
        dest.unlink()
    drv = ogr.GetDriverByName("GPKG")
    out = drv.CreateDataSource(sh(dest))
    o_lyr = out.CreateLayer("zones", srs=lyr.GetSpatialRef(),
                            geom_type=ogr.wkbMultiPolygon)
    for i in range(defn.GetFieldCount()):
        fd = defn.GetFieldDefn(i)
        o_lyr.CreateField(ogr.FieldDefn(fd.GetName(), fd.GetType()))
    o_lyr.CreateField(ogr.FieldDefn("production", ogr.OFTReal))
    o_lyr.CreateField(ogr.FieldDefn("attraction", ogr.OFTReal))
    o_defn = o_lyr.GetLayerDefn()
    n = 0
    for feat in lyr:
        nf2 = ogr.Feature(o_defn)
        for i in range(defn.GetFieldCount()):
            nf2.SetField(i, feat.GetField(i))
        code = str(feat.GetField(nf["cbs_code"]) or "").strip() \
            if "cbs_code" in nf else ""
        p, a = prod.get(code, (0.0, 0.0))
        nf2.SetField("production", float(p or 0))
        nf2.SetField("attraction", float(a or 0))
        nf2.SetGeometry(feat.GetGeometryRef())
        o_lyr.CreateFeature(nf2)
        n += 1
    out = None
    ds = None
    tot = sum(v[0] for v in prod.values())
    print(f"  [ok] zones.gpkg: {n} zones, total production {tot:.0f}")


if __name__ == "__main__":
    main()
