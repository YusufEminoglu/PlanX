#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build the final PlanX Practical Guide HTML with the real screenshots embedded.

Produces:
  practical_guide.html            - interactive, tabs, search, screenshots linked from screenshots/
  practical_guide_static_en.html  - print/PDF-optimised, same content
  Copies both to the user's Downloads folder as single self-contained files.
"""
import html
import json
import os
import re
from pathlib import Path

GUIDE = Path(__file__).resolve().parents[1]  # docs/PRACTICAL_GUIDE (this script lives in scripts/)
# The public manual lives in the portal repository (geophilo_project), not
# in this plugin repository or its Hub zip. GEOPHILO_MANUALS overrides it.
MANUALS = Path(os.environ.get("GEOPHILO_MANUALS") or Path(__file__).resolve().parents[3].parents[1] / "geophilo_project" / "_manual_sources") / "planx" / "PRACTICAL_GUIDE"
SHOT = GUIDE / "screenshots"
MAN = GUIDE / "manifest"

with open(MAN / "algorithms_detailed.json", encoding="utf-8") as f:
    manifest = json.load(f)
with open(MAN / "screenshots_all.json", encoding="utf-8") as f:
    shots = json.load(f)

results = shots.get("results", {})


def shot_path(algo_id):
    """Relative URL of the 4-panel screenshot, JPEG first (much smaller).

    The images are published next to the guide (guide/screenshots/...), so the
    page links to them instead of embedding them: embedded, the 84 screenshots
    pushed the page past the 25 MiB file limit of the hosting.
    """
    for ext in ("jpg", "png"):
        shot = SHOT / algo_id / f"{algo_id}_4panel.{ext}"
        if shot.exists():
            return f"screenshots/{algo_id}/{shot.name}"
    return None


# --------------------------------------------------------------- CSS / shell
CSS = """
:root{--bg:#fff;--fg:#1a1a1a;--muted:#555;--accent:#13a0a0;--accent-dark:#0d7a7a;
--accent-light:#e6f7f7;--border:#ddd;--code-bg:#f5f7f7;--sidebar-bg:#f0f4f4;
--sidebar-fg:#333;--table-stripe:#f9fbfb;--tab-bg:#f5f7f7}
@media(prefers-color-scheme:dark){:root{--bg:#1a1a2e;--fg:#e0e0e0;--muted:#999;
--accent:#13a0a0;--accent-dark:#0d7a7a;--accent-light:#0d2a2a;--border:#333;
--code-bg:#1e2d3d;--sidebar-bg:#16213e;--sidebar-fg:#ccc;--table-stripe:#1a2a3a;--tab-bg:#1e2d3d}}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:var(--bg);
color:var(--fg);display:flex;min-height:100vh;font-size:11pt;line-height:1.55}
#sidebar{width:320px;min-width:320px;height:100vh;position:sticky;top:0;
background:var(--sidebar-bg);border-right:1px solid var(--border);display:flex;
flex-direction:column;overflow:hidden}
#sidebar-header{padding:16px 18px 8px;border-bottom:1px solid var(--border)}
#sidebar-header .logo{font-size:1.4em;font-weight:700;color:var(--accent);display:block}
#sidebar-header .subtitle{font-size:.78em;color:var(--muted)}
#search-wrap{padding:10px 14px}
#search{width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:6px;
font-size:.9em;background:var(--bg);color:var(--fg);outline:none}
#search:focus{border-color:var(--accent);box-shadow:0 0 0 2px var(--accent-light)}
#toc{flex:1;overflow-y:auto;padding:4px 0;list-style:none}
.toc-group{border-bottom:1px solid var(--border)}
.toc-group-btn{display:block;width:100%;text-align:left;padding:8px 18px;background:none;
border:none;font-size:.88em;font-weight:600;color:var(--sidebar-fg);cursor:pointer}
.toc-group-btn:hover{background:var(--accent-light)}
.toc-group-btn .arrow{font-size:.7em;transition:transform .2s;display:inline-block}
.toc-group-btn[aria-expanded="false"] .arrow{transform:rotate(-90deg)}
.toc-algs{list-style:none;overflow:hidden}
.toc-algs li a{display:block;padding:4px 18px 4px 28px;font-size:.85em;
color:var(--sidebar-fg);text-decoration:none;border-left:3px solid transparent}
.toc-algs li a:hover,.toc-algs li a.active{background:var(--accent-light);
border-left-color:var(--accent);color:var(--accent-dark)}
.toc-algs li a.hidden{display:none}
#sidebar-footer{padding:10px 18px;border-top:1px solid var(--border);display:flex;
flex-direction:column;gap:4px}
#sidebar-footer a{font-size:.82em;color:var(--muted);text-decoration:none}
#sidebar-footer a:hover{color:var(--accent)}
#content{flex:1;max-width:78em;padding:2em 2.5em 6em;overflow-y:auto}
h1{font-size:2.2em;margin:0 0 .15em;color:var(--accent)}
h2{font-size:1.5em;margin:1.6em 0 .5em;padding-bottom:.25em;
border-bottom:2px solid var(--accent);color:var(--accent-dark)}
h3{font-size:1.15em;margin:1.3em 0 .4em}
h4{font-size:1em;margin:1em 0 .3em;color:var(--muted)}
p,ul,ol{margin:.6em 0}ul,ol{padding-left:1.8em}li{margin:.25em 0}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
code{font-family:Consolas,monospace;font-size:.9em;background:var(--code-bg);
padding:.1em .3em;border-radius:3px}
table{width:100%;border-collapse:collapse;margin:.8em 0;font-size:.92em}
th,td{text-align:left;padding:.45em .6em;border:1px solid var(--border);vertical-align:top}
th{background:var(--accent-light);font-weight:600}
tr:nth-child(even) td{background:var(--table-stripe)}
.param-table td:first-child{font-family:Consolas,monospace;font-weight:600;white-space:nowrap}
.note{background:var(--accent-light);border-left:4px solid var(--accent);padding:.7em 1em;
margin:.8em 0;border-radius:0 4px 4px 0;font-size:.95em}
.algo-block{margin:1.2em 0;padding:1.2em;border:1px solid var(--border);border-radius:8px;
background:#fcfcfc}
@media(prefers-color-scheme:dark){.algo-block{background:#1d2033}}
.algo-title{font-weight:700;font-size:1.15em;color:var(--accent-dark);margin-bottom:.3em}
.algo-meta{font-size:.85em;color:var(--muted);margin-bottom:.8em}
.section{margin:1em 0}
.section-title{font-weight:600;color:var(--accent-dark);margin-bottom:.4em;
border-bottom:1px solid var(--border);padding-bottom:.2em}
.help-text{white-space:pre-wrap;font-size:.92em;line-height:1.5;background:#fafafa;
padding:.8em;border:1px solid #eee;border-radius:4px}
@media(prefers-color-scheme:dark){.help-text{background:#1a2a3a;border-color:#2b3a4a}}
.shot{margin:.8em 0;border:1px solid var(--border);border-radius:8px;overflow:hidden;
background:#fff}
.shot img{width:100%;height:auto;display:block}
.shot figcaption{padding:.7em;font-size:.88em;color:var(--muted);
border-top:1px solid var(--border);background:var(--tab-bg)}
.shot .step-badge{display:inline-block;background:var(--accent);color:#fff;font-size:.72em;
font-weight:600;padding:.15em .55em;border-radius:3px;margin-right:.5em}
.tabs{display:flex;border-bottom:2px solid var(--border);margin:1.2em 0 0}
.tab-btn{padding:.7em 1.4em;background:var(--tab-bg);border:none;
border-bottom:3px solid transparent;font-size:.95em;font-weight:600;color:var(--muted);
cursor:pointer}
.tab-btn.active{color:var(--accent);border-bottom-color:var(--accent);background:var(--bg)}
.tab-panel{display:none;padding-top:1em}
.tab-panel.active{display:block}
#cover{text-align:center;padding:3em 0 1.5em}
#cover h1{font-size:2.6em}
#cover .sub{font-size:1.1em;color:var(--muted)}
#cover .meta{font-size:.9em;color:var(--muted);margin-top:.8em}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:1.4em}
#cover .grid{text-align:left;margin-top:2em}
.card{border:1px solid var(--border);border-radius:8px;padding:1em;background:#fcfcfc}
@media(prefers-color-scheme:dark){.card{background:#1d2033}}
.card h3{margin-top:0}
.card .n{font-size:1.8em;font-weight:700;color:var(--accent)}
.toc-list{columns:3;column-gap:1.6em;font-size:.92em}
.toc-list a{text-decoration:none}
.toc-list a:hover{text-decoration:underline}
"""

JS = """
const DATA = __DATA__;
const GROUPS = __GROUPS__;
let current = null;

function buildTOC(){
  const toc=document.getElementById('toc');
  toc.innerHTML='';
  GROUPS.forEach((g,idx)=>{
    const li=document.createElement('li');li.className='toc-group';
    const btn=document.createElement('button');
    btn.className='toc-group-btn';btn.setAttribute('aria-expanded','true');
    btn.innerHTML='<span class="arrow">\\u25BC</span> '+(idx+1)+'. '+g.name;
    const ul=document.createElement('ul');ul.className='toc-algs';
    g.algos.forEach(id=>{
      const a=document.createElement('a');
      a.href='#'+id;a.dataset.name=id;
      a.dataset.display=(DATA[id]&&DATA[id].display_name)||id;
      a.textContent=a.dataset.display;
      ul.appendChild(document.createElement('li')).appendChild(a);
    });
    btn.addEventListener('click',()=>{
      const open=btn.getAttribute('aria-expanded')==='true';
      btn.setAttribute('aria-expanded',!open);
      ul.style.display=open?'none':'block';
      btn.querySelector('.arrow').style.transform=open?'rotate(-90deg)':'';
    });
    li.appendChild(btn);li.appendChild(ul);toc.appendChild(li);
  });
  toc.querySelectorAll('.toc-algs a').forEach(a=>{
    a.addEventListener('click',e=>{e.preventDefault();show(a.dataset.name);
      history.pushState(null,'','#'+a.dataset.name);});
  });
}

function show(id){
  const d=DATA[id];if(!d)return;
  current=id;
  document.querySelectorAll('.toc-algs a').forEach(a=>
    a.classList.toggle('active',a.dataset.name===id));
  document.getElementById('content').innerHTML=page(d);
  bindTabs();
  document.getElementById('content').scrollIntoView({block:'start'});
}

function esc(s){return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

function page(d){
  const P=d.params||[];
  const IO=d.outputs||[];
  const inputs=P.filter(x=>x.type!=='FeatureSink');
  const outputs=IO.concat(P.filter(x=>x.type==='FeatureSink'));
  let h='';
  h+='<div class="algo-block"><div class="algo-title">'+esc(d.display_name)+
     ' <code>('+d.algo_id+')</code></div>';
  h+='<div class="algo-meta">Group: '+esc(d.group)+' &nbsp;|&nbsp; '+
     (d.seconds!=null?('runtime '+d.seconds+' s &nbsp;|&nbsp; '):'')+
     'Source: real QGIS run</div>';

  h+='<div class="tabs">';
  h+='<button class="tab-btn active" data-t="shot">\\ud83d\\udcbc Screenshot</button>';
  h+='<button class="tab-btn" data-t="theory">\\ud83d\\udcd6 Theory &amp; Interpretation</button>';
  h+='<button class="tab-btn" data-t="params">\\ud83d\\udccb Parameters &amp; Outputs</button>';
  h+='<button class="tab-btn" data-t="steps">\\ud83d\\udd17 Step-by-step</button>';
  h+='</div>';

  h+='<div class="tab-panel active" id="t-shot">';
  if(d.img){
    h+='<figure class="shot"><img src="' + d.img +
       '" alt="'+esc(d.display_name)+' 4-panel screenshot" loading="lazy">';
    h+='<figcaption><span class="step-badge">4-panel</span>'+
       esc(d.display_name)+' &mdash; Panel 1: input data &middot; Panel 2: parameters used '+
       '&middot; Panel 3: raw output &middot; Panel 4: styled output. '+
       'Produced by running the real PlanX engine in QGIS '+
       (d.qgis_version?d.qgis_version:'')+'.</figcaption></figure>';
  } else {
    h+='<div class="note">No screenshot available for this algorithm.</div>';
  }
  h+='</div>';

  h+='<div class="tab-panel" id="t-theory"><div class="help-text">'+
     esc(d.help_text)+'</div></div>';

  h+='<div class="tab-panel" id="t-params">';
  h+='<h4>Input parameters</h4><table class="param-table"><thead><tr>'+
     '<th>Parameter</th><th>Label</th><th>Type</th></tr></thead><tbody>';
  inputs.forEach(x=>{h+='<tr><td>'+esc(x.name)+'</td><td>'+esc(x.label)+
     '</td><td><code>'+esc(x.type)+'</code></td></tr>';});
  h+='</tbody></table>';
  h+='<h4>Outputs</h4><table class="param-table"><thead><tr>'+
     '<th>Output</th><th>Label</th><th>Type</th></tr></thead><tbody>';
  outputs.forEach(x=>{h+='<tr><td>'+esc(x.name)+'</td><td>'+esc(x.label)+
     '</td><td><code>'+esc(x.type)+'</code></td></tr>';});
  h+='</tbody></table>';
  if(d.run_params&&Object.keys(d.run_params).length){
    h+='<h4>Values used in the recorded run</h4><table class="param-table">'+
       '<thead><tr><th>Parameter</th><th>Value</th></tr></thead><tbody>';
    Object.entries(d.run_params).forEach(([k,v])=>{
      h+='<tr><td>'+esc(k)+'</td><td>'+esc(String(v))+'</td></tr>';});
    h+='</tbody></table>';
  }
  h+='</div>';

  h+='<div class="tab-panel" id="t-steps"><h4>How to run it</h4><ol>';
  (d.steps||[]).forEach(s=>{h+='<li>'+s+'</li>';});
  h+='</ol><h4>How to read the results</h4><div class="help-text">'+
     esc(d.read_how||'')+'</div></div>';

  h+='</div>';
  return h;
}

function bindTabs(){
  document.querySelectorAll('.tab-btn').forEach(b=>{
    b.addEventListener('click',()=>{
      document.querySelectorAll('.tab-btn').forEach(x=>x.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach(x=>x.classList.remove('active'));
      b.classList.add('active');
      document.getElementById('t-'+b.dataset.t).classList.add('active');
    });
  });
}

document.addEventListener('DOMContentLoaded',()=>{
  buildTOC();
  const s=document.getElementById('search');
  s.addEventListener('input',e=>{
    const q=e.target.value.toLowerCase();
    document.querySelectorAll('.toc-algs a').forEach(a=>{
      const m=a.dataset.display.toLowerCase().includes(q)||a.dataset.name.includes(q);
      a.classList.toggle('hidden',!m);
    });
    document.querySelectorAll('.toc-group').forEach(g=>{
      g.style.display=g.querySelectorAll('.toc-algs a:not(.hidden)').length?'':'none';
    });
  });
  if(location.hash&&DATA[location.hash.slice(1)])show(location.hash.slice(1));
});
"""

# --------------------------------------------------------------- build data
def build_data():
    data = {}
    groups = {}
    order = []
    for a in manifest["algorithms"]:
        aid = a["algo_id"]
        det = manifest["algo_details"].get(aid, {})
        r = results.get(aid, {})
        grp = det.get("group", a["group"])
        if a["group_order"] not in groups:
            groups[a["group_order"]] = {"name": grp, "algos": []}
            order.append(a["group_order"])
        groups[a["group_order"]]["algos"].append(aid)

        img = shot_path(aid)

        data[aid] = {
            "algo_id": aid,
            "display_name": det.get("display_name", aid),
            "group": grp,
            "help_text": det.get("help_summary", ""),
            "params": det.get("parameters", []),
            "outputs": det.get("outputs", []),
            "img": img,
            "seconds": r.get("seconds"),
            "run_params": r.get("params", {}),
        }
    return data, [groups[k] for k in sorted(order)]


# --------------------------------------------------- step-by-step text
def steps_for(aid, det):
    g = det.get("group", "")
    base = {
        "Network Analysis": [
            "Open <b>Processing &rarr; Toolbox &rarr; PlanX</b> and pick the tool.",
            "Set the <b>street network</b> to your line layer. Run "
            "<b>Prepare Network</b> first so crossing lines share junctions.",
            "Set the <b>facility / origin / destination</b> layer.",
            "Set the <b>breaks</b> (distances or cost thresholds) and run.",
            "Style the output by the band / class field and inspect the summary table.",
        ],
        "Centrality & Space Syntax": [
            "Run <b>Prepare Network</b> first (shared junctions matter for every metric).",
            "Choose the <b>centrality types</b> or the <b>radii</b> (e.g. <code>400, 800, 1600, n</code>).",
            "For large networks lower the <b>sample size</b> to keep the run tractable.",
            "Style the result as graduated on the metric and compare with the plan.",
        ],
        "Urban Morphology": [
            "Use a <b>closed polygon</b> building layer (no multipart gaps).",
            "Give the <b>limit / study area</b> so the tessellation stops at the district edge.",
            "Run and style the result graduated on the metric of interest.",
        ],
        "Accessibility": [
            "Prepare the street network first.",
            "Give the <b>demand points</b> (origins) and the <b>amenity layers</b>.",
            "Set the <b>threshold</b> in minutes (15 min = 1,200 m at 5 km/h).",
            "Style the composite score 0&ndash;100 and map the low-access clusters.",
        ],
        "Microclimate": [
            "Supply a <b>DSM</b> (buildings + terrain) &mdash; a bare DEM under-reports shading.",
            "Set the <b>date and time</b> (21 June, 12:00 is the standard test case).",
            "Set the <b>time zone offset</b> so the sun position is correct.",
            "Run, then style the raster with a single-band pseudo colour ramp.",
        ],
        "Plan Standards and QA": [
            "Supply the <b>land-use</b> and <b>population</b> layers.",
            "Set the <b>per-capita standards</b> (a CSV or the built-in defaults).",
            "Run and read the surplus / deficit column &mdash; that is the policy number.",
        ],
        "Reporting and Dashboard": [
            "Run the upstream PlanX tools first (access score, balance, adequacy, density).",
            "Point the tool at those layers (or let it auto-detect them in the project).",
            "Open the produced HTML report in any browser &mdash; it is a single shareable file.",
        ],
        "Optimization": [
            "Prepare the network and the demand points.",
            "Give the <b>candidate sites</b> layer (existing + possible locations).",
            "Set the <b>method</b> (coverage / p-median) and the distance or budget limit.",
            "Run, then inspect the site ranking and the allocation table.",
        ],
        "Equity": [
            "Run the accessibility or walkability tool first to get the value column.",
            "Give the <b>value field</b> and the <b>population field</b>.",
            "Add a <b>group field</b> (district, income band) for the cross-tabs.",
            "Read Gini / Theil / P90-P10 and the poverty share.",
        ],
        "Walkability": [
            "Prepare the network; supply land use, POIs and a DEM.",
            "Set the <b>search radius</b> (400&ndash;500 m is the usual walkable catchment).",
            "Tune the <b>component weights</b> if a component is missing.",
            "Style the 0&ndash;100 score and read the low-score segments as the priority list.",
        ],
        "Transit": [
            "Give the <b>GTFS zip</b> and the service day.",
            "Set the <b>time window</b> (e.g. 7&ndash;9 for the morning peak).",
            "For access analysis also give the <b>street network</b>, origins and destinations.",
            "Compare transit times with the walk-only times in the same output.",
        ],
        "Visibility": [
            "Supply the <b>DSM</b> and the observer or landmark layer.",
            "Set the <b>heights</b> (observer eye height, target height) and the radius.",
            "Run and style the visibility count raster.",
        ],
        "Population and Housing": [
            "Give the age-group table (or zone layer) for the projection.",
            "Set the <b>steps</b> and <b>years per step</b>.",
            "Feed the projected population into the housing-needs tool.",
            "Test the housing need against the residential capacity of the zoning.",
        ],
        "Green Infrastructure": [
            "Give the <b>green polygons</b> and the demand points.",
            "Set the <b>hierarchy</b> (e.g. <code>0.5=300, 2=800, 10=2000</code>).",
            "Run and read the coverage per class in the summary output.",
        ],
        "Urban Growth": [
            "Give a <b>seed urban mask</b> and a <b>suitability</b> raster of the same grid.",
            "Set the <b>land demand</b> in hectares and the number of iterations.",
            "Add a <b>constraints</b> raster for never-build land.",
            "Run and compare the year-of-conversion raster with the sprawl metric.",
        ],
        "Cycling": [
            "Give the network with speed, lanes, AADT and infrastructure fields.",
            "Run <b>Cycling Stress</b> first &mdash; the island tool reads its LTS field.",
            "Set the <b>maximum LTS</b> for the low-stress network (2 = all ages).",
            "Read the island map: many small islands mean a network in name only.",
        ],
        "Hazard Screening": [
            "Give the <b>DEM</b> (projected CRS).",
            "Run <b>Flow Accumulation</b> first &mdash; HAND reads its filled DEM, direction and accumulation.",
            "Set the <b>drainage threshold</b> and the <b>inundation depth</b>.",
            "Run <b>Flood Exposure</b> for the building and population counts.",
        ],
        "Travel Demand": [
            "Give the <b>zone layer</b> with population and employment.",
            "Set the production and attraction rates, then run the gravity model over the network.",
            "Feed the OD matrix into the mode split with per-mode time fields and betas.",
            "Check the parking demand against the supply in reach.",
        ],
        "Seismic Risk": [
            "Give the <b>receiver</b> layer and the scenario (magnitude, epicentre, depth).",
            "Set the <b>Vs30</b> and the spectral periods.",
            "Run ground motion first &mdash; the debris, liquefaction and landslide tools read its PGA.",
            "Feed the damage probabilities into the human-impact tool.",
        ],
    }
    extra = {
        "serviceareas": "Compare the catchment polygons with the straight-line circles: the "
                        "pedshed ratio in the summary is the share of the promised radius the "
                        "street layout actually delivers. Below 0.4 the network reaches less "
                        "than half of the regulatory radius.",
        "odmatrix": "The detour ratio (net cost / straight-line distance) above 1.4 signals a "
                    "barrier or a missing link. Values near 1.0 mean the network is direct.",
        "networkcentrality": "High betweenness with low closeness marks a bottleneck street: "
                             "important but far from everything.",
        "spacesyntax": "Integration rises toward the centre and falls at the edge; NACH/NAIN "
                       "rescale that to the local sub-network. Compare the 800 m and 1600 m "
                       "maps to see how local the pattern is.",
        "walkability": "The 0-100 score combines five normalised components. Read the low-score "
                       "segments as the retrofit list, not as a verdict on the street.",
        "annualsolar": "kWh/m2/yr is a clear-sky screening value, not a yield forecast. A "
                       "monthly raster shows the seasonal swing; the EPW calibration shifts it "
                       "toward real weather.",
        "shadowcasting": "Shadow length is proportional to height / tan(altitude). Near the "
                         "solstice the shadow is at its shortest, near the equinox at its longest.",
        "serviceareas": "Buffer catches hug the streets; concave hull gives the familiar blob; "
                        "convex hull is the most generous envelope.",
    }
    st = list(base.get(g, ["Run the tool and read the output field descriptions."]))
    if aid in extra:
        st = st + ["&nbsp;<br><b>Interpretation note:</b> " + extra[aid]]
    return st


def read_how(det):
    txt = det.get("help_summary", "")
    m = re.search(r"How to read the results(.*?)(Using the results|$)", txt, re.S)
    if m:
        return m.group(1).strip()
    m = re.search(r"Using the results(.*)$", txt, re.S)
    if m:
        return m.group(1).strip()
    return ""


# ------------------------------------------------------------------- write
data, groups = build_data()
for aid, d in data.items():
    det = manifest["algo_details"].get(aid, {})
    d["steps"] = steps_for(aid, det)
    d["read_how"] = read_how(det)
    d["qgis_version"] = "3.44 LTR"

js = JS.replace("__DATA__", json.dumps(data, ensure_ascii=False))
js = js.replace("__GROUPS__", json.dumps(groups, ensure_ascii=False))

cover = """
<div id="cover">
<h1>PlanX Practical Guide</h1>
<p class="sub">76 algorithms &middot; real Utrecht open data &middot; step-by-step usage</p>
<p class="meta">Every screenshot was produced by running the PlanX engine in QGIS
(<b>no core QGIS analysis tools</b>) on <b>real open data for Utrecht, Netherlands</b>:
OSM, the Dutch BAG building register with build years, CBS neighbourhood and
postcode statistics, the AHN national height model and the national GTFS feed.
Version 2026-10-21 &middot; GPL-3.0 &copy; Yusuf Eminoğlu</p>
<div class="grid" id="cover-grid"></div>
<h2 style="margin-top:2em">Index</h2>
<div class="toc-list" id="cover-toc"></div>
</div>
"""

page_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PlanX Practical Guide — 76 Algorithms (Applied Workflows &amp; Screenshots)</title>
<style>{CSS}</style>
</head>
<body>
<nav id="sidebar">
<div id="sidebar-header">
<span class="logo">PlanX</span>
<span class="subtitle">Practical Guide &middot; 76 algorithms</span>
</div>
<div id="search-wrap"><input type="text" id="search" placeholder="Search algorithms…" autocomplete="off"></div>
<ul id="toc"></ul>
<div id="sidebar-footer">
<a href="../PLANX_REFERENCE_MANUAL.html">&larr; Reference Manual (Theory)</a>
<a href="https://geophilo.com/planx/">geophilo.com/planx</a>
</div>
</nav>
<main id="content">{cover}</main>
<script>{js}
</script>
<script>
document.addEventListener('DOMContentLoaded',function(){{
  const g=document.getElementById('cover-grid');
  const n=Object.keys(DATA).length;
  const gcount=GROUPS.length;
  const shots=Object.values(DATA).filter(d=>d.img).length;
  g.innerHTML=
    '<div class="card"><div class="n">'+n+'</div><h3>Algorithms</h3>'+
    '<p>across '+gcount+' tool groups, each with parameters, outputs, '+
    'theory and a step-by-step workflow.</p></div>'+
    '<div class="card"><div class="n">'+shots+'</div><h3>Real screenshots</h3>'+
    '<p>4-panel captures: input data, parameters used, raw output, styled output.</p></div>'+
    '<div class="card"><div class="n">Utrecht</div><h3>Real open data</h3>'+
    '<p>1,000 ha of the historic centre: OSM, BAG (32,812 buildings with build '+
    'year), CBS (50 neighbourhoods, 99,830 residents), AHN 0.5 m DSM/DTM, GTFS NL.</p></div>';
  const tc=document.getElementById('cover-toc');
  GROUPS.forEach((grp,i)=>{{
    const d=document.createElement('div');
    d.innerHTML='<b>'+(i+1)+'. '+grp.name+'</b>';
    const ul=document.createElement('div');
    grp.algos.forEach(id=>{{
      const a=document.createElement('a');
      a.href='#'+id;a.textContent='\\u00b7 '+(DATA[id]?DATA[id].display_name:id);
      a.style.display='block';
      a.addEventListener('click',e=>{{e.preventDefault();show(id);
        history.pushState(null,'','#'+id);}});
      ul.appendChild(a);
    }});
    d.appendChild(ul);
    tc.appendChild(d);
  }});
}});
</script>
</body>
</html>"""

MANUALS.mkdir(parents=True, exist_ok=True)
out = MANUALS / "practical_guide.html"
out.write_text(page_html, encoding="utf-8")
print(f"wrote {out} ({out.stat().st_size/1024/1024:.1f} MB)")

# ------------------------------------------------------------------ copies
dl = Path("/mnt/c/Users/YE/Downloads")
if dl.exists():
    for name in ("PlanX_Practical_Guide.html", "PlanX_Practical_Guide_EN.html"):
        try:
            (dl / name).write_text(page_html, encoding="utf-8")
            print(f"copied -> {dl / name}")
        except Exception as e:
            print("copy failed:", e)
