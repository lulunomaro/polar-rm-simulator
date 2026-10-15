import hashlib,json,pathlib,subprocess,time
root=pathlib.Path.cwd(); out=root/'artifacts/navigation-goal-lifecycle-focused-20261015-01'
tests=['tests/test_navigation_goal_lifecycle.py','tests/test_decision_plugin.py','tests/test_decision_bridge_core.py','tests/test_navigation_plugin.py','tests/test_robotio_ros2_bridge.py']
paths=tests+['rm_match/integrations/navigation_goal_lifecycle.py','rm_match/platform_v2/decision_contracts.py','rm_match/deployment/decision_plugin.py','rm_match/deployment/navigation_plugin.py','rm_match/integrations/robotio_ros2_bridge.py']
before={}
for name in paths:
 raw=(root/name).read_bytes();before[name]=hashlib.sha256(raw).hexdigest();target=out/'source03'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
cmd=[str(root/'.venv-sim/Scripts/python.exe'),'-m','pytest',*tests,'-q','--junitxml='+str(out/'junit03.xml')]
(out/'COMMAND03.json').write_text(json.dumps(cmd,indent=2),encoding='utf-8')
start=time.perf_counter()
with (out/'stdout03.log').open('wb') as stdout,(out/'stderr03.log').open('wb') as stderr:
 p=subprocess.Popen(cmd,cwd=root,stdout=stdout,stderr=stderr);rc=p.wait(timeout=120)
after={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in paths}
result=dict(exit_code=rc,reaped=p.poll() is not None,elapsed=time.perf_counter()-start,before=before,after=after,source_unchanged=before==after,scope='controlled backend/futures plus original JSONL/ROS envelope units, no actual ROS/WSL/sensors/physics')
(out/'PROCESS_RESULT03.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print((out/'stdout03.log').read_text());print((out/'stderr03.log').read_text());print(json.dumps(result))
