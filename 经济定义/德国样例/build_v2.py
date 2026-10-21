"""Reconstruct OECD FUAs using exact official municipality codes and one geometry vintage."""
from pathlib import Path
import sys,csv,json,zipfile,io,collections,unicodedata,re
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'.runtime'))

import shapefile
from shapely.geometry import shape,mapping
from shapely import union_all,make_valid
from shapely.ops import transform
from pyproj import Transformer
RAW,OUT=ROOT/'raw',ROOT/'outputs';OUT.mkdir(exist_ok=True)
def read(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write(name,rows,fields=None):
 with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields or list(rows[0]));w.writeheader();w.writerows(rows)
def norm(s):
 return re.sub(r'[^a-z0-9]','', ''.join(c for c in unicodedata.normalize('NFKD',s.casefold()) if not unicodedata.combining(c)))
members=[r for r in read(RAW/'fua_cities_sau_mapping.csv') if r['iso3']=='DEU']
old=read(RAW/'v1_member_matches.csv')
oldidx={(r['fuacode'],r['pk']):r for r in old}
with zipfile.ZipFile(RAW/'LAU_RG_01M_2024_4326.shp.zip') as z:
 base=next(n[:-4] for n in z.namelist() if n.endswith('.shp'))
 reader=shapefile.Reader(shp=io.BytesIO(z.read(base+'.shp')),shx=io.BytesIO(z.read(base+'.shx')),dbf=io.BytesIO(z.read(base+'.dbf')),encoding='utf-8')
 attrs=[r.as_dict() for r in reader.iterRecords()]
 print('Source fields',list(attrs[0]),flush=True)
 germany=[]
 for i,p in enumerate(attrs):
  if p['CNTR_CODE']=='DE':germany.append({'type':'Feature','properties':p,'geometry':reader.shape(i).__geo_interface__})
print('Official German LAUs',len(germany),flush=True)
(RAW/'germany_lau_2024.geojson').write_text(json.dumps({'type':'FeatureCollection','features':germany},ensure_ascii=False,separators=(',',':')),encoding='utf-8')
index=collections.defaultdict(list)
for f in germany:index[f['properties']['GISCO_ID'].removeprefix('DE_')].append(f)
assert all(len(v)==1 for v in index.values()), 'Duplicate official LAU codes require review'
namefield=next((k for k in ['LAU_NAME','NAME_LATN','NAME_LAT','NAME'] if k in germany[0]['properties']),None)
assert namefield,'Unrecognised official name field'
rows=[]
for m in members:
 code=m['pk'][3:];f=index.get(code,[None])[0];prior=oldidx[(m['fuacode'],m['pk'])]
 p=f['properties'] if f else {}
 rows.append({**m,'member_ags':code,'official_lau_id':p.get('GISCO_ID','').removeprefix('DE_'), 'official_name':p.get(namefield,''),'match_status':'exact_code' if f else 'unresolved_code','name_agrees':norm(m['name_lat'])==norm(p.get(namefield,'')) if f else False,'geometry_source':'Eurostat GISCO LAU 2024, 01M' if f else '', 'geometry_year':2024 if f else '', 'v1_status':prior['match_status'],'v1_gid_3':prior['gid_3'],'v1_candidates':prior['candidate_gids'],'review_status':'pending'})
write('01_德国成员编码匹配_v2.csv',rows)
write('02_仍待解决的成员.csv',[r for r in rows if r['match_status']=='unresolved_code'],list(rows[0]))
write('03_同码名称差异.csv',[r for r in rows if r['match_status']=='exact_code' and not r['name_agrees']],list(rows[0]))
write('04_与第一版逐成员比较.csv',rows)
groups=collections.defaultdict(list)
for r in rows:groups[r['fuacode']].append(r)
project=Transformer.from_crs(4326,3035,always_xy=True).transform
catalog=[];features=[];repairs=[]
for code,rr in sorted(groups.items()):
 parts=[]
 for r in rr:
  if r['match_status']!='exact_code':continue
  g=shape(index[r['member_ags']][0]['geometry'])
  if not g.is_valid:
   repairs.append({'fua_code':code,'member_ags':r['member_ags'],'action':'make_valid','review_status':'pending'})
   g=make_valid(g)
  assert g.is_valid and not g.is_empty
  parts.append(g)
 g=union_all(parts) if parts else None
 matched=len(parts);missing=len(rr)-matched
 prop={'fua_code':code,'fua_name':rr[0]['fuaname_en'],'members_total':len(rr),'members_matched':matched,'members_unresolved':missing,'coverage_status':'complete_by_code' if not missing else 'partial','definition_source':'OECD member mapping','geometry_source':'Eurostat GISCO LAU 2024, 01M','geometry_year':2024,'definition_vintage':'not yet confirmed','review_status':'pending','geometry_valid':bool(g is not None and g.is_valid),'area_km2_epsg3035':transform(project,g).area/1e6 if g is not None else None,'v1_matched_members':sum(r['v1_status']=='matched' for r in rr),'name_differences':sum(r['match_status']=='exact_code' and not r['name_agrees'] for r in rr)}
 catalog.append(prop)
 if g is not None:
  assert g.is_valid and not g.is_empty
  features.append({'type':'Feature','properties':prop,'geometry':mapping(g)})
write('05_德国FUA覆盖比较_v2.csv',catalog)
write('06_几何修复记录.csv',repairs,['fua_code','member_ags','action','review_status'])
(OUT/'07_德国FUA_官方市镇拼合_v2.geojson').write_text(json.dumps({'type':'FeatureCollection','features':features},ensure_ascii=False,separators=(',',':')),encoding='utf-8')
stats={'members':len(rows),'matched':sum(r['match_status']=='exact_code' for r in rows),'unresolved':sum(r['match_status']=='unresolved_code' for r in rows),'name_differences':sum(r['match_status']=='exact_code' and not r['name_agrees'] for r in rows),'fuas':len(groups),'complete_by_code':sum(c['coverage_status']=='complete_by_code' for c in catalog),'partial':sum(c['coverage_status']=='partial' for c in catalog),'official_german_laus':len(germany),'geometry_repairs':len(repairs),'geometry_source':'GISCO 2024 LAU, 01M; not GADM','reference_comparison':'pending'}
(OUT/'quality_summary.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(stats,ensure_ascii=False,indent=2))
print('Unresolved saved to exception CSV')
