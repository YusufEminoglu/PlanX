#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Final data preparation for the PlanX practical guide, Utrecht (real open data).

1. CBS PC6 postcode population (PDOK WFS) -> allocated to the BAG address
   points, giving a real population per demand point.
2. DEM/DSM gap filling: SRTM into the AHN DTM gaps, then the DTM into the
   AHN DSM gaps, so both rasters are complete over the study area.
3. Writes the final layer set that the PlanX runner consumes.
"""
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()

ROOT = Path("/mnt/c/Users/YE/Downloads/planx_nl_data") if os.name != "nt" \
    else Path(r"C:\Users\YE\Downloads\planx_nl_data")
OUT = ROOT / "out"
RAW = ROOT / "raw"
RD = "EPSG:28992"
BBOX = (135206.6, 454196.8, 138361.3, 457368.2)
UA = {"User-Agent": "Mozilla/5.0 (PlanX data pipeline)"}


def sh(p):
    return str(p).replace("/", "\\") if os.name == "nt" else str(p)


def run(cmd, timeout=3600):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode and r.stderr:
        tail = [x for x in r.stderr.strip().splitlines() if x.strip()]
        if tail:
            print("    !", tail[-1][:140])
    return r.returncode == 0


def wfs_all(base, typename, dest_path):
    """Download a WFS layer with pagination into a GPKG."""
    feats = []
    start = 0
    page = 1000
    while True:
        params = {
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeNames": typename, "outputFormat": "application/json",
            "srsName": RD, "count": str(page), "startIndex": str(start),
            "bbox": f"{BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]},{RD}",
        }
        url = base + "?" + urllib.parse.urlencode(params)
        tmp = RAW / "pc6_page.json"
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as f:
                f.write(r.read())
            with open(tmp, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"    [WARN] page {start}: {str(e)[:110]}")
            break
        got = data.get("features", [])
        feats.extend(got)
        start += page
        if len(got) < page or start > 60000:
            break
    tmp.unlink(missing_ok=True)
    if not feats:
        return False
    gj = RAW / "pc6.geojson"
    with open(gj, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f)
    src = ogr.Open(sh(gj))
    lyr = src.GetLayer(0)
    defn = lyr.GetLayerDefn()
    if dest_path.exists():
        dest_path.unlink()
    drv = ogr.GetDriverByName("GPKG")
    out = drv.CreateDataSource(sh(dest_path))
    o_lyr = out.CreateLayer(dest_path.stem, srs=lyr.GetSpatialRef(),
                            geom_type=ogr.wkbMultiPolygon)
    for i in range(defn.GetFieldCount()):
        fd = defn.GetFieldDefn(i)
        o_lyr.CreateField(ogr.FieldDefn(fd.GetName(), fd.GetType()))
    o_defn = o_lyr.GetLayerDefn()
    for feat in lyr:
        nf = ogr.Feature(o_defn)
        for i in range(defn.GetFieldCount()):
            nf.SetField(i, feat.GetField(i))
        nf.SetGeometry(feat.GetGeometryRef())
        o_lyr.CreateFeature(nf)
    out = None
    src = None
    gj.unlink(missing_ok=True)
    print(f"  [ok] {dest_path.name}: {len(feats)} features")
    return True


def get_postcode_population():
    print("=== CBS PC6 postcode population (PDOK WFS) ===")
    dest = OUT / "postcode_pop.gpkg"
    if not wfs_all("https://service.pdok.nl/cbs/postcode6/2024/wfs/v1_0",
                   "postcode6:postcode6", dest):
        print("  [FAIL] PC6 download")
        return None
    ds = ogr.Open(sh(dest))
    lyr = ds.GetLayer(0)
    d = lyr.GetLayerDefn()
    n = {d.GetFieldDefn(i).GetName(): i for i in range(d.GetFieldCount())}
    pop_field = None
    for cand in ("aantalInwoners", "inwoners", "AantalInwoners", "pop"):
        if cand in n:
            pop_field = cand
            break
    if not pop_field:
        print("  [WARN] no population field; fields:", list(n))
        pop_field = list(n)[-1]
    pc = {}
    for f in lyr:
        code = str(f.GetField(n.get("postcode6", list(n)[0])) or "").strip()
        code = code.replace(" ", "").upper()
        try:
            v = int(f.GetField(n[pop_field]) or 0)
        except (TypeError, ValueError):
            v = 0
        if v < 0:          # CBS "no data" sentinel
            v = 0
        pc[code] = v
    ds = None
    print(f"  [ok] {len(pc)} postcodes with population "
          f"(total {sum(pc.values())})")
    return pc


def allocate_population(pc_pop):
    """Attach the real population to every BAG address point."""
    print("=== population allocation to address points ===")
    # keep one pristine copy of the BAG addresses (never overwritten)
    raw = OUT / "_bag_raw.gpkg"
    if not raw.exists():
        run(["ogr2ogr", "-f", "GPKG", sh(raw), sh(OUT / "bag_adres.gpkg"),
             "-sql", "SELECT * FROM demand", "-nln", "demand", "-nlt", "POINT",
             "-lco", "GEOMETRY_NAME=geom"])
    dem = raw
    if not dem.exists():
        print("  [FAIL] BAG addresses missing")
        return
    ds = ogr.Open(sh(dem))
    lyr = ds.GetLayer(0)
    d = lyr.GetLayerDefn()
    n = {d.GetFieldDefn(i).GetName(): i for i in range(d.GetFieldCount())}
    # count addresses per postcode
    per_pc = {}
    for f in lyr:
        pc = str(f.GetField(n["postcode"]) or "").replace(" ", "").upper()
        per_pc[pc] = per_pc.get(pc, 0) + 1
    out_name = OUT / "_demand_pop.gpkg"
    if out_name.exists():
        out_name.unlink()
    drv = ogr.GetDriverByName("GPKG")
    out = drv.CreateDataSource(sh(out_name))
    o_lyr = out.CreateLayer("demand", srs=lyr.GetSpatialRef(), geom_type=ogr.wkbPoint)
    skip = {"pop", "pc_pop"}
    for i in range(d.GetFieldCount()):
        fd = d.GetFieldDefn(i)
        if fd.GetName() in skip:
            continue
        o_lyr.CreateField(ogr.FieldDefn(fd.GetName(), fd.GetType()))
    o_lyr.CreateField(ogr.FieldDefn("pop", ogr.OFTReal))
    o_lyr.CreateField(ogr.FieldDefn("pc_pop", ogr.OFTInteger))
    o_defn = o_lyr.GetLayerDefn()
    assigned = 0
    total = 0.0
    for feat in lyr:
        nf = ogr.Feature(o_defn)
        for i in range(d.GetFieldCount()):
            nm = d.GetFieldDefn(i).GetName()
            if nm in skip:
                continue
            nf.SetField(d.GetFieldIndex(nm), feat.GetField(i))
        pc = str(feat.GetField(n["postcode"]) or "").replace(" ", "").upper()
        tot = pc_pop.get(pc, 0)
        cnt = per_pc.get(pc, 0)
        p = (tot / cnt) if cnt else 0.0
        if p > 0:
            assigned += 1
            total += p
        nf.SetField("pop", round(p, 3))
        nf.SetField("pc_pop", int(tot))
        nf.SetGeometry(feat.GetGeometryRef())
        o_lyr.CreateFeature(nf)
    out = None
    ds = None
    out_name.replace(OUT / "demand.gpkg")
    print(f"  [ok] demand.gpkg: {assigned} addresses with population "
          f"(total {total:.0f} residents)")


def fill_rasters():
    """Fill the AHN DTM/DSM gaps with real fallback data (SRTM)."""
    print("=== DEM / DSM gap filling ===")
    import numpy as np
    srtm = OUT / "srtm_dem.tif"
    dtm = OUT / "dem.tif"
    dsm = OUT / "dsm.tif"
    nod = -9999.0

    def read(p):
        ds = gdal.Open(sh(p))
        b = ds.GetRasterBand(1)
        a = b.ReadAsArray().astype("float32")
        gt = ds.GetGeoTransform()
        srs = ds.GetSpatialRef()
        ds = None
        return a, gt, srs

    def write(p, a, gt, srs, nodata=-9999.0):
        h, w = a.shape
        drv = gdal.GetDriverByName("GTiff")
        ds = drv.Create(sh(p), w, h, 1, gdal.GDT_Float32,
                        options=["COMPRESS=DEFLATE", "TILED=YES"])
        ds.SetGeoTransform(gt)
        ds.SetProjection(srs.ExportToWkt())
        b = ds.GetRasterBand(1)
        b.SetNoDataValue(nodata)
        b.WriteArray(a)
        ds.FlushCache()
        ds = None

    # --- DEM: AHN DTM, gaps filled with SRTM
    if dtm.exists():
        a, gt, srs = read(dtm)
        gaps = int((a <= nod + 1).sum())
        if srtm.exists():
            # resample SRTM onto the AHN grid (1 m) before filling
            up = OUT / "_srtm_on_grid.tif"
            run(["gdalwarp", "-t_srs", RD,
                 "-te", str(BBOX[0]), str(BBOX[1]), str(BBOX[2]), str(BBOX[3]),
                 "-tr", "1", "1", "-r", "cubic", "-of", "GTiff",
                 "-co", "COMPRESS=DEFLATE", sh(srtm), sh(up)])
            if up.exists():
                b2, gt2, srs2 = read(up)
                if b2.shape == a.shape:
                    a = np.where(a <= nod + 1, b2, a)
                up.unlink()
        a = np.where(a <= nod + 1, np.nan, a)
        a = np.nan_to_num(a, nan=nod)
        write(dtm, a, gt, srs)
        v = a[a > nod + 1]
        print(f"  DEM: {v.size/a.size*100:.1f}% valid, {v.min():.1f}..{v.max():.1f} m "
              f"(filled {gaps} AHN gap px with SRTM)")

    # --- DSM: AHN DSM, gaps filled with the DEM
    if dsm.exists() and dtm.exists():
        a, gt, srs = read(dsm)
        b2, gt2, srs2 = read(dtm)
        gaps = int((a <= nod + 1).sum())
        if b2.shape == a.shape:
            a = np.where(a <= nod + 1, b2, a)
        a = np.where(a <= nod + 1, np.nan, a)
        a = np.nan_to_num(a, nan=nod)
        write(dsm, a, gt, srs)
        v = a[a > nod + 1]
        print(f"  DSM: {v.size/a.size*100:.1f}% valid, {v.min():.1f}..{v.max():.1f} m "
              f"(filled {gaps} AHN gap px with the DTM)")


if __name__ == "__main__":
    pc_pop = get_postcode_population()
    if pc_pop:
        allocate_population(pc_pop)
    fill_rasters()
    print("\n=== FINAL ===")
    for p in sorted(OUT.glob("*.gpkg")):
        try:
            ds = ogr.Open(sh(p))
            print(f"  {ds.GetLayer(0).GetFeatureCount():8d}  {p.name}")
            ds = None
        except Exception:
            print(f"  {'':8s}  {p.name}")
    for p in sorted(OUT.glob("*.tif")):
        if p.name.startswith(("_", "ahn_", "srtm")):
            continue
        ds = gdal.Open(sh(p))
        print(f"  {ds.RasterXSize}x{ds.RasterYSize:<5}  {p.name}")
        ds = None
