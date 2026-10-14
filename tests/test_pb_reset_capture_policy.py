"""Real PB WslNavigationAdapter/AdapterSlot, simulated session reset and clocks.

No WSL/ROS/physics. Reset receives context only and must never spend an old
capture's remaining 150ms on the first algorithm request after negotiation.
"""
import copy
import json
import threading
import time
import pytest
from unittest.mock import patch

from rm_match.integrations.pb_wsl_navigation_registry import (
    ADAPTER_ID,SCHEMA,register_pb_wsl_navigation,navigation_descriptor,WslNavigationAdapter)
from rm_match.platform_v2.adapters import Registry
from rm_match.platform_v2.runtime import AdapterSlot
from rm_match.platform_v2.contracts import action_for,IDENTITY
from test_decision_plugin import nav_observation


class Session:
    def __init__(self,*args,clock,fail=False,**kwargs):
        self.clock=clock;self.fail=fail;self.reset_entered=threading.Event();self.reset_release=threading.Event()
        self.prepared=False;self.stopped=False;self.closed=0;self.resets=[];self.requests=[]
    def prepare(self):self.prepared=True
    def reset(self,context,config):
        self.resets.append((copy.deepcopy(context),copy.deepcopy(config)));self.reset_entered.set()
        assert self.reset_release.wait(1.)
        self.clock.now+=.134
        if self.fail:raise RuntimeError('simulated actual reset failure')
    def exchange(self,packet,timeout):
        self.requests.append((copy.deepcopy(packet),timeout));self.clock.now+=.03
        if self.clock.now>=packet['observation']['wall_deadline']:raise TimeoutError('simulated original act deadline')
        o=packet['observation']
        return dict(schema='polar.sim.adapter.jsonl.v1',op='act',ok=True,
            action=action_for(o,'navigation','velocity_body',dict(frame='base_link',vx_mps=.2,vy_mps=0.,wz_rps=0.)))
    def request_stop(self):self.stopped=True
    def close(self):self.closed+=1


class Clock:
    now=1.
    def __call__(self):return self.now


def fixture(tmp_path,fail=False):
    clock=Clock();created=[]
    def factory(*args,**kwargs):
        session=Session(*args,**kwargs,fail=fail);created.append(session);return session
    path=tmp_path/'registration.json'
    path.write_text(json.dumps(dict(schema=SCHEMA,config_ref={},environment_ref={},out=str(tmp_path/'out'),diagnostics=False)),encoding='utf8')
    registry=Registry();session=register_pb_wsl_navigation(registry,path,repo_root=tmp_path,clock=clock,session_factory=factory)
    slot=AdapterSlot(registry,clock);published=[];original=slot._latest
    def record(q,value):
        if q is slot.results:published.append(copy.deepcopy(value))
        return original(q,value)
    slot._latest=record
    return clock,registry,session,slot,published


def job(seq,frame,sim,capture_wall):
    o=nav_observation();o.update(robot_id='red_sentry',episode=0,binding_epoch=1,observed_seq=seq,
        sim_time=sim,wall_deadline=capture_wall+.15)
    cloud=o['sensors']['pointcloud'];cloud.update(frame_id=frame,capture_sim_time=sim,
        acquisition_start_ns=round((sim-.1)*1e9),acquisition_end_ns=round(sim*1e9))
    imu=o['sensors']['imu'];imu['capture_sim_time']=sim
    for row,stamp in zip(imu['samples'],(cloud['acquisition_start_ns'],cloud['acquisition_end_ns'])):row['sample_sim_ns']=stamp
    return dict(kind='navigation',observation=o,binding=dict(adapter_id=ADAPTER_ID,epoch=1,config={}),
        sensor_budget=dict(source='navigation_sensor_v1',frame_id=frame,capture_wall=capture_wall,
            capture_sim_time=sim,wall_deadline=capture_wall+.15,sim_deadline=sim+.15))


def wait(predicate):
    end=time.perf_counter()+1.
    while time.perf_counter()<end:
        if predicate():return
        time.sleep(.002)
    raise AssertionError('bounded real slot synchronization missing')


def close(slot,session):
    session.reset_release.set();slot.close();slot.thread.join(1.)
    assert not slot.thread.is_alive() and slot.lifecycle_error is None


def test_actual_descriptor_and_instance_opt_in_to_existing_capture_policy(tmp_path):
    assert navigation_descriptor()['reset_observation_policy']=='discard_reset_observation_v1'
    clock,registry,session,slot,published=fixture(tmp_path)
    try:
        assert session.prepared and not session.resets and not session.requests
        assert registry.get(ADAPTER_ID).descriptor['reset_observation_policy']=='discard_reset_observation_v1'
        adapter=registry.create(ADAPTER_ID,{})
        assert type(adapter) is WslNavigationAdapter
        assert adapter.descriptor['reset_observation_policy']=='discard_reset_observation_v1'
        adapter.close()
    finally:close(slot,session)


