"""Capture fresh focused protocol/cleanup checks on the exact input sources."""
from pathlib import Path
import argparse,hashlib,json,os,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--attempt',type=int,required=True);args=p.parse_args()
out=ROOT/f'artifacts/staged-protocol-focused-20261015-{args.attempt:02}';out.mkdir()
names=['rm_match/deployment/navigation_plugin.py','rm_match/deployment/robotio_plugin.py',
 'rm_match/deployment/decision_plugin.py','rm_match/integrations/navigation_jsonl_peer.py',
 'rm_match/integrations/decision_jsonl_peer.py','rm_match/integrations/robotio_ros2_bridge.py',
 'rm_match/integrations/pb_navigation_transport.py','tools/pb_navigation_stack.py',
 'rm_match/platform_v2/navigation_feedback_contracts.py','rm_match/platform_v2/decision_contracts.py',
 'tests/test_staged_navigation_plugin.py','tests/test_navigation_feedback_pipeline.py',
 'tests/test_pb_shared_cleanup_deadline.py','tests/fixtures/staged_navigation_feedback_fixture.py',
 'tests/fixtures/decision_navigation_feedback_v2.py']
snapshot=lambda:{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}
before=snapshot()
for name in names:
    target=out/'source'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((ROOT/name).read_bytes())
command=[sys.executable,'-m','pytest','-q','--junitxml='+str(out/'JUNIT.xml'),
 'tests/test_staged_navigation_plugin.py','tests/test_navigation_feedback_pipeline.py',
 'tests/test_pb_shared_cleanup_deadline.py','tests/test_navigation_plugin.py',
 'tests/test_robotio_plugin.py','tests/test_robotio_ros2_bridge.py','tests/test_robotio_registration_races.py',
 'tests/test_robotio_wsl.py','tests/test_active_goal_navigation_plugin.py','tests/test_active_goal_ros2_bridge.py',
 'tests/test_pb_navigation_stack.py','tests/test_pb_navigation_transport.py']
(out/'driver.py').write_bytes(Path(__file__).read_bytes())
(out/'COMMAND.json').write_bytes((json.dumps(dict(argv=command,source_before=before),indent=2)+'\n').encode())
start=time.perf_counter()
with (out/'stdout.log').open('xb') as stdout,(out/'stderr.log').open('xb') as stderr:
    child=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,
        shell=False,creationflags=subprocess.CREATE_NO_WINDOW)
    (out/'PID.json').write_text(json.dumps(dict(pid=child.pid,driver_pid=os.getpid()))+'\n')
    code=child.wait(timeout=180)
after=snapshot()
result=dict(returncode=code,reaped=child.poll() is not None,elapsed_s=time.perf_counter()-start,
 source_before=before,source_after=after,source_unchanged=before==after,
 scope='unit/synthetic/owned JSONL protocol checks, no actual ROS or team algorithm acceptance')
(out/'RESULT.json').write_bytes((json.dumps(result,indent=2)+'\n').encode())
print(json.dumps({k:v for k,v in result.items() if k not in ('source_before','source_after')}))
raise SystemExit(code or (0 if before==after else 1))
