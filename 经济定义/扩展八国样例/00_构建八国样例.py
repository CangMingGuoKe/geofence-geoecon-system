# -*- coding: utf-8 -*-
"""
八国经济定义层构建：马来西亚 / 泰国 / 阿根廷 / 秘鲁 / 摩洛哥 / 阿联酋 六国成圈，
伊朗与新西兰只做行政层（见文末说明），产物为 01 至 04 号中间文件。

与非洲样例的做法一致：成员按名称匹配，先按「都市圈所属上级」限定候选集，
再走 精确 -> 去变音 -> 别名 -> 模糊。差别在于成员层级各不相同：
  马来西亚  区（District）        -> GADM ADM2（L3）
  泰国      府（Province）        -> GADM ADM1（L2），只有曼谷一圈
  阿根廷    省（Department）      -> GADM ADM2（L3），首都自治市在 ADM1（L2）
  秘鲁      区（District）        -> GADM ADM3（L4）
  摩洛哥    省 / 市镇             -> GADM ADM2 / ADM3（L3 / L4）
  阿联酋    酋长国（Emirate）      -> GADM ADM1（L2）
伊朗与新西兰的成员都是「城市自身」，源表给的是 City Proper / Regional Council，
做出多边形也只是整市或整大区，不是都市圈，按用户口径这两国只上行政层。
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
FUZZY = 0.85

# 每个国家：大洲表、OE 里的国家名、按优先级排列的 GADM 层（3=L3，4=L4，2=L2）
CFG = {
    'MYS': {'sheet': 'Asia',          'country': 'Malaysia',              'levels': ['3']},
    'THA': {'sheet': 'Asia',          'country': 'Thailand',              'levels': ['2']},
    'ARG': {'sheet': 'Latin America', 'country': 'Argentina',             'levels': ['3', '2']},
    'PER': {'sheet': 'Latin America', 'country': 'Peru',                  'levels': ['4', '3']},
    # 摩洛哥 GADM 仍是 2015 年改革前的区划：大卡萨布兰卡的努瓦塞尔、梅迪乌纳两省在 ADM2 缺失，
    # ADM3 的同名单元是圈（Cercle）或城市公社，与源表的「省 / 市镇」不是同一口径，故只按 ADM2 匹配。
    'MAR': {'sheet': 'Africa',        'country': 'Morocco',               'levels': ['3']},
    'ARE': {'sheet': 'Middle East',   'country': 'United Arab Emirates',  'levels': ['2']},
}

# 上级限定：都市圈 -> 允许的上级 GID 前缀。用于消解同名（如阿根廷多个省都有 San Martín，
# 秘鲁多个省都有 Miraflores / La Esperanza / Santa Rosa）。键用 (ISO3, OE 城市名)，因为
# OE 的城市代码带后缀（ARG1C、PER4C），不适合当配置键。
PARENT_GID = {
    ('ARG', 'Buenos Aires'): ['ARG.1.', 'ARG.5_'],   # ARG.5_1 是首都自治市（CABA），L2 的 GID 用下划线
    ('ARG', 'La Plata'): ['ARG.1.'],
    ('PER', 'Arequipa'): ['PER.4.1.'],
    ('PER', 'Trujillo'): ['PER.13.11.'],
    ('PER', 'Chiclayo'): ['PER.14.1.', 'PER.14.3.'],
    ('MAR', 'Casablanca'): ['MAR.5.'],
    ('MAR', 'Rabat'): ['MAR.11.'],
    ('MAR', 'Tangier'): ['MAR.14.'],
}

# 手工别名：OE 写法 -> GADM 写法（均为归一化前的原串，便于核对）
ALIAS = {
    # 阿根廷：OE 给的是城市名，GADM 的行政单元是 partido（县）
    'San Justo': 'La Matanza', 'Adrogué': 'Almirante Brown', 'Caseros': 'Tres de Febrero',
    'Los Polvorines': 'Malvinas Argentinas', 'Monte Grande': 'Esteban Echeverría',
    'Olivos': 'Vicente López', 'Buenos Aires': 'Ciudad de Buenos Aires',
    'San Martín': 'General San Martín',
    # 秘鲁：源表拼写与 GADM 不一致
    'Cerra Colorado': 'Cerro Colorado', 'Jose L. Bustamante Y Rivero': 'José Luis Bustamante y Rivero',
    'Leonardi Ortiz': 'Jose Leonardo Ortiz', 'Puerto Eten': 'Eten Puerto',
    # 摩洛哥
    'Rabat Province': 'Rabat', 'Sale Prefecture': 'Salé', 'AitMelloul': 'Ait Melloul',
    # 马来西亚
    'Central Malacca': 'Melaka Tengah', 'Johor Bahru': 'Johor Baharu',
    # 阿联酋：源表带 (full)/(part) 注记
    'Dubai (full)': 'Dubai', 'Sharjah (part)': 'Sharjah', 'Ajman (part)': 'Ajman',
}


def gadm_name(s):
    """GADM 摩洛哥的 ADM3 把名字写成 'NA(BenSlimane)' 这种形式，剥掉外壳取真名。"""
    s = str(s)
    m = re.match(r'^NA\((.*)\)$', s)
    return m.group(1) if m else s


def base(s):
    s = unicodedata.normalize('NFKD', str(s or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[^A-Za-z0-9]', '', s).lower()


def clean_member(s):
    s = re.sub(r'\([^)]*\)', '', str(s or '')).strip()
    s = re.sub(r'\s+(Kism|Markaz|Governorate|Province|District|Department|Commune|'
               r'Municipality|Region|Emirate|Autonomous City|Federal District|'
               r'City Proper|Metropolitan Area|Urban Agglomeration|Regional Council)$',
               '', s, flags=re.I).strip()
    return s


def read_oe(target):
    """读一个国家在指定大洲表里的全部城市块。新城市行无条件重置游标，避免跨城市串行。"""
    out = []
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    ws = wb[target['sheet']]
    rows = list(ws.iter_rows(values_only=True))
    hi = None
    for i, r in enumerate(rows[:20]):
        c = ['' if x is None else str(x).strip() for x in r]
        if c and c[0].lower() == 'oe city name':
            hi, hdr = i, c
            break
    def col(n):
        for j, h in enumerate(hdr):
            if h.lower() == n:
                return j
        return None
    cc, ccode = col('country'), col('oe city code')
    cl_, clv, cg = col('local region name'), col('local region level'), col('geographic level')
    cur = None
    for i in range(hi + 1, len(rows)):
        r = tuple(list(rows[i]) + [None] * 12)
        c = ['' if x is None else str(x).strip() for x in r]
        nm, ct = c[0], c[cc] if cc is not None else ''
        lc = c[cl_] if cl_ is not None else ''
        lvl = c[clv] if clv is not None else ''
        geo = c[cg] if cg is not None else ''
        if nm and ct:
            cur = None
            if ct == target['country']:
                cur = {'name': nm, 'code': c[ccode] if ccode is not None else '',
                       'geo': geo, 'members': []}
                out.append(cur)
                if lc:
                    cur['members'].append({'level': lvl or geo, 'name': lc, 'role': 'self'})
        elif cur is not None and not nm and not ct and lc:
            cur['members'].append({'level': lvl or geo, 'name': lc, 'role': 'member'})
    return out


def load_layers(iso3):
    d = None
    for x in os.listdir(GEOJSON_DIR):
        if x.startswith(iso3 + '_'):
            d = os.path.join(GEOJSON_DIR, x)
            break
    layers = {}
    for lv, adm in (('2', 'adm1'), ('3', 'adm2'), ('4', 'adm3')):
        p = os.path.join(d, f'{iso3}_L{lv}_{adm}.geojson')
        if os.path.exists(p):
            layers[lv] = gpd.read_file(p, ignore_geometry=True)
    return d, layers


def build_index(gdf, lv):
    gidc = {'2': 'GID_1', '3': 'GID_2', '4': 'GID_3'}[lv]
    namec = {'2': 'NAME_1', '3': 'NAME_2', '4': 'NAME_3'}[lv]
    typec = {'2': 'TYPE_1', '3': 'TYPE_2', '4': 'TYPE_3'}[lv]
    parentc = {'2': None, '3': 'NAME_1', '4': 'NAME_2'}[lv]
    idx = collections.defaultdict(list)
    for _, r in gdf.iterrows():
        nm = gadm_name(r[namec])
        idx[base(nm)].append((nm, str(r[gidc]), str(r[typec]),
                              str(r[parentc]) if parentc and parentc in gdf.columns else ''))
    return idx


def main():
    rows_all, queue_all = [], []
    for iso3, cfg in CFG.items():
        cities = read_oe(cfg)
        print('\n=== %s %s：%d 城，成员 %d 条'
              % (iso3, cfg['country'], len(cities), sum(len(c['members']) for c in cities)))
        d, layers = load_layers(iso3)
        idxs = {lv: build_index(g, lv) for lv, g in layers.items()}

        for c in cities:
            pref = PARENT_GID.get((iso3, c['name']), [])
            for m in c['members']:
                raw = m['name']
                clean = clean_member(raw)
                key = base(ALIAS.get(clean, clean))
                hit = None
                for lv in cfg['levels']:
                    idx = idxs.get(lv, {})

                    def under_pref(xs):
                        return [x for x in xs if any(x[1].startswith(p) for p in pref)]

                    cand = under_pref(idx.get(key, [])) if pref else idx.get(key, [])
                    if pref and not cand:
                        # GADM 对同省重名会写成 SanFernando(1)/(2)，归一化后是 sanfernando1
                        for d in ('1', '2', '3'):
                            c2 = under_pref(idx.get(key + d, []))
                            if c2:
                                cand = c2
                                break
                    if len(cand) == 1:
                        hit = (cand[0], lv, 'name_exact')
                        break
                    if len(cand) > 1:
                        hit = (cand[0], lv, 'name_exact_ambiguous')
                        break
                    # 模糊只在限定上级内做；有上级限定就不跨省回退，宁记缺口也不错配
                    pool = [k for k in idx if (not pref or under_pref(idx[k]))]
                    near = difflib.get_close_matches(key, pool, n=1, cutoff=FUZZY)
                    if near:
                        cc = under_pref(idx[near[0]]) if pref else idx[near[0]]
                        hit = (cc[0], lv, 'name_fuzzy')
                        break
                    if pref:
                        continue
                row = {'metro_id': c['code'], 'metro_name': c['name'], 'country': cfg['country'],
                       'iso3': iso3, 'geo_level': c['geo'], 'member_level': m['level'],
                       'member_name': raw, 'member_role': m['role'],
                       'def_version': DEF_VERSION}
                if hit:
                    (nm, gid, tp, par), lv, meth = hit
                    row.update({'gid': gid, 'gadm_name': nm, 'type': tp, 'parent': par,
                                'gadm_level': 'L' + lv, 'method': meth})
                else:
                    row.update({'gid': '', 'gadm_name': '', 'type': '', 'parent': '',
                                'gadm_level': '', 'method': 'missing'})
                    queue_all.append(row)
                rows_all.append(row)

    with open(os.path.join(HERE, '04_匹配结果_全量.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(rows_all[0].keys()))
        w.writeheader(); w.writerows(rows_all)
    cols = list(rows_all[0].keys())
    with open(os.path.join(HERE, '04_匹配异常队列.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(queue_all)

    st = collections.Counter(r['method'] for r in rows_all)
    print('\n=== 合计 %d 条 ===' % len(rows_all))
    for k, v in st.most_common():
        print('  %-24s %d' % (k, v))
    ok = len(rows_all) - len(queue_all)
    print('  成功 %d / %d = %.2f%%' % (ok, len(rows_all), 100.0 * ok / max(len(rows_all), 1)))

    print('\n=== 逐城（★成功 / 缺口）===')
    for mid in dict.fromkeys(r['metro_id'] for r in rows_all):
        ms = [r for r in rows_all if r['metro_id'] == mid]
        print('\n  [%s] %s  %d 成员' % (mid, ms[0]['metro_name'], len(ms)))
        for r in ms:
            print('    %-4s %-40s -> %-14s %-28s %s'
                  % ('★' if r['gid'] else '缺口', r['member_name'][:40], r['gid'] or '—',
                     (r['gadm_name'] or '—')[:28], r['method']))


if __name__ == '__main__':
    main()
