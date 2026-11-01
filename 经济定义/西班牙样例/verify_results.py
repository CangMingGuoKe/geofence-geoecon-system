"""Verify published products against immutable inputs and independent sample unions."""
from pathlib import Path
import csv,json,hashlib,zipfile,io,sqlite3,struct,math
import shapefile
from shapely.geometry import shape
from shapely import union_all,from_wkb
from shapely.ops import transform
from pyproj import Transformer
ROOT=Path(__file__).resolve().parent;RAW=ROOT/'raw';OUT=ROOT/'outputs'
def read(p):return list(csv.DictReader(p.open(encoding='utf-8-sig',newline='')))
checks=[]
sources=json.loads((ROOT/'sources.json').read_text(encoding='utf-8'))
for s in sources:assert hashlib.sha256((RAW/s['path']).read_bytes()).hexdigest()==s['sha256'],s['path']
checks.append('All official source snapshots match pinned SHA256 hashes')
original=[r for r in read(RAW/'fua_cities_sau_mapping.csv') if r['iso3']=='ESP'];rows=read(OUT/'02_成员编码匹配.csv')
assert len(rows)==len(original)==1264 and len({(r['fuacode'],r['pk']) for r in rows})==1264
original_idx={(r['fuacode'],r['pk']):r for r in original}
for r in rows:
 assert all(r[k]==v for k,v in original_idx[(r['fuacode'],r['pk'])].items())
 assert len(r['member_ine5'])==5 and r['pk']=='ESP'+r['member_ine5']
 assert r['review_status']=='pending'
 assert r['match_status']!='exact_code' or r['gisco_id']=='ES_'+r['member_ine5']
assert sum(r['match_status']=='exact_code' for r in rows)==1262
missing=read(OUT/'03_未匹配与特殊单元.csv');assert {r['member_ine5'] for r in missing}=={'54003','54005'} and all(r['fuacode']=='ES045F' for r in missing)
checks.append('1264 original member records preserved; 1262 exact five-digit joins; two missing special units stay unresolved')
fc=json.loads((OUT/'07_西班牙FUA候选边界.geojson').read_text(encoding='utf-8'))['features'];geoms={f['properties']['fua_code']:shape(f['geometry']) for f in fc}
assert len(geoms)==len(fc)==81 and all(g.is_valid and not g.is_empty for g in geoms.values())
catalog=read(OUT/'06_西班牙FUA覆盖汇总.csv');assert sum(r['coverage_status']=='complete_by_code' for r in catalog)==80
melilla=next(r for r in catalog if r['fua_code']=='ES045F');assert melilla['coverage_status']=='partial' and melilla['members_unresolved']=='2' and melilla['area_is_partial']=='True'
checks.append('81 valid nonempty FUA geometries; 80 complete-by-code; Melilla explicitly partial with area flag')
sample_counts={'ES001F':166,'ES002F':135,'ES024F':13,'ES045F':1}
selected={c:{r['member_ine5'] for r in rows if r['fuacode']==c and r['match_status']=='exact_code'} for c in sample_counts};parts={c:[] for c in sample_counts}
with zipfile.ZipFile(RAW/'LAU_RG_01M_2024_4326.shp.zip') as z:
 base=next(n[:-4] for n in z.namelist() if n.endswith('.shp'))
 rd=shapefile.Reader(shp=io.BytesIO(z.read(base+'.shp')),shx=io.BytesIO(z.read(base+'.shx')),dbf=io.BytesIO(z.read(base+'.dbf')),encoding='utf-8')
 for i,r in enumerate(rd.iterRecords()):
  if r['CNTR_CODE']!='ES':continue
  for c,codes in selected.items():
   if r['GISCO_ID'][3:] in codes:parts[c].append(shape(rd.shape(i).__geo_interface__))
for c,n in sample_counts.items():assert len(parts[c])==n and union_all(parts[c]).equals(geoms[c]),c
checks.append('Madrid, Barcelona, Santa Cruz de Tenerife and partial Melilla independently reconstructed from original SHP and equal exported boundaries')
con=sqlite3.connect(OUT/'07_西班牙FUA候选边界.gpkg');assert con.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
gg=con.execute('SELECT fua_code,geom,members_unresolved,coverage_status FROM fua_boundaries').fetchall();assert len(gg)==81
for c,b,n,status in gg:
 assert b[:2]==b'GP' and struct.unpack('<i',b[4:8])[0]==4326 and from_wkb(b[8:]).equals(geoms[c])
 assert (n==2 and status=='partial') if c=='ES045F' else (n==0 and status=='complete_by_code')
con.close();checks.append('GeoPackage integrity, EPSG4326 header, all 81 geometry round trips and partial-coverage attributes pass')
comparison=read(OUT/'08_与GISCO官方FUA空间比较.csv');assert len(comparison)==81
available=[r for r in comparison if r['reference_available']=='True'];absent=[r for r in comparison if r['reference_available']=='False']
assert len(available)==66 and len(absent)==15 and all(r['iou']=='' and r['reference_area_km2']=='' for r in absent)
assert all(0<=float(r['iou'])<=1 for r in available)
manifest={r['code']:r for r in json.loads((ROOT/'reference_manifest.json').read_text(encoding='utf-8'))}
projection=Transformer.from_crs(4326,6933,always_xy=True).transform
for code in ('ES001F','ES002F'):
 data=json.loads((RAW/'fua_reference_units'/manifest[code]['file']).read_text(encoding='utf-8'));ff=data['features'] if data['type']=='FeatureCollection' else [data]
 b=transform(projection,union_all([shape(f['geometry']) for f in ff]));a=transform(projection,geoms[code])
 metric=a.intersection(b).area/a.union(b).area;reported=float(next(r for r in comparison if r['fua_code']==code)['iou']);assert math.isclose(metric,reported,abs_tol=1e-10)
checks.append('66 reference comparisons, 15 explicit null references, and independently recalculated Madrid/Barcelona IoUs pass')
(OUT/'verification.json').write_text(json.dumps({'passed':True,'checks':checks,'scientific_geography_review':'pending; code completeness is not equivalence to OECD economic indicator geography'},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'passed':True,'checks':checks},ensure_ascii=False,indent=2))
