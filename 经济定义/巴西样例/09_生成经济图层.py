# -*- coding: utf-8 -*-
"""
步骤 9 · 生成「巴西经济都市圈」地图图层数据，供 GADM/interactive_map.html 挂接。

输出：GADM/map_data/BRA_metro.js（window.BRA_METRO + window.BRA_METRO_SEARCH）
数据：07_巴西都市圈边界.geojson（并集几何）+ 07_巴西都市圈一览.csv + 07_巴西都市圈成员关系.csv，
      并读取步骤 8 的审核结果（若已跑过）带上版本与状态。
格式：与美国、日本完全对齐（原始经纬度 + JS 端墨卡托投影，简化 0.005 度）。
差别：巴西源表没有成员代码，成员以名称标识，故成员条不含代码字段，另带 IBGE 代码供核对。
零侵入：只新增一个 map_data/BRA_metro.js，不改现有任何 .js。
"""
import csv
import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
import geopandas as gpd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(ROOT, 'GADM/map_data/BRA_metro.js')
SIMPLIFY = 0.005          # 度，约 550 米，与美国、日本样例一致


def rd(name):
    with open(os.path.join(HERE, name), encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def rings_from(geom):
    """把 Polygon / MultiPolygon 拆成「外环 + 内环」坐标环，坐标取整到 4 位小数"""
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


summary = {r['metro_id']: r for r in rd('07_巴西都市圈一览.csv')}
# 步骤 8 的审核结果（若已跑过）：状态按成员、版本按都市圈
review, version = {}, {}
if os.path.exists(os.path.join(HERE, '08_审核状态.csv')):
    review = {(r['metro_id'], r['member_name']): r for r in rd('08_审核状态.csv')}
if os.path.exists(os.path.join(HERE, '08_版本记录.csv')):
    version = {r['metro_id']: r for r in rd('08_版本记录.csv')}

members = {}
for r in rd('07_巴西都市圈成员关系.csv'):
    rv = review.get((r['metro_id'], r['member_name']), {})
    members.setdefault(r['metro_id'], []).append({
        'n': r['member_name'],                       # 成员名（巴西无成员代码，名称即定位键）
        'st': r['state_name'] or '未匹配',
        'mm': r['match_method'],
        'rs': rv.get('review_status') or ('missing' if not r['gid_2'] else 'matched'),
        'gid': r['gid_2'], 'type': r['type_2'], 'cc': r['cc_2'], 'role': r['member_role'],
    })

gdf = gpd.read_file(os.path.join(HERE, '07_巴西都市圈边界.geojson')).to_crs(4326)
gdf['geometry'] = gdf.geometry.simplify(SIMPLIFY, preserve_topology=True)

metro_list = []
for _, row in gdf.iterrows():
    p = dict(row)
    mid = p['metro_id']
    s = summary.get(mid, {})
    rings = rings_from(row.geometry)
    if not rings:
        print('  跳过无几何的 %s' % mid)
        continue
    states = s.get('states', '')
    metro_list.append({
        'n': p['metro_name'], 'id': mid,
        'cbsa': '',                                     # 巴西无 CBSA，留空
        'oe': s.get('n_members', ''),                   # 占位列，保持与美日字段对齐
        'nm': int(s.get('n_members', len(members.get(mid, [])))),
        'nmatch': int(s.get('n_matched', 0)),
        'nmiss': int(s.get('n_missing', 0)),
        'area': int(round(float(s.get('area_km2_epsg6933', 0) or 0))),
        'ver': int(version.get(mid, {}).get('version', 0) or 0),
        'last': version.get(mid, {}).get('last_action', '') or '机器结果（未人工审核）',
        'reviewer': version.get(mid, {}).get('last_reviewer', ''),
        'prefs': states, 'states': states,               # 美日用 prefs、巴西用 states，两个键都给
        'members': members.get(mid, []),
        'c': rings, 'b': bbox_of(rings),
    })

search = [{'t': 3, 'zh': '', 'en': m['n'], 'loc': m['n'], 'iso3': 'BRA', 'mid': m['id'], 'b': m['b']}
          for m in metro_list]

with open(OUT, 'w', encoding='utf-8') as f:
    f.write('window.BRA_METRO = ' + json.dumps(metro_list, ensure_ascii=False, separators=(',', ':')) + ';\n')
    f.write('window.BRA_METRO_SEARCH = ' + json.dumps(search, ensure_ascii=False, separators=(',', ':')) + ';\n')

print('已生成 %s' % OUT)
print('  都市圈 %d 个 | 成员 %d 条 | 体积 %.0f KB'
      % (len(metro_list), sum(len(m['members']) for m in metro_list), os.path.getsize(OUT) / 1024))
