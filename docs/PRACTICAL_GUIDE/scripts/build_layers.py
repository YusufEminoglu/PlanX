#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build the PlanX analysis layers for Utrecht from the downloaded open data.

  OSM (BBBike)      -> streets, land use, POI, facilities, green, water
  BAG (PDOK)        -> official building footprints with build year,
                        address points with the real resident count
  CBS (PDOK+StatLine) -> neighbourhood polygons with real socio-economic data
  AHN (PDOK)        -> 0.5 m DSM and DTM
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()

ROOT = Path("/mnt/c/Users/YE/Downloads/planx_nl_data") if os.name != "nt" \
    else Path(r"C:\Users\YE\Downloads\planx_nl_data")
OUT = ROOT / "out"
WORK = OUT / "work"
WORK.mkdir(parents=True, exist_ok=True)
RD = "EPSG:28992"
BBOX = (135206.6, 454196.8, 138361.3, 457368.2)
SPAT = ["5.0983", "52.0758", "5.1445", "52.1042"]


def sh(p):
    return str(p).replace("/", "\\") if os.name == "nt" else str(p)


def ogr_run(cmd, timeout=1800):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode and r.stderr:
        print("    !", r.stderr.strip().splitlines()[-1][:150])
    return r.returncode == 0


def count(path, layer=None):
    try:
        ds = ogr.Open(sh(path))
        lyr = ds.GetLayerByName(layer) if layer else ds.GetLayer(0)
        n = lyr.GetFeatureCount()
        ds = None
        return n
    except Exception:
        return -1


# ======================================================== 1. OSM extraction
def extract_osm():
    print("\n=== OSM extraction (BBBike Utrecht PBF) ===")
    pbf = ROOT / "raw" / "utrecht.osm.pbf"
    for layer, tag in (("lines", "osm_lines"), ("points", "osm_points"),
                       ("multipolygons", "osm_polys")):
        dst = OUT / f"{tag}.gpkg"
        if dst.exists():
            print(f"  [skip] {tag}.gpkg ({count(dst)} features)")
            continue
        ogr_run(["ogr2ogr", "-f", "GPKG", sh(dst), sh(pbf), layer,
                 "-spat"] + SPAT + ["-nln", tag,
                 "--config", "OSM_USE_CURVE", "NO", "-skipfailures"])
        print(f"  [{'ok' if dst.exists() else 'FAIL'}] {tag}.gpkg "
              f"-> {count(dst)} features")


