#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rebuild the neighbourhood layer (CBS buurten + socio-economic indicators)
and a terrain-clipped demand sample."""
import os
from pathlib import Path

from osgeo import gdal, ogr

gdal.UseExceptions()
ogr.UseExceptions()

ROOT = Path("/mnt/c/Users/YE/Downloads/planx_nl_data") if os.name != "nt" \
    else Path(r"C:\Users\YE\Downloads\planx_nl_data")
OUT = ROOT / "out"


def sh(p):
    return str(p).replace("/", "\\") if os.name == "nt" else str(p)


INDICATORS = [
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
    ("dwellings", "aantalWoningen", ogr.OFTInteger),
]


def build_neighbourhoods():
    print("=== neighbourhoods (CBS buurten + indicators) ===")
    src = ogr.Open(sh(OUT / "cbs_buurten.gpkg"))
    lyr = src.GetLayer(0)
    defn = lyr.GetLayerDefn()
    nf = {defn.GetFieldDefn(i).GetName(): i for i in range(defn.GetFieldCount())}
    print("  source fields:", list(nf)[:8], "...")
    dest = OUT / "neighbourhoods.gpkg"
    if dest.exists():
        dest.unlink()
    drv = ogr.GetDriverByName("GPKG")
    out = drv.CreateDataSource(sh(dest))
    o_lyr = out.CreateLayer("neighbourhoods", srs=lyr.GetSpatialRef(),
                            geom_type=ogr.wkbMultiPolygon)
    for i in range(defn.GetFieldCount()):
        fd = defn.GetFieldDefn(i)
        o_lyr.CreateField(ogr.FieldDefn(fd.GetName(), fd.GetType()))
    for name, _k, typ in INDICATORS:
        o_lyr.CreateField(ogr.FieldDefn(name, typ))
    for extra in ("cbs_code", "cbs_name", "wijk", "buurt"):
        o_lyr.CreateField(ogr.FieldDefn(extra, ogr.OFTString))
    o_defn = o_lyr.GetLayerDefn()
    total = 0
    n = 0
    for feat in lyr:
        nf2 = ogr.Feature(o_defn)
        for i in range(defn.GetFieldCount()):
            nf2.SetField(i, feat.GetField(i))
        for name, key, _t in INDICATORS:
            if key in nf:
                v = feat.GetField(nf[key])
                if v is not None:
                    try:
                        nf2.SetField(name, int(v))
                    except (TypeError, ValueError):
                        try:
                            nf2.SetField(name, float(v))
                        except (TypeError, ValueError):
                            pass
        for src_f, dst_f in (("buurtcode", "cbs_code"), ("buurtnaam", "cbs_name"),
                             ("wijkcode", "wijk"), ("buurtnaam", "buurt")):
            if src_f in nf:
                nf2.SetField(dst_f, str(feat.GetField(nf[src_f]) or "").strip())
        if "population" in [x[0] for x in INDICATORS]:
            try:
                total += int(nf2.GetField("population") or 0)
            except (TypeError, ValueError):
                pass
        nf2.SetGeometry(feat.GetGeometryRef())
        o_lyr.CreateFeature(nf2)
        n += 1
    out = None
    src = None
    print(f"  [ok] neighbourhoods.gpkg: {n} neighbourhoods, "
          f"total population {total}")


def build_clipped_sample():
    """A demand sample clipped to the terrain, for the hazard tools."""
    print("=== demand sample clipped to the terrain ===")
    dem = OUT / "dem.tif"
    src = OUT / "demand_sample.gpkg"
    if not dem.exists() or not src.exists():
        print("  [FAIL] missing input")
        return
    ds = gdal.Open(sh(dem))
    gt = ds.GetGeoTransform()
    inset = 2 * abs(gt[1])          # keep two cells clear of the raster edge
    xmin = gt[0] + inset
    ymax = gt[3] - inset
    xmax = gt[0] + ds.RasterXSize * gt[1] - inset
    ymin = gt[3] + ds.RasterYSize * gt[5] + inset
    ds = None
    sds = ogr.Open(sh(src))
    lyr = sds.GetLayer(0)
    defn = lyr.GetLayerDefn()
    dest = OUT / "demand_terrain.gpkg"
    if dest.exists():
        dest.unlink()
    drv = ogr.GetDriverByName("GPKG")
    out = drv.CreateDataSource(sh(dest))
    o_lyr = out.CreateLayer("demand_terrain", srs=lyr.GetSpatialRef(),
                            geom_type=ogr.wkbPoint)
    for i in range(defn.GetFieldCount()):
        fd = defn.GetFieldDefn(i)
        o_lyr.CreateField(ogr.FieldDefn(fd.GetName(), fd.GetType()))
    o_defn = o_lyr.GetLayerDefn()
    kept = 0
    for feat in lyr:
        g = feat.GetGeometryRef()
        if g is None:
            continue
        c = g.Centroid()
        if not (xmin <= c.GetX() <= xmax and ymin <= c.GetY() <= ymax):
            continue
        rds = gdal.Open(sh(dem))
        rgt = rds.GetGeoTransform()
        px = int((c.GetX() - rgt[0]) / rgt[1])
        py = int((c.GetY() - rgt[3]) / rgt[5])
        if not (0 <= px < rds.RasterXSize and 0 <= py < rds.RasterYSize):
            rds = None
            continue
        val = rds.GetRasterBand(1).ReadAsArray(px, py, 1, 1)[0][0]
        rds = None
        if val <= -9000:
            continue
        nf2 = ogr.Feature(o_defn)
        for i in range(defn.GetFieldCount()):
            nf2.SetField(i, feat.GetField(i))
        nf2.SetGeometry(g)
        o_lyr.CreateFeature(nf2)
        kept += 1
    out = None
    sds = None
    print(f"  [ok] demand_terrain.gpkg: {kept} points inside the terrain")


if __name__ == "__main__":
    build_neighbourhoods()
    build_clipped_sample()
