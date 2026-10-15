import ast,hashlib,json,pathlib,subprocess,time
root=pathlib.Path.cwd();out=root/'artifacts/navigation-goal-consumption-focused-20261015-01'
tests=['tests/test_navigation_goal_consumption.py','tests/test_pb_navigation_sil_audit.py','tests/test_pb_goal_navigation_bridge.py']
paths=['tools/audit_navigation_goals.py','tests/test_navigation_goal_consumption.py','tools/qa_pb_navigation_sil.py','rm_match/platform_v2/contracts.py','rm_match/platform_v2/decision_contracts.py','rm_match/integrations/navigation_goal_lifecycle.py']
before={}
for name in paths:
 raw=(root/name).read_bytes();before[name]=hashlib.sha256(raw).hexdigest();target=out/'source01'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
for name in paths[:2]:ast.parse((root/name).read_text(encoding='utf-8'))
cmd=[str(root/'.venv-sim/Scripts/python.exe'),'-m','pytest',*tests,'-q','--junitxml='+str(out/'junit01.xml')]
(out/'COMMAND01.json').write_text(json.dumps(cmd,indent=2),encoding='utf-8');start=time.perf_counter()
with (out/'stdout01.log').open('wb') as stdout,(out/'stderr01.log').open('wb') as stderr:
 child=subprocess.Popen(cmd,cwd=root,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr);rc=child.wait(timeout=60)
after={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in paths}
result=dict(exit_code=rc,reaped=child.poll() is not None,elapsed=time.perf_counter()-start,before=before,after=after,source_unchanged=before==after,scope='synthetic source/action/physical receipt fixture audit plus legacy units; no ROS/WSL/NN/physics')
(out/'PROCESS_RESULT01.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print((out/'stdout01.log').read_text());print((out/'stderr01.log').read_text());print(json.dumps(result));raise SystemExit(rc)
