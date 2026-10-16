"""Frozen scheduler metadata, live generations and original budgets; no native qualification."""
from types import MappingProxyType,SimpleNamespace
from unittest.mock import patch

import pytest

from rm_match.platform_v2.adapters import Registry,descriptor
from rm_match.platform_v2.contracts import ContractError
from rm_match.platform_v2.runtime import PlatformRuntime
from rm_match.platform_v2.test_control import Clock
from rm_match.platform_v2.test_runtime import FakeBackend


def register(registry=None,**extra):
    registry=Registry() if registry is None else registry
    value=descriptor('generic_camera','aim','fixture',['camera','odometry'],
        schedule_on_camera_frame=True,max_camera_age_sim_s=.08,max_camera_age_wall_s=.08,
        vendor_metadata={'nested':{'large':list(range(100))}},**extra)
    registry.register(value,lambda _:None)
    return registry,value


def test_scheduler_metadata_is_small_immutable_and_cannot_alias_public_or_registered_inputs():
    registry,original=register()
    original['required_sensors'].clear();original['max_camera_age_sim_s']=5.
    public=registry.get('generic_camera').descriptor;public['required_sensors'].clear()
    public['max_camera_age_wall_s']=5.;registry.descriptors()[0]['required_sensors'].clear()
    metadata=registry.scheduling_descriptor('generic_camera')
    assert type(metadata) is MappingProxyType
    assert dict(metadata)==dict(required_sensors=('camera','odometry'),schedule_on_camera_frame=True,
        max_camera_age_sim_s=.08,max_camera_age_wall_s=.08)
    with pytest.raises(TypeError):metadata['max_camera_age_wall_s']=5.
    with pytest.raises(TypeError):metadata['required_sensors'][0]='truth'
    # Public callers retain a complete independently mutable descriptor.
    assert registry.get('generic_camera').descriptor['vendor_metadata']['nested']['large']==list(range(100))
    assert registry.get('generic_camera').scheduling is None


def test_registered_metadata_queries_do_not_deepcopy_large_public_metadata():
    registry,_=register()
    # Any deepcopy here is redundant; the public get path must still copy.
    with patch('rm_match.platform_v2.adapters.copy.deepcopy',side_effect=AssertionError('copied public descriptor')):
        for _ in range(100):assert registry.scheduling_descriptor('generic_camera')['max_camera_age_wall_s']==.08
        with pytest.raises(AssertionError,match='copied public descriptor'):registry.get('generic_camera')


@pytest.mark.parametrize('sensors',[[],['camera'],('odometry','ranges')])
def test_absent_optional_keys_keep_callers_default_semantics(sensors):
    registry=Registry();value=descriptor('example','navigation','fixture',sensors)
    registry.register(value,lambda _:None)
    result=registry.scheduling_descriptor('example')
    assert dict(result)=={'required_sensors':tuple(sensors)}
    assert result.get('max_camera_age_wall_s',.037)==.037


@pytest.mark.parametrize('field,value',[
    ('required_sensors',None),('required_sensors',{'camera'}),('required_sensors',['camera',[]]),
    ('schedule_on_camera_frame',[]),('max_camera_age_sim_s',{'custom':.08}),
    ('observation_profile',['pointcloud_imu_v1'])])
def test_unusual_existing_metadata_keeps_public_copy_and_deferred_validation(field,value):
    registry=Registry();data=descriptor('legacy','aim','fixture',['camera']);data[field]=value
    registry.register(data,lambda _:None)
    old=registry.get('legacy').descriptor;new=registry.scheduling_descriptor('legacy')
    assert type(new) is dict and new==old
    if type(new[field]) in (list,dict,set):assert new[field] is not registry._specs['legacy'].descriptor[field]


def test_partial_registration_and_unknown_adapter_error_semantics_are_preserved():
    registry=Registry();registry.register({'adapter_id':'partial','kind':'aim'},lambda _:None)
    assert registry.scheduling_descriptor('partial')=={'adapter_id':'partial','kind':'aim'}
    with pytest.raises(ContractError,match='^unknown_adapter$'):registry.scheduling_descriptor('missing')


