# -*- coding: utf-8 -*-
"""
步骤8 · 人工审核与版本记录（最小数据闭环）

设计原则：
  1. 原始数据不可覆盖 —— 机器结果 07_美国都市圈成员关系.csv 只读，永不改写。
  2. 追加式审计日志 —— 每次人工动作追加一行到 08_审核日志.csv，可完整回溯。
  3. 审核状态 = 机器结果 + 审核日志（幂等重算），版本号随动作递增。

审核动作：
  approve_metro    通过某都市圈全部成员
  approve_member   通过某都市圈中的单个成员（按 county_fips 定位）
  mark_missing     确认某成员「缺失」（记录理由与证据，不强行补几何）
  replace_member   替换某成员的几何（gid_before -> gid_after）
  add_member       新增成员
  delete_member    删除成员（保留行、标记 deleted，不物理删除）

运行：
  python 08_审核工具.py init                # 初始化审核状态（pending）
  python 08_审核工具.py approve-all --reviewer 黄丰 --reason "机器匹配通过"
  python 08_审核工具.py mark-missing USM02 24510 --reviewer 黄丰 --reason "..." --evidence "..."
  python 08_审核工具.py status               # 重算并写出状态/版本/日志
"""
import csv, os, sys, json, argparse
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
MACHINE = os.path.join(HERE, '07_美国都市圈成员关系.csv')
LOG = os.path.join(HERE, '08_审核日志.csv')
STATE = os.path.join(HERE, '08_审核状态.csv')
VERSION = os.path.join(HERE, '08_版本记录.csv')

ECON_DEF_VERSION = 'Global_Cities_Definitions_Oct19'
GADM_VERSION = 'GADM 4.1'

LOG_COLS = ['audit_id','timestamp','action','metro_id','metro_name','county_fips','county_name',
            'gid_before','gid_after','reviewer','reason','evidence_source','econ_def_version','gadm_version']
STATE_COLS = ['metro_id','metro_name','cbsa_code','state_name','state_fips','county_name','county_fips',
              'fips5','gid_2','hasc_2','match_method','review_status','reviewer','review_time','review_reason']
VERSION_COLS = ['metro_id','metro_name','version','n_approved','n_replaced','n_added','n_deleted',
                'n_confirmed_missing','last_action','last_reviewer','last_time']


