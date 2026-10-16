"""Actual MuJoCo manual target + synthetic joins; no native/GL qualification."""
import copy
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest
from rm_match.platform_v2.backend import MuJoCoBackend
from rm_match.platform_v2.control import Rejected
from rm_match.platform_v2.runtime import PlatformRuntime
from rm_match.platform_v2.test_control import Clock
from tools.native_target_motion import ScriptedTargetMotion,target_velocity


@pytest.fixture
def scene():
    clock=Clock();backend=MuJoCoBackend();events=[];holder=[]
    def trace(row):
        events.append(row)
        if holder and not holder[0].closed:holder[0].consumed(row)
    runtime=PlatformRuntime(backend,clock=clock,trace=trace,telemetry_publish_interval_s=.02)
    target=ScriptedTargetMotion(runtime.control,backend,'blue_infantry',.08);holder.append(target)
    try:yield clock,backend,runtime,target,events
    finally:target.close();runtime.close()


def tick(scene,count=1):
    clock,_,runtime,target,_=scene
    for _ in range(count):target.before_step();runtime.step_once();clock.advance(.002)


def test_actual_motion_uses_scoped_original_windows_and_close_revokes(scene):
    clock,backend,runtime,target,events=scene;tick(scene,1500)
    with pytest.raises(Rejected,match='robot_scope_forbidden'):
        runtime.control.claim(target._token,'red_sentry',['motion'])
    assert all(w['issued_wall']<w['input_expires']<=w['expires_wall']<=w['issued_wall']+.15 for w in target.windows.values())
    assert target.bad_consumptions==0 and target.active_consumptions==1500
    raw={};consumed={}
    # Fabricated native receipt headers ONLY test exact audit joining, never inference.
    for fid,sample in enumerate(target.samples[100::30],1):
        raw[fid]=dict(capture_sim_time=sample['sim_time'])
        consumed[fid]=dict(episode=sample['episode'],budget=dict(frame_id=fid,
            episode=sample['episode'],capture_sim_time=sample['sim_time']))
    target.close();report=target.report(raw,consumed)
    assert report['displacement_m']>=.15 and report['original_manual_authority_and_motion_proven']
    assert report['distinct_moving_actuated_frames']>=10
    assert report['native_target_association_verified'] is False
    assert report['moving_target_tracking_qualified'] is False
    runtime.step_once()
    assert backend.last_commands['blue_infantry']['force_x']==backend.last_commands['blue_infantry']['force_y']==0.
    assert all(runtime.control.leases['blue_infantry',c].owner is None for c in ('motion','gimbal','fire'))
    # Wrong original source time/episode cannot be rescued by the observed motion.
    for receipt in consumed.values():receipt['budget']['episode']+=1
    assert target.report(raw,consumed)['distinct_moving_actuated_frames']==0


def test_sender_stall_does_not_extend_manual_deadline(scene):
    clock,backend,runtime,target,events=scene;tick(scene)
    clock.now=next(iter(target.windows.values()))['input_expires']
    runtime.step_once()  # Deliberately no fresh target packet at the exact deadline.
    receipt=next(e for e in reversed(events) if e['event']=='actuator_consumed' and e['robot_id']=='blue_infantry')
    assert receipt['target']['motion'] is None
    assert backend.last_commands['blue_infantry']['force_x']==backend.last_commands['blue_infantry']['force_y']==0.


@pytest.mark.parametrize('field',['owner','epoch','seq','expired','future_window','oversized_window'])
def test_tampered_target_consumption_never_supplies_motion_proof(scene,field):
    _,_,_,target,events=scene;tick(scene)
    receipt=copy.deepcopy(next(e for e in events if e['event']=='actuator_consumed' and e['robot_id']=='blue_infantry' and e['phase']=='integration_entry'))
    lease=receipt['manual_inputs']['motion'];window=target.windows[lease['input_window_id']]
    if field=='owner':lease['owner']='other_owner'
    elif field=='epoch':lease['epoch']+=1
    elif field=='seq':lease['seq']+=1
    elif field=='expired':lease['input_expires']=receipt['consume_wall']
    elif field=='future_window':window['issued_wall']=receipt['consume_wall']+.01
    elif field=='oversized_window':window['expires_wall']=window['issued_wall']+.2
    target.consumed(receipt)
    assert target.bad_consumptions==1


def test_reset_does_not_reclaim_old_motion_epoch(scene):
    _,backend,runtime,target,_=scene;tick(scene)
    backend._sim.reset()
    with pytest.raises(ValueError,match='episode reset'):target.before_step()


def load_smoke():
    spec=importlib.util.spec_from_file_location('moving_native_smoke',Path(__file__).resolve().parents[1]/'tools/smoke_wsl_native_live.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


@pytest.mark.parametrize('bad',[True,False,0,.029,.151,-.151,float('nan'),float('inf'),'0.08',10**500])
def test_invalid_target_command_cannot_start_resources(bad):
    with pytest.raises(ValueError):target_velocity(bad)
    with pytest.raises(ValueError):load_smoke().build_plan('wsl_stdio_v1',moving_target_vy_mps=bad)


def test_default_plan_and_static_qualification_do_not_inherit_moving_pass():
    smoke=load_smoke();assert smoke.build_plan('wsl_stdio_v1')==smoke.PLAN
    plan=smoke.build_plan('wsl_stdio_v1',moving_target_vy_mps=.08)
    assert plan['configuration']['moving_target']['robot_id']=='blue_infantry'
    assert plan['configuration']['moving_target']['algorithm_input'] is False
    assert plan['criteria']['minimum_physics_rtf']==.98
    assert plan['configuration']['camera_native_budget_s']==.08 and plan['configuration']['server_input_window_s']==.15
    base=importlib.util.spec_from_file_location('moving_measurement_fixture',Path(__file__).with_name('test_wsl_native_live_classification.py'))
    fixture=importlib.util.module_from_spec(base);base.loader.exec_module(fixture)
    measured=fixture.measured();measured['configuration']=copy.deepcopy(plan['configuration'])
    for wrong in (None,False,1):
        measured['original_target_motion_proven']=wrong
        assert not smoke.classify(measured,plan=plan)['live_moving_scene_chain_qualified']
    measured['original_target_motion_proven']=True
    result=smoke.classify(measured,plan=plan)
    assert result['live_moving_scene_chain_qualified'] and not result['live_static_chain_qualified']
    assert result['moving_target_tracking_qualified'] is False
    assert 'live_moving_target_chain_qualified' not in result
    assert not result['full_match_qualified']


@pytest.mark.parametrize('bad',['nan','0','0.2'])
def test_cli_rejects_motion_before_running_native(bad):
    smoke=load_smoke()
    with patch.object(smoke,'run') as run,pytest.raises(SystemExit):
        smoke.main(['--moving-target-vy-mps',bad])
    run.assert_not_called()
