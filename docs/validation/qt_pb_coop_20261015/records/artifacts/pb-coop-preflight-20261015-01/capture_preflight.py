"""Capture explicitly authorized read-only WSL identity checks, no ROS launch."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

root = Path.cwd()
out = root / 'artifacts/pb-coop-preflight-20261015-01'
environment = root / 'artifacts/pb-humble-ext4-runtime-20261014/ENVIRONMENT_COMPAT_FINAL.json'
config = root / 'artifacts/pb-navigation-sil-config-20261014-04.json'
sources = [environment, config, root / 'rm_match/integrations/pb_wsl_navigation.py',
           root / 'rm_match/integrations/pb_wsl_navigation_registry.py',
           out / 'linux_readonly_preflight.py']


def snapshot():
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}


def linux(path):
    return '/mnt/' + path.drive[0].lower() + '/' + '/'.join(path.parts[1:])


before = snapshot()
command = [str(Path(os.environ['SystemRoot']) / 'System32/wsl.exe'), '-d', 'Ubuntu-22.04',
           '--', '/usr/bin/python3', '-I', '-B', '-S', linux(out / 'linux_readonly_preflight.py'),
           '--environment', linux(environment), '--environment-sha', before[str(environment.relative_to(root))],
           '--config', linux(config), '--config-sha', before[str(config.relative_to(root))]]
(out / 'COMMAND.json').write_text(json.dumps(dict(command=command, source_before=before,
    scope='readonly_wsl_paths_versions_sha_processes_no_ros_gl_algorithm'), indent=2) + '\n', encoding='utf-8')
started = time.perf_counter()
child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=root)
timed_out = False
try:
    stdout, stderr = child.communicate(timeout=35)
except subprocess.TimeoutExpired:
    timed_out = True
    child.kill()
    stdout, stderr = child.communicate(timeout=5)
(out / 'stdout.bin').write_bytes(stdout)
(out / 'stderr.bin').write_bytes(stderr)
after = snapshot()
details = json.loads(stdout) if child.returncode == 0 else None
result = dict(command=command, exit_code=child.returncode, pid=child.pid,
              reaped=child.poll() is not None, timed_out=timed_out,
              elapsed_s=time.perf_counter() - started, source_before=before, source_after=after,
              source_unchanged=before == after, linux_report=details,
              algorithm_or_ros_started=False,
              scope='resource_identity_preflight_not_new_navigation_or_coop_acceptance')
(out / 'RESULT.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print(json.dumps(dict(exit_code=child.returncode, reaped=result['reaped'],
    elapsed_s=result['elapsed_s'], source_unchanged=result['source_unchanged'],
    resource_identity_passed=None if details is None else details['resource_identity_passed'],
    errors=None if details is None else details['errors'],
    matching_processes=None if details is None else details['matching_processes'],
    python_abi=None if details is None else details['python_abi'],
    package_xml_versions=None if details is None else details['package_xml_versions']), indent=2))
raise SystemExit(0 if child.returncode == 0 and not timed_out and before == after else 1)
