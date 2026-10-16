"""Host cleanup proof sharing race, no inference/deadline acceptance changes."""
import ctypes
import json
import subprocess
import sys
import threading
import time

import pytest
from tests import test_owned_wsl_cleanup as fixtures


def actor(tmp_path):
    helper=fixtures.HostCleanupTests();ready=helper.proof(tmp_path)
    child=subprocess.Popen([sys.executable,'-c','pass'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,bufsize=0)
    child.wait(timeout=2)
    return helper.actor(tmp_path,child,ready)


def test_transient_proof_read_permission_is_retried_without_minting_proof(tmp_path,monkeypatch):
    a=actor(tmp_path);load=a._load_cleanup_proof;calls=[]
    def locked():
        calls.append(time.perf_counter())
        if len(calls)<=3:raise PermissionError('fixture writer still owns sharing lock')
        return load()
    monkeypatch.setattr(a,'_load_cleanup_proof',locked)
    a.close()
    assert len(calls)==4 and a.diagnostics[-1]['clean']
    assert a.cleanup['clean'] and a.cleanup['run_id']=='fixture-run'
    assert a._close_error is None and a.process is None


@pytest.mark.parametrize('fault',['bad_json','wrong_owner','permanent_denied'])
def test_invalid_or_permanently_unreadable_proof_remains_unclean_and_sticky(tmp_path,monkeypatch,fault):
    a=actor(tmp_path);calls=[];load=a._load_cleanup_proof
    if fault=='bad_json':(tmp_path/'CLEANUP.json').write_text('{')
    if fault=='wrong_owner':
        value=json.loads((tmp_path/'CLEANUP.json').read_text());value['run_id']='wrong'
        (tmp_path/'CLEANUP.json').write_text(json.dumps(value))
    def read():
        calls.append(time.perf_counter())
        if fault=='permanent_denied':raise PermissionError('fixture permanent denial')
        return load()
    monkeypatch.setattr(a,'_load_cleanup_proof',read)
    started=time.perf_counter()
    with pytest.raises(RuntimeError):a.close()
    elapsed=time.perf_counter()-started
    assert elapsed<1.5 and not a.diagnostics[-1]['clean']
    assert a.stderr.closed and a.process is None
    assert len(calls)==1 if fault!='permanent_denied' else len(calls)>1
    if fault=='permanent_denied':assert elapsed>=1.19
    with pytest.raises(RuntimeError):a.close()


@pytest.mark.skipif(sys.platform!='win32',reason='Actual Windows deny-share handle')
def test_actual_windows_cleanup_file_sharing_lock_is_released_within_original_budget(tmp_path):
    from ctypes import wintypes as w
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.CreateFileW.argtypes=(w.LPCWSTR,w.DWORD,w.DWORD,w.LPVOID,w.DWORD,w.DWORD,w.HANDLE)
    k.CreateFileW.restype=w.HANDLE;k.CloseHandle.argtypes=(w.HANDLE,);k.CloseHandle.restype=w.BOOL
    a=actor(tmp_path)
    handle=k.CreateFileW(str(tmp_path/'CLEANUP.json'),0x80000000,0,None,3,0,None)
    assert handle!=ctypes.c_void_p(-1).value
    unlocked=threading.Event()
    def release():
        assert k.CloseHandle(handle);unlocked.set()
    timer=threading.Timer(.06,release);timer.start()
    try:
        with pytest.raises(PermissionError):(tmp_path/'CLEANUP.json').read_bytes()
        started=time.perf_counter();a.close()
        assert unlocked.is_set() and time.perf_counter()-started<1.3
        assert a.diagnostics[-1]['clean'] and a.cleanup['reaped']
    finally:
        timer.join()
        if a.process is not None:a.close()
