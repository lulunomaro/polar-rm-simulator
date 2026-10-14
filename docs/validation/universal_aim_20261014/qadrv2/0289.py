"""Shutdown bounds using owned harmless children; no native/GPU execution."""
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

from ..integrations.rmcs_process import RMCSProcess
from .adapters import BaseAdapter
from .contracts import ContractError
from .native_adapter import NativeSourceAdapter
from .offline_runtime import OfflineRuntime,OfflineWorker
from .runtime import AdapterSlot, PlatformRuntime
from .test_contracts import sample
from .test_runtime import FakeBackend


class RegistryFixture:
    def __init__(self,instance):self.instance=instance
    def create(self,*args):return self.instance
    def get(self,*args):return SimpleNamespace(descriptor={'kind':'aim','output_modes':['gimbal_target']})


def submit(slot):
    slot.submit(dict(binding={'adapter_id':'fixture','config':{},'epoch':1},kind='aim',observation=sample()))


class ReviewedNativeFixture(NativeSourceAdapter):
    """Exercise the real reviewed cancellation and close, without inference."""
    def __init__(self,process=None,reset_gate=None):
        self.process=process;self._cancelled=threading.Event();self._lifecycle_lock=threading.Lock()
        self.entered=threading.Event();self.reset_gate=reset_gate;self.acted=False
    def reset(self,context):
        if self._cancelled.is_set():raise ContractError('native_adapter_cancelled')
        BaseAdapter.reset(self,context)
        if self.reset_gate is not None:self.entered.set();self.reset_gate.wait(5.)
    def act(self,o):
        self.acted=True;self.entered.set()
        # readline can stall after select reports a partial line. Cancellation
        # must terminate the actual owned process, not merely set a Python flag.
        self.process.process.stdout.readline()
        raise RuntimeError('child_cancelled')


