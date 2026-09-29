# -*- coding: utf-8 -*-
"""
沙特经济定义层构建：仿照美国、日本、巴西样例的做法，产出 01 至 04 号中间产物。

与前三国的差别（沙特与中东表特有的处理）：
1. 中东表是 8 列且**没有「本地代码」列**（表头只定义 6 列：城市名 / 国家 / OE 城市代码 /
   地理级别 / 本地层级 / 本地名称）。成员只能按**名称**定位，与美国（县 FIPS）、日本（JIS）
   都不同，与巴西一样退化为名称匹配。
2. GADM 沙特的代码字段全空（L2 的 CC_1 0/13、L3 的 CC_2 0/147、L3 的 HASC_2 0/147），
   且 L3 的 VARNAME_2 与 NL_NAME_2 整列为 NA，**没有任何别名字段可用**，别名表只能手工建。
3. GADM 的地名罗马化与 OE 差异大，且普遍带阿拉伯语冠词前缀（Al / Ad / Ar / Ash / As / Az / At），
   所以匹配分四层：精确 -> 剥冠词 -> 手工别名 -> 模糊（0.8）。别名只收有确证的对应关系：
   Mecca 对 MakkahAlMukarramah、Medina 对 AlMadinah、Jeddah 对 Jiddah、Khobar 对 AlKhubar。
4. 沙特 L3 归一化后**无同名**（重复组 0），因此不需要像巴西那样先定州再匹配，可直接全局匹配。
5. 沙特的「市」在源表里被定义为 Governorate（省），对应 GADM 沙特 L3 的 147 个 Muhafazah。
   其中 4 个城市是一城一省，Dammam 是三省聚合（Dammam / Khobar / Qatif）。要注意这类边界的
   含义是**整个省**，不是城区，与欧洲 City Proper 同类，使用时须知道。
6. Dammam 在 GADM 里**没有对应单元**：全表五个字段（含阿拉伯语本地名）搜 damm 与 دمام 命中 0，
   东区 11 个省里也没有，故如实留缺口。

产出：01 成员表、02 区底表、03 省底表、04 匹配结果、04 匹配异常队列
"""
import collections
import csv
import difflib
import glob
import os
import re
import sys
import unicodedata

import geopandas as gpd
import openpyxl

sys.stdout.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
XLSX = os.path.join(os.path.dirname(ROOT), 'Global_Cities_Definitions_Oct19(1).xlsx')
GEO = glob.glob(os.path.join(ROOT, 'GADM/geojson/SAU_*'))[0]
DEF_VERSION = 'Global_Cities_Definitions_Oct19'
SHEET = 'Middle East'
COUNTRY = 'Saudi Arabia'
FUZZY_CUTOFF = 0.8
# 阿拉伯语冠词前缀，长的排前面（Ash 先于 As、Ad 先于 Ar）
ARTICLES = ('ash', 'al', 'ad', 'ar', 'as', 'az', 'at', 'an')
# 手工别名：OE 写法 -> GADM 归一化写法。只收有确证的对应关系。
ALIAS = {
    'mecca': 'makkahalmukarramah',
    'medina': 'almadinah',
    'jeddah': 'jiddah',
    'khobar': 'alkhubar',
}


