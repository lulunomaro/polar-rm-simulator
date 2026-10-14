"""CPU fixtures only: private pixels, public JSON, revocation and original ages."""
import base64
from collections import OrderedDict
from copy import deepcopy
from dataclasses import FrozenInstanceError,replace
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np

from .camera import CameraProvider,Capture
from .native_camera_snapshot import NativeCameraSnapshot,mint_native_snapshot,is_native_snapshot
from .native_observation import validate_native_observation,raw_native_observation,reviewed_native_instance,NATIVE_SCHEMA
from .contracts import ContractError,validate_observation,action_for
from .native_adapter import NativeSourceAdapter
from .runtime import AdapterSlot,PlatformRuntime
from .adapters import Registry,descriptor
from .test_contracts import sample
from .test_control import Clock
from .test_runtime import FakeBackend
from ..telemetry import TimingLedger

RID='red_sentry'
C=('adapter',RID,'aim','owner',1)


def fixture():
    o=sample(True);o['robot_id']=RID
    cam=o['sensors']['camera'];raw=base64.b64decode(cam['image']['data_base64'])
    pixels=mint_native_snapshot(raw,robot_id=RID,episode=o['episode'],frame_id=cam['frame_id'],
        capture_wall=1000.,capture_sim_time=cam['capture_sim_time'],consumers=frozenset((C,)),
        **{k:cam['image'][k] for k in ('width','height','stride_bytes')},
        own={k:cam[k] for k in ('own_qpos_at_capture','own_qvel_at_capture','own_odom_at_capture','own_odom_velocity_at_capture')},
        intrinsics=cam['intrinsics'],extrinsics=cam['extrinsics'])
    o['sensors']['camera']=dict(available=False,reason='calibrated_camera_unavailable')
    o['wall_deadline']=1000.08
    budget=dict(robot_id=RID,episode=1,frame_id=1,capture_wall=1000.,capture_sim_time=1.,wall_deadline=1000.08,sim_deadline=1.08)
    return o,pixels,budget


def provider_fixture():
    """Tiny real numpy renderer output; no MuJoCo context or native process."""
    base,pixels,budget=fixture();cam=pixels.metadata()
    p=object.__new__(CameraProvider);clock=Clock()
    p.clock=clock;p.lock=threading.Lock();p.wake=threading.Event();p.stopped=threading.Event()
    p.episode=1;p.ttl=.2;p.profile=SimpleNamespace(width=16,height=12);p.max_views=1
    p.enable_native_pixels=True;p.native_pixels_hook=None;p.error=None;p.display_error='fixture_no_display'
    p.cache={};p.native_cache={};p.display_cache={};p.display_pending=OrderedDict();p.pending=OrderedDict()
    p.free=[];p.running=False;p.raw_published=0;p.dropped=0;p.thread=None;p.display_thread=None
    p.display_wake=threading.Event();p.renderer_identity=None
    p.timings=TimingLedger(('renderer_init','render_queue_wait','render_total','raw_encode','capture_to_raw','capture_to_private_pixels'))
    p.desired={RID:frozenset((C,))};p.calibrations={RID:dict(intrinsics=cam['intrinsics'],extrinsics=cam['extrinsics'])}
    p.rgb=np.frombuffer(pixels.raw_bytes,np.uint8).reshape(12,16,3).copy()
    class Renderer:
        identity={'renderer':'unit_numpy_fixture'};last_timings={}
        def render(self,cap):return p.rgb
        def close(self):pass
    p.model=None;p.renderer_factory=lambda *a:Renderer()
    p.status=lambda:dict(available=not p.stopped.is_set() and not p.error,reason='tiny_CPU_unit_fixture')
    cap=Capture(RID,1,1,1.,1000.,frozenset((C,)),object(),{k:cam[k] for k in ('own_qpos_at_capture','own_qvel_at_capture','own_odom_at_capture','own_odom_velocity_at_capture')},())
    p.pending[RID]=cap
    return p,clock,base,budget


