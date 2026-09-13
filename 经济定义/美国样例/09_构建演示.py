# -*- coding: utf-8 -*-
"""
步骤9 · 阶段演示构建（独立、零侵入现有产品雏形）

原则：不改动 GADM 仓库任何文件。只【读取】GADM 州界 GeoJSON 作行政底图，
叠加本目录步骤 7 生成的 88 都市圈边界 + 步骤 8 的审核/版本状态，
输出一个【自包含】HTML（Leaflet + OSM 底图），可直接双击打开或本地起服务。

几何做了 Douglas-Peucker 简化以压缩体积（演示用；精确边界仍以 07_*.gpkg 为准）。
"""
import json, csv, os
import geopandas as gpd

HERE = os.path.dirname(os.path.abspath(__file__))
METRO_GJ = os.path.join(HERE, '07_美国都市圈边界.geojson')
SUMMARY_CSV = os.path.join(HERE, '07_美国都市圈一览.csv')
REVIEW_CSV = os.path.join(HERE, '08_审核状态.csv')
VERSION_CSV = os.path.join(HERE, '08_版本记录.csv')
STATE_GJ = r'D:\Desktop\科研--深圳数据经济研究院\地理围栏体系\GADM\geojson\USA_美国\USA_L2_adm1.geojson'
OUT = os.path.join(HERE, '09_阶段演示.html')


