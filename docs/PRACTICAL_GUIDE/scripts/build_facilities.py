#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a standalone facilities layer (public and service anchors)."""
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


# amenity values that count as a planning facility
FACILITY_AMENITY = {
    "school", "university", "college", "kindergarten", "library", "hospital",
    "clinic", "doctors", "marketplace", "community_centre", "townhall",
    "place_of_worship", "police", "fire_station", "post_office",
    "veterinary", "sports_centre", "bus_station", "theatre", "cinema",
    "drinking_water", "fuel", "charging_station", "parcel_locker",
}
HEALTHCARE = {"hospital", "clinic", "doctors", "pharmacy", "veterinary"}


def main():
    src = OUT / "pois.gpkg"
    ds = ogr.Open(sh(src))
    lyr = ds.GetLayerByName("pois")
    defn = lyr.GetLayerDefn()
    nf = {defn.GetFieldDefn(i).GetName(): i for i in range(defn.GetFieldCount())}

    dest = OUT / "facilities.gpkg"
    if dest.exists():
        dest.unlink()
    drv = ogr.GetDriverByName("GPKG")
    out = drv.CreateDataSource(sh(dest))
    o_lyr = out.CreateLayer("facilities", srs=lyr.GetSpatialRef(), geom_type=ogr.wkbPoint)
    for f in ("name", "type", "subtype", "tags"):
        o_lyr.CreateField(ogr.FieldDefn(f, ogr.OFTString))
    o_lyr.CreateField(ogr.FieldDefn("class", ogr.OFTString))
    o_defn = o_lyr.GetLayerDefn()

    n = 0
    kinds = {}
    for feat in lyr:
        sub = str(feat.GetField(nf["subtype"]) or "")
        typ = str(feat.GetField(nf["type"]) or "")
        keep = False
        cls = ""
        if typ == "amenity" and sub in FACILITY_AMENITY:
            keep, cls = True, sub
        elif typ == "healthcare" and sub in HEALTHCARE:
            keep, cls = True, sub
        elif typ == "public_transport" and sub in ("station", "stop_position",
                                                   "platform"):
            keep, cls = True, sub
        elif typ == "railway" and sub == "station":
            keep, cls = True, "station"
        elif typ == "shop" and sub in ("supermarket", "mall", "department_store",
                                       "convenience", "bakery"):
            keep, cls = True, "shop:" + sub
        elif typ == "leisure" and sub in ("sports_centre", "fitness_centre",
                                         "swimming_pool", "pitch"):
            keep, cls = True, "leisure:" + sub
        if not keep:
            continue
        nf2 = ogr.Feature(o_defn)
        for f in ("name", "type", "subtype", "tags"):
            nf2.SetField(f, str(feat.GetField(nf[f]) or ""))
        nf2.SetField("class", cls)
        nf2.SetGeometry(feat.GetGeometryRef())
        o_lyr.CreateFeature(nf2)
        kinds[cls] = kinds.get(cls, 0) + 1
        n += 1
    out = None
    ds = None
    print(f"  [ok] facilities.gpkg: {n} features")
    for k, v in sorted(kinds.items(), key=lambda x: -x[1])[:16]:
        print(f"      {k:28s} {v}")


if __name__ == "__main__":
    main()