# ================================================= 2. OSM -> thematic layers
def osm_to_thematic():
    print("\n=== OSM -> thematic layers ===")
    lines = OUT / "osm_lines.gpkg"
    points = OUT / "osm_points.gpkg"
    polys = OUT / "osm_polys.gpkg"

    # ---- streets: routable highway network
    dest = OUT / "streets.gpkg"
    if not dest.exists() and lines.exists():
        ogr_run(["ogr2ogr", "-f", "GPKG", sh(dest), sh(lines),
                 "-where", "highway IN ('motorway','motorway_link','trunk','trunk_link',"
                 "'primary','primary_link','secondary','secondary_link','tertiary',"
                 "'tertiary_link','residential','unclassified','living_street',"
                 "'service','pedestrian','footway','path','cycleway','steps')",
                 "-nln", "streets", "-skipfailures"])
    print(f"  streets.gpkg -> {count(dest)} features")

    # ---- land use polygons
    dest = OUT / "landuse.gpkg"
    if not dest.exists() and polys.exists():
        ogr_run(["ogr2ogr", "-f", "GPKG", sh(dest), sh(polys),
                 "-where", "landuse IS NOT NULL OR building IS NOT NULL "
                 "OR (natural IN ('water','wood','scrub','wetland','grassland'))",
                 "-nln", "landuse", "-skipfailures"])
    print(f"  landuse.gpkg -> {count(dest)} features")

    # ---- green space
    dest = OUT / "green.gpkg"
    if not dest.exists() and polys.exists():
        ogr_run(["ogr2ogr", "-f", "GPKG", sh(dest), sh(polys),
                 "-where", "leisure IN ('park','garden','pitch','playground',"
                 "'golf_course','nature_reserve','dog_park','recreation_ground') "
                 "OR landuse IN ('forest','grass','village_green','meadow',"
                 "'recreation_ground','cemetery','allotments')",
                 "-nln", "green", "-skipfailures"])
    print(f"  green.gpkg -> {count(dest)} features")

    # ---- water
    dest = OUT / "water.gpkg"
    if not dest.exists() and polys.exists():
        ogr_run(["ogr2ogr", "-f", "GPKG", sh(dest), sh(polys),
                 "-where", "natural='water' OR waterway IS NOT NULL "
                 "OR landuse='reservoir'",
                 "-nln", "water", "-skipfailures"])
    print(f"  water.gpkg -> {count(dest)} features")

    # ---- POI points
    dest = OUT / "pois.gpkg"
    if not dest.exists() and points.exists():
        ogr_run(["ogr2ogr", "-f", "GPKG", sh(dest), sh(points),
                 "-where", "amenity IS NOT NULL OR shop IS NOT NULL "
                 "OR leisure IS NOT NULL OR tourism IS NOT NULL "
                 "OR healthcare IS NOT NULL OR historic IS NOT NULL",
                 "-nln", "pois", "-skipfailures"])
    print(f"  pois.gpkg -> {count(dest)} features")

    # ---- facilities: the public/educational/care anchors
    dest = OUT / "facilities.gpkg"
    if not dest.exists() and points.exists():
        ogr_run(["ogr2ogr", "-f", "GPKG", sh(dest), sh(points),
                 "-where", "amenity IN ('school','university','college','kindergarten',"
                 "'library','hospital','clinic','doctors','pharmacy','marketplace',"
                 "'community_centre','townhall','place_of_worship','police',"
                 "'fire_station','post_office','veterinary','sports_centre') "
                 "OR healthcare IN ('hospital','clinic','doctors') "
                 "OR amenity='bus_station' OR railway='station' "
                 "OR public_transport='station'",
                 "-nln", "facilities", "-skipfailures"])
    print(f"  facilities.gpkg -> {count(dest)} features")


# ================================================== 3. BAG -> buildings etc.
def bag_to_layers():
    print("\n=== BAG -> buildings / demand points ===")
    pand = OUT / "bag_pand.gpkg"
    adres = OUT / "bag_adres.gpkg"

    # official building footprints with build year
    dest = OUT / "buildings.gpkg"
    if not dest.exists() and pand.exists():
        ogr_run(["ogr2ogr", "-f", "GPKG", sh(dest), sh(pand),
                 "-nln", "buildings", "-lco", "GEOMETRY_NAME=geom"])
    print(f"  buildings.gpkg -> {count(dest)} features")

    # address points = real demand points (BAG residents per address)
    dest = OUT / "demand.gpkg"
    if not dest.exists() and adres.exists():
        ogr_run(["ogr2ogr", "-f", "GPKG", sh(dest), sh(adres),
                 "-nln", "demand", "-lco", "GEOMETRY_NAME=geom"])
    print(f"  demand.gpkg -> {count(dest)} features")


# ==================================== 4. OSM buildings with height (for DSM check)
def osm_buildings():
    print("\n=== OSM buildings (heights / build year) ===")
    polys = OUT / "osm_polys.gpkg"
    dest = OUT / "buildings_osm.gpkg"
    if not dest.exists() and polys.exists():
        ogr_run(["ogr2ogr", "-f", "GPKG", sh(dest), sh(polys),
                 "-where", "building IS NOT NULL",
                 "-nln", "buildings_osm"])
    print(f"  buildings_osm.gpkg -> {count(dest)} features")
    if dest.exists():
        ds = ogr.Open(sh(dest))
        lyr = ds.GetLayer(0)
        flds = [lyr.GetLayerDefn().GetFieldDefn(i).GetName()
                for i in range(lyr.GetLayerDefn().GetFieldCount())]
        for f in ("height", "building:levels", "start_date", "building"):
            if f in flds:
                print(f"    has '{f}'")
        ds = None