class NativeSnapshotTests(unittest.TestCase):
    def test_private_schema_same_bytes_and_detached_metadata(self):
        base,p,b=fixture();envelope=validate_native_observation(base,p,consumer=C,budget=b,now=1000.01)
        self.assertEqual(envelope.schema,NATIVE_SCHEMA)
        self.assertFalse(envelope.base['sensors']['camera']['available'])
        raw=raw_native_observation(envelope)
        self.assertEqual(raw.rgb.tobytes(),p.raw_bytes);self.assertFalse(raw.rgb.flags.writeable)
        self.assertNotIn('data_base64',p.metadata()['image'])
        self.assertNotIn('NativeCamera',json.dumps(envelope.base))
        base['own']['qpos'][0]=44.;self.assertEqual(envelope.base['own']['qpos'][0],0.)
        metadata=p.metadata();metadata['intrinsics']['fx']=99.;self.assertEqual(p.intrinsics[0],10.)
        with self.assertRaises(FrozenInstanceError):p.frame_id=3
        with self.assertRaises(TypeError):NativeCameraSnapshot(raw_bytes=p.raw_bytes)
        with self.assertRaises(ContractError):validate_observation(dict(envelope.base,native_pixels=p))
        with self.assertRaises(TypeError):json.dumps(p)

    def test_forgery_context_budget_and_both_deadlines(self):
        base,p,b=fixture()
        fake=object.__new__(NativeCameraSnapshot)
        self.assertFalse(is_native_snapshot(fake))
        with self.assertRaises(ContractError):validate_native_observation(base,fake,consumer=C,budget=b,now=1000.)
        for key,value in [('robot_id','blue_sentry'),('episode',2),('binding_epoch',2),('sim_time',1.081),('sim_time',.999)]:
            o=deepcopy(base);o[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ContractError):validate_native_observation(o,p,consumer=C,budget=b,now=1000.01)
        for now in (999.999,1000.08,1000.081):
            with self.subTest(now=now),self.assertRaises(ContractError):validate_native_observation(base,p,consumer=C,budget=b,now=now)
        for key,value in [('frame_id',2),('episode',True),('capture_wall',1000.01),('capture_sim_time',True),('capture_sim_time',1.01)]:
            budget=dict(b);budget[key]=value
            with self.subTest(key=key),self.assertRaises(ContractError):validate_native_observation(base,p,consumer=C,budget=budget,now=1000.01)
        with self.assertRaises(ContractError):validate_native_observation(base,p,consumer=(*C[:4],2),budget=b,now=1000.01)
        with self.assertRaises(ContractError):validate_native_observation(base,p,consumer=(*C[:4],True),budget=b,now=1000.01)
        o=deepcopy(base);o['wall_deadline']=1000.005
        with self.assertRaises(ContractError):validate_native_observation(o,p,consumer=C,budget=b,now=1000.006)

    def test_factory_bad_shape_calibration_time_and_truth_rejected(self):
        base,p,b=fixture();m=p.metadata()
        kw=dict(robot_id=RID,episode=1,frame_id=1,capture_wall=1000.,capture_sim_time=1.,consumers=frozenset((C,)),
            width=16,height=12,stride_bytes=48,own={k:m[k] for k in ('own_qpos_at_capture','own_qvel_at_capture','own_odom_at_capture','own_odom_velocity_at_capture')},intrinsics=m['intrinsics'],extrinsics=m['extrinsics'])
        for update in [dict(width=True),dict(height=13),dict(stride_bytes=49),dict(capture_sim_time=float('nan')),
                       dict(intrinsics={**m['intrinsics'],'enemy_xy':[0.,0.]}),dict(extrinsics={**m['extrinsics'],'rotation_xyzw':[0.]*4}),
                       dict(own={**kw['own'],'enemy_id':9})]:
            with self.subTest(update=update),self.assertRaises(ContractError):mint_native_snapshot(p.raw_bytes,**{**kw,**update})


