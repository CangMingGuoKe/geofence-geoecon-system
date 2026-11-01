"""Download official snapshots into ignored raw/ and reject changed content."""
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
  if hashlib.sha256(data).hexdigest()!=s['sha256']:raise ValueError('Source changed; obtain archived snapshot: '+s['url'])
  p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
 p.with_name(p.name+'.source.json').write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8')
 return s['path']
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:done=list(pool.map(fetch,sources))
print('Verified official snapshots:',len(done))
