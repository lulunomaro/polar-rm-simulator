"""One owned resource-only preparation; no image, native tick or physics."""
import argparse,hashlib,json,os,sys,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from rm_match.integrations.wsl_operator_pipe import WslPipeOperatorProcess
p=argparse.ArgumentParser();p.add_argument('--attempt',type=int,default=1);args=p.parse_args()
out=ROOT/f'artifacts/prepared-native-startup-probe-20261014-{args.attempt:02}'
out.mkdir()
sources=['rm_match/integrations/wsl_operator_pipe.py','rm_match/integrations/wsl_operator_pipe_worker.py',
 'rm_match/integrations/wsl_operator.py','rm_match/integrations/wsl_operator_worker.py',
 'rm_match/integrations/owned_linux_group.py','rm_match/platform_v2/native_image.py',
 'rm_match/platform_v2/native_camera_snapshot.py']
def hashes():return {n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in sources}
before=hashes()
for n in sources:
 p=out/'source'/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/n).read_bytes())
(out/'driver.py').write_bytes(Path(__file__).read_bytes())
process=None;errors=[];started=time.perf_counter();phases={}
try:
 process=WslPipeOperatorProcess(ROOT/'artifacts/native-original-nav-checkpoint-build-20261013/operator_source.local.json',
  out/'binding',dict(fov_degrees=180.,circle_radius_x_norm=1.,circle_radius_y_norm=1.))
 phases['construction_elapsed_s']=time.perf_counter()-started
 process.reset(dict(episode=0))
 phases['reset_elapsed_s']=time.perf_counter()-started-phases['construction_elapsed_s']
except BaseException as exc:
 errors.append(dict(phase='prepare',type=type(exc).__name__,message=str(exc)))
 (out/'ERROR.txt').write_text(traceback.format_exc(),encoding='utf-8')
finally:
 if process is not None:
  try:process.close()
  except BaseException as exc:errors.append(dict(phase='close',type=type(exc).__name__,message=str(exc)))
 result=dict(schema='polar.resource-only-native-startup-probe.v1',driver_pid=os.getpid(),
  elapsed_s=time.perf_counter()-started,phases=phases,errors=errors,
  ready=None if process is None else process.ready,cleanup=None if process is None else process.cleanup,
  diagnostics=None if process is None else process.diagnostics,evidence_out=None if process is None else str(process.evidence_out),
  source_before=before,source_after=hashes(),source_unchanged=before==hashes(),
  native_control_requests=0,images=0,camera_captures=0,physics_steps=0,
  scope='Owned model-resource preparation and stdin readiness only; no warm-up ticks or live qualification')
 (out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(dict(errors=errors,ready=result['ready'],cleanup=result['cleanup'],elapsed_s=result['elapsed_s'])))
raise SystemExit(0 if not errors else 2)
