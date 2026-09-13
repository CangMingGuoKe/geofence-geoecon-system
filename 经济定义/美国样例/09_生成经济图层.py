# -*- coding: utf-8 -*-
"""
步骤9 · 生成「经济都市圈」地图图层数据，供 GADM/interactive_map.html 挂接。

输出：D:/.../GADM/map_data/USA_metro.js（window.USA_METRO + window.USA_METRO_SEARCH）
数据：07 都市圈边界.geojson（union 几何）+ 08 审核状态/版本记录 + 07 一览
格式：对齐现有 map_data/*.js 的「原始经纬度 + JS 端墨卡托投影」约定（preproject 模式）。

零侵入：只【新增】一个 map_data/USA_metro.js，不改现有任何 .js / html。
"""
import json, csv, os
import geopandas as gpd

HERE = os.path.dirname(os.path.abspath(__file__))
METRO_GJ = os.path.join(HERE, '07_美国都市圈边界.geojson')
SUMMARY_CSV = os.path.join(HERE, '07_美国都市圈一览.csv')
REVIEW_CSV = os.path.join(HERE, '08_审核状态.csv')
VERSION_CSV = os.path.join(HERE, '08_版本记录.csv')
OUT = r'D:\Desktop\科研--深圳数据经济研究院\地理围栏体系\GADM\map_data\USA_metro.js'

SIMPLIFY = 0.005  # 度，约 550m；演示精度足够，精确边界以 07_*.gpkg 为准


def rd(path):
    with open(path, encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def rings_from(geom):
    """把 Polygon/MultiPolygon 拆成「外环 + 内环(孔洞)」坐标环列表，坐标取整到 4 位小数。"""
    polys = [geom] if geom.geom_type == 'Polygon' else list(geom.geoms)
    out = []
    for g in polys:
        if g.geom_type != 'Polygon' or g.is_empty:
            continue
        out.append([[round(x, 4), round(y, 4)] for x, y in g.exterior.coords])
        for h in g.interiors:
            out.append([[round(x, 4), round(y, 4)] for x, y in h.coords])
    return out


def bbox_of(rings):
    xs = [p[0] for r in rings for p in r]
    ys = [p[1] for r in rings for p in r]
    return [round(min(xs), 4), round(min(ys), 4), round(max(xs), 4), round(max(ys), 4)]


summary = {r['metro_id']: r for r in rd(SUMMARY_CSV)}
version = {r['metro_id']: r for r in rd(VERSION_CSV)}
members = {}
for r in rd(REVIEW_CSV):
    members.setdefault(r['metro_id'], []).append({
        'n': r['county_name'], 'st': r['state_name'],
        'mm': r['match_method'], 'rs': r['review_status'],
        'fips': r['fips5'], 'gid': r['gid_2'], 'hasc': r['hasc_2'],
    })

gdf = gpd.read_file(METRO_GJ).to_crs(4326)
gdf['geometry'] = gdf.geometry.simplify(SIMPLIFY, preserve_topology=True)

metro_list = []
for _, row in gdf.iterrows():
    p = dict(row)
    mid = p['metro_id']
    s = summary.get(mid, {}); v = version.get(mid, {})
    rings = rings_from(row.geometry)
    if not rings:
        continue
    metro_list.append({
        'n': p['metro_name'], 'id': mid, 'cbsa': str(p.get('cbsa_code', '')),
        'nm': int(s.get('n_members_total', p.get('n_members', 0))),
        'nmatch': int(s.get('n_matched', 0)),
        'nmiss': int(s.get('n_missing', p.get('n_missing', 0))),
        'area': int(round(float(s.get('area_km2_epsg5070', 0) or 0))),
        'ver': int(v.get('version', 0)), 'last': v.get('last_action', ''),
        'reviewer': v.get('last_reviewer', ''),
        'members': members.get(mid, []),
        'c': rings, 'b': bbox_of(rings),
    })

search = []
for m in metro_list:
    search.append({'t': 3, 'zh': '', 'en': m['n'], 'loc': m['n'], 'iso3': 'USA', 'mid': m['id'], 'b': m['b']})

with open(OUT, 'w', encoding='utf-8') as f:
    f.write('window.USA_METRO = ' + json.dumps(metro_list, ensure_ascii=False, separators=(',', ':')) + ';\n')
    f.write('window.USA_METRO_SEARCH = ' + json.dumps(search, ensure_ascii=False, separators=(',', ':')) + ';\n')

print('已生成', OUT)
print('都市圈 feature:', len(metro_list))
print('体积 %.1f KB' % (os.path.getsize(OUT) / 1024))
