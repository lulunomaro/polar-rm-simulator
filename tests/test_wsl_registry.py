"""Prepared ownership/cancellation races; fake bridge, never WSL or native runs."""
from contextlib import contextmanager
import os
from pathlib import Path
import runpy
import threading
import time
import unittest
from unittest.mock import patch

from rm_match.deployment.wsl_registry import WslRegistry
from rm_match.deployment.wsl_profile import validate_wsl_spec
from rm_match.platform_v2.contracts import ContractError

fixture=runpy.run_path(str(Path(__file__).with_name('test_wsl_profile.py')))['fixture']
CONTEXT={'episode':1,'robot_id':'red_sentry','binding_epoch':1}


class Bridge:
    instances=[];entered=None;release=None;startup_error=False;constructor_entered=None;constructor_release=None
    def __init__(self,*args,**kwargs):
        self.stopped=False;self.closed=False;self.reset_count=0;self.controls=[];self.instances.append(self)
        if self.constructor_entered is not None:self.constructor_entered.set();self.constructor_release.wait(3.)
    def reset(self,*args):
        self.reset_count+=1
        if self.entered is not None:self.entered.set();self.release.wait(3.)
        if self.startup_error:raise RuntimeError('synthetic startup failed')
    def request_stop(self):self.stopped=True
    def close(self):self.closed=True
    def control(self,packet):self.controls.append(packet);return {'status':'synthetic'}


@contextmanager
def registry_fixture():
    Bridge.instances=[];Bridge.entered=None;Bridge.release=None;Bridge.startup_error=False
    Bridge.constructor_entered=None;Bridge.constructor_release=None
    with fixture() as f:
        checked=validate_wsl_spec(f['spec_path'],repo_root=f['repo'],shared_out=f['out'])
        registry=WslRegistry(checked,f['out'],'Ubuntu',None)
        with patch('rm_match.integrations.wsl_operator.WslOperatorProcess',Bridge):
            try:yield f,checked,registry
            finally:
                if Bridge.release is not None:Bridge.release.set()
                if Bridge.constructor_release is not None:Bridge.constructor_release.set()
                registry.close()
                if registry.native_instance is not None:registry.native_instance.cancel();registry.native_instance.close()


