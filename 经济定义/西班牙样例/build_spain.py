"""OECD Spanish member definitions joined by five-digit code to GISCO LAU 2024."""
from pathlib import Path
import csv,json,collections,zipfile,io,re,unicodedata,sqlite3,struct
from datetime import datetime,timezone
import shapefile
from shapely.geometry import shape,mapping,MultiPolygon
from shapely import make_valid,union_all,to_wkb
from shapely.ops import transform
from pyproj import Transformer,CRS
ROOT=Path(__file__).resolve().parent;RAW=ROOT/'raw';OUT=ROOT/'outputs';OUT.mkdir(exist_ok=True)
def read(p):return list(csv.DictReader(p.open(encoding='utf-8-sig',newline='')))
def write(name,rr,fields=None):
 with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields or list(rr[0]));w.writeheader();w.writerows(rr)
def norm(s):return re.sub(r'[^a-z0-9]','', ''.join(c for c in unicodedata.normalize('NFKD',s.casefold()) if not unicodedata.combining(c)))
project=Transformer.from_crs(4326,6933,always_xy=True).transform
repairs=[]
def polygonal(g):
 if g.geom_type in ('Polygon','MultiPolygon'):return g
 return union_all([polygonal(p) for p in g.geoms if p.geom_type in ('Polygon','MultiPolygon','GeometryCollection')])
def valid(g,source,identifier):
 if not g.is_valid:
  repairs.append({'source':source,'identifier':identifier,'action':'make_valid and retain polygonal parts','review_status':'pending'});g=polygonal(make_valid(g))
 assert g.is_valid and not g.is_empty and g.geom_type in ('Polygon','MultiPolygon')
 return g
members=[r for r in read(RAW/'fua_cities_sau_mapping.csv') if r['iso3']=='ESP']
assert members and len({(r['fuacode'],r['pk']) for r in members})==len(members)
with zipfile.ZipFile(RAW/'LAU_RG_01M_2024_4326.shp.zip') as z:
 base=next(n[:-4] for n in z.namelist() if n.endswith('.shp'))
 rd=shapefile.Reader(shp=io.BytesIO(z.read(base+'.shp')),shx=io.BytesIO(z.read(base+'.shx')),dbf=io.BytesIO(z.read(base+'.dbf')),encoding='utf-8')
 laus={}
 for i,r in enumerate(rd.iterRecords()):
  p=r.as_dict()
  if p['CNTR_CODE']!='ES':continue
  assert re.fullmatch(r'ES_\d{5}',p['GISCO_ID']),p
  code=p['GISCO_ID'][3:];assert code not in laus
  laus[code]={'properties':p,'geometry':valid(shape(rd.shape(i).__geo_interface__),'LAU_WGS84',code)}
evidence='https://educativo.ign.es/atlas-didactico/organizacion-territorial-bach/estructuracin_interna.html'
rows=[]
for m in members:
 assert re.fullmatch(r'ESP\d{5}',m['pk'])
 code=m['pk'][3:];f=laus.get(code);p=f['properties'] if f else {}
 rows.append({**m,'member_ine5':code,'province_code':code[:2],'gisco_id':p.get('GISCO_ID',''),'official_name':p.get('LAU_NAME',''),'match_status':'exact_code' if f else 'unresolved_code','name_agrees':norm(m['name_lat'])==norm(p.get('LAU_NAME','')) if f else None,'geometry_source':'Eurostat GISCO LAU 2024 01M' if f else '', 'geometry_year':2024 if f else None,'exception_reason':'special non-municipal unit; no same-code feature in LAU 2024' if not f and code in ('54003','54005') else 'no same-code feature' if not f else '', 'evidence_url':evidence if not f and code in ('54003','54005') else '', 'review_status':'pending'})
