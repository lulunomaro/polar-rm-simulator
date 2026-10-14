import copy
import threading
import time
import unittest
from types import SimpleNamespace
from .runtime import PlatformRuntime
from .control import ControlPlane
from .contracts import action_for
from .test_control import Clock

class FakeBackend:
    def __init__(self,ids=('alpha','beta')):
        self.robot_ids=ids;self.timestep=.01;self.sim_time=0.;self.episode=0;self.targets={};self.step_threads=[];self.closed=False
    def sensor_sample(self,rid):
        return SimpleNamespace(robot_id=rid,episode=self.episode,sim_time=self.sim_time,team='red',role='sentry',
            own_qpos=(0.,0.,0.,.1,.1),own_qvel=(0.,)*5,odom_xyyaw=(0.,)*3,odom_vxyw=(0.,)*3,
            own_hp=100,ammo=100,own_heat=0.,match_phase='running',remaining_seconds=300.,emergency_stop=False,
            ranges=(1.,2.),range_angles=(0.,1.),range_max=8.,enemy_truth='MUST_NOT_CROSS_BOUNDARY',sim=self)
    def own_pose(self,rid):return dict(vx=0.,vy=0.,wz=0.)
    def allowed(self,rid):return True
    def validate_target(self,rid,channel,value):return channel!='gimbal' or (-3.14<=value['yaw_rad']<=3.14 and -.4<=value['pitch_rad']<=.5)
    def step(self,targets):
        self.targets=copy.deepcopy(targets);self.sim_time+=self.timestep;self.step_threads.append(threading.get_ident())
    def neutralize(self):self.targets={r:dict(motion=None,gimbal=None,fire=False) for r in self.robot_ids}
    def display_snapshot(self):return dict(sim_time=self.sim_time,source='simulator_truth_display_only',robots=[])
    def close(self):self.closed=True

class TestAdapter:
    def __init__(self,kind,config):self.kind=kind;self.config=config
    def reset(self,context):self.context=context
    def act(self,o):
        seen=self.config.get('seen')
        if seen is not None:seen.append(o)
        event=self.config.get('event')
        if event is not None:event.wait(3.)
        if self.config.get('error'):raise RuntimeError('named_test_failure')
        if self.kind=='navigation':
            c=dict(frame='base_link',vx_mps=self.config.get('vx',.3),vy_mps=0.,wz_rps=0.)
            a=action_for(o,self.kind,'velocity_body',c)
        else:
            c=dict(frame='base_link',yaw_rad=self.config.get('yaw',.2),pitch_rad=self.config.get('pitch',.1),
                active=True,confidence=None,fire_permission=True)
            a=action_for(o,self.kind,'gimbal_target',c)
        change=self.config.get('change')
        if change=='robot':a['robot_id']='other'
        if change=='nan':a['command']['vx_mps']=float('nan')
        if change=='epoch':a['binding_epoch']-=1
        if change=='seq':a['observed_seq']-=1
        return a
    def close(self):pass