def base(s):
    """归一化：去重音、转小写、只留字母"""
    s = unicodedata.normalize('NFKD', str(s or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[^A-Za-z]', '', s).lower()


def strip_article(k):
    """剥掉阿拉伯语冠词前缀，但保留太短的结果（避免把 Ali 剥成 i 这类）"""
    for a in ARTICLES:
        if k.startswith(a) and len(k) > len(a) + 3:
            return k[len(a):]
    return k


def read_oe_saudi():
    """按「列 0 非空即新城市块」解析。中东表成员名在第 5 列（第 4 列是本地层级），
    城市行本身也可能带第一个成员（Dammam 就是这样，另有两条续行）。"""
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    ws = wb[SHEET]
    cities, cur = [], None
    for i, r in enumerate(ws.iter_rows(min_row=4, values_only=True), start=4):
        r = tuple(list(r) + [None] * (8 - len(r)))
        if r[0] and str(r[0]).strip() and r[1]:
            cur = None
            if str(r[1]).strip() == COUNTRY:
                cur = {'name': str(r[0]).strip(),
                       'oe_code': str(r[2]).strip() if r[2] else '',
                       'geo_level': (r[3] or r[4]), 'row': i, 'members': []}
                cities.append(cur)
                if r[5] not in (None, '') and str(r[5]).strip():
                    cur['members'].append({'level': (r[4] or r[3]),
                                           'name': str(r[5]).strip(), 'row': i,
                                           'role': 'self'})
        elif cur is not None and not r[0] and not r[1] and r[5] not in (None, '') and str(r[5]).strip():
            cur['members'].append({'level': (r[4] or r[3]),
                                   'name': str(r[5]).strip(), 'row': i, 'role': 'member'})
    return cities


def main():
    cities = read_oe_saudi()
    print('OE 沙特城市: %d 个 | 成员条目 %d 条'
          % (len(cities), sum(len(c['members']) for c in cities)))

    # ---- GADM 底表 ----
    l2 = gpd.read_file(os.path.join(GEO, 'SAU_L2_adm1.geojson'), ignore_geometry=True)
    l3 = gpd.read_file(os.path.join(GEO, 'SAU_L3_adm2.geojson'), ignore_geometry=True)
    region_of_gid1 = dict(zip(l2['GID_1'], l2['NAME_1']))

    with open(os.path.join(HERE, '02_GADM沙特_区底表.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['gid_1', 'name_1', 'type_1', 'hasc_1', 'name_1_norm', 'n_provinces'])
        cnt = collections.Counter(l3['GID_1'])
        for _, r in l2.iterrows():
            w.writerow([r['GID_1'], r['NAME_1'], r['TYPE_1'], r['HASC_1'],
                        base(r['NAME_1']), cnt.get(r['GID_1'], 0)])
    print('  已写 02_GADM沙特_区底表.csv（%d 行）' % len(l2))

    with open(os.path.join(HERE, '03_GADM沙特_省底表.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['gid_2', 'gid_1', 'region_name', 'province_name', 'type_2',
                    'province_norm', 'province_norm_strip'])
        for _, r in l3.iterrows():
            k = base(r['NAME_2'])
            w.writerow([r['GID_2'], r['GID_1'], region_of_gid1.get(r['GID_1'], ''), r['NAME_2'],
                        r['TYPE_2'], k, strip_article(k)])
    print('  已写 03_GADM沙特_省底表.csv（%d 行，类型全为 %s）'
          % (len(l3), '/'.join(sorted(set(l3['TYPE_2'].dropna().unique())))))

    # ---- 01 成员表 ----
    rows = []
    for k, c in enumerate(cities, 1):
        for m in c['members']:
            rows.append({'metro_id': 'SAUM%02d' % k, 'metro_name': c['name'],
                         'geo_level': c['geo_level'], 'oe_city_code': c['oe_code'],
                         'member_level': m['level'], 'member_name': m['name'],
                         'member_role': m['role'], 'region_oe': '',
                         'source_sheet': SHEET, 'source_row': m['row'],
                         'def_version': DEF_VERSION})
    with open(os.path.join(HERE, '01_沙特经济定义_都市圈成员表.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print('  已写 01_沙特经济定义_都市圈成员表.csv（%d 行）' % len(rows))

    # ---- 04 匹配：精确 -> 剥冠词 -> 别名 -> 模糊 ----
    by_k, by_ks = {}, {}
    ck, cks = collections.Counter(), collections.Counter()
    for _, r in l3.iterrows():
        k = base(r['NAME_2'])
        ks = strip_article(k)
        ck[k] += 1
        cks[ks] += 1
        by_k[k] = (r['NAME_2'], r['GID_2'], r['TYPE_2'], region_of_gid1.get(r['GID_1'], ''))
        by_ks.setdefault(ks, (r['NAME_2'], r['GID_2'], r['TYPE_2'], region_of_gid1.get(r['GID_1'], '')))
    dup_k = [x for x, v in ck.items() if v > 1]
    dup_ks = [x for x, v in cks.items() if v > 1]
    print('  同名键：归一化后 %d 组、剥冠词后 %d 组（都为 0 则匹配确定）' % (len(dup_k), len(dup_ks)))

    out, queue = [], []
    for row in rows:
        key = base(row['member_name'])
        hit, method, conf = None, '', ''
        if key in by_k:
            hit, method, conf = by_k[key], 'name_exact', 'high'
        elif strip_article(key) in by_ks:
            hit, method, conf = by_ks[strip_article(key)], 'name_strip_article', 'high'
        elif ALIAS.get(key) in by_k:
            hit, method, conf = by_k[ALIAS[key]], 'name_alias', 'medium'
        else:
            near = difflib.get_close_matches(strip_article(key), list(by_ks), n=1, cutoff=FUZZY_CUTOFF)
            if near:
                hit, method, conf = by_ks[near[0]], 'name_fuzzy', 'low'
        if hit:
            row.update({'gid_2': hit[1], 'gadm_name': hit[0], 'type_2': hit[2],
                        'region_name': hit[3], 'match_method': method, 'confidence': conf})
        else:
            row.update({'gid_2': '', 'gadm_name': '', 'type_2': '', 'region_name': '',
                        'match_method': 'missing', 'confidence': ''})
            queue.append(row)
        out.append(row)

    for name, data in (('04_匹配结果_全量.csv', out), ('04_匹配异常队列.csv', queue)):
        with open(os.path.join(HERE, name), 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=list(data[0].keys()))
            w.writeheader()
            w.writerows(data)

    # ---- 报告 ----
    st = collections.Counter(r['match_method'] for r in out)
    print()
    print('=== 匹配结果（%d 条）===' % len(out))
    for k in ('name_exact', 'name_strip_article', 'name_alias', 'name_fuzzy', 'missing'):
        if st.get(k):
            print('  %-22s %d' % (k, st[k]))
    ok = len(out) - len(queue)
    print('  匹配成功 %d / %d = %.2f%%' % (ok, len(out), 100.0 * ok / max(len(out), 1)))
    for r in queue:
        print('    缺口: %-10s %-12s 层级=%s' % (r['metro_name'], r['member_name'], r['member_level']))
    print()
    print('=== 逐城成员 ===')
    for c in cities:
        ms = [r for r in out if r['metro_name'] == c['name']]
        print('  %-10s 层级=%-12s 成员 %d: %s'
              % (c['name'], str(c['geo_level'])[:12], len(ms),
                 '、'.join('%s%s' % (r['member_name'], '' if r['gid_2'] else '(缺)') for r in ms)))


if __name__ == '__main__':
    main()