def test_legacy_descriptor_absence_spends_near150ms_reset_old_capture_and_faults(tmp_path):
    # Controlled counterfactual matching the preserved pre-fix descriptor. The
    # real adapter/session boundary and real slot are unchanged; no source edit.
    metadata=navigation_descriptor();metadata.pop('reset_observation_policy')
    with patch('rm_match.integrations.pb_wsl_navigation_registry.navigation_descriptor',return_value=metadata):
        clock,registry,session,slot,published=fixture(tmp_path)
        first=job(1,0,.1,1.);original=copy.deepcopy(first)
        try:
            session.reset_release.set();slot.submit(first);wait(lambda:len(published)>=1)
            assert published[0]['error']=='TimeoutError' and published[0]['discarded_reason'] is None
            assert len(session.requests)==1 and session.requests[0][1]==pytest.approx(.016)
            assert first==original and session.stopped
        finally:close(slot,session)


def test_real_pb_reset_134ms_discards_first_and_queued_capture_then_fresh_unchanged(tmp_path):
    clock,registry,session,slot,published=fixture(tmp_path)
    first=job(1,0,.1,1.);queued=job(2,1,.2,1.07);saved=copy.deepcopy((first,queued))
    try:
        slot.submit(first);assert session.reset_entered.wait(1.)
        slot.submit(queued);session.reset_release.set();wait(lambda:len(published)>=2)
        assert len(session.resets)==1 and not session.requests
        assert clock.now<first['observation']['wall_deadline']  # only 16ms remain
        for row in published[:2]:
            assert row['error'] is None and row['value'] is None
            assert row['discarded_reason']=='reset_observation_discarded_waiting_for_new_capture'
        assert (first,queued)==saved
        clock.now=1.145;fresh=job(3,2,.3,1.14);original=copy.deepcopy(fresh)
        slot.submit(fresh);wait(lambda:len(published)>=3);accepted=published[-1]
        assert accepted['error'] is None and accepted['discarded_reason'] is None
        assert len(session.requests)==1 and len(session.resets)==1
        packet,remaining=session.requests[0]
        assert packet==dict(op='act',observation=fresh['observation'])
        assert remaining==pytest.approx(fresh['observation']['wall_deadline']-1.145)
        for key in IDENTITY:
            assert type(accepted['value'][key]) is type(fresh['observation'][key])
            assert accepted['value'][key]==fresh['observation'][key]
        assert fresh==original and not session.stopped
    finally:close(slot,session)
    assert session.closed==1 and session.stopped


@pytest.mark.parametrize('frame,sim,capture_wall',[(0,.3,1.14),(2,.1,1.14),(2,.3,1.134)])
def test_pb_new_seq_cannot_relabel_pre_reset_frame_sim_or_capture_wall(tmp_path,frame,sim,capture_wall):
    clock,registry,session,slot,published=fixture(tmp_path)
    try:
        session.reset_release.set();slot.submit(job(1,0,.1,1.));wait(lambda:len(published)>=1)
        clock.now=1.135;candidate=job(2,frame,sim,capture_wall);original=copy.deepcopy(candidate)
        slot.submit(candidate);wait(lambda:len(published)>=2)
        assert published[-1]['discarded_reason']=='reset_observation_discarded_waiting_for_new_capture'
        assert published[-1]['error'] is None and not session.requests and candidate==original
    finally:close(slot,session)


def test_reset_failure_remains_sticky_and_does_not_turn_into_pending_localization(tmp_path):
    clock,registry,session,slot,published=fixture(tmp_path,fail=True)
    try:
        session.reset_release.set();slot.submit(job(1,0,.1,1.));wait(lambda:len(published)>=1)
        assert published[0]['error']=='RuntimeError' and published[0]['discarded_reason'] is None
        assert published[0]['value'] is None and session.stopped and session.closed==1
        consuming=threading.Event();consumed=threading.Event();again=threading.Event();original_get=slot.pending.get
        def get(*args,**kwargs):
            consuming.set()
            if consumed.is_set():again.set()
            value=original_get(*args,**kwargs);consumed.set();return value
        slot.pending.get=get
        assert consuming.wait(1.)  # Previous in-flight get must finish first.
        clock.now=1.145;slot.submit(job(2,2,.3,1.14))
        assert consumed.wait(1.) and again.wait(1.)
        assert len(published)==1 and not session.requests and len(session.resets)==1
    finally:close(slot,session)
