r"""
PlanX Practical Guide Runner - REAL DATA (Utrecht, Netherlands).

Runs every PlanX algorithm on real open data:
  OSM (BBBike)  |  BAG (PDOK)  |  CBS (PDOK + StatLine)  |  AHN (PDOK)  |  GTFS (ovapi.nl)

    C:\OSGeo4W\bin\python-qgis-ltr.bat practical_guide_runner_real.py --all
"""
import sys
import os
import json
import time
import shutil
import traceback
from pathlib import Path

for _p in (r'C:\OSGeo4W\apps\qgis-ltr\python\plugins',
           r'C:\OSGeo4W\apps\qgis\python\plugins'):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.append(_p)

from qgis.core import (
    QgsApplication, Qgis, QgsProject, QgsMapSettings, QgsMapRendererParallelJob,
    QgsRectangle, QgsVectorLayer, QgsRasterLayer, QgsGraduatedSymbolRenderer,
    QgsRendererRange, QgsSymbol, QgsFillSymbol, QgsLineSymbol, QgsMarkerSymbol,
    QgsCategorizedSymbolRenderer, QgsRendererCategory, QgsSingleSymbolRenderer,
    QgsSingleBandPseudoColorRenderer, QgsColorRampShader, QgsRasterShader,
    QgsStyle, QgsProcessingFeedback, QgsProcessingContext,
    QgsProcessingParameterFeatureSource, QgsProcessingParameterField,
    QgsProcessingParameterEnum, QgsProcessingParameterNumber,
    QgsProcessingParameterBoolean, QgsProcessingParameterString,
    QgsProcessingParameterExtent, QgsProcessingParameterCrs,
    QgsProcessingParameterFile, QgsProcessingParameterFeatureSink,
    QgsProcessingParameterRasterDestination, QgsProcessingParameterVectorDestination,
    QgsProcessingParameterFileDestination, QgsCoordinateReferenceSystem,
)
from qgis.PyQt.QtGui import QImage, QPainter, QColor, QFont, QPen
from qgis.PyQt.QtCore import QSize, QRectF, Qt

GUIDE_DIR = Path(__file__).resolve().parent
SHOT_DIR = GUIDE_DIR / "screenshots"
MANIFEST_DIR = GUIDE_DIR / "manifest"
WORK_DIR = GUIDE_DIR / "work_utrecht"
PLUGIN_ROOT = GUIDE_DIR.parent.parent.parent

if os.name == "nt":
    DATA = Path(r"C:\Users\YE\Downloads\planx_nl_data\out")
    GTFS_DIR = Path(r"C:\Users\YE\Downloads\planx_nl_data\gtfs")
else:
    DATA = Path("/mnt/c/Users/YE/Downloads/planx_nl_data/out")
    GTFS_DIR = Path("/mnt/c/Users/YE/Downloads/planx_nl_data/gtfs")

for _d in (SHOT_DIR, MANIFEST_DIR):
    _d.mkdir(parents=True, exist_ok=True)
if WORK_DIR.exists():
    shutil.rmtree(WORK_DIR, ignore_errors=True)
WORK_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(PLUGIN_ROOT))

QGS_APP = QgsApplication([], False)
QgsApplication.initQgis()
print(f"[OK] QGIS {Qgis.QGIS_VERSION}", flush=True)

import processing  # noqa: E402
from planx.provider import PlanXProvider  # noqa: E402

_provider = PlanXProvider()
QgsApplication.processingRegistry().addProvider(_provider)
ALGOS = {a.id().split(':')[-1]: a for a in _provider.algorithms()}
print(f"[OK] PlanX provider: {len(ALGOS)} algorithms", flush=True)
try:
    from processing.core.Processing import Processing
    Processing.initialize()
    if "native" not in QgsApplication.processingRegistry().providers():
        from qgis.analysis import QgsNativeAlgorithms
        QgsApplication.processingRegistry().addProvider(QgsNativeAlgorithms())
except Exception:
    pass

FEEDBACK = QgsProcessingFeedback()
CONTEXT = QgsProcessingContext()
PROJECT = QgsProject.instance()
PROJECT.setCrs(QgsCoordinateReferenceSystem("EPSG:28992"))

RAMP = ["#1a9850", "#91cf60", "#fee08b", "#fc8d59", "#d73027",
        "#4575b4", "#74add1", "#7b3294", "#c51b7d", "#7b3294"]


def sh(p):
    return str(p).replace("/", "\\") if os.name == "nt" else str(p)


def run(algo_id, params, outs=None):
    p = dict(params)
    if outs:
        p.update(outs)
    try:
        return processing.run(f"planx:{algo_id}", p, context=CONTEXT, feedback=FEEDBACK)
    except Exception as e:
        print(f"      [FAIL] {algo_id}: {str(e).replace(chr(10), ' ')[:190]}", flush=True)
        return None


def load_layer(path, name):
    if not path or not os.path.exists(str(path)):
        return None
    if str(path).lower().endswith(".tif"):
        lyr = QgsRasterLayer(str(path), name)
    else:
        lyr = QgsVectorLayer(str(path), name, "ogr")
    return lyr if lyr.isValid() else None


# ============================================================ real data set
class Data:
    streets = DATA / "streets.gpkg"
    buildings = DATA / "buildings.gpkg"
    landuse = DATA / "landuse.gpkg"
    pois = DATA / "pois.gpkg"
    facilities = DATA / "facilities.gpkg"
    green = DATA / "green.gpkg"
    green_patches = DATA / "green_patches.gpkg"
    water = DATA / "water.gpkg"
    demand = DATA / "demand.gpkg"
    nb = DATA / "neighbourhoods.gpkg"
    pc = DATA / "postcode_pop.gpkg"
    parcels = DATA / "parcels.gpkg"
    demand_terrain = DATA / "demand_terrain.gpkg"
    zones = DATA / "zones.gpkg"
    demand_ac = DATA / "demand_ac.gpkg"
    demand_s = DATA / "demand_sample.gpkg"
    demand_od = DATA / "demand_od.gpkg"
    demand_rt = DATA / "demand_routes.gpkg"
    dem = DATA / "dem.tif"
    dsm = DATA / "dsm.tif"
    dem5 = DATA / "dem5.tif"
    dsm5 = DATA / "dsm5.tif"
    lc2010 = DATA / "landcover_2010.tif"
    lc2017 = DATA / "landcover_2017.tif"
    urb2010 = DATA / "urban_2010.tif"
    urb2017 = DATA / "urban_2017.tif"
    gtfs = GTFS_DIR / "gtfs-nl.zip"