# ================================= 5. CBS neighbourhoods + socio-economic data
def cbs_neighbourhoods():
    print("\n=== CBS neighbourhoods + socio-economic data ===")
    buurten = OUT / "cbs_buurten.gpkg"
    wijken = OUT / "cbs_wijken.gpkg"
    stats_path = OUT / "cbs_kerncijfers.json"

    if not stats_path.exists():
        print("  [FAIL] cbs_kerncijfers.json missing")
        return
    with open(stats_path, encoding="utf-8") as f:
        stats = json.load(f)
    rows = {r["Codering_3"].strip(): r for r in stats["rows"]}

    # join the CBS indicators onto the buurt polygons
    dest = OUT / "neighbourhoods.gpkg"
    if dest.exists():
        dest.unlink()
    if not buurten.exists():
        print("  [FAIL] cbs_buurten.gpkg missing")
        return
    src = ogr.Open(sh(buurten))
    s_lyr = src.GetLayer(0)
    s_defn = s_lyr.GetLayerDefn()
    srs = s_lyr.GetSpatialRef()

    drv = ogr.GetDriverByName("GPKG")
    out = drv.CreateDataSource(sh(dest))
    o_lyr = out.CreateLayer("neighbourhoods", srs=srs, geom_type=ogr.wkbMultiPolygon)
    # copy source fields
    for i in range(s_defn.GetFieldCount()):
        fd = s_defn.GetFieldDefn(i)
        o_lyr.CreateField(ogr.FieldDefn(fd.GetName(), fd.GetType()))
    # CBS indicator fields: the PDOK wijk/buurt layer already carries the
    # official CBS indicators; add English aliases for the PlanX tools
    indicators = [
        ("population", "aantalInwoners", ogr.OFTInteger),
        ("male", "mannen", ogr.OFTInteger),
        ("female", "vrouwen", ogr.OFTInteger),
        ("pct_age_0_15", "percentagePersonen0Tot15Jaar", ogr.OFTInteger),
        ("pct_age_15_25", "percentagePersonen15Tot25Jaar", ogr.OFTInteger),
        ("pct_age_25_45", "percentagePersonen25Tot45Jaar", ogr.OFTInteger),
        ("pct_age_45_65", "percentagePersonen45Tot65Jaar", ogr.OFTInteger),
        ("pct_age_65_plus", "percentagePersonen65JaarEnOuder", ogr.OFTInteger),
        ("households", "aantalHuishoudens", ogr.OFTInteger),
        ("avg_hh_size", "gemiddeldeHuishoudsgrootte", ogr.OFTReal),
        ("area_ha", "oppervlakteTotaalInHa", ogr.OFTInteger),
        ("pop_density_km2", "bevolkingsdichtheidInwonersPerKm2", ogr.OFTInteger),
        ("urbanity_addr_km2", "stedelijkheidAdressenPerKm2", ogr.OFTInteger),
        ("pct_nl_origin", "percentageMetHerkomstlandNederland", ogr.OFTInteger),
        ("pct_eu_origin", "percentageMetHerkomstlandUitEuropaExclNl", ogr.OFTInteger),
        ("pct_non_eu_origin", "percentageMetHerkomstlandBuitenEuropa", ogr.OFTInteger),
    ]
    for name, _key, typ in indicators:
        o_lyr.CreateField(ogr.FieldDefn(name, typ))
    o_lyr.CreateField(ogr.FieldDefn("cbs_code", ogr.OFTString))
    o_lyr.CreateField(ogr.FieldDefn("cbs_name", ogr.OFTString))
    o_lyr.CreateField(ogr.FieldDefn("wijk", ogr.OFTString))
    o_lyr.CreateField(ogr.FieldDefn("buurt", ogr.OFTString))

    src_fields = {s_defn.GetFieldDefn(i).GetName().lower(): i
                  for i in range(s_defn.GetFieldCount())}

    o_defn = o_lyr.GetLayerDefn()
    joined = 0
    for feat in s_lyr:
        code = ""
        for cand in ("buurtcode", "wijkcode", "codering"):
            if cand in src_fields:
                code = str(feat.GetField(src_fields[cand])).strip()
                break
        nf = ogr.Feature(o_defn)
        for i in range(s_defn.GetFieldCount()):
            nf.SetField(i, feat.GetField(i))
        # alias the CBS indicators
        for name, key, _t in indicators:
            if key in src_fields:
                v = feat.GetField(src_fields[key])
                if v is not None:
                    try:
                        nf.SetField(name, int(v))
                    except (TypeError, ValueError):
                        try:
                            nf.SetField(name, float(v))
                        except (TypeError, ValueError):
                            pass
        if "buurtcode" in src_fields:
            nf.SetField("cbs_code", str(feat.GetField(src_fields["buurtcode"])).strip())
        if "buurtnaam" in src_fields:
            nf.SetField("cbs_name", str(feat.GetField(src_fields["buurtnaam"])).strip())
        if "wijkcode" in src_fields:
            nf.SetField("wijk", str(feat.GetField(src_fields["wijkcode"])).strip())
        if "buurtnaam" in src_fields:
            nf.SetField("buurt", str(feat.GetField(src_fields["buurtnaam"])).strip())
        if code:
            joined += 1
        nf.SetGeometry(feat.GetGeometryRef())
        o_lyr.CreateFeature(nf)
    out = None
    src = None
    print(f"  neighbourhoods.gpkg -> {count(dest)} features "
          f"({joined} joined with CBS kerncijfers)")
    print(f"  wijken.gpkg -> {count(wijken)} features")


