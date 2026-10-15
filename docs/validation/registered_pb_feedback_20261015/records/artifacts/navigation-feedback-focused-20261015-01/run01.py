from pathlib import Path
import ast,hashlib,json,subprocess,time
root=Path.cwd();out=root/'artifacts/navigation-feedback-focused-20261015-01'
tests=['tests/test_navigation_feedback_contracts.py','tests/test_decision_navigation_v2.py','tests/test_decision_plugin.py']
paths=['rm_match/platform_v2/navigation_feedback_contracts.py','rm_match/platform_v2/decision_contracts.py','rm_match/deployment/decision_plugin.py','rm_match/integrations/decision_jsonl_peer.py','tests/test_navigation_feedback_contracts.py','tests/test_decision_navigation_v2.py','tests/fixtures/decision_navigation_feedback_v2.py']
before={}
for name in paths:
 raw=(root/name).read_bytes();ast.parse(raw.decode('utf8'));before[name]=hashlib.sha256(raw).hexdigest();target=out/'source01'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
cmd=[str(root/'.venv-sim/Scripts/python.exe'),'-m','pytest',*tests,'-q','--junitxml='+str(out/'junit01.xml')]
(out/'COMMAND01.json').write_text(json.dumps(cmd,indent=2),encoding='utf8');started=time.perf_counter()
with (out/'stdout01.log').open('wb') as stdout,(out/'stderr01.log').open('wb') as stderr:
 child=subprocess.Popen(cmd,cwd=root,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr);code=child.wait(timeout=90)
after={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in paths}
result=dict(exit_code=code,reaped=child.poll() is not None,elapsed=time.perf_counter()-started,before=before,after=after,source_unchanged=before==after,scope='declared estimate/feedback/v2 decision and harmless owned JSONL fixture; no actual ROS/WSL/SIL/SLAM/NN/GUI')
(out/'PROCESS_RESULT01.json').write_text(json.dumps(result,indent=2),encoding='utf8');print((out/'stdout01.log').read_text());print((out/'stderr01.log').read_text());print(json.dumps(result));raise SystemExit(code)
