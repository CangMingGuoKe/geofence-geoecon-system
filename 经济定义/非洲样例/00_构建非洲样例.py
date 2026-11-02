# -*- coding: utf-8 -*-
"""
非洲三国（南非 / 埃及 / 尼日利亚）经济定义层构建：产出 01 至 04 号中间产物。

与美、日、巴西、沙特四例的差别：
1. 非洲表与中东表同构，只有 6 列（城市名 / 国家 / OE 城市代码 / 地理级别 / 本地层级 / 本地名称），
   没有成员代码列，成员只能按名称定位。
2. 三国的成员层级不一致，且同一国里混层：
   - 南非：9 个城市全部落在 GADM L3（大都会市政 / 区市政），名称只差一个后缀
     （Metropolitan Municipality / District Municipality / Municipality）。
   - 埃及：亚历山大、塞得港、苏伊士是**省级**（L2 省 / Governorate）；开罗都市圈是 46 个 Kism（L3），
     横跨开罗、吉萨、盖勒尤卜三省；马哈拉与曼苏拉各 2 个 Kism；卢克索为 1 个 Kism 加 1 个 Markaz。
     成员名带阿拉伯语变音符，GADM 写法与之差别大，须去变音 + 去冠词 + 别名。
   - 尼日利亚：拉各斯与阿布贾在源表里是 State 级、**没有成员行**（整州当一城，落到 L2）；
     其余 14 城是 LGA（L3）。源表有 3 处拼写错误（Onistsha、Madiguri、Sabon），按确证别名修正。
3. 因此匹配不能全局做，必须先按「城市所属上级」限定候选集，再做 精确 -> 去冠词 -> 别名 -> 模糊。
   这一步是必要的而非保险：埃及 Al-Matariyah 在达卡利亚与开罗各有一个，尼日利亚 Nasarawa 在卡诺州
   与纳萨拉瓦州各有一个，不限定上级会错配。

产出：01 成员表、02 区底表（L2）、03 市底表（L3）、04 匹配结果_全量、04 匹配异常队列
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

sys.stdout.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
XLSX = os.path.join(os.path.dirname(ROOT), 'Global_Cities_Definitions_Oct19(1).xlsx')
GEOJSON_DIR = os.path.join(ROOT, 'GADM', 'geojson')
DEF_VERSION = 'Global_Cities_Definitions_Oct19'
SHEET = 'Africa'
FUZZY_CUTOFF = 0.82

# 阿拉伯语冠词前缀，长的排前面
ARTICLES = ('ash', 'al', 'ad', 'ar', 'as', 'az', 'at', 'an', 'el')
# 南非行政区名后缀：OE 写成全称，GADM 只留主体
ZAF_SUFFIX = ('metropolitanmunicipality', 'districtmunicipality', 'municipality')

# 埃及：成员名归一到 GADM 的别名表。键与值都是「去变音、去符号、小写」后的整串写法，
# 不经去冠词，避免 Alexandria 被剥成 exandria 这类误伤。
EGY_ALIAS = {
    'azbakeya': 'alazbakiyah',
    'elmarg': 'almarj',
    'matariyyah': 'almatariyah',
    'zamalek': 'zamalik',
    'zeitoun': 'azzaytun',
    'manshiyatnaser': 'monshatnasr',
    'tura': 'turah',
    'imbaba': 'imbabah',
    'rodelfarag': 'rudalfaraj',
    'azzawiyahalhamra': 'zawiyyaalhamra',
    'oldcairo': 'ancientcairo',
}
# 带数字的名字：先去尾数、映射词干、再接回数字（Shubra el-Kheima 1 -> Shubraal-Khaymah1）
EGY_STEM_ALIAS = {
    'shubraelkheima': 'shubraalkhaymah',
    'mahallaelkubra': 'almahallahalkubra',
    'elmansurah': 'almansurah',
}
# 整串别名（含数字、无法按词干处理的）
EGY_FULL_ALIAS = {
    '15thofmaycity': '15mayu',
}
# 尼日利亚：源表拼写错误与简写，按确证对应修正
NGA_ALIAS = {
    'onistsha': 'onitsha',
    'onistshanorth': 'onitshanorth',
    'madiguri': 'maiduguri',
    'sabon': 'sabongari',
    'okirika': 'okrika',
}

# 每个都市圈限定的上级（GID 前缀），用于消除同名歧义
METRO_PARENT = {
    # 南非：省
    'ZAF001': ['ZAF.3.'], 'ZAF002': ['ZAF.9.'], 'ZAF003': ['ZAF.2.'],
    'ZAF004': ['ZAF.4.'], 'ZAF005': ['ZAF.3.'], 'ZAF006': ['ZAF.8.'],
    'ZAF007': ['ZAF.1.'], 'ZAF008': ['ZAF.6.'], 'ZAF009': ['ZAF.5.'],
    # 埃及：省
    'EGY001': ['EGY.11.', 'EGY.8.', 'EGY.12.'], 'EGY002': ['EGY.6.'],
    'EGY003': ['EGY.20.'], 'EGY004': ['EGY.15.'], 'EGY005': ['EGY.5.'],
    'EGY006': ['EGY.1.'], 'EGY007': ['EGY.13.'],
    # 尼日利亚：州
    'NGA001': ['NGA.25.'], 'NGA002': ['NGA.20.'], 'NGA003': ['NGA.31.'],
    'NGA004': ['NGA.15.'], 'NGA005': ['NGA.33.'], 'NGA006': ['NGA.19.'],
    'NGA007': ['NGA.12.'], 'NGA008': ['NGA.31.'], 'NGA009': ['NGA.4.'],
    'NGA010': ['NGA.1.'], 'NGA011': ['NGA.8.'], 'NGA012': ['NGA.24.'],
    'NGA013': ['NGA.14.'], 'NGA014': ['NGA.32.'], 'NGA015': ['NGA.28.'],
    'NGA016': ['NGA.19.'],
}
# 省级成员（埃 3 城、尼 2 城）：源表 geo_level 为州/省，落 L2；成员行即城市自身，
# 故按城市名（而非成员名）取 L2。键为 OE 城市名归一化后的写法。
L2_METROS = {'EGY002', 'EGY003', 'EGY004', 'NGA001', 'NGA004'}
METRO_L2_GID = {
    'EGY002': 'EGY.6_1',    # Alexandria   -> AlIskandariyah
    'EGY003': 'EGY.20_1',   # Port Said    -> BurSa`id
    'EGY004': 'EGY.15_1',   # Suez         -> AsSuways
    'NGA001': 'NGA.25_1',   # Lagos        -> Lagos 州
    'NGA004': 'NGA.15_1',   # Abuja        -> FederalCapitalTerritory
}
# 显式映射：GADM 罗马化与 OE 写法差到模糊匹配不可靠时，逐条指定。
# 键为 (都市圈, 成员名归一化写法)，值可指 L2 或 L3，按 GID 自动判层。
EXPLICIT = {
    ('EGY007', 'aluqsur'): 'EGY.13.1_1',       # Luxor        -> Al-Uqsur 区（GADM 作 Luxor）
    ('EGY007', 'shurtahtibah'): 'EGY.13.2_1',  # Shurtah Tibah-> TibahPoliceDept.
    ('NGA002', 'kanomunicipal'): 'NGA.20.21_1',  # Kano Municipal -> 卡诺市 LGA
}


def base(s, keep_digits=True):
    """归一化：去重音、转小写、只留字母与数字"""
    s = unicodedata.normalize('NFKD', str(s or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c))
    pat = r'[^A-Za-z0-9]' if keep_digits else r'[^A-Za-z]'
    return re.sub(pat, '', s).lower()


def strip_article(k):
    for a in ARTICLES:
        if k.startswith(a) and len(k) > len(a) + 3:
            return k[len(a):]
    return k


def split_num(k):
    """拆出结尾数字：shubraelkheima1 -> ('shubraelkheima', '1')"""
    m = re.match(r'^(.*?)(\d+)$', k)
    return (m.group(1), m.group(2)) if m else (k, '')


def clean_member(s):
    """去掉 OE 成员名里的层级词与括号注记：'Abdīn Kism (fully urban)' -> 'Abdīn'"""
    s = re.sub(r'\([^)]*\)', '', str(s or '')).strip()
    s = re.sub(r'\s+(Kism|Markaz|Governorate|State|Province|District|Commune|'
               r'Municipality|Metropolitan Municipality|District Municipality|'
               r'Local Government Area|City)$', '', s, flags=re.I).strip()
    return s


def read_africa(targets):
    """按「第 0 列非空即新城市块」解析。新城市行必须无条件重置游标，
    否则上一国的续行会被并进下一个目标城市（初步试跑时卢克索曾因此多出 15 个异国成员）。"""
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    ws = wb[SHEET]
    cities, cur = [], None
    for i, r in enumerate(ws.iter_rows(min_row=4, values_only=True), start=4):
        r = tuple(list(r) + [None] * (8 - len(r)))
        cells = ['' if x is None else str(x).strip() for x in r]
        name, country, code, geo, lvl, local = cells[:6]
        if name:                                  # 新城市块：无论哪国，一律重置游标
            cur = None
            if country in targets:
                cur = {'name': name, 'country': country, 'oe_code': code,
                       'geo_level': geo, 'row': i, 'members': []}
                cities.append(cur)
                if local:
                    cur['members'].append({'level': lvl or geo, 'name': local,
                                           'row': i, 'role': 'self'})
        elif cur is not None and not country and not code and local:
            cur['members'].append({'level': lvl or geo, 'name': local,
                                   'row': i, 'role': 'member'})
    return cities


def load_gadm(iso3):
    d = None
    for x in os.listdir(GEOJSON_DIR):
        if x.startswith(iso3 + '_'):
            d = os.path.join(GEOJSON_DIR, x)
            break
    l2 = gpd.read_file(os.path.join(d, f'{iso3}_L2_adm1.geojson'), ignore_geometry=True)
    l3 = gpd.read_file(os.path.join(d, f'{iso3}_L3_adm2.geojson'), ignore_geometry=True)
    return d, l2, l3


def build_index(gdf, gid_col, name_col, type_col):
    """归一化名字索引：{归一化名: [(原始名, GID, TYPE), ...]}"""
    idx = collections.defaultdict(list)
    for _, r in gdf.iterrows():
        k = base(r[name_col])
        idx[k].append((str(r[name_col]), str(r[gid_col]), str(r[type_col])))
    return idx


def norm_key(name, iso3):
    """OE 成员名 -> 可比键（含国家特有别名展开）"""
    k = base(clean_member(name))
    if iso3 == 'ZAF':
        for suf in ZAF_SUFFIX:
            if k.endswith(suf) and len(k) > len(suf) + 3:
                k = k[: -len(suf)]
                break
    elif iso3 == 'EGY':
        if k in EGY_FULL_ALIAS:
            return EGY_FULL_ALIAS[k]
        stem, num = split_num(k)
        stem = EGY_STEM_ALIAS.get(stem, EGY_ALIAS.get(stem, stem))
        k = stem + num
    elif iso3 == 'NGA':
        k = NGA_ALIAS.get(k, k)
    return k


def match_one(iso3, key, idx, idx_strip, pref_prefixes, gid_to_type, name_of):
    """在限定上级内匹配：精确 -> 去冠词 -> 模糊。都不中返回 None。"""
    def in_pref(cands):
        if not pref_prefixes:
            return cands
        return [c for c in cands if any(c[1].startswith(p) for p in pref_prefixes)]

    cands = in_pref(idx.get(key, []))
    if len(cands) == 1:
        return cands[0], 'name_exact', 'high'
    if len(cands) > 1:
        return cands[0], 'name_exact_ambiguous', 'low'

    sk = strip_article(key)
    if sk in idx_strip:
        c = in_pref(idx_strip[sk])
        if len(c) == 1:
            return c[0], 'name_strip_article', 'high'
        if len(c) > 1:
            return c[0], 'name_strip_article_ambiguous', 'low'

    pool = [k for k in idx if in_pref(idx[k])]
    near = difflib.get_close_matches(sk, pool, n=2, cutoff=FUZZY_CUTOFF)
    if len(near) == 1:
        c = in_pref(idx[near[0]])
        return c[0], 'name_fuzzy', 'low'
    if len(near) > 1:
        c = in_pref(idx[near[0]])
        return c[0], 'name_fuzzy_ambiguous', 'low'
    return None


def main():
    targets = {'South Africa', 'Egypt', 'Nigeria'}
    cities = read_africa(targets)
    print('OE 非洲三国城市: %d 个 | 成员条目 %d 条（解析后，未修正）'
          % (len(cities), sum(len(c['members']) for c in cities)))
    for c in cities:
        print('  %-14s %-12s geo=%-20s 成员 %d'
              % (c['country'][:14], c['name'][:12], c['geo_level'] or '(原始层级看成员)', len(c['members'])))

    # ---- 01 成员表 ----
    rows = []
    for c in cities:
        mid = c['oe_code']          # OE 城市代码即 ZAF001 / EGY001 / NGA001，天然按国编号
        c['mid'] = mid
        # 拉各斯、阿布贾在源表里是 State 级且没有成员行（整州当一城）。若照成员表走会一行不剩、
        # 直接掉出图层，故补一条「整州」成员，与埃及的省组成圈同口径。
        if not c['members'] and mid in L2_METROS:
            c['members'].append({'level': c['geo_level'] or 'State', 'name': c['name'],
                                 'row': c['row'], 'role': 'whole_l2'})
        for m in c['members']:
            rows.append({'metro_id': mid, 'metro_name': c['name'], 'country': c['country'],
                         'geo_level': c['geo_level'], 'oe_city_code': c['oe_code'],
                         'member_level': m['level'], 'member_name': m['name'],
                         'member_clean': clean_member(m['name']),
                         'member_role': m['role'], 'source_sheet': SHEET,
                         'source_row': m['row'], 'def_version': DEF_VERSION})
    with open(os.path.join(HERE, '01_非洲经济定义_都市圈成员表.csv'), 'w',
              newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print('\n已写 01_非洲经济定义_都市圈成员表.csv（%d 行）' % len(rows))

    # ---- 底表 + 索引 ----
    all_out, all_queue = [], []
    for iso3, country in (('ZAF', 'South Africa'), ('EGY', 'Egypt'), ('NGA', 'Nigeria')):
        d, l2, l3 = load_gadm(iso3)
        with open(os.path.join(HERE, f'02_GADM_{iso3}_省州底表.csv'), 'w',
                  newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['gid_1', 'name_1', 'type_1', 'name_norm'])
            for _, r in l2.iterrows():
                w.writerow([r['GID_1'], r['NAME_1'], r['TYPE_1'], base(r['NAME_1'])])
        with open(os.path.join(HERE, f'03_GADM_{iso3}_市县底表.csv'), 'w',
                  newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['gid_2', 'gid_1', 'name_2', 'type_2', 'name_norm', 'name_norm_strip'])
            for _, r in l3.iterrows():
                kk = base(r['NAME_2'])
                w.writerow([r['GID_2'], r['GID_1'], r['NAME_2'], r['TYPE_2'],
                            kk, strip_article(kk)])
        print('  已写 %s 底表：L2 %d 行、L3 %d 行' % (iso3, len(l2), len(l3)))

        gid1name = {str(r['GID_1']): (str(r['NAME_1']), str(r['TYPE_1'])) for _, r in l2.iterrows()}
        gid2name = {str(r['GID_2']): (str(r['NAME_2']), str(r['TYPE_2'])) for _, r in l3.iterrows()}
        idx3 = build_index(l3, 'GID_2', 'NAME_2', 'TYPE_2')
        idx3s = collections.defaultdict(list)
        for kk, v in idx3.items():
            idx3s[strip_article(kk)].extend(v)
        idx2 = build_index(l2, 'GID_1', 'NAME_1', 'TYPE_1')
        idx2s = collections.defaultdict(list)
        for kk, v in idx2.items():
            idx2s[strip_article(kk)].extend(v)

        for row in [r for r in rows if r['country'] == country]:
            mid = row['metro_id']
            key = norm_key(row['member_name'], iso3)
            pref = METRO_PARENT.get(mid, [])
            hit = None
            if (mid, key) in EXPLICIT:
                gid = EXPLICIT[(mid, key)]
                if gid in gid2name:
                    hit = ((gid2name[gid][0], gid, gid2name[gid][1]), 'explicit', 'high')
                elif gid in gid1name:
                    hit = ((gid1name[gid][0], gid, gid1name[gid][1]), 'explicit', 'high')
            elif mid in L2_METROS:
                gid = METRO_L2_GID[mid]
                if gid in gid1name:
                    hit = ((gid1name[gid][0], gid, gid1name[gid][1]), 'metro_whole_l2', 'high')
            else:
                hit = match_one(iso3, key, idx3, idx3s, pref, None, None)
                if hit is None:      # 兜底：L3 找不到时再试 L2（埃及有 Markaz 落在省层的情形）
                    hit = match_one(iso3, key, idx2, idx2s, pref, None, None)
                    if hit:
                        hit = (hit[0], hit[1].replace('name_', 'name_l2_'), hit[2])
            if hit:
                (nm, gid, tp), meth, cf = hit
                row.update({'gid': gid, 'gadm_name': nm, 'type': tp,
                            'match_method': meth, 'confidence': cf})
            else:
                row.update({'gid': '', 'gadm_name': '', 'type': '',
                            'match_method': 'missing', 'confidence': ''})
                all_queue.append(row)
            all_out.append(row)

    for name, data in (('04_匹配结果_全量.csv', all_out), ('04_匹配异常队列.csv', all_queue)):
        with open(os.path.join(HERE, name), 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=list(data[0].keys()) if data else
                               ['metro_id', 'metro_name', 'member_name'])
            w.writeheader()
            w.writerows(data)

    # ---- 审核报告：逐条列出，便于人工过目 ----
    st = collections.Counter(r['match_method'] for r in all_out)
    print('\n=== 匹配结果（%d 条）===' % len(all_out))
    for k, v in st.most_common():
        print('  %-28s %d' % (k, v))
    ok = len(all_out) - len(all_queue)
    print('  匹配成功 %d / %d = %.2f%%' % (ok, len(all_out), 100.0 * ok / max(len(all_out), 1)))

    print('\n=== 逐城明细（★=成功、空=缺口、低=需人工复核）===')
    for c in cities:
        ms = [r for r in all_out if r['metro_id'] == c['mid']]
        print('\n  [%s] %s (%s) 成员 %d' % (c['mid'], c['name'], c['geo_level'] or '混层', len(ms)))
        for r in ms:
            mark = '★' if r['gid'] else '缺口'
            if r['gid'] and r['confidence'] == 'low':
                mark = '复核'
            print('    %-4s %-46s -> %-14s %-30s %s'
                  % (mark, r['member_clean'][:46], r['gid'] or '—',
                     (r['gadm_name'] or '—')[:30], r['match_method']))


if __name__ == '__main__':
    main()
