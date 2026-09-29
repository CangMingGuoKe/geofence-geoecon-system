# -*- coding: utf-8 -*-
"""
步骤 8 · 沙特样例的人工审核与版本记录（与美国、日本、巴西同一套设计）

设计原则（与前三例一致）：
  1. 原始数据不可覆盖：机器结果 07_沙特都市圈成员关系.csv 只读，永不改写。
  2. 追加式审计日志：每次人工动作追加一行到 08_审核日志.csv，可完整回溯。
  3. 审核状态 = 机器结果 + 审核日志（幂等重算），版本号随动作递增。

与前三例的差别只有定位字段：
  美国用县 FIPS 码，日本用 5 位 JIS 码，巴西用成员名（源表没有成员代码）；
  沙特同样用**成员名**，因为中东表连「本地代码」列都没有（表头只定义 6 列）。
  成员名在同一都市圈内唯一，可作键；含空格与阿拉伯语罗马化拼写，命令行调用须加引号，例如：
    python 08_审核工具.py mark-missing "SAUM01" "Dammam" --reviewer 黄丰 --reason "..."

审核动作：
  approve_metro    通过某都市圈全部「已有几何」的成员
  approve_member   通过某都市圈中的单个成员
  mark_missing     确认某成员缺失（记录理由与证据，不强行补几何）
  replace_member   替换某成员的几何（gid_before -> gid_after）
  add_member       新增成员（源表漏列的省）
  delete_member    删除成员（保留行、标记 deleted，不物理删除）

运行：
  python 08_审核工具.py init
  python 08_审核工具.py approve-all --reviewer 黄丰 --reason "机器匹配通过"
  python 08_审核工具.py mark-missing "SAUM01" "Dammam" --reviewer 黄丰 --reason "..." --evidence "..."
  python 08_审核工具.py status
"""
import argparse
import csv
import os
import sys
from collections import Counter
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
MACHINE = os.path.join(HERE, '07_沙特都市圈成员关系.csv')
LOG = os.path.join(HERE, '08_审核日志.csv')
STATE = os.path.join(HERE, '08_审核状态.csv')
VERSION = os.path.join(HERE, '08_版本记录.csv')

ECON_DEF_VERSION = 'Global_Cities_Definitions_Oct19'
GADM_VERSION = 'GADM 4.1'

LOG_COLS = ['audit_id', 'timestamp', 'action', 'metro_id', 'metro_name', 'member_name',
            'gid_before', 'gid_after', 'reviewer', 'reason', 'evidence_source',
            'econ_def_version', 'gadm_version']
STATE_COLS = ['metro_id', 'metro_name', 'member_name', 'member_role', 'region_name',
              'province_name', 'gid_2', 'type_2', 'match_method', 'confidence',
              'review_status', 'reviewer', 'review_time', 'review_reason']
VERSION_COLS = ['metro_id', 'metro_name', 'version', 'n_approved', 'n_replaced', 'n_added',
                'n_deleted', 'n_confirmed_missing', 'last_action', 'last_reviewer', 'last_time']


