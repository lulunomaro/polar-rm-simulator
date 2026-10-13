"""Meaningful fail-closed report checks; no fake inference/physics success."""
import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

spec=importlib.util.spec_from_file_location('live_smoke',Path(__file__).resolve().parents[1]/'tools/smoke_wsl_native_live.py')
smoke=importlib.util.module_from_spec(spec);spec.loader.exec_module(smoke)


def measured():
    return dict(configuration=copy.deepcopy(smoke.PLAN['configuration']),duration_s=10.,
        physics_rtf=.995,raw_frames=140,native_results=70,distinct_native_actuated_frames=50,
        exact_sensor_pixel_binding=True,source_unchanged=True,sdk_admission=True,
        native_sensor_budget_80ms=True,
        actual_transport_matches_plan=True,
        adapter_error_count=0,incomplete_native_requests=0,native_evidence_closed=True,
        window_acknowledged=True,fire_true=0,clean_shutdown=True,errors=[],
        raw_ages_s=[.045,.06],native_result_ages_s=[.06,.075],
        actuator_wall_ages_s=[.067,.079],actuator_sim_ages_s=[.066,.078])


def test_fresh_real_chain_never_qualifies_fullmatch_gui_hardware():
    r=smoke.classify(measured())
    assert r['live_static_chain_qualified']
    assert not any(r[k] for k in ('full_match_qualified','hardware_qualified','visible_qt_qualified'))


def test_missing_or_late_stage_cannot_be_hidden_by_successful_receipts():
    for stage in ('raw_ages_s','native_result_ages_s','actuator_wall_ages_s','actuator_sim_ages_s'):
        for values in ([],[.01,.081],[float('nan')],[-.001]):
            m=measured();m[stage]=values
            assert not smoke.classify(m)['live_static_chain_qualified']


def test_no_native_or_actuator_samples_never_pass():
    for key in ('raw_frames','native_results','distinct_native_actuated_frames'):
        m=measured();m[key]=0
        assert not smoke.classify(m)['live_static_chain_qualified']


def test_slowed_physics_or_configuration_change_fails():
    m=measured();m['physics_rtf']=.3
    assert not smoke.classify(m)['live_static_chain_qualified']
    for key,value in [('real_time_factor_limit',.1),('camera_native_budget_s',.15),
                      ('total_fps',2),('server_input_window_s',1)]:
        m=measured();m['configuration'][key]=value
        assert not smoke.classify(m)['live_static_chain_qualified']


def test_unauthorized_or_unbound_pixels_and_leaked_resources_fail():
    for key in ('exact_sensor_pixel_binding','source_unchanged','sdk_admission','window_acknowledged','clean_shutdown'):
        m=measured();m[key]=False
        assert not smoke.classify(m)['live_static_chain_qualified']
    m=measured();m['fire_true']=1
    assert not smoke.classify(m)['live_static_chain_qualified']


def test_rejected_runtime_fault_fails_even_with_enough_good_results():
    m=measured();m['errors']=['native_timeout']
    assert not smoke.classify(m)['live_static_chain_qualified']
    m=measured();m['native_sensor_budget_80ms']=False
    assert not smoke.classify(m)['live_static_chain_qualified']


def test_distributions_preserve_max_and_empty_sample_counts():
    assert smoke.distribution([])['sample_count']==0
    r=smoke.distribution([.01,.081,.03])
    assert r['max_ms']==81 and r['within_80ms_count']==2 and r['p50_ms']==30


def test_stage_join_requires_real_frame_hash_and_uses_only_host_clock():
    raw={1:dict(raw_rgb_sha256='actualpixels',capture_wall=100.,encoded_wall=100.04)}
    events=[dict(event='adapter_enqueue',observed_seq=7,sensor_budget={'frame_id':1},host_received_wall=100.045),
        dict(event='native_request',frame_id=1,observed_seq=7,raw_rgb_sha256='actualpixels',host_received_wall=100.05),
        dict(event='native_result',frame_id=1,raw_rgb_sha256='actualpixels',host_received_wall=100.07,
            wall_time=99999999.)]
    consumed={1:dict(consume_wall=100.075,consume_sim_time=5.075,
        budget=dict(capture_wall=100.,capture_sim_time=5.))}
    r=smoke.stage_measurements(events,raw,consumed)
    assert r['exact_sensor_pixel_binding']
    assert abs(r['native_result_ages_s'][0]-.07)<1e-8
    assert abs(r['stages']['exposure_to_actuator_consume']['max_ms']-75)<1e-6
    events[1]['raw_rgb_sha256']='substituted'
    assert not smoke.stage_measurements(events,raw,consumed)['exact_sensor_pixel_binding']


