#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fill the derived attributes: building heights and demand population."""
import json
import os
import sys
from pathlib import Path

import numpy as np
from osgeo import gdal, ogr

gdal.UseExceptions()
ogr.UseExceptions()

ROOT = Path("/mnt/c/Users/YE/Downloads/planx_nl_data") if os.name != "nt" \
    else Path(r"C:\Users\YE\Downloads\planx_nl_data")
OUT = ROOT / "out"
RD = "EPSG:28992"


def sh(p):
    return str(p).replace("/", "\\") if os.name == "nt" else str(p)


def fill_population():
    """Write the real CBS PC6 population onto the BAG address points."""
    print("=== demand population (CBS PC6 -> BAG addresses) ===")
    pc = OUT / "postcode_pop.gpkg"
    dem = OUT / "bag_adres.gpkg"
    if not pc.exists() or not dem.exists():
        print("  [FAIL] missing input")
        return
    ds = ogr.Open(sh(pc))
    lyr = ds.GetLayer(0)
    d = lyr.GetLayerDefn()
    n = {d.GetFieldDefn(i).GetName(): i for i in range(d.GetFieldCount())}
    pc_pop = {}
    for f in lyr:
        code = str(f.GetField(n.get("postcode6", list(n)[0])) or "").replace(" ", "").upper()
        try:
            v = int(f.GetField(n["aantalInwoners"]) or 0)
        except (TypeError, ValueError, KeyError):
            v = 0
        if v > 0:
            pc_pop[code] = v
    ds = None
    print(f"  {len(pc_pop)} postcodes, {sum(pc_pop.values())} residents")

    ds = ogr.Open(sh(dem))
    lyr = ds.GetLayer(0)
    d = lyr.GetLayerDefn()
    n = {d.GetFieldDefn(i).GetName(): i for i in range(d.GetFieldCount())}
    per_pc = {}
    for f in lyr:
        pc = str(f.GetField(n["postcode"]) or "").replace(" ", "").upper()
        per_pc[pc] = per_pc.get(pc, 0) + 1

    # rebuild with the population column filled
    out_name = OUT / "_demand_new.gpkg"
    if out_name.exists():
        out_name.unlink()
    drv = ogr.GetDriverByName("GPKG")
    out = drv.CreateDataSource(sh(out_name))
    o_lyr = out.CreateLayer("demand", srs=lyr.GetSpatialRef(), geom_type=ogr.wkbPoint)
    for i in range(d.GetFieldCount()):
        fd = d.GetFieldDefn(i)
        o_lyr.CreateField(ogr.FieldDefn(fd.GetName(), fd.GetType()))
    if "pop" not in n:
        o_lyr.CreateField(ogr.FieldDefn("pop", ogr.OFTReal))
    o_defn = o_lyr.GetLayerDefn()
    total = 0.0
    for f in lyr:
        pc = str(f.GetField(n["postcode"]) or "").replace(" ", "").upper()
        tot = pc_pop.get(pc, 0)
        cnt = per_pc.get(pc, 0)
        p = round(tot / cnt, 4) if cnt and tot else 0.0
        total += p
        nf = ogr.Feature(o_defn)
        for i in range(d.GetFieldCount()):
            nf.SetField(i, f.GetField(i))
        nf.SetField(o_defn.GetFieldIndex("pop"), p)
        nf.SetGeometry(f.GetGeometryRef())
        o_lyr.CreateFeature(nf)
    out = None
    ds = None
    out_name.replace(OUT / "demand.gpkg")
    print(f"  [ok] demand.gpkg: {total:.0f} residents on "
          f"{len(per_pc)} postcodes")


