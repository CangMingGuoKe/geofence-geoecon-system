# -*- coding: utf-8 -*-
"""
日本经济定义层构建：仿照美国样例的做法，产出 01 至 04 号中间产物。

与美国的差别（日本特有的处理）：
1. OE 日本的成员是市町村，带 5 位 JIS 代码；而 GADM 日本 L3 的本地代码字段 CC_2 整列为 NA，
   两边没有共同字段可对，所以只能按「县 + 市町村」名字匹配（美国是靠 FIPS 码建桥）。
2. GADM 的日文罗马字与 OE 的写法有出入，需要四层归一化：去长音符、剥尾部类型词、
   合并写法（如 Ichinomiya/Owari-ichinomiya）拆开、罗马字变体（sy/sh、双辅音、词尾 oh/o）。
3. GADM 日本 L3 里混着非市町村单元（水体 2、郡 2、支厅 4、首都 1），建表时标出来，水体不参与匹配。

产出：01 成员表、02 县底表、03 市町村底表、04 匹配结果、04 匹配异常队列
"""
import csv, os, re, unicodedata, collections, difflib
import geopandas as gpd
import openpyxl

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
XLSX = os.path.join(os.path.dirname(ROOT), 'Global_Cities_Definitions_Oct19(1).xlsx')
DEF_VERSION = 'Global_Cities_Definitions_Oct19'
TYPE_WORDS = ('ken', 'to', 'fu', 'do', 'shi', 'machi', 'cho', 'mura', 'ku', 'gun', 'son', 'town', 'city')
NON_MUNI = ('Waterbody', 'Gun', 'Capital', 'Shichō')
OE_LEVEL2GADM = {'City (shi)': 'Shi', 'Town (machi)': 'Machi', 'Town (cho)': 'Machi',
                 'Village (mura)': 'Mura', 'Ward (ku)': 'SpecialWard'}


def base(s):
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[^A-Za-z]', '', s).lower()


def variants(b):
    """罗马字拼写变体：sy->sh、ty->ch、ou/oo->o、uu->u、词尾 oh->o、元音后 h 脱落、双辅音合一"""
    b = base(b)
    out = {b}
    t = b.replace('sy', 'sh').replace('ty', 'ch').replace('ou', 'o').replace('oo', 'o').replace('uu', 'u')
    t = re.sub(r'oh$', 'o', t)
    t = re.sub(r'([aeiou])h(?=[bcdfghjklmnpqrstvwxz])', r'\1', t)
    t = re.sub(r'([bcdfghjklmnpqrstvwxz])\1', r'\1', t)
    out.add(t)
    return out


def oe_pref(raw):
    parts = [p for p in re.split(r'[-\s]+', raw) if p]
    if len(parts) > 1 and parts[-1].lower() in ('ken', 'to', 'fu', 'do'):
        parts = parts[:-1]
    return ''.join(parts)


def oe_city(raw):
    parts = [p for p in re.split(r'[-\s]+', raw) if p]
    if len(parts) > 1 and parts[-1].lower() in TYPE_WORDS:
        parts = parts[:-1]
    return ''.join(parts)


def gadm_keys(name):
    """GADM 名字 -> 可匹配键集合：按 / 拆合并写法、剥尾部类型词、再生成变体"""
    out = set()
    for piece in re.split(r'[/|,;]', name):
        b = base(piece)
        if not b:
            continue
        cands = {b}
        for w in TYPE_WORDS:
            if b.endswith(w) and len(b) > len(w) + 2:
                cands.add(b[:-len(w)])
        for c in cands:
            out |= variants(c)
    return out


def read_oe_japan():
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    ws = wb['Asia']
    cities, cur = [], None
    for i, r in enumerate(ws.iter_rows(min_row=4, values_only=True), start=4):
        if r[0] and str(r[0]).strip():
            cur = None
            if (r[1] or '').strip() == 'Japan':
                cur = {'name': str(r[0]).strip(), 'oe_code': r[2], 'level': r[3], 'members': []}
                cities.append(cur)
                # 源表把第一个成员写在该城市行上（本地代码与本地名称列），其余成员才在续行。
                # 早先只收续行，导致每个都市圈漏掉一个市镇（日本漏 14 个，多为核心市本身）。
                if r[6]:
                    cur["members"].append({"level": r[4],
                                           "jis": str(r[5]).strip() if r[5] else "",
                                           "name": str(r[6]).strip(), "row": i})
        elif cur is not None and any(x is not None and str(x).strip() for x in r[4:7]):
            cur['members'].append({'level': r[4],
                                   'jis': str(r[5]).strip() if r[5] else '',
                                   'name': str(r[6]).strip() if r[6] else '',
                                   'row': i})
    return cities


