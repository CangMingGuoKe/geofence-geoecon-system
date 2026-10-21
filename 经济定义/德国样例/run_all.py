"""Rebuild using pinned official downloads; original data is cached locally."""
from pathlib import Path
import subprocess,sys
ROOT=Path(__file__).resolve().parent
for name in ['prepare_data.py','audit_v1.py','build_v2.py','harmonize_and_compare.py','member_reference_diagnosis.py','verify_and_preview.py','render_reference_preview.py']:
 print('Running',name,flush=True)
 subprocess.run([sys.executable,'-X','utf8',str(ROOT/name)],check=True,cwd=ROOT)
print('Rebuild and verification completed; scientific review remains pending.')
