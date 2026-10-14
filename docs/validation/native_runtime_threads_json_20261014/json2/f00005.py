"""Windows harmless repaired owned-Job lifecycle, same leader/grandchild protocol."""
import ctypes
from ctypes import wintypes
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from rm_match.deployment.json_adapter import register_json_adapters,SCHEMA
from rm_match.platform_v2.adapters import Registry
assert sys.platform=='win32'
k=ctypes.WinDLL('kernel32',use_last_error=True)
k.OpenProcess.argtypes=(wintypes.DWORD,wintypes.BOOL,wintypes.DWORD);k.OpenProcess.restype=wintypes.HANDLE
k.WaitForSingleObject.argtypes=(wintypes.HANDLE,wintypes.DWORD);k.WaitForSingleObject.restype=wintypes.DWORD
k.CloseHandle.argtypes=(wintypes.HANDLE,);k.CloseHandle.restype=wintypes.BOOL
source=ROOT/'rm_match/deployment/json_adapter.py';sha=hashlib.sha256(source.read_bytes()).hexdigest()
nonce=uuid.uuid4().hex
with tempfile.TemporaryDirectory(prefix='polar-json-owned-after-') as td:
    out=Path(td);birth=out/'birth.json';grand=out/'grand.py';leader=out/'leader.py'
    grand.write_text('import json,os,sys,time;from pathlib import Path;Path(sys.argv[1]).write_text(json.dumps(dict(pid=os.getpid(),nonce=sys.argv[2])));time.sleep(3)\n')
    leader.write_text('import json,subprocess,sys;subprocess.Popen([sys.executable,"-u",sys.argv[1],sys.argv[2],sys.argv[3]],stdin=subprocess.DEVNULL);r=json.loads(input());print(json.dumps(dict(schema=r["schema"],op="reset",ok=True)),flush=True)\n')
    manifest=out/'manifest.json';manifest.write_text(json.dumps(dict(schema=SCHEMA,adapters=[dict(
        adapter_id='custom_owned_before',kind='navigation',label='Harmless ownership fixture',
        command=[sys.executable,'-u',str(leader),str(grand),str(birth),nonce],cwd=td,required_sensors=[])])))
    registry=Registry();register_json_adapters(registry,manifest);adapter=registry.create('custom_owned_before',{})
    adapter.reset(dict(robot_id='red_sentry',episode=0,binding_epoch=1));child=adapter.process
    child.wait(timeout=2)
    deadline=time.perf_counter()+2
    while not birth.exists() and time.perf_counter()<deadline:time.sleep(.005)
    row=json.loads(birth.read_text());assert row['nonce']==nonce
    handle=k.OpenProcess(0x00100000,False,row['pid']);assert handle
    try:
        before=k.WaitForSingleObject(handle,0)==258
        started=time.perf_counter();adapter.close();elapsed=time.perf_counter()-started
        alive=k.WaitForSingleObject(handle,1000)==258
        assert k.WaitForSingleObject(handle,5000)==0,'Bounded harmless fixture did not auto-exit'
    finally:k.CloseHandle(handle)
    report=dict(scope='Actual Windows harmless local JSON adapter, no simulation/ROS/NN',
       source_sha256=sha,source_unchanged=hashlib.sha256(source.read_bytes()).hexdigest()==sha,
       leader_returncode=child.returncode,grandchild_alive_before_close=before,
       grandchild_alive_after_close=alive,ownership_status=adapter.shutdown_status,adapter_IO_thread_stopped=not adapter.thread.is_alive(),
       close_elapsed_s=elapsed,fixture_child_exit_verified=True,nonce=nonce,
       defect_reproduced=before and alive and child.returncode==0)
    (Path(__file__).parent/'RESULT.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));assert not report['defect_reproduced'];assert adapter.shutdown_status['clean'];assert adapter.shutdown_status['ownership']['group_empty']
