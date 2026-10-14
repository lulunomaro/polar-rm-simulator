"""Capture one clean diagnostic build, never launch an inference executable."""
import hashlib,json,os,subprocess,time
from pathlib import Path
root=Path(__file__).resolve().parents[1]
out=root/'artifacts/compiled-properties-build-driver-20261014-01';out.mkdir()
linux='/mnt/c/'+root.as_posix()[3:]
files=['operator_native/runtime/build_portable.py','operator_native/runtime/CMakeLists.txt',
 'operator_native/runtime/overlays/prepare_first_frame_profile.py','operator_native/runtime/overlays/first_frame_trace.hpp',
 'tools/native_model_properties.py','tools/validate_native_performance_profile.py']
before={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in files}
for n in files:
 p=out/'source'/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((root/n).read_bytes())
command=['C:/Windows/System32/wsl.exe','-d','Ubuntu','--cd',linux,'--exec','/usr/bin/python3',
 'operator_native/runtime/build_portable.py','build','--out',linux+'/artifacts/native-compiled-properties-trace-build-20261014',
 '--prefix',linux+'/artifacts/deps/openvino/runtime/cmake','--jobs','2',
 '--corner-refinement','contour-v3','--performance-profile','first-frame-trace']
(out/'driver.py').write_bytes(Path(__file__).read_bytes())
(out/'COMMAND.json').write_text(json.dumps(dict(argv=command,cwd=str(root),source_before=before,
 scope='One fresh 29-TU clean diagnostic build; no NN/GL/physics; no recovered source edits'),indent=2)+'\n',encoding='utf-8')
started=time.perf_counter()
with (out/'stdout.log').open('xb') as stdout,(out/'stderr.log').open('xb') as stderr:
 child=subprocess.Popen(command,cwd=root,stdout=stdout,stderr=stderr,stdin=subprocess.DEVNULL,shell=False,creationflags=subprocess.CREATE_NO_WINDOW)
 (out/'PID.json').write_text(json.dumps(dict(pid=child.pid,driver_pid=os.getpid()))+'\n',encoding='utf-8')
 code=child.wait()
after={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in files}
result=dict(returncode=code,reaped=child.poll() is not None,elapsed_s=time.perf_counter()-started,
 source_before=before,source_after=after,source_unchanged=before==after)
(out/'PROCESS_RESULT.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k not in ('source_before','source_after')}));raise SystemExit(code)