D = Data


def _mk_symbol(layer, color):
    try:
        t = layer.geometryType()
        if t == 0:
            return QgsMarkerSymbol.createSimple(
                {"name": "circle", "color": color.name(), "outline_color": "#1a1a1a",
                 "outline_width": "0.15", "size": "1.8"})
        if t == 1:
            return QgsLineSymbol.createSimple(
                {"color": color.name(), "width": "0.5", "capstyle": "round"})
        return QgsFillSymbol.createSimple(
            {"color": color.name(), "outline_color": "#333333", "outline_width": "0.1"})
    except Exception:
        return QgsSymbol.defaultSymbol(layer.geometryType())


def _style_vector(layer):
    if not isinstance(layer, QgsVectorLayer):
        return
    try:
        fields = [f for f in layer.fields()
                  if f.name().lower() not in ("fid", "geom", "geometry")]
        if not fields:
            layer.setRenderer(QgsSingleSymbolRenderer(_mk_symbol(layer, QColor("#4fc3f7"))))
            return
        num_field = None
        for cand in ("value", "score", "walk_score", "access_score", "index",
                     "cost", "length", "area", "dist", "distance", "time",
                     "minutes", "pga", "gi", "lts", "hierarchy", "class",
                     "level", "rank", "count", "share", "pct", "ratio",
                     "intensity", "height_m", "h", "band", "depth", "n",
                     "total", "pop", "population", "value_m"):
            for f in fields:
                if f.name().lower() == cand:
                    num_field = f
                    break
            if num_field:
                break
        if num_field is None:
            for f in fields:
                if f.isNumeric():
                    num_field = f
                    break
        if num_field is None:
            for f in fields:
                if f.typeName().lower() in ("string", "text"):
                    vals = set()
                    for feat in layer.getFeatures():
                        vals.add(str(feat[f.name()]))
                        if len(vals) > 8:
                            break
                    if 1 < len(vals) <= 8:
                        cats = [QgsRendererCategory(
                            v, _mk_symbol(layer, QColor(RAMP[i % len(RAMP)])), v)
                            for i, v in enumerate(sorted(vals))]
                        layer.setRenderer(QgsCategorizedSymbolRenderer(f.name(), cats))
                    else:
                        layer.setRenderer(QgsSingleSymbolRenderer(
                            _mk_symbol(layer, QColor("#4fc3f7"))))
                    return
            layer.setRenderer(QgsSingleSymbolRenderer(_mk_symbol(layer, QColor("#4fc3f7"))))
            return
        vals = []
        for feat in layer.getFeatures():
            v = feat[num_field.name()]
            try:
                if v is not None and v != "":
                    vals.append(float(v))
            except (TypeError, ValueError):
                continue
        if not vals:
            layer.setRenderer(QgsSingleSymbolRenderer(_mk_symbol(layer, QColor("#4fc3f7"))))
            return
        vmin, vmax = min(vals), max(vals)
        if vmax == vmin:
            vmax = vmin + 1.0
        ranges = [QgsRendererRange(
            vmin + (vmax - vmin) * i / 5, vmin + (vmax - vmin) * (i + 1) / 5,
            _mk_symbol(layer, QColor(RAMP[i % len(RAMP)])),
            f"{vmin + (vmax-vmin)*i/5:.2f} - {vmin + (vmax-vmin)*(i+1)/5:.2f}")
            for i in range(5)]
        layer.setRenderer(QgsGraduatedSymbolRenderer(num_field.name(), ranges))
    except Exception:
        pass


def _style_raster(layer):
    if not isinstance(layer, QgsRasterLayer):
        return
    try:
        prov = layer.dataProvider()
        st = prov.bandStatistics(1)
        if st.minimumValue == st.maximumValue:
            return
        fn = QgsColorRampShader()
        fn.setColorRampType(QgsColorRampShader.Interpolated)
        ramp = QgsStyle.defaultStyle().colorRamp("Viridis")
        fn.setColorRampItemList([
            QgsColorRampShader.ColorRampItem(
                st.minimumValue + (st.maximumValue - st.minimumValue) * i / 9.0,
                ramp.color(i / 9.0), "")
            for i in range(10)])
        shader = QgsRasterShader()
        shader.setRasterShaderFunction(fn)
        layer.setRenderer(QgsSingleBandPseudoColorRenderer(prov, 1, shader))
    except Exception:
        pass


def _render(layers, extent, size):
    s = QgsMapSettings()
    s.setLayers([lay for lay in layers if lay is not None and lay.isValid()])
    s.setExtent(extent)
    s.setOutputSize(size)
    s.setBackgroundColor(QColor("#ffffff"))
    try:
        s.setDestinationCrs(layers[0].crs())
    except Exception:
        pass
    job = QgsMapRendererParallelJob(s)
    job.start()
    job.waitForFinished()
    return job.renderedImage()


