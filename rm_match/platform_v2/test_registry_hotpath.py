"""Frozen scalar registry queries with detached public metadata and live gates."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from .adapters import Registry,descriptor
from .contracts import ContractError,action_for,build_observation
from .runtime import PlatformRuntime
from .test_control import Clock
from .test_runtime import FakeBackend


class RegistryCapabilityTests(unittest.TestCase):
    def test_source_and_public_metadata_mutation_cannot_change_frozen_flags(self):
        original=descriptor('native','aim','fixture',('camera','odometry'),stationary_only=True,
            source_identity={'nested':{'hashes':['original']}})
        saved=deepcopy(original);registry=Registry();registry.register(original,lambda _:None)
        original['required_sensors'].clear();original['stationary_only']=False
        original['source_identity']['nested']['hashes'][0]='external changed'
        public=registry.get('native').descriptor;public['required_sensors'].clear();public['stationary_only']=False
        public['source_identity']['nested']['hashes'][0]='public changed'
        rows=registry.descriptors();rows[0]['required_sensors'].clear();rows[0]['stationary_only']=False
        self.assertIs(registry.capability('native','stationary_only'),True)
        self.assertIs(registry.capability('native','requires_camera'),True)
        self.assertEqual(registry.get('native').descriptor,saved)
        with self.assertRaises(ContractError):registry.capability('native','source_identity')

    def test_scalar_queries_keep_existing_truth_and_sensor_membership_semantics(self):
        for stationary in (False,True,0,1,None,[],['legacy truthy'],'legacy truthy'):
            registry=Registry();d=descriptor('test','aim','fixture',('camera',),stationary_only=stationary)
            registry.register(d,lambda _:None)
            with self.subTest(stationary=stationary):
                self.assertIs(registry.capability('test','stationary_only'),bool(stationary))
                self.assertEqual(registry.get('test').descriptor,d)
        for sensors in (['camera','odometry'],('camera','odometry'),{'camera','odometry'},frozenset({'camera'}),['vendor_future_sensor']):
            registry=Registry();d=descriptor('test','aim','fixture',());d['required_sensors']=sensors
            registry.register(d,lambda _:None)
            with self.subTest(sensors=sensors):
                self.assertIs(registry.capability('test','requires_camera'),'camera' in sensors)
                self.assertEqual(registry.get('test').descriptor,d)

    def test_unknown_queries_are_errors_and_partial_public_registration_stays_compatible(self):
        registry=Registry();minimal={'adapter_id':'partial','kind':'aim'}
        registry.register(minimal,lambda _:None);self.assertEqual(registry.get('partial').descriptor,minimal)
        self.assertIs(registry.capability('partial','stationary_only'),False)
        with self.assertRaises(ContractError):registry.capability('partial','requires_camera')
        for aid,key in [('missing','stationary_only'),('partial','not_a_capability'),('partial',[])]:
            with self.subTest(aid=aid,key=key),self.assertRaises(ContractError):registry.capability(aid,key)

    def test_unqueryable_metadata_does_not_add_a_registration_restriction(self):
        class Unqueryable:
            def __bool__(self):raise ValueError('unsupported boolean')
            def __contains__(self,item):raise ValueError('unsupported membership')
        registry=Registry();d={'adapter_id':'partial','kind':'aim',
            'stationary_only':Unqueryable(),'required_sensors':Unqueryable()}
        registry.register(d,lambda _:None)
        self.assertIsInstance(registry.get('partial').descriptor['required_sensors'],Unqueryable)
        for key in ('stationary_only','requires_camera'):
            with self.subTest(key=key),self.assertRaises(ContractError):registry.capability('partial',key)


class RuntimeHotpathTests(unittest.TestCase):
    def fixture(self,registry=None):
        clock=Clock();backend=FakeBackend(ids=('red_sentry',))
        if registry is None:
            registry=Registry();registry.register(descriptor('native','aim','fixture',('camera','odometry'),stationary_only=True),lambda _:None)
        runtime=PlatformRuntime(backend,registry=registry,clock=clock);runtime._episode=backend.episode
        token=runtime.control.open_session('operator')['token'];epochs=runtime.control.claim(token,'red_sentry',['gimbal'])['lease_epochs']
        binding=runtime.bind(token,'red_sentry','aim',epochs,'native',{})
        observation=build_observation(backend.sensor_sample('red_sentry'),binding_epoch=binding['binding_epoch'],observed_seq=1,wall_deadline=clock()+.08)
        runtime.outputs['red_sentry','aim']=action_for(observation,'aim','gimbal_target',dict(frame='base_link',yaw_rad=.2,pitch_rad=.1,active=True,confidence=None,fire_permission=False))
        runtime.output_budgets['red_sentry','aim']=dict(capture_wall=clock(),wall_deadline=clock()+.08,capture_sim_time=0.,sim_deadline=.08)
        return runtime,clock,backend,token,epochs

    def test_targets_and_camera_demand_query_scalars_without_public_descriptor_copy(self):
        runtime,clock,backend,_,_=self.fixture()
        try:
            snapshot=runtime.control.snapshot();original=runtime.registry.get
            with patch.object(runtime.registry,'get',wraps=original) as get:
                for _ in range(3):
                    self.assertEqual(runtime._targets(snapshot,0.)['red_sentry']['gimbal']['yaw_rad'],.2)
                    self.assertIn('red_sentry',runtime._camera_desired(snapshot))
                self.assertEqual(get.call_count,0)
        finally:runtime.close()

    def test_frozen_descriptor_does_not_cache_wall_budget_or_measured_motion(self):
        runtime,clock,backend,_,_=self.fixture()
        try:
            snapshot=runtime.control.snapshot();self.assertIsNotNone(runtime._targets(snapshot,0.)['red_sentry']['gimbal'])
            backend.own_pose=lambda _:dict(vx=.04,vy=0.,wz=0.)
            self.assertIsNone(runtime._targets(snapshot,0.)['red_sentry']['gimbal'])
            backend.own_pose=lambda _:dict(vx=0.,vy=0.,wz=0.)
            self.assertIsNotNone(runtime._targets(snapshot,0.)['red_sentry']['gimbal'])
            clock.advance(.08)
            self.assertIsNone(runtime._targets(snapshot,0.)['red_sentry']['gimbal'])
        finally:runtime.close()

    def test_release_epoch_still_revokes_targets_and_camera_consumer(self):
        runtime,_,_,token,epochs=self.fixture()
        try:
            self.assertIsNotNone(runtime._targets(runtime.control.snapshot(),0.)['red_sentry']['gimbal'])
            runtime.control.release(token,'red_sentry',epochs);snapshot=runtime.control.snapshot()
            self.assertIsNone(runtime._targets(snapshot,0.)['red_sentry']['gimbal'])
            self.assertEqual(runtime._camera_desired(snapshot),{})
        finally:runtime.close()

    def test_legacy_registry_without_query_api_keeps_live_get_semantics(self):
        class Legacy:
            stationary=True;sensors=['camera']
            def get(self,*args):return SimpleNamespace(descriptor=descriptor('native','aim','legacy',self.sensors,stationary_only=self.stationary))
        legacy=Legacy();runtime=PlatformRuntime(FakeBackend(),registry=legacy)
        try:
            self.assertTrue(runtime._registry_capability('native','stationary_only'))
            self.assertTrue(runtime._registry_capability('native','requires_camera'))
            legacy.stationary=False;legacy.sensors=[]
            self.assertFalse(runtime._registry_capability('native','stationary_only'))
            self.assertFalse(runtime._registry_capability('native','requires_camera'))
        finally:runtime.close()


if __name__=='__main__':unittest.main()
