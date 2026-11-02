# -*- coding: utf-8 -*-
"""
非洲三国经济定义层：生成 32 个都市圈的边界，并做质量检查。

做法同前四例：把每个都市圈匹配上的成员边界取并集。非洲特有的几点：
1. 成员跨层：南非与尼日利亚绝大多数在 L3，埃及的亚历山大、塞得港、苏伊士、
   尼日利亚的拉各斯与阿布贾整州成圈，落在 L2。并集按 GID 取，
   先查 L3 再查 L2，避免同名跨层误取。
2. 埃及开罗都市圈跨三个省（开罗、吉萨、盖勒尤卜），是本数据集里唯一的跨省都市圈。
3. 面积用 EPSG:6933（全球等积圆柱），与前四例口径一致。
   国土面积只报 GADM 自身合计，不与外部参考值比对：本项目未收录三国国土面积的
   权威来源，硬引外部数字会变成无源之数。

产出：07 全部边界与一览、07 成员关系、07 质量检查报告、05 每国两个样例
"""
import collections
import csv
import glob
import json
import os
import sys

import geopandas as gpd
from shapely.geometry import Polygon
from shapely.ops import unary_union

sys.stdout.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
GEOJSON_DIR = os.path.join(ROOT, 'GADM', 'geojson')
AREA_CRS = 'EPSG:6933'
ISO = ('ZAF', 'EGY', 'NGA')