# ============================================== 6. AHN rasters -> DEM / DSM
def build_rasters():
    print("\n=== AHN -> DEM / DSM (1 m, clipped) ===")
    for src_name, dst_name in (("ahn_dsm", "dsm"), ("ahn_dtm", "dem")):
        src = OUT / f"{src_name}_crop.tif"
        dst = OUT / f"{dst_name}.tif"
        if not src.exists():
            print(f"  [FAIL] {src.name} missing")
            continue
        if dst.exists():
            dst.unlink()
        ogr_run(["gdalwarp", "-t_srs", RD,
                 "-te", str(BBOX[0]), str(BBOX[1]), str(BBOX[2]), str(BBOX[3]),
                 "-tr", "1", "1", "-r", "bilinear", "-of", "GTiff",
                 "-co", "COMPRESS=DEFLATE", "-co", "TILED=YES",
                 "-srcnodata", "3.4028234663852886e+38", "-dstnodata", "-9999",
                 sh(src), sh(dst)])
        if dst.exists():
            ds = gdal.Open(sh(dst))
            b = ds.GetRasterBand(1)
            b.SetNoDataValue(-9999)
            st = b.ComputeStatistics(False)
            ds = None
            print(f"  {dst_name}.tif {count_raster(dst)} "
                  f"elev {st[0]:.1f}..{st[2]:.1f} m (avg {st[1]:.1f})")


def count_raster(p):
    ds = gdal.Open(sh(p))
    r = f"{ds.RasterXSize}x{ds.RasterYSize}"
    ds = None
    return r


if __name__ == "__main__":
    extract_osm()
    osm_to_thematic()
    bag_to_layers()
    osm_buildings()
    cbs_neighbourhoods()
    build_rasters()
    print("\n=== FINAL INVENTORY ===")
    for p in sorted(OUT.glob("*.gpkg")):
        print(f"  {count(p):8d}  {p.name}")
    for p in sorted(OUT.glob("*.tif")):
        print(f"  {count_raster(p):>10s}  {p.name}")
