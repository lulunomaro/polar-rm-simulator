"""Capture one fresh protocol-focused run, including final dependency bytes."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument('--attempt', type=int, required=True)
p.add_argument('--final-only', action='store_true')
a = p.parse_args()
assert 1 <= a.attempt <= 10
out = ROOT/f'artifacts/active-goal-protocol-focused-20261015-{a.attempt:02}'
out.mkdir()
names = [
    'rm_match/deployment/navigation_plugin.py', 'rm_match/deployment/robotio_plugin.py',
    'rm_match/deployment/robotio_wsl.py', 'rm_match/deployment/json_adapter.py',
    'rm_match/integrations/navigation_jsonl_peer.py', 'rm_match/integrations/robotio_ros2_bridge.py',
    'rm_match/integrations/navigation_goal_lifecycle.py', 'rm_match/integrations/goal_navigation_compute.py',
    'rm_match/platform_v2/goal_navigation_contracts.py', 'rm_match/platform_v2/navigation_contracts.py',
    'rm_match/platform_v2/decision_contracts.py', 'rm_match/platform_v2/contracts.py',
    'tests/test_active_goal_navigation_plugin.py', 'tests/test_active_goal_ros2_bridge.py',
    'tests/fixtures/active_goal_navigation_fixture.py',
]
if a.final_only:
    names += ['rm_match/integrations/pb_goal_controller_source.py', 'tools/qa_active_goal_protocol_sil.py',
        'tests/test_goal_navigation_contracts.py', 'tests/test_goal_navigation_compute.py',
        'tests/test_pb_goal_controller_source.py', 'tests/test_active_goal_protocol_audit.py']
def snapshot():
    return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}
before = snapshot()
for name in names:
    target = out/'sources'/name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((ROOT/name).read_bytes())
selected = ['tests/test_active_goal_navigation_plugin.py', 'tests/test_active_goal_ros2_bridge.py']
if a.final_only:
    selected += ['tests/test_goal_navigation_contracts.py', 'tests/test_goal_navigation_compute.py',
        'tests/test_pb_goal_controller_source.py', 'tests/test_active_goal_protocol_audit.py']
else:
    selected += ['tests/test_navigation_plugin.py', 'tests/test_robotio_ros2_bridge.py',
        'tests/test_robotio_plugin.py', 'tests/test_robotio_wsl.py']
command = [sys.executable, '-m', 'pytest', '-q', '--junitxml='+str(out/'pytest.xml'), *selected]
(out/'driver.py').write_bytes(Path(__file__).read_bytes())
(out/'COMMAND.json').write_bytes((json.dumps(dict(argv=command, source_before=before), indent=2)+'\n').encode())
start = time.perf_counter()
with (out/'stdout.log').open('xb') as stdout, (out/'stderr.log').open('xb') as stderr:
    child = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
        stdout=stdout, stderr=stderr, shell=False, creationflags=subprocess.CREATE_NO_WINDOW)
    (out/'PID.json').write_text(json.dumps(dict(pid=child.pid, driver_pid=os.getpid()))+'\n')
    code = child.wait(timeout=180)
after = snapshot()
result = dict(returncode=code, reaped=child.poll() is not None, elapsed_s=time.perf_counter()-start,
    source_before=before, source_after=after, source_unchanged=before==after,
    scope='unit/synthetic/actual owned JSONL protocol only; no live ROS/team algorithm/full match')
(out/'RESULT.json').write_bytes((json.dumps(result, indent=2)+'\n').encode())
print(json.dumps({k:v for k,v in result.items() if k not in ('source_before','source_after')}))
raise SystemExit(code or (0 if before==after else 1))
