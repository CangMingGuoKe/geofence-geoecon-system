# -*- coding: utf-8 -*-
"""
八国经济定义层：生成都市圈边界并做质量检查。

成员跨 L2 / L3 / L4（泰国与阿联酋在 L2、马来西亚与阿根廷在 L3、秘鲁在 L4），
取几何时按 GID 逐层查找，先 L4 再 L3 再 L2，避免同号异层误取。

产出：07 边界 / 一览 / 成员关系 / 质量检查报告，05 每国两个样例
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
GEOJSON_DIR = os.path.join(ROOT, 'GADM', 'geojson')
AREA_CRS = 'EPSG:6933'
ISO = ('MYS', 'THA', 'ARG', 'PER', 'MAR', 'ARE')


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
    geo, name_of, parent_of = {}, {}, {}
    for iso3 in ISO:
        d = geo_dir(iso3)
        for lv, adm, gidc, nc in (('2', 'adm1', 'GID_1', 'NAME_1'),
                                  ('3', 'adm2', 'GID_2', 'NAME_2'),
                                  ('4', 'adm3', 'GID_3', 'NAME_3')):
            p = os.path.join(d, f'{iso3}_L{lv}_{adm}.geojson')
            if not os.path.exists(p):
                continue
            g = gpd.read_file(p)
            for _, r in g.iterrows():
                geo[str(r[gidc])] = r.geometry
                name_of[str(r[gidc])] = str(r[nc])
        for lv, adm, gidc, pc in (('3', 'adm2', 'GID_2', 'NAME_1'), ('4', 'adm3', 'GID_3', 'NAME_2')):
            p = os.path.join(d, f'{iso3}_L{lv}_{adm}.geojson')
            if os.path.exists(p):
                g = gpd.read_file(p, ignore_geometry=True)
                if pc in g.columns:
                    for _, r in g.iterrows():
                        parent_of[str(r[gidc])] = str(r[pc])

    by_metro = collections.OrderedDict()
    for r in matched:
        by_metro.setdefault(r['metro_id'], []).append(r)

    feats, overview, relations, geoms = [], [], [], {}
    for mid, rows in by_metro.items():
        name = rows[0]['metro_name']
        iso3 = rows[0]['iso3']
        ok = [r for r in rows if r['gid']]
        miss = [r for r in rows if not r['gid']]
        gids = [r['gid'] for r in ok]
        dup = [k for k, v in collections.Counter(gids).items() if v > 1]
        if not gids:
            print('  跳过无匹配成员的 %s（%s）' % (name, mid))
            continue
        boundary = unary_union([geo[g] for g in gids])
        polys = [boundary] if boundary.geom_type == 'Polygon' else list(boundary.geoms)
        holes = [h for p in polys for h in p.interiors]
        hole_area = (gpd.GeoSeries([Polygon(h) for h in holes], crs='EPSG:4326')
                     .to_crs(AREA_CRS).area.sum() / 1e6) if holes else 0.0
        area = gpd.GeoSeries([boundary], crs='EPSG:4326').to_crs(AREA_CRS).area.iloc[0] / 1e6
        parents = sorted(set(parent_of.get(g, '') for g in gids if parent_of.get(g)))
        geoms[mid] = boundary
        feats.append({'type': 'Feature',
                      'properties': {'metro_id': mid, 'metro_name': name, 'iso3': iso3,
                                     'n_members': len(rows), 'n_missing': len(miss),
                                     'parents': '、'.join(parents)},
                      'geometry': boundary.__geo_interface__})
        overview.append({'metro_id': mid, 'metro_name': name, 'iso3': iso3,
                         'n_members': len(rows), 'n_matched': len(ok), 'n_missing': len(miss),
                         'parents': '、'.join(parents), 'geom_type': boundary.geom_type,
                         'n_parts': len(polys), 'n_holes': len(holes),
                         'hole_area_km2': round(hole_area, 1), 'is_valid': boundary.is_valid,
                         'is_empty': boundary.is_empty,
                         'area_km2_epsg6933': round(area, 1), 'dup_gid': len(dup)})
        for r in rows:
            relations.append({'metro_id': mid, 'metro_name': name, 'iso3': iso3,
                              'member_name': r['member_name'], 'member_role': r['member_role'],
                              'gadm_level': r['gadm_level'], 'parent_name': parent_of.get(r['gid'], ''),
                              'gadm_name': r['gadm_name'], 'gid': r['gid'], 'type': r['type'],
                              'method': r['method']})

    # 都市圈之间重叠
    mids = list(geoms)
    overlaps = []
    for i in range(len(mids)):
        for j in range(i + 1, len(mids)):
            a, b = geoms[mids[i]], geoms[mids[j]]
            if not a.intersects(b):
                continue
            ia = gpd.GeoSeries([a.intersection(b)], crs='EPSG:4326').to_crs(AREA_CRS).area.iloc[0] / 1e6
            if ia > 1.0:
                overlaps.append((mids[i], mids[j], round(ia, 1)))

    with open(os.path.join(HERE, '07_八国都市圈边界.geojson'), 'w', encoding='utf-8') as f:
        json.dump({'type': 'FeatureCollection', 'features': feats}, f, ensure_ascii=False)
    gpd.GeoDataFrame.from_features(feats, crs='EPSG:4326').to_file(
        os.path.join(HERE, '07_八国都市圈边界.gpkg'), driver='GPKG', layer='07_八国都市圈边界')
    wr('07_八国都市圈成员关系.csv', relations)
    wr('07_八国都市圈一览.csv', overview)

    # 每国两个样例：成员最多、面积最大
    samples = []
    for iso3 in ISO:
        sub = [r for r in overview if r['iso3'] == iso3]
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
                               'gadm_level', 'parent_name', 'gadm_name', 'gid', 'type', 'method')}
            for r in relations if r['metro_id'] == mid])
        with open(os.path.join(HERE, '05_%s_都市圈边界.geojson' % mid), 'w', encoding='utf-8') as fh:
            json.dump({'type': 'FeatureCollection', 'features': [f]}, fh, ensure_ascii=False)
        print('  已写 05_%s（%s）：%d 成员，面积 %.0f km²'
              % (mid, pick['metro_name'], int(pick['n_members']), float(pick['area_km2_epsg6933'])))

    # 报告
    L = ['# 八国经济都市圈 · 质量检查报告', '',
         '数据：Oxford Economics `Global_Cities_Definitions_Oct19`；底图 GADM 4.1。'
         '面积按 EPSG:6933 等积投影计算。', '', '## 总览', '',
         '| 国家 | 都市圈 | 成员关系 | 未匹配 | 面积合计 km² |', '|---|---|---|---|---|']
    for iso3, cn in (('MYS', '马来西亚'), ('THA', '泰国'), ('ARG', '阿根廷'),
                     ('PER', '秘鲁'), ('MAR', '摩洛哥'), ('ARE', '阿联酋')):
        sub = [r for r in overview if r['iso3'] == iso3]
        L.append('| %s %s | %d | %d | %d | %.0f |'
                 % (iso3, cn, len(sub), sum(int(r['n_members']) for r in sub),
                    sum(int(r['n_missing']) for r in sub),
                    sum(float(r['area_km2_epsg6933']) for r in sub)))
    L += ['', '## 几何与匹配', '',
          '- 空几何 %d 个，无效几何 %d 个。'
          % (sum(1 for r in overview if str(r['is_empty']) == 'True'),
             sum(1 for r in overview if str(r['is_valid']) != 'True')),
          '- 同一都市圈内重复 GID：%d 处。' % sum(int(r['dup_gid']) for r in overview),
          '- 未匹配成员：%d 条落在已成圈的都市圈内，全部缺口（含未成圈都市圈的成员）见 `04_匹配异常队列.csv`。'
          % sum(int(r['n_missing']) for r in overview),
          '', '## 都市圈之间的重叠', '']
    L += (['- %s 与 %s 相交 %.1f km²' % (a, b, ia) for a, b, ia in overlaps]
          or ['- 面积大于 1 km² 的相交对：0 对。'])
    L += ['', '## 已知缺口与口径', '',
          '- **阿根廷**：布宜诺斯艾利斯都市圈 31 个成员里 7 个在 GADM 中无对应单元，成因分两类。'
          '一类是 1990 年代从旧 partido 分设出来的 `Los Polvorines`（马尔维纳斯阿根廷斯）、'
          '`José C. Paz`、`Hurlingham`、`Ezeiza`、`Presidente Perón` 五个：该省 L3 只有 128 个单元，'
          '且仍保留 `General Sarmiento` 这类分设前的旧单元，说明 GADM 该省界线早于那次分设。'
          '另一类是 `San Miguel` 与 `Ituzaingó`：全省 L3 里根本没有这两个名字，'
          '同名单元只在科连特斯省，按上级限定不回退，故如实记缺。',
          '- **秘鲁**：`Pomalca` 在 GADM 的秘鲁 ADM3 中完全没有，奇克拉约都市圈少 1 个区。',
          '- **摩洛哥**：GADM 仍是 2015 年区划改革前的口径，大卡萨布兰卡只含卡萨布兰卡与穆罕默迪耶两省，'
          '努瓦塞尔与梅迪乌纳两省在 ADM2 缺失；阿加迪尔、伊奈兹甘、艾特梅卢勒三个市镇在 ADM2 也不存在。'
          '这些单元在 ADM3 里虽有同名记录，但类型是圈（Cercle）或未标类型的小单元，与源表口径不符，'
          '故不硬套。阿加迪尔都市圈因成员全部未匹配而不成圈。',
          '- **阿联酋**：源表把迪拜-沙迦-阿治曼写成迪拜全境加沙迦、阿治曼的**部分**，'
          '但 GADM 只有整个酋长国的边界，本层按整酋长国取，面积会大于源表定义。',
          '- **泰国**：源表只定义曼谷一个都市圈（曼谷加周边五府），其余城市没有成员清单。',
          '- **马来西亚**：吉隆坡是 6 个区聚合的都市圈，其余 10 城各为单个区，属市域而非都市圈。',
          '- **伊朗与新西兰**：源表给的是城市自身（City Proper）或大区议会（Regional Council），'
          '成员数等于城市数，拼出来是整市或整大区，不是都市圈，故本次只上行政层，不做经济图层。']
    with open(os.path.join(HERE, '07_质量检查报告.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')

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
    print('  %-10s %-26s %4s %4s %3s %4s %10s' % ('metro', 'name', '成员', '匹配', '缺', '块数', '面积km²'))
    for r in ov:
        print('  %-10s %-26s %4s %4s %3s %4s %10s'
              % (r['metro_id'], r['metro_name'][:26], r['n_members'], r['n_matched'],
                 r['n_missing'], r['n_parts'], r['area_km2_epsg6933']))
