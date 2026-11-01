from pathlib import Path
import subprocess,sys
ROOT=Path(__file__).resolve().parent
for name in ['prepare_data.py','build_spain.py','verify_results.py','render_preview.py']:
 print('Running',name,flush=True)
 subprocess.run([sys.executable,'-X','utf8',str(ROOT/name)],check=True,cwd=ROOT)
print('Spanish FUA pilot rebuilt and verified. Scientific review remains pending.')
