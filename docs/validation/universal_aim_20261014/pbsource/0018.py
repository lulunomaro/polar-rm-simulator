"""Pure source/lifecycle evidence only. No ROS/WSL/model execution."""
import hashlib,json,os,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
PY=ROOT/'.venv-sim/Scripts/python.exe'
SOURCE=['rm_match/integrations/pb_aim_contract.py','rm_match/integrations/pb_aim_ros_peer.py',
 'rm_match/integrations/pb_aim_configure.py','rm_match/integrations/pb_aim_engine.py',
 'rm_match/integrations/pb_aim_stack.py','rm_match/integrations/pb_aim_source.hpp',
 'tools/prepare_pb_aim_plugin.py','tools/prepare_pb_aim_dependencies.py','tools/prepare_pb_aim_stack.py',
 'tests/test_pb_aim_plugin.py','tests/test_pb_aim_prepare_lifecycle.py','tests/test_pb_aim_dependencies.py',
 'docs/PB2025_AIM_ADAPTER_SOURCE.md']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
before={p:sha(ROOT/p) for p in SOURCE}
OLD=['pb2025-aim-source-20261014-02','pb2025-aim-dependency-compat-20261014-02','pb2025-aim-plugin-focused-20261014-01']
previous={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for d in OLD for p in (ROOT/'artifacts'/d).rglob('*') if p.is_file()}
commands=[('focused',[str(PY),'-m','pytest','tests/test_pb_aim_prepare_lifecycle.py','tests/test_pb_aim_plugin.py','tests/test_pb_aim_dependencies.py','-q']),
 ('source_prepare',[str(PY),'tools/prepare_pb_aim_plugin.py','--source',str(ROOT/'external/pb2025-aim-interface-review'),'--out',str(ROOT/'artifacts/pb2025-aim-source-20261014-03')]),
 ('dependency_prepare',[str(PY),'tools/prepare_pb_aim_dependencies.py','--source-root',str(ROOT/'artifacts/pb2025-aim-dependencies-20261014-01/source'),'--out',str(ROOT/'artifacts/pb2025-aim-dependency-compat-20261014-03')])]
rows=[]
for name,argv in commands:
 start=time.perf_counter()
 with (OUT/(name+'.log')).open('wb') as log:
  child=subprocess.Popen(argv,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
  code=child.wait()
 rows.append(dict(name=name,argv=argv,pid=child.pid,exit_code=code,reaped=child.poll() is not None,wall_seconds=time.perf_counter()-start))
 if code:break
after={p:sha(ROOT/p) for p in SOURCE}
old_after={p:sha(ROOT/p) for p in previous}
for relative in SOURCE:
 target=OUT/'executed_source'/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((ROOT/relative).read_bytes())
result=dict(schema='polar.pb-aim-source-pure-validation.v1',commands=rows,
 source_before=before,source_after=after,source_unchanged=before==after,
 previous_artifacts_sha256=previous,previous_artifacts_unchanged=previous==old_after,
 scope='Pure Python/source-copy fixtures only: no ROS/DDS/WSL/GL/build/model load/NN; one symlink case depends on actual Windows privilege',
 first_focused_failure=dict(passed=36,failed=2,skipped=1,
  causes=['PyYAML missing in .venv-sim (root installed actual6.0.2 separately)','Pure fixture incorrectly used _context; actual bridge property is context']),
 source_manifest=str(ROOT/'artifacts/pb2025-aim-source-20261014-03/SOURCE_MANIFEST.json'),
 dependency_manifest=str(ROOT/'artifacts/pb2025-aim-dependency-compat-20261014-03/SOURCE_MANIFEST.json'))
(OUT/'RESULT.json').write_bytes((json.dumps(result,indent=2)+'\n').encode())
print(json.dumps(dict(source_unchanged=result['source_unchanged'],previous_artifacts_unchanged=result['previous_artifacts_unchanged'],commands=rows),indent=2))
raise SystemExit(0 if len(rows)==3 and all(r['exit_code']==0 for r in rows) and before==after and previous==old_after else 1)
