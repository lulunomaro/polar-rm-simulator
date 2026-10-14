"""Harmless actual process ownership/pipe tests, no ROS/NN/physics.

POSIX actual subprocess cases require their own explicit load window opt-in.
"""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch
from rm_match.deployment.json_adapter import SCHEMA,register_json_adapters
from rm_match.platform_v2.adapters import Registry
from rm_match.platform_v2.test_contracts import sample

class _Fixture:
    def make(self,leader_exit=True):
        td=tempfile.TemporaryDirectory(prefix='polar-json-owned-');out=Path(td.name)
        nonce=uuid.uuid4().hex;birth=out/'birth.json';grand=out/'grand.py';leader=out/'leader.py'
        grand.write_text('import json,os,signal,sys,time;from pathlib import Path\n'
            'if sys.platform=="linux":signal.signal(signal.SIGTERM,signal.SIG_IGN)\n'
            'p=Path(sys.argv[1]);tmp=p.with_suffix(".tmp");tmp.write_text(json.dumps(dict(pid=os.getpid(),nonce=sys.argv[2])));os.replace(tmp,p)\n'
            'time.sleep(8)\n')
        leader.write_text('import json,subprocess,sys,time\n'
            'subprocess.Popen([sys.executable,"-u",sys.argv[1],sys.argv[2],sys.argv[3]])\n'
            'r=json.loads(input());print(json.dumps(dict(schema=r["schema"],op="reset",ok=True)),flush=True)\n'
            + ('' if leader_exit else 'time.sleep(8)\n'))
        manifest=out/'manifest.json';manifest.write_text(json.dumps(dict(schema=SCHEMA,adapters=[dict(
            adapter_id='custom_owned_test',kind='navigation',label='Harmless owned-process test',
            command=[sys.executable,'-u',str(leader),str(grand),str(birth),nonce],cwd=td.name,required_sensors=[])])))
        registry=Registry();register_json_adapters(registry,manifest)
        adapter=registry.create('custom_owned_test',{});o=sample();o['wall_deadline']=time.perf_counter()+.15
        context={k:o[k] for k in ('robot_id','episode','binding_epoch')}
        return td,adapter,o,context,birth,nonce

    def birth(self,path,nonce):
        deadline=time.perf_counter()+2
        while not path.exists() and time.perf_counter()<deadline:time.sleep(.005)
        row=json.loads(path.read_text());self.assertEqual(row['nonce'],nonce);return row

