#!/usr/bin/env python3
"""Bounded Windows NVIDIA/MuJoCo + explicit WSL native live diagnostic.

Default invocation prints the fixed plan without starting a renderer or process.
No offline clock, barrier, slower physics target or substituted sensor input.
"""
from __future__ import annotations
import argparse
from collections import Counter
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import threading
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PHASE_DETAIL_STRIDE=50
PLAN = dict(schema='polar.wsl.native.live-plan.v1',
    configuration=dict(robot_count=6, timestep_s=.002, resolution=[1440,1080],
        total_fps=15, active_views=1, real_time_factor_limit=1.,
        camera_native_budget_s=.08, server_input_window_s=.15, manual_fire=False,
        native_transport='wsl_stdio_v1',
        clock='Windows time.perf_counter, wall_deadline_live'),
    scene=dict(red_sentry_xy_m=[-3.5,3.], blue_infantry_xy_m=[-1.2,3.],
        initial_velocity='zero, remaining public analytic 3v3 scene unchanged',
        truth_boundary='Initial scene is audit-only; native input is actual BGR/calibration/own capture-state'),
    setup=dict(renderer_ready_bound_s=15., native_ready_bound_s=20.,
        before_timed_run='No capture, inference, physics or clock substitution during startup'),
    measurement=dict(seconds_min=10., seconds_max=20., include_first_capture=True,
        stages=['exposure_to_raw_encode_end', 'raw_encode_end_to_adapter_enqueue',
            'adapter_enqueue_to_native_request', 'native_request_to_native_result',
            'native_result_to_actuator_consume', 'exposure_to_actuator_consume'],
        distributions=['sample_count','p50_ms','p95_ms','p99_ms','max_ms'],
        logging='In-memory small event records; first proven physical integration per source frame, all phase counters'),
    criteria=dict(minimum_physics_rtf=.98, minimum_raw_frames=30,
        minimum_native_results=10, minimum_distinct_native_actuated_frames=10,
        all_raw_encode_ages_at_most_s=.08, all_native_result_ages_at_most_s=.08,
        all_actuator_wall_and_sim_ages_at_most_s=.08,
        exact_render_native_pixel_binding=True, source_unchanged=True,
        reviewed_sdk_admission_and_window_ack=True, clean_shutdown=True),
    scope='Bounded public-static-scene live diagnostic only; not full-match, aim accuracy, GUI or hardware qualification')


def build_plan(transport,*,private_native_pixels=False,raw_base64_codec='stdlib_chunked',host_opencv_threads=None,
        host_python_switch_interval_ms=None,authority_affinity_mask=None,robot_id='red_sentry',native_robot_scope=None,profile_phases=False,
        camera_capture_policy='latest_pending',telemetry_publish_interval_ms=0.,moving_target_vy_mps=None,gimbal_servo='position',gimbal_yaw_gain=1.,camera_renderer_mode='thread',display_jpeg_codec='pillow_jpeg85'):
    if transport not in ('wsl_stdio_v1','wsl_stdio_bgr_v2','wsl_async_bgr_v3'):raise ValueError('Explicit reviewed transport required')
    if type(private_native_pixels) is not bool:raise ValueError('Explicit boolean private pixel mode required')
    if type(raw_base64_codec) is not str or raw_base64_codec not in ('stdlib_chunked','pybase64_1_5_1'):
        raise ValueError('Explicit reviewed raw codec required')
    plan=copy.deepcopy(PLAN)
    from rm_match.platform_v2.camera import DISPLAY_JPEG_CODECS
    if type(display_jpeg_codec) is not str or display_jpeg_codec not in DISPLAY_JPEG_CODECS:
        raise ValueError('Unknown display JPEG codec')
    if display_jpeg_codec!='pillow_jpeg85':
        plan['configuration']['display_jpeg_codec']=display_jpeg_codec
        plan['criteria']['display_jpeg_codec_matches_plan']=True
        plan['scope']+='; explicit display-only JPEG85 encoder, original native RGB/BGR chain unchanged'
    from rm_match.platform_v2.camera import RENDERER_MODES
    if type(camera_renderer_mode) is not str or camera_renderer_mode not in RENDERER_MODES:
        raise ValueError('Unknown camera renderer mode')
    if camera_renderer_mode!='thread':
        plan['configuration']['camera_renderer_mode']=camera_renderer_mode
        plan['criteria']['camera_renderer_configuration_matches_plan']=True
        plan['scope']+='; opt-in owned MuJoCo render process, original exposure and actuator gates retained'
    from rm_match.platform_v2.gimbal_servo import servo_mode,yaw_gain
    gain=yaw_gain(gimbal_yaw_gain)
    if gain!=1.:
        if servo_mode(gimbal_servo)!='position_gravity_v1':raise ValueError('Explicit yaw gain requires position_gravity_v1 servo')
        plan['configuration']['gimbal_yaw_gain']=gain
    if servo_mode(gimbal_servo)!='position':
        plan['configuration']['gimbal_servo']=gimbal_servo
        plan['criteria']['gimbal_servo_configuration_matches_plan']=True
        plan['scope']+='; explicit verified own-model gravity feedforward, unchanged physical model and raw algorithm reference'
    from rm_match.platform_v2.runtime import telemetry_publish_interval
    if type(telemetry_publish_interval_ms) not in (int,float):
        raise ValueError('Explicit numeric telemetry interval required')
    interval=telemetry_publish_interval(telemetry_publish_interval_ms/1000.)
    if interval>0:
        plan['configuration']['telemetry_publish_interval_s']=interval
        plan['criteria']['telemetry_publication_matches_plan']=True
        plan['scope']+='; explicit historical display sampling only; physics, sensors, guards and receipt traces retain original cadence'
    from rm_match.platform_v2.camera import CAPTURE_POLICIES
    if type(camera_capture_policy) is not str or camera_capture_policy not in CAPTURE_POLICIES:
        raise ValueError('Unknown camera capture policy')
    if camera_capture_policy!='latest_pending':
        plan['configuration']['camera_capture_policy']=camera_capture_policy
        plan['criteria']['camera_capture_policy_matches_plan']=True
        plan['scope']+='; render-ready exposure defers new snapshots while GL/encoding is busy; frame rate may decrease'
    from rm_match.match_model import ROSTER
    from rm_match.platform_v2.native_robot_scope import load_native_robot_scope
    roster={rid:(team,role) for rid,team,role in ROSTER}
    if type(robot_id) is not str or robot_id not in roster:raise ValueError('Live diagnostic requires a declared scene robot')
    scope=load_native_robot_scope(native_robot_scope)
    # Check the same source identity later enforced on actual own measurements.
    actor=scope.match(robot_id,*roster[robot_id])
    if moving_target_vy_mps is not None:
        from tools.native_target_motion import target_velocity
        velocity=target_velocity(moving_target_vy_mps)
        target=('blue' if actor.team=='red' else 'red')+'_infantry'
        plan['configuration']['moving_target']=dict(robot_id=target,vy_mps=velocity,
            profile='scripted_manual_body_velocity_v1',algorithm_input=False)
        plan['criteria']['original_target_motion_proven']=True
        plan['scope']='Bounded moving-scene diagnostic, stationary shooter; native target association is unverified; scripted manual target motion is not navigation/decision; not target-tracking, accuracy, shooting, GUI, moving-shooter or full-match qualification'
    if native_robot_scope is not None or robot_id!='red_sentry':
        plan['configuration']['robot_id']=robot_id
        plan['configuration']['native_robot_scope']=dict(path=None if native_robot_scope is None else str(Path(native_robot_scope).absolute()),
            sha256=scope.sha256,team=actor.team,role=actor.role,referee_id=actor.referee_id,stationary_only=True)
        target=('blue' if actor.team=='red' else 'red')+'_infantry'
        sign=1 if actor.team=='red' else -1
        plan['scene']={robot_id+'_xy_m':[-3.5*sign,3.],target+'_xy_m':[-1.2*sign,3.],
            'initial_velocity':'zero, remaining public analytic 3v3 scene unchanged',
            'truth_boundary':PLAN['scene']['truth_boundary']}
    from rm_match.platform_v2.host_scheduling import switch_interval_ms,affinity_mask
    if host_python_switch_interval_ms is not None:
        plan['configuration']['host_python_switch_interval_ms']=switch_interval_ms(host_python_switch_interval_ms)
        plan['criteria']['host_scheduling_applied_and_restored']=True
    if authority_affinity_mask is not None:
        plan['configuration']['authority_affinity_mask']=affinity_mask(authority_affinity_mask)
        plan['criteria']['host_scheduling_applied_and_restored']=True
    if host_opencv_threads is not None:
        if type(host_opencv_threads) is not int or not 1<=host_opencv_threads<=32:
            raise ValueError('Explicit host OpenCV threads must be an integer within 1..32')
        plan['configuration']['host_opencv_threads']=host_opencv_threads
        plan['criteria']['host_opencv_setting_unchanged']=True
    plan['configuration']['native_transport']=transport
    if transport=='wsl_async_bgr_v3':
        plan['criteria']['original_async_transactions_accounted']=True
        plan['measurement']['logging']+='; pending/late-discard are separate, never counted as timely NN or actuation'
        plan['scope']+='; async qualification covers timely accepted samples, not an all-inferences-under-80ms claim'
    if raw_base64_codec!='stdlib_chunked':
        plan['configuration']['raw_base64_codec']=raw_base64_codec
        plan['criteria']['exact_raw_codec_identity']=True
    if private_native_pixels:
        plan['configuration'].update(private_native_pixels=True,
            input_publication='sealed_actual_rgb_before_public_base64')
        if transport in ('wsl_stdio_bgr_v2','wsl_async_bgr_v3'):
            plan['configuration']['rgb_trace_strategy']='archived_bgr_postclose_exact_channel_swap'
            plan['criteria']['postclose_actual_pixel_audit']=True
        plan['measurement']['stages']+=['exposure_to_private_pixels','private_pixels_to_adapter_enqueue']
        plan['measurement']['logging']+='; actual private cache publish timestamp, public encoding measured separately'
    if type(profile_phases) is not bool:raise ValueError('Explicit phase profiling must be boolean')
    if profile_phases:
        if transport!='wsl_async_bgr_v3':raise ValueError('Phase profiling requires async native transport')
        plan['configuration'].update(host_phase_timing='bounded_wall_thread_cpu_v1',host_phase_capacity=262144,
            authority_phase_detail_stride=PHASE_DETAIL_STRIDE)
        plan['criteria']['host_phase_trace_complete']=True
        plan['scope']+='; opt-in bounded thread/wall phase instrumentation adds diagnostic overhead'
    return plan