class SlotShutdownTests(unittest.TestCase):
    def test_blocking_owned_native_read_is_cancelled_reaped_and_pipes_closed(self):
        self.check_blocked_native('live')

    def test_offline_blocking_owned_native_read_is_cancelled_and_reaped(self):
        self.check_blocked_native('offline')

    def check_blocked_native(self,mode):
        with tempfile.TemporaryDirectory() as directory:
            actor=RMCSProcess(sys.executable,Path(directory)/'unused',directory,os.environ.copy())
            actor.stderr=(Path(directory)/'stderr').open('w');errorlog=actor.stderr
            code='import signal,time; '
            if os.name=='posix':code+='signal.signal(signal.SIGTERM,signal.SIG_IGN); '
            code+='print("ready",flush=True); time.sleep(60)'
            child=actor.process=subprocess.Popen([getattr(sys,'_base_executable',sys.executable),'-I','-c',code],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=actor.stderr,text=True,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.assertEqual(child.stdout.readline().strip(),'ready')
            native=ReviewedNativeFixture(actor)
            if mode=='offline':
                slot=OfflineWorker(lambda:native,{'robot_id':'red_infantry','episode':1,'binding_epoch':1})
            else:slot=AdapterSlot(RegistryFixture(native),lambda:0.)
            try:
                if mode=='offline':slot.submit(sample())
                else:submit(slot)
                self.assertTrue(native.entered.wait(2.))
                start=time.perf_counter();slot.close();slot.thread.join(1.5)
                self.assertLess(time.perf_counter()-start,1.6)
                self.assertFalse(slot.thread.is_alive());self.assertIsNone(slot.lifecycle_error)
                self.assertIsNotNone(child.poll());self.assertTrue(errorlog.closed)
                self.assertTrue(child.stdout.closed);self.assertTrue(child.stdin.closed)
                self.assertIsNone(native.process);self.assertIsNone(slot._instance)
            finally:
                if child.poll() is None:child.kill();child.wait(timeout=2.)
                slot.close();slot.thread.join(2.);actor.close()

    def test_late_reset_cannot_act_after_authority_cancel(self):
        release=threading.Event();native=ReviewedNativeFixture(reset_gate=release)
        slot=AdapterSlot(RegistryFixture(native),lambda:0.)
        try:
            submit(slot);self.assertTrue(native.entered.wait(2.));slot.close()
            release.set();slot.thread.join(1.)
            self.assertFalse(slot.thread.is_alive());self.assertFalse(native.acted)
            self.assertTrue(native._cancelled.is_set())
            with self.assertRaisesRegex(ContractError,'cancelled'):native.reset({'episode':1,'robot_id':'r','binding_epoch':1})
        finally:release.set();slot.close();slot.thread.join(2.)

    def test_cancel_during_popen_refuses_late_child_and_closes_owned_streams(self):
        entered=threading.Event();release=threading.Event()
        class Child:
            def __init__(self):
                import io
                self.stdin=io.StringIO();self.stdout=io.StringIO();self.stderr=None;self.dead=False
            def poll(self):return 0 if self.dead else None
            def terminate(self):self.dead=True
            def kill(self):self.dead=True
            def wait(self,timeout):return 0
        child=Child();errors=[]
        def late_popen(*args,**kwargs):entered.set();release.wait(3.);return child
        with tempfile.TemporaryDirectory() as directory:
            actor=RMCSProcess(sys.executable,Path(directory)/'unused',directory,{})
            def reset():
                try:actor.reset({})
                except Exception as exc:errors.append(str(exc))
            with patch('rm_match.integrations.rmcs_process.subprocess.Popen',late_popen):
                worker=threading.Thread(target=reset);worker.start()
                try:
                    self.assertTrue(entered.wait(1.));actor.request_stop();release.set();worker.join(1.)
                    self.assertFalse(worker.is_alive());self.assertTrue(child.dead)
                    self.assertEqual(errors,['RMCS transport cancelled during startup'])
                    self.assertIsNone(actor.process);self.assertIsNone(actor.stderr)
                    self.assertTrue(child.stdout.closed);self.assertTrue(child.stdin.closed)
                    with self.assertRaisesRegex(RuntimeError,'stopped'):actor.reset({})
                finally:release.set();worker.join(3.);actor.close()

    def test_actual_native_sensor_startup_cannot_recover_after_cancel(self):
        from .test_native_adapter import NativeTests
        helper=NativeTests();helper.setUp();entered=threading.Event();release=threading.Event();errors=[];processes=[]
        class Process:
            def __init__(self,*a,**kw):self.stopped=False;self.closed=False;self.controlled=False;processes.append(self)
            def reset(self,*a):entered.set();release.wait(3.)
            def request_stop(self):self.stopped=True
            def close(self):self.closed=True
            def control(self,*a):self.controlled=True;raise AssertionError('cancelled startup must never infer')
        adapter=helper.adapter();o=helper.observation();adapter.act(o)
        o['sim_time']=1.5;o['sensors']['camera'].update(capture_sim_time=1.5,frame_id=2)
        def act():
            try:adapter.act(o)
            except Exception as e:errors.append(e)
        try:
            with patch('rm_match.operator.source_aim.OperatorFovProcess',Process):
                worker=threading.Thread(target=act);worker.start()
                try:
                    self.assertTrue(entered.wait(2.));adapter.cancel();release.set();worker.join(2.)
                    self.assertFalse(worker.is_alive());self.assertEqual(len(errors),1)
                    self.assertIsInstance(errors[0],ContractError)
                    self.assertTrue(processes[0].stopped);self.assertTrue(processes[0].closed)
                    self.assertFalse(processes[0].controlled);self.assertIsNone(adapter.process)
                    with self.assertRaisesRegex(ContractError,'cancelled'):adapter.act(o)
                finally:release.set();worker.join(3.);adapter.close()
        finally:helper.tearDown()

    def test_offline_unknown_blocking_plugin_reports_resource_failure(self):
        release=threading.Event();entered=threading.Event()
        class Plugin:
            def reset(self,*a):pass
            def act(self,*a):entered.set();release.wait(5.);return None
            def close(self):pass
        runtime=OfflineRuntime(FakeBackend(ids=('r',)),camera=None,selected_robot='r',native_factory=Plugin)
        runtime.state='COMPLETED'
        runtime.worker=OfflineWorker(Plugin,{'episode':1,'robot_id':'r','binding_epoch':1})
        try:
            runtime.worker.submit(sample());self.assertTrue(entered.wait(1.))
            start=time.perf_counter();runtime.close();self.assertLess(time.perf_counter()-start,2.1)
            self.assertFalse(runtime.shutdown_status['clean'])
            self.assertEqual(runtime.shutdown_status['unfinished_slots'],[{'robot_id':'r','kind':'offline_aim'}])
            self.assertEqual(runtime.state,'HALTED');self.assertEqual(runtime.cached['offline_final_state'],'HALTED')
            self.assertEqual(runtime.error,'adapter_shutdown_incomplete')
            self.assertEqual(runtime.halt_reason,'resource_cleanup_incomplete')
        finally:release.set();runtime.worker.thread.join(2.)

    def test_offline_close_exception_is_preserved_as_lifecycle_failure(self):
        class Plugin:
            def reset(self,*a):pass
            def close(self):raise RuntimeError('failed fixture cleanup')
        runtime=OfflineRuntime(FakeBackend(ids=('r',)),camera=None,selected_robot='r',native_factory=Plugin)
        runtime.worker=OfflineWorker(Plugin,{'episode':1,'robot_id':'r','binding_epoch':1})
        runtime.close()
        self.assertFalse(runtime.shutdown_status['clean'])
        self.assertEqual(runtime.shutdown_status['lifecycle_errors'],[{'robot_id':'r','kind':'offline_aim','error':'RuntimeError'}])
        self.assertEqual(runtime.error,'adapter_shutdown_incomplete')

    def test_all_unknown_plugins_share_one_join_budget_and_report_unclean(self):
        release=threading.Event();instances=[]
        class Plugin:
            def __init__(self):self.entered=threading.Event();self.cancelled=False
            def reset(self,*args):pass
            def act(self,*args):self.entered.set();release.wait(5.);raise RuntimeError('fixture_released')
            def cancel(self):self.cancelled=True;release.wait(5.)
            def close(self):pass
        runtime=PlatformRuntime(FakeBackend(ids=('a','b','c')),clock=lambda:0.)
        for rid in runtime.backend.robot_ids:
            plugin=Plugin();instances.append(plugin)
            slot=AdapterSlot(RegistryFixture(plugin),lambda:0.);runtime.slots[rid,'aim']=slot;submit(slot)
        try:
            self.assertTrue(all(p.entered.wait(1.) for p in instances))
            start=time.perf_counter();runtime.close();elapsed=time.perf_counter()-start
            self.assertGreater(elapsed,1.35);self.assertLess(elapsed,2.1)
            self.assertFalse(runtime.shutdown_status['clean'])
            self.assertEqual(len(runtime.shutdown_status['unfinished_slots']),3)
            self.assertEqual(runtime.error,'adapter_shutdown_incomplete')
            self.assertTrue(all(not p.cancelled for p in instances))
            self.assertEqual(runtime.cached['runtime_state'],'error');self.assertTrue(runtime.backend.closed)
        finally:
            release.set()
            for slot in runtime.slots.values():slot.thread.join(2.)


if __name__=='__main__':unittest.main()