def rd(path):
    with open(path, encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


# ---------- 1. 都市圈边界 + 元数据 ----------
metro = json.load(open(METRO_GJ, encoding='utf-8'))
summary = {r['metro_id']: r for r in rd(SUMMARY_CSV)}
version = {r['metro_id']: r for r in rd(VERSION_CSV)}
members = {}
for r in rd(REVIEW_CSV):
    members.setdefault(r['metro_id'], []).append({
        'county_name': r['county_name'], 'state_name': r['state_name'],
        'fips5': r['fips5'], 'match_method': r['match_method'],
        'review_status': r['review_status'],
    })

feats = metro['features']
for f in feats:
    p = f['properties']; mid = p['metro_id']
    s = summary.get(mid, {}); v = version.get(mid, {})
    mem = members.get(mid, [])
    p['n_members'] = int(s.get('n_members_total', p.get('n_members', len(mem))))
    p['n_matched'] = int(s.get('n_matched', p['n_members'] - p.get('n_missing', 0)))
    p['n_missing'] = int(s.get('n_missing', p.get('n_missing', 0)))
    p['area_km2'] = int(round(float(s.get('area_km2_epsg5070', 0) or 0)))
    p['version'] = int(v.get('version', 0))
    p['last_action'] = v.get('last_action', '')
    p['reviewer'] = v.get('last_reviewer', '')
    p['involved_states'] = ' / '.join(sorted(set(m['state_name'] for m in mem if m['state_name'])))
    p['members'] = mem
    # bbox [west, south, east, north]
    b = f['geometry']
    coords = []
    def walk(g):
        if g['type'] == 'Polygon':
            coords.extend(g['coordinates'][0])
        elif g['type'] == 'MultiPolygon':
            for poly in g['coordinates']:
                coords.extend(poly[0])
    walk(b)
    xs = [c[0] for c in coords]; ys = [c[1] for c in coords]
    p['bbox'] = [round(min(xs), 4), round(min(ys), 4), round(max(xs), 4), round(max(ys), 4)]

# 简化都市圈几何
m_gdf = gpd.GeoDataFrame.from_features(feats, crs='EPSG:4326')
m_gdf['geometry'] = m_gdf.geometry.simplify(0.01, preserve_topology=True)
metro_js = m_gdf.to_json(ensure_ascii=False)

# ---------- 2. 州界（行政底图） ----------
st = gpd.read_file(STATE_GJ)[['NAME_1', 'geometry']].copy()
st['geometry'] = st.geometry.simplify(0.02, preserve_topology=True)
state_js = st.to_json(ensure_ascii=False)

# ---------- 3. HTML 模板 ----------
HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>美国都市圈经济定义 · 阶段演示</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<style>
  html,body,#map{height:100%;margin:0}
  body{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
  .panel{position:absolute;top:12px;right:12px;z-index:1000;background:#fff;border-radius:8px;
         box-shadow:0 2px 12px rgba(0,0,0,.25);padding:12px 14px;max-width:300px;font-size:13px;color:#333}
  .panel h1{font-size:15px;margin:0 0 6px}
  .panel .stat{color:#555;line-height:1.5}
  .panel .foot{margin-top:6px;color:#999;font-size:11px;line-height:1.4}
  .search{position:absolute;top:12px;left:12px;z-index:1000;width:300px}
  .search input{width:100%;padding:9px 11px;border:1px solid #ccc;border-radius:8px;
                box-shadow:0 2px 8px rgba(0,0,0,.15);font-size:14px;box-sizing:border-box}
  .search .results{background:#fff;border-radius:8px;box-shadow:0 2px 12px rgba(0,0,0,.25);
                   max-height:320px;overflow:auto;margin-top:6px;display:none}
  .search .results .item{padding:8px 11px;cursor:pointer;border-bottom:1px solid #eee;font-size:13px}
  .search .results .item:hover{background:#eef4fb}
  .legend{position:absolute;bottom:24px;left:12px;z-index:1000;background:#fff;border-radius:8px;
          box-shadow:0 2px 8px rgba(0,0,0,.2);padding:8px 11px;font-size:12px;color:#444}
  .sw{display:inline-block;width:13px;height:13px;border-radius:3px;vertical-align:-2px;margin-right:6px}
  .memb{margin:2px 0;font-size:12px;color:#333}
  .memb .st{color:#999}
  .tag{display:inline-block;padding:0 5px;border-radius:3px;font-size:10px;margin-left:5px;vertical-align:1px}
  .ok{background:#e6f6ec;color:#1a7f37}
  .warn{background:#fff3e0;color:#b45309}
  .bad{background:#fdecea;color:#b42318}
  .pp{min-width:250px;max-width:320px}
  .pp .t{font-weight:600;font-size:14px}
  .pp .m{font-size:12px;color:#666;margin-top:2px}
  .pp .memlist{margin-top:6px;max-height:190px;overflow:auto;border-top:1px solid #eee;padding-top:4px}
</style>
</head>
<body>
<div id="map"></div>
<div class="panel">
  <h1>美国都市圈经济定义 · 阶段演示</h1>
  <div class="stat" id="summary"></div>
  <div class="foot">数据源：Global_Cities_Definitions_Oct19 ＋ GADM 4.1<br>
    几何为演示简化版，精确边界见 07_美国都市圈边界.gpkg</div>
</div>
<div class="search">
  <input id="q" type="text" placeholder="搜索都市圈，如 Atlanta / New York / St. Louis">
  <div class="results" id="results"></div>
</div>
<div class="legend">
  <div><span class="sw" style="background:#2b6cb0"></span>经济都市圈（成员完整）</div>
  <div><span class="sw" style="background:#dd6b20"></span>经济都市圈（有缺失成员）</div>
  <div><span class="sw" style="background:#cbd5e1"></span>行政州界（GADM）</div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script>
const METRO = __METRO__;
const STATES = __STATE__;

var map = L.map('map').setView([38.5,-96], 4);
var base = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',
  {maxZoom:12, attribution:'&copy; OpenStreetMap'}).addTo(map);

var stateLayer = L.geoJSON(STATES, {style:function(){return {color:'#94a3b8',weight:1,fill:false};}});
stateLayer.bindTooltip(function(l){return l.feature.properties.NAME_1;}, {sticky:true});

function metroStyle(f){
  var miss = f.properties.n_missing || 0;
  return {color:'#0f2b4c', weight:1.2,
          fillColor: miss>0 ? '#dd6b20' : '#2b6cb0',
          fillOpacity: miss>0 ? 0.5 : 0.35};
}
var layerById = {};
function popupHTML(p){
  var h = '<div class="pp"><div class="t">'+p.metro_name+'</div>';
  h += '<div class="m">CBSA '+p.cbsa_code+' · 面积 '+fmt(p.area_km2)+' km²</div>';
  h += '<div class="m">成员县 '+p.n_members+'（已匹配 '+p.n_matched+'，缺失 '+p.n_missing+'）</div>';
  h += '<div class="m">审核 v'+p.version+' · '+p.last_action+(p.reviewer?' · '+p.reviewer:'')+'</div>';
  if(p.involved_states){ h += '<div class="m">涉及州：'+p.involved_states+'</div>'; }
  if(p.members && p.members.length){
    h += '<div class="memlist">';
    p.members.forEach(function(m){
      var tag = m.review_status==='confirmed_missing' ? '<span class="tag bad">缺失</span>'
        : (m.match_method==='missing' ? '<span class="tag warn">未匹配</span>'
          : '<span class="tag ok">'+m.match_method+'</span>');
      h += '<div class="memb">'+m.county_name+' <span class="st">'+m.state_name+'</span>'+tag+'</div>';
    });
    h += '</div>';
  }
  h += '</div>';
  return h;
}
var metroLayer = L.geoJSON(METRO, {
  style: metroStyle,
  onEachFeature: function(f, layer){
    layerById[f.properties.metro_id] = layer;
    layer.bindPopup(popupHTML(f.properties));
    layer.on('mouseover', function(){layer.setStyle({weight:2.5, fillOpacity:0.65}); layer.bringToFront();});
    layer.on('mouseout', function(){layer.setStyle(metroStyle(f));});
  }
});

stateLayer.addTo(map);
metroLayer.addTo(map);
L.control.layers({'OSM 底图': base}, {'行政州界': stateLayer, '经济都市圈(88)': metroLayer},
  {collapsed:false}).addTo(map);

// 摘要
(function(){
  var a={metros:METRO.features.length, members:0, matched:0, missing:0};
  METRO.features.forEach(function(f){
    a.members += f.properties.n_members; a.matched += f.properties.n_matched; a.missing += f.properties.n_missing;
  });
  document.getElementById('summary').innerHTML =
    '<b>'+a.metros+'</b> 都市圈 · <b>'+a.members+'</b> 成员县 · 匹配 <b>'+a.matched+'</b> · 缺失 <b>'+a.missing+'</b>';
})();

// 搜索
var idx = METRO.features.map(function(f){
  return {id:f.properties.metro_id, name:f.properties.metro_name,
          bbox:f.properties.bbox, bounds:L.latLngBounds([[f.properties.bbox[1],f.properties.bbox[0]],[f.properties.bbox[3],f.properties.bbox[2]]])};
});
var q=document.getElementById('q'), res=document.getElementById('results');
q.addEventListener('input', function(){
  var t=q.value.toLowerCase(); res.innerHTML=''; res.style.display='none';
  if(!t){return;}
  var hits=idx.filter(function(x){return x.name.toLowerCase().indexOf(t)>=0;}).slice(0,20);
  if(hits.length){res.style.display='block';}
  hits.forEach(function(x){
    var d=document.createElement('div'); d.className='item'; d.textContent=x.name;
    d.onclick=function(){
      map.fitBounds(x.bounds, {padding:[24,24], maxZoom:9});
      var ly=layerById[x.id]; if(ly){ly.openPopup();}
      res.style.display='none'; q.value=x.name;
    };
    res.appendChild(d);
  });
});
document.addEventListener('click', function(e){ if(!e.target.closest('.search')){res.style.display='none';} });

function fmt(n){ return (n||0).toLocaleString('en-US'); }
</script>
</body>
</html>
"""

html = HTML.replace('__METRO__', metro_js).replace('__STATE__', state_js)
with open(OUT, 'w', encoding='utf-8') as f:
    f.write(html)

print('已生成', OUT)
print('体积 %.1f KB' % (os.path.getsize(OUT) / 1024))
print('都市圈 feature', len(feats), '· 州 feature', len(st))