def distribution(values):
    values = sorted(values)
    def percentile(fraction):
        if not values:return None
        pos=(len(values)-1)*fraction;low=int(pos);high=min(low+1,len(values)-1)
        return (values[low]+(values[high]-values[low])*(pos-low))*1000
    return dict(sample_count=len(values),p50_ms=percentile(.5),p95_ms=percentile(.95),
        p99_ms=percentile(.99),max_ms=None if not values else values[-1]*1000,
        within_80ms_count=sum(0<=v<=.08 for v in values))


def run_durations(timing,sim_time):
    """Absent authority timestamps are unmeasured; cleanup has a separate span."""
    start=timing.get('start')
    def duration(key):
        end=timing.get(key)
        if any(type(x) not in (int,float) or not math.isfinite(x) for x in (start,end)):return None
        return end-start if end>=start else None
    physics=duration('physics_end');combined=duration('end')
    return dict(physics_wall_s=physics,run_and_cleanup_wall_s=combined,
        physics_rtf=sim_time/physics if physics is not None and physics>0 else None,
        run_and_cleanup_rtf=sim_time/combined if combined is not None and combined>0 else None,
        scope='Authority start to entry into runtime.close for physics; runtime.run return includes cleanup')


def collect_transport_evidence(native_root,process):
    """Inspect only this fresh run, including a failed preparation's owned files."""
    selected=getattr(process,'evidence_out',None)
    candidates=[Path(selected)] if selected is not None else sorted(Path(native_root).glob('binding_*/wsl*supervisor_*'))
    collection=dict(candidate_count=len(candidates),selected_directory=None,
        scope='Fresh run directory only; files alone do not establish readiness or clean shutdown')
    if len(candidates)!=1:return {},collection
    collection['selected_directory']=str(candidates[0]);evidence={}
    for name in ('WORKER_STARTUP.json','STARTUP_PHASES.json','PRE_NATIVE_EXIT.json',
        'OWNED_CHILD.json','STARTUP.json','CLEANUP.json','HOST_TRACE.json','SUPERVISOR_ERROR.json','FINAL_IO.json','NATIVE_EVENTS.json'):
        path=candidates[0]/name
        if path.is_file():evidence[name]=json.loads(path.read_text(encoding='utf-8'))
    return evidence,collection


def expected_shutdown_rejection(error, runtime, client_error_type):
    """Only the server's exact terminal rejection after actual stop is expected."""
    return (isinstance(error,client_error_type) and getattr(error,'code',None)=='runtime_stopped'
        and getattr(runtime,'_closed',False) is True and runtime.stop_event.is_set()
        and runtime.control.stopped is True)


def image_stage_summary(events):
    """Timing fields coexist with converter/clock metadata in real telemetry."""
    samples={}
    for event in events:
        if event['event']=='native_frame_prepare':
            for stage,duration in event.get('image_stages',{}).items():
                if stage.endswith('_s') and type(duration) in (int,float):
                    samples.setdefault(stage,[]).append(duration)
    return {stage:distribution(values) for stage,values in samples.items()}


def native_sensor_budget_valid(budget):
    fields={'robot_id','episode','frame_id','capture_wall','capture_sim_time','wall_deadline','sim_deadline'}
    return (type(budget) is dict and set(budget)==fields
        and type(budget['robot_id']) is str and 0<len(budget['robot_id'])<=128
        and all(type(budget[k]) is int and 0<=budget[k]<=2**53-1 for k in ('episode','frame_id'))
        and all(type(budget[k]) in (int,float) and math.isfinite(budget[k]) and 0<=budget[k]<=1e12
            for k in ('capture_wall','capture_sim_time','wall_deadline','sim_deadline'))
        and budget['capture_wall']<budget['wall_deadline']<=budget['capture_wall']+.08
        and budget['capture_sim_time']<budget['sim_deadline']<=budget['capture_sim_time']+.08)


def actuator_receipt_budget_checks(receipt):
    """Original absolute limits: wall is exclusive, sim is inclusive; no epsilon."""
    if type(receipt) is not dict:return dict(wall=False,sim=False)
    budget=receipt.get('budget')
    if not native_sensor_budget_valid(budget):return dict(wall=False,sim=False)
    if (any(type(receipt.get(k)) is not type(budget[k]) or receipt[k]!=budget[k] for k in ('robot_id','episode'))
        or ('frame_id' in receipt and (type(receipt['frame_id']) is not int or receipt['frame_id']!=budget['frame_id']))):
        return dict(wall=False,sim=False)
    wall=receipt.get('consume_wall');sim=receipt.get('consume_sim_time')
    return dict(wall=type(wall) in (int,float) and math.isfinite(wall) and budget['capture_wall']<=wall<budget['wall_deadline'],
        sim=type(sim) in (int,float) and math.isfinite(sim) and budget['capture_sim_time']<=sim<=budget['sim_deadline'])


def _typed_equal(a,b):
    if type(a) is not type(b):return False
    if type(a) is dict:return a.keys()==b.keys() and all(_typed_equal(a[k],b[k]) for k in a)
    if type(a) is list:return len(a)==len(b) and all(_typed_equal(x,y) for x,y in zip(a,b))
    return a==b


def physical_integration_checks(receipt,boundary,actual_ctrl,actual_command):
    """Audit after mj_step; a preparatory write never proves integration.

    The engine's original uniform entry sample is NOT its later mj_step call.
    Both must retain the original exposure budget. This cannot grant authority.
    """
    numeric=lambda v:type(v) in (int,float) and math.isfinite(v)
    r=receipt if type(receipt) is dict else {}
    b=boundary if type(boundary) is dict else {}
    budget=r.get('budget');rid=r.get('robot_id')
    valid_budget=native_sensor_budget_valid(budget)
    start=b.get('integration_start_wall');call=b.get('integration_call_wall');post=b.get('post_step_wall')
    times=all(numeric(v) for v in (start,call,post)) and start<=call<=post
    command_fields=('force_x','force_y','yaw_torque','gimbal_yaw','gimbal_pitch')
    controls=(type(actual_command) is dict and type(actual_ctrl) is list and len(actual_ctrl)==5
        and all(numeric(v) for v in actual_ctrl)
        and all(numeric(actual_command.get(k)) and actual_command[k]==v for k,v in zip(command_fields,actual_ctrl))
        and actual_command.get('fire') is False)
    target=r.get('target')
    return dict(entry_phase=r.get('phase')=='integration_entry',
        original_entry_budget=all(actuator_receipt_budget_checks(r).values()),
        episode=_typed_equal(r.get('episode'),b.get('episode')) and type(r.get('episode')) is int,
        entry_wall=times and _typed_equal(r.get('consume_wall'),start),
        entry_sim=numeric(b.get('sim_time')) and _typed_equal(r.get('consume_sim_time'),b.get('sim_time')),
        actual_call_within_original_wall_budget=bool(valid_budget and times and budget['capture_wall']<=call<budget['wall_deadline']),
        final_target=(type(target) is dict and type(target.get('gimbal')) is dict and target.get('fire') is False
            and _typed_equal(target,b.get('targets',{}).get(rid))),
        final_budget=bool(valid_budget and _typed_equal(budget,b.get('output_budgets',{}).get(rid))),
        actual_controls=controls)


def classify(measurements,*,plan=None):
    """Late/rejected results and empty measurements never establish live pass."""
    plan=PLAN if plan is None else plan
    c=plan['criteria'];m=measurements
    checks=dict(configuration_unchanged=m.get('configuration')==plan['configuration'],
        bounded_real_wall_run=type(m.get('duration_s')) in (int,float) and 10<=m['duration_s']<=20.5,
        physics_rtf=type(m.get('physics_rtf')) in (int,float) and m['physics_rtf']>=c['minimum_physics_rtf'],
        raw_sample_count=m.get('raw_frames',0)>=c['minimum_raw_frames'],
        native_sample_count=m.get('native_results',0)>=c['minimum_native_results'],
        no_sticky_adapter_fault=m.get('adapter_error_count')==0,
        all_native_requests_completed=m.get('incomplete_native_requests')==0,
        actual_evidence_preserved=m.get('native_evidence_closed') is True,
        actual_native_actuation=m.get('distinct_native_actuated_frames',0)>=c['minimum_distinct_native_actuated_frames'],
        physical_integration_evidence=m.get('physical_integration_evidence') is True,
        native_sensor_budget_80ms=m.get('native_sensor_budget_80ms') is True,
        actual_transport_matches_plan=m.get('actual_transport_matches_plan') is True,
        exact_sensor_pixel_binding=m.get('exact_sensor_pixel_binding') is True,
        source_unchanged=m.get('source_unchanged') is True,
        sdk_admission=m.get('sdk_admission') is True,
        window_acknowledged=m.get('window_acknowledged') is True,
        zero_fire=m.get('fire_true')==0,
        clean_shutdown=m.get('clean_shutdown') is True,
        runtime_error_free=not m.get('errors'))
    for key in ('raw_ages_s','native_result_ages_s','actuator_wall_ages_s','actuator_sim_ages_s'):
        values=m.get(key,[])
        checks[key]=bool(values) and all(type(v) in (int,float) and 0<=v<=.08 for v in values)
        if key.startswith('actuator_') and 'actuator_budget_receipts' in m:
            receipts=m['actuator_budget_receipts'];axis='wall' if key=='actuator_wall_ages_s' else 'sim'
            capture='capture_wall' if axis=='wall' else 'capture_sim_time'
            consume='consume_wall' if axis=='wall' else 'consume_sim_time'
            checks[key]=(type(receipts) is list and bool(receipts) and len(receipts)==len(values)
                and all(actuator_receipt_budget_checks(r)[axis] and type(v) is type(r[consume]-r['budget'][capture])
                    and v==r[consume]-r['budget'][capture] for r,v in zip(receipts,values)))
    if c.get('exact_raw_codec_identity'):
        checks['raw_codec_identity_unchanged']=m.get('raw_codec_identity_unchanged') is True
    if c.get('postclose_actual_pixel_audit'):
        checks['postclose_actual_pixel_audit']=m.get('postclose_actual_pixel_audit') is True
    if c.get('host_phase_trace_complete'):
        checks['host_phase_trace_complete']=m.get('host_phase_trace_complete') is True
    if c.get('host_opencv_setting_unchanged'):
        checks['host_opencv_setting_unchanged']=m.get('host_opencv_setting_unchanged') is True
    if c.get('camera_capture_policy_matches_plan'):
        checks['camera_capture_policy_matches_plan']=m.get('camera_capture_policy_matches_plan') is True
    if c.get('telemetry_publication_matches_plan'):
        checks['telemetry_publication_matches_plan']=m.get('telemetry_publication_matches_plan') is True
    if c.get('gimbal_servo_configuration_matches_plan'):
        checks['gimbal_servo_configuration_matches_plan']=m.get('gimbal_servo_configuration_matches_plan') is True
    if c.get('camera_renderer_configuration_matches_plan'):
        checks['camera_renderer_configuration_matches_plan']=m.get('camera_renderer_configuration_matches_plan') is True
    if c.get('display_jpeg_codec_matches_plan'):
        checks['display_jpeg_codec_matches_plan']=m.get('display_jpeg_codec_matches_plan') is True
    if c.get('original_async_transactions_accounted'):
        checks['original_async_transactions_accounted']=m.get('original_async_transactions_accounted') is True
    if c.get('host_scheduling_applied_and_restored'):
        checks['host_scheduling_applied_and_restored']=m.get('host_scheduling_applied_and_restored') is True
    moving=c.get('original_target_motion_proven') is True
    if moving:checks['original_target_motion_proven']=m.get('original_target_motion_proven') is True
    result=dict(checks=checks,live_static_chain_qualified=not moving and all(checks.values()),
        full_match_qualified=False,hardware_qualified=False,visible_qt_qualified=False,
        rejected_or_failed_criteria=[k for k,v in checks.items() if not v])
    if moving:
        result['live_moving_scene_chain_qualified']=all(checks.values())
        result['moving_target_tracking_qualified']=False
    return result