def test_inherited_get_uses_frozen_metadata_but_overrides_remain_live():
    class Inherited(Registry):pass
    inherited,_=register(Inherited())
    assert type(inherited.scheduling_descriptor('generic_camera')) is MappingProxyType
    class Dynamic(Registry):
        age=.08
        def get(self,aid):
            result=super().get(aid);result.descriptor['max_camera_age_wall_s']=self.age
            return result
    dynamic,_=register(Dynamic())
    assert dynamic.scheduling_descriptor('generic_camera')['max_camera_age_wall_s']==.08
    dynamic.age=.01
    assert dynamic.scheduling_descriptor('generic_camera')['max_camera_age_wall_s']==.01
    inherited.get=lambda _:SimpleNamespace(descriptor={'live_override':True})
    assert inherited.scheduling_descriptor('generic_camera')=={'live_override':True}


def test_legacy_duck_registry_does_not_acquire_a_stale_runtime_cache():
    class Legacy:
        age=.08
        def get(self,_):return SimpleNamespace(descriptor={'max_camera_age_wall_s':self.age})
    legacy=Legacy();runtime=PlatformRuntime(FakeBackend(),registry=legacy)
    try:
        assert runtime._scheduling_descriptor('anything')['max_camera_age_wall_s']==.08
        legacy.age=.02
        assert runtime._scheduling_descriptor('anything')['max_camera_age_wall_s']==.02
    finally:runtime.close()


def test_staged_spec_publication_includes_its_own_metadata_without_separate_cache():
    current,_=register();staged=Registry();staged._specs=dict(current._specs);staged._capabilities=dict(current._capabilities)
    staged.register(descriptor('second','navigation','fixture',['pointcloud','imu'],observation_profile='pointcloud_imu_v1'),lambda _:None)
    assert 'second' not in current._specs
    current.__dict__.update(_specs=staged._specs,_capabilities=staged._capabilities)
    assert dict(current.scheduling_descriptor('second'))==dict(required_sensors=('pointcloud','imu'),observation_profile='pointcloud_imu_v1')
    assert current.scheduling_descriptor('generic_camera') is staged.scheduling_descriptor('generic_camera')


def test_same_frame_checks_reuse_only_metadata_and_rebind_rechecks_new_original_deadline():
    clock=Clock();backend=FakeBackend(ids=('alpha',));registry,_=register()
    # The camera identity path runs before expensive sensor construction.
    class Camera:
        enable_native_pixels=False
        max_views=1
        frame=7
        calls=[]
        def sensor_identity(self,rid,episode,consumer,sim_time,max_age):
            self.calls.append((consumer,sim_time,max_age));return (self.frame,)
        def stop(self):pass
        def status(self):return {}
    camera=Camera();runtime=PlatformRuntime(backend,registry=registry,clock=clock,camera=camera)
    runtime._episode=backend.episode
    control=runtime.control;token=control.open_session('operator',control_profile='server_window_v1')['token']
    epochs=control.claim(token,'alpha',['gimbal'])['lease_epochs']
    bound=runtime.bind(token,'alpha','aim',epochs,'generic_camera',{})
    window=control.control_window(token,'alpha',epochs)
    control.adapter_input(token,'alpha','aim',epochs,bound['binding_epoch'],0,window['window_id'],.15)
    identity=(backend.episode,bound['binding_epoch'],control.bindings['alpha','aim'].owner,camera.frame)
    runtime._camera_samples['alpha','aim']=identity
    try:
        # Snapshot outside the patched copy hook, since lease isolation is required.
        snapshot=control.snapshot()
        with patch('rm_match.platform_v2.adapters.copy.deepcopy',side_effect=AssertionError('descriptor copied')):
            for sim in (0.,.001,.002):runtime._schedule(snapshot,sim)
        assert len(camera.calls)==3 and all(row[2]==.08 for row in camera.calls)
        assert not runtime.slots
        clock.now=window['expires_wall']
        runtime._schedule(control.snapshot(),.003)
        assert len(camera.calls)==3 and ('alpha','aim') not in runtime._camera_samples
        assert control.bindings['alpha','aim'].epoch>bound['binding_epoch']
        rebound=runtime.bind(token,'alpha','aim',epochs,'generic_camera',{})
        assert rebound['binding_epoch']>bound['binding_epoch']
        # No old same-frame activation or receipt is revived by cached metadata.
        runtime._schedule(control.snapshot(),.004)
        assert len(camera.calls)==3 and not runtime.slots
    finally:runtime.close()