class EarlyPublicationTests(unittest.TestCase):
    def run_blocked(self,operation=None):
        p,clock,base,budget=provider_fixture();entered=threading.Event();release=threading.Event();events=[];raw_inputs=[]
        original=CameraProvider._encode
        def blocked(cap,rgb,*,raw_bytes=None):
            raw_inputs.append(raw_bytes);entered.set()
            if not release.wait(2.):raise RuntimeError('unit_encoder_timeout')
            return original(p,cap,rgb,raw_bytes=raw_bytes)
        p._encode=blocked;p.native_pixels_hook=events.append
        p.thread=threading.Thread(target=p._loop);p.thread.start()
        try:
            self.assertTrue(entered.wait(1.))
            packet=p.native_sensor_packet(RID,1,C,1.,.2)
            self.assertIsNotNone(packet['pixels'])
            self.assertIs(packet['pixels'].raw_bytes,raw_inputs[0])
            self.assertFalse(p.sensor_camera(RID,1,C,1.,.2)['available'])
            self.assertEqual(events[0]['event'],'private_pixels_published')
            self.assertEqual(set(p.native_cache),{RID})
            if operation:operation(p,clock,packet)
            else:
                p.rgb[:]=0
                release.set()
                # Small bounded completion wait is a unit synchronization, not a benchmark.
                for _ in range(200):
                    with p.lock:complete=RID in p.cache
                    if complete:break
                    threading.Event().wait(.002)
                self.assertTrue(complete)
                public=p.sensor_camera(RID,1,C,1.,.2)
                self.assertEqual(base64.b64decode(public['image']['data_base64']),packet['pixels'].raw_bytes)
                self.assertIs(p.cache[RID]['pixel_token'].raw_bytes,packet['pixels'].raw_bytes)
                self.assertEqual([x['event'] for x in events],['private_pixels_published','public_base64_complete'])
                self.assertNotIn('pixels',public)
        finally:release.set();p.stop();self.assertTrue(p.wait_closed(2.))

    def test_private_early_public_waits_and_one_actual_copy(self):self.run_blocked()

    def test_fault_reset_release_and_stop_during_encoding(self):
        for mode in ('fault','reset','release','consumer_generation','stop','wall_expired','sim_expired'):
            def operation(p,clock,packet):
                if mode=='fault':p.fault('injected_unit_fault')
                elif mode=='reset':
                    with p.lock:p._reset_locked(2)
                elif mode=='release':
                    with p.lock:p.desired={}
                elif mode=='consumer_generation':
                    with p.lock:p.desired={RID:frozenset(((*C[:4],2),))}
                elif mode=='stop':p.stop()
                elif mode=='wall_expired':clock.advance(.081)
                sim=1.081 if mode=='sim_expired' else 1.
                self.assertIsNone(p.native_sensor_packet(RID,1,C,sim,.2)['pixels'])
                self.assertFalse(p.native_capture_valid(RID,1,C,packet['budget'],sim))
            with self.subTest(mode=mode):self.run_blocked(operation)

    def test_disabled_does_not_expose_private_cache(self):
        p,clock,base,b=provider_fixture();p.enable_native_pixels=False
        self.assertIsNone(p.native_sensor_identity(RID,1,C,1.,.2))
        self.assertEqual(p.native_sensor_packet(RID,1,C,1.,.2),dict(pixels=None,budget=None))

    def test_one_latest_private_frame_and_expired_render_not_published(self):
        p,clock,base,b=provider_fixture();cap=p.pending[RID]
        p._publish_native_pixels(cap,p.rgb)
        old=p.native_cache[RID]['pixels']
        p._publish_native_pixels(replace(cap,frame_seq=2),p.rgb)
        self.assertEqual(len(p.native_cache),1)
        self.assertEqual(p.native_sensor_identity(RID,1,C,1.,.2)[0],2)
        self.assertEqual(old.frame_id,1)
        clock.advance(.081)
        p._publish_native_pixels(replace(cap,frame_seq=3),p.rgb)
        self.assertEqual(p.native_cache[RID]['pixels'].frame_id,2)
        self.assertIsNone(p.native_sensor_identity(RID,1,C,1.,.2))

    def test_publication_stamp_precedes_late_hook_and_hook_never_holds_lock(self):
        p,clock,base,b=provider_fixture();events=[]
        def hook(row):
            acquired=p.lock.acquire(blocking=False)
            self.assertTrue(acquired)
            if acquired:p.lock.release()
            events.append(row)
        p.native_pixels_hook=hook
        p.timings.record=lambda *args:clock.advance(.004)
        p._publish_native_pixels(p.pending[RID],p.rgb)
        self.assertEqual(events[0]['wall_time'],1000.)
        self.assertEqual(clock(),1000.004)
        self.assertEqual(p.native_sensor_packet(RID,1,C,1.,.2)['budget']['capture_wall'],1000.)