def stage_measurements(events, raw_frames, consumed_frames,*,private_native_pixels=False,pixel_audit=None):
    """Join only host-clock source frame identities; never use Linux clock values."""
    enqueues={};requests={};results={};stages={k:[] for k in PLAN['measurement']['stages']}
    publications={};unpublished={};matched=True;inapplicable={}
    if private_native_pixels:
        stages.update(exposure_to_private_pixels=[],private_pixels_to_adapter_enqueue=[])
        inapplicable['raw_encode_end_to_adapter_enqueue']='private native input is published before public base64 completion'
    def finite_number(v):return type(v) in (int,float) and math.isfinite(v)
    def actual_sha(v):return type(v) is str and bool(v)
    audit_proofs={}
    if (type(pixel_audit) is dict and pixel_audit.get('schema')=='polar.live.native-pixel-audit.v1'
        and pixel_audit.get('clean') is True and pixel_audit.get('errors')==[]
        and type(pixel_audit.get('proofs')) is list):
        for proof in pixel_audit['proofs']:
            fid=proof.get('frame_id')
            if fid in audit_proofs:matched=False
            audit_proofs[fid]=proof
    def rgb_sha(event,frame_id):
        sha=event.get('raw_rgb_sha256')
        if actual_sha(sha):return sha
        if (not private_native_pixels or sha is not None
            or event.get('rgb_trace_strategy')!='archived_bgr_postclose_exact_channel_swap'):return None
        proof=audit_proofs.get(frame_id);raw=raw_frames.get(frame_id)
        if proof is None or raw is None:return None
        if (proof.get('original_capture_wall')!=raw.get('capture_wall')
            or proof.get('original_capture_sim_time')!=raw.get('capture_sim_time')
            or proof.get('original_capture_sim_time')!=event.get('capture_sim_time')
            or proof.get('observation_sim_time')!=event.get('observation_sim_time')
            or proof.get('raw_bgr_sha256')!=event.get('raw_bgr_sha256')
            or proof.get('derived_rgb_sha256')!=raw.get('raw_rgb_sha256')
            or proof.get('raw_rgb_sha256')!=raw.get('raw_rgb_sha256')
            or proof.get('shape')!=raw.get('shape') or proof.get('image_bytes')!=4665600
            or not finite_number(event.get('observation_sim_time'))
            or proof.get('original_control_time_ns')!=round(event['observation_sim_time']*1e9)
            or proof.get('strategy')!='archived_bgr_postclose_exact_channel_swap'
            or not any(all(identity.get(k)==event.get(k) and type(identity.get(k)) is type(event.get(k))
                for k in ('observed_seq','episode','binding_epoch')) for identity in proof.get('request_identities',[]))):return None
        return proof.get('derived_rgb_sha256')
    for event in events:
        kind=event['event']
        if kind=='adapter_enqueue':
            budget=event.get('sensor_budget')
            if budget:enqueues[event['observed_seq']]=event
        elif kind=='native_request':requests[event['frame_id']]=event
        elif kind=='native_result':results[event['frame_id']]=event
        elif kind=='private_pixels_published' and private_native_pixels:
            fid=event.get('frame_id')
            if fid in publications:matched=False
            publications[fid]=event
        elif kind=='private_publish_rejected' and private_native_pixels:
            fid=event.get('frame_id')
            if fid in unpublished:matched=False
            unpublished[fid]=event
    if private_native_pixels:
        if set(publications).intersection(unpublished) or set(publications).union(unpublished)!=set(raw_frames):matched=False
        for fid,rejection in unpublished.items():
            raw=raw_frames.get(fid)
            if (fid in requests or raw is None or raw.get('frame_id')!=fid
                or rejection.get('reason') not in ('no_native_consumer','runtime_stopped','camera_fault','episode_changed','capture_revoked','native_80ms_expired')
                or rejection.get('capture_wall')!=raw.get('capture_wall')
                or rejection.get('capture_sim_time')!=raw.get('capture_sim_time')
                or rejection.get('wall_clock')!='provider_monotonic'
                or not all(finite_number(v) for v in (rejection.get('wall_time'),raw.get('capture_wall'),raw.get('capture_sim_time'),raw.get('encoded_wall')))
                or not raw['capture_wall']<=rejection['wall_time']<=raw['encoded_wall']):matched=False
        for fid,publication in publications.items():
            raw=raw_frames.get(fid);published=publication.get('wall_time')
            valid=(raw is not None and raw.get('frame_id')==fid
                and publication.get('capture_wall')==raw.get('capture_wall')
                and publication.get('capture_sim_time')==raw.get('capture_sim_time')
                and publication.get('wall_clock')=='provider_monotonic' and actual_sha(raw.get('raw_rgb_sha256'))
                and all(finite_number(v) for v in (published,raw.get('capture_wall'),raw.get('capture_sim_time'),raw.get('encoded_wall')))
                and 0<=published-raw['capture_wall']<=.08 and published<=raw['encoded_wall'])
            if not valid:matched=False
            else:stages['exposure_to_private_pixels'].append(published-raw['capture_wall'])
    for frame_id,request in requests.items():
        raw=raw_frames.get(frame_id)
        if (raw is None or not actual_sha(raw.get('raw_rgb_sha256'))
            or raw.get('raw_rgb_sha256')!=rgb_sha(request,frame_id)):
            matched=False
        enqueue=enqueues.get(request['observed_seq'])
        if enqueue and enqueue['sensor_budget']['frame_id']!=frame_id:matched=False
        result=results.get(frame_id)
        if raw and enqueue and not private_native_pixels:
            stages['raw_encode_end_to_adapter_enqueue'].append(enqueue['host_received_wall']-raw['encoded_wall'])
        if private_native_pixels:
            publication=publications.get(frame_id)
            budget=None if enqueue is None else enqueue.get('sensor_budget')
            published=None if publication is None else publication.get('wall_time')
            valid=(publication is not None and raw is not None and budget is not None
                and raw.get('frame_id')==frame_id
                and budget.get('capture_wall')==raw.get('capture_wall')
                and budget.get('capture_sim_time')==raw.get('capture_sim_time')
                and request.get('capture_sim_time')==raw.get('capture_sim_time')
                and finite_number(published) and finite_number(enqueue.get('host_received_wall'))
                and published<=enqueue['host_received_wall']<=request['host_received_wall'])
            if not valid:matched=False
            else:stages['private_pixels_to_adapter_enqueue'].append(enqueue['host_received_wall']-published)
        if enqueue:
            stages['adapter_enqueue_to_native_request'].append(request['host_received_wall']-enqueue['host_received_wall'])
        if result:
            stages['native_request_to_native_result'].append(result['host_received_wall']-request['host_received_wall'])
        consume=consumed_frames.get(frame_id)
        if result and consume:
            stages['native_result_to_actuator_consume'].append(consume['consume_wall']-result['host_received_wall'])
    for raw in raw_frames.values():
        if all(finite_number(raw.get(k)) for k in ('encoded_wall','capture_wall')):
            stages['exposure_to_raw_encode_end'].append(raw['encoded_wall']-raw['capture_wall'])
        else:matched=False
    for consume in consumed_frames.values():
        stages['exposure_to_actuator_consume'].append(consume['consume_wall']-consume['budget']['capture_wall'])
    native_ages=[]
    for frame_id,result in results.items():
        request=requests.get(frame_id);raw=raw_frames.get(frame_id)
        if (request is None or raw is None or not actual_sha(rgb_sha(result,frame_id))
            or rgb_sha(result,frame_id)!=rgb_sha(request,frame_id)):
            matched=False
        if raw and finite_number(raw.get('capture_wall')):native_ages.append(result['host_received_wall']-raw['capture_wall'])
        elif raw:matched=False
    return dict(stages={k:distribution(v) for k,v in stages.items()},
        stage_samples_s=stages,stage_inapplicable=inapplicable,
        unpublished_private_frames={fid:row.get('reason') for fid,row in unpublished.items()},
        exact_sensor_pixel_binding=matched and bool(requests),
        raw_ages_s=stages['exposure_to_raw_encode_end'],native_result_ages_s=native_ages,
        actuator_budget_receipts=[dict(robot_id=x.get('robot_id'),episode=x.get('episode'),frame_id=fid,
            consume_wall=x['consume_wall'],consume_sim_time=x['consume_sim_time'],budget=copy.deepcopy(x['budget']))
            for fid,x in consumed_frames.items()],
        actuator_wall_ages_s=[x['consume_wall']-x['budget']['capture_wall'] for x in consumed_frames.values()],
        actuator_sim_ages_s=[x['consume_sim_time']-x['budget']['capture_sim_time'] for x in consumed_frames.values()])


