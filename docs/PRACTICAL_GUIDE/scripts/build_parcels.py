#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build a parcels layer for the land-allocation tools from real CBS data:
each CBS neighbourhood (buurt) becomes a parcel, and its suitability for
each land use is the real share of that CBS land-cover class (Bestand
Bodemgebruik 2010) inside the neighbourhood.
"""
import os
import subprocess
from pathlib import Path

import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()

ROOT = Path("/mnt/c/Users/YE/Downloads/planx_nl_data") if os.name != "nt" \
    else Path(r"C:\Users\YE\Downloads\planx_nl_data")
OUT = ROOT / "out"
RD = "EPSG:28992"
BBOX = (135206.6, 454196.8, 138361.3, 457368.2)
CELL = 10.0

# CBS Bestand Bodemgebruik 2010 classes -> land use
CLASS_FIELDS = {
    1: ("s_built", "Bebouwd (built-up)"),
    2: ("s_industrial", "Bedrijfsterrein (industrial)"),
    3: ("s_semi", "Semi-bebouwd (semi-built)"),
    4: ("s_recreation", "Recreatie (recreation)"),
    5: ("s_water", "Water"),
    6: ("s_road", "Hoofdweg (main road)"),
    7: ("s_industrial_estate", "Spoorterrein (industrial estate)"),
}
FIELD_ORDER = ["s_built", "s_industrial", "s_semi", "s_recreation", "s_water",
               "s_road", "s_industrial_estate"]


def sh(p):
    return str(p).replace("/", "\\") if os.name == "nt" else str(p)


def main():
    print("=== parcels with real CBS land-cover suitability ===")
    lc = OUT / "landcover_2010.tif"
    nb = OUT / "cbs_buurten.gpkg"
    if not lc.exists() or not nb.exists():
        print("  [FAIL] missing input")
        return
    ds = gdal.Open(sh(lc))
    arr = ds.GetRasterBand(1).ReadAsArray()
    gt = ds.GetGeoTransform()
    ds = None
    W = arr.shape[1]
    H = arr.shape[0]

    src = ogr.Open(sh(nb))
    lyr = src.GetLayer(0)
    defn = lyr.GetLayerDefn()
    nf = {defn.GetFieldDefn(i).GetName(): i for i in range(defn.GetFieldCount())}

    dest = OUT / "parcels.gpkg"
    if dest.exists():
        dest.unlink()
    drv = ogr.GetDriverByName("GPKG")
    out = drv.CreateDataSource(sh(dest))
    o_lyr = out.CreateLayer("parcels", srs=lyr.GetSpatialRef(),
                            geom_type=ogr.wkbMultiPolygon)
    for i in range(defn.GetFieldCount()):
        fd = defn.GetFieldDefn(i)
        o_lyr.CreateField(ogr.FieldDefn(fd.GetName(), fd.GetType()))
    for f in FIELD_ORDER:
        o_lyr.CreateField(ogr.FieldDefn(f, ogr.OFTReal))
    o_lyr.CreateField(ogr.FieldDefn("zone_id", ogr.OFTString))
    o_defn = o_lyr.GetLayerDefn()

    n = 0
    for feat in lyr:
        g = feat.GetGeometryRef()
        if not g:
            continue
        env = g.GetEnvelope()
        # raster rows run north -> south (gt[5] < 0), so the top edge of the
        # feature (env[3]) is the first row and the bottom edge (env[2]) the last
        x0 = max(int((env[0] - gt[0]) / gt[1]), 0)
        x1 = min(int((env[1] - gt[0]) / gt[1]) + 1, W)
        y0 = max(int((env[3] - gt[3]) / gt[5]), 0)
        y1 = min(int((env[2] - gt[3]) / gt[5]) + 1, H)
        if y1 <= y0:
            y0, y1 = 0, H
        if x1 <= x0 or y1 <= y0:
            continue
        win = arr[y0:y1, x0:x1]
        total = win.size
        shares = {}
        for cls, (fname, _lab) in CLASS_FIELDS.items():
            shares[fname] = round(float((win == cls).sum()) / total, 4) if total else 0.0

        nf2 = ogr.Feature(o_defn)
        for i in range(defn.GetFieldCount()):
            nf2.SetField(i, feat.GetField(i))
        for f in FIELD_ORDER:
            nf2.SetField(f, shares[f])
        code = str(feat.GetField(nf["buurtcode"]) or "").strip() if "buurtcode" in nf else ""
        nf2.SetField("zone_id", code)
        nf2.SetGeometry(g)
        o_lyr.CreateFeature(nf2)
        n += 1
    out = None
    src = None
    print(f"  [ok] parcels.gpkg: {n} CBS neighbourhoods with 7 real "
          f"land-cover suitability fields")
    print(f"  fields: {', '.join(FIELD_ORDER)}")


if __name__ == "__main__":
    main()
