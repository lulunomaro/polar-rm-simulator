"""Worker lifecycle/source synchronization units, not a navigation algorithm."""
import copy
import threading
import time
from types import SimpleNamespace
import pytest
from rm_match.platform_v2.runtime import AdapterSlot
from rm_match.platform_v2.adapters import descriptor
from rm_match.platform_v2.contracts import action_for,IDENTITY
from test_decision_plugin import nav_observation

class FixtureRegistry:
    def __init__(self,clock,policy,*,block=False,fail=False):
        self.clock=clock;self.seen=[];self.reset_entered=threading.Event();self.reset_release=threading.Event()
        if not block:self.reset_release.set()
        self.closed=0;self.resets=0;self.fail=fail
        self.metadata=descriptor('custom_reset_fixture','navigation','Synthetic reset fixture',['pointcloud','imu'],
            observation_profile='pointcloud_imu_v1',reset_observation_policy=policy)
    def get(self,_):return SimpleNamespace(descriptor=self.metadata)
    def create(self,_,config):
        registry=self
        class Adapter:
            def reset(self,context):
                registry.resets+=1;registry.reset_entered.set()
                assert registry.reset_release.wait(1.)
                registry.clock[0]+= .09
                if registry.fail:raise RuntimeError('synthetic reset failure')
            def act(self,o):
                registry.seen.append(copy.deepcopy(o))
                return action_for(o,'navigation','velocity_body',dict(frame='base_link',vx_mps=.2,vy_mps=0.,wz_rps=0.))
            def close(self):registry.closed+=1
        return Adapter()

def job(seq,frame,sim,capture_wall,deadline):
    o=nav_observation();o['observed_seq']=seq;o['sim_time']=sim;o['wall_deadline']=deadline
    cloud=o['sensors']['pointcloud'];cloud.update(frame_id=frame,capture_sim_time=sim,
        acquisition_start_ns=int(round((sim-.1)*1e9)),acquisition_end_ns=int(round(sim*1e9)))
    imu=o['sensors']['imu'];imu['capture_sim_time']=sim
    for sample,stamp in zip(imu['samples'],(cloud['acquisition_start_ns'],cloud['acquisition_end_ns'])):sample['sample_sim_ns']=stamp
    return dict(kind='navigation',observation=o,binding=dict(adapter_id='custom_reset_fixture',epoch=o['binding_epoch'],config={}),
        sensor_budget=dict(source='navigation_sensor_v1',frame_id=frame,capture_wall=capture_wall,capture_sim_time=sim,
            wall_deadline=deadline,sim_deadline=sim+.15))

def result(slot):
    end=time.perf_counter()+1.
    while time.perf_counter()<end:
        value=slot.poll()
        if value is not None:return value
        time.sleep(.005)
    raise AssertionError('bounded worker result missing')

def close(slot,registry):
    registry.reset_release.set();slot.close();slot.thread.join(1.)
    assert not slot.thread.is_alive() and slot.lifecycle_error is None

def test_reset_queued_and_pre_reset_pending_captures_never_reach_algorithm():
    clock=[1.];registry=FixtureRegistry(clock,'discard_reset_observation_v1',block=True);slot=AdapterSlot(registry,lambda:clock[0])
    first=job(1,0,.1,1.,1.15);pending=job(2,1,.2,1.07,1.22)
    published=[];original_latest=slot._latest
    def record(q,value):
        if q is slot.results:published.append(copy.deepcopy(value))
        return original_latest(q,value)
    slot._latest=record
    try:
        slot.submit(first);assert registry.reset_entered.wait(1.)
        slot.submit(pending);registry.reset_release.set()
        end=time.perf_counter()+1.
        while len(published)<2 and time.perf_counter()<end:time.sleep(.005)
        assert len(published)==2
        a,b=published
        assert a['error'] is None and b['error'] is None
        assert a['value'] is None and b['value'] is None
        assert a['discarded_reason']==b['discarded_reason']=='reset_observation_discarded_waiting_for_new_capture'
        assert clock[0]<first['observation']['wall_deadline'] and not registry.seen
        clock[0]=1.11;fresh=job(3,2,.3,1.10,1.25);original=copy.deepcopy(fresh)
        slot.poll()  # The real result queue intentionally retains only its latest item.
        slot.submit(fresh);accepted=result(slot)
        assert accepted['error'] is None and accepted['discarded_reason'] is None
        assert registry.resets==1 and registry.seen==[fresh['observation']]
        assert {k:accepted['value'][k] for k in IDENTITY}=={k:fresh['observation'][k] for k in IDENTITY}
        assert fresh==original
    finally:close(slot,registry)
    assert registry.closed==1

@pytest.mark.parametrize('policy',[None,True,'unknown_policy'])
def test_legacy_or_unknown_policy_keeps_first_eligible_observation(policy):
    clock=[1.];registry=FixtureRegistry(clock,policy);slot=AdapterSlot(registry,lambda:clock[0]);value=job(1,0,.1,1.,1.15)
    try:
        slot.submit(value);accepted=result(slot)
        assert accepted['error'] is None and accepted['discarded_reason'] is None
        assert registry.seen==[value['observation']]
    finally:close(slot,registry)

def test_failed_actual_reset_is_not_converted_to_pending_by_capture_policy():
    clock=[1.];registry=FixtureRegistry(clock,'discard_reset_observation_v1',fail=True);slot=AdapterSlot(registry,lambda:clock[0])
    try:
        slot.submit(job(1,0,.1,1.,1.15));failed=result(slot)
        assert failed['error']=='RuntimeError' and failed['discarded_reason'] is None and not registry.seen
        assert registry.closed==1
    finally:close(slot,registry)
