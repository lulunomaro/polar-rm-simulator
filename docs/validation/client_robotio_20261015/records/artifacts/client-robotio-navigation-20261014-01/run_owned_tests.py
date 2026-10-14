"""Actual installed PySide6 offscreen tests, owned Windows process group."""
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT))
from rm_match.deployment.json_owned_process import OwnedJsonProcess

CLIENT=ROOT/'external/polar-rm-client-robotio-review'
OUT=HERE/'pytest-owned'
OUT.mkdir(exist_ok=False)
FILES=['test_platform_adapters.py','test_aim_plugin_discovery.py','test_aim_status_display.py',
    'test_operator_state_projection.py','test_platform_control_windows.py','test_platform_handoff.py',
    'test_platform_manual_yaw.py','test_platform_manual_yaw_ui.py','test_platform_spin.py',
    'test_platform_status.py','test_platform_admission_client.py','test_platform_display_generation.py',
    'test_platform_diagnostics.py','test_sim_platform_v2.py']
command=[str(ROOT/'.venv-client/Scripts/python.exe'),'-m','pytest',
    *['tests/'+name for name in FILES],'-q','--junitxml='+str(OUT/'pytest.xml')]
env=os.environ.copy();env.update(QT_QPA_PLATFORM='offscreen',PYTHONPATH=str(ROOT))
env.pop('POLAR_SIM_ADMISSION_CREDENTIAL',None)
stop=threading.Event();record=dict(argv=command,cwd=str(CLIENT),
    environment=dict(QT_QPA_PLATFORM='offscreen',PYTHONPATH=str(ROOT)),scope='Qt/protocol fixtures, no physical/ROS/NN/visible window qualification')
owner=None;reader=None;started=time.perf_counter();errors=[]
try:
    with (OUT/'stderr.log').open('wb') as err:
        owner=OwnedJsonProcess(command,cwd=str(CLIENT),env=env,stop_event=stop,stderr=err)
        record['pid']=owner.child.pid
        def read():
            try:
                total=0
                with (OUT/'stdout.log').open('wb') as log:
                    while True:
                        chunk=owner.child.stdout.read(65536)
                        if not chunk:return
                        total+=len(chunk)
                        if total>16*1024*1024:raise RuntimeError('test_log_bound_exceeded')
                        log.write(chunk)
            except BaseException as exc:errors.append(type(exc).__name__)
        reader=threading.Thread(target=read,name='client-test-evidence',daemon=True);reader.start()
        record['exit_code']=owner.child.wait(timeout=120.)
except BaseException as exc:
    errors.append(type(exc).__name__)
finally:
    stop.set()
    if owner is not None:
        record['cleanup']=owner.cleanup(time.perf_counter()+1.5)
        if reader is not None:reader.join(1.)
        for stream in (owner.child.stdin,owner.child.stdout):stream.close()
        owner.release_handles()
    record['reader_stopped']=reader is None or not reader.is_alive()
    record['elapsed_s']=time.perf_counter()-started;record['errors']=errors
    record['driver_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (OUT/'PROCESS_RESULT.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf8')
print(json.dumps(record,indent=2))
raise SystemExit(0 if record.get('exit_code')==0 and record.get('cleanup',{}).get('clean') and record['reader_stopped'] and not errors else 2)
