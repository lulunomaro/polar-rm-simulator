from pathlib import Path
import ast,hashlib,json,subprocess,time
root=Path.cwd();out=root/'artifacts/goal-navigation-contracts-focused-20261015-01'
paths=['rm_match/platform_v2/goal_navigation_contracts.py','tests/test_goal_navigation_contracts.py','rm_match/platform_v2/contracts.py','rm_match/platform_v2/navigation_contracts.py','rm_match/platform_v2/decision_contracts.py']
before={}
for name in paths:
 raw=(root/name).read_bytes();before[name]=hashlib.sha256(raw).hexdigest();p=out/'source03'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
for name in paths[:2]:ast.parse((root/name).read_text())
cmd=[str(root/'.venv-sim/Scripts/python.exe'),'-m','pytest','tests/test_goal_navigation_contracts.py','-q','--junitxml='+str(out/'junit03.xml')]
(out/'COMMAND03.json').write_text(json.dumps(cmd,indent=2),encoding='utf8');started=time.perf_counter()
with (out/'stdout03.log').open('wb') as stdout,(out/'stderr03.log').open('wb') as stderr:
 child=subprocess.Popen(cmd,cwd=root,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr);code=child.wait(timeout=60)
after={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in paths}
result=dict(exit_code=code,reaped=child.poll() is not None,elapsed=time.perf_counter()-started,before=before,after=after,source_unchanged=before==after,scope='synthetic stateless and per-binding history protocol tests, no ROS/WSL/physics/NN/GUI')
(out/'PROCESS_RESULT03.json').write_text(json.dumps(result,indent=2),encoding='utf8');print((out/'stdout03.log').read_text());print((out/'stderr03.log').read_text());print(json.dumps(result));raise SystemExit(code)

