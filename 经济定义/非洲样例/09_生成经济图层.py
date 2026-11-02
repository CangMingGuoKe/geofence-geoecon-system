# -*- coding: utf-8 -*-
"""
步骤 9 · 生成「非洲三国经济都市圈」地图图层数据，供 GADM/interactive_map.html 挂接。
（沿用第四步的编号习惯，与前四例保持一致。）

输出：GADM/map_data/ZAF_metro.js、EGY_metro.js、NGA_metro.js
      每个文件含 window.<ISO3>_METRO 与 window.<ISO3>_METRO_SEARCH。
数据：07_非洲都市圈边界.geojson（并集几何）+ 07_非洲都市圈一览.csv
      + 07_非洲都市圈成员关系.csv，并读取步骤 8 的审核结果（若已跑过）。
格式：与美国、日本、巴西、沙特完全对齐（原始经纬度 + JS 端墨卡托投影，简化 0.005 度）。
零侵入：只新增三个 map_data/*_metro.js，不改现有任何 .js。
"""
import csv
import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
import geopandas as gpd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT_DIR = os.path.join(ROOT, 'GADM', 'map_data')
SIMPLIFY = 0.005


def rd(name):
    with open(os.path.join(HERE, name), encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def rings_from(geom):
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


summary = {r['metro_id']: r for r in rd('07_非洲都市圈一览.csv')}
relations = rd('07_非洲都市圈成员关系.csv')
review = {}
if os.path.exists(os.path.join(HERE, '08_审核状态.csv')):
    review = {(r['metro_id'], r['member_name']): r for r in rd('08_审核状态.csv')}
version = {}
if os.path.exists(os.path.join(HERE, '08_版本记录.csv')):
    version = {r['metro_id']: r for r in rd('08_版本记录.csv')}

members = {}
for r in relations:
    rv = review.get((r['metro_id'], r['member_name']), {})
    members.setdefault(r['metro_id'], []).append({
        'n': r['member_name'],
        'st': r['parent_name'] or '未匹配',
        'mm': r['match_method'],
        'rs': rv.get('review_status') or ('missing' if not r['gid'] else 'matched'),
        'gid': r['gid'], 'type': r['type'], 'role': r['member_role'], 'lv': r['level'],
    })

gdf = gpd.read_file(os.path.join(HERE, '07_非洲都市圈边界.geojson')).to_crs(4326)
gdf['geometry'] = gdf.geometry.simplify(SIMPLIFY, preserve_topology=True)

by_country = {}
for _, row in gdf.iterrows():
    p = dict(row)
    mid = p['metro_id']
    s = summary.get(mid, {})
    rings = rings_from(row.geometry)
    if not rings:
        print('  跳过无几何的 %s' % mid)
        continue
    parents = s.get('parents', '')
    v = version.get(mid, {})
    by_country.setdefault(mid[:3], []).append({
        'n': p['metro_name'], 'id': mid,
        'cbsa': '',
        'oe': mid,                                  # 保留 OE 城市代码，便于回溯源表
        'nm': int(s.get('n_members', len(members.get(mid, [])))),
        'nmatch': int(s.get('n_matched', 0)),
        'nmiss': int(s.get('n_missing', 0)),
        'area': int(round(float(s.get('area_km2_epsg6933', 0) or 0))),
        'ver': int(v.get('version', 0) or 0),
        'last': v.get('last_action', '') or '机器结果（未人工审核）',
        'reviewer': v.get('last_reviewer', ''),
        'prefs': parents, 'regions': parents,
        'members': members.get(mid, []),
        'c': rings, 'b': bbox_of(rings),
    })

for iso3, lst in by_country.items():
    search = [{'t': 3, 'zh': '', 'en': m['n'], 'loc': m['n'], 'iso3': iso3,
               'mid': m['id'], 'b': m['b']} for m in lst]
    out = os.path.join(OUT_DIR, '%s_metro.js' % iso3)
    with open(out, 'w', encoding='utf-8') as f:
        f.write('window.%s_METRO = ' % iso3 + json.dumps(lst, ensure_ascii=False, separators=(',', ':')) + ';\n')
        f.write('window.%s_METRO_SEARCH = ' % iso3 + json.dumps(search, ensure_ascii=False, separators=(',', ':')) + ';\n')
    print('已生成 %s' % out)
    print('  都市圈 %d 个 | 成员 %d 条 | 体积 %.0f KB'
          % (len(lst), sum(len(m['members']) for m in lst), os.path.getsize(out) / 1024))
