# -*- coding: utf-8 -*-
"""
日本经济定义层：生成 14 个都市圈的边界，并做质量检查。

做法同美国：把每个都市圈匹配上的市町村边界取并集。日本特有的两点：
1. 面积用 EPSG:6933（全球等积圆柱），因为美国用的 EPSG:5070 是北美专用；实测日本 L3 合计 372,465 km²，
   与国土面积参考值 377,975 km²（含水域）量级相符。
2. 3 个成员在 GADM 里没有对应几何（Ama、Itoshima 是 2010 年合并后新设、GADM 仍是合并前单元；
   Kisosaki 被 GADM 错记在 Aichi 县下），所以对应都市圈的边界会缺一块，质量检查里单独统计。

产出：05 两个样例、07 全部边界与一览、07 成员关系、07 质量检查报告
"""
import csv, json, os, collections, sys
import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union
from shapely.geometry import Polygon

sys.stdout.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
AREA_CRS = 'EPSG:6933'          # 全球等积圆柱投影，用于面积统计
SAMPLE = ['JPM06', 'JPM01']     # 样例：札幌（单县）、东京（跨县）


def rd(name):
    return list(csv.DictReader(open(os.path.join(HERE, name), encoding='utf-8-sig')))


def wr(name, rows):
    with open(os.path.join(HERE, name), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main():
    matched = rd('04_匹配结果_全量.csv')
    gj = gpd.read_file(os.path.join(ROOT, 'GADM/geojson/JPN_日本/JPN_L3_adm2.geojson'))
    geom = dict(zip(gj['GID_2'], gj.geometry))
    pref = dict(zip(gj['GID_2'], gj['NAME_1']))

    by_city = collections.OrderedDict()
    for r in matched:
        by_city.setdefault(r['metro_id'], []).append(r)

    feats, overview, relations = [], [], []
    for mid, rows in by_city.items():
        name = rows[0]['metro_name']
        ok = [r for r in rows if r['gid_2']]
        miss = [r for r in rows if not r['gid_2']]
        gids = [r['gid_2'] for r in ok]
        dup = [k for k, v in collections.Counter(gids).items() if v > 1]
        pieces = [geom[g] for g in gids]
        boundary = unary_union(pieces)
        polys = [boundary] if boundary.geom_type == 'Polygon' else list(boundary.geoms)
        holes = [h for p in polys for h in p.interiors]
        hole_area = gpd.GeoSeries([Polygon(h) for h in holes],
                                  crs='EPSG:4326').to_crs(AREA_CRS).area.sum() / 1e6 if holes else 0.0
        area = gpd.GeoSeries([boundary], crs='EPSG:4326').to_crs(AREA_CRS).area.iloc[0] / 1e6
        prefs = sorted(set(pref[g] for g in gids))
        feats.append({'type': 'Feature',
                      'properties': {'metro_id': mid, 'metro_name': name,
                                     'n_members': len(rows), 'n_missing': len(miss),
                                     'n_prefs': len(prefs), 'prefs': '、'.join(prefs)},
                      'geometry': boundary.__geo_interface__})
        overview.append({'metro_id': mid, 'metro_name': name, 'n_members': len(rows),
                         'n_matched': len(ok), 'n_missing': len(miss),
                         'n_prefs': len(prefs), 'prefs': '、'.join(prefs),
                         'geom_type': boundary.geom_type, 'n_parts': len(polys),
                         'n_holes': len(holes), 'hole_area_km2': round(hole_area, 1),
                         'is_valid': boundary.is_valid, 'is_empty': boundary.is_empty,
                         'area_km2_epsg6933': round(area, 1), 'dup_gid': len(dup)})
        for r in rows:
            relations.append({'metro_id': mid, 'metro_name': name, 'member_name': r['member_name'],
                              'member_jis': r['member_jis'], 'pref_name': pref.get(r['gid_2'], ''),
                              'muni_name': r['gadm_name'], 'gid_2': r['gid_2'], 'type_2': r['type_2'],
                              'match_method': r['match_method'], 'confidence': r['confidence']})
        if mid in SAMPLE:
            tag = 'JPM06' if mid == 'JPM06' else 'JPM13'
            wr('05_%s_成员表.csv' % tag, [{k: r[k] for k in
                ('metro_id', 'metro_name', 'member_name', 'member_jis', 'gadm_name', 'gid_2', 'type_2', 'match_method')
                if k in r} for r in rows])
            with open(os.path.join(HERE, '05_%s_都市圈边界.geojson' % tag), 'w', encoding='utf-8') as f:
                json.dump({'type': 'FeatureCollection', 'features': [
                    feats[-1]]}, f, ensure_ascii=False)
            print('  已写 05_%s（%s）：%d 成员，%s，%d 块，面积 %.0f km²'
                  % (tag, name, len(rows), boundary.geom_type, len(polys), area))

    with open(os.path.join(HERE, '07_日本都市圈边界.geojson'), 'w', encoding='utf-8') as f:
        json.dump({'type': 'FeatureCollection', 'features': feats}, f, ensure_ascii=False)
    gpd.GeoDataFrame.from_features(feats, crs='EPSG:4326').to_file(
        os.path.join(HERE, '07_日本都市圈边界.gpkg'), driver='GPKG', layer='07_日本都市圈边界')
    wr('07_日本都市圈成员关系.csv', relations)
    wr('07_日本都市圈一览.csv', overview)
    print('  已写 07 全部产物（%d 个都市圈）' % len(feats))
    return overview, relations


if __name__ == '__main__':
    ov, rel = main()
    print()
    print('=== 质量检查 ===')
    print('  都市圈 %d 个 | 成员关系 %d 条' % (len(ov), len(rel)))
    print('  未匹配缺口合计:', sum(int(r['n_missing']) for r in ov))
    print('  同一都市圈内重复 GID:', sum(int(r['dup_gid']) for r in ov))
    print('  空几何:', sum(1 for r in ov if str(r['is_empty']) == 'True'),
          '| 无效几何:', sum(1 for r in ov if str(r['is_valid']) != 'True'))
    a = sorted(float(r['area_km2_epsg6933']) for r in ov)
    print('  面积范围: %.0f ~ %.0f km²，中位 %.0f' % (a[0], a[-1], a[len(a) // 2]))
    print()
    print('  %-30s 成员 匹配 缺  跨县 块数 孔洞 孔面积 面积km²' % '都市圈')
    for r in ov:
        print('  %-30s %4s %4s %3s %4s %5s %4s %7s %8s'
              % (r['metro_name'][:30], r['n_members'], r['n_matched'], r['n_missing'],
                 r['n_prefs'], r['n_parts'], r['n_holes'], r['hole_area_km2'], r['area_km2_epsg6933']))
