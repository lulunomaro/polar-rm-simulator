"""One fresh compiled-model resource observation. No image, tick or inference."""
import hashlib,json,os,subprocess,sys,tempfile,time,traceback
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from tools.validate_native_performance_profile import validate_performance_spec
from tools.native_model_properties import parse_native_model_properties
from rm_match.integrations.owned_linux_group import LinuxOwnedProcessGroup
from rm_match.integrations.wsl_operator_worker import _stdin_wait
out=root/'artifacts/native-compiled-properties-zero-tick-20261014-01';out.mkdir()
spec_path=root/'artifacts/native-compiled-properties-trace-build-20261014/operator_source.local.json'
spec,sha=validate_performance_spec(spec_path,expected_profile='first-frame-trace')
(out/'SPEC.json').write_bytes(spec_path.read_bytes())
owner=LinuxOwnedProcessGroup();child=None;cleanup=None;ready=None;errors=[];tmp=None;log=None
started=time.monotonic()
try:
 tmp=tempfile.TemporaryDirectory(prefix='polar-model-properties-',dir='/dev/shm');workspace=Path(tmp.name);workspace.chmod(0o700)
 (workspace/'tracking_mode').write_bytes(spec['runtime_mode_contents'].encode())
 env=os.environ.copy();env.update(spec.get('environment',{}));env.update(AUTOAIM_CONFIG=spec['autoaim_config'],RMCS_HEADLESS_SHARE=spec['model_share'],ORT_DISABLE_TELEMETRY='1')
 log=(out/'native_stderr.log').open('xb')
 command=[spec['binary'],spec['executor_yaml']]
 child=subprocess.Popen(command,cwd=workspace,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,bufsize=0,start_new_session=True)
 owned=owner.attach(child)
 (out/'OWNED_CHILD.json').write_text(json.dumps(dict(owned,spec_sha256=sha,command=command),indent=2)+'\n')
 deadline=started+15.
 while time.monotonic()<deadline:
  ready=_stdin_wait(child.pid)
  if ready:break
  if child.poll() is not None:raise RuntimeError('Native exited before stdin readiness')
  time.sleep(.005)
 if ready is None:raise TimeoutError('Original 15s resource readiness bound expired')
 (out/'STARTUP.json').write_text(json.dumps(dict(readiness=ready,setup_linux_s=time.monotonic()-started,
  native_control_requests=0,images=0,inference_calls=0,physics_steps=0,camera_captures=0,
  cpu_affinity=sorted(os.sched_getaffinity(child.pid)),spec_sha256=sha,**owned),indent=2)+'\n')
except BaseException as exc:
 errors.append(type(exc).__name__+':'+str(exc));(out/'ERROR.txt').write_text(traceback.format_exc())
finally:
 if child is not None:
  cleanup=owner.cleanup()
  for stream in (child.stdin,child.stdout):stream.close()
 if log is not None:log.close()
 tmp_path=None if tmp is None else tmp.name
 if tmp is not None:tmp.cleanup()
 stderr=(out/'native_stderr.log').read_bytes() if (out/'native_stderr.log').exists() else b''
 properties=parse_native_model_properties(stderr,expected_profile='first-frame-trace')
 result=dict(schema='polar.compiled-model-zero-tick-probe.v1',spec_sha256=sha,elapsed_linux_s=time.monotonic()-started,
  readiness=ready,cleanup=cleanup,tmpfs_removed=tmp_path is None or not Path(tmp_path).exists(),errors=errors,
  compiled_properties=properties,native_control_requests=0,images=0,inference_calls=0,physics_steps=0,camera_captures=0,
  native_stderr_sha256=hashlib.sha256(stderr).hexdigest(),
  scope='New diagnostic ELF, original CPU/LATENCY configuration; property queries and resource initialization only. No first-frame warm-up or live qualification')
 (out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps(result))
raise SystemExit(0 if not errors and ready and cleanup and cleanup['clean'] and result['tmpfs_removed'] and properties['valid'] and properties['core_properties_known'] else 2)
