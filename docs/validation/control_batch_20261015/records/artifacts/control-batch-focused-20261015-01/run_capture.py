"""Focused fake-clock and real loopback HTTP batch checks; no simulation."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

root = Path.cwd()
out = root / 'artifacts/control-batch-focused-20261015-01'
sources = ['rm_match/platform_v2/control.py', 'rm_match/platform_v2/server.py',
           'tests/test_control_batch.py', 'rm_match/platform_v2/spin.py']


def snapshot():
    return {source: hashlib.sha256((root / source).read_bytes()).hexdigest()
            for source in sources}


before = snapshot()
command = [sys.executable, '-B', '-m', 'pytest', '-q',
           'tests/test_control_batch.py', '-p', 'no:cacheprovider',
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
              scope='control_batch_fake_clock_atomicity_and_real_loopback_http_only',
              started_algorithm_ros_wsl_physics_gl_gui=False)
(out / 'RESULT.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print(stdout.decode('utf-8', errors='replace'))
print(json.dumps(result, indent=2))
if child.returncode or timed_out or before != after:
    raise SystemExit(1)
