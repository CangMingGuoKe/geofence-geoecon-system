"""Keep exact joins distinct from documented mergers; compare independently supplied FUA geometry."""
from pathlib import Path
import sys,json,csv,collections,sqlite3,struct
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parent

from shapely.geometry import shape,mapping,MultiPolygon
from shapely import union_all,make_valid,to_wkb,from_wkb
from shapely.ops import transform
from pyproj import Transformer,CRS
OUT=ROOT/'outputs';RAW=ROOT/'raw'
def read(p):return list(csv.DictReader(p.open(encoding='utf-8-sig',newline='')))
def write(name,rr,fields=None):
 with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields or list(rr[0]));w.writeheader();w.writerows(rr)
mergers=[
 {'old_ags':'01059101','old_name':'Tastrup','successor_ags':'01059126','successor_name':'Hürup','effective_date':'2023-03-01','fua_code':'DE049F','evidence_url':'https://www.schleswig-holstein.de/DE/landesregierung/ministerien-behoerden/IV/Presse/PI/2023/230303_Gemeindefusion'},
 {'old_ags':'01059141','old_name':'Maasbüll','successor_ags':'01059126','successor_name':'Hürup','effective_date':'2023-03-01','fua_code':'DE049F','evidence_url':'https://www.schleswig-holstein.de/DE/landesregierung/ministerien-behoerden/IV/Presse/PI/2023/230303_Gemeindefusion'},
 {'old_ags':'16076026','old_name':'Hartmannsdorf','successor_ags':'16076003','successor_name':'Bad Köstritz','effective_date':'2023-01-01','fua_code':'DE113F','evidence_url':'https://statistik.thueringen.de/datenbank/gebiet3.asp?nr=76003'}]
rows=read(OUT/'01_德国成员编码匹配_v2.csv');idx={r['member_ags']:r for r in rows}
for m in mergers:
 assert idx[m['old_ags']]['match_status']=='unresolved_code'
 successor=idx[m['successor_ags']]
 assert successor['match_status']=='exact_code' and successor['fuacode']==m['fua_code']==idx[m['old_ags']]['fuacode']
 m.update(successor_already_in_same_fua=True,geometry_action='already contained in successor polygon; do not add duplicate geometry',review_status='pending')
write('08_历史行政合并证据.csv',mergers)
mi={m['old_ags']:m for m in mergers}
for r in rows:
 m=mi.get(r['member_ags'])
 r['coverage_method']='documented_merger_into_existing_member' if m else 'exact_code'
 r['geometry_ags']=m['successor_ags'] if m else r['official_lau_id']
 r['merger_effective_date']=m['effective_date'] if m else ''
 r['merger_evidence_url']=m['evidence_url'] if m else ''
 r['old_municipality_geometry_available']=False if m else True
write('09_成员追溯与2024边界对应.csv',rows)
fc=json.loads((OUT/'07_德国FUA_官方市镇拼合_v2.geojson').read_text(encoding='utf-8'))
for f in fc['features']:
 p=f['properties'];rr=[r for r in rows if r['fuacode']==p['fua_code']]
 p.update(members_accounted_2024=sum(bool(r['geometry_ags']) for r in rr),merger_predecessor_members=sum(r['coverage_method']!='exact_code' for r in rr),distinct_geometry_units=len({r['geometry_ags'] for r in rr}),coverage_status_2024='all_members_accounted_with_documented_mergers',historical_boundary_identity='not independently established')
