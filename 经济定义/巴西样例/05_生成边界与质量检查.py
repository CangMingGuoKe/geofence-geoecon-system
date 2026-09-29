# -*- coding: utf-8 -*-
"""
巴西经济定义层：生成 26 个都市圈 / 城市的边界，并做质量检查。

做法同美国、日本：把每个都市圈匹配上的市镇边界取并集。巴西特有的几点：
1. 面积用 EPSG:6933（全球等积圆柱），与美国用的 EPSG:5070（北美专用）区分开；实测 GADM 巴西
   L3 市镇层合计 8,509,068 km²，与外部公开的国土面积参考值（非本项目数据，库内未留源） 8,515,767 km² 相差 0.08%，量级与精度都成立。
2. 「单市」城市（源表没有成员行，城市自身即成员，member_role=self）只有 1 个成员，
   边界就是该市镇本身，质量检查里与多成员的都市圈一并统计。
3. 已剔除 Cuiabá RM（源表错标，成员名单与 Curitiba RM 相同），故都市圈编号有跳号（缺 BRM08）。
4. 跨州数与日本「跨县数」同义：巴西的都市圈基本都在一个州内，跨州情况由脚本统计后如实报出。

产出：05 两个样例、07 全部边界与一览、07 成员关系
"""
import collections
import csv
import json
import os
import sys

import geopandas as gpd
from shapely.geometry import Polygon
from shapely.ops import unary_union

sys.stdout.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
GEO = os.path.join(ROOT, 'GADM/geojson/BRA_巴西')
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
    matched = [r for r in rd('04_匹配结果_全量.csv')
               if r['match_method'] != 'excluded_source_issue']
    gj = gpd.read_file(os.path.join(GEO, 'BRA_L3_adm2.geojson'))
    geom = dict(zip(gj['GID_2'], gj.geometry))
    state = dict(zip(gj['GID_2'], gj['NAME_1']))

    by_city = collections.OrderedDict()
    for r in matched:
        by_city.setdefault(r['metro_id'], []).append(r)

    # 样例：取成员最多的一个，与成员最少（但多于 1 个）的一个
    sizes = sorted(((len(v), k) for k, v in by_city.items()), reverse=True)
    sample = {sizes[0][1]}
    small = [k for n, k in reversed(sizes) if n > 1]
    if small:
        sample.add(small[0])

    feats, overview, relations, holes_report = [], [], [], []
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
        states = sorted(set(state[g] for g in gids))
        feats.append({'type': 'Feature',
                      'properties': {'metro_id': mid, 'metro_name': name,
                                     'n_members': len(rows), 'n_missing': len(miss),
                                     'n_states': len(states), 'states': '、'.join(states)},
                      'geometry': boundary.__geo_interface__})
        overview.append({'metro_id': mid, 'metro_name': name, 'n_members': len(rows),
                         'n_matched': len(ok), 'n_missing': len(miss),
                         'n_states': len(states), 'states': '、'.join(states),
                         'geom_type': boundary.geom_type, 'n_parts': len(polys),
                         'n_holes': len(holes), 'hole_area_km2': round(hole_area, 1),
                         'is_valid': boundary.is_valid, 'is_empty': boundary.is_empty,
                         'area_km2_epsg6933': round(area, 1), 'dup_gid': len(dup)})
        if holes:
            holes_report.append((name, len(holes), round(hole_area, 1)))
        for r in rows:
            relations.append({'metro_id': mid, 'metro_name': name,
                              'member_name': r['member_name'], 'member_role': r['member_role'],
                              'state_name': state.get(r['gid_2'], ''), 'muni_name': r['gadm_name'],
                              'gid_2': r['gid_2'], 'cc_2': r['cc_2'], 'type_2': r['type_2'],
                              'match_method': r['match_method'], 'confidence': r['confidence']})
        if mid in sample:
            wr('05_%s_成员表.csv' % mid,
               [{k: r[k] for k in ('metro_id', 'metro_name', 'member_name', 'member_role',
                                   'gadm_name', 'gid_2', 'cc_2', 'match_method')} for r in rows])
            with open(os.path.join(HERE, '05_%s_都市圈边界.geojson' % mid), 'w', encoding='utf-8') as f:
                json.dump({'type': 'FeatureCollection', 'features': [feats[-1]]}, f, ensure_ascii=False)
            print('  已写 05_%s（%s）：%d 成员，%s，%d 块，面积 %.0f km²'
                  % (mid, name, len(rows), boundary.geom_type, len(polys), area))

    with open(os.path.join(HERE, '07_巴西都市圈边界.geojson'), 'w', encoding='utf-8') as f:
        json.dump({'type': 'FeatureCollection', 'features': feats}, f, ensure_ascii=False)
    gpd.GeoDataFrame.from_features(feats, crs='EPSG:4326').to_file(
        os.path.join(HERE, '07_巴西都市圈边界.gpkg'), driver='GPKG', layer='07_巴西都市圈边界')
    wr('07_巴西都市圈成员关系.csv', relations)
    wr('07_巴西都市圈一览.csv', overview)
    print('  已写 07 全部产物（%d 个都市圈）' % len(feats))
    return overview, relations, holes_report


if __name__ == '__main__':
    ov, rel, hr = main()
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
    print('  跨州都市圈: %d 个' % sum(1 for r in ov if int(r['n_states']) > 1))
    print('  有孔洞的都市圈: %d 个' % len(hr))
    print()
    print('  %-30s %4s %4s %3s %4s %5s %4s %9s' % ('都市圈', '成员', '匹配', '缺', '跨州', '块数', '孔洞', '面积km²'))
    for r in ov:
        print('  %-30s %4s %4s %3s %4s %5s %4s %9s'
              % (r['metro_name'][:30], r['n_members'], r['n_matched'], r['n_missing'],
                 r['n_states'], r['n_parts'], r['n_holes'], r['area_km2_epsg6933']))
