"""Harmless lifecycle fixtures; actual Linux groups, no ROS/model/rendering."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from rm_match.integrations.wsl_operator import WslOperatorProcess

ROOT=Path(__file__).resolve().parents[1]


class HostCleanupTests(unittest.TestCase):
    def actor(self,out,child,ready):
        a=WslOperatorProcess.__new__(WslOperatorProcess)
        a._stop=threading.Event();a._broken=threading.Event();a.evidence_out=out
        a.diagnostics=[];a.process=child;a.stderr=io.BytesIO();a.ready=ready
        a.cleanup=None;a.checked=SimpleNamespace(linux_spec_sha256='spec');a._threads=[]
        return a

    def proof(self,out,**changes):
        own=dict(run_id='fixture-run',supervisor_pid=991,pid=992,pgid=992,boot_id='fixture-boot',
                 leader_start_ticks=5,spec_sha256='spec',transport='wsl_stdio_v1')
        (out/'OWNED_CHILD.json').write_text(json.dumps(own))
        clean=dict(own,clean=True,reaped=True,group_empty=True,remaining_members=[],errors=[],returncode=0)
        clean.update(changes);(out/'CLEANUP.json').write_text(json.dumps(clean))
        return dict(run_id=own['run_id'],supervisor_pid=own['supervisor_pid'],native_pid=own['pid'],transport=own['transport'])

    def test_wrong_run_proof_rejected_but_all_host_streams_closed(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td);ready=self.proof(out,run_id='another-run')
            child=subprocess.Popen([sys.executable,'-c','pass'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,bufsize=0)
            child.wait(timeout=2);a=self.actor(out,child,ready)
            with self.assertRaisesRegex(RuntimeError,'ownership mismatch'):a.close()
            self.assertTrue(child.stdin.closed);self.assertTrue(child.stdout.closed);self.assertTrue(a.stderr.closed)
            self.assertFalse(a.diagnostics[-1]['clean']);self.assertIsNone(a.process)
            with self.assertRaises(RuntimeError):a.close()

    def pre_native_proof(self,out,**changes):
        start=dict(run_id='fixture-run',supervisor_pid=991,supervisor_start_ticks=5,boot_id='fixture-boot',
            spec_sha256='spec',transport='wsl_stdio_bgr_v2',native_spawn_attempted=False)
        (out/'WORKER_STARTUP.json').write_text(json.dumps(start))
        proof=dict(start,reason='host_cancel',native_child_reaped=False,clean=True,errors=[],tmpfs_removed=True)
        proof.update(changes);(out/'PRE_NATIVE_EXIT.json').write_text(json.dumps(proof))

    def test_pre_native_exit_is_clean_but_never_claims_a_reaped_native_child(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td);self.pre_native_proof(out)
            child=subprocess.Popen([sys.executable,'-c','pass'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,bufsize=0)
            child.wait(timeout=2);a=self.actor(out,child,None);a.close()
            self.assertTrue(a.diagnostics[-1]['clean']);self.assertTrue(a.diagnostics[-1]['native_not_spawned'])
            self.assertFalse(a.diagnostics[-1]['linux_child_reaped']);self.assertTrue(child.stdout.closed)

    def test_pre_native_proof_rejects_mismatched_birth_spawn_or_existing_child(self):
        variants=(dict(run_id='other'),dict(supervisor_start_ticks=True),dict(native_spawn_attempted=True),
            dict(native_child_reaped=True),dict(reason='control_timeout'),dict(tmpfs_removed=False))
        for wrong in variants:
            with self.subTest(wrong=wrong),tempfile.TemporaryDirectory() as td:
                out=Path(td);self.pre_native_proof(out,**wrong);a=self.actor(out,None,None)
                with self.assertRaises(RuntimeError):a._load_cleanup_proof()
        with tempfile.TemporaryDirectory() as td:
            out=Path(td);self.pre_native_proof(out);(out/'OWNED_CHILD.json').write_text('{}')
            with self.assertRaisesRegex(RuntimeError,'ambiguous'):self.actor(out,None,None)._load_cleanup_proof()

    def test_ready_wrong_run_rejected_even_consistent_disk_proof(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td);ready=self.proof(out);ready['run_id']='wrong-startup'
            child=subprocess.Popen([sys.executable,'-c','pass'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,bufsize=0)
            child.wait(timeout=2);a=self.actor(out,child,ready)
            with self.assertRaisesRegex(RuntimeError,'another startup'):a.close()
            self.assertTrue(child.stdout.closed)

    def test_nonempty_group_proof_is_unclean(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td);ready=self.proof(out,group_empty=False,remaining_members=[{'pid':77}])
            child=subprocess.Popen([sys.executable,'-c','pass'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,bufsize=0)
            child.wait(timeout=2);a=self.actor(out,child,ready)
            with self.assertRaisesRegex(RuntimeError,'group cleanup not proved'):a.close()
            self.assertTrue(child.stdin.closed)

    def test_wait_failure_cannot_skip_finally_stream_cleanup(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td);ready=self.proof(out)
            child=subprocess.Popen([sys.executable,'-c','pass'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,bufsize=0)
            child.wait(timeout=2);a=self.actor(out,child,ready)
            with patch.object(child,'wait',side_effect=subprocess.TimeoutExpired('fixture',.01)):
                with self.assertRaises(RuntimeError):a.close()
            self.assertTrue(child.stdin.closed);self.assertTrue(child.stdout.closed);self.assertTrue(a.stderr.closed)
            self.assertFalse(a.diagnostics[-1]['clean'])

    def test_missing_cleanup_kills_only_launcher_and_unblocks_owned_pipe_threads(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)
            child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,bufsize=0)
            a=self.actor(out,child,None);entered=threading.Event()
            def writer():
                entered.set()
                try:child.stdin.write(b'x'*(8*1024*1024))
                except (OSError,ValueError):pass
            def reader():
                try:child.stdout.read(1)
                except (OSError,ValueError):pass
            a._threads=[threading.Thread(target=writer),threading.Thread(target=reader)]
            for thread in a._threads:thread.start()
            self.assertTrue(entered.wait(1));started=time.perf_counter()
            try:
                with self.assertRaisesRegex(RuntimeError,'missing Linux child cleanup proof'):a.close()
            finally:
                if child.poll() is None:child.kill();child.wait(timeout=2)
                for thread in a._threads:thread.join(2)
            self.assertLess(time.perf_counter()-started,1.5)
            self.assertTrue((out/'STOP').exists());self.assertTrue(all(not t.is_alive() for t in a._threads))
            self.assertFalse(a.diagnostics[-1]['clean']);self.assertTrue(child.stdin.closed);self.assertTrue(child.stdout.closed)


@unittest.skipUnless(sys.platform=='linux','Actual POSIX process groups; run explicitly through WSL')
class ActualLinuxGroupTests(unittest.TestCase):
    def test_cancel_or_deadline_during_file_setup_never_spawns_native_and_removes_tmpfs(self):
        from rm_match.integrations import wsl_operator_pipe_worker as worker
        import signal
        original_open=Path.open
        for mode in ('stop','signal','deadline'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as td:
                out=Path(td)
                def delayed_file_setup(path,*args,**kwargs):
                    stream=original_open(path,*args,**kwargs)
                    if path.name=='native_stderr.log':
                        if mode=='stop':(out/'STOP').write_bytes(b'cancel')
                        elif mode=='signal':os.kill(os.getpid(),signal.SIGTERM)
                        else:time.sleep(.07)
                    return stream
                valid=(dict(environment={},autoaim_config='unused',model_share='unused',binary='unused',executor_yaml='unused'),'spec')
                with patch.object(worker,'validate_linux_spec',return_value=valid),patch.object(Path,'open',delayed_file_setup),patch.object(worker.subprocess,'Popen',side_effect=AssertionError('late cancellation must not spawn')):
                    self.assertEqual(worker.prepare_and_supervise('unused','spec',out,{},startup_timeout=.05 if mode=='deadline' else 15.),2)
                proof=json.loads((out/'PRE_NATIVE_EXIT.json').read_text())
                self.assertEqual(proof['failed_phase'],'before_native_spawn');self.assertFalse(proof['native_spawn_attempted'])
                self.assertEqual(proof['reason'],'startup_timeout' if mode=='deadline' else 'host_cancel')
                self.assertTrue(proof['tmpfs_removed']);self.assertFalse(Path(proof['tmpfs_directory']).exists())
                self.assertFalse((out/'OWNED_CHILD.json').exists())
                print(json.dumps(dict(fixture='cancel_during_file_setup',mode=mode,proof=proof)),flush=True)

    def test_cancel_before_or_during_validation_never_spawns_native(self):
        from rm_match.integrations import wsl_operator_pipe_worker as worker
        for before in (True,False):
            with self.subTest(before=before),tempfile.TemporaryDirectory() as td:
                out=Path(td)
                if before:(out/'STOP').write_bytes(b'cancel')
                def validate(*args):
                    (out/'STOP').write_bytes(b'cancel')
                    return dict(environment={},autoaim_config='unused',model_share='unused',binary='unused',executor_yaml='unused'),'spec'
                with patch.object(worker,'validate_linux_spec',side_effect=validate) as validator,patch.object(worker,'supervise',side_effect=AssertionError('canceled startup must not spawn')):
                    self.assertEqual(worker.prepare_and_supervise('unused','spec',out,{}),0)
                self.assertEqual(validator.call_count,0 if before else 1)
                proof=json.loads((out/'PRE_NATIVE_EXIT.json').read_text())
                self.assertFalse(proof['native_spawn_attempted']);self.assertEqual(proof['reason'],'host_cancel')
                self.assertFalse((out/'OWNED_CHILD.json').exists());self.assertFalse((out/'STARTUP.json').exists())
                print(json.dumps(dict(fixture='pre_native_cancel',before_validation=before,proof=proof)),flush=True)

    def test_invalid_spec_records_owned_pre_native_exit_without_spawning(self):
        from rm_match.integrations import wsl_operator_pipe_worker as worker
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)
            with patch.object(worker,'validate_linux_spec',side_effect=ValueError('identity mismatch')),patch.object(worker,'supervise',side_effect=AssertionError('invalid identity must not spawn')):
                self.assertEqual(worker.prepare_and_supervise('unused','spec',out,{}),2)
            proof=json.loads((out/'PRE_NATIVE_EXIT.json').read_text())
            self.assertEqual(proof['reason'],'validation_failed');self.assertFalse(proof['native_child_reaped'])
            self.assertEqual(proof['failed_phase'],'validate_linux_spec');self.assertFalse((out/'OWNED_CHILD.json').exists())
            print(json.dumps(dict(fixture='pre_native_validation_failure',proof=proof)),flush=True)

    def test_both_workers_reap_term_ignoring_grandchild_after_leader_exits(self):
        for worker in ('wsl_operator_worker','wsl_operator_pipe_worker'):
            with self.subTest(worker=worker),tempfile.TemporaryDirectory() as td:
                out=Path(td);marker=out/'grandchild.json';leader_done=out/'leader_done'
                descendant="import os,signal,time,json;from pathlib import Path;signal.signal(signal.SIGTERM,signal.SIG_IGN);Path("+repr(str(marker))+ ").write_text(json.dumps({'pid':os.getpid(),'pgid':os.getpgrp()}));time.sleep(60)"
                leader=out/'leader.py'
                leader.write_text('import subprocess,sys,time\nfrom pathlib import Path\n'
                    +'subprocess.Popen([sys.executable,"-c",'+repr(descendant)+'])\n'
                    +'while not Path('+repr(str(marker))+').exists():time.sleep(.001)\n'
                    +'Path('+repr(str(leader_done))+').write_text("exited")\n')
                run="from rm_match.integrations."+worker+" import supervise;raise SystemExit(supervise(["+repr(sys.executable)+","+repr(str(leader))+"],"+repr(str(out/'worker'))+",{},spec_sha='harmless-group',startup_timeout=2.,control_timeout=.08))"
                process=subprocess.Popen([sys.executable,'-c',run],cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0)
                try:
                    process.wait(timeout=4)
                    record=json.loads((out/'worker/CLEANUP.json').read_text());own=json.loads((out/'worker/OWNED_CHILD.json').read_text())
                    grandchild=json.loads(marker.read_text())
                    self.assertTrue(leader_done.exists());self.assertEqual(record['returncode'],0)
                    self.assertTrue(record['clean'],record);self.assertTrue(record['group_empty']);self.assertTrue(record['killed'])
                    self.assertEqual(record['remaining_members'],[]);self.assertLess(record['cleanup_elapsed_s'],1.05)
                    self.assertEqual(record['run_id'],own['run_id']);self.assertEqual(grandchild['pgid'],own['pid'])
                    self.assertIn(grandchild['pid'],[r['pid'] for r in record['reaped_descendants']])
                    self.assertFalse(Path('/proc/'+str(grandchild['pid'])).exists())
                    if worker.endswith('pipe_worker'):self.assertTrue(record['tmpfs_removed'])
                    print(json.dumps(dict(fixture=worker,cleanup=record,leader_exited=True)),flush=True)
                finally:
                    if process.poll() is None:process.kill();process.wait(timeout=2)
                    for stream in (process.stdin,process.stdout,process.stderr):stream.close()

    def test_helper_rejects_non_session_child_without_signalling_foreign_group(self):
        from rm_match.integrations.owned_linux_group import LinuxOwnedProcessGroup
        owner=LinuxOwnedProcessGroup();child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
        try:
            with self.assertRaisesRegex(RuntimeError,'directly spawned Linux session'):owner.attach(child)
            with patch('os.killpg',side_effect=AssertionError('must not signal caller group')):
                result=owner.cleanup()
            self.assertFalse(result['clean']);self.assertIsNone(child.poll())
        finally:child.kill();child.wait(timeout=2)

    def test_group_cleanup_is_single_use_never_rekills_reused_id(self):
        from rm_match.integrations.owned_linux_group import LinuxOwnedProcessGroup
        owner=LinuxOwnedProcessGroup();child=subprocess.Popen([sys.executable,'-c','pass'],start_new_session=True)
        owner.attach(child);child.wait(timeout=2);self.assertTrue(owner.cleanup()['clean'])
        with patch('os.killpg',side_effect=AssertionError('must not signal reused group')):
            with self.assertRaisesRegex(RuntimeError,'single use'):owner.cleanup()

    def test_changed_leader_identity_never_signals_even_an_existing_group(self):
        from rm_match.integrations.owned_linux_group import LinuxOwnedProcessGroup
        owner=LinuxOwnedProcessGroup();child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],start_new_session=True)
        owner.attach(child);owner.identity['leader_start_ticks']+=1
        try:
            with patch('os.killpg',side_effect=AssertionError('foreign identity must not be signalled')):
                result=owner.cleanup()
            self.assertFalse(result['clean']);self.assertIsNone(child.poll());self.assertFalse(result['group_empty'])
        finally:child.kill();child.wait(timeout=2)