write('01_OECD西班牙FUA成员表.csv',members)
write('02_成员编码匹配.csv',rows)
write('03_未匹配与特殊单元.csv',[r for r in rows if r['match_status']!='exact_code'],list(rows[0]))
write('04_同码名称差异.csv',[r for r in rows if r['match_status']=='exact_code' and not r['name_agrees']],list(rows[0]))
write('05_市镇代码与几何对应.csv',[{'member_ine5':r['member_ine5'],'gisco_id':r['gisco_id'],'fua_code':r['fuacode'],'match_status':r['match_status'],'review_status':'pending'} for r in rows])
claims=collections.defaultdict(set)
for r in rows:claims[r['member_ine5']].add(r['fuacode'])
write('05_跨FUA重复成员.csv',[{'member_ine5':k,'fua_codes':';'.join(sorted(v)),'review_status':'pending'} for k,v in claims.items() if len(v)>1],['member_ine5','fua_codes','review_status'])
groups=collections.defaultdict(list)
for r in rows:groups[r['fuacode']].append(r)
features=[];catalog=[];geoms={}
for code,rr in sorted(groups.items()):
 selected=sorted({r['member_ine5'] for r in rr if r['match_status']=='exact_code'})
 parts=[laus[k]['geometry'] for k in selected]
 g=valid(union_all(parts),'FUA_UNION',code) if parts else None
 total=len(rr);n=sum(r['match_status']=='exact_code' for r in rr);missing=total-n
 area=transform(project,g).area/1e6 if g is not None else None
 sum_area=sum(transform(project,p).area/1e6 for p in parts) if parts else None
 assert area is None or area<=sum_area+max(0.01,sum_area*1e-7)
 p={'fua_code':code,'fua_name':rr[0]['fuaname_en'],'definition_source':'OECD member mapping snapshot retrieved 2026-10-14','definition_vintage':'not confirmed','geometry_source':'Eurostat GISCO LAU 2024 01M','geometry_year':2024,'members_total':total,'members_matched':n,'members_unresolved':missing,'member_match_rate':n/total,'distinct_geometry_units':len(selected),'coverage_status':'complete_by_code' if not missing else 'partial' if n else 'no_geometry','geometry_valid':g is not None and g.is_valid,'area_km2_epsg6933':area,'sum_member_area_km2':sum_area,'area_is_partial':bool(missing),'review_status':'pending'}
 catalog.append(p)
 if g is not None:features.append({'type':'Feature','properties':p,'geometry':mapping(g)});geoms[code]=g
write('06_西班牙FUA覆盖汇总.csv',catalog)
(OUT/'07_西班牙FUA候选边界.geojson').write_text(json.dumps({'type':'FeatureCollection','features':features},ensure_ascii=False,separators=(',',':')),encoding='utf-8')
reference_manifest=json.loads((ROOT/'reference_manifest.json').read_text(encoding='utf-8'));refs={};refprops={}
for r in reference_manifest:
 if r['status']!='downloaded':continue
 fc=json.loads((RAW/'fua_reference_units'/r['file']).read_text(encoding='utf-8'));ff=fc['features'] if fc['type']=='FeatureCollection' else [fc]
 assert ff and all(f['properties'].get('URAU_CODE')==r['code'] for f in ff)
 refs[r['code']]=valid(union_all([valid(shape(f['geometry']),'GISCO_FUA',r['code']) for f in ff]),'GISCO_FUA_UNION',r['code']);refprops[r['code']]=ff[0]['properties']
comparison=[]
for p in catalog:
 code=p['fua_code'];a=geoms.get(code);b=refs.get(code)
 row={'fua_code':code,'oecd_fua_name':p['fua_name'],'reference_name':refprops.get(code,{}).get('URAU_NAME',''),'members_total':p['members_total'],'members_matched':p['members_matched'],'coverage_status':p['coverage_status'],'reference_available':b is not None,'union_area_km2':p['area_km2_epsg6933'],'reference_area_km2':None,'iou':None,'union_outside_reference_km2':None,'reference_outside_union_km2':None,'symmetric_difference_km2':None,'flag':'no_same_code_reference','review_status':'pending'}
 if a is not None and b is not None:
  ap=valid(transform(project,a),'PROJECTED_UNION',code);bp=valid(transform(project,b),'PROJECTED_REFERENCE',code)
  iou=ap.intersection(bp).area/ap.union(bp).area
  row.update(reference_area_km2=bp.area/1e6,iou=iou,union_outside_reference_km2=ap.difference(bp).area/1e6,reference_outside_union_km2=bp.difference(ap).area/1e6,symmetric_difference_km2=ap.symmetric_difference(bp).area/1e6,flag='high_spatial_agreement_pending_review' if iou>=0.98 else 'needs_definition_review')
  if p['members_unresolved']:row['flag']='partial_membership_even_if_spatially_similar'
 comparison.append(row)
write('08_与GISCO官方FUA空间比较.csv',comparison)
write('09_需复核的FUA.csv',[r for r in comparison if r['flag']!='high_spatial_agreement_pending_review'],list(comparison[0]))
write('10_几何修复记录.csv',repairs,['source','identifier','action','review_status'])
diagnosis=[]
for r in rows:
 b=refs.get(r['fuacode']);f=laus.get(r['member_ine5']);fraction=None
 if f and b is not None:
  a=valid(transform(project,f['geometry']),'PROJECTED_MEMBER',r['member_ine5']);bp=valid(transform(project,b),'PROJECTED_REFERENCE_MEMBER_CHECK',r['fuacode']);fraction=a.intersection(bp).area/a.area
 diagnosis.append({'fua_code':r['fuacode'],'member_ine5':r['member_ine5'],'member_name':r['name_lat'],'fraction_inside_same_code_reference':fraction,'flag':'unmatched_member' if not f else 'no_reference' if fraction is None else 'mostly_outside_reference' if fraction<0.5 else 'boundary_crosses_reference' if fraction<0.98 else 'mostly_inside_reference','review_status':'pending'})
