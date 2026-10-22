#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build the POI / facility / water layers from the OSM extract.

The BBBike OSM extract keeps most tags in a serialised `other_tags` field,
so the thematic layers are filtered with LIKE and then re-parsed into clean
columns (type, name, subtype).
"""
import json
import os
import re
import subprocess
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


def run(cmd, timeout=2400):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode and r.stderr:
        tail = [x for x in r.stderr.strip().splitlines() if x.strip()]
        if tail:
            print("    !", tail[-1][:150])
    return r.returncode == 0


def parse_tags(raw):
    """Parse the OSM driver's other_tags string into a dict.

    The BBBike/OSM driver writes a Ruby-style hash:  "key"=>"value","k2"=>"v2"
    """
    if not raw:
        return {}
    txt = str(raw)
    out = {}
    for m in re.finditer(r'"([^"]+)"\s*(?:=>|=|:)\s*"([^"]*)"', txt):
        out[m.group(1)] = m.group(2)
    for m in re.finditer(r'"([^"]+)"\s*(?:=>|:)\s*([A-Za-z0-9_.+-]+)\s*[,}\]]', txt):
        out.setdefault(m.group(1), m.group(2))
    return out


# --------------------------------------------------------------- POI layer
POI_KEYS = ("amenity", "shop", "leisure", "tourism", "healthcare", "historic",
             "office", "craft", "sport", "public_transport", "railway",
             "aeroway", "emergency", "community_centre", "theatre")


def build_pois():
    print("=== POI / facility / water layers ===")
    src = OUT / "osm_points.gpkg"
    if not src.exists():
        print("  [FAIL] osm_points.gpkg missing")
        return
    ds = ogr.Open(sh(src))
    lyr = ds.GetLayer(0)
    defn = lyr.GetLayerDefn()
    names = {defn.GetFieldDefn(i).GetName(): i for i in range(defn.GetFieldCount())}
    has_other = "other_tags" in names

    dest = OUT / "pois.gpkg"
    if dest.exists():
        dest.unlink()
    drv = ogr.GetDriverByName("GPKG")
    out = drv.CreateDataSource(sh(dest))
    o_lyr = out.CreateLayer("pois", srs=lyr.GetSpatialRef(), geom_type=ogr.wkbPoint)
    o_lyr.CreateField(ogr.FieldDefn("name", ogr.OFTString))
    o_lyr.CreateField(ogr.FieldDefn("type", ogr.OFTString))
    o_lyr.CreateField(ogr.FieldDefn("subtype", ogr.OFTString))
    o_lyr.CreateField(ogr.FieldDefn("tags", ogr.OFTString))
    o_defn = o_lyr.GetLayerDefn()

    n_poi = 0
    n_fac = 0
    n_water = 0
    fac_lyr = out.CreateLayer("facilities", srs=lyr.GetSpatialRef(), geom_type=ogr.wkbPoint)
    fac_lyr.CreateField(ogr.FieldDefn("name", ogr.OFTString))
    fac_lyr.CreateField(ogr.FieldDefn("type", ogr.OFTString))
    fac_lyr.CreateField(ogr.FieldDefn("subtype", ogr.OFTString))
    fac_lyr.CreateField(ogr.FieldDefn("tags", ogr.OFTString))
    f_defn = fac_lyr.GetLayerDefn()

    water_lyr = out.CreateLayer("water", srs=lyr.GetSpatialRef(), geom_type=ogr.wkbPoint)
    water_lyr.CreateField(ogr.FieldDefn("name", ogr.OFTString))
    water_lyr.CreateField(ogr.FieldDefn("type", ogr.OFTString))
    w_defn = water_lyr.GetLayerDefn()

    FACILITY_AMENITY = {
        "school", "university", "college", "kindergarten", "library",
        "hospital", "clinic", "doctors", "marketplace", "community_centre",
        "townhall", "place_of_worship", "police", "fire_station", "post_office",
        "veterinary", "sports_centre", "bus_station", "theatre", "cinema",
    }

    for feat in lyr:
        tags = {}
        for col in ("amenity", "shop", "leisure", "tourism", "healthcare",
                    "historic", "office", "craft", "sport", "public_transport",
                    "railway", "aeroway", "emergency"):
            if col in names:
                v = feat.GetField(names[col])
                if v:
                    tags[col] = str(v)
        if has_other:
            tags.update(parse_tags(feat.GetField(names["other_tags"])))
        if not tags:
            continue
        name = str(feat.GetField(names["name"])) if "name" in names and \
            feat.GetField(names["name"]) else ""
        if not name and "addr:housename" in tags:
            name = tags["addr:housename"]

        # --- POI
        ptype = psub = None
        for k in POI_KEYS:
            if k in tags:
                ptype = k
                psub = tags[k]
                break
        if ptype:
            nf = ogr.Feature(o_defn)
            nf.SetField("name", name)
            nf.SetField("type", ptype)
            nf.SetField("subtype", psub)
            nf.SetField("tags", json.dumps(tags, ensure_ascii=False)[:900])
            nf.SetGeometry(feat.GetGeometryRef())
            o_lyr.CreateFeature(nf)
            n_poi += 1

        # --- facility
        amen = tags.get("amenity", "")
        if (amen in FACILITY_AMENITY or tags.get("healthcare") in
                ("hospital", "clinic", "doctors") or tags.get("railway") == "station"
                or tags.get("public_transport") == "station"):
            nf = ogr.Feature(f_defn)
            nf.SetField("name", name)
            nf.SetField("type", amen or tags.get("healthcare") or
                        tags.get("railway") or "station")
            nf.SetField("subtype", tags.get("amenity", "") or
                        tags.get("healthcare", "") or tags.get("railway", ""))
            nf.SetField("tags", json.dumps(tags, ensure_ascii=False)[:900])
            nf.SetGeometry(feat.GetGeometryRef())
            fac_lyr.CreateFeature(nf)
            n_fac += 1

        # --- water
        if (tags.get("natural") == "water" or tags.get("waterway") or
                tags.get("landuse") == "reservoir" or tags.get("amenity") == "drinking_water"):
            nf = ogr.Feature(w_defn)
            nf.SetField("name", name)
            nf.SetField("type", tags.get("natural") or tags.get("landuse") or
                        tags.get("waterway", ""))
            nf.SetGeometry(feat.GetGeometryRef())
            water_lyr.CreateFeature(nf)
            n_water += 1

    out = None
    ds = None
    print(f"  pois.gpkg        -> {n_poi} features")
    print(f"  facilities.gpkg  -> {n_fac} features")
    print(f"  water (points)   -> {n_water} features")


# ------------------------------------------------- OSM buildings with tags
def build_osm_buildings():
    print("=== OSM buildings (height / levels / build year) ===")
    src = OUT / "osm_polys.gpkg"
    if not src.exists():
        return
    ds = ogr.Open(sh(src))
    lyr = ds.GetLayer(0)
    defn = lyr.GetLayerDefn()
    names = {defn.GetFieldDefn(i).GetName(): i for i in range(defn.GetFieldCount())}

    dest = OUT / "buildings_osm.gpkg"
    if dest.exists():
        dest.unlink()
    drv = ogr.GetDriverByName("GPKG")
    out = drv.CreateDataSource(sh(dest))
    o_lyr = out.CreateLayer("buildings_osm", srs=lyr.GetSpatialRef(),
                            geom_type=ogr.wkbMultiPolygon)
    for f in ("name", "building", "height", "levels", "start_date",
              "building_levels", "min_height", "year_built"):
        o_lyr.CreateField(ogr.FieldDefn(f, ogr.OFTString))
    o_lyr.CreateField(ogr.FieldDefn("tags", ogr.OFTString))
    o_defn = o_lyr.GetLayerDefn()

    n = 0
    for feat in lyr:
        if "building" not in names or not feat.GetField(names["building"]):
            continue
        tags = {}
        if "other_tags" in names:
            tags = parse_tags(feat.GetField(names["other_tags"]))
        nf = ogr.Feature(o_defn)
        for f in ("name", "building", "height", "levels", "start_date",
                  "building_levels", "min_height", "year_built"):
            v = ""
            if f in names:
                v = str(feat.GetField(names[f]) or "")
            if not v and f in tags:
                v = str(tags[f])
            nf.SetField(f, v)
        # Dutch OSM uses building:levels / roof:levels rather than levels
        if not nf.GetField("levels"):
            lv = tags.get("building:levels", "")
            if not lv:
                rv = tags.get("roof:levels", "")
                lv = str(int(float(rv)) + 1) if rv else ""
            nf.SetField("levels", str(lv))
        if not nf.GetField("start_date"):
            nf.SetField("start_date", str(tags.get("start_date", "")))
        if not nf.GetField("height"):
            nf.SetField("height", str(tags.get("height", "")))
        nf.SetField("tags", json.dumps(tags, ensure_ascii=False)[:600])
        nf.SetGeometry(feat.GetGeometryRef())
        o_lyr.CreateFeature(nf)
        n += 1
    out = None
    ds = None
    print(f"  buildings_osm.gpkg -> {n} features")


# --------------------------------------------- BAG buildings + heights
def bag_buildings_with_heights():
    """Attach OSM height data to the official BAG footprints.

    A spatial index over the OSM building centroids makes this a fast
    point-in-polygon lookup, which is what the height join really is.
    """
    print("=== BAG buildings + OSM heights (spatial join) ===")
    bld = OUT / "bag_pand.gpkg"      # untouched source (idempotent rebuild)
    osm = OUT / "buildings_osm.gpkg"
    if not bld.exists() or not osm.exists():
        print("  [SKIP] missing input")
        return

    # ---- index the OSM buildings by centroid (uniform grid hash)
    ds_o = ogr.Open(sh(osm))
    lyr_o = ds_o.GetLayer(0)
    d_o = lyr_o.GetLayerDefn()
    n_o = {d_o.GetFieldDefn(i).GetName(): i for i in range(d_o.GetFieldCount())}
    CELL = 10.0
    grid = {}

    def cells(x, y, r=1):
        cx, cy = int(x // CELL), int(y // CELL)
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                yield (cx + dx, cy + dy)

    n_osm = 0
    for feat in lyr_o:
        g = feat.GetGeometryRef()
        if not g:
            continue
        c = g.Centroid()
        rec = (c.GetX(), c.GetY(),
               str(feat.GetField(n_o["height"]) or "") if "height" in n_o else "",
               str(feat.GetField(n_o["levels"]) or "") if "levels" in n_o else "",
               str(feat.GetField(n_o["start_date"]) or "") if "start_date" in n_o else "",
               str(feat.GetField(n_o["building"]) or "") if "building" in n_o else "")
        for key in cells(c.GetX(), c.GetY()):
            grid.setdefault(key, []).append(rec)
        n_osm += 1
    ds_o = None
    print(f"  indexed {n_osm} OSM buildings")

    # ---- attach to the BAG footprints
    ds = ogr.Open(sh(bld))
    lyr = ds.GetLayer(0)
    d = lyr.GetLayerDefn()
    n_f = {d.GetFieldDefn(i).GetName(): i for i in range(d.GetFieldCount())}
    out_name = OUT / "buildings.gpkg"
    if out_name.exists():
        out_name.unlink()
    drv = ogr.GetDriverByName("GPKG")
    out_ds = drv.CreateDataSource(sh(out_name))
    o_lyr = out_ds.CreateLayer("buildings", srs=lyr.GetSpatialRef(),
                               geom_type=ogr.wkbMultiPolygon)
    for i in range(d.GetFieldCount()):
        fd = d.GetFieldDefn(i)
        o_lyr.CreateField(ogr.FieldDefn(fd.GetName(), fd.GetType()))
    o_lyr.CreateField(ogr.FieldDefn("height_m", ogr.OFTReal))
    o_lyr.CreateField(ogr.FieldDefn("age_class", ogr.OFTString))
    o_lyr.CreateField(ogr.FieldDefn("osm_building", ogr.OFTString))
    o_lyr.CreateField(ogr.FieldDefn("osm_start_date", ogr.OFTString))
    o_defn = o_lyr.GetLayerDefn()

    cnt = n_h = 0
    for feat in lyr:
        nf = ogr.Feature(o_defn)
        for i in range(d.GetFieldCount()):
            nf.SetField(i, feat.GetField(i))
        g = feat.GetGeometryRef()
        hm = None
        btype = sdate = ""
        if g:
            c = g.Centroid()
            cands = []
            for key in cells(c.GetX(), c.GetY()):
                cands.extend(grid.get(key, ()))
            if cands:
                cands.sort(key=lambda r: (0 if r[2] else 1, 0 if r[3] else 1))
                rec = cands[0]
                btype, sdate = rec[5], rec[4]
                for raw, factor in ((rec[2], 1.0), (rec[3], 3.0)):
                    try:
                        v = str(raw).replace(",", ".").replace("m", "").strip()
                        if v:
                            hm = float(v) * factor
                            break
                    except ValueError:
                        pass
        if hm is not None:
            n_h += 1
        else:
            hm = 9.0
        nf.SetField("height_m", round(hm, 2))
        nf.SetField("age_class", str(feat.GetField(n_f["bouwjaar"]) or "")
                    if "bouwjaar" in n_f else "")
        nf.SetField("osm_building", btype)
        nf.SetField("osm_start_date", sdate)
        nf.SetGeometry(g)
        o_lyr.CreateFeature(nf)
        cnt += 1
    out_ds = None
    ds = None
    print(f"  buildings.gpkg -> {cnt} features ({n_h} with a real OSM height)")


if __name__ == "__main__":
    build_pois()
    build_osm_buildings()
    bag_buildings_with_heights()