(OUT/'10_德国FUA_2024口径边界.geojson').write_text(json.dumps(fc,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
write('10_德国FUA_2024覆盖汇总.csv',[f['properties'] for f in fc['features']])
project=Transformer.from_crs(4326,3035,always_xy=True).transform
comparison_repairs=[]
def geoms(path,key):
 result={}
 for f in json.loads(path.read_text(encoding='utf-8'))['features']:
  g=transform(project,make_valid(shape(f['geometry'])))
  if not g.is_valid:
   comparison_repairs.append({'source':path.name,'fua_code':f['properties'][key],'action':'make_valid after EPSG3035 projection for metrics only; source output unchanged'})
   g=make_valid(g)
  result[f['properties'][key]]=g
 return result
new=geoms(OUT/'10_德国FUA_2024口径边界.geojson','fua_code')
old={}  # GADM source/derived geometry stays local per repository policy
baseline_iou={r['fua_code']:float(r['v1_iou']) for r in read(RAW/'v1_spatial_summary.csv') if r['v1_iou']}
ref=geoms(RAW/'germany_fua_reference_2024.geojson','requested_oecd_code')
refprops={f['properties']['requested_oecd_code']:f['properties'] for f in json.loads((RAW/'germany_fua_reference_2024.geojson').read_text(encoding='utf-8'))['features']}
write('11_空间比较用几何修复.csv',comparison_repairs,['source','fua_code','action'])
comparison=[]
for f in fc['features']:
 p=f['properties'];code=p['fua_code'];a=new[code];b=ref.get(code)
 row={'fua_code':code,'fua_name':p['fua_name'],'v1_members_matched':p['v1_matched_members'],'v2_exact_code_members':p['members_matched'],'members_total':p['members_total'],'v2_members_accounted_2024':p['members_accounted_2024'],'reference_available':b is not None,'v2_area_km2':a.area/1e6,'reference_area_km2':b.area/1e6 if b is not None else None,'v1_iou':None,'v2_iou':None,'v2_symmetric_difference_km2':None,'v2_outside_reference_km2':None,'reference_outside_v2_km2':None,'flag':'no_reference','review_status':'pending'}
 row['reference_name']=refprops.get(code,{}).get('URAU_NAME','')
 row['same_code_does_not_prove_same_definition']=True
 if b is not None:
  iou=a.intersection(b).area/a.union(b).area
  row.update(v2_iou=iou,v2_symmetric_difference_km2=a.symmetric_difference(b).area/1e6,v2_outside_reference_km2=a.difference(b).area/1e6,reference_outside_v2_km2=b.difference(a).area/1e6,flag='needs_definition_review' if iou<0.98 else 'high_spatial_agreement_pending_review')
  row['v1_iou']=baseline_iou.get(code)
 row['v1_iou_source']='frozen local v1 comparison; no GADM geometry redistributed'
 comparison.append(row)
write('11_与GISCO官方FUA空间比较.csv',comparison)
write('12_需复核的FUA.csv',[r for r in comparison if r['flag']!='high_spatial_agreement_pending_review'],list(comparison[0]))
# Plain GeoPackage export, WGS84 multipolygons; preserve all source/status attributes in JSON.
gpkg=OUT/'10_德国FUA_2024口径边界.gpkg'
con=sqlite3.connect(gpkg)
con.executescript('PRAGMA application_id=1196444487; PRAGMA user_version=10300; DROP TABLE IF EXISTS fua_boundaries; DROP TABLE IF EXISTS gpkg_contents; DROP TABLE IF EXISTS gpkg_geometry_columns; DROP TABLE IF EXISTS gpkg_spatial_ref_sys; CREATE TABLE gpkg_spatial_ref_sys(srs_name TEXT NOT NULL,srs_id INTEGER NOT NULL PRIMARY KEY,organization TEXT NOT NULL,organization_coordsys_id INTEGER NOT NULL,definition TEXT NOT NULL,description TEXT); CREATE TABLE gpkg_contents(table_name TEXT NOT NULL PRIMARY KEY,data_type TEXT NOT NULL,identifier TEXT UNIQUE,description TEXT DEFAULT "",last_change DATETIME NOT NULL,min_x DOUBLE,min_y DOUBLE,max_x DOUBLE,max_y DOUBLE,srs_id INTEGER); CREATE TABLE gpkg_geometry_columns(table_name TEXT NOT NULL,column_name TEXT NOT NULL,geometry_type_name TEXT NOT NULL,srs_id INTEGER NOT NULL,z TINYINT NOT NULL,m TINYINT NOT NULL,PRIMARY KEY(table_name,column_name)); CREATE TABLE fua_boundaries(fid INTEGER PRIMARY KEY AUTOINCREMENT,geom MULTIPOLYGON,fua_code TEXT UNIQUE,fua_name TEXT,members_total INTEGER,members_exact_code INTEGER,coverage_status TEXT,review_status TEXT,attributes_json TEXT);')
con.executemany('INSERT INTO gpkg_spatial_ref_sys VALUES(?,?,?,?,?,?)',[('Undefined Cartesian',-1,'NONE',-1,'undefined',''),('Undefined geographic',0,'NONE',0,'undefined',''),('WGS 84',4326,'EPSG',4326,CRS.from_epsg(4326).to_wkt(version='WKT1_GDAL'),'')])
extent=union_all([shape(f['geometry']) for f in fc['features']]).bounds
con.execute('INSERT INTO gpkg_contents VALUES(?,?,?,?,?,?,?,?,?,?)',('fua_boundaries','features','Germany OECD FUA 2024 geometry','OECD member definitions on GISCO 2024 LAU geometry; pending review',datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z'),*extent,4326))
con.execute('INSERT INTO gpkg_geometry_columns VALUES(?,?,?,?,?,?)',('fua_boundaries','geom','MULTIPOLYGON',4326,0,0))
for f in fc['features']:
 p=f['properties'];g=shape(f['geometry']);g=MultiPolygon([g]) if g.geom_type=='Polygon' else g
 assert g.geom_type=='MultiPolygon' and g.is_valid
 blob=b'GP'+bytes([0,1])+struct.pack('<i',4326)+to_wkb(g,byte_order=1)
 con.execute('INSERT INTO fua_boundaries(geom,fua_code,fua_name,members_total,members_exact_code,coverage_status,review_status,attributes_json) VALUES(?,?,?,?,?,?,?,?)',(blob,p['fua_code'],p['fua_name'],p['members_total'],p['members_matched'],p['coverage_status_2024'],'pending',json.dumps(p,ensure_ascii=False)))
con.commit();con.close()
stats=json.loads((OUT/'quality_summary.json').read_text())
valid=[r for r in comparison if r['reference_available']]
stats.update(members_accounted_after_documented_mergers=sum(bool(r['geometry_ags']) for r in rows),merger_predecessors=len(mergers),fuas_accounted_on_2024_geometry=98,reference_fu_as=len(ref),reference_comparison='completed; GISCO 2024 100K vs LAU 2024 01M',iou_threshold_diagnostic_only=0.98,high_agreement_fuas=sum(r['flag']=='high_spatial_agreement_pending_review' for r in comparison),needs_definition_review=sum(r['flag']=='needs_definition_review' for r in comparison),median_v2_iou=sorted(r['v2_iou'] for r in valid)[len(valid)//2] if valid else None)
(OUT/'quality_summary.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(stats,ensure_ascii=False,indent=2))
print('Lowest agreement among available references',[(r['fua_code'],r['fua_name'],round(r['v2_iou'],4)) for r in sorted(valid,key=lambda r:r['v2_iou'])[:12]])