def rd(name):
    with open(os.path.join(HERE, name), encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def wr(name, rows):
    with open(os.path.join(HERE, name), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def geo_dir(iso3):
    for d in os.listdir(GEOJSON_DIR):
        if d.startswith(iso3 + '_'):
            return os.path.join(GEOJSON_DIR, d)
    raise FileNotFoundError(iso3)


def main():
    matched = rd('04_匹配结果_全量.csv')
    geo, name_of, type_of, parent_of = {}, {}, {}, {}
    for iso3 in ISO:
        d = geo_dir(iso3)
        l2 = gpd.read_file(os.path.join(d, f'{iso3}_L2_adm1.geojson'))
        l3 = gpd.read_file(os.path.join(d, f'{iso3}_L3_adm2.geojson'))
        for _, r in l2.iterrows():
            geo[str(r['GID_1'])] = r.geometry
            name_of[str(r['GID_1'])] = str(r['NAME_1'])
            type_of[str(r['GID_1'])] = str(r['TYPE_1'])
        for _, r in l3.iterrows():
            geo[str(r['GID_2'])] = r.geometry
            name_of[str(r['GID_2'])] = str(r['NAME_2'])
            type_of[str(r['GID_2'])] = str(r['TYPE_2'])
            parent_of[str(r['GID_2'])] = str(r['NAME_1'])
        for _, r in l2.iterrows():
            parent_of[str(r['GID_1'])] = str(r['NAME_1'])

    by_metro = collections.OrderedDict()
    for r in matched:
        by_metro.setdefault(r['metro_id'], []).append(r)

    feats, overview, relations, areas, geoms = [], [], [], {}, {}
    for mid, rows in by_metro.items():
        name = rows[0]['metro_name']
        country = rows[0]['country']
        ok = [r for r in rows if r['gid']]
        miss = [r for r in rows if not r['gid']]
        gids = [r['gid'] for r in ok]
        dup = [k for k, v in collections.Counter(gids).items() if v > 1]
        if not gids:
            print('  跳过无匹配成员的 %s' % name)
            continue
        boundary = unary_union([geo[g] for g in gids])
        polys = [boundary] if boundary.geom_type == 'Polygon' else list(boundary.geoms)
        holes = [h for p in polys for h in p.interiors]
        hole_area = (gpd.GeoSeries([Polygon(h) for h in holes], crs='EPSG:4326')
                     .to_crs(AREA_CRS).area.sum() / 1e6) if holes else 0.0
        area = gpd.GeoSeries([boundary], crs='EPSG:4326').to_crs(AREA_CRS).area.iloc[0] / 1e6
        parents = sorted(set(parent_of.get(g, '') for g in gids))
        areas[mid] = area
        geoms[mid] = boundary
        feats.append({'type': 'Feature',
                      'properties': {'metro_id': mid, 'metro_name': name, 'country': country,
                                     'n_members': len(rows), 'n_missing': len(miss),
                                     'n_parents': len(parents), 'parents': '、'.join(parents)},
                      'geometry': boundary.__geo_interface__})
        overview.append({'metro_id': mid, 'metro_name': name, 'country': country,
                         'n_members': len(rows), 'n_matched': len(ok), 'n_missing': len(miss),
                         'n_parents': len(parents), 'parents': '、'.join(parents),
                         'geom_type': boundary.geom_type, 'n_parts': len(polys),
                         'n_holes': len(holes), 'hole_area_km2': round(hole_area, 1),
                         'is_valid': boundary.is_valid, 'is_empty': boundary.is_empty,
                         'area_km2_epsg6933': round(area, 1), 'dup_gid': len(dup)})
        for r in rows:
            relations.append({'metro_id': mid, 'metro_name': name, 'country': country,
                              'member_name': r['member_name'], 'member_role': r['member_role'],
                              'level': '',
                              'parent_name': parent_of.get(r['gid'], ''),
                              'gadm_name': r['gadm_name'], 'gid': r['gid'], 'type': r['type'],
                              'match_method': r['match_method'], 'confidence': r['confidence']})

    # 修正 level 标注（上面那行只做占位，按 GID 段数判定：XXX.n_m 为 L2，XXX.n.m_m 为 L3）
    for r in relations:
        r['level'] = 'L2' if r['gid'] and r['gid'].count('.') == 1 else ('L3' if r['gid'] else '')

    # ---- 跨圈重叠检查：两都市圈若共享成员或几何相交，须显式记录 ----
    mids = list(geoms)
    overlaps = []
    for i in range(len(mids)):
        for j in range(i + 1, len(mids)):
            a, b = geoms[mids[i]], geoms[mids[j]]
            if areas[mids[i]] > 200000 and areas[mids[j]] > 200000:
                continue
            if a.intersects(b):
                inter = a.intersection(b)
                ia = gpd.GeoSeries([inter], crs='EPSG:4326').to_crs(AREA_CRS).area.iloc[0] / 1e6
                if ia > 1.0:
                    overlaps.append((mids[i], mids[j], round(ia, 1)))

    with open(os.path.join(HERE, '07_非洲都市圈边界.geojson'), 'w', encoding='utf-8') as f:
        json.dump({'type': 'FeatureCollection', 'features': feats}, f, ensure_ascii=False)
    gpd.GeoDataFrame.from_features(feats, crs='EPSG:4326').to_file(
        os.path.join(HERE, '07_非洲都市圈边界.gpkg'), driver='GPKG', layer='07_非洲都市圈边界')
    wr('07_非洲都市圈成员关系.csv', relations)
    wr('07_非洲都市圈一览.csv', overview)

    # ---- 样例：每国取「成员最多」与「面积最大」各一 ----
    samples = []
    for iso3 in ISO:
        sub = [r for r in overview if r['metro_id'].startswith(iso3)]
        if not sub:
            continue
        samples.append(max(sub, key=lambda r: (int(r['n_members']), -float(r['area_km2_epsg6933']))))
        samples.append(max(sub, key=lambda r: float(r['area_km2_epsg6933'])))
    seen = set()
    for pick in samples:
        mid = pick['metro_id']
        if mid in seen:
            continue
        seen.add(mid)
        f = [x for x in feats if x['properties']['metro_id'] == mid][0]
        wr('05_%s_成员表.csv' % mid,
           [{k: r[k] for k in ('metro_id', 'metro_name', 'member_name', 'member_role',
                               'level', 'parent_name', 'gadm_name', 'gid', 'type',
                               'match_method')}
            for r in relations if r['metro_id'] == mid])
        with open(os.path.join(HERE, '05_%s_都市圈边界.geojson' % mid), 'w', encoding='utf-8') as fh:
            json.dump({'type': 'FeatureCollection', 'features': [f]}, fh, ensure_ascii=False)
        print('  已写 05_%s（%s）：%d 成员，%d 块，面积 %.0f km²'
              % (mid, pick['metro_name'], int(pick['n_members']),
                 int(pick['n_parts']), float(pick['area_km2_epsg6933'])))

    # ---- 报告 ----
    lines = ['# 非洲三国经济都市圈 · 质量检查报告', '',
             '数据：Oxford Economics `Global_Cities_Definitions_Oct19` Africa 表；'
             '底图 GADM 4.1。面积按 EPSG:6933 等积投影计算。', '',
             '## 总览', '',
             '| 国家 | 都市圈 | 成员关系 | 未匹配缺口 | 面积合计 km² |',
             '|---|---|---|---|---|']
    for iso3, cn in (('ZAF', '南非'), ('EGY', '埃及'), ('NGA', '尼日利亚')):
        sub = [r for r in overview if r['metro_id'].startswith(iso3)]
        lines.append('| %s %s | %d | %d | %d | %.0f |'
                     % (iso3, cn, len(sub), sum(int(r['n_members']) for r in sub),
                        sum(int(r['n_missing']) for r in sub),
                        sum(float(r['area_km2_epsg6933']) for r in sub)))
    lines += ['', '## 几何与匹配', '',
              '- 空几何 %d 个，无效几何 %d 个。'
              % (sum(1 for r in overview if str(r['is_empty']) == 'True'),
                 sum(1 for r in overview if str(r['is_valid']) != 'True')),
              '- 同一都市圈内重复 GID：%d 处。' % sum(int(r['dup_gid']) for r in overview),
              '- 未匹配成员：%d 条，逐条见 `04_匹配异常队列.csv`。'
              % sum(int(r['n_missing']) for r in overview),
              '- 跨上级（省/州）都市圈：%d 个（%s）。'
              % (sum(1 for r in overview if int(r['n_parents']) > 1),
                 '、'.join(r['metro_name'] for r in overview if int(r['n_parents']) > 1)),
              '', '## 都市圈之间的重叠', '']
    if overlaps:
        for a, b, ia in overlaps:
            lines.append('- %s 与 %s 相交 %.1f km²' % (a, b, ia))
    else:
        lines.append('- 面积大于 1 km² 的相交对：0 对。')
    lines += ['', '## 已知缺口与口径', '',
              '- 伊巴丹（NGA003）的成员 `Ibadan Central` 在 GADM 中无对应 LGA。'
              '伊巴丹市由 5 个 LGA 组成（North / North-East / North-West / South-East / South-West），'
              '源表列了其中 4 个并另设 `Central`，故 `Central` 记为确认缺口，未强行套到某个 LGA 上。',
              '- 拉各斯与阿布贾在源表中是 State 级且无成员行，按整州成圈，边界含义是**整个州**而非城区。',
              '- 亚历山大、塞得港、苏伊士同为 Governorate 级，边界含义是**整个省**。',
              '- 开罗都市圈由 46 个 Kism 组成，跨开罗、吉萨、盖勒尤卜三省；'
              '`Al-Warrāq Kism` 在源表中标注为 partial（urban parts only），此处按 GADM 整块取。',
              '- 南非的 9 城全部落在 L3（大都会市政 / 区市政），边界含义是该市政全域。'
              '其中 Ekurhuleni 在 GADM 中为 3,459 km²，明显大于同省其他大都会市政'
              '（约翰内斯堡 1,645 km²、茨瓦内 6,298 km²、开普敦 2,455 km²），'
              '会连带放大约翰内斯堡都市圈的面积，使用前建议与南非官方市政面积核对；本层未改动底图几何。',
              '- 哈科特港（NGA005）有 3.35 km²（占该圈 0.14%）落在 GADM 的尼日利亚国界之外，'
              '碎成 213 块，全部沿岸线分布。成因是 GADM 的 L3 与 L1 对尼日尔三角洲岸线的画法不同，'
              '不是成员错配：该国 L3 并集比 L1 还小 99.9 km²，两者本就不完全套合。',
              '- 三个都市圈内（开罗、卡诺、伊巴丹）成员边界之间有 0.6 至 0.7 km² 的细缝重叠，'
              '成圈时取并集已消除，不影响面积。',
              ]
    with open(os.path.join(HERE, '07_质量检查报告.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')

    print('  已写 07 全部产物（%d 个都市圈）' % len(feats))
    return overview, relations, overlaps


if __name__ == '__main__':
    ov, rel, ovl = main()
    print()
    print('=== 质量检查 ===')
    print('  都市圈 %d 个 | 成员关系 %d 条' % (len(ov), len(rel)))
    print('  未匹配缺口合计: %d' % sum(int(r['n_missing']) for r in ov))
    print('  重复 GID: %d | 空几何: %d | 无效几何: %d'
          % (sum(int(r['dup_gid']) for r in ov),
             sum(1 for r in ov if str(r['is_empty']) == 'True'),
             sum(1 for r in ov if str(r['is_valid']) != 'True')))
    print('  相交对(>1km²): %d' % len(ovl))
    print()
    print('  %-12s %-12s %4s %4s %3s %4s %10s' % ('metro', 'name', '成员', '匹配', '缺', '块数', '面积km²'))
    for r in ov:
        print('  %-12s %-12s %4s %4s %3s %4s %10s'
              % (r['metro_id'], r['metro_name'][:12], r['n_members'], r['n_matched'],
                 r['n_missing'], r['n_parts'], r['area_km2_epsg6933']))
