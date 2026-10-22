#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PlanX real-data pipeline - Utrecht, Netherlands (open data, no synthetic data).

Sources (all open / public):
  OSM       BBBike Utrecht extract (PBF)
  BAG       PDOK Kadaster WFS  - buildings with build year, addresses with residents
  CBS       PDOK wijk/buurt WFS + StatLine 86165NED kerncijfers
  AHN       PDOK WMS           - 0.5 m DSM and DTM
  SRTM      AWS terrain tiles  - DEM fallback
  GTFS      ovapi.nl           - full Dutch public transport feed

Study area: ~1000 ha around the historic centre of Utrecht.
"""
import json
import gzip
import os
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()

# Works both in WSL (/mnt/c/...) and native Windows
if os.name == "nt":
    ROOT = Path(r"C:\Users\YE\Downloads\planx_nl_data")
else:
    ROOT = Path("/mnt/c/Users/YE/Downloads/planx_nl_data")
RAW = ROOT / "raw"
OUT = ROOT / "out"
for d in (RAW, OUT):
    d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- study area
# ~3.16 x 3.16 km around the Dom Tower / historic centre -> ~1000 ha
LAT_MIN, LAT_MAX = 52.0758, 52.1042
LON_MIN, LON_MAX = 5.0983, 5.1445
BBOX_WGS = (LON_MIN, LAT_MIN, LON_MAX, LAT_MAX)
RD = "EPSG:28992"          # Amersfoort / RD New - the Dutch standard projected CRS

src = osr.SpatialReference()
src.ImportFromEPSG(4326)
src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
dst = osr.SpatialReference()
dst.ImportFromEPSG(28992)
dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
tr = osr.CoordinateTransformation(src, dst)
xmin, ymin, _ = tr.TransformPoint(LON_MIN, LAT_MAX)
xmax, ymax, _ = tr.TransformPoint(LON_MAX, LAT_MIN)
# RD y axis points north, so normalise to (min, min, max, max)
BBOX_RD = (min(xmin, xmax), min(ymin, ymax), max(xmin, xmax), max(ymin, ymax))
print(f"[area] RD bbox = {BBOX_RD[0]:.1f} {BBOX_RD[1]:.1f} {BBOX_RD[2]:.1f} {BBOX_RD[3]:.1f}")
w_m = BBOX_RD[2] - BBOX_RD[0]
h_m = BBOX_RD[3] - BBOX_RD[1]
print(f"[area] {w_m:.0f} m x {h_m:.0f} m = {w_m * h_m / 10000:.0f} ha")

UA = {"User-Agent": "Mozilla/5.0 (PlanX practical guide data pipeline)"}


def sh(p):
    """Native path for the current OS."""
    p = str(p)
    return p.replace("/", "\\") if os.name == "nt" else p


def fetch(url, dest, binary=True, retries=3):
    dest = Path(dest)
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  [skip] {dest.name} already present")
        return True
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=600) as r, open(dest, "wb") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
            print(f"  [ok] {dest.name} ({dest.stat().st_size/1e6:.1f} MB)")
            return True
        except Exception as e:
            print(f"  [retry {attempt}] {dest.name}: {str(e)[:120]}")
            if attempt == retries:
                return False
    return False


# ============================================================ 1. OSM extraction
def extract_osm():
    print("\n=== 1. OSM (BBBike Utrecht) -> clipped layers ===")
    pbf = RAW / "utrecht.osm.pbf"
    if not pbf.exists():
        print("  [FAIL] PBF missing")
        return False
    sp = f"{BBOX_WGS[0]} {BBOX_WGS[1]} {BBOX_WGS[2]} {BBOX_WGS[3]}"
    ok = True
    for layer, tag in (("lines", "osm_lines"), ("points", "osm_points"),
                       ("multipolygons", "osm_polys")):
        dst_p = OUT / f"{tag}.gpkg"
        if dst_p.exists():
            print(f"  [skip] {tag}.gpkg")
            continue
        cmd = ["ogr2ogr", "-f", "GPKG", sh(dst_p), sh(pbf), layer,
               "-spat", sp, "-nln", tag, "-lco", "GEOMETRY_NAME=geom",
               "--config", "OSM_USE_CURVE", "NO", "-skipfailures"]
        print(f"  extracting {layer} ...")
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if r.returncode != 0:
            print(f"  [WARN] {layer}: {r.stderr[:200]}")
        if dst_p.exists():
            n = ogr.Open(sh(dst_p)).GetLayerByName(tag).GetFeatureCount()
            print(f"  [ok] {tag}.gpkg -> {n} features")
        else:
            ok = False
    return ok


# ==================================================== 2. BAG WFS (buildings)
def wfs_dump(base, typename, dest, extra="", srs=RD, bbox=None, page=1000,
             max_pages=400):
    """Download a WFS layer as GeoJSON via GetFeature, with pagination."""
    bb = bbox or BBOX_RD
    gjs = []
    start = 0
    total = None
    while True:
        params = {
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeNames": typename, "outputFormat": "application/json",
            "srsName": srs, "count": str(page), "startIndex": str(start),
            "bbox": f"{bb[0]},{bb[1]},{bb[2]},{bb[3]},{srs}",
        }
        url = base + "?" + urllib.parse.urlencode(params)
        tmp = RAW / f"wfs_{typename.replace(':', '_')}_{start}.geojson"
        if not fetch(url, tmp, retries=3):
            if tmp.exists():
                tmp.unlink()
            break
        try:
            with open(tmp, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"  [WARN] {typename} page {start}: {e}")
            tmp.unlink()
            break
        feats = data.get("features", [])
        total = len(feats)
        gjs.extend(feats)
        print(f"  [ok] {typename} page {start}: {total} features "
              f"(total {len(gjs)})")
        tmp.unlink()
        if total < page:
            break
        start += page
        if start > 200000 or start // page >= max_pages:
            break

    if not gjs:
        print(f"  [FAIL] {typename}: no features")
        return False

    gj = RAW / (dest.stem + ".geojson")
    with open(gj, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": gjs}, f)
    print(f"  [ok] {typename}: {len(gjs)} features total")

    src_ds = ogr.Open(sh(gj))
    if src_ds is None:
        print(f"  [FAIL] cannot open {gj.name}")
        return False
    src_lyr = src_ds.GetLayer(0)
    drv = ogr.GetDriverByName("GPKG")
    if dest.exists():
        dest.unlink()
    out_ds = drv.CreateDataSource(sh(dest))
    gt = ogr.wkbUnknown
    for f in src_lyr.GetNextFeature() if False else []:
        pass
    out_lyr = out_ds.CreateLayer(dest.stem, srs=src_lyr.GetSpatialRef(),
                                 geom_type=gt)
    defn = src_lyr.GetLayerDefn()
    for i in range(defn.GetFieldCount()):
        fd = defn.GetFieldDefn(i)
        newfd = ogr.FieldDefn(fd.GetName(), fd.GetType())
        newfd.SetWidth(fd.GetWidth())
        out_lyr.CreateField(newfd)
    out_defn = out_lyr.GetLayerDefn()
    for feat in src_lyr:
        nf = ogr.Feature(out_defn)
        for i in range(defn.GetFieldCount()):
            nf.SetField(i, feat.GetField(i))
        nf.SetGeometry(feat.GetGeometryRef())
        out_lyr.CreateFeature(nf)
    out_ds = None
    src_ds = None
    gj.unlink()
    print(f"  [ok] {dest.name} written")
    return True


def get_bag():
    print("\n=== 2. BAG (PDOK WFS) - buildings with build year, addresses ===")
    base = "https://service.pdok.nl/kadaster/bag/wfs/v2_0"
    wfs_dump(base, "bag:pand", OUT / "bag_pand.gpkg")
    wfs_dump(base, "bag:verblijfsobject", OUT / "bag_adres.gpkg")


# ============================================== 3. CBS wijk / buurt polygons
def get_cbs_regions():
    print("\n=== 3. CBS wijk / buurt polygons (PDOK WFS 2025) ===")
    base = "https://service.pdok.nl/cbs/wijken-en-buurten-2025/wfs/v1_0"
    wfs_dump(base, "wijkenbuurten:wijken", OUT / "cbs_wijken.gpkg")
    wfs_dump(base, "wijkenbuurten:buurten", OUT / "cbs_buurten.gpkg")


# ======================================================= 4. CBS kerncijfers
CBS_TABLE = "86165NED"      # Kerncijfers wijken en buurten 2025


def get_cbs_stats():
    print(f"\n=== 4. CBS kerncijfers {CBS_TABLE} (StatLine) ===")
    dim_url = (f"https://opendata.cbs.nl/ODataApi/OData/{CBS_TABLE}/WijkenEnBuurten"
               "?$format=json")
    dim_path = RAW / "cbs_regions.json"
    if not fetch(dim_url, dim_path):
        return False
    with open(dim_path, encoding="utf-8") as f:
        regions = json.load(f).get("value", [])
    all_codes = [r["Key"] for r in regions]
    utrecht = [c for c in all_codes
               if c.startswith(("GM0344", "WK0344", "BU0344"))]
    print(f"  [ok] {len(utrecht)} Utrecht region codes (GM/WK/BU 0344)")

    # the region codes that matter are the ones whose polygon touches the
    # study area - read them from the PDOK buurten layer
    wanted = set()
    buurten = OUT / "cbs_buurten.gpkg"
    if buurten.exists():
        ds = ogr.Open(sh(buurten))
        lyr = ds.GetLayer(0)
        wanted = {f.GetField("codering") for f in lyr
                  if f.GetGeometryRef() and
                  f.GetGeometryRef().Intersects(
                      ogr.CreateGeometryFromWkt(
                          f"POLYGON(({BBOX_RD[0]} {BBOX_RD[1]},"
                          f"{BBOX_RD[2]} {BBOX_RD[1]},"
                          f"{BBOX_RD[2]} {BBOX_RD[3]},"
                          f"{BBOX_RD[0]} {BBOX_RD[3]},"
                          f"{BBOX_RD[0]} {BBOX_RD[1]}))"))}
        print(f"  [ok] {len(wanted)} buurten intersect the study area")
        ds = None
    codes = sorted(w for w in wanted if w in all_codes) or utrecht

    # fetch the data for those codes only (one row per region x indicator)
    rows = []
    chunk = 25
    for i in range(0, len(codes), chunk):
        part = codes[i:i + chunk]
        flt = " or ".join(f"WijkenEnBuurten eq '{c}'" for c in part)
        url = (f"https://opendata.cbs.nl/ODataApi/OData/{CBS_TABLE}/TypedDataSet"
               f"?$format=json&$filter={urllib.parse.quote(flt)}")
        tmp = RAW / f"cbs_chunk_{i}.json"
        if fetch(url, tmp, retries=2):
            with open(tmp, encoding="utf-8") as f:
                rows.extend(json.load(f).get("value", []))
            tmp.unlink()
        print(f"  [ok] chunk {i//chunk+1}: {len(rows)} rows so far")
        if len(part) < chunk:
            break
    print(f"  [ok] {len(rows)} CBS data rows for {len(codes)} regions")
    with open(OUT / "cbs_kerncijfers.json", "w", encoding="utf-8") as f:
        json.dump({"codes": codes, "rows": rows}, f)
    return bool(rows)


# ============================================================== 5. AHN DEM
def get_ahn():
    print("\n=== 5. AHN 0.5 m DSM / DTM (PDOK WMS) ===")
    base = ("https://service.pdok.nl/rws/actueel-hoogtebestand-nederland/wms/v1_0")
    # request at ~0.5 m: 3.2 km -> 6400 px (WMS max is usually 4096, so use 2 m)
    for layer, out_name, res in (("dtm_05m", "ahn_dtm.tif", 2.0),
                                  ("dsm_05m", "ahn_dsm.tif", 2.0)):
        dest = OUT / out_name
        if dest.exists():
            print(f"  [skip] {out_name}")
            continue
        w = int((BBOX_RD[2] - BBOX_RD[0]) / res)
        h = int((BBOX_RD[3] - BBOX_RD[1]) / res)
        params = {
            "service": "WMS", "version": "1.3.0", "request": "GetMap",
            "layers": layer, "styles": "", "crs": RD,
            "bbox": f"{BBOX_RD[0]},{BBOX_RD[1]},{BBOX_RD[2]},{BBOX_RD[3]}",
            "width": str(w), "height": str(h), "format": "image/tiff",
        }
        url = base + "?" + urllib.parse.urlencode(params)
        if fetch(url, dest):
            try:
                ds = gdal.Open(sh(dest))
                gt = ds.GetGeoTransform()
                print(f"  [ok] {out_name} {ds.RasterXSize}x{ds.RasterYSize} "
                      f"px={abs(gt[1]):.2f} m band={ds.GetRasterBand(1).GetDescription()}")
                ds = None
            except Exception as e:
                print(f"  [WARN] {out_name} unreadable: {e}")
        else:
            # fall back to SRTM
            print(f"  [WARN] AHN {layer} failed, using SRTM")


def get_srtm():
    print("\n=== 5b. SRTM DEM fallback (AWS terrain tiles) ===")
    hgt = RAW / "N52E005.hgt"
    gz = RAW / "N52E005.hgt.gz"
    if not hgt.exists() and gz.exists():
        with gzip.open(gz, "rb") as f_in, open(hgt, "wb") as f_out:
            f_out.write(f_in.read())
    if not hgt.exists():
        fetch("https://elevation-tiles-prod.s3.amazonaws.com/skadi/N52/N52E005.hgt.gz", gz)
        if gz.exists():
            with gzip.open(gz, "rb") as f_in, open(hgt, "wb") as f_out:
                f_out.write(f_in.read())
    if hgt.exists():
        dem = OUT / "srtm_dem.tif"
        if not dem.exists():
            cmd = ["gdalwarp", "-t_srs", RD, "-te", f"{BBOX_RD[0]}", f"{BBOX_RD[1]}",
                   f"{BBOX_RD[2]}", f"{BBOX_RD[3]}", "-r", "cubic", "-tr", "10", "10",
                   "-of", "GTiff", "-co", "COMPRESS=DEFLATE",
                   sh(hgt), sh(dem)]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
            if r.returncode:
                print("  [WARN] gdalwarp:", r.stderr[:200])
        if dem.exists():
            ds = gdal.Open(sh(dem))
            print(f"  [ok] srtm_dem.tif {ds.RasterXSize}x{ds.RasterYSize} "
                  f"px={abs(ds.GetGeoTransform()[1]):.0f} m")
            ds = None
            return True
    return False


# ============================================================== 6. GTFS
def get_gtfs():
    print("\n=== 6. GTFS (ovapi.nl) ===")
    z = RAW / "gtfs-nl.zip"
    if not z.exists():
        fetch("https://gtfs.ovapi.nl/gtfs-nl.zip", z)
    if z.exists():
        d = ROOT / "gtfs"
        d.mkdir(exist_ok=True)
        with zipfile.ZipFile(z) as zf:
            zf.extractall(d)
        names = sorted(p.name for p in d.iterdir() if p.is_file())
        print(f"  [ok] {len(names)} files: {names[:8]}")
        return True
    return False


# ==================================================================== main
def main():
    steps = [extract_osm, get_bag, get_cbs_regions, get_cbs_stats, get_ahn,
             get_srtm, get_gtfs]
    results = {}
    for s in steps:
        try:
            results[s.__name__] = bool(s())
        except Exception as e:
            import traceback
            traceback.print_exc()
            results[s.__name__] = False
    print("\n=== STEP RESULTS ===")
    for k, v in results.items():
        print(f"  {'OK  ' if v else 'FAIL'}  {k}")
    # inventory
    print("\n=== OUTPUT INVENTORY ===")
    for p in sorted(OUT.iterdir()):
        print(f"  {p.stat().st_size/1e6:9.2f} MB  {p.name}")


if __name__ == "__main__":
    main()
