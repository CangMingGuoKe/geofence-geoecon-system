from pathlib import Path
import csv,collections,json
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'outputs';OUT.mkdir(exist_ok=True)
with (ROOT/'raw/v1_member_matches.csv').open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
names=collections.defaultdict(set)
for r in rows:
 if r['match_status']=='matched':names[r['member_ags'][:2]].add(r['gadm_state'])
assert all(len(v)==1 for v in names.values())
data=[]
for state in sorted({r['member_ags'][:2] for r in rows}):
 rr=[r for r in rows if r['member_ags'].startswith(state)]
 counts=collections.Counter(r['match_status'] for r in rr)
 data.append({'state_code':state,'state_name':next(iter(names[state])) if names[state] else '', 'members':len(rr),'v1_matched':counts['matched'],'v1_match_rate':counts['matched']/len(rr),'not_found_by_rule':counts['not_found'],'aggregate_grain_conflict':counts['aggregate_grain_conflict'],'geometry_claim_collision':counts['geometry_claim_collision']})
with (OUT/'00_第一版各州问题诊断.csv').open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
print(json.dumps(data,ensure_ascii=False,indent=2))