write('11_市镇层面参考边界差异.csv',diagnosis)
# GeoPackage WGS84 multipolygons. Complete source/status properties remain in JSON.
con=sqlite3.connect(OUT/'07_西班牙FUA候选边界.gpkg')
con.executescript('PRAGMA application_id=1196444487; PRAGMA user_version=10300; DROP TABLE IF EXISTS fua_boundaries; DROP TABLE IF EXISTS gpkg_contents; DROP TABLE IF EXISTS gpkg_geometry_columns; DROP TABLE IF EXISTS gpkg_spatial_ref_sys; CREATE TABLE gpkg_spatial_ref_sys(srs_name TEXT NOT NULL,srs_id INTEGER NOT NULL PRIMARY KEY,organization TEXT NOT NULL,organization_coordsys_id INTEGER NOT NULL,definition TEXT NOT NULL,description TEXT); CREATE TABLE gpkg_contents(table_name TEXT NOT NULL PRIMARY KEY,data_type TEXT NOT NULL,identifier TEXT UNIQUE,description TEXT DEFAULT "",last_change DATETIME NOT NULL,min_x DOUBLE,min_y DOUBLE,max_x DOUBLE,max_y DOUBLE,srs_id INTEGER); CREATE TABLE gpkg_geometry_columns(table_name TEXT NOT NULL,column_name TEXT NOT NULL,geometry_type_name TEXT NOT NULL,srs_id INTEGER NOT NULL,z TINYINT NOT NULL,m TINYINT NOT NULL,PRIMARY KEY(table_name,column_name)); CREATE TABLE fua_boundaries(fid INTEGER PRIMARY KEY AUTOINCREMENT,geom MULTIPOLYGON,fua_code TEXT UNIQUE,fua_name TEXT,members_total INTEGER,members_matched INTEGER,members_unresolved INTEGER,coverage_status TEXT,review_status TEXT,area_km2 REAL,attributes_json TEXT);')
con.executemany('INSERT INTO gpkg_spatial_ref_sys VALUES(?,?,?,?,?,?)',[('Undefined Cartesian',-1,'NONE',-1,'undefined',''),('Undefined geographic',0,'NONE',0,'undefined',''),('WGS 84',4326,'EPSG',4326,CRS.from_epsg(4326).to_wkt(version='WKT1_GDAL'),'')])
extent=union_all(list(geoms.values())).bounds
con.execute('INSERT INTO gpkg_contents VALUES(?,?,?,?,?,?,?,?,?,?)',('fua_boundaries','features','Spain OECD FUA pilot','Membership coverage and scientific review status retained',datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z'),*extent,4326))
con.execute('INSERT INTO gpkg_geometry_columns VALUES(?,?,?,?,?,?)',('fua_boundaries','geom','MULTIPOLYGON',4326,0,0))
for p in catalog:
 if p['fua_code'] not in geoms:continue
 g=geoms[p['fua_code']];g=MultiPolygon([g]) if g.geom_type=='Polygon' else g
 blob=b'GP'+bytes([0,1])+struct.pack('<i',4326)+to_wkb(g,byte_order=1)
 con.execute('INSERT INTO fua_boundaries(geom,fua_code,fua_name,members_total,members_matched,members_unresolved,coverage_status,review_status,area_km2,attributes_json) VALUES(?,?,?,?,?,?,?,?,?,?)',(blob,p['fua_code'],p['fua_name'],p['members_total'],p['members_matched'],p['members_unresolved'],p['coverage_status'],'pending',p['area_km2_epsg6933'],json.dumps(p,ensure_ascii=False)))
con.commit();con.close()
valid_iou=sorted(r['iou'] for r in comparison if r['iou'] is not None)
import statistics
stats={'oecd_members':len(rows),'matched_members':sum(r['match_status']=='exact_code' for r in rows),'unresolved_members':sum(r['match_status']!='exact_code' for r in rows),'fuas':len(catalog),'geometries':len(features),'complete_by_code':sum(not p['members_unresolved'] for p in catalog),'partial_fuas':sum(p['coverage_status']=='partial' for p in catalog),'official_spanish_laus':len(laus),'name_differences':sum(r['name_agrees'] is False for r in rows),'official_reference_fuas':len(refs),'missing_reference_fuas':len(catalog)-len(refs),'median_iou':statistics.median(valid_iou) if valid_iou else None,'diagnostic_iou_threshold':0.98,'comparison_flags':dict(collections.Counter(r['flag'] for r in comparison)),'geometry_repairs':len(repairs),'definition_vintage':'not confirmed','geometry_year':2024,'review_status':'pending','area_projection':'EPSG:6933','economic_observations_included':False}
write('10_几何修复记录.csv',repairs,['source','identifier','action','review_status'])
(OUT/'quality_summary.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(stats,ensure_ascii=False,indent=2))
