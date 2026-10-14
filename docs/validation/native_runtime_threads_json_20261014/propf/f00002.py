"""Record local non-NN focused tests; no native executable is invoked."""
import hashlib
import json
from pathlib import Path
import subprocess
import time

root=Path(__file__).resolve().parents[2]
out=Path(__file__).parent
sources=('operator_native/runtime/overlays/first_frame_trace.hpp',
         'tools/native_model_properties.py','tests/test_native_model_properties.py')
sha=lambda raw:hashlib.sha256(raw).hexdigest()
before={rel:sha((root/rel).read_bytes()) for rel in sources}
for rel in sources:
    target=out/'source'/rel;target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes((root/rel).read_bytes())
command=[str(root/'.venv-sim/Scripts/python.exe'),'-m','pytest',
    'tests/test_native_model_properties.py','operator_native/runtime/test_performance_profiles.py',
    'tests/test_native_saved_input.py','-q']
(out/'COMMAND.json').write_text(json.dumps(dict(command=command,cwd=str(root),
    qualification='Non-NN parser/static prepare/previous saved-input unit tests only',source_before=before),indent=2)+'\n')
started=time.perf_counter()
with (out/'stdout.log').open('wb') as stdout,(out/'stderr.log').open('wb') as stderr:
    child=subprocess.Popen(command,cwd=root,stdout=stdout,stderr=stderr)
    code=child.wait(timeout=60)
after={rel:sha((root/rel).read_bytes()) for rel in sources}
result=dict(returncode=code,pid=child.pid,reaped=child.poll() is not None,
    elapsed_s=time.perf_counter()-started,source_before=before,source_after=after,
    sources_unchanged=before==after,stdout_sha256=sha((out/'stdout.log').read_bytes()),
    stderr_sha256=sha((out/'stderr.log').read_bytes()),
    qualification='No C++ compilation, WSL, GL, ROS or OpenVINO model execution')
(out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
