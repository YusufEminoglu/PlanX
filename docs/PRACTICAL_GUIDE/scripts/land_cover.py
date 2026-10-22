#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CBS Bestand Bodemgebruik (national land-use) 2010 and 2017 -> class rasters
and urban masks, so the land-cover change and sprawl tools run on real
two-period data for Utrecht.
"""
import json
import os
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
from osgeo import gdal, ogr

gdal.UseExceptions()
ogr.UseExceptions()

ROOT = Path("/mnt/c/Users/YE/Downloads/planx_nl_data") if os.name != "nt" \
    else Path(r"C:\Users\YE\Downloads\planx_nl_data")
OUT = ROOT / "out"
RAW = ROOT / "raw"
RD = "EPSG:28992"
BBOX = (135206.6, 454196.8, 138361.3, 457368.2)
CELL = 10.0
W = int((BBOX[2] - BBOX[0]) / CELL)
H = int((BBOX[3] - BBOX[1]) / CELL)
UA = {"User-Agent": "Mozilla/5.0 (PlanX data pipeline)"}


def sh(p):
    return str(p).replace("/", "\\") if os.name == "nt" else str(p)


def run(cmd, timeout=2400):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode and r.stderr:
        tail = [x for x in r.stderr.strip().splitlines() if x.strip()]
        if tail:
            print("    !", tail[-1][:140])
    return r.returncode == 0


def wfs(base, typename, dest):
    feats = []
    start = 0
    while True:
        params = {
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeNames": typename, "outputFormat": "application/json",
            "srsName": RD, "count": "1000", "startIndex": str(start),
            "bbox": f"{BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]},{RD}",
        }
        url = base + "?" + urllib.parse.urlencode(params)
        tmp = RAW / "bb_page.json"
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
        start += 1000
        if len(got) < 1000 or start > 40000:
            break
    tmp.unlink(missing_ok=True)
    if not feats:
        return False
    gj = RAW / (dest.stem + ".geojson")
    with open(gj, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f)
    src = ogr.Open(sh(gj))
    lyr = src.GetLayer(0)
    defn = lyr.GetLayerDefn()
    if dest.exists():
        dest.unlink()
    drv = ogr.GetDriverByName("GPKG")
    out = drv.CreateDataSource(sh(dest))
    o_lyr = out.CreateLayer(dest.stem, srs=lyr.GetSpatialRef(),
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
    gj.unlink()
    print(f"  [ok] {dest.name}: {len(feats)} features")
    return True


def rasterize(src_gpkg, class_field, class_map, out_tif, urban=False):
    """Rasterise a land-use layer to a class grid (GDAL RasterizeLayer)."""
    src = ogr.Open(sh(src_gpkg))
    lyr = src.GetLayer(0)
    defn = lyr.GetLayerDefn()
    nf = {defn.GetFieldDefn(i).GetName(): i for i in range(defn.GetFieldCount())}
    key = class_field if class_field in nf else list(nf)[0]

    mem_drv = ogr.GetDriverByName("Memory")
    mem = mem_drv.CreateDataSource("mem")
    m_lyr = mem.CreateLayer("tmp", srs=lyr.GetSpatialRef(), geom_type=ogr.wkbPolygon)
    m_lyr.CreateField(ogr.FieldDefn("cls", ogr.OFTInteger))
    m_defn = m_lyr.GetLayerDefn()
    n = 0
    for feat in lyr:
        val = str(feat.GetField(nf[key]) or "").strip()
        code = class_map.get(val)
        if code is None:
            continue
        g = feat.GetGeometryRef()
        if not g:
            continue
        try:
            env = g.GetEnvelope()
            if (env[1] - env[0]) > 20000 or (env[3] - env[2]) > 20000:
                continue
            try:
                g = g.MakeValid()
            except Exception:
                pass
        except Exception:
            continue
        nf2 = ogr.Feature(m_defn)
        nf2.SetField("cls", int(code))
        nf2.SetGeometry(g)
        m_lyr.CreateFeature(nf2)
        n += 1

    mem = None
    src = None
    # burn each class with gdal_rasterize (robust and fast)
    tmp_base = OUT / (Path(out_tif).stem + "_burn.tif")
    if tmp_base.exists():
        tmp_base.unlink()
    run(["gdal_rasterize", "-of", "GTiff", "-a_srs", RD,
         "-te", str(BBOX[0]), str(BBOX[1]), str(BBOX[2]), str(BBOX[3]),
         "-tr", str(CELL), str(CELL), "-init", "0", "-burn", "1",
         "-co", "COMPRESS=DEFLATE", sh(src_gpkg), sh(tmp_base),
         "-where", f"{class_field} is not null"])
    if not tmp_base.exists():
        print(f"  [FAIL] {out_tif}")
        return
    ds = gdal.Open(sh(tmp_base))
    arr = ds.GetRasterBand(1).ReadAsArray()
    ds = None
    out_arr = np.zeros_like(arr)
    for cls, code in class_map.items():
        run(["gdal_rasterize", "-of", "GTiff", "-a_srs", RD,
             "-te", str(BBOX[0]), str(BBOX[1]), str(BBOX[2]), str(BBOX[3]),
             "-tr", str(CELL), str(CELL), "-init", "0", "-burn", str(code),
             "-co", "COMPRESS=DEFLATE", sh(src_gpkg), sh(tmp_base),
             "-where", f"{class_field} = '{cls}'"])
        d2 = gdal.Open(sh(tmp_base))
        a2 = d2.GetRasterBand(1).ReadAsArray()
        d2 = None
        out_arr = np.where(a2 > 0, code, out_arr)
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(sh(out_tif), W, H, 1, gdal.GDT_Int16,
                    options=["COMPRESS=DEFLATE", "TILED=YES"])
    ds.SetGeoTransform((BBOX[0], CELL, 0, BBOX[3], 0, -CELL))
    srs = gdal.osr.SpatialReference()
    srs.ImportFromEPSG(28992)
    ds.SetProjection(srs.ExportToWkt())
    b = ds.GetRasterBand(1)
    b.SetNoDataValue(0)
    b.WriteArray(out_arr.astype("int16"))
    ds.FlushCache()
    ds = None
    tmp_base.unlink(missing_ok=True)
    vals = np.unique(out_arr)
    print(f"  [ok] {os.path.basename(out_tif)}: {W}x{H} @ {CELL:.0f} m, "
          f"{n} polygons, classes {vals.tolist()[:10]}")


if __name__ == "__main__":
    print("=== CBS Bestand Bodemgebruik 2010 / 2017 ===")
    for year in (2010, 2017):
        dest = OUT / f"bodemgebruik_{year}.gpkg"
        if dest.exists():
            print(f"  [skip] {dest.name}")
            continue
        tname = (f"bestand_bodemgebruik_{year}_bodemgebruik" if year == 2010
                 else "bestandbodemgebruik:BBG2017")
        wfs(f"https://service.pdok.nl/cbs/bestand-bodemgebruik-{year}/wfs/v1_0",
            tname, dest)

    # land-cover class rasters for the change matrix
    # CBS Bestand Bodemgebruik classes (2010 classification, used for both years)
    CLASS_MAP = {
        "Bebouwd exclusief bedrijfsterrein": 1,
        "Bedrijfsterrein": 2,
        "Semi-bebouwd": 3,
        "Recreatie": 4,
        "Water": 5,
        "Hoofdweg": 6,
        "Spoorterrein": 7,
        "Bebouwd inclusief bedrijfsterrein": 1,
    }
    URBAN = {"Bebouwd exclusief bedrijfsterrein", "Bedrijfsterrein",
             "Semi-bebouwd", "Hoofdweg", "Spoorterrein",
             "Bebouwd inclusief bedrijfsterrein"}
    for year in (2010, 2017):
        src = OUT / f"bodemgebruik_{year}.gpkg"
        if not src.exists():
            continue
        ds = ogr.Open(sh(src))
        lyr = ds.GetLayer(0)
        d = lyr.GetLayerDefn()
        flds = [d.GetFieldDefn(i).GetName() for i in range(d.GetFieldCount())]
        ds = None
        fld = "bodemgebruik" if "bodemgebruik" in flds else flds[0]
        print(f"  {year} fields: {flds[:6]}")
        rasterize(src, fld, CLASS_MAP, OUT / f"landcover_{year}.tif")
        rasterize(src, fld, {k: 1 for k in URBAN}, OUT / f"urban_{year}.tif",
                  urban=True)
