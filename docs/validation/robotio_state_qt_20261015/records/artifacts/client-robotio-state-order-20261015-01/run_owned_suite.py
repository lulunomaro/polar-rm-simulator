"""Captured actual installed PySide6 suite; fixtures, not a live/visible run."""
from pathlib import Path
import hashlib
import json
import os
import sys
import threading
import time

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT))
from rm_match.deployment.json_owned_process import OwnedJsonProcess
CLIENT=ROOT/'external/polar-rm-client-robotio-state-review'
mode=sys.argv[1];OUT=HERE/('pytest-'+mode);OUT.mkdir()
FILES=['test_platform_claim_state_order.py']
if mode.startswith('after'):
    FILES+=['test_platform_adapters.py','test_aim_plugin_discovery.py','test_aim_status_display.py',
        'test_operator_state_projection.py','test_platform_control_windows.py','test_platform_handoff.py',
        'test_platform_manual_yaw.py','test_platform_manual_yaw_ui.py','test_platform_spin.py',
        'test_platform_status.py','test_platform_admission_client.py','test_platform_display_generation.py',
        'test_platform_diagnostics.py','test_sim_platform_v2.py','test_transport_safety_regressions.py']
paths=['rm_client/sim_platform_transport.py',*['tests/'+f for f in FILES]]
before={}
for rel in paths:
    raw=(CLIENT/rel).read_bytes();before[rel]=hashlib.sha256(raw).hexdigest()
    target=OUT/'source'/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
command=[str(ROOT/'.venv-client/Scripts/python.exe'),'-m','pytest',*['tests/'+f for f in FILES],'-q','--junitxml='+str(OUT/'pytest.xml')]
env=dict(os.environ);env.update(QT_QPA_PLATFORM='offscreen',PYTHONPATH=str(ROOT))
for key in tuple(env):
    if any(s in key.upper() for s in ('CREDENTIAL','SECRET','TOKEN','PASSWORD')):env.pop(key,None)
stop=threading.Event();owner=None;reader=None;errors=[];started=time.perf_counter()
record=dict(argv=command,cwd=str(CLIENT),source_sha256=before,mode=mode,
    scope='original transport concurrency/negative fixtures plus installed PySide6 offscreen suite; no physics/GL renderer/ROS/NN/visible GUI')
(OUT/'COMMAND.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf8')
try:
    with (OUT/'stderr.log').open('wb') as err:
        owner=OwnedJsonProcess(command,cwd=str(CLIENT),env=env,stop_event=stop,stderr=err)
        record['pid']=owner.child.pid
        def read():
            try:
                total=0
                with (OUT/'stdout.log').open('wb') as log:
                    while True:
                        raw=owner.child.stdout.read(65536)
                        if not raw:return
                        total+=len(raw)
                        if total>16*1024*1024:raise RuntimeError('fixture_log_bound')
                        log.write(raw)
            except BaseException as exc:errors.append(type(exc).__name__)
        reader=threading.Thread(target=read,daemon=True);reader.start()
        record['exit_code']=owner.child.wait(timeout=120.)
except BaseException as exc:errors.append(type(exc).__name__)
finally:
    stop.set();deadline=time.perf_counter()+1.5
    if owner is not None:
        record['cleanup']=owner.cleanup(deadline)
        if reader is not None:reader.join(max(0.,deadline-time.perf_counter()))
        for stream in (owner.child.stdin,owner.child.stdout):stream.close()
        owner.release_handles()
    record.update(reader_stopped=reader is None or not reader.is_alive(),errors=errors,
        source_unchanged=all(hashlib.sha256((CLIENT/p).read_bytes()).hexdigest()==h for p,h in before.items()),
        elapsed_s=time.perf_counter()-started,driver_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (OUT/'PROCESS_RESULT.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf8')
print(json.dumps({k:v for k,v in record.items() if k!='source_sha256'},indent=2))
raise SystemExit(0 if record.get('exit_code')==0 and record.get('cleanup',{}).get('clean') and record['reader_stopped'] and record['source_unchanged'] and not errors else 2)
