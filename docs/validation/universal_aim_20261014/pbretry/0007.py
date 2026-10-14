"""Pure HTTP response/cache fixtures only; never downloads or invokes WSL."""
import hashlib,json,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
files=['tools/build_pb_aim_plugins.py','tools/prepare_pb_aim_system_dependencies.py',
 'tests/test_build_pb_aim_plugins.py','tests/test_pb_aim_system_dependencies.py']
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
before={f:sha(ROOT/f) for f in files}
argv=[str(ROOT/'.venv-sim/Scripts/python.exe'),'-m','pytest','tests/test_pb_aim_system_dependencies.py','tests/test_build_pb_aim_plugins.py','-q']
started=time.perf_counter()
with (OUT/'focused.log').open('wb') as log:
 child=subprocess.Popen(argv,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT);code=child.wait()
after={f:sha(ROOT/f) for f in files}
for f in files:
 target=OUT/'executed_source'/f;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((ROOT/f).read_bytes())
report=dict(schema='polar.pb-aim-https-retry-pure-validation.v1',argv=argv,pid=child.pid,exit_code=code,
 reaped=child.poll() is not None,wall_seconds=time.perf_counter()-started,source_before=before,source_after=after,
 source_unchanged=before==after,scope='Pure mocked HTTP and actual local-file cache tests; no real network/WSL/apt/ROS/build/NN',
 candidates='HTTPS exact same host/path first, original HTTP second, HTTPS one final retry; at most3, signed SHA/size always required',
 partial_evidence='Each failed attempt retains separate partial bytes/hash; never reused as cache; cache accepted only full signed SHA+size',
 planned_deps_argv=['/usr/bin/python3','/mnt/c/Users/lulu/Desktop/claude/polarsimulation/polar-rm-simulator/tools/prepare_pb_aim_system_dependencies.py',
 '--out','/root/polar-pb-aim-system-deps-20261014-02','--cache','/root/polar-pb-aim-system-deps-20261014-01/debs','--run'])
(OUT/'RESULT.json').write_bytes((json.dumps(report,indent=2)+'\n').encode());print(json.dumps(report,indent=2))
raise SystemExit(code if before==after else 3)