def load_machine():
    with open(MACHINE, encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def load_log():
    if not os.path.exists(LOG):
        return []
    with open(LOG, encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def append_log(actions):
    """追加写、自动编号与时间戳。"""
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
    return len(actions)


def apply(machine, log):
    """幂等重算：机器结果 + 日志 -> 每成员状态 + 每都市圈版本。"""
    members = {(m['metro_id'], m['member_name']): dict(m, review_status='pending', reviewer='',
                                                       review_time='', review_reason='')
               for m in machine}
    metro_name = {m['metro_id']: m['metro_name'] for m in machine}
    for a in log:                       # add_member 可能引入机器结果里没有的成员
        mid = a['metro_id']
        if a['action'] == 'add_member' and (mid, a['member_name']) not in members:
            members[(mid, a['member_name'])] = {
                'metro_id': mid, 'metro_name': metro_name.get(mid, ''),
                'member_name': a['member_name'], 'member_role': 'added', 'region_name': '',
                'province_name': '', 'gid_2': '', 'type_2': '',
                'match_method': 'manual_add', 'confidence': '',
                'review_status': 'pending', 'reviewer': '', 'review_time': '', 'review_reason': ''}
    for a in log:
        key = (a['metro_id'], a['member_name'])
        act = a['action']

        def mark(status, gid_after=None):
            m = members[key]
            if gid_after is not None:
                m['gid_2'] = gid_after
            m['review_status'] = status
            m['reviewer'] = a['reviewer']
            m['review_time'] = a['timestamp']
            m['review_reason'] = a['reason']

        if act == 'approve_metro':
            for k, m in members.items():
                # 只通过「确有几何」的成员；缺失须显式 mark_missing
                if k[0] == a['metro_id'] and m['review_status'] == 'pending' and m.get('gid_2', ''):
                    m['review_status'] = 'approved'
                    m['reviewer'] = a['reviewer']
                    m['review_time'] = a['timestamp']
                    m['review_reason'] = a['reason']
        elif act == 'approve_member' and key in members:
            if members[key].get('gid_2', ''):
                mark('approved')
        elif act == 'mark_missing' and key in members:
            mark('confirmed_missing')
        elif act == 'replace_member' and key in members:
            mark('replaced', a['gid_after'])
        elif act == 'add_member' and key in members:
            mark('added', a['gid_after'])
        elif act == 'delete_member' and key in members:
            mark('deleted')

    vers = {}
    for (mid, _), m in members.items():
        v = vers.setdefault(mid, {'metro_id': mid, 'metro_name': m['metro_name'], 'version': 0,
                                  'n_approved': 0, 'n_replaced': 0, 'n_added': 0, 'n_deleted': 0,
                                  'n_confirmed_missing': 0, 'last_action': '', 'last_reviewer': '',
                                  'last_time': ''})
        keymap = {'approved': 'n_approved', 'replaced': 'n_replaced', 'added': 'n_added',
                  'deleted': 'n_deleted', 'confirmed_missing': 'n_confirmed_missing'}
        if m['review_status'] in keymap:
            v[keymap[m['review_status']]] += 1
    act_count, last = Counter(), {}
    for a in log:
        act_count[a['metro_id']] += 1
        last[a['metro_id']] = (a['action'], a['reviewer'], a['timestamp'])
    for mid, v in vers.items():
        v['version'] = act_count.get(mid, 0)
        if mid in last:
            v['last_action'], v['last_reviewer'], v['last_time'] = last[mid]
    return members, vers


def write_outputs(members, vers):
    rows = [{k: m.get(k, '') for k in STATE_COLS}
            for m in sorted(members.values(), key=lambda m: (m['metro_id'], m['member_name']))]
    with open(STATE, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=STATE_COLS)
        w.writeheader()
        w.writerows(rows)
    vrows = sorted(vers.values(), key=lambda v: v['metro_id'])
    with open(VERSION, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=VERSION_COLS)
        w.writeheader()
        w.writerows(vrows)


def cmd_init():
    if os.path.exists(LOG):
        print('日志已存在，跳过初始化（如需重置请先删除 08_审核日志.csv）')
        return
    open(LOG, 'w', encoding='utf-8-sig').close()
    members, vers = apply(load_machine(), [])
    write_outputs(members, vers)
    print('已初始化：%d 条成员记录，全部 pending；版本记录 %d 个都市圈' % (len(members), len(vers)))


def cmd_status():
    members, vers = apply(load_machine(), load_log())
    write_outputs(members, vers)
    print('审核状态重算完成：', dict(Counter(m['review_status'] for m in members.values())))
    print('版本记录：%d 个都市圈' % len(vers))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd')
    sub.add_parser('init')
    sub.add_parser('status')
    p = sub.add_parser('approve-all')
    p.add_argument('--reviewer', required=True)
    p.add_argument('--reason', required=True)
    for name in ('mark-missing', 'replace', 'add', 'delete'):
        p = sub.add_parser(name)
        p.add_argument('metro')
        p.add_argument('member', help='成员名（含空格与罗马化拼写，请加引号）')
        if name in ('replace', 'add'):
            p.add_argument('new_gid')
        p.add_argument('--reviewer', required=True)
        p.add_argument('--reason', required=True)
        p.add_argument('--evidence', default='')
    sub.add_parser('reset')
    args = ap.parse_args()

    if args.cmd == 'init':
        cmd_init()
    elif args.cmd == 'status':
        cmd_status()
    elif args.cmd == 'reset':
        for f in (LOG, STATE, VERSION):
            if os.path.exists(f):
                os.remove(f)
        print('已清空日志/状态/版本，可重新开始')
    elif args.cmd == 'approve-all':
        machine = load_machine()
        metro_ids = sorted({m['metro_id'] for m in machine})
        n = append_log([{'action': 'approve_metro', 'metro_id': mid,
                         'metro_name': next(m['metro_name'] for m in machine if m['metro_id'] == mid),
                         'reviewer': args.reviewer, 'reason': args.reason} for mid in metro_ids])
        print('已追加 %d 条 approve_metro（每个都市圈一条），请再跑 status 重算' % n)
    else:
        act = {'mark-missing': 'mark_missing', 'replace': 'replace_member',
               'add': 'add_member', 'delete': 'delete_member'}[args.cmd]
        row = {'action': act, 'metro_id': args.metro, 'member_name': args.member,
               'reviewer': args.reviewer, 'reason': args.reason,
               'evidence_source': getattr(args, 'evidence', '')}
        if act in ('replace_member', 'add_member'):
            row['gid_after'] = args.new_gid
        for m in load_machine():
            if m['metro_id'] == args.metro and m['member_name'] == args.member:
                row['metro_name'] = m['metro_name']
                row['gid_before'] = m['gid_2']
                break
        n = append_log([row])
        print('已追加 %d 条 %s，请再跑 status 重算' % (n, act))


if __name__ == '__main__':
    main()
