"""Deterministic authority/sensor scheduling; no MuJoCo, image or HTTP run."""
import copy
import unittest
from .runtime import PlatformRuntime
from .adapters import default_registry
from .contracts import action_for
from .test_runtime import FakeBackend

class CapturedSlot:
    dropped=0;lifecycle_error=None
    def __init__(self):self.jobs=[];self.result=None
    def submit(self,job):self.jobs.append(copy.deepcopy(job))
    def poll(self):value=self.result;self.result=None;return value
    def close(self):pass

class FreshBackend(FakeBackend):
    def __init__(self):super().__init__(('r',));self.samples=[];self.sample_hook=None;self.stale=False
    def sensor_sample(self,rid):
        raw=super().sensor_sample(rid);self.samples.append((self.episode,self.sim_time))
        raw.odom_xyyaw=(self.sim_time,0.,0.)
        if self.stale:raw.sim_time=0.
        if self.sample_hook:self.sample_hook()
        return raw

class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.now=10.;self.backend=FreshBackend();self.events=[]
        self.runtime=PlatformRuntime(self.backend,clock=lambda:self.now,trace=self.events.append)
        self.runtime._episode=0;self.p=self.runtime.control
        self.token=self.p.open_session('operator','server_window_v1')['token']
        self.epochs=self.p.claim(self.token,'r',['motion'])['lease_epochs']
        self.binding=self.runtime.bind(self.token,'r','navigation',self.epochs,'nav_rule_v1',{'goal_world_m':[.75,0.]})
        self.slot=CapturedSlot();self.runtime.slots['r','navigation']=self.slot
    def tearDown(self):self.runtime.close()
    def pulse(self,seq,window=None):
        window=window or self.p.control_window(self.token,'r',self.epochs)
        return self.p.adapter_input(self.token,'r','navigation',self.epochs,self.binding['binding_epoch'],seq,window['window_id'],.15)
    def schedule(self,sim):
        self.backend.sim_time=sim;self.runtime._schedule(self.p.snapshot(),sim)
    def deliver(self,job):
        self.slot.result=dict(job=job,value=action_for(job['observation'],'navigation','velocity_body',dict(frame='base_link',vx_mps=.2,vy_mps=0.,wz_rps=0.)),error=None,completed=self.now)
        self.runtime._collect(self.p.snapshot(),self.backend.sim_time)
    def test_new_window_prospectively_samples_current_own_state(self):
        old=self.pulse(0);self.schedule(0.);first=self.slot.jobs[-1];self.deliver(first)
        self.now=10.1;new=self.pulse(1);self.schedule(.02)
        self.assertEqual(len(self.slot.jobs),2);second=self.slot.jobs[-1]
        self.assertEqual(second['observation']['own']['odom_xyyaw'][0],.02)
        self.assertEqual(second['observation']['sensors']['ranges']['capture_sim_time'],.02)
        self.assertEqual(second['observation']['wall_deadline'],new['activation_expires'])
        self.assertEqual(first['observation']['wall_deadline'],old['activation_expires'])
        self.assertEqual(second['sample_identity']['sim_ns'],20_000_000)
        self.assertEqual(second['sample_identity']['wall_capture_start'],10.1)
        self.assertEqual(second['sample_identity']['wall_capture_end'],10.1)
        self.deliver(second);self.now=old['activation_expires']
        self.assertIsNotNone(self.runtime._targets(self.p.snapshot(),.03)['r']['motion'])
    def test_withheld_new_result_does_not_extend_old_output(self):
        a=self.pulse(0);self.schedule(0.);first=self.slot.jobs[-1];self.deliver(first)
        self.now=10.1;self.pulse(1);self.schedule(.02);self.now=a['activation_expires']
        self.assertIsNone(self.runtime._targets(self.p.snapshot(),.03)['r']['motion'])
    def test_same_physical_time_cannot_be_resampled_as_fresh(self):
        self.pulse(0);self.schedule(0.);self.now=10.1;self.pulse(1);self.schedule(0.)
        self.assertEqual(len(self.slot.jobs),1);self.assertEqual(len(self.backend.samples),1)
    def test_wall_minimum_and_same_window_do_not_trigger(self):
        self.pulse(0);self.schedule(0.);self.now=10.049;self.pulse(1);self.schedule(.02)
        self.assertEqual(len(self.slot.jobs),1)
        self.now=10.051;self.schedule(.022);self.assertEqual(len(self.slot.jobs),2)
        # The next pulse does not extend its original window authorization.
        self.now=10.102;self.schedule(.024);self.assertEqual(len(self.slot.jobs),2)
    def test_repeated_pulses_same_window_never_refresh(self):
        w=self.p.control_window(self.token,'r',self.epochs);self.pulse(0,w);self.schedule(0.)
        self.now=10.1;self.pulse(1,w);self.schedule(.02);self.assertEqual(len(self.slot.jobs),1)
    def test_expired_activation_never_samples(self):
        a=self.pulse(0);self.schedule(0.);self.now=a['activation_expires'];self.schedule(.02)
        self.assertEqual(len([j for j in self.slot.jobs if not j.get('deactivate')]),1)
    def test_capture_overrun_does_not_queue_expired_job(self):
        self.pulse(0);self.schedule(0.);self.now=10.1;new=self.pulse(1)
        self.backend.sample_hook=lambda:setattr(self,'now',new['activation_expires'])
        self.schedule(.02);self.assertEqual(len(self.slot.jobs),1)
    def test_stale_backend_time_not_restamped(self):
        self.pulse(0);self.schedule(0.);self.now=10.1;self.pulse(1);self.backend.stale=True
        self.schedule(.02);self.assertEqual(len([j for j in self.slot.jobs if not j.get('deactivate')]),1)
        self.assertTrue(self.runtime.status['r','navigation'].startswith('sensor_error'))

    def test_ordinary_sample_resets_wall_minimum(self):
        self.pulse(0);self.schedule(0.);self.now=10.03;self.schedule(.05)
        self.assertEqual(len(self.slot.jobs),2)
        self.now=10.06;self.pulse(1);self.schedule(.06)
        self.assertEqual(len(self.slot.jobs),2)
        self.now=10.081;self.schedule(.062);self.assertEqual(len(self.slot.jobs),3)

    def test_both_triggers_sample_once(self):
        self.pulse(0);self.schedule(0.);self.now=10.1;self.pulse(1);self.schedule(.05)
        self.assertEqual(len(self.backend.samples),2);self.assertEqual(len(self.slot.jobs),2)

    def test_other_profiles_and_legacy_keep_sim_only(self):
        from .adapters import Registry
        registered=self.runtime.registry.get('nav_rule_v1')
        for variant in ('legacy','camera','custom'):
            with self.subTest(variant=variant):
                self.runtime._own_samples.clear();self.runtime.next_observation.clear();self.slot.jobs.clear();self.backend.samples.clear()
                self.now=10.;self.pulse(0 if variant=='legacy' else (2 if variant=='camera' else 4))
                snapshot=self.p.snapshot();b=snapshot['bindings']['r']['navigation']
                # Each fixture declares its actual immutable profile through
                # public registration, rather than mutating registered internals.
                spec=copy.deepcopy(registered.descriptor)
                if variant=='legacy':b['activation_required']=False
                if variant=='camera':spec['required_sensors']=['camera','odometry']
                if variant=='custom':
                    spec['adapter_id']='custom';b['adapter_id']='custom'
                registry=Registry();registry.register(spec,registered.factory);self.runtime.registry=registry
                self.backend.sim_time=0.;self.runtime._schedule(snapshot,0.)
                count=len(self.backend.samples);self.now=10.1
                b['activation_seq']+=1;b['activation_window_id']+=1;b['activation_expires']+=.1
                self.backend.sim_time=.02;self.runtime._schedule(snapshot,.02)
                self.assertEqual(len(self.backend.samples),count)

    def test_release_clears_cache_and_old_result(self):
        self.pulse(0);self.schedule(0.);job=self.slot.jobs[-1]
        self.p.release(self.token,'r',self.epochs);self.runtime._schedule(self.p.snapshot(),.01)
        self.assertNotIn(('r','navigation'),self.runtime._own_samples)
        self.deliver(job);self.assertNotIn(('r','navigation'),self.runtime.outputs)

    def test_rebind_does_not_inherit_previous_wall_floor(self):
        self.pulse(0);self.schedule(0.);self.now=10.01
        self.binding=self.runtime.bind(self.token,'r','navigation',self.epochs,'nav_rule_v1',{'goal_world_m':[.75,0.]})
        self.pulse(0);self.schedule(.002)
        self.assertEqual(len(self.slot.jobs),2)
        self.assertEqual(self.slot.jobs[-1]['observation']['binding_epoch'],self.binding['binding_epoch'])

    def test_unavailable_ranges_can_recover_without_sticky_fault(self):
        original=self.backend.sensor_sample
        def unavailable(rid):
            raw=original(rid);raw.ranges=();raw.range_angles=();return raw
        self.backend.sensor_sample=unavailable
        self.pulse(0);self.schedule(0.)
        self.assertEqual(self.runtime.status['r','navigation'],'required_sensor_unavailable:ranges')
        self.assertNotIn(('r','navigation'),self.runtime._fault_epochs)
        self.backend.sensor_sample=original;self.now=10.1;self.pulse(1);self.schedule(.02)
        self.assertEqual(len(self.slot.jobs),1)

    def test_blocked_real_slot_has_one_running_one_pending_across_refreshes(self):
        import threading
        from .runtime import AdapterSlot
        from .adapters import AdapterSpec
        entered=threading.Event();release=threading.Event()
        class Blocking:
            def reset(self,context):pass
            def close(self):pass
            def act(self,o):
                entered.set();release.wait(1.)
                return action_for(o,'navigation','velocity_body',dict(frame='base_link',vx_mps=.2,vy_mps=0.,wz_rps=0.))
        original=self.runtime.registry.get('nav_rule_v1')
        self.runtime.registry._specs['nav_rule_v1']=AdapterSpec(original.descriptor,lambda config:Blocking())
        slot=AdapterSlot(self.runtime.registry,lambda:self.now);self.runtime.slots['r','navigation']=slot
        try:
            self.pulse(0);self.schedule(0.);self.assertTrue(entered.wait(1.));worker=slot.thread
            for i in range(1,6):
                self.now=10.+i*.06;self.pulse(i);self.schedule(i*.01)
            self.assertIs(slot.thread,worker);self.assertLessEqual(slot.pending.qsize(),1)
            self.assertTrue(slot.running);self.assertGreaterEqual(slot.dropped,3)
            self.assertIsNone(self.runtime._targets(self.p.snapshot(),self.backend.sim_time)['r']['motion'])
            self.p.release(self.token,'r',self.epochs);self.runtime._schedule(self.p.snapshot(),self.backend.sim_time)
            self.assertLessEqual(slot.pending.qsize(),1)
        finally:
            slot.close();release.set();slot.thread.join(1.);self.assertFalse(slot.thread.is_alive())