class NativeSlotTests(unittest.TestCase):
    def test_exact_worker_private_entry_validates_without_decode_and_rechecks_revocation(self):
        base,p,b=fixture();instance=object.__new__(NativeSourceAdapter)
        instance.reset=lambda context:setattr(instance,'context',context)
        instance.close=lambda:None
        instance.cancel=lambda:None
        r=Registry();r.register(descriptor('aim_native_rmcs_v1','aim','CPU fixture',('camera',)),lambda _:instance)
        for valid in (True,False):
            slot=AdapterSlot(r,lambda:1000.01)
            action=action_for(base,'aim','gimbal_target',dict(frame='base_link',yaw_rad=0.,pitch_rad=0.,active=False,confidence=None,fire_permission=False))
            try:
                with (patch.object(NativeSourceAdapter,'_act_sensor',return_value=action) as native,
                      patch('rm_match.platform_v2.contracts.base64.b64decode',side_effect=AssertionError('no base64 in private path'))):
                    slot.submit(dict(kind='aim',binding=dict(epoch=1,adapter_id='aim_native_rmcs_v1',config={}),observation=base,
                        native_pixels=p,native_consumer=C,sensor_budget=b,native_camera_check=lambda:valid))
                    result=slot.results.get(timeout=1.)
                    self.assertEqual(native.call_count,int(valid))
                    if valid:
                        self.assertIsNone(result['error'])
                        self.assertEqual(native.call_args.kwargs['native_envelope'].schema,NATIVE_SCHEMA)
                        self.assertIs(native.call_args.kwargs['native_envelope'].pixels,p)
                    else:
                        self.assertIsNone(result['error'])
                        self.assertEqual(result['discarded_reason'],'authority_revoked_before_act')
            finally:slot.close();slot.thread.join(1.)

    def test_unknown_subclass_and_overridden_act_never_get_private_job(self):
        class UnknownNative(NativeSourceAdapter):
            def __init__(self):self.called=False;self.observation=None
            def reset(self,c):self.context=c
            def close(self):pass
            def act(self,o):
                self.called=True;self.observation=o
                return action_for(o,'aim','gimbal_target',dict(frame='base_link',yaw_rad=0.,pitch_rad=0.,active=False,confidence=None,fire_permission=False))
        instance=UnknownNative();r=Registry();r.register(descriptor('aim_native_rmcs_v1','aim','CPU fixture',('camera',)),lambda _:instance)
        slot=AdapterSlot(r,lambda:1000.01);base,p,b=fixture()
        try:
            slot.submit(dict(kind='aim',binding=dict(epoch=1,adapter_id='aim_native_rmcs_v1',config={}),observation=base,
                native_pixels=p,native_consumer=C,sensor_budget=b,native_camera_check=lambda:True))
            result=slot.results.get(timeout=1.)
            self.assertTrue(result['private_rejected']);self.assertIsNone(result['error']);self.assertFalse(instance.called)
            self.assertFalse(reviewed_native_instance(instance))
            public=sample(True);public['robot_id']=RID;public['wall_deadline']=1000.08
            slot.submit(dict(kind='aim',binding=dict(epoch=1,adapter_id='aim_native_rmcs_v1',config={}),observation=public))
            result=slot.results.get(timeout=1.)
            self.assertIsNone(result['error']);self.assertTrue(instance.called)
            self.assertIsNot(instance.observation,public)
            validate_observation(instance.observation)
            self.assertTrue(instance.observation['sensors']['camera']['available'])
            self.assertNotIn('native_pixels',instance.observation)
            self.assertIs(type(instance.observation['sensors']['camera']['image']['data_base64']),str)
        finally:slot.close();slot.thread.join(1.)

    def test_exact_native_entry_retains_camera_profile_and_context_checks(self):
        base,p,b=fixture();instance=object.__new__(NativeSourceAdapter);instance.context=dict(episode=1,robot_id=RID,binding_epoch=1)
        instance._cancelled=threading.Event()
        self.assertTrue(reviewed_native_instance(instance))
        # Synthetic 16x12 cannot pass production 1440x1080; no native is launched.
        with self.assertRaisesRegex(ContractError,'native_camera_resolution_mismatch'):
            NativeSourceAdapter._act_native_pixels(instance,base,p,consumer=C,budget=b,now=1000.01)
        instance.context['binding_epoch']=2
        with self.assertRaisesRegex(ContractError,'adapter_context_mismatch'):
            NativeSourceAdapter._act_native_pixels(instance,base,p,consumer=C,budget=b,now=1000.01)

    def test_numeric_but_wrong_production_calibration_rejected_without_process(self):
        from ..camera_profile import SourceCameraProfile
        base,p,b=fixture();profile=SourceCameraProfile();m=p.metadata()
        intr=dict(fx=profile.fx+1.,fy=profile.fy,cx=profile.cx,cy=profile.cy,
            distortion_model='brown_conrady_5',distortion=list(profile.distortion))
        pixels=mint_native_snapshot(bytes(profile.width*profile.height*3),robot_id=RID,episode=1,frame_id=1,
            capture_wall=1000.,capture_sim_time=1.,consumers=frozenset((C,)),width=profile.width,height=profile.height,
            stride_bytes=profile.width*3,own={k:m[k] for k in ('own_qpos_at_capture','own_qvel_at_capture','own_odom_at_capture','own_odom_velocity_at_capture')},
            intrinsics=intr,extrinsics=m['extrinsics'])
        instance=object.__new__(NativeSourceAdapter);instance.context=dict(episode=1,robot_id=RID,binding_epoch=1)
        instance._cancelled=threading.Event()
        with self.assertRaisesRegex(ContractError,'native_camera_calibration_mismatch'):
            NativeSourceAdapter._act_native_pixels(instance,base,pixels,consumer=C,budget=b,now=1000.01)