def _panel_label(p, x, y, w, text, sub=""):
    p.fillRect(QRectF(x, y, w, 34), QColor(19, 160, 160, 240))
    p.setPen(QColor("#ffffff"))
    p.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
    p.drawText(QRectF(x + 10, y + 4, w - 20, 26), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
    if sub:
        p.setPen(QColor("#0d3b3b"))
        p.setFont(QFont("Segoe UI", 8))
        p.fillRect(QRectF(x, y + 34, w, 19), QColor(255, 255, 255, 228))
        p.drawText(QRectF(x + 10, y + 34, w - 20, 19), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, sub)


def capture_4panel(algo_id, display, in_layers, out_layers, param_text, out_png):
    PW, PH, HDR = 900, 620, 30
    img = QImage(QSize(PW * 2, PH * 2 + HDR), QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("#ffffff"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)

    all_l = [lay for lay in (in_layers + out_layers) if lay is not None and lay.isValid()]
    extent = None
    for lay in all_l:
        e = lay.extent()
        if e.isEmpty():
            continue
        extent = QgsRectangle(e) if extent is None else extent
        extent.combineExtentWith(e)
    if extent is None or extent.isEmpty():
        extent = QgsRectangle(135206, 454196, 138361, 457368)
    else:
        extent.scale(1.06)

    def draw(x, y, layers, label, sub):
        if not layers:
            p.fillRect(QRectF(x, y, PW, PH), QColor("#f4f6f6"))
            p.setPen(QColor("#99a5a5"))
            p.setFont(QFont("Segoe UI", 13))
            p.drawText(QRectF(x, y, PW, PH), Qt.AlignmentFlag.AlignCenter, "no layer for this panel")
        else:
            im = _render(layers, extent, QSize(PW, PH))
            if not im.isNull():
                p.drawImage(x, y, im)
        _panel_label(p, x, y, PW, label, sub)

    draw(0, HDR, in_layers, "1 - INPUT DATA", "real source layers")
    draw(PW, HDR, out_layers, "3 - OUTPUT (RAW)", "un-styled result")

    styled = []
    for lay in out_layers:
        if lay is None or not lay.isValid():
            continue
        if isinstance(lay, QgsVectorLayer):
            try:
                lay.renderer().setOpacity(0.9)
            except Exception:
                pass
            _style_vector(lay)
        else:
            _style_raster(lay)
        styled.append(lay)
    draw(0, HDR + PH, styled, "4 - OUTPUT (STYLED)", "graduated / categorized")
    draw(PW, HDR + PH, out_layers, "2 - PARAMETERS", "values used in this run")

    p.save()
    p.setClipRect(QRectF(PW, HDR, PW, PH))
    p.fillRect(QRectF(PW + 26, HDR + 46, PW - 52, PH - 88), QColor(255, 255, 255, 244))
    p.setPen(QPen(QColor("#13a0a0"), 1.4))
    p.drawRect(QRectF(PW + 26, HDR + 46, PW - 52, PH - 88))
    p.setPen(QColor("#1a1a1a"))
    p.setFont(QFont("Consolas", 7))
    y0 = HDR + 60
    for line in param_text.splitlines()[:38]:
        p.drawText(int(PW + 34), int(y0), line)
        y0 += 10.5
    p.restore()

    p.fillRect(QRectF(0, 0, PW * 2, HDR), QColor("#0d2a2a"))
    p.setPen(QColor("#7fe3e3"))
    p.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
    p.drawText(12, 21, f"PlanX - {display}  ({algo_id})")
    p.setPen(QColor("#9fd6d6"))
    p.setFont(QFont("Segoe UI", 8))
    p.drawText(PW + 12, 21,
               "Real QGIS run on open data - Utrecht NL - PlanX engine only")
    p.end()
    img.save(out_png, "PNG")
    return os.path.exists(str(out_png))


def _fmt(params):
    out = []
    for k, v in params.items():
        if v in (None, ""):
            continue
        sv = str(v)
        if len(sv) > 46:
            sv = sv[:43] + "..."
        out.append(f"{k} = {sv}")
    return "\n".join(out)


# ================================================================ params
def build_setup(aid):
    P = {}
    inp = []

    def use(*keys):
        for k in keys:
            if k not in inp:
                inp.append(k)

    S = sh(D.streets)
    B = sh(D.buildings)
    L = sh(D.landuse)
    PO = sh(D.pois)
    FA = sh(D.facilities)
    GR = sh(D.green_patches)
    WA = sh(D.water)
    DM = sh(D.demand)
    DMS = sh(D.demand_s)
    DMO = sh(D.demand_od)
    DMR = sh(D.demand_rt)
    NB = sh(D.nb)
    PC = sh(D.parcels)
    DEM = sh(D.dem)
    DSM = sh(D.dsm)
    DEM5 = sh(D.dem5)
    DSM5 = sh(D.dsm5)

    if aid == 'democity':
        return None, []
    elif aid == 'preparenetwork':
        P = {'INPUT': S, 'MIN_LENGTH': 1.0, 'CREATE_INDEX': True}
        use('streets')
    elif aid == 'odmatrix':
        # the straight desire-line layer would be ~1.3 GB for 600 x 944 pairs,
        # so it is switched off here - the cost matrix table is the real output
        P = {'NETWORK': S, 'ORIGINS': DMO, 'DESTINATIONS': FA, 'LINES': None}
        use('streets', 'demand', 'facilities')
    elif aid == 'odroutes':
        P = {'NETWORK': S, 'ORIGINS': DMR, 'DESTINATIONS': FA,
             'K_NEAREST': 1, 'OUT_LINES': None}
        use('streets', 'demand', 'facilities')
    elif aid == 'serviceareas':
        P = {'NETWORK': S, 'FACILITIES': FA, 'BREAKS': '250, 500, 1000',
             'METHOD': 0, 'BUFFER': 30.0, 'RINGS': False}
        use('streets', 'facilities')
    elif aid == 'nearestfacility':
        P = {'NETWORK': S, 'DEMAND': DMS, 'FACILITIES': FA}
        use('streets', 'demand', 'facilities')
    elif aid == 'linkcriticality':
        P = {'NETWORK': S, 'ORIGINS': DMO, 'DESTINATIONS': FA}
        use('streets', 'demand', 'facilities')
    elif aid == 'deadends':
        P = {'NETWORK': S, 'MIN_BRANCH': 10.0}
        use('streets')
    elif aid == 'networkcentrality':
        P = {'NETWORK': S}
        use('streets')
    elif aid == 'spacesyntax':
        P = {'NETWORK': S, 'RADII': '400, 800, 1600, n'}
        use('streets')
    elif aid == 'buildingmetrics':
        P = {'BUILDINGS': B}
        use('buildings')
    elif aid == 'tessellation':
        P = {'BUILDINGS': B, 'STUDY_AREA': L, 'DENSIFY': 5.0}
        use('buildings', 'landuse')
    elif aid == 'spacematrix':
        P = {'BUILDINGS': B, 'BLOCKS': L}
        use('buildings', 'landuse')
    elif aid == 'streetmorphology':
        P = {'NETWORK': S}
        use('streets')
    elif aid == 'accessscore':
        P = {'ORIGINS': DM, 'NETWORK': S, 'AMENITIES': PO,
             'SPEED': 5.0, 'THRESHOLD': 15.0}
        use('demand', 'streets', 'pois')
    elif aid == 'shadowcasting':
        P = {'DSM': DSM5, 'WHEN': '2024-06-21T12:00:00', 'UTC_OFFSET': 2}
        use('dsm')
    elif aid == 'skyviewfactor':
        P = {'DSM': DSM5, 'DIRECTIONS': 16, 'RADIUS': 120.0}
        use('dsm')
    elif aid == 'frontalarea':
        P = {'BUILDINGS': B, 'DEFAULT_HEIGHT': 12.0, 'CELL_SIZE': 20.0}
        use('buildings')
    elif aid == 'sunhours':
        P = {'DSM': DSM5, 'DATE': '2024-06-21', 'UTC_OFFSET': 2, 'INTERVAL': 30}
        use('dsm')
    elif aid == 'solarirradiation':
        P = {'DSM': DSM5, 'DATE': '2024-06-21', 'UTC_OFFSET': 2, 'INTERVAL': 30,
             'USE_SVF': True}
        use('dsm')
    elif aid == 'annualsolar':
        P = {'DSM': DSM5, 'YEAR': 2024, 'UTC_OFFSET': 2, 'INTERVAL': 60,
             'USE_SVF': True}
        use('dsm')
    elif aid == 'heatriskgrid':
        P = {'BUILDINGS': B, 'DEFAULT_HEIGHT': 12.0, 'GREEN': GR, 'CELL_SIZE': 30.0}
        use('buildings', 'green')
    elif aid == 'noisescreen':
        P = {'ROADS': S, 'BUILDINGS': B, 'RECEIVERS': DMO,
             'CELL': 60.0, 'CUTOFF': 300.0}
        use('streets', 'buildings', 'demand')
    elif aid == 'roademissions':
        P = {'ROADS': S, 'EF_GKM': 0.1}
        use('streets')
    elif aid == 'airscreen':
        P = {'ROADS': sh(WORK_DIR / "roademissions__OUTPUT.gpkg"),
             'BUILDINGS': B, 'RECEIVERS': DMO, 'CELL': 80.0, 'CUTOFF': 400.0}
        use('streets', 'buildings', 'demand')
    elif aid == 'landusebalance':
        P = {'LANDUSE': L, 'POPULATION': DM}
        use('landuse', 'demand')
    elif aid == 'facilityadequacy':
        P = {'NETWORK': S, 'DEMAND': DMS, 'FACILITIES': FA, 'MAX_COST': 800.0}
        use('streets', 'demand', 'facilities')
    elif aid == 'densitygrid':
        P = {'INPUT': B, 'CELL_SIZE': 50.0}
        use('buildings')
    elif aid == 'performancereport':
        P = {'TITLE': 'Utrecht Historic Centre - Plan Performance Report',
             'ACCESS': sh(WORK_DIR / "accessscore__OUTPUT.gpkg"),
             'ACCESS_SCORE': 'score',
             'BALANCE': sh(WORK_DIR / "landusebalance__OUTPUT.gpkg"),
             'FACILITIES': sh(WORK_DIR / "facilityadequacy__OUT_FACILITIES.gpkg"),
             'DEMAND': DM, 'DEMAND_POP': 'pop',
             'DENSITY': sh(WORK_DIR / "densitygrid__OUTPUT.gpkg")}
    elif aid == 'scenariosnapshot':
        P = {'NAME': 'Utrecht Baseline',
             'ACCESS': sh(WORK_DIR / "accessscore__OUTPUT.gpkg"),
             'BALANCE': sh(WORK_DIR / "landusebalance__OUTPUT.gpkg"),
             'FACILITIES': sh(WORK_DIR / "facilityadequacy__OUT_FACILITIES.gpkg"),
             'DEMAND': DM,
             'DENSITY': sh(WORK_DIR / "densitygrid__OUTPUT.gpkg")}
    elif aid == 'scenariocompare':
        P = {'SNAPSHOT_A': sh(WORK_DIR / "snapA.json"),
             'SNAPSHOT_B': sh(WORK_DIR / "snapB.json")}
    elif aid == 'scenariorank':
        P = {'FILES': '', 'FOLDER': sh(WORK_DIR / "snapshots"), 'SIMULATIONS': 20}
    elif aid == 'planaudit':
        P = {'NAME': 'Utrecht Historic Centre Audit', 'NETWORK': S, 'DEMAND': DM,
             'AMENITIES': PO, 'THRESHOLD': 15.0, 'LANDUSE': L, 'FACILITIES': FA,
             'GREENS': GR}
        use('streets', 'demand', 'pois', 'landuse', 'facilities', 'green')
    elif aid == 'scenariopipeline':
        P = {'NAME': 'Utrecht LUTI Pipeline', 'SEED': sh(D.urb2010),
             'SUITABILITY': sh(D.lc2010), 'CONSTRAINTS': '',
             'DEMAND_HA': 40.0, 'ITERATIONS': 8, 'RNG_SEED': 42,
             'POP_GROWTH': 5000.0, 'DEMAND': DM, 'NETWORK': S, 'AMENITIES': PO,
             'THRESHOLD': 15.0, 'LANDUSE': L}
        use('streets', 'demand', 'pois', 'landuse')
    elif aid == 'facilitylocation':
        P = {'NETWORK': S, 'DEMAND': DM, 'CANDIDATES': FA,
             'METHOD': 0, 'P': 3, 'RADIUS': 600.0}
        use('streets', 'demand', 'facilities')
    elif aid == 'capacitatedallocation':
        P = {'NETWORK': S, 'DEMAND': DM, 'FACILITIES': FA, 'MAX_COST': 1500.0}
        use('streets', 'demand', 'facilities')
    elif aid == 'landallocation':
        P = {'PARCELS': PC,
             'SUIT_FIELDS': ['s_built', 's_industrial', 's_recreation', 's_water'],
             'TARGETS': 's_built=40000,s_industrial=20000,'
                        's_recreation=30000,s_water=10000',
             'W_COMPACT': 0.3}
        use('parcels')
    elif aid == 'paretoallocation':
        P = {'PARCELS': PC,
             'SUIT_FIELDS': ['s_built', 's_industrial', 's_recreation', 's_water'],
             'TARGETS': 's_built=40000,s_industrial=20000,'
                        's_recreation=30000,s_water=10000',
             'N_POINTS': 5, 'W_MAX': 1.0}
        use('parcels')
    elif aid == 'capacitatedsiting':
        P = {'NETWORK': S, 'DEMAND': DM, 'CANDIDATES': FA,
             'P': 2, 'MAX_COST': 800.0}
        use('streets', 'demand', 'facilities')
    elif aid in ('accessequity', 'inequalitycurves', 'equitycrosstab'):
        P = {'INPUT': sh(WORK_DIR / "accessscore__OUTPUT.gpkg"),
             'VALUE_FIELD': 'score', 'POP_FIELD': 'pop', 'RANK_FIELD': ''}
        use('demand')
    elif aid == 'walkability':
        P = {'NETWORK': S, 'LANDUSE': L, 'POIS': PO, 'RADIUS': 400.0}
        use('streets', 'landuse', 'pois')
    elif aid == 'walkingslope':
        P = {'NETWORK': S, 'DEM': DEM5, 'SAMPLE_STEP': 25.0}
        use('streets', 'dem')
    elif aid == 'streetcomfort':
        P = {'NETWORK': S, 'POSITIVE': PO, 'BANDWIDTH': 120.0}
        use('streets', 'pois')
    elif aid == 'routequality':
        P = {'NETWORK': sh(WORK_DIR / "walkability__OUT_SEGMENTS.gpkg"),
             'ORIGINS': DM, 'DESTINATIONS': FA, 'PENALTY': 2.0}
        use('demand', 'facilities')
    elif aid in ('gtfsimport', 'transitfrequency', 'transitaccess'):
        P = {'FILE': sh(D.gtfs)}
        if aid == 'transitfrequency':
            P['START'] = 7
            P['END'] = 9
        if aid == 'transitaccess':
            P.update({'DEPARTURE': 8, 'NETWORK': S, 'ORIGINS': DMS,
                      'DEMAND': DMS, 'WALK_SPEED': 5.0, 'MAX_WALK': 10.0})
            use('streets', 'demand')
    elif aid == 'viewshed':
        P = {'DSM': DSM, 'OBSERVERS': FA, 'OBSERVER_HEIGHT': 10.0,
             'TARGET_HEIGHT': 1.5, 'RADIUS': 500.0, 'DIRECTIONS': 180}
        use('dsm', 'facilities')
    elif aid == 'isovistfield':
        P = {'BUILDINGS': B, 'CELL': 25.0, 'MAX_DIST': 100.0}
        use('buildings')
    elif aid == 'visualexposure':
        P = {'DSM': DSM, 'LANDMARKS': FA, 'EYE_HEIGHT': 1.5, 'RADIUS': 500.0}
        use('dsm', 'facilities')
    elif aid == 'populationprojection':
        P = {'INPUT': sh(WORK_DIR / "age_rates.gpkg"),
             'AGE_FIELD': 'age', 'POP_FIELD': 'pop',
             'SURVIVAL_FIELD': 'surv', 'FERTILITY_FIELD': 'fert',
             'STEPS': 5, 'STEP_YEARS': 5}
    elif aid == 'housingneeds':
        P = {'POP_FUTURE': 150000.0, 'HH_SIZE': 2.4, 'EXISTING': 50000.0,
             'VACANCY': 0.05, 'REPLACEMENT': 500.0, 'BACKLOG': 200.0}
    elif aid == 'residentialcapacity':
        P = {'PARCELS': L, 'UNIT_SIZE': 100.0, 'EFFICIENCY': 0.8}
        use('landuse')
    elif aid == 'popallocate':
        P = {'PARCELS': L, 'INCREMENT': 5000.0}
        use('landuse')
    elif aid == 'greenaccess':
        P = {'NETWORK': S, 'DEMAND': DM, 'GREENS': GR,
             'HIERARCHY': '0.5=300, 2=800, 10=2000'}
        use('streets', 'demand', 'green')
    elif aid == 'greenconnectivity':
        P = {'GREENS': GR, 'MAX_GAP': 50.0}
        use('green')
    elif aid == 'landcoverchange':
        P = {'RASTER_T1': sh(D.lc2010), 'RASTER_T2': sh(D.lc2017)}
    elif aid == 'growthsim':
        P = {'SEED': sh(D.urb2010), 'SUITABILITY': sh(D.lc2010),
             'DEMAND_HA': 30.0, 'ITERATIONS': 10, 'RNG_SEED': 42}
    elif aid == 'sprawlmetrics':
        P = {'URBAN_T1': sh(D.urb2010), 'URBAN_T2': sh(D.urb2017),
             'POP_T1': 99830.0, 'POP_T2': 120000.0}
    elif aid == 'cyclingstress':
        P = {'NETWORK': S}
        use('streets')
    elif aid == 'lowstressislands':
        P = {'NETWORK': sh(WORK_DIR / "cyclingstress__OUTPUT.gpkg"),
             'THRESHOLD': 2, 'ORIGINS': DM, 'DESTINATIONS': PO}
        use('demand', 'pois')
    elif aid == 'flowaccumulation':
        P = {'DEM': DEM5}
        use('dem')
    elif aid == 'handindex':
        P = {'DEM': sh(WORK_DIR / "flowaccumulation__OUTPUT_FILLED.tif"),
             'D8_DIR': sh(WORK_DIR / "flowaccumulation__OUTPUT_DIR.tif"),
             'ACCUM': sh(WORK_DIR / "flowaccumulation__OUTPUT_ACCUM.tif"),
             'THRESHOLD': 50, 'DEPTH': 1.0}
    elif aid == 'floodexposure':
        P = {'INUNDATION': sh(WORK_DIR / "handindex__OUTPUT_INUNDATION.tif"),
             'BUILDINGS': B, 'DEMAND': DM}
        use('buildings', 'demand')
    elif aid == 'tripgeneration':
        P = {'ZONES': NB, 'POP_FIELD': 'population',
             'JOBS_FIELD': 'households', 'P_RATE': 0.6, 'A_RATE': 0.5}
        use('nb')
    elif aid == 'gravitymodel':
        P = {'ZONES': sh(D.zones),
             'ZONE_ID': 'cbs_code',
             'PRODUCTION_FIELD': 'production', 'ATTRACTION_FIELD': 'attraction',
             'NETWORK': S, 'BETA': 0.1, 'KIND': 0,
             'MAX_ITER': 100, 'TOL': 0.001, 'LINES': None}
        use('landuse', 'streets')
    elif aid == 'modesplit':
        P = {'FLOWS': sh(WORK_DIR / "gravitymodel__OUTPUT.gpkg"),
             'FLOW_FIELD': 'flow', 'MODE_TIMES': 'cost,cost',
             'MODE_BETAS': '-0.05,-0.08', 'MODE_ASCS': '0,-0.5',
             'MODE_NAMES': 'car,transit'}
    elif aid == 'parkingdemand':
        P = {'ZONES': L}
        use('landuse')
    elif aid == 'parkingsupplybalance':
        P = {'ZONES': L, 'SUPPLY': FA, 'RADIUS': 500.0, 'NETWORK': S}
        use('landuse', 'facilities', 'streets')
    elif aid == 'groundmotion':
        P = {'MAGNITUDE': 7.0, 'DEPTH_KM': 10.0, 'VS30': 400.0,
             'EPICENTRE': sh(WORK_DIR / "epicentre.gpkg"), 'RECEIVERS': DM}
        use('demand')
    elif aid == 'liquefaction':
        P = {'MODE': 0, 'DEM': DEM5, 'TARGET': sh(D.demand_terrain),
             'PGA_G': 0.35, 'PGA_FIELD': '',
             'MAGNITUDE': 7.0, 'TECTONIC': 1, 'VS30_MS': 300.0,
             'GROUNDWATER_M': 5.0}
        use('dem', 'demand')
    elif aid == 'seismicdebris':
        P = {'BUILDINGS': B, 'NETWORK_MODE': 0, 'NETWORK': L,
             'MAGNITUDE': 7.0, 'REFERENCE_PGA': 0.4, 'SIMULATIONS': 5, 'SEED': 42}
        use('buildings', 'landuse')
    elif aid == 'seismicimpact':
        P = {'BUILDINGS': sh(WORK_DIR / "seismicdebris__OUT_BUILDINGS.gpkg"),
             'AREA_FIELD': 'footprint_area', 'FLOOR_FIELD': 'height_m_2',
             'BUILDING_TYPE': 0, 'TIME_OF_DAY': 0, 'OCCUPANCY': 0}
    elif aid == 'coseismiclandslide':
        P = {'AC_SOURCE': 1, 'TARGET': sh(D.demand_ac),
             'TERRAIN': DEM, 'PGA_G': 0.35, 'PGA_FIELD': '',
             'AC_FIELD': 'ac_g', 'MAGNITUDE': 7.0}
        use('dem')
    else:
        return None, []

    return P, inp


LAYER_FILES = {
    'streets': D.streets, 'buildings': D.buildings, 'landuse': D.landuse,
    'pois': D.pois, 'facilities': D.facilities, 'green': D.green,
    'water': D.water, 'demand': D.demand, 'nb': D.nb, 'dem': D.dem,
    'dsm': D.dsm, 'parcels': D.parcels, 'demand_s': D.demand_s,
    'green_patches': D.green_patches, 'demand_terrain': D.demand_terrain,
    'zones': D.zones,
    'demand_od': D.demand_od, 'demand_rt': D.demand_rt,
}


def resolve(aid, algo, P):
    out = {}
    for prm in algo.parameterDefinitions():
        name = prm.name()
        if isinstance(prm, (QgsProcessingParameterFeatureSink,
                            QgsProcessingParameterRasterDestination,
                            QgsProcessingParameterVectorDestination,
                            QgsProcessingParameterFileDestination)):
            continue
        if isinstance(prm, QgsProcessingParameterField):
            parent = prm.parentLayerParameterName()
            src = P.get(parent)
            cur = P.get(name)
            if isinstance(cur, (list, tuple)):
                out[name] = list(cur)
                continue
            if cur == "" and name in P:
                out[name] = ""       # explicitly cleared - keep it empty
                continue
            if not isinstance(src, str) or not os.path.exists(src):
                out[name] = ""
                continue
            if isinstance(cur, str) and cur:
                lyr = load_layer(src, "p")
                if lyr is not None and lyr.fields().lookupField(cur) >= 0:
                    out[name] = cur
                    continue
            lyr = load_layer(src, "p")
            cand = ""
            if lyr is not None:
                for f in lyr.fields():
                    if f.name().lower() in ("fid", "geom", "geometry"):
                        continue
                    cand = f.name()
                    break
            out[name] = cand
            continue
        if isinstance(prm, QgsProcessingParameterEnum):
            cur = P.get(name)
            out[name] = cur if (isinstance(cur, int) and
                                 0 <= cur < len(prm.options())) else prm.defaultValue()
            continue
        if isinstance(prm, QgsProcessingParameterNumber):
            cur = P.get(name)
            out[name] = cur if isinstance(cur, (int, float)) and \
                not isinstance(cur, bool) else prm.defaultValue()
            continue
        if isinstance(prm, QgsProcessingParameterBoolean):
            cur = P.get(name)
            out[name] = cur if isinstance(cur, bool) else prm.defaultValue()
            continue
        if isinstance(prm, QgsProcessingParameterCrs):
            out[name] = P.get(name) or "EPSG:28992"
            continue
        if isinstance(prm, QgsProcessingParameterExtent):
            continue
        if isinstance(prm, QgsProcessingParameterFeatureSource):
            cur = P.get(name)
            if isinstance(cur, str) and cur:
                out[name] = cur
            continue
        if isinstance(prm, QgsProcessingParameterFile):
            cur = P.get(name)
            out[name] = cur if cur else ""
            continue
        cur = P.get(name)
        out[name] = cur if cur is not None else (prm.defaultValue()
                                                 if hasattr(prm, "defaultValue")
                                                 else "")
    for k, v in P.items():
        out.setdefault(k, v)
    return out


def dest_paths(aid, algo, skip=None):
    o = {}
    skip = skip or set()
    for prm in algo.parameterDefinitions():
        if prm.name() in skip:
            continue
        if isinstance(prm, (QgsProcessingParameterFeatureSink,
                            QgsProcessingParameterVectorDestination)):
            o[prm.name()] = sh(WORK_DIR / f"{aid}__{prm.name()}.gpkg")
        elif isinstance(prm, QgsProcessingParameterRasterDestination):
            o[prm.name()] = sh(WORK_DIR / f"{aid}__{prm.name()}.tif")
        elif isinstance(prm, QgsProcessingParameterFileDestination):
            ext = ""
            try:
                ext = prm.defaultFileExtension() or ""
            except Exception:
                pass
            if not ext.startswith(".") and ext:
                ext = "." + ext
            o[prm.name()] = sh(WORK_DIR / f"{aid}__{prm.name()}{ext or '.out'}")
    return o


def propagate_snapshots():
    """Copy the scenario snapshot into the files the compare/rank tools read."""
    snap = None
    for cand in ("scenariosnapshot__OUTPUT_JSON.json",
                 "scenariosnapshot__OUTPUT_JSON.out"):
        pth = WORK_DIR / cand
        if pth.exists():
            snap = pth
            break
    if snap is None:
        return
    for nm in ("snapA.json", "snapB.json"):
        shutil.copy(snap, WORK_DIR / nm)
    snaps = WORK_DIR / "snapshots"
    snaps.mkdir(exist_ok=True)
    for idx, label in ((1, "Utrecht Baseline"), (2, "Utrecht Alternative")):
        try:
            with open(snap, encoding="utf-8") as fh:
                data = json.load(fh)
            data["name"] = label
            with open(snaps / f"snap{idx}.json", "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
        except Exception:
            shutil.copy(snap, snaps / f"snap{idx}.json")


def make_aux():
    """Small helper layers derived from the real data."""
    from qgis.core import (QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY,
                            QgsField, QgsVectorFileWriter, QgsCoordinateTransform,
                            QgsCoordinateReferenceSystem)
    # age-rate table for the cohort-component projection
    lyr = QgsVectorLayer("Point?crs=EPSG:28992&field=age:string&field=pop:integer"
                         "&field=surv:double&field=fert:double", "age", "memory")
    pr = lyr.dataProvider()
    for i in range(18):
        f = QgsFeature(lyr.fields())
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(136000, 456000)))
        f['age'] = f"{i*5}-{i*5+4}"
        f['pop'] = int(1200 * (1.0 - i * 0.045))
        f['surv'] = 0.995 - i * 0.0015
        f['fert'] = 0.0 if i > 9 else (0.012 if i >= 4 else 0.0)
        pr.addFeature(f)
    lyr.updateExtents()
    QgsVectorFileWriter.writeAsVectorFormatV3(
        lyr, sh(WORK_DIR / "age_rates.gpkg"), PROJECT.transformContext(),
        QgsVectorFileWriter.SaveVectorOptions())
    # epicentre for the ground-motion scenario
    ep = QgsVectorLayer("Point?crs=EPSG:28992", "epicentre", "memory")
    f = QgsFeature(ep.fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(136800, 456500)))
    ep.dataProvider().addFeature(f)
    ep.updateExtents()
    QgsVectorFileWriter.writeAsVectorFormatV3(
        ep, sh(WORK_DIR / "epicentre.gpkg"), PROJECT.transformContext(),
        QgsVectorFileWriter.SaveVectorOptions())
    # demand copy with a critical-acceleration column
    dm = load_layer(D.demand, "d")
    if dm is not None:
        out = QgsVectorLayer("Point?crs=EPSG:28992&field=ac_g:double&field=grp:string",
                             "dac", "memory")
        opr = out.dataProvider()
        i = 0
        for feat in dm.getFeatures():
            f = QgsFeature(out.fields())
            f.setGeometry(feat.geometry())
            f['ac_g'] = round(0.12 + 0.05 * (i % 9), 3)
            f['grp'] = ("A", "B", "C")[i % 3]
            opr.addFeature(f)
            i += 1
        out.updateExtents()
        QgsVectorFileWriter.writeAsVectorFormatV3(
            out, sh(WORK_DIR / "demand_ac.gpkg"), PROJECT.transformContext(),
            QgsVectorFileWriter.SaveVectorOptions())
    # the landslide tool needs every target inside the terrain raster
    try:
        from osgeo import gdal as _gdal
        _ds = _gdal.Open(sh(D.dem))
        _gt = _ds.GetGeoTransform()
        _ext = (_gt[0], _gt[3] + _ds.RasterYSize * _gt[5],
                _gt[0] + _ds.RasterXSize * _gt[1], _gt[3])
        _ds = None
        src = QgsVectorLayer(sh(WORK_DIR / "demand_ac.gpkg"), "dac", "ogr")
        clip_geom = QgsGeometry.fromRect(
            QgsRectangle(_ext[0], _ext[1], _ext[2], _ext[3]))
        out = QgsVectorLayer("Point?crs=EPSG:28992", "dac_clip", "memory")
        opr = out.dataProvider()
        out.addAttributes(src.fields())
        out.updateFields()
        kept = 0
        for feat in src.getFeatures():
            g = feat.geometry()
            if g is not None and clip_geom.contains(g):
                nf = QgsFeature(out.fields())
                nf.setGeometry(g)
                for fld in out.fields().names():
                    try:
                        nf.setAttribute(fld, feat[fld])
                    except Exception:
                        pass
                opr.addFeature(nf)
                kept += 1
        out.updateExtents()
        QgsVectorFileWriter.writeAsVectorFormatV3(
            out, sh(WORK_DIR / "demand_ac_clip.gpkg"),
            PROJECT.transformContext(), QgsVectorFileWriter.SaveVectorOptions())
        print(f"[OK] {kept} landslide targets inside the terrain", flush=True)
    except Exception:
        traceback.print_exc()
    print("[OK] aux layers written", flush=True)