def test_only_exact_remote_stopped_code_after_actual_stop_is_expected():
    class ClientError(RuntimeError):
        def __init__(self,code):self.code=code
    runtime=SimpleNamespace(_closed=True,stop_event=SimpleNamespace(is_set=lambda:True),
        control=SimpleNamespace(stopped=True))
    assert smoke.expected_shutdown_rejection(ClientError('runtime_stopped'),runtime,ClientError)
    for code in ('transport_uncertain','invalid_session','unclassified_error'):
        assert not smoke.expected_shutdown_rejection(ClientError(code),runtime,ClientError)
    runtime._closed=False
    assert not smoke.expected_shutdown_rejection(ClientError('runtime_stopped'),runtime,ClientError)
    runtime._closed=True;runtime.stop_event.is_set=lambda:False
    assert not smoke.expected_shutdown_rejection(ClientError('runtime_stopped'),runtime,ClientError)
    runtime.stop_event.is_set=lambda:True;runtime.control.stopped=False
    assert not smoke.expected_shutdown_rejection(ClientError('runtime_stopped'),runtime,ClientError)


def test_actual_image_stage_metadata_is_not_treated_as_duration():
    r=smoke.image_stage_summary([dict(event='native_frame_prepare',image_stages=dict(
        converter='opencv',clock_domain='host_perf_counter',rgb_to_bgr_s=.003,total_s=.006))])
    assert set(r)=={'rgb_to_bgr_s','total_s'}
    assert r['total_s']['p50_ms']==6


def test_explicit_v2_plan_does_not_mutate_default_or_change_safety_limits():
    original=copy.deepcopy(smoke.PLAN)
    plan=smoke.build_plan('wsl_stdio_bgr_v2')
    assert smoke.PLAN==original
    assert plan['configuration']['native_transport']=='wsl_stdio_bgr_v2'
    assert plan['criteria']==smoke.PLAN['criteria']
    m=measured();m['configuration']=copy.deepcopy(plan['configuration'])
    assert smoke.classify(m,plan=plan)['live_static_chain_qualified']
    assert not smoke.classify(m)['live_static_chain_qualified']
    m['actual_transport_matches_plan']=False
    assert not smoke.classify(m,plan=plan)['live_static_chain_qualified']


def test_enough_early_good_results_cannot_hide_late_sticky_fault_or_incomplete_request():
    for key,value in [('adapter_error_count',1),('incomplete_native_requests',1),
                      ('incomplete_native_requests',-1),('native_evidence_closed',False)]:
        m=measured();m[key]=value
        assert not smoke.classify(m)['live_static_chain_qualified']


def test_writer_requires_actual_closed_balanced_counts_and_no_worker_error():
    status=dict(clean=True,written=12,submitted=12,failed=0,worker_alive=False)
    events=[dict(event='native_evidence_closed',status=status)]
    r=smoke.fault_and_evidence_measurements(events,{'native_request':12,'native_result':12},writer_required=True)
    assert r['native_evidence_closed']
    for key,value in [('clean',False),('written',11),('failed',1),('worker_alive',True)]:
        bad=copy.deepcopy(events);bad[0]['status'][key]=value
        assert not smoke.fault_and_evidence_measurements(bad,{},writer_required=True)['native_evidence_closed']
    assert not smoke.fault_and_evidence_measurements([],{},writer_required=True)['native_evidence_closed']
    assert smoke.fault_and_evidence_measurements([],{},writer_required=False)['native_evidence_closed']
