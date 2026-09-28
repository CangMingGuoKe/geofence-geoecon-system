# -*- coding: utf-8 -*-
"""
步骤 9 · 生成「日本经济都市圈」地图图层数据，供 GADM/interactive_map.html 挂接。

输出：GADM/map_data/JPN_metro.js（window.JPN_METRO + window.JPN_METRO_SEARCH）
数据：07_日本都市圈边界.geojson（并集几何）+ 07_日本都市圈一览.csv + 07_日本都市圈成员关系.csv
格式：与美国样例完全对齐（原始经纬度 + JS 端墨卡托投影，简化 0.005 度）。
差别：日本还没做步骤 8 的人工审核，所以版本一律 1、状态取机器结果（matched / missing）。

零侵入：只新增一个 map_data/JPN_metro.js，不改现有任何 .js。
"""
import csv, json, os, sys
sys.stdout.reconfigure(encoding='utf-8')
import geopandas as gpd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(ROOT, 'GADM/map_data/JPN_metro.js')
SIMPLIFY = 0.005          # 度，约 550 米，与美国样例一致


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


summary = {r['metro_id']: r for r in rd('07_日本都市圈一览.csv')}
members = {}
for r in rd('07_日本都市圈成员关系.csv'):
    members.setdefault(r['metro_id'], []).append({
        'n': r['member_name'], 'st': r['pref_name'] or '未匹配',
        'mm': r['match_method'], 'rs': 'missing' if not r['gid_2'] else 'matched',
        'jis': r['member_jis'], 'gid': r['gid_2'], 'type': r['type_2'],
    })

gdf = gpd.read_file(os.path.join(HERE, '07_日本都市圈边界.geojson')).to_crs(4326)
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
    metro_list.append({
        'n': p['metro_name'], 'id': mid,
        'cbsa': '',                                     # 日本无 CBSA，留空
        'oe': s.get('n_members', ''),                   # 占位列，保持与美国字段对齐
        'nm': int(s.get('n_members', len(members.get(mid, [])))),
        'nmatch': int(s.get('n_matched', 0)),
        'nmiss': int(s.get('n_missing', 0)),
        'area': int(round(float(s.get('area_km2_epsg6933', 0) or 0))),
        'ver': 1, 'last': '机器结果（未人工审核）', 'reviewer': '',
        'prefs': s.get('prefs', ''),
        'members': members.get(mid, []),
        'c': rings, 'b': bbox_of(rings),
    })

search = [{'t': 3, 'zh': '', 'en': m['n'], 'loc': m['n'], 'iso3': 'JPN', 'mid': m['id'], 'b': m['b']}
          for m in metro_list]

with open(OUT, 'w', encoding='utf-8') as f:
    f.write('window.JPN_METRO = ' + json.dumps(metro_list, ensure_ascii=False, separators=(',', ':')) + ';\n')
    f.write('window.JPN_METRO_SEARCH = ' + json.dumps(search, ensure_ascii=False, separators=(',', ':')) + ';\n')

print('已生成 %s' % OUT)
print('  都市圈 %d 个 | 成员 %d 条 | 体积 %.0f KB'
      % (len(metro_list), sum(len(m['members']) for m in metro_list), os.path.getsize(OUT) / 1024))
