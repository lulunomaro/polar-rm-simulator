"""Fresh read-only audit and byte identity receipt; does not start ROS or physics."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT / 'artifacts/pb-wsl-production-sil-actual-20261014-attempt3'
DRIVER = ROOT / 'artifacts/pb-wsl-production-driver-20261014-03'
def sha(raw): return hashlib.sha256(raw).hexdigest()
def load(path): return json.loads(path.read_bytes())
command = [sys.executable, str(HERE/'audit.py'), '--source', str(SOURCE)]
assert not (HERE/'RESULT.json').exists(), 'fresh audit required'
script_before = sha((HERE/'audit.py').read_bytes())
originals_before = {p.relative_to(SOURCE).as_posix(): sha(p.read_bytes())
                    for p in sorted(SOURCE.rglob('*')) if p.is_file()}
driver_before = sha((DRIVER/'PROCESS_RESULT.json').read_bytes())
identity = load(DRIVER/'PROCESS_RESULT.json')
assert identity['returncode'] == 0 and identity['reaped'] is True
assert identity['source_before'] == identity['source_after'] and identity['source_unchanged'] is True
snapshot_proofs = {}
for relative, expected in identity['source_before'].items():
    path = Path(relative)
    assert not path.is_absolute() and '..' not in path.parts
    saved = DRIVER/'source'/path
    assert saved.is_file() and not saved.is_symlink(), relative
    actual = sha(saved.read_bytes())
    assert actual == expected, relative
    snapshot_proofs[relative] = actual
raw_identity = load(SOURCE/'RESULT.json')['source_sha256']
for relative, actual in snapshot_proofs.items():
    if relative in raw_identity:
        assert raw_identity[relative] == actual, relative
for required in ('rm_match/platform_v2/server.py', 'rm_match/platform_v2/client.py',
                 'rm_match/platform_v2/admission.py'):
    assert required in snapshot_proofs and snapshot_proofs[required] == raw_identity[required]
(HERE/'COMMAND.json').write_text(json.dumps({'command':command,
    'qualification':'Read-only independent original actual3 evidence; no new ROS/WSL/physics run'},indent=2)+'\n',encoding='utf8')
started = time.perf_counter()
process = subprocess.run(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
elapsed = time.perf_counter()-started
(HERE/'stdout.log').write_bytes(process.stdout)
(HERE/'stderr.log').write_bytes(process.stderr)
originals_after = {p.relative_to(SOURCE).as_posix(): sha(p.read_bytes())
                   for p in sorted(SOURCE.rglob('*')) if p.is_file()}
script_after = sha((HERE/'audit.py').read_bytes())
report = load(HERE/'RESULT.json')
record = {
    'exit_code':process.returncode, 'elapsed_s':elapsed, 'owned_driver_reaped':True,
    'audit_script_before_sha256':script_before, 'audit_script_after_sha256':script_after,
    'audit_script_unchanged':script_before==script_after,
    'original_files_before_sha256':originals_before, 'original_files_after_sha256':originals_after,
    'originals_unchanged':originals_before==originals_after,
    'actual_driver_process_sha256':driver_before,
    'actual_driver_unchanged':driver_before==sha((DRIVER/'PROCESS_RESULT.json').read_bytes()),
    'saved_source_snapshot_sha256':snapshot_proofs,
    'execution_roster_count':len(raw_identity), 'saved_source_count':len(snapshot_proofs),
    'server_client_admission_saved_bytes_match_execution':True,
    'result_sha256':sha((HERE/'RESULT.json').read_bytes()),
    'stdout_sha256':sha(process.stdout), 'stderr_sha256':sha(process.stderr),
    'scope':'Independent frozen actual3 original consumption/production/goal/resource audit; no milestone acceptance',
}
(HERE/'PROCESS_RESULT.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf8')
print(json.dumps({k:report[k] for k in ('passed','ROS_counts','nonzero_consumed_steps',
    'consumed_command_identities','capture_age_host_wall_s')}))
print(json.dumps({k:record[k] for k in ('exit_code','elapsed_s','originals_unchanged',
    'execution_roster_count','saved_source_count','server_client_admission_saved_bytes_match_execution',
    'result_sha256','audit_script_before_sha256')}))
raise SystemExit(0 if process.returncode==0 and report['passed'] and record['originals_unchanged']
    and record['audit_script_unchanged'] and record['actual_driver_unchanged'] else 2)