@unittest.skipUnless(os.name=='nt','WSL opt-in is Windows-host only')
class WslRegistryTests(unittest.TestCase):
    def test_prepared_single_handover_preserves_process_on_first_reset(self):
        with registry_fixture() as (_,_,registry):
            prepared=registry.prepare_native();process=prepared.process
            self.assertEqual(process.reset_count,1)
            first=registry.create('aim_native_rmcs_v1',{})
            self.assertIs(first,prepared);self.assertIsNone(registry._prepared)
            first.reset(CONTEXT)
            self.assertIs(first.process,process);self.assertFalse(process.closed)
            second=registry.create('aim_native_rmcs_v1',{})
            self.assertIsNot(second,first);self.assertIsNone(second.process)
            first.cancel();first.close();second.cancel();second.close()

    def test_later_generation_closes_then_recreates_with_full_startup_guard(self):
        with registry_fixture() as (_,checked,registry),patch.object(type(checked),'verify_unchanged',autospec=True,return_value='checked') as verify:
            adapter=registry.prepare_native();adapter=registry.create('aim_native_rmcs_v1',{})
            old=adapter.process;adapter.reset(CONTEXT)
            count=verify.call_count
            adapter._native_control({'frame':{}},{'wall_deadline':123.456})
            self.assertEqual(verify.call_count,count)
            self.assertEqual(old.controls[-1]['host_deadline'],123.456)
            adapter.reset(dict(CONTEXT,binding_epoch=2));self.assertTrue(old.closed);self.assertIsNone(adapter.process)
            adapter._start_process(1)
            self.assertGreater(verify.call_count,count);self.assertIsNot(adapter.process,old)
            with self.assertRaisesRegex(ContractError,'already_started'):adapter._start_process(1)

    def test_unclaimed_preload_closes_and_closed_registry_cannot_revive(self):
        with registry_fixture() as (_,_,registry):
            prepared=registry.prepare_native();process=prepared.process;registry.close()
            self.assertTrue(process.closed);self.assertTrue(process.stopped)
            with self.assertRaisesRegex(ContractError,'registry_closed'):registry.create('aim_native_rmcs_v1',{})
            with self.assertRaisesRegex(ContractError,'registry_closed'):registry.prepare_native()
            self.assertEqual(len(Bridge.instances),1)

    def test_preparation_error_is_cancelled_closed_and_not_claimable(self):
        with registry_fixture() as (_,_,registry):
            Bridge.startup_error=True
            with self.assertRaisesRegex(RuntimeError,'startup failed'):registry.prepare_native()
            self.assertIsNone(registry._prepared);self.assertFalse(registry._preparing)
            self.assertTrue(Bridge.instances[0].closed);self.assertTrue(Bridge.instances[0].stopped)

    def test_close_cancels_inflight_prepare_without_waiting_for_startup_lock(self):
        with registry_fixture() as (_,_,registry):
            Bridge.entered=threading.Event();Bridge.release=threading.Event();errors=[]
            def prepare():
                try:registry.prepare_native()
                except Exception as exc:errors.append(exc)
            thread=threading.Thread(target=prepare);thread.start()
            try:
                self.assertTrue(Bridge.entered.wait(2.))
                with self.assertRaisesRegex(ContractError,'preparation_in_progress'):registry.create('aim_native_rmcs_v1',{})
                before=time.perf_counter();registry.close();self.assertLess(time.perf_counter()-before,.2)
                self.assertTrue(Bridge.instances[0].stopped)
                Bridge.release.set();thread.join(2.)
                self.assertFalse(thread.is_alive());self.assertEqual(len(errors),1)
                self.assertTrue(Bridge.instances[0].closed);self.assertIsNone(registry._prepared)
            finally:Bridge.release.set();thread.join(3.)

    def test_cancel_between_constructor_and_publication_closes_late_wrapper(self):
        with registry_fixture() as (_,_,registry):
            Bridge.constructor_entered=threading.Event();Bridge.constructor_release=threading.Event();errors=[]
            def prepare():
                try:registry.prepare_native()
                except Exception as exc:errors.append(exc)
            thread=threading.Thread(target=prepare);thread.start()
            try:
                self.assertTrue(Bridge.constructor_entered.wait(2.));registry.close()
                Bridge.constructor_release.set();thread.join(2.)
                self.assertFalse(thread.is_alive());self.assertEqual(len(errors),1)
                self.assertEqual(Bridge.instances[0].reset_count,0)
                self.assertTrue(Bridge.instances[0].stopped);self.assertTrue(Bridge.instances[0].closed)
            finally:Bridge.constructor_release.set();thread.join(3.)

    def test_source_spec_and_host_snapshot_swaps_refuse_handover_and_close_preload(self):
        for selected in ('linux','host'):
            with self.subTest(selected=selected),registry_fixture() as (f,_,registry):
                adapter=registry.prepare_native();process=adapter.process
                path=f['spec_path'] if selected=='linux' else adapter.spec_path
                path.write_bytes(path.read_bytes()+b' ')
                with self.assertRaisesRegex(ContractError,'changed_after_registration'):registry.create('aim_native_rmcs_v1',{})
                self.assertTrue(process.stopped);self.assertTrue(process.closed);self.assertIsNone(registry._prepared)

    def test_spec_swap_between_handover_and_first_reset_is_rejected(self):
        with registry_fixture() as (f,_,registry):
            adapter=registry.prepare_native();adapter=registry.create('aim_native_rmcs_v1',{})
            f['spec_path'].write_bytes(f['spec_path'].read_bytes()+b' ')
            with self.assertRaisesRegex(ContractError,'changed_after_registration'):adapter.reset(CONTEXT)
            self.assertFalse(adapter._bound)

    def test_each_handover_boundary_hashes_both_specs_once_and_preserves_reset_guard(self):
        from rm_match.platform_v2.wsl_native_adapter import WslNativeSourceAdapter
        with registry_fixture() as (_,_,registry):
            adapter=registry.prepare_native()
            original=WslNativeSourceAdapter.spec_digest
            with patch.object(WslNativeSourceAdapter,'spec_digest',side_effect=original) as digest:
                adapter=registry.create('aim_native_rmcs_v1',{})
                self.assertEqual(digest.call_count,2)
                adapter.reset(CONTEXT)
                self.assertEqual(digest.call_count,4)

    def test_small_spec_hasher_matches_every_byte_and_rejects_unbounded_input(self):
        import hashlib
        from rm_match.platform_v2.wsl_native_adapter import WslNativeSourceAdapter
        with registry_fixture() as (f,_,_):
            path=f['out']/'hash-fixture'
            for size in (0,1,65535,65536,65537,1024*1024):
                data=(bytes(range(256))*(size//256+1))[:size];path.write_bytes(data)
                with self.subTest(size=size):self.assertEqual(WslNativeSourceAdapter.spec_digest(path),hashlib.sha256(data).hexdigest())
            path.write_bytes(bytes(1024*1024+1))
            with self.assertRaisesRegex(ContractError,'size_exceeded'):WslNativeSourceAdapter.spec_digest(path)

    def test_prepared_config_mismatch_closes_preload_and_bool_cannot_equal_numeric(self):
        with registry_fixture() as (_,_,registry):
            adapter=registry.prepare_native();process=adapter.process
            with self.assertRaisesRegex(ContractError,'config_mismatch'):registry.create('aim_native_rmcs_v1',{'fov_degrees':90.})
            self.assertTrue(process.stopped);self.assertTrue(process.closed)
            with self.assertRaises(ContractError):registry.create('aim_native_rmcs_v1',{'circle_radius_x_norm':True})

    def test_cancelled_prepared_instance_cannot_be_handed_over_or_reset(self):
        with registry_fixture() as (_,_,registry):
            adapter=registry.prepare_native();process=adapter.process;adapter.cancel()
            with self.assertRaisesRegex(ContractError,'cancelled'):registry.create('aim_native_rmcs_v1',{})
            self.assertTrue(process.closed)
            with self.assertRaisesRegex(ContractError,'cancelled'):adapter.reset(CONTEXT)

    def test_cancel_before_startup_creates_no_bridge(self):
        with registry_fixture() as (_,_,registry):
            adapter=registry.create('aim_native_rmcs_v1',{});adapter.cancel()
            with self.assertRaises(ContractError):adapter.prepare()
            self.assertEqual(Bridge.instances,[])

    def test_server_sensor_budget_reaches_bridge_without_refresh(self):
        from copy import deepcopy
        from rm_match.platform_v2.runtime import PlatformRuntime
        from rm_match.platform_v2.test_runtime import FakeBackend
        from rm_match.platform_v2.test_control import Clock
        from rm_match.platform_v2.test_contracts import sample
        class Camera:
            max_views=1
            def sensor_packet(self,*args):
                camera=deepcopy(sample(True)['sensors']['camera']);camera['capture_sim_time']=0.
                return dict(camera=camera,budget=dict(capture_wall=1000.,wall_deadline=1000.08,capture_sim_time=0.,sim_deadline=.2))
            def stop(self):pass
            def status(self):return {}
        class Slot:
            lifecycle_error=None
            def __init__(self,*args):self.jobs=[]
            def submit(self,job):self.jobs.append(job)
            def close(self):pass
        with registry_fixture() as (_,_,registry):
            adapter=registry.prepare_native();adapter=registry.create('aim_native_rmcs_v1',{});adapter.reset(CONTEXT)
            clock=Clock();clock.advance(.03);backend=FakeBackend(ids=('red_sentry',))
            runtime=PlatformRuntime(backend,registry=registry,camera=Camera(),clock=clock);runtime._episode=backend.episode
            try:
                token=runtime.control.open_session('operator')['token'];epochs=runtime.control.claim(token,'red_sentry',['gimbal'])['lease_epochs']
                runtime.bind(token,'red_sentry','aim',epochs,'aim_native_rmcs_v1',{})
                with patch('rm_match.platform_v2.runtime.AdapterSlot',Slot):runtime._schedule(runtime.control.snapshot(),backend.sim_time)
                job=runtime.slots['red_sentry','aim'].jobs[0]
                self.assertEqual(job['observation']['wall_deadline'],1000.08)
                self.assertEqual(job['sensor_budget']['sim_deadline'],.08)
                adapter._native_control({'frame':{}},job['observation'])
                self.assertEqual(adapter.process.controls[-1]['host_deadline'],1000.08)
                self.assertNotEqual(adapter.process.controls[-1]['host_deadline'],clock()+.08)
            finally:runtime.close()


if __name__=='__main__':unittest.main()