class TestRegistry:
    def __init__(self):self.factories={};self.seen=[];self.event=None
    def get(self,name):
        if name not in ('nav','aim','blocked','failing','badrobot','badnan','badepoch','badseq','badpitch','stationaryaim'):raise KeyError(name)
        kind='aim' if name in ('aim','badpitch','stationaryaim') else 'navigation'
        return SimpleNamespace(descriptor=dict(adapter_id=name,kind=kind,
            output_modes=['gimbal_target' if kind=='aim' else 'velocity_body'],required_sensors=[],stationary_only=name=='stationaryaim'))
    def descriptors(self):return [self.get(n).descriptor for n in ('nav','aim')]
    def create(self,name,config):
        spec=self.get(name);config=dict(config);config['seen']=self.seen
        if name=='blocked':config['event']=self.event
        if name=='failing':config['error']=True
        if name.startswith('bad'):config['change']=name[3:]
        if name=='badpitch':config['pitch']=1.
        return TestAdapter(spec.descriptor['kind'],config)

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.backend=FakeBackend();self.registry=TestRegistry()
        self.runtime=PlatformRuntime(self.backend,registry=self.registry,clock=self.clock,observation_period=.02)
        p=self.runtime.control;self.a=p.open_session('operator')['token'];self.b=p.open_session('operator')['token']
        self.ae=p.claim(self.a,'alpha',['motion','gimbal','fire'])['lease_epochs']
        self.be=p.claim(self.b,'beta',['motion','gimbal','fire'])['lease_epochs']
    def tearDown(self):
        if self.registry.event:self.registry.event.set()
        self.runtime.close()
    def bind(self,token,rid,epochs,kind='navigation',name='nav',config=None):
        channel='motion' if kind=='navigation' else 'gimbal'
        return self.runtime.bind(token,rid,kind,{channel:epochs[channel]},name,config or {})
    def tick(self,n=1):
        for _ in range(n):self.runtime.step_once();self.clock.advance(.01);time.sleep(.005)
    def test_independent_navigation_and_aim_bindings(self):
        self.bind(self.a,'alpha',self.ae,config={'vx':.2});self.bind(self.b,'beta',self.be,config={'vx':-.4})
        self.bind(self.a,'alpha',self.ae,'aim','aim',{'yaw':.3});self.bind(self.b,'beta',self.be,'aim','aim',{'yaw':-.3})
        self.tick(4)
        a,b=self.backend.targets['alpha'],self.backend.targets['beta']
        self.assertEqual(a['motion']['vx_mps'],.2);self.assertEqual(b['motion']['vx_mps'],-.4)
        self.assertEqual(a['gimbal']['yaw_rad'],.3);self.assertEqual(b['gimbal']['yaw_rad'],-.3)
        self.assertFalse(a['fire']);self.assertFalse(b['fire'])
        self.assertEqual(len(set(self.backend.step_threads)),1)
    def test_algorithm_observation_contains_no_sim_or_enemy_truth(self):
        self.bind(self.a,'alpha',self.ae);self.tick(3)
        o=self.registry.seen[0]
        self.assertNotIn('enemy_truth',o);self.assertNotIn('sim',o);self.assertNotIn('robots',o)
        self.assertEqual(o['robot_id'],'alpha');self.assertFalse(o['sensors']['camera']['available'])
    def test_rebind_neutralizes_and_discards_old_inflight_result(self):
        self.registry.event=threading.Event()
        self.bind(self.a,'alpha',self.ae,name='blocked',config={'vx':.7});self.tick()
        slot=self.runtime.slots['alpha','navigation']
        self.bind(self.a,'alpha',self.ae,config={'vx':-.2});self.runtime.step_once()
        self.assertIsNone(self.backend.targets['alpha']['motion'])
        self.registry.event.set();self.tick(6)
        self.assertEqual(self.backend.targets['alpha']['motion']['vx_mps'],-.2)
        self.assertIs(slot,self.runtime.slots['alpha','navigation'])
    def test_exception_neutralizes_only_its_robot(self):
        self.bind(self.a,'alpha',self.ae,name='failing');self.bind(self.b,'beta',self.be)
        self.tick(5)
        self.assertIsNone(self.backend.targets['alpha']['motion'])
        self.assertIsNotNone(self.backend.targets['beta']['motion'])
    def test_bounded_backpressure_and_stalled_rebind(self):
        self.registry.event=threading.Event();self.bind(self.a,'alpha',self.ae,name='blocked');self.tick()
        slot=self.runtime.slots['alpha','navigation'];thread=slot.thread
        for i in range(20):
            self.bind(self.a,'alpha',self.ae,name='blocked',config={'vx':.1});self.tick()
        self.assertEqual(len(self.runtime.slots),1);self.assertIs(slot.thread,thread)
        self.assertLessEqual(slot.pending.qsize(),1);self.assertGreater(slot.dropped,0)
        self.assertIsNone(self.backend.targets['alpha']['motion'])
        self.assertEqual(self.runtime.health()['steps'],21)
    def test_wrong_robot_nan_binding_and_sequence_fail_closed(self):
        for name in ['badrobot','badnan','badepoch','badseq']:
            self.bind(self.a,'alpha',self.ae,name=name);self.tick(3)
            self.assertIsNone(self.backend.targets['alpha']['motion'],name)
    def test_actual_robot_limits_reject_broad_contract_aim(self):
        self.bind(self.a,'alpha',self.ae,'aim','badpitch');self.tick(3)
        self.assertIsNone(self.backend.targets['alpha']['gimbal'])
    def test_stale_output_timeout_neutral_and_no_manual_takeover(self):
        self.bind(self.a,'alpha',self.ae);self.tick(3)
        self.assertIsNotNone(self.backend.targets['alpha']['motion'])
        self.clock.advance(.4);self.runtime.step_once()
        self.assertIsNone(self.backend.targets['alpha']['motion'])
    def test_manual_fire_requires_separate_live_command(self):
        self.bind(self.a,'alpha',self.ae,'aim','aim');self.tick(3)
        self.assertFalse(self.backend.targets['alpha']['fire'])
        self.runtime.control.control(self.a,'alpha','fire',self.ae['fire'],1,{'fire':True},.1)
        self.runtime.step_once();self.assertTrue(self.backend.targets['alpha']['fire'])
        self.clock.advance(.11);self.runtime.step_once();self.assertFalse(self.backend.targets['alpha']['fire'])
    def test_readonly_cached_snapshot_works_from_other_thread(self):
        self.tick();spectator=self.runtime.control.open_session('spectator')['token'];values=[]
        thread=threading.Thread(target=lambda:values.append(self.runtime.snapshot(spectator)))
        thread.start();thread.join();self.assertEqual(values[0]['source'],'simulator_truth_display_only')
    def test_second_physics_thread_refused(self):
        self.tick();errors=[]
        def other():
            try:self.runtime.step_once()
            except Exception as e:errors.append(e)
        thread=threading.Thread(target=other);thread.start();thread.join()
        self.assertIsInstance(errors[0],RuntimeError);self.assertEqual(len(self.backend.step_threads),1)
    def test_released_robot_neutral_before_next_step(self):
        self.bind(self.a,'alpha',self.ae);self.tick(3)
        self.runtime.control.release(self.a,'alpha',self.ae);self.runtime.step_once()
        self.assertIsNone(self.backend.targets['alpha']['motion']);self.assertFalse(self.backend.targets['alpha']['fire'])
    def test_stationary_aim_rechecked_on_current_manual_motion(self):
        self.bind(self.a,'alpha',self.ae,'aim','stationaryaim');self.tick(3)
        self.assertIsNotNone(self.backend.targets['alpha']['gimbal'])
        self.runtime.control.control(self.a,'alpha','motion',self.ae['motion'],1,
            dict(frame='base_link',vx_mps=.2,vy_mps=0.,wz_rps=0.),.2)
        self.runtime.step_once()
        self.assertIsNone(self.backend.targets['alpha']['gimbal'])
        self.assertEqual(self.runtime.status['alpha','aim'],'stationary_required')
    def test_stationary_aim_rechecked_on_current_measured_motion(self):
        self.bind(self.a,'alpha',self.ae,'aim','stationaryaim');self.tick(3)
        self.backend.own_pose=lambda rid:dict(vx=.04,vy=0.,wz=0.)
        self.runtime.step_once();self.assertIsNone(self.backend.targets['alpha']['gimbal'])
    def test_new_episode_revokes_leases_and_inflight_commands(self):
        self.bind(self.a,'alpha',self.ae);self.tick(3)
        self.backend.episode+=1;self.backend.sim_time=0.
        self.runtime.step_once()
        self.assertIsNone(self.backend.targets['alpha']['motion'])
        self.assertIsNone(self.runtime.control.snapshot()['leases']['alpha']['motion']['owner'])
    def test_sensor_failure_does_not_stop_other_robot(self):
        original=self.backend.sensor_sample
        def sample(rid):
            if rid=='alpha':raise ValueError('sensor_failure_test')
            return original(rid)
        self.backend.sensor_sample=sample
        self.bind(self.a,'alpha',self.ae);self.bind(self.b,'beta',self.be);self.tick(4)
        self.assertIsNone(self.backend.targets['alpha']['motion'])
        self.assertIsNotNone(self.backend.targets['beta']['motion'])
        self.assertEqual(self.runtime.status['alpha','navigation'],'sensor_error:ValueError')
    def test_fault_is_sticky_with_pending_same_epoch_job(self):
        first_started=threading.Event();release=threading.Event();calls=[]
        class FlakyAdapter(TestAdapter):
            def act(inner,o):
                calls.append(o['binding_epoch'])
                if len(calls)==1:
                    first_started.set();release.wait(2.)
                    raise ValueError('first_job_fault')
                return super().act(o)
        self.registry.create=lambda name,config:FlakyAdapter('navigation',config)
        self.bind(self.a,'alpha',self.ae)
        self.runtime.step_once();self.assertTrue(first_started.wait(.5))
        self.tick(4)
        slot=self.runtime.slots['alpha','navigation']
        self.assertEqual(slot.pending.qsize(),1)
        release.set()
        deadline=time.monotonic()+.5
        while slot.results.empty() and time.monotonic()<deadline:time.sleep(.002)
        self.runtime.step_once();self.tick(3)
        self.assertEqual(len(calls),1,'Pending same-epoch job executed after a fault')
        self.assertIsNone(self.backend.targets['alpha']['motion'])
        self.assertEqual(self.runtime.status['alpha','navigation'],'adapter_error:ValueError')
        self.bind(self.a,'alpha',self.ae);self.tick(4)
        self.assertGreater(len(calls),1)
        self.assertIsNotNone(self.backend.targets['alpha']['motion'])
    def test_invalid_contract_result_cannot_be_overwritten_by_pending_success(self):
        first_started=threading.Event();release=threading.Event();calls=[]
        class FlakyIdentity(TestAdapter):
            def act(inner,o):
                calls.append(o['binding_epoch'])
                value=super().act(o)
                if len(calls)==1:
                    first_started.set();release.wait(2.);value['robot_id']='wrong_robot'
                return value
        self.registry.create=lambda name,config:FlakyIdentity('navigation',config)
        self.bind(self.a,'alpha',self.ae);self.runtime.step_once()
        self.assertTrue(first_started.wait(.5));self.tick(4)
        slot=self.runtime.slots['alpha','navigation'];self.assertEqual(slot.pending.qsize(),1)
        release.set();deadline=time.monotonic()+.5
        while slot.results.empty() and time.monotonic()<deadline:time.sleep(.002)
        self.tick(4)
        self.assertEqual(len(calls),1)
        self.assertIsNone(self.backend.targets['alpha']['motion'])
        self.assertEqual(self.runtime.status['alpha','navigation'],'adapter_error:ContractError')
    def test_authority_rejects_late_valid_result_after_same_epoch_fault(self):
        self.bind(self.a,'alpha',self.ae,name='failing');self.tick(3)
        key=('alpha','navigation');slot=self.runtime.slots[key]
        o=self.registry.seen[0]
        b=self.runtime.control.snapshot()['bindings']['alpha']['navigation']
        valid=action_for(o,'navigation','velocity_body',dict(frame='base_link',vx_mps=.5,vy_mps=0.,wz_rps=0.))
        slot._latest(slot.results,dict(job=dict(kind='navigation',binding=b,observation=o),value=valid,error=None,completed=self.clock()))
        self.runtime.step_once()
        self.assertIsNone(self.backend.targets['alpha']['motion'])
        self.assertEqual(self.runtime.status[key],'adapter_error:RuntimeError')
    def test_sensor_identity_episode_and_time_checked_before_adapter(self):
        original=self.backend.sensor_sample
        self.backend.sim_time=1.;self.backend.episode=1
        for field,value in [('robot_id','beta'),('episode',0),('sim_time',1000.),('sim_time',0.)]:
            def sample(rid,field=field,value=value):
                raw=original(rid);setattr(raw,field,value);return raw
            self.backend.sensor_sample=sample
            self.bind(self.a,'alpha',self.ae);self.tick(3)
            self.assertIsNone(self.backend.targets['alpha']['motion'],field)
            self.assertEqual(self.runtime.status['alpha','navigation'],'sensor_error:ValueError')
        self.assertEqual(self.registry.seen,[],'Bad sensor envelope reached an adapter')
    def test_system_exit_neutralizes_immediately_and_keeps_worker_alive(self):
        second_started=threading.Event();release=threading.Event();calls=[]
        class ExitingAdapter(TestAdapter):
            def act(inner,o):
                calls.append(o['binding_epoch'])
                if len(calls)==2:
                    second_started.set();release.wait(2.);raise SystemExit('third_party_exit')
                return super().act(o)
        self.registry.create=lambda name,config:ExitingAdapter('navigation',config)
        self.bind(self.a,'alpha',self.ae);self.tick(2)
        self.assertIsNotNone(self.backend.targets['alpha']['motion'])
        self.tick(2);self.assertTrue(second_started.wait(.5));release.set()
        slot=self.runtime.slots['alpha','navigation'];deadline=time.monotonic()+.5
        while slot.results.empty() and time.monotonic()<deadline:time.sleep(.002)
        self.runtime.step_once()
        self.assertIsNone(self.backend.targets['alpha']['motion'])
        self.assertEqual(self.runtime.status['alpha','navigation'],'adapter_error:SystemExit')
        self.assertTrue(slot.thread.is_alive());self.tick(3);self.assertEqual(len(calls),2)
        self.bind(self.a,'alpha',self.ae);self.tick(3)
        self.assertIsNotNone(self.backend.targets['alpha']['motion'])
    def test_system_exit_during_rebind_close_is_faulted(self):
        class ExitingClose(TestAdapter):
            def close(inner):raise SystemExit('third_party_close_exit')
        self.registry.create=lambda name,config:ExitingClose('navigation',config)
        self.bind(self.a,'alpha',self.ae);self.tick(3)
        self.assertIsNotNone(self.backend.targets['alpha']['motion'])
        self.bind(self.a,'alpha',self.ae);self.tick(3)
        slot=self.runtime.slots['alpha','navigation']
        self.assertIsNone(self.backend.targets['alpha']['motion'])
        self.assertEqual(self.runtime.status['alpha','navigation'],'adapter_error:SystemExit')
        self.assertEqual(slot.lifecycle_error,'SystemExit');self.assertTrue(slot.thread.is_alive())
    def test_system_exit_during_unbind_close_does_not_kill_worker(self):
        class ExitingClose(TestAdapter):
            def close(inner):raise SystemExit('third_party_close_exit')
        self.registry.create=lambda name,config:ExitingClose('navigation',config)
        self.bind(self.a,'alpha',self.ae);self.tick(3)
        self.runtime.control.unbind(self.a,'alpha','navigation',{'motion':self.ae['motion']});self.tick(3)
        slot=self.runtime.slots['alpha','navigation']
        self.assertIsNone(self.backend.targets['alpha']['motion'])
        self.assertEqual(slot.lifecycle_error,'SystemExit');self.assertTrue(slot.thread.is_alive())
    def test_close_neutralizes_without_advancing_sim_time(self):
        self.tick();before=self.backend.sim_time;self.runtime.close()
        self.assertEqual(before,self.backend.sim_time);self.assertTrue(self.backend.closed)
        self.assertIsNone(self.backend.targets['alpha']['motion'])

if __name__=='__main__':unittest.main()
