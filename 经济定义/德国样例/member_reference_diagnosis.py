"""Explain boundary discrepancies at municipality level, without changing OECD membership."""
from pathlib import Path
import sys,json,csv,re,unicodedata
ROOT=Path(__file__).resolve().parent;
from shapely.geometry import shape
from shapely import make_valid
from shapely.ops import transform
from pyproj import Transformer
RAW=ROOT/'raw';OUT=ROOT/'outputs'
rows=list(csv.DictReader((OUT/'09_成员追溯与2024边界对应.csv').open(encoding='utf-8-sig')))
project=Transformer.from_crs(4326,3035,always_xy=True).transform
ref={f['properties']['requested_oecd_code']:make_valid(transform(project,shape(f['geometry']))) for f in json.loads((RAW/'germany_fua_reference_2024.geojson').read_text(encoding='utf-8'))['features']}
members={r['geometry_ags'] for r in rows}
laus={f['properties']['GISCO_ID'][3:]:make_valid(transform(project,shape(f['geometry']))) for f in json.loads((RAW/'germany_lau_2024.geojson').read_text(encoding='utf-8'))['features'] if f['properties']['GISCO_ID'][3:] in members}
diagnosis=[]
for r in rows:
 b=ref.get(r['fuacode']);g=laus[r['geometry_ags']]
 fraction=g.intersection(b).area/g.area if b is not None else None
 diagnosis.append({'fua_code':r['fuacode'],'oecd_fua_name':r['fuaname_en'],'member_ags':r['member_ags'],'member_name':r['name_lat'],'geometry_ags':r['geometry_ags'],'fraction_inside_same_code_reference':fraction,'flag':'no_reference' if fraction is None else 'mostly_outside_reference' if fraction<0.5 else 'boundary_crosses_reference' if fraction<0.98 else 'mostly_inside_reference','diagnostic_only':True,'review_status':'pending'})
with (OUT/'14_市镇层面参考边界差异.csv').open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(diagnosis[0]));w.writeheader();w.writerows(diagnosis)
def norm(s):return re.sub('[^a-z0-9]','', ''.join(c for c in unicodedata.normalize('NFKD',s.casefold()) if not unicodedata.combining(c)))
names=[]
for r in rows:
 if r['match_status']!='exact_code' or r['name_agrees']=='True':continue
 a,b=r['name_lat'],r['official_name']
 simple=norm(a)==norm(b.split(',')[0]) or norm(a.split(',')[0])==norm(b.split(',')[0])
 names.append({'member_ags':r['member_ags'],'oecd_name':a,'official_name':b,'fua_code':r['fuacode'],'difference_type':'comma_suffix_or_qualifier_only' if simple else 'other_name_difference','classification_is_diagnostic':True,'review_status':'pending'})
with (OUT/'15_同码名称差异分类.csv').open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(names[0]));w.writeheader();w.writerows(names)
print('Mostly outside reference',sum(r['flag']=='mostly_outside_reference' for r in diagnosis))
print('Name differences',len(names),'comma suffix only',sum(r['difference_type']=='comma_suffix_or_qualifier_only' for r in names))