def main():
    only = None
    if '--algo' in sys.argv:
        only = sys.argv[sys.argv.index('--algo') + 1]

    make_aux()
    propagate_snapshots()

    order = [
        'preparenetwork', 'odmatrix', 'odroutes', 'serviceareas', 'nearestfacility',
        'linkcriticality', 'deadends', 'networkcentrality', 'spacesyntax',
        'buildingmetrics', 'tessellation', 'spacematrix', 'streetmorphology',
        'accessscore', 'shadowcasting', 'skyviewfactor', 'frontalarea', 'sunhours',
        'solarirradiation', 'annualsolar', 'heatriskgrid', 'noisescreen',
        'roademissions', 'airscreen', 'landusebalance', 'facilityadequacy',
        'densitygrid', 'performancereport', 'scenariosnapshot', 'scenariocompare',
        'scenariorank', 'planaudit', 'scenariopipeline', 'facilitylocation',
        'capacitatedallocation', 'landallocation', 'paretoallocation',
        'capacitatedsiting', 'accessequity', 'inequalitycurves', 'equitycrosstab',
        'walkability', 'walkingslope', 'streetcomfort', 'routequality',
        'gtfsimport', 'transitfrequency', 'transitaccess', 'viewshed', 'isovistfield',
        'visualexposure', 'populationprojection', 'housingneeds',
        'residentialcapacity', 'popallocate', 'greenaccess', 'greenconnectivity',
        'landcoverchange', 'growthsim', 'sprawlmetrics', 'cyclingstress',
        'lowstressislands', 'flowaccumulation', 'handindex', 'floodexposure',
        'tripgeneration', 'gravitymodel', 'modesplit', 'parkingdemand',
        'parkingsupplybalance', 'groundmotion', 'liquefaction', 'seismicdebris',
        'seismicimpact', 'coseismiclandslide', 'democity',
    ]
    order = [a for a in order if a in ALGOS]
    for aid in ALGOS:
        if aid not in order:
            order.append(aid)
    if only:
        order = [only]

    ok = fail = 0
    results = {}
    print(f"\n=== STAGE 2: {len(order)} algorithms on REAL Utrecht data ===", flush=True)
    for i, aid in enumerate(order, 1):
        t0 = time.time()
        algo = ALGOS[aid]
        # the algorithm always runs (downstream tools read its output) but the
        # screenshot is only taken when it is not there yet
        done_png = SHOT_DIR / aid / f"{aid}_4panel.png"
        have_shot = done_png.exists() and only is None
        P, inp_keys = build_setup(aid)
        if P is None:
            print(f"[{i:2d}/{len(order)}] {aid}: no setup (demo generator)", flush=True)
            results[aid] = {'ok': False, 'reason': 'not applicable to real data'}
            continue
        P = resolve(aid, algo, P)
        dests = dest_paths(aid, algo, skip={k for k, v in P.items() if v is None})
        res = run(aid, P, dests)
        if res is None:
            print(f"[{i:2d}/{len(order)}] {aid}: RUN FAILED", flush=True)
            results[aid] = {'ok': False, 'reason': 'run failed'}
            fail += 1
            continue

        # the scenario snapshot feeds the compare / rank tools, so publish it
        # as soon as it is written - before any screenshot short-circuit
        if aid == 'scenariosnapshot':
            propagate_snapshots()

        out_layers = []
        for k, v in res.items():
            lyr = None
            if isinstance(v, str) and os.path.exists(v):
                lyr = load_layer(v, f"{aid}_{k}")
            elif hasattr(v, 'isValid') and hasattr(v, 'name'):
                lyr = v
            if lyr is not None and lyr.isValid():
                out_layers.append(lyr)
                try:
                    if lyr.id() not in PROJECT.mapLayers():
                        PROJECT.addMapLayer(lyr)
                except Exception:
                    pass

        text_out = [(k, v) for k, v in res.items()
                    if isinstance(v, str) and os.path.exists(v)
                    and v.lower().endswith(('.html', '.json', '.htm', '.out'))]

        if not out_layers and not text_out:
            print(f"[{i:2d}/{len(order)}] {aid}: no output", flush=True)
            results[aid] = {'ok': False, 'reason': 'no output'}
            fail += 1
            continue

        in_layers = []
        for k in inp_keys:
            lyr = load_layer(LAYER_FILES.get(k, ""), k)
            if lyr is not None:
                in_layers.append(lyr)
        if not in_layers:
            for k in ('landuse', 'streets', 'buildings', 'dsm'):
                lyr = load_layer(LAYER_FILES.get(k, ""), k)
                if lyr is not None:
                    in_layers.append(lyr)
                    break

        png = SHOT_DIR / aid / f"{aid}_4panel.png"
        png.parent.mkdir(parents=True, exist_ok=True)
        try:
            if have_shot:
                results[aid] = {
                    'ok': True, 'display_name': algo.displayName(),
                    'group': algo.group(),
                    'png': f"screenshots/{aid}/{aid}_4panel.png",
                    'data': 'Utrecht NL (open data)', 'resumed': True}
                ok += 1
                print(f"[{i:2d}/{len(order)}] {aid}: OK (reused screenshot)",
                      flush=True)
                continue
            if out_layers:
                capture_4panel(aid, algo.displayName(), in_layers, out_layers,
                               _fmt(P), sh(png))
            else:
                in_layers = in_layers[:1] or None
                capture_4panel(aid, algo.displayName(), in_layers or [], [],
                               _fmt(P) + f"\nreport: {text_out[0][1] if text_out else ''}",
                               sh(png))
            results[aid] = {
                'ok': True,
                'display_name': algo.displayName(),
                'group': algo.group(),
                'png': f"screenshots/{aid}/{aid}_4panel.png",
                'params': {k: (v if isinstance(v, (int, float, bool)) else str(v))
                           for k, v in P.items() if v not in (None, "")},
                'seconds': round(time.time() - t0, 1),
                'data': 'Utrecht NL (open data)',
            }
            ok += 1
            print(f"[{i:2d}/{len(order)}] {aid}: OK ({time.time()-t0:.1f}s)", flush=True)
        except Exception:
            traceback.print_exc()
            results[aid] = {'ok': False, 'reason': 'capture failed'}
            fail += 1

        with open(MANIFEST_DIR / f"screenshots_{aid}.json", 'w', encoding='utf-8') as f:
            json.dump({
                'algo_id': aid, 'display_name': algo.displayName(),
                'group': algo.group(),
                'dataset': 'Utrecht, Netherlands - open data (OSM / BAG / CBS / AHN / GTFS)',
                'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                'screenshots': [{
                    'step': 1,
                    'caption': (f"{algo.displayName()} - 4-panel view on real "
                                f"Utrecht data (Input | Parameters | Raw Output | Styled Output)"),
                    'path': f"screenshots/{aid}/{aid}_4panel.png",
                    'panels': ['Input Data', 'Parameters', 'Raw Output', 'Styled Output'],
                }],
            }, f, indent=2, ensure_ascii=False)


    summary = {'total': len(order), 'ok': ok, 'failed': fail,
               'dataset': 'Utrecht, Netherlands (open data)',
               'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
               'results': results}
    with open(MANIFEST_DIR / "screenshots_all.json", 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\n=== DONE: {ok} ok / {fail} failed / {len(order)} total ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