def fill_heights():
    """Building height from the AHN surface model, OSM as the fallback."""
    print("=== building heights (AHN DSM - DTM, OSM fallback) ===")
    dsm_p = OUT / "dsm.tif"
    dtm_p = OUT / "dem.tif"
    bld = OUT / "bag_pand.gpkg"
    osm = OUT / "buildings_osm.gpkg"
    if not all(x.exists() for x in (dsm_p, dtm_p, bld)):
        print("  [FAIL] missing rasters")
        return
    dsm = gdal.Open(sh(dsm_p))
    dtm = gdal.Open(sh(dtm_p))
    b_dsm = dsm.GetRasterBand(1)
    b_dtm = dtm.GetRasterBand(1)
    gd = dsm.GetGeoTransform()
    nod = -9999.0

    # OSM heights in a grid
    grid = {}
    CELL = 12.0

    def cells(x, y):
        cx, cy = int(x // CELL), int(y // CELL)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                yield (cx + dx, cy + dy)

    if osm.exists():
        ds_o = ogr.Open(sh(osm))
        l_o = ds_o.GetLayer(0)
        d_o = l_o.GetLayerDefn()
        n_o = {d_o.GetFieldDefn(i).GetName(): i for i in range(d_o.GetFieldCount())}
        for f in l_o:
            g = f.GetGeometryRef()
            if not g:
                continue
            c = g.Centroid()
            rec = (str(f.GetField(n_o["height"]) or "") if "height" in n_o else "",
                   str(f.GetField(n_o["levels"]) or "") if "levels" in n_o else "",
                   str(f.GetField(n_o["start_date"]) or "") if "start_date" in n_o else "",
                   str(f.GetField(n_o["building"]) or "") if "building" in n_o else "")
            for k in cells(c.GetX(), c.GetY()):
                grid.setdefault(k, []).append(rec)
        ds_o = None

    ds = ogr.Open(sh(bld))
    lyr = ds.GetLayer(0)
    d = lyr.GetLayerDefn()
    n_f = {d.GetFieldDefn(i).GetName(): i for i in range(d.GetFieldCount())}
    # rebuild with the derived fields
    out_name = OUT / "_buildings_new.gpkg"
    if out_name.exists():
        out_name.unlink()
    drv = ogr.GetDriverByName("GPKG")
    out = drv.CreateDataSource(sh(out_name))
    o_lyr = out.CreateLayer("buildings", srs=lyr.GetSpatialRef(),
                            geom_type=ogr.wkbMultiPolygon)
    for i in range(d.GetFieldCount()):
        fd = d.GetFieldDefn(i)
        o_lyr.CreateField(ogr.FieldDefn(fd.GetName(), fd.GetType()))
    for fname, ftype in (("height_m", ogr.OFTReal), ("height_src", ogr.OFTString),
                         ("age_class", ogr.OFTString), ("build_year", ogr.OFTInteger),
                         ("osm_building", ogr.OFTString)):
        o_lyr.CreateField(ogr.FieldDefn(fname, ftype))
    o_defn = o_lyr.GetLayerDefn()
    n_ahn = n_osm = 0
    hs = []
    for f in lyr:
        g = f.GetGeometryRef()
        hm = None
        src = ""
        bt = sdate = ""
        if g:
            c = g.Centroid()
            px = int((c.GetX() - gd[0]) / gd[1])
            py = int((c.GetY() - gd[3]) / gd[5])
            if 0 <= px < dsm.RasterXSize and 0 <= py < dsm.RasterYSize:
                dv = float(b_dsm.ReadAsArray(px, py, 1, 1)[0][0])
                tv = float(b_dtm.ReadAsArray(px, py, 1, 1)[0][0])
                if dv > nod and tv > nod and dv - tv > 1.5:
                    hm = dv - tv
                    src = "AHN"
                    n_ahn += 1
            if hm is None:
                cands = []
                for k in cells(c.GetX(), c.GetY()):
                    cands.extend(grid.get(k, ()))
                if cands:
                    cands.sort(key=lambda r: (0 if r[0] else 1, 0 if r[1] else 1))
                    h, lv, sdate, bt = cands[0]
                    for raw, factor in ((h, 1.0), (lv, 3.0)):
                        try:
                            v = str(raw).replace(",", ".").replace("m", "").strip()
                            if v:
                                hm = float(v) * factor
                                src = "OSM"
                                break
                        except ValueError:
                            pass
                    if hm is not None:
                        n_osm += 1
        if hm is None:
            hm = 9.0
            src = "default"
        hs.append(hm)
        by = None
        try:
            by = int(f.GetField(n_f["bouwjaar"]))
        except (TypeError, ValueError):
            pass
        nf = ogr.Feature(o_defn)
        for i in range(d.GetFieldCount()):
            nf.SetField(i, f.GetField(i))
        nf.SetField("height_m", round(hm, 2))
        nf.SetField("height_src", src)
        nf.SetField("age_class", str(by) if by else "")
        nf.SetField("build_year", by if by else 0)
        nf.SetField("osm_building", bt)
        nf.SetGeometry(f.GetGeometryRef())
        o_lyr.CreateFeature(nf)
    out = None
    ds = None
    print(f"  [ok] buildings: {len(hs)} features | AHN {n_ahn} | OSM {n_osm} | "
          f"height {min(hs):.1f}..{max(hs):.1f} m")

    # publish as buildings.gpkg
    src_gpkg = OUT / "buildings.gpkg"
    if src_gpkg.exists():
        src_gpkg.unlink()
    out_name.replace(src_gpkg)
    ds = ogr.Open(sh(src_gpkg))
    print(f"  [ok] buildings.gpkg: {ds.GetLayer(0).GetFeatureCount()} features")
    ds = None


if __name__ == "__main__":
    fill_population()
    fill_heights()
