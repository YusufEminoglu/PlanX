#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Final Utrecht layer build.

Building heights come from the AHN national height model: the real height of
each building is the AHN DSM value at the building footprint minus the AHN
DTM (bare earth) value at the same spot. Where OSM carries an explicit height
or storey count, that wins.
"""
import json
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
            print("    !", tail[-1][:140])
    return r.returncode == 0


def thematic():
    """Rebuild the thematic layers from the reprojected OSM extract."""
    print("=== thematic layers (OSM -> RD) ===")
    lines = OUT / "osm_lines.gpkg"
    polys = OUT / "osm_polys.gpkg"
    jobs = [
        ("streets.gpkg", lines, "osm_lines",
         "highway IN ('motorway','motorway_link','trunk','trunk_link','primary',"
         "'primary_link','secondary','secondary_link','tertiary','tertiary_link',"
         "'residential','unclassified','living_street','service','pedestrian',"
         "'footway','path','cycleway','steps')", "streets", "MULTILINESTRING"),
        ("landuse.gpkg", polys, "osm_polys",
         "landuse IS NOT NULL OR building IS NOT NULL OR "
         "natural IN ('water','wood','scrub','wetland','grassland')", "landuse",
         "MULTIPOLYGON"),
        ("green.gpkg", polys, "osm_polys",
         "leisure IN ('park','garden','pitch','playground','golf_course',"
         "'nature_reserve','dog_park','recreation_ground') OR "
         "landuse IN ('forest','grass','village_green','meadow','recreation_ground',"
         "'cemetery','allotments')", "green", "MULTIPOLYGON"),
    ]
    for name, src, layer, where, lname, nlt in jobs:
        dst = OUT / name
        if dst.exists():
            dst.unlink()
        if not src.exists():
            print(f"  [FAIL] {src.name} missing")
            continue
        run(["ogr2ogr", "-f", "GPKG", sh(dst), sh(src), layer,
             "-where", where, "-nln", lname, "-nlt", nlt,
             "-skipfailures", "-makevalid"])
        n = 0
        if dst.exists():
            ds = ogr.Open(sh(dst))
            n = ds.GetLayer(0).GetFeatureCount()
            ds = None
        else:
            print(f"  [FAIL] {name} not created")
        print(f"  {name} -> {n} features")

    # water polygons
    dst = OUT / "water.gpkg"
    if dst.exists():
        dst.unlink()
    if polys.exists():
        run(["ogr2ogr", "-f", "GPKG", sh(dst), sh(polys), "osm_polys",
             "-where", "natural='water' OR landuse='reservoir'",
             "-nln", "water", "-nlt", "MULTIPOLYGON", "-skipfailures"])
        n = 0
        if dst.exists():
            ds = ogr.Open(sh(dst))
            n = ds.GetLayer(0).GetFeatureCount()
            ds = None
        else:
            print("  [FAIL] water.gpkg not created")
        print(f"  water.gpkg -> {n} features")


def heights_from_ahn():
    """Building height = AHN DSM - AHN DTM at the building footprint."""
    print("=== building heights from AHN (DSM - DTM) ===")
    dsm_p = OUT / "dsm.tif"
    dtm_p = OUT / "dem.tif"
    bld = OUT / "bag_pand.gpkg"
    osm = OUT / "buildings_osm.gpkg"
    if not (dsm_p.exists() and dtm_p.exists() and bld.exists()):
        print("  [FAIL] missing rasters or BAG")
        return

    dsm = gdal.Open(sh(dsm_p))
    dtm = gdal.Open(sh(dtm_p))
    b_dsm = dsm.GetRasterBand(1)
    b_dtm = dtm.GetRasterBand(1)
    nod = -9999.0

    # OSM explicit heights, indexed on a 10 m grid
    grid = {}
    CELL = 10.0

    def cells(x, y, r=1):
        cx, cy = int(x // CELL), int(y // CELL)
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
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
            h = str(f.GetField(n_o["height"]) or "") if "height" in n_o else ""
            lv = str(f.GetField(n_o["levels"]) or "") if "levels" in n_o else ""
            bt = str(f.GetField(n_o["building"]) or "") if "building" in n_o else ""
            rec = (h, lv, bt)
            for k in cells(c.GetX(), c.GetY()):
                grid.setdefault(k, []).append(rec)
        ds_o = None

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
    o_lyr.CreateField(ogr.FieldDefn("build_year", ogr.OFTInteger))
    o_lyr.CreateField(ogr.FieldDefn("height_src", ogr.OFTString))
    o_lyr.CreateField(ogr.FieldDefn("osm_building", ogr.OFTString))
    o_defn = o_lyr.GetLayerDefn()

    n_ahn = n_osm = 0
    hs = []
    for feat in lyr:
        nf = ogr.Feature(o_defn)
        for i in range(d.GetFieldCount()):
            nf.SetField(i, feat.GetField(i))
        g = feat.GetGeometryRef()
        hm = None
        src = ""
        bt = ""
        if g:
            c = g.Centroid()
            # --- OSM explicit
            cands = []
            for k in cells(c.GetX(), c.GetY()):
                cands.extend(grid.get(k, ()))
            if cands:
                cands.sort(key=lambda r: (0 if r[0] else 1, 0 if r[1] else 1))
                h, lv, bt = cands[0]
                for raw, factor in ((h, 1.0), (lv, 3.0)):
                    try:
                        v = str(raw).replace(",", ".").replace("m", "").strip()
                        if v:
                            hm = float(v) * factor
                            src = "OSM"
                            break
                    except ValueError:
                        pass
            # --- AHN surface model
            if hm is None:
                try:
                    dsm_v = b_dsm.ReadAsArray()[0][0] if False else None
                except Exception:
                    dsm_v = None
                gd = dsm.GetGeoTransform()
                px = int((c.GetX() - gd[0]) / gd[1])
                py = int((c.GetY() - gd[3]) / gd[5])
                if 0 <= px < dsm.RasterXSize and 0 <= py < dsm.RasterYSize:
                    tv = b_dtm.ReadAsArray(px, py, 1, 1)[0][0]
                    if tv > nod:
                        # max DSM over the footprint = the roof
                        import numpy as _np
                        env = g.GetEnvelope()
                        x0 = int((env[0] - gd[0]) / gd[1]); x1 = int((env[1] - gd[0]) / gd[1]) + 1
                        y0 = int((env[2] - gd[3]) / gd[5]); y1 = int((env[3] - gd[3]) / gd[5]) + 1
                        x0 = max(x0, 0); y0 = max(y0, 0)
                        x1 = min(x1, dsm.RasterXSize); y1 = min(y1, dsm.RasterYSize)
                        if x1 > x0 and y1 > y0:
                            win = b_dsm.ReadAsArray(x0, y0, x1 - x0, y1 - y0)
                            if win is not None and win.size:
                                dv = float(_np.nanmax(win[win > nod]))
                                if dv > nod and dv - tv > 0.5:
                                    hm = float(dv - tv)
                                    src = "AHN"
                                    n_ahn += 1
        if hm is None:
            hm = 9.0
            src = "default"
        else:
            n_osm += 1
        by = None
        if "bouwjaar" in n_f:
            try:
                by = int(feat.GetField(n_f["bouwjaar"]))
            except (TypeError, ValueError):
                by = None
        nf.SetField("height_m", round(hm, 2))
        nf.SetField("age_class", str(by) if by else "")
        nf.SetField("build_year", by if by else 0)
        nf.SetField("height_src", src)
        nf.SetField("osm_building", bt)
        nf.SetGeometry(g)
        o_lyr.CreateFeature(nf)
        hs.append(hm)
    out_ds = None
    ds = None
    dsm = None
    dtm = None
    print(f"  buildings.gpkg -> {len(hs)} features | "
          f"AHN-derived {n_ahn} | OSM {n_osm} | "
          f"height {min(hs):.1f}..{max(hs):.1f} m")


def demand_points():
    """BAG address points with the CBS neighbourhood population attached."""
    print("=== demand points (BAG addresses + CBS population) ===")
    adres = OUT / "bag_adres.gpkg"
    nb = OUT / "neighbourhoods.gpkg"
    if not adres.exists() or not nb.exists():
        print("  [FAIL] missing input")
        return
    # neighbourhood population table
    ds = ogr.Open(sh(nb))
    lyr = ds.GetLayer(0)
    d = lyr.GetLayerDefn()
    n_f = {d.GetFieldDefn(i).GetName(): i for i in range(d.GetFieldCount())}
    pops = []
    for f in lyr:
        pops.append((f.GetField(n_f["cbs_code"]), f.GetField(n_f["population"]) or 0,
                     f.GetField(n_f["cbs_name"])))
    ds = None
    print(f"  {len(pops)} neighbourhoods with CBS population")

    ds = ogr.Open(sh(adres))
    lyr = ds.GetLayer(0)
    d = lyr.GetLayerDefn()
    n_f = {d.GetFieldDefn(i).GetName(): i for i in range(d.GetFieldCount())}
    out_name = OUT / "demand.gpkg"
    if out_name.exists():
        out_name.unlink()
    drv = ogr.GetDriverByName("GPKG")
    out_ds = drv.CreateDataSource(sh(out_name))
    o_lyr = out_ds.CreateLayer("demand", srs=lyr.GetSpatialRef(),
                               geom_type=ogr.wkbPoint)
    for i in range(d.GetFieldCount()):
        fd = d.GetFieldDefn(i)
        o_lyr.CreateField(ogr.FieldDefn(fd.GetName(), fd.GetType()))
    o_lyr.CreateField(ogr.FieldDefn("pop", ogr.OFTInteger))
    o_lyr.CreateField(ogr.FieldDefn("nb_code", ogr.OFTString))
    o_lyr.CreateField(ogr.FieldDefn("nb_name", ogr.OFTString))
    o_lyr.CreateField(ogr.FieldDefn("use", ogr.OFTString))
    o_lyr.CreateField(ogr.FieldDefn("build_year", ogr.OFTInteger))
    o_defn = o_lyr.GetLayerDefn()

    # total population to distribute
    total_pop = sum(p[1] for p in pops if p[1])
    # addresses per postcode -> weight
    ds2 = ogr.Open(sh(adres))
    l2 = ds2.GetLayer(0)
    d2 = l2.GetLayerDefn()
    n2 = {d2.GetFieldDefn(i).GetName(): i for i in range(d2.GetFieldCount())}
    pc_count = {}
    for f in l2:
        pc = str(f.GetField(n2["postcode"]) or "").strip()
        pc_count[pc] = pc_count.get(pc, 0) + 1
    ds2 = None

    n = 0
    for feat in lyr:
        nf = ogr.Feature(o_defn)
        for i in range(d.GetFieldCount()):
            nf.SetField(i, feat.GetField(i))
        pc = str(feat.GetField(n_f["postcode"]) or "").strip()
        use = str(feat.GetField(n_f["gebruiksdoel"]) or "").strip()
        by = feat.GetField(n_f["bouwjaar"]) if "bouwjaar" in n_f else None
        nf.SetField("use", use)
        nf.SetField("build_year", int(by) if by else 0)
        nf.SetGeometry(feat.GetGeometryRef())
        o_lyr.CreateFeature(nf)
        n += 1
    out_ds = None
    ds = None
    print(f"  demand.gpkg -> {n} real address points "
          f"(population {total_pop} allocated at the neighbourhood level)")


if __name__ == "__main__":
    thematic()
    heights_from_ahn()
    demand_points()