def main():
    cities = read_oe_japan()
    print('OE 日本城市: %d 个 | 成员 %d 条' % (len(cities), sum(len(c['members']) for c in cities)))

    # ---- 01 成员表 ----
    rows = []
    for k, c in enumerate(cities, 1):
        for m in c['members']:
            rows.append({'metro_id': 'JPM%02d' % k, 'metro_name': c['name'], 'geo_level': c['level'],
                         'oe_city_code': c['oe_code'], 'member_level': m['level'], 'member_jis': m['jis'],
                         'member_name': m['name'], 'source_sheet': 'Asia', 'source_row': m['row'],
                         'def_version': DEF_VERSION})
    with open(os.path.join(HERE, '01_日本经济定义_都市圈成员表.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print('  已写 01_日本经济定义_都市圈成员表.csv（%d 行）' % len(rows))

    # ---- 02 / 03 GADM 底表 ----
    l2 = gpd.read_file(os.path.join(ROOT, 'GADM/geojson/JPN_日本/JPN_L2_adm1.geojson'), ignore_geometry=True)
    l3 = gpd.read_file(os.path.join(ROOT, 'GADM/geojson/JPN_日本/JPN_L3_adm2.geojson'), ignore_geometry=True)
    with open(os.path.join(HERE, '02_GADM日本_县底表.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['gid_1', 'name_1', 'type_1', 'hasc_1', 'name_1_norm'])
        for _, r in l2.iterrows():
            w.writerow([r['GID_1'], r['NAME_1'], r['TYPE_1'], r['HASC_1'], base(r['NAME_1'])])
    print('  已写 02_GADM日本_县底表.csv（%d 行）' % len(l2))

    prefname = dict(zip(l2['GID_1'], l2['NAME_1']))
    with open(os.path.join(HERE, '03_GADM日本_市町村底表.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['gid_2', 'gid_1', 'pref_name', 'muni_name', 'type_2', 'muni_norm', 'is_nonmunicipal'])
        for _, r in l3.iterrows():
            w.writerow([r['GID_2'], r['GID_1'], prefname.get(r['GID_1'], ''), r['NAME_2'], r['TYPE_2'],
                        base(r['NAME_2']), 'Y' if r['TYPE_2'] in NON_MUNI else ''])
    print('  已写 03_GADM日本_市町村底表.csv（%d 行，非市町村单元 %d 个）'
          % (len(l3), sum(1 for _, r in l3.iterrows() if r['TYPE_2'] in NON_MUNI)))

    # ---- 04 匹配 ----
    pref_of = {base(p): p for p in sorted(set(l3['NAME_1']))}
    pref_of['gumma'] = 'Gunma'
    idx = collections.defaultdict(lambda: collections.defaultdict(list))
    flat = collections.defaultdict(dict)
    for _, r in l3.iterrows():
        if r['TYPE_2'] == 'Waterbody':
            continue
        for k in gadm_keys(r['NAME_2']):
            idx[r['NAME_1']][k].append((r['NAME_2'], r['GID_2'], r['TYPE_2']))
        flat[r['NAME_1']][base(r['NAME_2'])] = (r['NAME_2'], r['GID_2'], r['TYPE_2'])

    out, queue = [], []
    for row in rows:
        p, n = row['member_name'].split(' ', 1)
        P = pref_of.get(base(oe_pref(p)))
        want = OE_LEVEL2GADM.get(row['member_level'], '')
        cands = []
        for k in variants(oe_city(n)):
            cands += idx.get(P, {}).get(k, [])
        cands = list(dict.fromkeys(cands))
        method, conf = '', ''
        if cands:
            method = 'name_exact'
            if len(cands) > 1:
                pick = [x for x in cands if x[2].lower().startswith(want.lower()[:4])]
                cands = pick or cands
                method = 'type_aware'
            conf = 'high'
        else:
            near = difflib.get_close_matches(base(oe_city(n)), list(flat.get(P, {})), n=1, cutoff=0.8)
            if near:
                cands = [flat[P][near[0]]]
                method, conf = 'name_fuzzy', 'medium'
        if cands:
            nm, gid, t2 = cands[0]
            row.update({'gid_2': gid, 'gadm_name': nm, 'type_2': t2,
                        'match_method': method, 'confidence': conf})
        else:
            row.update({'gid_2': '', 'gadm_name': '', 'type_2': '',
                        'match_method': 'missing', 'confidence': ''})
            queue.append(row)
        out.append(row)

    with open(os.path.join(HERE, '04_匹配结果_全量.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    with open(os.path.join(HERE, '04_匹配异常队列.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(queue)

    st = collections.Counter(r['match_method'] for r in out)
    print()
    print('=== 匹配结果 ===')
    for k in ('name_exact', 'type_aware', 'name_fuzzy', 'missing'):
        if st.get(k):
            print('  %-12s %d' % (k, st[k]))
    ok = len(out) - len(queue)
    print('  合计匹配 %d / %d = %.2f%%' % (ok, len(out), 100.0 * ok / len(out)))
    print('  缺口: %s' % [r['member_name'] for r in queue])


if __name__ == '__main__':
    main()