def async_transaction_measurements(events,transport_evidence):
    """Account original transactions without treating pending or late as results.

    This is an additional v3 audit. Linux elapsed values never grant host
    authority. Actual fresh native_result/physical receipt counts still supply
    the unchanged minimum sample and 80ms qualification checks.
    """
    from rm_match.platform_v2.contracts import IDENTITY
    from rm_match.integrations.wsl_aim_async_worker import (SCHEMA,TRANSPORT,MAX_IMAGE,
        OWNERSHIP_FIELDS,same_identity,validate_source_context)
    queued={};terminal={};started={};accepted={};stdout_stamps={};valid=True
    dispositions=Counter()
    def key(row):return row.get('request_id')
    def matches(row,request):
        return (type(row.get('source_context')) is dict and set(row['source_context'])==set(IDENTITY)
            and all(type(row['source_context'].get(k)) is type(request.get(k))
                and row['source_context'].get(k)==request.get(k) for k in IDENTITY)
            and all(type(row.get(k)) is type(request.get(k)) and row.get(k)==request.get(k)
                for k in ('frame_id','exposure_timestamp_ns','control_time_ns','raw_bgr_sha256')))
    for row in events:
        event=row['event'];serial=key(row)
        if event=='async_native_fault':valid=False
        if event=='async_transport_request':
            if type(serial) is not int or serial in queued:valid=False
            try:
                validate_source_context(row.get('source_context'))
                if not matches(row,row):valid=False
            except ValueError:valid=False
            queued[serial]=row
        elif event in ('async_native_started','async_native_stdout','async_late_discard','async_after_pending_discard',
                       'async_discarded_before_native','async_discarded_before_write','async_result_accepted80'):
            request=queued.get(serial)
            if request is None or not matches(row,request):valid=False;continue
            if event=='async_native_started':
                if serial in started or row.get('native_stdin_complete') is not True:valid=False
                started[serial]=row
            elif event=='async_result_accepted80':
                if serial in accepted or terminal.get(serial)!='async_native_stdout':valid=False
                accepted[serial]=row
                stamp=row.get('wall_time');decision=row.get('acceptance_decision_wall',stamp)
                if (type(stamp) not in (float,int) or not math.isfinite(stamp)
                    or type(decision) not in (float,int) or not math.isfinite(decision)
                    or not 0<=decision<=stamp or not decision<request['source_context']['wall_deadline']):valid=False
                if 'acceptance_decision_wall' in row:
                    # Separate the original host acceptance check from later
                    # log publication; never rewrite wall_time or infer a time
                    # for old evidence. The wrapper still withholds expired
                    # responses and every actuator retains the original budget.
                    deadline=row.get('original_host_deadline');original=request.get('original_host_deadline')
                    stdout=stdout_stamps.get(serial)
                    if (row.get('wall_clock')!='host_perf_counter' or type(deadline) not in (float,int)
                        or type(deadline) is not type(original) or deadline!=original
                        or not decision<deadline<=request['source_context']['wall_deadline']
                        or type(stdout) not in (float,int) or not request['wall_time']<=stdout<=decision):valid=False
            else:
                if serial in terminal and not (terminal[serial]=='async_native_stdout'
                    and event=='async_late_discard' and serial not in accepted):valid=False
                terminal[serial]=event;dispositions[event]+=1
                if event=='async_native_stdout':stdout_stamps[serial]=row.get('wall_time')
                if event in ('async_native_stdout','async_late_discard','async_after_pending_discard') and serial not in started:valid=False
    journal=transport_evidence.get('NATIVE_EVENTS.json',{})
    cleanup=transport_evidence.get('CLEANUP.json',{})
    native_events=journal.get('events',[]);host_trace=transport_evidence.get('HOST_TRACE.json',[])
    owned=transport_evidence.get('OWNED_CHILD.json',{});ready=transport_evidence.get('STARTUP.json',{})
    if any(row.get('event')=='async_native_fault' for row in host_trace):valid=False
    def exact_json(a,b):
        if type(a) is not type(b):return False
        if type(a) is dict:return set(a)==set(b) and all(exact_json(a[k],b[k]) for k in a)
        if type(a) is list:return len(a)==len(b) and all(exact_json(x,y) for x,y in zip(a,b))
        return a==b
    def owned_close_proven():
        if (type(owned) is not dict or type(cleanup) is not dict or type(ready) is not dict
            or type(journal) is not dict or type(native_events) is not list or type(host_trace) is not list):return False
        if any(k not in owned or type(cleanup.get(k)) is not type(owned[k]) or cleanup[k]!=owned[k]
            for k in OWNERSHIP_FIELDS):return False
        identity={k:owned[k] for k in OWNERSHIP_FIELDS}
        if (type(identity['run_id']) is not str or len(identity['run_id'])!=32
            or any(c not in '0123456789abcdef' for c in identity['run_id'])
            or type(identity['spec_sha256']) is not str or len(identity['spec_sha256'])!=64
            or any(c not in '0123456789abcdef' for c in identity['spec_sha256'])
            or type(identity['boot_id']) is not str or not identity['boot_id']
            or any(type(identity[k]) is not int or identity[k]<=0 for k in ('supervisor_pid','pid','pgid','leader_start_ticks'))
            or identity['pid']!=identity['pgid'] or identity['transport']!=TRANSPORT):return False
        if (any(cleanup.get(k) is not True for k in ('clean','reaped','group_empty','tmpfs_removed'))
            or cleanup.get('remaining_members')!=[] or cleanup.get('errors')!=[]
            or cleanup.get('reason') not in ('host_cancel','host_eof')):return False
        if (ready.get('event')!='ready' or ready.get('schema')!=SCHEMA or ready.get('transport')!=TRANSPORT
            or any(type(ready.get(k)) is not type(identity[v]) or ready[k]!=identity[v]
                for k,v in (('run_id','run_id'),('supervisor_pid','supervisor_pid'),('native_pid','pid'),('spec_sha256','spec_sha256')))
            or any(type(ready.get(k)) is not int or ready[k]!=0
                for k in ('native_ticks','inference_calls','camera_captures','physics_steps'))):return False
        ready_rows=[r for r in native_events if r.get('event')=='ready']
        closed=[r for r in host_trace if r.get('event')=='closed']
        return (len(ready_rows)==1 and exact_json(ready_rows[0],ready) and len(closed)==1
            and closed[0].get('clean') is True and closed[0].get('linux_child_reaped') is True
            and closed[0].get('native_not_spawned') is False and closed[0].get('errors')==[]
            and same_identity(journal.get('ownership'),identity))
    def native_matches(row,request):
        return (type(row.get('id')) is int and row['id']==request['request_id']
            and same_identity(row.get('source_context'),request.get('source_context'))
            and all(type(row.get(k)) is type(request.get(v)) and row.get(k)==request.get(v)
                for k,v in (('frame_id','frame_id'),('control_time_ns','control_time_ns'),
                            ('exposure_timestamp_ns','exposure_timestamp_ns'),('image_sha256','raw_bgr_sha256')))
            and type(row.get('bgr_bytes')) is int and row['bgr_bytes']==MAX_IMAGE)
    def cancellation_matches(row,request):
        return (owned_close_proven() and request is not None and row.get('reason')==cleanup['reason']
            and same_identity(row.get('ownership'),{k:owned[k] for k in OWNERSHIP_FIELDS}))
    cancelled=0;input_cancelled=0;unwritten_cancelled=0
    for row in native_events:
        event=row.get('event')
        if event not in ('native_cancelled','input_cancelled'):continue
        serial=row.get('id');request=queued.get(serial)
        okay=(cancellation_matches(row,request) and serial not in terminal and native_matches(row,request)
            and row.get('schema')==SCHEMA and row.get('transport')==TRANSPORT
            and row.get('clock_domain')=='linux_local_diagnostic_only')
        related=[r for r in native_events if type(r.get('id')) is int and r['id']==serial]
        if event=='native_cancelled':
            okay=(okay and not any(r.get('event') in ('result','input_cancelled','discarded_before_native') for r in related)
                and type(row.get('native_stdin_bytes_written')) is int and type(row.get('native_stdin_expected_bytes')) is int
                and 0<=row['native_stdin_bytes_written']<=row['native_stdin_expected_bytes']<=65536
                and row['native_stdin_expected_bytes']>0
                and (serial not in started or row['native_stdin_bytes_written']==row['native_stdin_expected_bytes']))
            label='owned_native_cancelled_at_close'
        else:
            admissions=[r for r in related if r.get('event')=='input_header_received']
            received=row.get('received_bgr_bytes');verified=row.get('payload_sha256_verified')
            okay=(okay and serial not in started and len(admissions)==1 and native_matches(admissions[0],request)
                and admissions[0].get('schema')==SCHEMA and admissions[0].get('transport')==TRANSPORT
                and admissions[0].get('clock_domain')=='linux_local_diagnostic_only'
                and admissions[0].get('header_validated') is True and row.get('header_validated') is True
                and type(admissions[0].get('received_bgr_bytes')) is int and type(received) is int
                and 0<=admissions[0]['received_bgr_bytes']<=received<=MAX_IMAGE
                and row.get('native_compute_started') is False and type(row.get('native_stdin_bytes_written')) is int
                and row['native_stdin_bytes_written']==0
                and ((row.get('phase')=='receiving_payload' and received<MAX_IMAGE and verified is False
                      and row.get('verified_image_sha256') is None)
                     or (row.get('phase')=='validated_payload' and received==MAX_IMAGE and verified is True
                         and row.get('verified_image_sha256')==request['raw_bgr_sha256']))
                and not any(r.get('event') in ('native_started','result','native_cancelled','discarded_before_native') for r in related))
            label='owned_input_cancelled_at_close'
        if not okay:valid=False;continue
        terminal[serial]=label;dispositions[label]+=1
        if event=='native_cancelled':cancelled+=1
        else:input_cancelled+=1
    for row in host_trace:
        if row.get('event')!='async_cancelled_before_write':continue
        serial=row.get('request_id');request=queued.get(serial)
        if (type(serial) is not int or not cancellation_matches(row,request) or serial in terminal or serial in started or not matches(row,request)
            or type(row.get('bgr_bytes')) is not int or row['bgr_bytes']!=MAX_IMAGE
            or row.get('phase')!='queued' or row.get('writer_joined') is not True
            or row.get('transport_write_attempted') is not False or row.get('transport_write_in_progress') is not False
            or type(row.get('transport_bytes_written')) is not int or row['transport_bytes_written']!=0
            or type(row.get('transport_expected_bytes')) is not int
            or not MAX_IMAGE<row['transport_expected_bytes']<=MAX_IMAGE+65536
            or any(type(r.get('id')) is int and r['id']==serial for r in native_events)):
            valid=False;continue
        terminal[serial]='owned_unwritten_cancelled_at_close';dispositions[terminal[serial]]+=1;unwritten_cancelled+=1
    wrappers={};wrapper_results=0;wrapper_expired=0
    for row in events:
        if row['event'] not in ('native_result','native_response_expired_before_action'):continue
        candidates=[]
        for serial,a in accepted.items():
            if (all(type(row.get(k)) is type(a.get(k)) and row.get(k)==a.get(k)
                    for k in ('robot_id','episode','binding_epoch','observed_seq','wall_deadline',
                              'frame_id','capture_sim_time','raw_bgr_sha256'))
                and type(row.get('observation_sim_time')) is type(a['sim_time'])
                and row['observation_sim_time']==a['sim_time']):candidates.append((serial,a))
        if len(candidates)!=1:valid=False;continue
        serial,a=candidates[0];original=a.get('response');response=row.get('response');stamp=row.get('wall_time')
        # A timely bridge return may expire before the wrapper regains the GIL.
        # This is a withheld original response, never another successful sample.
        same_response=(exact_json(response,original) or (type(original) is dict
            and exact_json(response,dict(original,episode=a['episode'],should_control=original.get('tracking')))))
        expired=row['event']=='native_response_expired_before_action'
        if (serial in wrappers or not same_response or row.get('wall_clock')!='host_perf_counter'
            or type(stamp) not in (int,float) or not math.isfinite(stamp)
            or (expired and stamp<a['wall_deadline']) or (not expired and not 0<=stamp<a['wall_deadline'])):
            valid=False;continue
        wrappers[serial]=row['event']
        if expired:wrapper_expired+=1
        else:wrapper_results+=1
    if set(wrappers)!=set(accepted):valid=False
    incomplete=len(set(queued)-set(terminal))
    return dict(original_async_transactions_accounted=bool(queued) and valid and incomplete==0,
        async_queued_transactions=len(queued),async_actual_complete_stdin=len(started),
        async_timely_accepted_results=len(accepted),async_owned_cancelled_at_close=cancelled,
        async_wrapper_native_results=wrapper_results,async_expired_before_action=wrapper_expired,
        async_owned_input_cancelled_at_close=input_cancelled,async_owned_unwritten_cancelled_at_close=unwritten_cancelled,
        async_terminal_dispositions=dict(dispositions),async_incomplete_transactions=incomplete,
        async_pending_statuses=sum(row['event']=='native_pending_status' for row in events),
        scope='Pending is no command; late actual stdout is discarded on its original identity, never a timely NN sample')


