# -*- coding: utf-8 -*-
"""
沙特经济定义层：生成 5 个都市圈的边界，并做质量检查。

做法同美国、日本、巴西：把每个都市圈匹配上的省边界取并集。沙特特有的几点：
1. 面积用 EPSG:6933（全球等积圆柱）。已用三种独立算法互证：GADM 沙特 L3 的测地面积
   1,922,800 km²、EPSG:6933 下 1,923,037 km²、沙特本地 Albers 等积投影下 1,922,737 km²，
   三者相差 0.02% 以内，说明投影选得对。**但 GADM 沙特几何合计比外部公开的国土面积参考值（非本项目数据，库内未留源）
   2,149,690 km² 少 10.55%**，这是 GADM 沙特边界覆盖本身的缺口，不是投影或处理问题，
   使用时须知道（巴西同级对比只差 0.08%）。
2. 沙特的「市」在源表里定义为 Governorate（省），边界含义是**整个省**而非城区，
   与欧洲 City Proper 同类。Dammam 是三省聚合，另 4 城是一城一省。
3. Dammam 的成员 Dammam 在 GADM 里没有对应单元（真缺口），故 Dammam 圈由 2 个省拼成、缺 1 块。

产出：05 两个样例、07 全部边界与一览、07 成员关系
"""
import collections
import csv
import json
import glob
import os
import sys

import geopandas as gpd
from shapely.geometry import Polygon
from shapely.ops import unary_union

sys.stdout.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
GEO = glob.glob(os.path.join(ROOT, 'GADM/geojson/SAU_*'))[0]
AREA_CRS = 'EPSG:6933'