@unittest.skipUnless(sys.platform=='win32','Actual Windows owned Job/stdio check')
class WindowsJobTests(_Fixture,unittest.TestCase):
    def handle(self,pid):
        from ctypes import wintypes as w
        k=ctypes.WinDLL('kernel32',use_last_error=True)
        k.OpenProcess.argtypes=(w.DWORD,w.BOOL,w.DWORD);k.OpenProcess.restype=w.HANDLE
        k.WaitForSingleObject.argtypes=(w.HANDLE,w.DWORD);k.WaitForSingleObject.restype=w.DWORD
        k.CloseHandle.argtypes=(w.HANDLE,);k.CloseHandle.restype=w.BOOL
        h=k.OpenProcess(0x00100000,False,pid);self.assertTrue(h)
        return k,h

    def test_exited_leader_descendant_is_killed_even_with_idle_adapter(self):
        td,a,o,context,birth,nonce=self.make()
        handle=None
        try:
            a.reset(context);child=a.process;child.wait(timeout=2)
            row=self.birth(birth,nonce);k,handle=self.handle(row['pid'])
            self.assertEqual(k.WaitForSingleObject(handle,0),258)
            a.close()
            self.assertEqual(k.WaitForSingleObject(handle,1000),0)
            self.assertTrue(a.shutdown_status['clean']);self.assertTrue(a.shutdown_status['ownership']['group_empty'])
            self.assertEqual(a.shutdown_status['ownership']['active_processes'],0)
            self.assertTrue(a.shutdown_status['ownership']['reaped']);self.assertFalse(a.thread.is_alive())
        finally:
            a.close()
            if handle:k.CloseHandle(handle)
            td.cleanup()

    def test_blocked_response_pipe_closes_with_original_expired_action(self):
        td,a,o,context,birth,nonce=self.make();handle=None
        try:
            a.reset(context);a.process.wait(timeout=2)
            row=self.birth(birth,nonce);k,handle=self.handle(row['pid'])
            o['wall_deadline']=time.perf_counter()+.04;started=time.perf_counter()
            with self.assertRaises(Exception) as raised:a.act(o)
            self.assertIsNotNone(a.shutdown_status,str(raised.exception))
            self.assertLess(time.perf_counter()-started,1.65)
            # Job accounting can reach zero before a separately retained
            # synchronization handle is signalled by asynchronous termination.
            self.assertEqual(k.WaitForSingleObject(handle,1000),0)
            self.assertTrue(a.shutdown_status['clean']);self.assertFalse(a.thread.is_alive())
        finally:
            a.close()
            if handle:k.CloseHandle(handle)
            td.cleanup()

    def test_job_assignment_failure_never_executes_child(self):
        from rm_match.deployment import windows_owned_job as job
        td,a,o,context,birth,nonce=self.make()
        try:
            with patch.object(job,'_assign',side_effect=OSError('fixture forced job assignment refusal')):
                with self.assertRaises(job.OwnedLaunchFailure):a.reset(context)
            self.assertFalse(birth.exists())
            a.close();proof=a.shutdown_status['ownership']
            self.assertTrue(proof['clean']);self.assertTrue(proof['reaped']);self.assertTrue(proof['group_empty'])
            self.assertFalse(proof['not_spawned']) # suspended OS process existed; argv never executed
        finally:a.close();td.cleanup()

    def test_cancel_after_assignment_is_observed_before_resume(self):
        from rm_match.deployment import windows_owned_job as job
        td,a,o,context,birth,nonce=self.make();errors=[];assigned=threading.Event();original=job._assign
        def pause(k,j,p):
            original(k,j,p);assigned.set()
            self.assertTrue(a._cancelled.wait(1.))
        def reset():
            try:a.reset(context)
            except Exception as exc:errors.append(exc)
        try:
            with patch.object(job,'_assign',side_effect=pause):
                thread=threading.Thread(target=reset);thread.start()
                self.assertTrue(assigned.wait(1.));a.close();thread.join(1.)
            self.assertFalse(thread.is_alive());self.assertEqual(len(errors),1)
            self.assertFalse(birth.exists());self.assertTrue(a.shutdown_status['clean'])
            self.assertTrue(a.shutdown_status['ownership']['group_empty'])
        finally:a.close();td.cleanup()

    def test_uncertain_job_members_cannot_be_reported_clean(self):
        td,a,o,context,birth,nonce=self.make(leader_exit=False)
        try:
            a.reset(context);self.birth(birth,nonce);owner=a._owned_process.owner
            with patch.object(owner,'active_processes',return_value=1):
                with self.assertRaisesRegex(RuntimeError,'cleanup unproved'):a.close()
            self.assertFalse(a.shutdown_status['clean']);self.assertFalse(a.shutdown_status['ownership']['group_empty'])
            self.assertIsNotNone(owner.returncode)
            with self.assertRaises(RuntimeError):a.close() # failed proof remains sticky
        finally:
            try:a.close()
            except RuntimeError:pass
            td.cleanup()

    def test_job_close_does_not_touch_separately_spawned_process(self):
        outside=subprocess.Popen([sys.executable,'-c','import time;time.sleep(5)'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        td,a,o,context,birth,nonce=self.make()
        try:
            a.reset(context);self.birth(birth,nonce);a.close()
            self.assertIsNone(outside.poll())
        finally:a.close();outside.terminate();outside.wait(timeout=2);td.cleanup()

    @unittest.skipUnless(sys.platform=='win32','Actual Windows owned handle failure check')
    def test_handle_close_failure_does_not_skip_io_thread_cleanup(self):
        td,a,o,context,birth,nonce=self.make();handle=None
        try:
            a.reset(context);row=self.birth(birth,nonce);owner=a._owned_process.owner
            k,handle=WindowsJobTests.handle(self,row['pid'])
            original=owner.release_handles
            def fail_after_close():
                original();raise OSError('fixture handle release error')
            with patch.object(owner,'release_handles',side_effect=fail_after_close):
                with self.assertRaisesRegex(RuntimeError,'owned_handle_close'):a.close()
            self.assertFalse(a.shutdown_status['clean']);self.assertTrue(a.shutdown_status['ownership']['group_empty'])
            self.assertTrue(a.shutdown_status['io_thread_stopped'])
            self.assertEqual(k.WaitForSingleObject(handle,1000),0)
        finally:
            try:a.close()
            except RuntimeError:pass
            if handle:k.CloseHandle(handle)
            td.cleanup()

    def test_closed_adapter_cannot_late_reset_or_spawn(self):
        td,a,o,context,birth,nonce=self.make()
        try:
            a.close()
            with self.assertRaisesRegex(Exception,'cannot_restart'):a.reset(context)
            self.assertFalse(birth.exists());self.assertIsNone(a.process)
        finally:a.close();td.cleanup()

    def test_io_thread_start_failure_still_reclaims_owned_job(self):
        td,a,o,context,birth,nonce=self.make()
        try:
            with patch.object(threading.Thread,'start',side_effect=RuntimeError('fixture IO thread start refused')):
                with self.assertRaisesRegex(RuntimeError,'IO thread start refused'):a.reset(context)
            self.assertTrue(a.shutdown_status['clean']);self.assertTrue(a.shutdown_status['ownership']['group_empty'])
            self.assertTrue(a.shutdown_status['ownership']['reaped']);self.assertTrue(a.shutdown_status['io_thread_stopped'])
        finally:a.close();td.cleanup()

class LaunchProofTests(_Fixture,unittest.TestCase):
    """Injected POSIX launch failure states, not actual Linux process evidence."""
    def test_failed_attach_and_failed_inspection_proof_reach_adapter_close(self):
        from rm_match.deployment import json_owned_process as owned
        for inspection_raises in (False,True):
            with self.subTest(inspection_raises=inspection_raises):
                td,a,o,context,birth,nonce=self.make()
                child=SimpleNamespace(stdin=None,stdout=None)
                class Owner:
                    child=None
                    def attach(self,process):
                        self.child=process;raise RuntimeError('fixture attach identity rejection')
                    def cleanup_until(self,deadline):
                        if inspection_raises:raise OSError('fixture group inspection unavailable')
                        return dict(clean=False,reaped=False,not_spawned=False,group_empty=False,
                            errors=['fixture original owned-group failure'])
                try:
                    with patch.object(owned.sys,'platform','linux'),patch.object(owned,'_LinuxAdapterGroup',Owner),patch.object(owned.subprocess,'Popen',return_value=child):
                        with self.assertRaises(owned.OwnedJsonLaunchFailure) as caught:a.reset(context)
                    proof=caught.exception.cleanup_status
                    self.assertFalse(proof['clean']);self.assertFalse(proof['group_empty'])
                    self.assertFalse(proof['not_spawned']);self.assertFalse(birth.exists())
                    with self.assertRaisesRegex(RuntimeError,'launch cleanup unproved'):a.close()
                    self.assertEqual(a.shutdown_status['ownership'],proof);self.assertFalse(a.shutdown_status['clean'])
                finally:
                    try:a.close()
                    except RuntimeError:pass
                    td.cleanup()

    def test_posix_no_spawn_is_distinct_from_reaped(self):
        from rm_match.deployment import json_owned_process as owned
        td,a,o,context,birth,nonce=self.make()
        class Owner:
            child=None
            def cleanup_until(self,deadline):
                return dict(clean=True,reaped=False,not_spawned=True,group_empty=True,errors=[])
        try:
            with patch.object(owned.sys,'platform','linux'),patch.object(owned,'_LinuxAdapterGroup',Owner),patch.object(owned.subprocess,'Popen',side_effect=OSError('fixture launch refused')):
                with self.assertRaises(owned.OwnedJsonLaunchFailure):a.reset(context)
            a.close();self.assertTrue(a.shutdown_status['clean'])
            self.assertTrue(a.shutdown_status['ownership']['not_spawned']);self.assertFalse(a.shutdown_status['ownership']['reaped'])
        finally:a.close();td.cleanup()

    def test_cancel_during_posix_launch_retains_reaped_group_proof(self):
        from rm_match.deployment import json_owned_process as owned
        td,a,o,context,birth,nonce=self.make();child=SimpleNamespace(stdin=None,stdout=None)
        class Owner:
            child=None
            def attach(self,process):self.child=process
            def cleanup_until(self,deadline):
                return dict(clean=True,reaped=True,not_spawned=False,group_empty=True,errors=[],fixture_only=True)
        def spawn(*args,**kwargs):a._cancelled.set();return child
        try:
            with patch.object(owned.sys,'platform','linux'),patch.object(owned,'_LinuxAdapterGroup',Owner),patch.object(owned.subprocess,'Popen',side_effect=spawn):
                with self.assertRaises(owned.OwnedJsonLaunchFailure):a.reset(context)
            a.close();self.assertTrue(a.shutdown_status['clean'])
            self.assertFalse(a.shutdown_status['ownership']['not_spawned']);self.assertTrue(a.shutdown_status['ownership']['reaped'])
            self.assertFalse(birth.exists())
        finally:a.close();td.cleanup()


@unittest.skipUnless(sys.platform=='linux' and os.environ.get('POLAR_TEST_JSON_OWNED_POSIX')=='1',
                     'Explicit actual Linux owned JSON process fixture window')
class LinuxGroupTests(_Fixture,unittest.TestCase):
    def test_exited_leader_term_ignoring_child_is_killed_and_reaped(self):
        td,a,o,context,birth,nonce=self.make()
        try:
            a.reset(context);a.process.wait(timeout=2);row=self.birth(birth,nonce)
            self.assertTrue(Path('/proc/%d'%row['pid']).exists());a.close()
            self.assertFalse(Path('/proc/%d'%row['pid']).exists())
            proof=a.shutdown_status['ownership'];self.assertTrue(proof['clean']);self.assertTrue(proof['group_empty'])
            self.assertTrue(proof['reaped']);self.assertTrue(proof['killed']);self.assertFalse(a.thread.is_alive())
        finally:a.close();td.cleanup()

    def test_blocked_pipe_action_preserves_deadline_and_bounded_cleanup(self):
        td,a,o,context,birth,nonce=self.make()
        try:
            a.reset(context);a.process.wait(timeout=2);row=self.birth(birth,nonce)
            o['wall_deadline']=time.perf_counter()+.04;started=time.perf_counter()
            with self.assertRaises(Exception):a.act(o)
            self.assertLess(time.perf_counter()-started,1.65)
            self.assertFalse(Path('/proc/%d'%row['pid']).exists());self.assertTrue(a.shutdown_status['clean'])
        finally:a.close();td.cleanup()
