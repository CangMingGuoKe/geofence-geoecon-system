# -*- coding: utf-8 -*-
"""
巴西经济定义层构建：仿照美国、日本样例的做法，产出 01 至 04 号中间产物。

与美日的差别（巴西特有的处理）：
1. 源表成员没有代码可对（美国有县 FIPS、日本有 JIS），只能按名字匹配。好在巴西成员就是市镇
   （município），而 GADM 巴西 L3 正好是市镇层（5,572 个，带 IBGE 代码）。
2. 同名市镇极多（Campo Grande 在三个州都有），必须先定州再匹配。定州不用名字投票，改用
   OE 自带的城市坐标做「点落多边形」，实测 26 / 26 全部落进正确的州。这一点很关键：6 个
   「单市」城市没有成员列表，名字投票对它们无效，而坐标法照样能定州。
   坐标取自 Coordinates 表，该表经纬度是带不换行空格（\xa0）的字符串，须先清掉才能转浮点。
3. 源表有两处需要处置的数据问题：
   (a) Cuiabá RM 的 25 个成员与 Curitiba RM 完全相同，且全部落在 Paraná 州，而 Cuiabá 本身
       在 Mato Grosso（坐标落点已证）。判定源表错标，本层剔除该城市；为留痕，行仍写在 01 里
       并用 source_issue 列标出，匹配环节跳过。
   (b) 6 个城市（Brasília、Campo Grande、Teresina、Ribeirao Prêto、Sao José dos Campos、
       Sorocaba）是「单市」定义，源表没有成员行，按「城市即成员」补一行，member_role 记为 self。
4. GADM 巴西 L3 的 5,572 个单元全部是 Município，没有水体等杂物，不必像日本那样标非市镇单元。
   联邦区在 L3 里也有单元（Brasília / DistritoFederal / 5300108），无需跨层引用 L2。
5. 父级 GID 一律从 GID_1 列直接取，不用字符串截断推（GADM 的版本后缀会让 BRA.1.1_2 与
   BRA.1_1 这类父子关系被推错）。

匹配策略：先州内精确（归一化后比较），不中则州内模糊（difflib 相似度 0.8）。归一化只做
「去重音 + 小写 + 只留字母数字」，不剥连接词，避免过度归一引入错配。

6. 解析要同时收「城市行自带的第一个成员」与续行：源表把第一个成员写在该城市行的本地名称列，
   其余成员在其后的续行里。只收续行会每个都市圈漏掉一个市镇（巴西漏 20 个、日本漏 14 个）。

产出：01 成员表、02 州底表、03 市底表、04 匹配结果、04 匹配异常队列
"""
import collections
import csv
import difflib
import os
import re
import sys
import unicodedata

import geopandas as gpd
import openpyxl
from shapely.geometry import Point

sys.stdout.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
XLSX = os.path.join(os.path.dirname(ROOT), 'Global_Cities_Definitions_Oct19(1).xlsx')
GEO = os.path.join(ROOT, 'GADM/geojson/BRA_巴西')
DEF_VERSION = 'Global_Cities_Definitions_Oct19'
SHEET = 'Latin America'
COUNTRY = 'Brazil'
FUZZY_CUTOFF = 0.8
# 源表错标的城市，整块剔除
SOURCE_ERROR = {'Cuiabá RM'}
# 「单市」定义的城市：源表无成员行，按城市自身补一行


