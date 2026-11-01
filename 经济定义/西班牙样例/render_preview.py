"""Scientific comparison with identical extents within each row; no geometry edits."""
from pathlib import Path
import csv,json
from shapely.geometry import shape
from shapely import union_all
from shapely.ops import transform
from pyproj import Transformer
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'outputs';RAW=ROOT/'raw'
projection=Transformer.from_crs(4326,3035,always_xy=True).transform
fc=json.loads((OUT/'07_西班牙FUA候选边界.geojson').read_text(encoding='utf-8'))['features'];new={f['properties']['fua_code']:transform(projection,shape(f['geometry'])) for f in fc}
manifest={r['code']:r for r in json.loads((ROOT/'reference_manifest.json').read_text(encoding='utf-8'))}
metrics={r['fua_code']:r for r in csv.DictReader((OUT/'08_与GISCO官方FUA空间比较.csv').open(encoding='utf-8-sig'))}
def font(size):
 for name in ['C:/Windows/Fonts/arial.ttf','DejaVuSans.ttf']:
  try:return ImageFont.truetype(name,size)
  except OSError:pass
 return ImageFont.load_default()
im=Image.new('RGB',(1160,1110),'#f5f8fc');d=ImageDraw.Draw(im);ft=font(23);sm=font(17)
d.text((28,20),'Spain OECD FUA pilot: code coverage and boundary differences',font=font(28),fill='#173451')
d.text((28,65),'1262 / 1264 member codes matched. 80 complete-by-code FUAs; Melilla remains partial.',font=sm,fill='#435b73')
for ri,(code,label) in enumerate([('ES001F','Madrid: 166 / 166 members matched'),('ES002F','Barcelona: 135 / 135 members matched')]):
 data=json.loads((RAW/'fua_reference_units'/manifest[code]['file']).read_text(encoding='utf-8'));ff=data['features'] if data['type']=='FeatureCollection' else [data]
 gs=[new[code],transform(projection,union_all([shape(f['geometry']) for f in ff]))]
 a,b,c,e=union_all(gs).bounds;scale=min(480/(c-a),280/(e-b));cx=(a+c)/2;cy=(b+e)/2;y0=145+ri*425
 d.text((28,y0-30),label+'; IoU '+format(float(metrics[code]['iou']),'.2%'),font=ft,fill='#173451')
 for ci,g in enumerate(gs):
  x0=20+ci*570;d.rounded_rectangle((x0,y0+8,x0+550,y0+385),radius=10,fill='white',outline='#d5dfea')
  d.text((x0+14,y0+20),'OECD members + GISCO LAU 2024' if ci==0 else 'GISCO FUA 2024 same-code reference',font=font(21),fill='#173451')
  def xy(x,y):return (x0+275+(x-cx)*scale,y0+215-(y-cy)*scale)
  for p in list(g.geoms) if g.geom_type=='MultiPolygon' else [g]:
   d.polygon([xy(x,y) for x,y in p.exterior.coords],fill='#c3dcef' if ci==0 else '#f2cc97',outline='#286a9e' if ci==0 else '#af6a1d',width=2)
   for h in p.interiors:d.polygon([xy(x,y) for x,y in h.coords],fill='white')
d.text((28,1010),'Same code does not prove the same definition. Scientific review pending. EPSG:3035 display.',font=sm,fill='#435b73')
d.text((28,1038),'Administrative boundaries: (c) EuroGeographics. Source: European Commission - Eurostat/GISCO.',font=sm,fill='#435b73')
d.text((28,1066),'OECD membership snapshot: 2026-10-14. Areas and IoU computed in EPSG:6933.',font=sm,fill='#435b73')
im.save(OUT/'12_马德里与巴塞罗那边界对照.png')
print('Saved Spain boundary comparison preview')