def fault_and_evidence_measurements(events, counts, *, writer_required,async_measurements=None):
    errors=sum(x['event']=='adapter_result' and bool(x.get('error')) for x in events)
    incomplete=counts.get('native_request',0)-counts.get('native_result',0)
    if async_measurements is not None:incomplete=async_measurements['async_incomplete_transactions']
    statuses=[x.get('status') for x in events if x['event']=='native_evidence_closed']
    evidence_clean=(not writer_required and not statuses) or (bool(statuses) and all(
        type(s) is dict and s.get('clean') is True and s.get('written')==s.get('submitted')
        and type(s.get('written')) is int and s.get('failed')==0 and s.get('worker_alive') is False
        for s in statuses))
    return dict(adapter_error_count=errors,incomplete_native_requests=incomplete,
        native_evidence_closed=bool(evidence_clean),native_evidence_shutdown_statuses=statuses,
        native_evidence_writer_required=writer_required)


def run(a):
    from rm_match.platform_v2.host_scheduling import PythonSwitchInterval,AuthorityThreadAffinity,scheduling_qualified
    if a.out.exists():raise ValueError('Fresh output directory required; preserved evidence is never overwritten')
    switch=PythonSwitchInterval(getattr(a,'host_python_switch_interval_ms',None))
    affinity=AuthorityThreadAffinity(getattr(a,'authority_affinity_mask',None))
    scheduling=dict(python_switch_interval=switch.record,authority_affinity=affinity.record)
    try:
        with switch:
            report=_run(a,affinity,scheduling)
    finally:
        # Even setup failures retain actual attempted/restored scheduling state.
        a.out.mkdir(parents=True,exist_ok=True)
        (a.out/'HOST_SCHEDULING.json').write_text(json.dumps(scheduling,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    report['measurements']['host_scheduling_applied_and_restored']=scheduling_qualified(scheduling)
    report['classification']=classify(report['measurements'],plan=report.pop('_plan'))
    (a.out/'RESULT.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(report['classification'],indent=2))
    return 0 if (report['classification']['live_static_chain_qualified']
        or report['classification'].get('live_moving_scene_chain_qualified') is True) else 2


def selected_client_identity(a):
    """Explicit root/manifest pair; omitted manifest retains the legacy patch."""
    from rm_match.deployment.launcher import check_client
    selected=getattr(a,'client_patch_manifest',None)
    return (check_client(a.client_root) if selected is None else
            check_client(a.client_root,patch_manifest=selected))


def selected_client_plan(a):
    from rm_match.deployment.launcher import client_patch_identity
    selected=getattr(a,'client_patch_manifest',None)
    if selected is None:
        return None
    return dict(client_root=str(a.client_root.expanduser().absolute()),
        client_patch_manifest=str(selected.expanduser().absolute()),
        client_patch=client_patch_identity(manifest_path=selected.expanduser().absolute()))


def _run(a,affinity,scheduling):
    if sys.platform!='win32':raise RuntimeError('Actual Windows host required for NVIDIA live diagnostic')
    from rm_match.deployment.enrollment import provision_operator
    from rm_match.deployment.wsl_profile import own_wsl_registry
    from rm_match.platform_v2.admission import AdmissionPolicy
    from rm_match.platform_v2.backend import MuJoCoBackend
    from rm_match.platform_v2.camera import CameraProvider,MuJoCoCameraRenderer
    from rm_match.platform_v2.runtime import PlatformRuntime
    from rm_match.platform_v2.server import PlatformHTTPServer,TransportConfig
    from rm_match.match_model import SPAWNS
    import mujoco
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    host_threads=getattr(a,'host_opencv_threads',None)
    plan=build_plan(a.native_transport,private_native_pixels=a.private_native_pixels,raw_base64_codec=a.raw_base64_codec,
        host_opencv_threads=host_threads,host_python_switch_interval_ms=getattr(a,'host_python_switch_interval_ms',None),
        authority_affinity_mask=getattr(a,'authority_affinity_mask',None),robot_id=getattr(a,'robot_id','red_sentry'),native_robot_scope=getattr(a,'native_robot_scope',None),
        profile_phases=getattr(a,'profile_phases',False),camera_capture_policy=getattr(a,'camera_capture_policy','latest_pending'),
        telemetry_publish_interval_ms=getattr(a,'telemetry_publish_interval_ms',0.),
        moving_target_vy_mps=getattr(a,'moving_target_vy_mps',None),gimbal_servo=getattr(a,'gimbal_servo','position'),gimbal_yaw_gain=getattr(a,'gimbal_yaw_gain',1.),
        camera_renderer_mode=getattr(a,'camera_renderer_mode','thread'),display_jpeg_codec=getattr(a,'display_jpeg_codec','pillow_jpeg85'))
    phase_probe=None
    if getattr(a,'profile_phases',False):
        from rm_match.integrations.phase_timing import NumericPhaseProbe
        phase_probe=NumericPhaseProbe(capacity=plan['configuration']['host_phase_capacity'])
    actor_id=getattr(a,'robot_id','red_sentry')
    def write(name,value):
        (out/name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    scope_path=getattr(a,'native_robot_scope',None)
    scope_raw=None if scope_path is None else Path(scope_path).read_bytes()
    if scope_raw is not None:
        if hashlib.sha256(scope_raw).hexdigest()!=plan['configuration']['native_robot_scope']['sha256']:
            raise RuntimeError('Native robot scope changed before resource construction')
        (out/'NATIVE_ROBOT_SCOPE.json').write_bytes(scope_raw)
    sources={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (ROOT/'rm_match').rglob('*.py')}
    sources[Path(__file__).relative_to(ROOT).as_posix()]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if plan['configuration'].get('moving_target'):
        sources['tools/native_target_motion.py']=hashlib.sha256((ROOT/'tools/native_target_motion.py').read_bytes()).hexdigest()
    if plan['criteria'].get('postclose_actual_pixel_audit'):
        for rel in ('tools/audit_live_native_pixels.py','tools/diagnose_native_saved_compute.py'):
            sources[rel]=hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()
    if phase_probe is not None:
        sources['tools/native_phase_report.py']=hashlib.sha256((ROOT/'tools/native_phase_report.py').read_bytes()).hexdigest()
    write('EXECUTED_SOURCE.json',sources);write('PLAN.json',plan)
    host_opencv=None
    if host_threads is not None:
        from rm_match.platform_v2.host_opencv import configure_opencv_threads
        host_opencv=configure_opencv_threads(host_threads)
        write('HOST_OPENCV_STARTUP.json',host_opencv)
    identity=selected_client_identity(a)
    selected=getattr(a,'_client_selection',None)
    if selected is not None:
        if selected_client_plan(a)!=selected or identity['client_patch']!=selected['client_patch']:
            raise RuntimeError('Selected client changed after plan')
        plan['client_selection']=selected
        write('PLAN.json',plan)
    write('CLIENT_IDENTITY.json',identity)
    selected_manifest=getattr(a,'client_patch_manifest',None)
    write('CLIENT_SELECTION.json',dict(client_root=str(a.client_root.absolute()),
        client_patch_manifest=None if selected_manifest is None else str(selected_manifest.absolute()),
        client_patch=identity['client_patch']))
    sys.path.insert(0,str(a.client_root.resolve()))
    from rm_client.sim_platform_client import PlatformClient,ClientError
    credential=provision_operator(out/'admission.json',allowed_robots=(actor_id,))
    backend=MuJoCoBackend(camera=True,gimbal_servo=plan['configuration'].get('gimbal_servo','position'),gimbal_yaw_gain=plan['configuration'].get('gimbal_yaw_gain',1.));sim=backend._sim
    servo_identity=dict(mode=backend.gimbal_servo_mode,yaw_gain=backend.gimbal_yaw_gain,provenance=None if backend._gimbal_servo is None else backend._gimbal_servo.provenance,
        scope='Own-model low-level feedforward only; raw native references and original authority checks unchanged; no target/accuracy/shooting qualification')
    write('GIMBAL_SERVO.json',servo_identity)
    if len(backend.robot_ids)!=6 or backend.timestep!=.002:raise RuntimeError('Six-car dt2ms required')
    for key,xy in plan['scene'].items():
        if not key.endswith('_xy_m'):continue
        rid=key[:-5];x,y=xy
        sim.data.qpos[sim.qindices[rid][0]]=x-SPAWNS[rid][0]
        sim.data.qpos[sim.qindices[rid][1]]=y-SPAWNS[rid][1]
    sim.data.qvel[:]=0;mujoco.mj_forward(sim.model,sim.data)
    write('PUBLIC_INITIAL_SCENE.json',dict(origin='Explicit public static test only; never native DTO',qpos=sim.data.qpos.tolist()))
    events=[];raw={};consumed={};prepared=set();entry_candidates=[];counts=Counter();errors=[];ready=threading.Event();renderer_errors=[];step_durations=[];authority_stages={};target_motion=None
    def trace(row):
        event=row['event'];counts[event]+=1
        if target_motion is not None:target_motion.consumed(row)
        now=time.perf_counter()
        if event=='physics_apply':
            counts['fire_true']+=sum(bool(t['fire']) for t in row['targets'].values())
            return
        if event=='integration_boundary':
            # All receipts from this completed physical step have arrived. Join
            # the real entry, final target/budget and actual mj_step call only.
            for receipt in entry_candidates:
                boundary={k:row[k] for k in ('episode','sim_time','integration_start_wall','integration_call_wall','post_step_wall')}
                boundary.update(targets={actor_id:row['targets'][actor_id]},output_budgets={actor_id:row['output_budgets'][actor_id]})
                ctrl=sim.data.ctrl[sim.aindices[actor_id]].tolist()
                command=dict(backend.last_commands[actor_id])
                checks=physical_integration_checks(receipt,boundary,ctrl,command)
                counts['native_integration_attempts']+=1
                passed=all(checks.values());counts['native_physical_integrations']+=passed
                value=dict(receipt,event='native_integration_attempt',host_received_wall=now,
                    integration_boundary=boundary,physical_integration_checks=checks,physical_integration_verified=passed,
                    actual_qpos=sim.data.qpos[sim.qindices[actor_id]].tolist(),actual_actuator_ctrl=ctrl,actual_command=command)
                events.append(value)
                if passed:consumed.setdefault(receipt['budget']['frame_id'],value)
            entry_candidates.clear()
            return
        if row.get('robot_id',actor_id)!=actor_id:return
        if event=='actuator_consumed':
            target=row['target'];budget=row.get('budget')
            if target.get('gimbal') is None or budget is None:return
            counts['native_actuator_receipts']+=1
            wall_age=row['consume_wall']-budget['capture_wall']
            sim_age=row['consume_sim_time']-budget['capture_sim_time']
            if not all(actuator_receipt_budget_checks(row).values()):
                counts['stale_actuator_receipts']+=1
                # Keep each failure even if this frame already had an earlier
                # timely receipt. First-frame deduplication must not hide it.
                events.append(dict(row,event='stale_actuator_receipt',
                    original_event='actuator_consumed',host_received_wall=now,
                    wall_age_s=wall_age,sim_age_s=sim_age))
            frame_id=budget['frame_id']
            if frame_id not in prepared:
                prepared.add(frame_id);events.append(dict(row,host_received_wall=now,evidence_scope='preparatory_write_only'))
            if row.get('phase')=='integration_entry':entry_candidates.append(dict(row))
            return
        events.append(dict(row,host_received_wall=now))
    renderer_mode=getattr(a,'camera_renderer_mode','thread')
    renderer_class=MuJoCoCameraRenderer
    if renderer_mode=='owned_process_v1':
        from rm_match.platform_v2.camera_process import ProcessCameraRenderer
        renderer_class=ProcessCameraRenderer
    class Render(renderer_class):
        def __init__(self,*args,**kwargs):
            try:
                super().__init__(*args,**kwargs)
                if 'NVIDIA' not in str(self.identity):raise RuntimeError('Actual NVIDIA GL required')
            except BaseException as exc:
                renderer_errors.append(type(exc).__name__+':'+str(exc));raise
            finally:ready.set()
    class Camera(CameraProvider):
        def _encode(self,cap,rgb,*,raw_bytes=None):
            value=super()._encode(cap,rgb,raw_bytes=raw_bytes)
            raw[cap.frame_seq]=dict(frame_id=cap.frame_seq,capture_wall=cap.wall_time,
                capture_sim_time=cap.sim_time,encoded_wall=value['encoded_wall'],
                raw_rgb_sha256=hashlib.sha256(rgb.tobytes() if raw_bytes is None else raw_bytes).hexdigest(),shape=list(rgb.shape))
            return value
    camera=Camera(sim,clock=time.perf_counter,total_fps=15,max_views=1,renderer_factory=Render,
        enable_native_pixels=a.private_native_pixels,native_pixels_hook=trace if a.private_native_pixels else None,
        raw_base64_codec=a.raw_base64_codec,capture_policy=getattr(a,'camera_capture_policy','latest_pending'),renderer_mode=renderer_mode,
        display_jpeg_codec=getattr(a,'display_jpeg_codec','pillow_jpeg85'))
    codec_identity=camera._raw_encoder_metadata
    write('RAW_CODEC_IDENTITY.json',codec_identity)
    probe_options={} if phase_probe is None else {'phase_probe':phase_probe}
    registry=own_wsl_registry(a.linux_native_spec,out/'native',repo_root=ROOT,
        distribution=a.distribution,native_trace=trace,transport=a.native_transport,native_robot_scope=getattr(a,'native_robot_scope',None),**probe_options)
    class TimedRuntime(PlatformRuntime):
        def step_once(self):
            started=time.perf_counter()
            index=self.steps
            if phase_probe is not None:phase_probe.mark('authority_step_start',detail=index)
            try:
                if target_motion is not None:target_motion.before_step()
                return super().step_once()
            finally:
                if phase_probe is not None:phase_probe.mark('authority_step_end',detail=index)
                step_durations.append(time.perf_counter()-started)
        def close(self):
            if self._authority==threading.get_ident() and 'start' in timing and 'physics_end' not in timing:
                timing['physics_end']=time.perf_counter()
            try:
                if target_motion is not None:target_motion.close()
            finally:super().close()
    runtime=TimedRuntime(backend,camera=camera,registry=registry,clock=time.perf_counter,trace=trace,
        enable_native_pixels=a.private_native_pixels,
        telemetry_publish_interval_s=plan['configuration'].get('telemetry_publish_interval_s',0.))
    if plan['configuration'].get('moving_target'):
        from tools.native_target_motion import ScriptedTargetMotion
        target=plan['configuration']['moving_target']
        target_motion=ScriptedTargetMotion(runtime.control,backend,target['robot_id'],target['vy_mps'])
    if getattr(a,'profile_authority',False) or phase_probe is not None:
        # Local QPC stage timers only. No suspension, alternate clock or change
        # to original scheduling/80ms/150ms gates; diagnostic overhead is explicit.
        for obj,name,label in ((runtime,'_collect','collect'),(runtime,'_schedule','schedule'),
            (runtime,'_targets','targets'),(backend,'_step','backend_step'),
            (backend,'display_snapshot','display_snapshot'),(runtime.control,'snapshot','control_snapshot'),
            (camera,'capture_from_authority','camera_authority_capture')) + (
                ((target_motion,'before_step','scripted_target_before_step'),) if target_motion is not None else ()):
            original=getattr(obj,name);samples=authority_stages.setdefault(label,[])
            def timed(*args,_original=original,_samples=samples,**kwargs):
                start=time.perf_counter()
                try:return _original(*args,**kwargs)
                finally:_samples.append(time.perf_counter()-start)
            if phase_probe is not None:
                def timed_phases(*args,_original=timed,_label=label,**kwargs):
                    index=runtime.steps
                    if index % PHASE_DETAIL_STRIDE:return _original(*args,**kwargs)
                    phase_probe.mark('authority_'+_label+'_start',detail=index)
                    try:return _original(*args,**kwargs)
                    finally:phase_probe.mark('authority_'+_label+'_end',detail=index)
                timed=timed_phases
            setattr(obj,name,timed)
    server=PlatformHTTPServer(TransportConfig(port=0,admission_policy=AdmissionPolicy.from_manifest(out/'admission.json')),runtime)
    http=threading.Thread(target=server.serve_forever,daemon=True)
    client=None;physics=None;native=None;native_process=None;sdk_events=[];timing={};sdk_admitted=False;window_acked=False
    setup=time.perf_counter()
    try:
        camera.start()
        if not ready.wait(15.) or renderer_errors:raise RuntimeError('Renderer readiness failed: '+str(renderer_errors))
        native=registry.prepare_native(dict(fov_degrees=180.,circle_radius_x_norm=1.,circle_radius_y_norm=1.))
        native_process=native.process
        if camera.capture_count or camera.raw_published or sim.time or counts['native_request']:
            raise RuntimeError('Capture/inference/physics before live readiness')
        write('STARTUP_ADMISSION.json',dict(setup_s=time.perf_counter()-setup,
            captures=0,native_requests=0,physics_time_s=0,renderer=camera.renderer_identity))
        http.start()
        client=PlatformClient('http://127.0.0.1:'+str(server.server_address[1]),
            timeout=.25,control_profile='server_window_v1',admission_credential=credential)
        client.open('operator');client.watch(actor_id);client.claim(actor_id,['gimbal'])
        bound=client.bind(actor_id,'aim','aim_native_rmcs_v1',
            dict(fov_degrees=180.,circle_radius_x_norm=1.,circle_radius_y_norm=1.))
        sdk_admitted=True
        def activate():
            nonlocal window_acked
            window=client.control_window(actor_id,['gimbal'])
            ack=client.adapter_input(actor_id,'aim',bound['binding_epoch'],window_id=window['window_id'],valid_for_s=.15)
            window_acked=True;sdk_events.append(dict(event='activation_ack',host_wall=time.perf_counter(),
                window_id=window['window_id'],activation_expires=ack['activation_expires']))
        activate()
        def authority():
            try:
                with affinity:
                    timing['start']=time.perf_counter()
                    timing['cpu_start']=time.process_time()
                    try:runtime.run(max_wall_seconds=a.seconds,real_time_factor=1.)
                    finally:
                        timing['end']=time.perf_counter()
                        timing['cpu_end']=time.process_time()
            except BaseException as exc:errors.append(type(exc).__name__+':'+str(exc))
        physics=threading.Thread(target=authority,name='live-physics-authority',daemon=True);physics.start()
        start=time.perf_counter();renew=start;sample=start
        while physics.is_alive() and time.perf_counter()-start<a.seconds:
            activate()
            now=time.perf_counter()
            if now-renew>=.25:client.renew(actor_id,['gimbal']);renew=now
            if now-sample>=.2:
                state=client.state();sample=now
                sdk_events.append(dict(event='operator_status',host_wall=now,
                    algorithm_status=state.get('algorithm_status'),runtime_state=state.get('runtime_state')))
            time.sleep(.04)
        client.release(actor_id,['gimbal']);client.close();client=None
    except BaseException as exc:
        if expected_shutdown_rejection(exc,runtime,ClientError):
            sdk_events.append(dict(event='expected_runtime_stopped',phase='terminal_sdk_request',
                host_wall=time.perf_counter(),remote_session_close_ack=False))
        else:errors.append(type(exc).__name__+':'+str(exc))
    finally:
        def cleanup(label,function):
            try:return function()
            except BaseException as exc:errors.append(label+': '+type(exc).__name__+':'+str(exc));return None
        cleanup('runtime_stop',runtime.request_stop)
        if physics is not None:cleanup('physics_join',lambda:physics.join(4.))
        else:cleanup('runtime_close_before_first_job',runtime.close)
        # The registry retains a prewarmed adapter until the first slot claims it.
        # Runtime closes claimed slots; the registry closes an unclaimed preload.
        cleanup('registry_close',registry.close)
        if client is not None:
            try:client.close()
            except BaseException as exc:
                if expected_shutdown_rejection(exc,runtime,ClientError):
                    sdk_events.append(dict(event='expected_runtime_stopped',phase='terminal_sdk_close',
                        host_wall=time.perf_counter(),remote_session_close_ack=False))
                else:errors.append('SDK_close: '+type(exc).__name__+':'+str(exc))
        cleanup('camera_stop',camera.stop)
        camera_closed=cleanup('camera_join',lambda:camera.wait_closed(4.)) is True
        if http.is_alive():cleanup('HTTP_shutdown',server.shutdown)
        cleanup('HTTP_close',server.server_close)
        if http.is_alive():cleanup('HTTP_join',lambda:http.join(2.))
    # Persist actual execution before any derived report/percentile calculation.
    # Report errors must never erase the native/physics/SDK source evidence.
    write('FRAME_BINDINGS.json',raw);write('SDK_EVENTS.json',sdk_events)
    (out/'ledger.jsonl').write_text(''.join(json.dumps(x,allow_nan=False)+'\n' for x in events),encoding='utf-8')
    write('RUNTIME_OBSERVATION.json',dict(counts=dict(counts),camera=camera.status(),
        telemetry_publication=runtime.telemetry_publication_status(),
        camera_closed=camera_closed,physics_thread_alive=physics is not None and physics.is_alive(),
        shutdown_status=getattr(runtime,'shutdown_status',None),runtime_error=runtime.error,
        sim_time=sim.time,timing=timing,errors=errors,step_duration_samples_s=step_durations))
    target_report=None
    if target_motion is not None:
        target_report=target_motion.report(raw,consumed)
        write('TARGET_MOTION.json',dict(report=target_report,windows=target_motion.windows,samples=target_motion.samples))
    durations=run_durations(timing,sim.time);elapsed=durations['run_and_cleanup_wall_s']
    clean=(camera_closed and not http.is_alive() and (physics is None or not physics.is_alive())
        and getattr(runtime,'shutdown_status',{}).get('clean') is True)
    phase_snapshot=phase_summary=None
    if phase_probe is not None:
        from tools.native_phase_report import summarize
        phase_snapshot=phase_probe.snapshot()
        phase_snapshot['captured_after_clean_shutdown']=clean
        phase_snapshot['sampling']=dict(authority_step='every_step',authority_details_step_stride=PHASE_DETAIL_STRIDE,
            transport_and_evidence='all_original_phase_calls')
        info=time.get_clock_info('thread_time')
        phase_snapshot['reported_thread_cpu_clock']=dict(implementation=info.implementation,resolution_s=info.resolution,
            note='API resolution is not measured accounting granularity; short zero CPU deltas do not prove zero work')
        write('PHASE_TIMING.json',phase_snapshot)
        phase_summary=summarize(phase_snapshot)
        phase_summary['captured_after_clean_shutdown']=clean
        write('PHASE_SUMMARY.json',phase_summary)
    source_unchanged=all((ROOT/p).is_file() and hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in sources.items())
    try:
        final_identity=selected_client_identity(a)
        client_unchanged=final_identity==identity
        write('CLIENT_FINAL_IDENTITY.json',dict(identity=final_identity,unchanged=client_unchanged))
    except Exception as exc:
        client_unchanged=False
        write('CLIENT_FINAL_IDENTITY.json',dict(unchanged=False,error=type(exc).__name__+':'+str(exc)))
    source_unchanged=source_unchanged and client_unchanged
    if scope_raw is not None:
        source_unchanged=source_unchanged and Path(scope_path).read_bytes()==scope_raw
    extension=codec_identity.get('extension_path')
    codec_unchanged=(camera.raw_base64_codec==a.raw_base64_codec and (extension is None
        or (Path(extension).is_file() and hashlib.sha256(Path(extension).read_bytes()).hexdigest()==codec_identity.get('extension_sha256'))))
    if counts['stale_actuator_receipts']:errors.append('Stale actuator consumption')
    budgets=[x['sensor_budget'] for x in events if x['event']=='adapter_enqueue' and x.get('sensor_budget')]
    native_budget_ok=bool(budgets) and all(native_sensor_budget_valid(b) for b in budgets)
    transport_evidence,evidence_collection=collect_transport_evidence(out/'native',native_process)
    actual_transport=(transport_evidence.get('STARTUP.json') or {}).get('transport')
    async_measurements=(async_transaction_measurements(events,transport_evidence)
        if a.native_transport=='wsl_async_bgr_v3' else None)
    pixel_audit=None
    if plan['criteria'].get('postclose_actual_pixel_audit'):
        from tools.audit_live_native_pixels import audit_saved_native_pixels
        pixel_audit=audit_saved_native_pixels(out)
        write('POST_CLOSE_PIXEL_AUDIT.json',pixel_audit)
    host_unchanged=True
    if host_opencv is not None:
        import cv2
        effective=cv2.getNumThreads()
        host_unchanged=type(effective) is int and effective==host_opencv['effective_threads']
        write('HOST_OPENCV_FINAL.json',dict(effective_threads=effective,unchanged=host_unchanged,
            scope='Host API query after teardown; no Linux/C++ thread change'))
    measured=dict(configuration=plan['configuration'],duration_s=elapsed,
        telemetry_publication=runtime.telemetry_publication_status(),
        telemetry_publication_matches_plan=(runtime.telemetry_publish_interval_s==plan['configuration'].get('telemetry_publish_interval_s',0.)
            and runtime._telemetry_published_steps+runtime._telemetry_deferred_steps==runtime.steps
            and runtime._telemetry_published_steps>0
            and counts['physics_apply']==counts['integration_boundary']==runtime.steps
            and counts['actuator_consumed']==18*runtime.steps
            and (runtime.telemetry_publish_interval_s==0. or runtime._telemetry_deferred_steps>0)),
        host_opencv_setting_unchanged=host_unchanged,
        camera_capture_policy_matches_plan=camera.capture_policy==plan['configuration'].get('camera_capture_policy','latest_pending'),
        physics_rtf=durations['physics_rtf'],run_durations=durations,raw_frames=len(raw),
        native_results=counts['native_result'],distinct_native_actuated_frames=len(consumed),
        distinct_native_prepared_frames=len(prepared),
        physical_integration_evidence=bool(consumed) and all(v['physical_integration_verified'] is True for v in consumed.values()),
        source_unchanged=source_unchanged,sdk_admission=sdk_admitted,window_acknowledged=window_acked,
        native_sensor_budget_80ms=native_budget_ok,
        actual_transport_matches_plan=actual_transport==a.native_transport,
        raw_codec_identity_unchanged=codec_unchanged,
        postclose_actual_pixel_audit=pixel_audit is not None and pixel_audit.get('clean') is True,
        fire_true=counts['fire_true'],clean_shutdown=clean,errors=errors,
        host_phase_trace_complete=phase_snapshot is not None and phase_snapshot['complete'] is True and clean,
        **fault_and_evidence_measurements(events,counts,
            writer_required=getattr(native,'_evidence_required',False),async_measurements=async_measurements),
        **stage_measurements(events,raw,consumed,private_native_pixels=a.private_native_pixels,pixel_audit=pixel_audit))
    if async_measurements is not None:measured.update(async_measurements)
    if target_report is not None:
        measured.update(target_motion=target_report,
            original_target_motion_proven=(target_report['original_manual_authority_and_motion_proven'] is True
                and target_report['robot_id']==plan['configuration']['moving_target']['robot_id']
                and target_report['vy_mps']==plan['configuration']['moving_target']['vy_mps']))
    if plan['criteria'].get('gimbal_servo_configuration_matches_plan'):
        measured['gimbal_servo_configuration_matches_plan']=(servo_identity['mode']==plan['configuration']['gimbal_servo']
            and servo_identity['yaw_gain']==plan['configuration'].get('gimbal_yaw_gain',1.)
            and set(servo_identity['provenance'] or {})==set(backend.robot_ids))
    if plan['criteria'].get('camera_renderer_configuration_matches_plan'):
        measured['camera_renderer_configuration_matches_plan']=(camera.renderer_mode==plan['configuration']['camera_renderer_mode']
            and (camera.renderer_identity or {}).get('isolation')=='owned_process_v1'
            and (camera.renderer_shutdown_status or {}).get('clean') is True)
        measured['renderer_shutdown_status']=camera.renderer_shutdown_status
    if plan['criteria'].get('display_jpeg_codec_matches_plan'):
        measured['display_jpeg_codec_matches_plan']=(camera.display_jpeg_codec==plan['configuration']['display_jpeg_codec']
            and camera.display_codec_identity.get('implementation')=='cv2.imencode'
            and camera.display_codec_identity.get('quality')==85 and camera.display_error is None and camera.rendered>0)
        measured['display_codec_identity']=dict(camera.display_codec_identity)
        measured['successful_display_frames']=camera.rendered
    rejects=Counter()
    for event in events:
        if event['event']=='adapter_result':
            if event.get('error'):rejects['adapter_error:'+event['error']]+=1
            if event['host_received_wall']>=event['wall_deadline']:rejects['adapter_result_after_deadline']+=1
        elif event['event']=='adapter_sample_rejected':
            rejects['adapter_sample:'+str(event.get('reason','expired'))]+=1
    rejects['raw_encode_over_80ms']=sum(x>.08 for x in measured['raw_ages_s'])
    rejects['native_result_over_80ms']=sum(x>.08 for x in measured['native_result_ages_s'])
    rejects['stale_actuator_receipts']=counts['stale_actuator_receipts']
    rejects['camera_dropped']=camera.dropped
    report=dict(schema='polar.wsl.native.live-result.v1',measurements=measured,
        host_process_cpu=dict(seconds=None if 'cpu_start' not in timing or 'cpu_end' not in timing else timing['cpu_end']-timing['cpu_start'],
            clock='process_time',scope='All Windows process threads during runtime.run including cleanup; excludes setup and WSL native child'),
        classification=classify(measured,plan=plan),counts=dict(counts),rejects=dict(rejects),camera=camera.status(),
        camera_timings=camera.timing_report(),shutdown_status=getattr(runtime,'shutdown_status',None),
        client_identity=identity,linux_spec_sha256=hashlib.sha256(a.linux_native_spec.read_bytes()).hexdigest(),
        environment={k:os.environ.get(k) for k in ('MUJOCO_GL','OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS')},
        native_process_diagnostic=getattr(native_process,'diagnostics',None),
        native_transport_evidence=transport_evidence,
        native_transport_evidence_collection=evidence_collection,
        image_preparation=image_stage_summary(events),
        raw_codec_identity=codec_identity,
        host_opencv_startup=host_opencv,
        host_scheduling=scheduling,
        pixel_audit=pixel_audit,
        runtime_step_wall=distribution(step_durations),
        host_phase_timing=phase_summary,
        authority_stage_timing=dict(enabled=bool(getattr(a,'profile_authority',False) or phase_probe is not None),
            clock='host_perf_counter',stages={k:distribution(v) for k,v in authority_stages.items()},
            scope='Optional diagnostic timers add overhead; no time or control-window substitution'),
        native_identity=None if native_process is None else native_process.checked.metadata,
        native_spec=None if native_process is None else native_process.checked.linux_spec,
        scope=plan['scope'])
    report['_plan']=plan
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--linux-native-spec','--native-spec',dest='linux_native_spec',type=Path)
    p.add_argument('--distribution',default='Ubuntu')
    p.add_argument('--native-transport',choices=('wsl_stdio_v1','wsl_stdio_bgr_v2','wsl_async_bgr_v3'),default='wsl_stdio_v1')
    p.add_argument('--private-native-pixels',action='store_true',help='Explicit experimental own-native input before public base64 completion')
    p.add_argument('--telemetry-publish-interval-ms',type=float,default=0.,
        help='Explicit historical display sampling, 0..100 ms; default every step; sensors/control/traces unchanged')
    p.add_argument('--camera-capture-policy',choices=('latest_pending','render_ready'),default='latest_pending',
        help='Explicit local render-ready mode defers fresh exposure while renderer is busy; may reduce FPS, never restamps old pixels')
    p.add_argument('--camera-renderer-mode',choices=('thread','owned_process_v1'),default='thread',
        help='Explicit bounded local MuJoCo render process; original exposure identity and deadlines retained')
    p.add_argument('--display-jpeg-codec',choices=('pillow_jpeg85','opencv_jpeg85_v1'),default='pillow_jpeg85',
        help='Explicit display-only JPEG85 encoder; raw native pixels never use this JPEG')
    p.add_argument('--robot-id',default='red_sentry',help='One actual scene robot for this stationary test; requires matching local scope')
    p.add_argument('--gimbal-servo',choices=('position','position_gravity_v1'),default='position',
        help='Explicit own-model gravity feedforward; original deadlines and native references unchanged')
    p.add_argument('--gimbal-yaw-gain',type=float,default=1.,help='Explicit own yaw position feedback gain, 1..4; other than 1 requires gravity servo')
    p.add_argument('--moving-target-vy-mps',type=float,
        help='Explicit manual scene target motion, magnitude 0.03..0.15 m/s; shooter stays stationary; no navigation/decision qualification')
    p.add_argument('--native-robot-scope',type=Path,help='Explicit local stationary robot identity registration')
    p.add_argument('--raw-base64-codec',choices=('stdlib_chunked','pybase64_1_5_1'),default='stdlib_chunked')
    p.add_argument('--host-opencv-threads',type=int,help='Explicit verified host camera OpenCV thread option, 1..32')
    from rm_match.platform_v2.host_scheduling import switch_interval_ms,parse_affinity_mask
    p.add_argument('--host-python-switch-interval-ms',type=lambda s:switch_interval_ms(float(s)),
        help='Explicit local CPython interval, finite 0.1..10 ms; restored after cleanup')
    p.add_argument('--authority-affinity-mask',type=parse_affinity_mask,
        help='Explicit Windows authority-thread mask, base-0 integer; restored after runtime.run')
    p.add_argument('--profile-authority',action='store_true',help='Additional local stage timers with explicit diagnostic overhead')
    p.add_argument('--profile-phases',action='store_true',help='Opt-in bounded same-source wall/thread-CPU samples, persisted after teardown; async native only')
    p.add_argument('--client-root',type=Path)
    p.add_argument('--client-patch-manifest',type=Path,
        help='Explicit reviewed patch for this exact client checkout; no automatic version fallback')
    p.add_argument('--out',type=Path)
    p.add_argument('--seconds',type=float,default=10.)
    p.add_argument('--run',action='store_true')
    a=p.parse_args(argv)
    if a.client_patch_manifest is not None and a.client_root is None:
        p.error('--client-patch-manifest requires its explicit --client-root')
    if a.authority_affinity_mask is not None and sys.platform!='win32':p.error('--authority-affinity-mask requires Windows')
    if a.host_opencv_threads is not None and not 1<=a.host_opencv_threads<=32:p.error('--host-opencv-threads must be within 1..32')
    if not 10<=a.seconds<=20:p.error('Actual run must be bounded to 10..20 wall seconds')
    try:
        selected_plan=build_plan(a.native_transport,private_native_pixels=a.private_native_pixels,raw_base64_codec=a.raw_base64_codec,
            host_opencv_threads=a.host_opencv_threads,host_python_switch_interval_ms=a.host_python_switch_interval_ms,
            authority_affinity_mask=a.authority_affinity_mask,robot_id=a.robot_id,native_robot_scope=a.native_robot_scope,
            profile_phases=a.profile_phases,camera_capture_policy=a.camera_capture_policy,
            telemetry_publish_interval_ms=a.telemetry_publish_interval_ms,moving_target_vy_mps=a.moving_target_vy_mps,gimbal_servo=a.gimbal_servo,gimbal_yaw_gain=a.gimbal_yaw_gain,
            camera_renderer_mode=a.camera_renderer_mode,display_jpeg_codec=a.display_jpeg_codec)
        a._client_selection=selected_client_plan(a)
        if a._client_selection is not None:
            selected_plan['client_selection']=a._client_selection
    except (ValueError,OSError) as exc:p.error('Invalid local native scene/scope: '+str(exc))
    if not a.run:
        print(json.dumps(selected_plan,indent=2));return 0
    for key in ('linux_native_spec','client_root','out'):
        if getattr(a,key) is None:p.error('--'+key.replace('_','-')+' is required with --run')
        setattr(a,key,getattr(a,key).resolve())
    if a.out.exists():p.error('Fresh output directory required; preserved evidence is never overwritten')
    if a.client_patch_manifest is not None:
        a.client_patch_manifest=a.client_patch_manifest.expanduser().absolute()
    try:return run(a)
    except BaseException as exc:
        # Errors before resource construction still leave an honest bounded
        # setup record. Resource-owning code above attempts every cleanup.
        a.out.mkdir(parents=True,exist_ok=True)
        (a.out/'REPORT_EXCEPTION.txt').write_text(traceback.format_exc(),encoding='utf-8')
        admitted=(a.out/'STARTUP_ADMISSION.json').exists()
        value=dict(schema='polar.wsl.native.live-failure.v2',
            state='AFTER_STARTUP_FAILURE' if admitted else 'SETUP_FAILED',
            startup_admitted=admitted,runtime_evidence_available=(a.out/'RUNTIME_OBSERVATION.json').exists(),
            errors=[type(exc).__name__+':'+str(exc)],live_static_chain_qualified=False,
            cleanup_qualified=False,plan=selected_plan)
        (a.out/'RESULT.json').write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(value,indent=2));return 2


if __name__=='__main__':
    raise SystemExit(main())