def load_machine():
    with open(MACHINE, encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def load_log():
    if not os.path.exists(LOG):
        return []
    with open(LOG, encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def append_log(actions):
    """actions: list of dicts; 追加写、自动编号与时间戳。"""
    old = load_log()
    next_id = len(old) + 1
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(LOG, 'a', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=LOG_COLS)
        if not old:
            w.writeheader()
        for a in actions:
            a = dict(a)
            a['audit_id'] = next_id
            a['timestamp'] = now
            a.setdefault('econ_def_version', ECON_DEF_VERSION)
            a.setdefault('gadm_version', GADM_VERSION)
            w.writerow({k: a.get(k, '') for k in LOG_COLS})
            next_id += 1


def apply(machine, log):
    """幂等重算审核状态：机器结果 + 日志 -> 每成员状态 + 版本。"""
    members = { (m['metro_id'], m['fips5']): dict(m, review_status='pending', reviewer='', review_time='', review_reason='')
                for m in machine }
    metro_name = {m['metro_id']: m['metro_name'] for m in machine}
    # 新增成员占位（add_member 可能引入 fips5 不在 machine 里）
    for a in log:
        mid = a['metro_id']
        if a['action'] == 'add_member' and (mid, a['county_fips']) not in members:
            members[(mid, a['county_fips'])] = {'metro_id': mid, 'metro_name': metro_name.get(mid, ''), 'county_fips': a['county_fips'],
                                                'county_name': a['county_name'], 'fips5': a['county_fips'], 'gid_2': '',
                                                'match_method': 'manual_add', 'review_status': 'pending'}
    for a in log:
        mid, fips = a['metro_id'], a['county_fips']
        act = a['action']
        if act == 'approve_metro':
            for k, m in members.items():
                # 仅通过「确有几何」的成员，缺失（gid_2 空）须显式 mark_missing
                if k[0] == mid and m['review_status'] == 'pending' and m.get('gid_2', ''):
                    m['review_status'] = 'approved'; m['reviewer'] = a['reviewer']
                    m['review_time'] = a['timestamp']; m['review_reason'] = a['reason']
        elif act == 'approve_member':
            if (mid, fips) in members:
                m = members[(mid, fips)]
                if m.get('gid_2', ''):
                    m['review_status'] = 'approved'; m['reviewer'] = a['reviewer']
                    m['review_time'] = a['timestamp']; m['review_reason'] = a['reason']
        elif act == 'mark_missing':
            if (mid, fips) in members:
                m = members[(mid, fips)]
                m['review_status'] = 'confirmed_missing'; m['reviewer'] = a['reviewer']
                m['review_time'] = a['timestamp']; m['review_reason'] = a['reason']
        elif act == 'replace_member':
            if (mid, fips) in members:
                m = members[(mid, fips)]
                m['gid_2'] = a['gid_after']; m['review_status'] = 'replaced'; m['reviewer'] = a['reviewer']
                m['review_time'] = a['timestamp']; m['review_reason'] = a['reason']
        elif act == 'add_member':
            if (mid, fips) in members:
                m = members[(mid, fips)]
                m['gid_2'] = a['gid_after']; m['review_status'] = 'added'; m['reviewer'] = a['reviewer']
                m['review_time'] = a['timestamp']; m['review_reason'] = a['reason']
        elif act == 'delete_member':
            if (mid, fips) in members:
                m = members[(mid, fips)]
                m['review_status'] = 'deleted'; m['reviewer'] = a['reviewer']
                m['review_time'] = a['timestamp']; m['review_reason'] = a['reason']
    # 版本记录：版本号 = 作用于该都市圈的审核动作数；last_* = 最近一次动作
    from collections import Counter
    vers = {}
    for (mid, fips), m in members.items():
        v = vers.setdefault(mid, {'metro_id': mid, 'metro_name': m['metro_name'], 'version': 0,
                                  'n_approved':0,'n_replaced':0,'n_added':0,'n_deleted':0,'n_confirmed_missing':0,
                                  'last_action':'','last_reviewer':'','last_time':''})
        st = m['review_status']
        keymap = {'approved':'n_approved','replaced':'n_replaced','added':'n_added',
                  'deleted':'n_deleted','confirmed_missing':'n_confirmed_missing'}
        if st in keymap:
            v[keymap[st]] += 1
    act_count = Counter(); last = {}
    for a in log:
        mid = a['metro_id']
        act_count[mid] += 1
        last[mid] = (a['action'], a['reviewer'], a['timestamp'])
    for mid, v in vers.items():
        v['version'] = act_count.get(mid, 0)
        if mid in last:
            v['last_action'], v['last_reviewer'], v['last_time'] = last[mid]
    return members, vers


def write_outputs(members, vers):
    # 状态（只写 STATE_COLS 字段，剔除机器结果里的 confidence 等额外键）
    state_rows = [{k: m.get(k, '') for k in STATE_COLS}
                  for m in sorted(members.values(), key=lambda m: (m['metro_id'], m['fips5']))]
    with open(STATE, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=STATE_COLS); w.writeheader(); w.writerows(state_rows)
    # 版本
    vrows = sorted(vers.values(), key=lambda v: v['metro_id'])
    with open(VERSION, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=VERSION_COLS); w.writeheader(); w.writerows(vrows)


def cmd_init():
    if os.path.exists(LOG):
        print('日志已存在，跳过初始化（如需重置请先删除 08_审核日志.csv）')
        return
    open(LOG, 'w', encoding='utf-8-sig').close()
    machine = load_machine()
    members, vers = apply(machine, [])
    write_outputs(members, vers)
    print('已初始化审核状态：%d 条成员记录，全部 pending；版本记录 %d 个都市圈' % (len(machine), len(vers)))


def cmd_status():
    members, vers = apply(load_machine(), load_log())
    write_outputs(members, vers)
    from collections import Counter
    c = Counter(m['review_status'] for m in members.values())
    print('审核状态重算完成：', dict(c))
    print('版本记录：%d 个都市圈' % len(vers))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd')

    p = sub.add_parser('init')
    p = sub.add_parser('status')

    p = sub.add_parser('approve-all')
    p.add_argument('--reviewer', required=True); p.add_argument('--reason', required=True)

    p = sub.add_parser('mark-missing')
    p.add_argument('metro'); p.add_argument('fips')
    p.add_argument('--reviewer', required=True); p.add_argument('--reason', required=True)
    p.add_argument('--evidence', default='')

    p = sub.add_parser('replace')
    p.add_argument('metro'); p.add_argument('fips'); p.add_argument('new_gid')
    p.add_argument('--reviewer', required=True); p.add_argument('--reason', required=True)
    p.add_argument('--evidence', default='')

    p = sub.add_parser('add')
    p.add_argument('metro'); p.add_argument('fips'); p.add_argument('new_gid'); p.add_argument('county_name')
    p.add_argument('--reviewer', required=True); p.add_argument('--reason', required=True)
    p.add_argument('--evidence', default='')

    p = sub.add_parser('delete')
    p.add_argument('metro'); p.add_argument('fips')
    p.add_argument('--reviewer', required=True); p.add_argument('--reason', required=True)
    p.add_argument('--evidence', default='')

    p = sub.add_parser('reset')

    args = ap.parse_args()
    if args.cmd == 'init':
        cmd_init(); return
    if args.cmd == 'status':
        cmd_status(); return
    if args.cmd == 'reset':
        for f in (LOG, STATE, VERSION):
            if os.path.exists(f):
                os.remove(f)
        print('已清空审核日志/状态/版本，可重新 init')
        return

    machine = load_machine()
    meta = {m['metro_id']: m for m in machine}
    if args.cmd == 'approve-all':
        mid_set = sorted(set(m['metro_id'] for m in machine))
        append_log([{'action':'approve_metro','metro_id':mid,'metro_name':meta[mid]['metro_name'],
                     'reviewer':args.reviewer,'reason':args.reason} for mid in mid_set])
        print('批量通过 %d 个都市圈' % len(mid_set))
    elif args.cmd == 'mark-missing':
        append_log([{'action':'mark_missing','metro_id':args.metro,'metro_name':meta.get(args.metro,{}).get('metro_name',''),
                     'county_fips':args.fips,'county_name':next((m['county_name'] for m in machine if m['metro_id']==args.metro and m['fips5']==args.fips),''),
                     'reviewer':args.reviewer,'reason':args.reason,'evidence_source':args.evidence}])
        print('已确认缺失 %s %s' % (args.metro, args.fips))
    elif args.cmd == 'replace':
        append_log([{'action':'replace_member','metro_id':args.metro,'metro_name':meta.get(args.metro,{}).get('metro_name',''),
                     'county_fips':args.fips,'county_name':next((m['county_name'] for m in machine if m['metro_id']==args.metro and m['fips5']==args.fips),''),
                     'gid_before':next((m['gid_2'] for m in machine if m['metro_id']==args.metro and m['fips5']==args.fips),''),
                     'gid_after':args.new_gid,'reviewer':args.reviewer,'reason':args.reason,'evidence_source':args.evidence}])
    elif args.cmd == 'add':
        append_log([{'action':'add_member','metro_id':args.metro,'metro_name':meta.get(args.metro,{}).get('metro_name',''),
                     'county_fips':args.fips,'county_name':args.county_name,'gid_after':args.new_gid,
                     'reviewer':args.reviewer,'reason':args.reason,'evidence_source':args.evidence}])
    elif args.cmd == 'delete':
        append_log([{'action':'delete_member','metro_id':args.metro,'metro_name':meta.get(args.metro,{}).get('metro_name',''),
                     'county_fips':args.fips,'county_name':next((m['county_name'] for m in machine if m['metro_id']==args.metro and m['fips5']==args.fips),''),
                     'gid_before':next((m['gid_2'] for m in machine if m['metro_id']==args.metro and m['fips5']==args.fips),''),
                     'reviewer':args.reviewer,'reason':args.reason,'evidence_source':args.evidence}])
    cmd_status()


if __name__ == '__main__':
    main()
