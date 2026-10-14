import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts' / 'coop-robotio-options-focused-20261014-04'
OUT.mkdir(exist_ok=False)
SOURCES = ['rm_match/deployment/coop_launcher.py', 'tests/test_coop_launcher.py',
           'rm_match/deployment/launcher.py', 'rm_match/deployment/profile.py',
           'client_patches/CLIENT_PATCH_MANIFEST.json']
def snapshot():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCES}
before = snapshot()
command = [sys.executable, '-m', 'pytest', '-q', 'tests/test_coop_launcher.py',
           '--junitxml=' + str(OUT / 'pytest.xml')]
started = time.perf_counter()
proc = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=30)
elapsed = time.perf_counter() - started
(OUT / 'pytest.stdout.log').write_bytes(proc.stdout)
(OUT / 'pytest.stderr.log').write_bytes(proc.stderr)
after = snapshot()
result = dict(command=command, exit_code=proc.returncode, reaped=True, elapsed_s=elapsed,
              source_before=before, source_after=after, source_unchanged=before == after,
              scope='local_launcher_config_and_owned_lifecycle_mocks_only_no_physics_client_DDS_NN',
              started_physics_client_dds_nn=False)
(OUT / 'RESULT.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf8')
print(json.dumps({k: result[k] for k in ('exit_code', 'reaped', 'elapsed_s', 'source_unchanged', 'scope')}))
print(proc.stdout.decode('utf8', errors='replace'))
raise SystemExit(proc.returncode)