def base(s):
    """归一化：去重音、转小写、只留字母数字。GADM 常把多词地名连写（SantaBárbara），
    源表用空格（Santa Bárbara），故一律去掉非字母数字后比较。"""
    s = unicodedata.normalize('NFKD', str(s or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[^A-Za-z0-9]', '', s).lower()


def read_oe_brazil():
    """按「列 0 非空即新城市块」解析，成员写在后续续行里（国家列只在首行出现）。"""
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    ws = wb[SHEET]
    cities, cur = [], None
    for i, r in enumerate(ws.iter_rows(min_row=4, values_only=True), start=4):
        r = tuple(list(r) + [None] * (7 - len(r)))
        if r[0] and str(r[0]).strip():
            cur = None
            if (r[1] or '').strip() == COUNTRY:
                cur = {'name': str(r[0]).strip(),
                       'oe_code': str(r[2]).strip() if r[2] else '',
                       'level': r[3], 'row': i, 'members': []}
                cities.append(cur)
                # 源表把第一个成员就写在该城市行上（本地名称列），其余成员才在续行。
                # 早先只收续行，导致每个都市圈漏掉一个市镇。
                if r[6]:
                    cur['members'].append({'level': r[4],
                                           'name': str(r[6]).strip(), 'row': i})
        elif cur is not None and not r[1] and (r[4] or r[6]):
            cur['members'].append({'level': r[4],
                                   'name': str(r[6]).strip() if r[6] else '',
                                   'row': i})
    return cities


def read_coords():
    """Coordinates 表：经纬度是字符串且带不换行空格，须清理。键为 OE 城市代码。"""
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    out = {}
    for r in list(wb['Coordinates'].iter_rows(values_only=True))[3:]:
        if not r or r[2] != COUNTRY or not r[3]:
            continue
        try:
            lat = float(str(r[4]).replace('\xa0', '').strip())
            lon = float(str(r[5]).replace('\xa0', '').strip())
        except (TypeError, ValueError):
            continue
        out[str(r[3]).strip()] = (lat, lon)
    return out


def main():
    cities = read_oe_brazil()
    coords = read_coords()
    print('OE 巴西城市: %d 个 | 源表成员行 %d 条 | 坐标 %d 条'
          % (len(cities), sum(len(c['members']) for c in cities), len(coords)))

    # ---- GADM 底表 ----
    l2 = gpd.read_file(os.path.join(GEO, 'BRA_L2_adm1.geojson'))
    l3 = gpd.read_file(os.path.join(GEO, 'BRA_L3_adm2.geojson'), ignore_geometry=True)
    state_of_gid1 = dict(zip(l2['GID_1'], l2['NAME_1']))

    with open(os.path.join(HERE, '02_GADM巴西_州底表.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['gid_1', 'name_1', 'type_1', 'hasc_1', 'name_1_norm', 'n_municipios'])
        cnt = collections.Counter(l3['GID_1'])
        for _, r in l2.iterrows():
            w.writerow([r['GID_1'], r['NAME_1'], r['TYPE_1'], r['HASC_1'],
                        base(r['NAME_1']), cnt.get(r['GID_1'], 0)])
    print('  已写 02_GADM巴西_州底表.csv（%d 行）' % len(l2))

    with open(os.path.join(HERE, '03_GADM巴西_市底表.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['gid_2', 'gid_1', 'state_name', 'muni_name', 'type_2', 'cc_2', 'muni_norm'])
        for _, r in l3.iterrows():
            w.writerow([r['GID_2'], r['GID_1'], state_of_gid1.get(r['GID_1'], ''), r['NAME_2'],
                        r['TYPE_2'], r['CC_2'], base(r['NAME_2'])])
    print('  已写 03_GADM巴西_市底表.csv（%d 行，类型全为 %s）'
          % (len(l3), '/'.join(sorted(set(l3['TYPE_2'].dropna().unique())))))

    # ---- 城市所属州：用 OE 坐标点落 GADM 州界 ----
    city_state, no_state = {}, []
    for c in cities:
        latlon = coords.get(c['oe_code'])
        pt = Point(latlon[1], latlon[0]) if latlon else None
        hit = l2[l2.contains(pt)] if pt is not None else l2.iloc[0:0]
        city_state[c['name']] = hit['NAME_1'].iloc[0] if len(hit) else ''
        if not len(hit):
            no_state.append(c['name'])
    print('  坐标定州：%d / %d 命中%s'
          % (len(cities) - len(no_state), len(cities),
             '' if not no_state else ' | 未命中: %s' % no_state))

    # ---- 01 成员表 ----
    rows = []
    for k, c in enumerate(cities, 1):
        mid, mname = 'BRM%02d' % k, c['name']
        issue = ('源表错标：成员名单与 Curitiba RM 完全相同且全在 Paraná 州，本层剔除'
                 if mname in SOURCE_ERROR else '')
        common = {'metro_id': mid, 'metro_name': mname, 'geo_level': c['level'],
                  'oe_city_code': c['oe_code'], 'state_oe': city_state.get(mname, ''),
                  'source_issue': issue, 'source_sheet': SHEET, 'def_version': DEF_VERSION}
        for m in c['members']:
            rows.append(dict(common, member_level=m['level'], member_name=m['name'],
                             member_role='member', source_row=m['row']))
        if not c["members"]:
            rows.append(dict(common, member_level=c['level'], member_name=mname,
                             member_role='self', source_row=c['row']))
    with open(os.path.join(HERE, '01_巴西经济定义_都市圈成员表.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    n_excl = sum(1 for r in rows if r['source_issue'])
    n_self = sum(1 for r in rows if r['member_role'] == 'self')
    print('  已写 01_巴西经济定义_都市圈成员表.csv（%d 行：源表成员 %d、补单市 %d、剔除 %d，有效 %d）'
          % (len(rows), len(rows) - n_self - n_excl, n_self, n_excl, len(rows) - n_excl))

    # ---- 04 匹配 ----
    gid1_of_gid2 = dict(zip(l3['GID_2'], l3['GID_1']))
    by_state = collections.defaultdict(dict)
    for _, r in l3.iterrows():
        st = state_of_gid1.get(r['GID_1'], '')
        by_state[st][base(r['NAME_2'])] = (r['NAME_2'], r['GID_2'], r['TYPE_2'], r['CC_2'])

    out, queue = [], []
    for row in rows:
        if row['source_issue']:
            row.update({'gid_2': '', 'gadm_name': '', 'type_2': '', 'cc_2': '',
                        'match_method': 'excluded_source_issue', 'confidence': ''})
            out.append(row)
            continue
        st = row['state_oe']
        pool = by_state.get(st, {})
        key = base(row['member_name'])
        hit = pool.get(key)
        method, conf = 'name_exact', 'high'
        if hit is None:
            near = difflib.get_close_matches(key, list(pool), n=1, cutoff=FUZZY_CUTOFF)
            if near:
                hit, method, conf = pool[near[0]], 'name_fuzzy', 'medium'
        if hit:
            row.update({'gid_2': hit[1], 'gadm_name': hit[0], 'type_2': hit[2], 'cc_2': hit[3],
                        'match_method': method, 'confidence': conf})
        else:
            row.update({'gid_2': '', 'gadm_name': '', 'type_2': '', 'cc_2': '',
                        'match_method': 'missing', 'confidence': ''})
            queue.append(row)
        out.append(row)

    for name, data in (('04_匹配结果_全量.csv', out), ('04_匹配异常队列.csv', queue)):
        with open(os.path.join(HERE, name), 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=list(data[0].keys()))
            w.writeheader()
            w.writerows(data)

    # ---- 报告 ----
    eff = [r for r in out if r['match_method'] != 'excluded_source_issue']
    st = collections.Counter(r['match_method'] for r in eff)
    print()
    print('=== 匹配结果（有效 %d 条）===' % len(eff))
    for k in ('name_exact', 'name_fuzzy', 'missing'):
        if st.get(k):
            print('  %-22s %d' % (k, st[k]))
    print('  %-22s %d' % ('剔除（源表错标）', len(out) - len(eff)))
    ok = len(eff) - len(queue)
    print('  匹配成功 %d / %d = %.2f%%' % (ok, len(eff), 100.0 * ok / max(len(eff), 1)))
    for r in queue:
        print('    缺口: %-24s %-24s 州=%s' % (r['metro_name'], r['member_name'], r['state_oe']))

    # ---- 交叉校验：坐标定的州 与 成员匹配结果落的州 是否一致 ----
    print()
    print('=== 交叉校验：坐标定州 vs 成员匹配落州 ===')
    bad = 0
    for c in cities:
        ms = [r for r in out if r['metro_name'] == c['name'] and r['gid_2']]
        if not ms:
            continue
        votes = collections.Counter(state_of_gid1.get(gid1_of_gid2.get(r['gid_2'], ''), '?') for r in ms)
        top = votes.most_common(1)[0][0]
        if top != city_state.get(c['name']):
            bad += 1
            print('  不一致: %-24s 坐标=%-16s 成员投票=%s'
                  % (c['name'], city_state.get(c['name']), dict(votes)))
    print('  一致 %d 个城市，不一致 %d 个' % (len(cities) - bad, bad))

    # ---- 规模校验：GADM 巴西市镇层总面积 ----
    area = gpd.read_file(os.path.join(GEO, 'BRA_L3_adm2.geojson')).to_crs('EPSG:6933').area.sum() / 1e6
    print()
    print('=== 规模校验 ===')
    print('  GADM 巴西 L3 市镇层合计面积 %.0f km²（官方国土面积参考 8,515,767 km²）' % area)


if __name__ == '__main__':
    main()
