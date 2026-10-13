"""Owned actual Windows driver; preserves raw failure and process exit evidence."""
import json
from pathlib import Path
import subprocess
import sys
import time

root=Path(__file__).resolve().parents[1]
out=root/'artifacts/pb-wsl-navigation-driver-20261014-02'
out.mkdir()
command=[str(root/'.venv-sim/Scripts/python.exe'),str(root/'tools/qa_pb_wsl_navigation_sil.py'),
 '--environment',str(root/'artifacts/pb-humble-ext4-runtime-20261014/ENVIRONMENT_COMPAT_FINAL.json'),
 '--stack-config',str(root/'artifacts/pb-navigation-sil-config-20261014-04.json'),
 '--out',str(root/'artifacts/pb-wsl-navigation-sil-actual-20261014-attempt2'),
 '--seconds','30','--diagnostics','--run']
(out/'COMMAND.json').write_text(json.dumps({'argv':command,'cwd':str(root)},indent=2)+'\n',encoding='utf8')
started=time.perf_counter()
with (out/'stdout.log').open('wb') as stdout,(out/'stderr.log').open('wb') as stderr:
 child=subprocess.Popen(command,cwd=root,stdout=stdout,stderr=stderr,shell=False,creationflags=subprocess.CREATE_NO_WINDOW)
 (out/'PID.json').write_text(json.dumps({'pid':child.pid})+'\n',encoding='utf8')
 code=child.wait()
record={'exit_code':code,'wall_seconds':time.perf_counter()-started,'owned_driver_reaped':child.poll() is not None}
(out/'PROCESS_RESULT.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf8')
print(json.dumps(record),flush=True)
raise SystemExit(code)