def rd(name):
    with open(os.path.join(HERE, name), encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def wr(name, rows):
    with open(os.path.join(HERE, name), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main():
    matched = rd('04_匹配结果_全量.csv')
    gj = gpd.read_file(os.path.join(GEO, 'SAU_L3_adm2.geojson'))
    geom = dict(zip(gj['GID_2'], gj.geometry))
    region = dict(zip(gj['GID_2'], gj['NAME_1']))

    by_city = collections.OrderedDict()
    for r in matched:
        by_city.setdefault(r['metro_id'], []).append(r)

    feats, overview, relations, areas = [], [], [], {}
    for mid, rows in by_city.items():
        name = rows[0]['metro_name']
        ok = [r for r in rows if r['gid_2']]
        miss = [r for r in rows if not r['gid_2']]
        gids = [r['gid_2'] for r in ok]
        dup = [k for k, v in collections.Counter(gids).items() if v > 1]
        boundary = unary_union([geom[g] for g in gids]) if gids else None
        if boundary is None:
            print('  跳过无匹配成员的 %s' % name)
            continue
        polys = [boundary] if boundary.geom_type == 'Polygon' else list(boundary.geoms)
        holes = [h for p in polys for h in p.interiors]
        hole_area = (gpd.GeoSeries([Polygon(h) for h in holes], crs='EPSG:4326')
                     .to_crs(AREA_CRS).area.sum() / 1e6) if holes else 0.0
        area = gpd.GeoSeries([boundary], crs='EPSG:4326').to_crs(AREA_CRS).area.iloc[0] / 1e6
        regions = sorted(set(region[g] for g in gids))
        areas[mid] = area
        feats.append({'type': 'Feature',
                      'properties': {'metro_id': mid, 'metro_name': name,
                                     'n_members': len(rows), 'n_missing': len(miss),
                                     'n_regions': len(regions), 'regions': '、'.join(regions)},
                      'geometry': boundary.__geo_interface__})
        overview.append({'metro_id': mid, 'metro_name': name, 'n_members': len(rows),
                         'n_matched': len(ok), 'n_missing': len(miss),
                         'n_regions': len(regions), 'regions': '、'.join(regions),
                         'geom_type': boundary.geom_type, 'n_parts': len(polys),
                         'n_holes': len(holes), 'hole_area_km2': round(hole_area, 1),
                         'is_valid': boundary.is_valid, 'is_empty': boundary.is_empty,
                         'area_km2_epsg6933': round(area, 1), 'dup_gid': len(dup)})
        for r in rows:
            relations.append({'metro_id': mid, 'metro_name': name,
                              'member_name': r['member_name'], 'member_role': r['member_role'],
                              'region_name': region.get(r['gid_2'], ''), 'province_name': r['gadm_name'],
                              'gid_2': r['gid_2'], 'type_2': r['type_2'],
                              'match_method': r['match_method'], 'confidence': r['confidence']})

    # 样例：成员最多的那个（Dammam，三省聚合）+ 面积最大的单成员圈
    multi = max(overview, key=lambda r: (int(r['n_members']), r['metro_id']))
    rest = [r for r in overview if r['metro_id'] != multi['metro_id']]
    big = max(rest, key=lambda r: float(r['area_km2_epsg6933'])) if rest else None
    for pick in (multi, big):
        if not pick:
            continue
        mid = pick['metro_id']
        f = [x for x in feats if x['properties']['metro_id'] == mid][0]
        wr('05_%s_成员表.csv' % mid,
           [{k: r[k] for k in ('metro_id', 'metro_name', 'member_name', 'member_role',
                               'region_name', 'gadm_name', 'gid_2', 'type_2', 'match_method')
             if k in r} for r in by_city[mid]])
        with open(os.path.join(HERE, '05_%s_都市圈边界.geojson' % mid), 'w', encoding='utf-8') as fh:
            json.dump({'type': 'FeatureCollection', 'features': [f]}, fh, ensure_ascii=False)
        print('  已写 05_%s（%s）：%d 成员，%d 块，面积 %.0f km²'
              % (mid, pick['metro_name'], int(pick['n_members']), int(pick['n_parts']),
                 float(pick['area_km2_epsg6933'])))

    with open(os.path.join(HERE, '07_沙特都市圈边界.geojson'), 'w', encoding='utf-8') as f:
        json.dump({'type': 'FeatureCollection', 'features': feats}, f, ensure_ascii=False)
    gpd.GeoDataFrame.from_features(feats, crs='EPSG:4326').to_file(
        os.path.join(HERE, '07_沙特都市圈边界.gpkg'), driver='GPKG', layer='07_沙特都市圈边界')
    wr('07_沙特都市圈成员关系.csv', relations)
    wr('07_沙特都市圈一览.csv', overview)
    print('  已写 07 全部产物（%d 个都市圈）' % len(feats))
    return overview, relations


if __name__ == '__main__':
    ov, rel = main()
    print()
    print('=== 质量检查 ===')
    print('  都市圈 %d 个 | 成员关系 %d 条' % (len(ov), len(rel)))
    print('  未匹配缺口合计: %d' % sum(int(r['n_missing']) for r in ov))
    print('  同一都市圈内重复 GID: %d' % sum(int(r['dup_gid']) for r in ov))
    print('  空几何: %d | 无效几何: %d'
          % (sum(1 for r in ov if str(r['is_empty']) == 'True'),
             sum(1 for r in ov if str(r['is_valid']) != 'True')))
    a = sorted(float(r['area_km2_epsg6933']) for r in ov)
    print('  面积范围: %.0f ~ %.0f km²，中位 %.0f' % (a[0], a[-1], a[len(a) // 2]))
    print('  跨区都市圈: %d 个' % sum(1 for r in ov if int(r['n_regions']) > 1))
    print()
    print('  %-12s %4s %4s %3s %4s %4s %6s %10s' % ('都市圈', '成员', '匹配', '缺', '跨区', '块数', '孔洞', '面积km²'))
    for r in ov:
        print('  %-12s %4s %4s %3s %4s %4s %6s %10s'
              % (r['metro_name'][:12], r['n_members'], r['n_matched'], r['n_missing'],
                 r['n_regions'], r['n_parts'], r['n_holes'], r['area_km2_epsg6933']))