class CaptureSlot:
    lifecycle_error=None
    def __init__(self,*args):self.jobs=[];self.results=[]
    def submit(self,job):self.jobs.append(job)
    def poll(self):return self.results.pop(0) if self.results else None
    def close(self):pass


class RuntimePrivateTests(unittest.TestCase):
    def setup_runtime(self,*,enabled=True,adapter_id='aim_native_rmcs_v1'):
        p,clock,base,budget=provider_fixture();backend=FakeBackend(ids=(RID,));backend.episode=1;backend.sim_time=1.
        registry=Registry();registry.register(descriptor(adapter_id,'aim','CPU fixture',('camera','odometry'),
            stationary_only=True,schedule_on_camera_frame=True,max_camera_age_sim_s=.08,max_camera_age_wall_s=.08),lambda _:None)
        runtime=PlatformRuntime(backend,clock=clock,registry=registry,camera=p,enable_native_pixels=enabled)
        runtime._episode=1
        token=runtime.control.open_session('operator',control_profile='server_window_v1')['token']
        epochs=runtime.control.claim(token,RID,['gimbal'])['lease_epochs']
        binding=runtime.bind(token,RID,'aim',epochs,adapter_id,{})
        window=runtime.control.control_window(token,RID,epochs)
        runtime.control.adapter_input(token,RID,'aim',epochs,binding['binding_epoch'],0,window['window_id'],.15)
        b=runtime.control.snapshot()['bindings'][RID]['aim'];consumer=runtime._camera_binding(RID,'aim',b)
        cap=replace(p.pending.pop(RID),consumers=frozenset((consumer,)))
        p.desired={RID:cap.consumers};p._publish_native_pixels(cap,p.rgb)
        return runtime,p,clock,backend,cap,token,epochs

    def schedule(self,runtime,backend):
        with patch('rm_match.platform_v2.runtime.AdapterSlot',CaptureSlot):
            runtime._schedule(runtime.control.snapshot(),backend.sim_time)
        return runtime.slots.get((RID,'aim'))

    def result(self,slot,clock):
        job=slot.jobs[-1];o=job['observation']
        action=action_for(o,'aim','gimbal_target',dict(frame='base_link',yaw_rad=.2,pitch_rad=.1,active=True,confidence=None,fire_permission=False))
        slot.results.append(dict(job=job,value=action,error=None,completed=clock()))
        return action

    def test_early_job_separate_schema_default_disabled_and_other_id_public(self):
        runtime,p,clock,backend,cap,token,epochs=self.setup_runtime()
        try:
            slot=self.schedule(runtime,backend);job=slot.jobs[-1]
            self.assertIn('native_pixels',job)
            self.assertIs(validate_observation(job['observation'])['sensors']['camera']['available'],False)
            self.assertEqual(job['observation']['wall_deadline'],1000.08)
            self.assertEqual(job['sensor_budget']['sim_deadline'],1.08)
            self.assertNotIn('raw_bytes',json.dumps(job['observation']))
            self.schedule(runtime,backend);self.assertEqual(len(slot.jobs),1)
        finally:runtime.close()
        for enabled,aid in [(False,'aim_native_rmcs_v1'),(True,'custom_native')]:
            runtime,p,clock,backend,cap,token,epochs=self.setup_runtime(enabled=enabled,adapter_id=aid)
            try:
                self.assertIsNone(self.schedule(runtime,backend))
                p.cache[RID]=p._encode(cap,p.rgb)
                # The prior unavailable sensor used the ordinary observation period.
                clock.advance(.05);backend.sim_time+=.05
                slot=self.schedule(runtime,backend)
                self.assertNotIn('native_pixels',slot.jobs[-1]);self.assertTrue(slot.jobs[-1]['observation']['sensors']['camera']['available'])
            finally:runtime.close()

    def test_unknown_same_id_retries_full_public_without_sticky_fault(self):
        runtime,p,clock,backend,cap,token,epochs=self.setup_runtime()
        try:
            slot=self.schedule(runtime,backend);first=slot.jobs[-1]
            slot.results.append(dict(job=first,value=None,error=None,completed=clock(),private_rejected=True))
            runtime._collect(runtime.control.snapshot(),backend.sim_time)
            self.assertNotIn((RID,'aim'),runtime._fault_epochs)
            self.schedule(runtime,backend)
            self.assertEqual(len(slot.jobs),1,'Unknown class must wait for COMPLETE public encoding')
            p.cache[RID]=p._encode(cap,p.rgb,raw_bytes=first['native_pixels'].raw_bytes)
            clock.advance(.051);backend.sim_time+=.051
            self.schedule(runtime,backend)
            self.assertEqual(len(slot.jobs),2)
            self.assertNotIn('native_pixels',slot.jobs[-1])
            self.assertTrue(slot.jobs[-1]['observation']['sensors']['camera']['available'])
        finally:runtime.close()

    def test_fault_before_collect_and_after_collect_rejects_pending_and_consumption(self):
        for phase in ('before_collect','after_collect'):
            runtime,p,clock,backend,cap,token,epochs=self.setup_runtime()
            try:
                slot=self.schedule(runtime,backend);self.result(slot,clock)
                if phase=='before_collect':p.fault('unit_fault')
                runtime._collect(runtime.control.snapshot(),backend.sim_time)
                if phase=='before_collect':self.assertNotIn((RID,'aim'),runtime.outputs)
                else:
                    self.assertIsNotNone(runtime._targets(runtime.control.snapshot(),backend.sim_time)[RID]['gimbal'])
                    p.fault('unit_fault')
                self.assertIsNone(runtime._targets(runtime.control.snapshot(),backend.sim_time)[RID]['gimbal'])
            finally:runtime.close()

    def test_public_fault_also_rejects_new_actions_in_both_flag_modes(self):
        for enabled in (False,True):
            runtime,p,clock,backend,cap,token,epochs=self.setup_runtime(enabled=enabled,adapter_id='custom_native')
            try:
                p.cache[RID]=p._encode(cap,p.rgb)
                slot=self.schedule(runtime,backend);self.assertNotIn('native_pixels',slot.jobs[-1])
                self.result(slot,clock);p.fault('public_encode_failure')
                runtime._collect(runtime.control.snapshot(),backend.sim_time)
                self.assertNotIn((RID,'aim'),runtime.outputs)
                self.assertIsNone(runtime._targets(runtime.control.snapshot(),backend.sim_time)[RID]['gimbal'])
            finally:runtime.close()

    def test_old_capture_and_150ms_activation_never_get_restarted(self):
        runtime,p,clock,backend,cap,token,epochs=self.setup_runtime()
        try:
            clock.advance(.10);backend.sim_time=1.01
            cap=replace(cap,frame_seq=2,wall_time=clock(),sim_time=backend.sim_time)
            p._publish_native_pixels(cap,p.rgb)
            slot=self.schedule(runtime,backend);job=slot.jobs[-1]
            self.assertAlmostEqual(job['sensor_budget']['wall_deadline'],1000.18)
            self.assertAlmostEqual(job['observation']['wall_deadline'],1000.15)
            self.result(slot,clock);runtime._collect(runtime.control.snapshot(),backend.sim_time)
            self.assertIsNotNone(runtime._targets(runtime.control.snapshot(),backend.sim_time)[RID]['gimbal'])
            clock.advance(.051)
            self.assertIsNone(runtime._targets(runtime.control.snapshot(),backend.sim_time)[RID]['gimbal'])
        finally:runtime.close()


if __name__=='__main__':unittest.main()
