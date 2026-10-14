"""Harmless Windows child stderr capture and pure failure-proof tests."""
import os
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch
import pytest
from rm_match.deployment.json_owned_process import OwnedJsonProcess
from rm_match.deployment.wsl_jsonl import OwnedWslJsonProcess

@pytest.mark.skipif(sys.platform!='win32',reason='actual Windows suspended Job fixture')
def test_windows_sink_keeps_raw_stderr_stdout_separate_and_original_handle_owned(tmp_path):
    path=tmp_path/'stderr.log'
    with path.open('wb',buffering=0) as sink:
        before=os.get_inheritable(sink.fileno())
        owner=OwnedJsonProcess([sys.executable,'-c',
            'import os;os.write(2,b"ModuleNotFoundError: missing_fixture\\n");os.write(1,b"canonical stdout\\n")'],
            cwd=str(tmp_path),env=dict(os.environ),stop_event=threading.Event(),stderr=sink)
        try:
            assert owner.child.stdout.readline(1024)==b'canonical stdout\n'
            assert owner.child.wait(timeout=2.)==0
            proof=owner.cleanup(time.perf_counter()+1.)
            assert proof['clean'] and proof['group_empty'] and proof['reaped']
            assert not sink.closed and os.get_inheritable(sink.fileno())==before
        finally:
            owner.cleanup(time.perf_counter()+1.)
            owner.child.stdin.close();owner.child.stdout.close();owner.release_handles()
    assert path.read_bytes()==b'ModuleNotFoundError: missing_fixture\n'

def test_posix_optional_sink_passed_to_only_owned_popen_without_taking_caller_file(tmp_path):
    from rm_match.deployment import json_owned_process as module
    class Child:
        stdin=None;stdout=None
    child=Child()
    class Owner:
        child=None
        def attach(self,c):self.child=c
    with (tmp_path/'stderr.log').open('wb') as sink:
        with patch.object(module.sys,'platform','linux'),patch.object(module,'_LinuxAdapterGroup',Owner),\
            patch.object(module.subprocess,'Popen',return_value=child) as spawn:
            result=OwnedJsonProcess(['/fixture/peer'],cwd='/fixture',env={},stop_event=threading.Event(),stderr=sink)
            assert result.child is child and spawn.call_args.kwargs['stderr'] is sink
            assert not sink.closed

def test_stderr_close_failure_cannot_report_clean_not_spawned_launch(tmp_path):
    class BrokenSink:
        closed=False
        def close(self):raise OSError('fixture close failure')
    owner=OwnedWslJsonProcess.__new__(OwnedWslJsonProcess)
    owner.status=None;owner._owned=None;owner.run_id='fixture'
    owner._launch_status=dict(clean=True,not_spawned=True,reaped=False,group_empty=True,errors=[])
    owner._stderr=BrokenSink()
    result=owner.cleanup(time.perf_counter()+.1)
    assert not result['clean'] and not result['host_stderr_closed']
    assert 'stderr_close:OSError' in result['errors']

def test_preownership_unknown_linux_failure_keeps_diagnostic_file_and_unclean(tmp_path):
    path=tmp_path/'supervisor.stderr.log';path.write_bytes(b'original import failure\n')
    owner=OwnedWslJsonProcess.__new__(OwnedWslJsonProcess)
    owner.status=None;owner._owned=None;owner._launch_status=None;owner.run_id='run';owner.sha='sha'
    owner.hello=None;owner.out=tmp_path;owner._reader=None;owner._stderr=path.open('ab',buffering=0)
    owner.request_stop=lambda:None
    result=owner.cleanup(time.perf_counter()+.05)
    assert result['clean'] is False and result['host_stderr_closed']
    assert path.read_bytes()==b'original import failure\n'
    assert 'linux_owned_cleanup_unproved' in result['errors']

def test_interrupted_cleanup_still_closes_own_sink_and_retains_unclean_proof(tmp_path):
    path=tmp_path/'supervisor.stderr.log'
    owner=OwnedWslJsonProcess.__new__(OwnedWslJsonProcess)
    owner.status=None;owner.run_id='run';owner._stderr=path.open('wb',buffering=0)
    owner._stderr.write(b'prior import failure\n')
    def interrupted(deadline):raise KeyboardInterrupt()
    owner._cleanup=interrupted
    with pytest.raises(KeyboardInterrupt):owner.cleanup(time.perf_counter()+1.5)
    assert owner._stderr.closed and not owner.status['clean']
    assert owner.status['host_stderr_closed']
    assert 'wsl_cleanup_interrupted:KeyboardInterrupt' in owner.status['errors']
    assert path.read_bytes()==b'prior import failure\n'
