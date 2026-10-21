"""Scientific overview using only OECD/GISCO definitions and geometry."""
from pathlib import Path
import json,csv
from shapely.geometry import shape
from shapely import union_all,make_valid
from shapely.ops import transform
from pyproj import Transformer
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'outputs'
project=Transformer.from_crs(4326,3035,always_xy=True).transform
def load(p,k):return {f['properties'][k]:transform(project,shape(f['geometry'])) for f in json.loads(p.read_text(encoding='utf-8'))['features']}
new=load(OUT/'10_德国FUA_2024口径边界.geojson','fua_code');ref=load(ROOT/'raw/germany_fua_reference_2024.geojson','requested_oecd_code')
def font(size):
 for name in ['C:/Windows/Fonts/arial.ttf','DejaVuSans.ttf']:
  try:return ImageFont.truetype(name,size)
  except OSError:pass
 return ImageFont.load_default()
im=Image.new('RGB',(1160,1060),'#f5f8fc');d=ImageDraw.Draw(im);ft=font(23);sm=font(17)
d.text((28,20),'Germany FUA pilot: municipality union vs GISCO reference',font=font(29),fill='#173451')
d.text((28,65),'Same code may identify different regions. All results pending scientific review.',font=sm,fill='#435b73')
for ri,(code,name) in enumerate([('DE001F','Berlin'),('DE006F','Ruhrgebiet (reference name: Essen)')]):
 gs=[new[code],ref[code]];a,b,c,e=union_all([make_valid(g) for g in gs]).bounds
 scale=min(480/(c-a),305/(e-b));cx=(a+c)/2;cy=(b+e)/2;y0=140+ri*425
 d.text((28,y0-30),code+' - '+name,font=ft,fill='#173451')
 for ci,g in enumerate(gs):
  x0=20+ci*570;d.rounded_rectangle((x0,y0+8,x0+550,y0+385),radius=10,fill='white',outline='#d5dfea')
  d.text((x0+14,y0+20),'OECD members + GISCO LAU 2024' if ci==0 else 'GISCO FUA 2024 reference',font=ft,fill='#173451')
  def xy(x,y):return (x0+275+(x-cx)*scale,y0+210-(y-cy)*scale)
  for p in list(g.geoms) if g.geom_type=='MultiPolygon' else [g]:
   d.polygon([xy(x,y) for x,y in p.exterior.coords],fill='#c3dcef' if ci==0 else '#f2cc97',outline='#286a9e' if ci==0 else '#af6a1d',width=2)
   for h in p.interiors:d.polygon([xy(x,y) for x,y in h.coords],fill='white')
d.text((28,1000),'EPSG:3035 display. Administrative boundaries: (c) EuroGeographics.',font=sm,fill='#435b73')
d.text((28,1026),'Source: European Commission - Eurostat/GISCO; OECD membership. Different boundary scales.',font=sm,fill='#435b73')
im.save(OUT/'16_官方市镇拼合与FUA参考.png')
print('Saved GISCO-only reference preview')
