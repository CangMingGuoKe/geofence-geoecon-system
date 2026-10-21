"""Fetch pinned official inputs to ignored raw/; reject changed snapshots."""
from pathlib import Path
import concurrent.futures,hashlib,json,ssl,urllib.request
import certifi
ROOT=Path(__file__).resolve().parent;RAW=ROOT/'raw';RAW.mkdir(exist_ok=True)
CTX=ssl.create_default_context(cafile=certifi.where())
sources=json.loads((ROOT/'sources.json').read_text(encoding='utf-8'))
def fetch(s):
 p=(RAW/s['path']).resolve();assert p.is_relative_to(RAW.resolve())
 if p.exists():
  if hashlib.sha256(p.read_bytes()).hexdigest()!=s['sha256']:raise ValueError('Local snapshot changed: '+str(p))
 else:
  with urllib.request.urlopen(s['url'],context=CTX,timeout=180) as r:data=r.read()
  if hashlib.sha256(data).hexdigest()!=s['sha256']:raise ValueError('Official snapshot changed; obtain archived version: '+s['url'])
  p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
 p.with_name(p.name+'.source.json').write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8')
 return s['path']
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:done=list(pool.map(fetch,sources))
manifest=json.loads((RAW/'fua_reference_manifest.json').read_text(encoding='utf-8'));features=[]
for r in manifest:
 if 'error' in r:continue
 data=json.loads((RAW/'fua_reference_units'/r['file']).read_text(encoding='utf-8'))
 for f in data['features'] if data['type']=='FeatureCollection' else [data]:
  f['properties']['requested_oecd_code']=r['code'];features.append(f)
(RAW/'germany_fua_reference_2024.geojson').write_text(json.dumps({'type':'FeatureCollection','features':features},ensure_ascii=False),encoding='utf-8')
assert len(features)==79
print('Verified pinned official inputs:',len(done),'FUA references:',len(features))
