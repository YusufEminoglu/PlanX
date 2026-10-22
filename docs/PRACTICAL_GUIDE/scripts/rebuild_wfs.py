#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Final rebuild of the PDOK-derived vector layers, straight from the WFS
GeoJSON into EPSG:28992 (the GeoJSON is always WGS84, so the conversion has
to happen here - and without -makevalid, which silently drops geometries).
"""
import json
import os
import subprocess
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
            print("    !", tail[-1][:150])
    return r.returncode == 0


def wfs_to_gpkg(base, typename, dest, nlt=None):
    """WFS -> GeoJSON (paged) -> GPKG in EPSG:28992."""
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
        tmp = RAW / "pg_page.json"
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
        print(f"  [FAIL] {typename}: no features")
        return False
    gj = RAW / (dest.stem + "_raw.geojson")
    with open(gj, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f)
    if dest.exists():
        dest.unlink()
    # the GeoJSON driver only honours the crs member through the OGR API
    src_ds = ogr.Open(sh(gj))
    src_lyr = src_ds.GetLayer(0)
    defn = src_lyr.GetLayerDefn()
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(28992)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    drv = ogr.GetDriverByName("GPKG")
    out_ds = drv.CreateDataSource(sh(dest))
    out_lyr = out_ds.CreateLayer(dest.stem, srs=srs, geom_type=ogr.wkbMultiPolygon)
    for i in range(defn.GetFieldCount()):
        fd = defn.GetFieldDefn(i)
        nfd = ogr.FieldDefn(fd.GetName(), fd.GetType())
        nfd.SetWidth(fd.GetWidth())
        out_lyr.CreateField(nfd)
    out_defn = out_lyr.GetLayerDefn()
    for feat in src_lyr:
        nf = ogr.Feature(out_defn)
        for i in range(defn.GetFieldCount()):
            nf.SetField(i, feat.GetField(i))
        g = feat.GetGeometryRef()
        if g is not None:
            nf.SetGeometry(g)
        out_lyr.CreateFeature(nf)
    out_ds = None
    src_ds = None
    gj.unlink(missing_ok=True)
    ds = ogr.Open(sh(dest))
    lyr = ds.GetLayer(0)
    n = lyr.GetFeatureCount()
    with_geom = 0
    sample = []
    for f in lyr:
        g = f.GetGeometryRef()
        if g is not None:
            with_geom += 1
            if len(sample) < 2:
                try:
                    c = g.Centroid()
                    sample.append((round(c.GetX(), 1), round(c.GetY(), 1)))
                except Exception:
                    sample.append("?")
        if with_geom > 5:
            break
    srs2 = lyr.GetSpatialRef()
    code = srs2.GetAuthorityCode(None) if srs2 else "?"
    ds = None
    print(f"  [ok] {dest.name}: {n} features, geometry OK: {with_geom > 0} "
          f"{sample}, EPSG:{code}")
    return True


if __name__ == "__main__":
    print("=== rebuild the PDOK vector layers in EPSG:28992 ===")
    wfs_to_gpkg("https://service.pdok.nl/kadaster/bag/wfs/v2_0", "bag:pand",
                OUT / "bag_pand.gpkg", "MULTIPOLYGON")
    wfs_to_gpkg("https://service.pdok.nl/kadaster/bag/wfs/v2_0",
                "bag:verblijfsobject", OUT / "bag_adres.gpkg", "POINT")
    wfs_to_gpkg("https://service.pdok.nl/cbs/wijken-en-buurten-2025/wfs/v1_0",
                "wijkenbuurten:buurten", OUT / "cbs_buurten.gpkg", "MULTIPOLYGON")
    wfs_to_gpkg("https://service.pdok.nl/cbs/wijken-en-buurten-2025/wfs/v1_0",
                "wijkenbuurten:wijken", OUT / "cbs_wijken.gpkg", "MULTIPOLYGON")
    wfs_to_gpkg("https://service.pdok.nl/cbs/postcode6/2024/wfs/v1_0",
                "postcode6:postcode6", OUT / "postcode_pop.gpkg", "MULTIPOLYGON")
    wfs_to_gpkg("https://service.pdok.nl/cbs/bestand-bodemgebruik-2010/wfs/v1_0",
                "bestand_bodemgebruik_2010_bodemgebruik",
                OUT / "bodemgebruik_2010.gpkg", "MULTIPOLYGON")
    wfs_to_gpkg("https://service.pdok.nl/cbs/bestand-bodemgebruik-2017/wfs/v1_0",
                "bestandbodemgebruik:BBG2017",
                OUT / "bodemgebruik_2017.gpkg", "MULTIPOLYGON")
