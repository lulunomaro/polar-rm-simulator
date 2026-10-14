from pathlib import Path
import hashlib
import json
import subprocess
import time

out=Path(__file__).resolve().parent
root=out.parents[1]
files=['rm_match/deployment/navigation_plugin.py',
       'rm_match/integrations/navigation_jsonl_peer.py',
       'tests/test_navigation_plugin.py','examples/navigation_plugins.json']
rows=[]
for relative in files:
    raw=(root/relative).read_bytes()
    target=out/'source'/relative
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(raw)
    rows.append(dict(path=relative,size=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
(out/'SOURCE_MANIFEST.json').write_text(json.dumps(dict(files=rows),indent=2)+'\n',encoding='utf8')
command=[str(root/'.venv-sim/Scripts/python.exe'),'-m','pytest',
         'tests/test_navigation_plugin.py','-q','--junitxml='+str(out/'pytest.xml')]
(out/'COMMAND.json').write_text(json.dumps(dict(argv=command,cwd=str(root),
    scope='pure protocol and actual harmless owned local child; no ROS/WSL/NN/GL'),indent=2)+'\n',encoding='utf8')
started=time.perf_counter()
with (out/'stdout.log').open('wb') as stdout,(out/'stderr.log').open('wb') as stderr:
    child=subprocess.Popen(command,cwd=root,stdout=stdout,stderr=stderr)
    code=child.wait(timeout=20.)
unchanged=all(hashlib.sha256((root/r['path']).read_bytes()).hexdigest()==r['sha256'] for r in rows)
(out/'PROCESS_RESULT.json').write_text(json.dumps(dict(exit_code=code,reaped=child.poll() is not None,
    elapsed_seconds=time.perf_counter()-started,source_unchanged=unchanged),indent=2)+'\n',encoding='utf8')
raise SystemExit(code if unchanged else 3)
