"""Capture a fresh bounded actual Qt manual + PB WSL navigation run."""
from pathlib import Path
import argparse,hashlib,json,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--attempt',type=int,required=True);p.add_argument('--seconds',type=float,default=5.);p.add_argument('--max-wall-seconds',type=float,default=15.);a=p.parse_args()
assert 1<=a.attempt<=10 and 5<=a.seconds<=30 and a.seconds+5<=a.max_wall_seconds<=60
out=ROOT/f'artifacts/goal-velocity-coop-driver-20261015-{a.attempt:02}';out.mkdir()
names=['tools/qa_navigation_goal_client.py','tools/qa_navigation_goal_supervisor.py','tools/navigation_goal_session.py','rm_match/integrations/navigation_goal_lifecycle.py','rm_match/integrations/nav2_goal_backend.py','rm_match/platform_v2/decision_contracts.py','tools/qa_goal_velocity_coop_sil.py','tools/pb_coop_cleanup.py','tools/qa_qt_manual_peer.py','tools/audit_qt_manual.py','rm_match/platform_v2/runtime.py','tools/audit_navigation_goals.py','tools/pb_navigation_stack.py','tools/qa_pb_navigation_sil.py','rm_match/integrations/pb_navigation_bridge.py','rm_match/integrations/pb_wsl_navigation_worker.py','rm_match/integrations/pb_goal_controller_context.hpp','tools/prepare_nav2_goal_controller_overlay.py',
 'rm_match/integrations/pb_wsl_navigation.py','rm_match/integrations/pb_wsl_navigation_registry.py',
 'client_patches/CLIENT_CAMERA_ORDER_PATCH_MANIFEST.json','client_patches/robotio_camera_order_v1.patch',
 'artifacts/pb-humble-ext4-runtime-20261014/ENVIRONMENT_COMPAT_FINAL.json','artifacts/goal-velocity-config-20261015-01/STACK_CONFIG.json']
def hashes():return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}
before=hashes()
argv=[sys.executable,str(ROOT/'tools/qa_goal_velocity_coop_sil.py'),'--out',str(ROOT/f'artifacts/goal-velocity-coop-actual-20261015-{a.attempt:02}'),
 '--environment',str(ROOT/'artifacts/pb-humble-ext4-runtime-20261014/ENVIRONMENT_COMPAT_FINAL.json'),
 '--stack-config',str(ROOT/'artifacts/goal-velocity-config-20261015-01/STACK_CONFIG.json'),
 '--seconds',str(a.seconds),'--max-wall-seconds',str(a.max_wall_seconds),'--host-opencv-threads','4','--host-python-switch-interval-ms','1','--run']
(out/'driver.py').write_bytes(Path(__file__).read_bytes());(out/'COMMAND.json').write_bytes((json.dumps(dict(argv=argv,source_before=before),indent=2)+'\n').encode())
started=time.perf_counter();timed_out=False
with (out/'stdout.log').open('xb') as stdout,(out/'stderr.log').open('xb') as stderr:
    child=subprocess.Popen(argv,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,shell=False,creationflags=subprocess.CREATE_NO_WINDOW)
    (out/'PID.json').write_bytes((json.dumps(dict(pid=child.pid,driver_pid=__import__('os').getpid()))+'\n').encode())
    try:code=child.wait(timeout=a.max_wall_seconds+35.)
    except subprocess.TimeoutExpired:
        timed_out=True;child.terminate();code=child.wait(timeout=5.)
after=hashes();result=dict(returncode=code,reaped=child.poll() is not None,elapsed_s=time.perf_counter()-started,timed_out=timed_out,
 forced_direct_child_termination=timed_out,source_before=before,source_after=after,source_unchanged=before==after)
(out/'RESULT.json').write_bytes((json.dumps(result,indent=2)+'\n').encode());print(json.dumps({k:v for k,v in result.items() if k not in ('source_before','source_after')}));raise SystemExit(2 if timed_out else code)
