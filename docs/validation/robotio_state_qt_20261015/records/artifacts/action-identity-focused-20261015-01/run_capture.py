"""Focused validation capture, no external algorithm/process/physics run."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

root = Path.cwd()
out = root / 'artifacts/action-identity-focused-20261015-01'
sources = [
    'rm_match/platform_v2/contracts.py', 'tests/test_action_identity_types.py',
    'rm_match/deployment/aim_plugin.py', 'rm_match/deployment/json_adapter.py',
    'rm_match/deployment/wsl_jsonl.py', 'rm_match/integrations/aim_jsonl_peer.py',
    'rm_match/integrations/robotio_ros2_bridge.py',
]


def snapshot():
    return {source: hashlib.sha256((root / source).read_bytes()).hexdigest()
            for source in sources}


before = snapshot()
command = [sys.executable, '-B', '-m', 'pytest', '-q',
           'tests/test_action_identity_types.py', '-p', 'no:cacheprovider',
           '--junitxml=' + str(out / 'pytest.xml')]
env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
started = time.perf_counter()
child = subprocess.Popen(command, cwd=root, env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
timed_out = False
try:
    stdout, stderr = child.communicate(timeout=30)
except subprocess.TimeoutExpired:
    timed_out = True
    child.kill()
    stdout, stderr = child.communicate(timeout=5)
elapsed = time.perf_counter() - started
(out / 'pytest.stdout.txt').write_bytes(stdout)
(out / 'pytest.stderr.txt').write_bytes(stderr)
after = snapshot()
result = dict(command=command, exit_code=child.returncode,
              pid=child.pid, reaped=child.poll() is not None, timed_out=timed_out,
              elapsed_s=elapsed, source_before=before, source_after=after,
              source_unchanged=before == after,
              scope='canonical_action_and_actual_aim_response_validators_only',
              started_algorithm_ros_wsl_physics_gui=False)
(out / 'RESULT.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print(stdout.decode('utf-8', errors='replace'))
print(json.dumps(result, indent=2))
repro_command = [sys.executable, '-B', '-c',
                "import runpy; runpy.run_path('artifacts/action-identity-focused-20261015-01/reproduce_identity.py')"]
repro = subprocess.run(repro_command, cwd=root, env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
(out / 'repro_after.stdout.txt').write_bytes(repro.stdout)
(out / 'repro_after.stderr.txt').write_bytes(repro.stderr)
(out / 'REPRO_AFTER_RESULT.json').write_text(json.dumps(dict(
    command=repro_command, exit_code=repro.returncode, reaped=True), indent=2) + '\n', encoding='utf-8')
print(repro.stdout.decode('utf-8', errors='replace'))
if child.returncode or timed_out or before != after or repro.returncode:
    raise SystemExit(1)
