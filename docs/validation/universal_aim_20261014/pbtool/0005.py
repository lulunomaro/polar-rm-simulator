"""Pure tool regressions plus one real external-cwd Python child; no WSL/build."""
import hashlib,json,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
files=['tools/build_pb_aim_plugins.py','tests/test_build_pb_aim_plugins.py']
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
before={f:sha(ROOT/f) for f in files}
argv=[str(ROOT/'.venv-sim/Scripts/python.exe'),'-m','pytest','tests/test_build_pb_aim_plugins.py','tests/test_pb_aim_system_dependencies.py','-q']
started=time.perf_counter()
with (OUT/'focused.log').open('wb') as log:
 child=subprocess.Popen(argv,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT);code=child.wait()
after={f:sha(ROOT/f) for f in files}
for f in files:
 target=OUT/'executed_source'/f;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((ROOT/f).read_bytes())
report=dict(schema='polar.pb-aim-build-bootstrap-validation.v1',argv=argv,pid=child.pid,exit_code=code,
 reaped=child.poll() is not None,wall_seconds=time.perf_counter()-started,source_before=before,source_after=after,
 source_unchanged=before==after,scope='Pure source/prefix tests plus actual Windows Python subprocess from external cwd; no WSL/ROS/build/NN',
 change='Prepend fixed file-derived repository ROOT to sys.path before tools imports; original manifests/prefix/failed roots unchanged')
(OUT/'RESULT.json').write_bytes((json.dumps(report,indent=2)+'\n').encode());print(json.dumps(report,indent=2))
raise SystemExit(code if before==after else 3)
