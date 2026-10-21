from pathlib import Path
import sys,json,csv,hashlib,sqlite3,io,zipfile,re,unicodedata,statistics
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'.runtime'));
import shapefile
from shapely.geometry import shape
from shapely import union_all,from_wkb,make_valid
from shapely.ops import transform
from pyproj import Transformer
from PIL import Image,ImageDraw,ImageFont
RAW=ROOT/'raw';OUT=ROOT/'outputs'
def read(p):return list(csv.DictReader(p.open(encoding='utf-8-sig',newline='')))
checks=[]
for meta in RAW.rglob('*.source.json'):
 p=meta.with_name(meta.name.removesuffix('.source.json'))
 m=json.loads(meta.read_text(encoding='utf-8'))
 assert p.exists() and hashlib.sha256(p.read_bytes()).hexdigest()==m['sha256'],p
checks.append('All downloaded raw snapshots pass SHA256 source metadata checks')
rows=read(OUT/'09_成员追溯与2024边界对应.csv')
assert len(rows)==4323 and len({(r['fuacode'],r['pk']) for r in rows})==4323
assert sum(r['match_status']=='exact_code' for r in rows)==4320
assert sum(r['coverage_method']=='documented_merger_into_existing_member' for r in rows)==3
assert all(re.fullmatch(r'\d{8}',r['geometry_ags']) for r in rows)
assert all(r['review_status']=='pending' for r in rows)
newfc=json.loads((OUT/'10_德国FUA_2024口径边界.geojson').read_text(encoding='utf-8'))['features']
new={f['properties']['fua_code']:shape(f['geometry']) for f in newfc}
assert len(new)==98 and all(g.is_valid and not g.is_empty and g.geom_type in ('Polygon','MultiPolygon') for g in new.values())
checks.append('4320 exact code joins and 3 documented merger predecessors; 98 valid nonempty FUA geometries; all review statuses pending')
with zipfile.ZipFile(RAW/'LAU_RG_01M_2024_4326.shp.zip') as z:
 base=next(n[:-4] for n in z.namelist() if n.endswith('.shp'))
 reader=shapefile.Reader(shp=io.BytesIO(z.read(base+'.shp')),shx=io.BytesIO(z.read(base+'.shx')),dbf=io.BytesIO(z.read(base+'.dbf')),encoding='utf-8')
 selected={r['geometry_ags'] for r in rows if r['fuacode']=='DE001F'}
 berlin=[]
 for i,p in enumerate(reader.iterRecords()):
  a=p.as_dict()
  if a['CNTR_CODE']=='DE' and a['GISCO_ID'].removeprefix('DE_') in selected:berlin.append(shape(reader.shape(i).__geo_interface__))
 assert len(berlin)==118 and union_all(berlin).equals(new['DE001F'])
checks.append('Berlin independently reconstructed from original SHP archive: 118 exact-code municipalities equal exported geometry')
con=sqlite3.connect(OUT/'10_德国FUA_2024口径边界.gpkg')
assert con.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
data=con.execute('SELECT fua_code,geom FROM fua_boundaries').fetchall();assert len(data)==98
for code,blob in data:assert blob[:2]==b'GP' and from_wkb(blob[8:]).equals(new[code])
con.close();checks.append('GeoPackage SQLite integrity and all 98 WKB geometry round trips pass')
comparison=read(OUT/'11_与GISCO官方FUA空间比较.csv')
valid=[r for r in comparison if r['reference_available']=='True']
assert len(valid)==79 and sum(not r['v2_iou'] for r in comparison)==19
assert all(0<=float(r['v2_iou'])<=1 for r in valid)
stats=json.loads((OUT/'quality_summary.json').read_text())
stats['median_v1_iou']=statistics.median(float(r['v1_iou']) for r in valid if r['v1_iou'])
stats['v2_iou_improved_count']=sum(float(r['v2_iou'])>float(r['v1_iou']) for r in valid if r['v1_iou'])
stats['v2_iou_lower_count']=sum(float(r['v2_iou'])<float(r['v1_iou']) for r in valid if r['v1_iou'])
(OUT/'quality_summary.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')
checks.append('79 same-code official references evaluated; 19 absent codes remain null, never zero')
(OUT/'verification.json').write_text(json.dumps({'passed':True,'checks':checks},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'checks':checks,'summary':stats},ensure_ascii=False,indent=2))
