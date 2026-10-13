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
        postclose_actual_pixel_audit=True,
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


def private_sequence():
    """Synthetic report rows for join validation, never inference evidence."""
    raw={1:dict(frame_id=1,raw_rgb_sha256='a'*64,capture_wall=100.,
        capture_sim_time=5.,encoded_wall=100.04)}
    events=[dict(event='private_pixels_published',frame_id=1,capture_wall=100.,capture_sim_time=5.,
        wall_time=100.01,wall_clock='provider_monotonic',host_received_wall=999999.,robot_id='red_sentry',episode=0),
        dict(event='adapter_enqueue',observed_seq=7,
            sensor_budget=dict(frame_id=1,capture_wall=100.,capture_sim_time=5.),host_received_wall=100.015),
        dict(event='native_request',frame_id=1,observed_seq=7,capture_sim_time=5.,
            raw_rgb_sha256='a'*64,host_received_wall=100.02),
        dict(event='native_result',frame_id=1,raw_rgb_sha256='a'*64,host_received_wall=100.035)]
    consumed={1:dict(consume_wall=100.037,consume_sim_time=5.037,
        budget=dict(capture_wall=100.,capture_sim_time=5.))}
    return events,raw,consumed


def test_private_plan_is_explicit_keeps_historical_default_and_all_gates():
    original=copy.deepcopy(smoke.PLAN)
    historical=smoke.build_plan('wsl_stdio_bgr_v2')
    private=smoke.build_plan('wsl_stdio_bgr_v2',private_native_pixels=True)
    assert smoke.PLAN==original
    assert not historical['configuration'].get('private_native_pixels',False)
    assert private['configuration']['private_native_pixels'] is True
    assert private['configuration']['input_publication']=='sealed_actual_rgb_before_public_base64'
    assert {k:private['criteria'][k] for k in historical['criteria']}==historical['criteria']
    assert private['criteria']['postclose_actual_pixel_audit'] is True
    for key in ('robot_count','timestep_s','resolution','total_fps','active_views',
        'real_time_factor_limit','camera_native_budget_s','server_input_window_s','manual_fire'):
        assert private['configuration'][key]==historical['configuration'][key]
    m=measured();m['configuration']=copy.deepcopy(private['configuration'])
    assert smoke.classify(m,plan=private)['live_static_chain_qualified']
    assert not smoke.classify(m,plan=historical)['live_static_chain_qualified']


def test_private_early_enqueue_uses_actual_publish_clock_not_delayed_callback():
    events,raw,consumed=private_sequence()
    r=smoke.stage_measurements(events,raw,consumed,private_native_pixels=True)
    assert r['exact_sensor_pixel_binding']
    assert r['stage_samples_s']['raw_encode_end_to_adapter_enqueue']==[]
    assert r['stages']['raw_encode_end_to_adapter_enqueue']['sample_count']==0
    assert r['stage_inapplicable']=={'raw_encode_end_to_adapter_enqueue':
        'private native input is published before public base64 completion'}
    assert abs(r['stages']['exposure_to_private_pixels']['max_ms']-10)<1e-6
    assert abs(r['stages']['private_pixels_to_adapter_enqueue']['max_ms']-5)<1e-6
    # Public completion remains independently audited, even after native result.
    assert abs(r['raw_ages_s'][0]-.04)<1e-8
    assert abs(r['native_result_ages_s'][0]-.035)<1e-8


def test_default_public_sequence_retains_applicable_original_stage():
    events,raw,consumed=private_sequence();raw[1]['encoded_wall']=100.012
    default=smoke.stage_measurements(events,raw,consumed)
    explicit=smoke.stage_measurements(events,raw,consumed,private_native_pixels=False)
    assert default==explicit
    assert default['stage_inapplicable']=={}
    assert default['exact_sensor_pixel_binding']
    assert abs(default['stages']['raw_encode_end_to_adapter_enqueue']['max_ms']-3)<1e-6


def test_private_path_keeps_public_raw_80ms_gate_even_with_fast_native_result():
    events,raw,consumed=private_sequence();raw[1]['encoded_wall']=100.081
    r=smoke.stage_measurements(events,raw,consumed,private_native_pixels=True)
    assert r['exact_sensor_pixel_binding']
    plan=smoke.build_plan('wsl_stdio_bgr_v2',private_native_pixels=True)
    m=measured();m.update(r);m['configuration']=copy.deepcopy(plan['configuration'])
    classified=smoke.classify(m,plan=plan)
    assert not classified['live_static_chain_qualified']
    assert not classified['checks']['raw_ages_s']


def test_private_publish_missing_duplicate_or_wrong_frame_fails_binding():
    for mode in ('missing','duplicate','wrong_frame'):
        events,raw,consumed=private_sequence()
        if mode=='missing':events.pop(0)
        elif mode=='duplicate':events.insert(0,copy.deepcopy(events[0]))
        else:events[0]['frame_id']=2
        assert not smoke.stage_measurements(events,raw,consumed,private_native_pixels=True)['exact_sensor_pixel_binding']


def test_private_publish_capture_identity_clock_and_order_must_match_exactly():
    for key,value in [('capture_wall',100.000001),('capture_sim_time',5.000001),
        ('wall_clock','linux_local_diagnostic_only'),('wall_clock','host_perf_counter'),
        ('wall_time',99.999),('wall_time',100.041),('wall_time',float('nan')),
        ('wall_time',float('inf')),('wall_time',True)]:
        events,raw,consumed=private_sequence();events[0][key]=value
        assert not smoke.stage_measurements(events,raw,consumed,private_native_pixels=True)['exact_sensor_pixel_binding']
    events,raw,consumed=private_sequence();events[1]['host_received_wall']=100.009
    r=smoke.stage_measurements(events,raw,consumed,private_native_pixels=True)
    assert not r['exact_sensor_pixel_binding']
    # An inverted publication/queue ordering is rejected, never clamped to zero.
    assert all(v!=0 for v in r['stage_samples_s']['private_pixels_to_adapter_enqueue'])


def test_private_enqueue_request_and_raw_identities_cannot_be_swapped():
    for where,key,value in [('budget','frame_id',2),('budget','capture_wall',100.000001),
        ('budget','capture_sim_time',5.000001),('request','capture_sim_time',5.000001),
        ('raw','frame_id',2),('raw','capture_wall',100.000001),('raw','capture_sim_time',5.000001)]:
        events,raw,consumed=private_sequence()
        row=events[1]['sensor_budget'] if where=='budget' else events[2] if where=='request' else raw[1]
        row[key]=value
        assert not smoke.stage_measurements(events,raw,consumed,private_native_pixels=True)['exact_sensor_pixel_binding']


def test_private_hash_binding_requires_raw_request_result_same_immutable_pixels():
    for where in ('raw','request','result'):
        for mode in ('missing','substituted'):
            events,raw,consumed=private_sequence()
            row=raw[1] if where=='raw' else events[2] if where=='request' else events[3]
            if mode=='missing':row.pop('raw_rgb_sha256')
            else:row['raw_rgb_sha256']='b'*64
            assert not smoke.stage_measurements(events,raw,consumed,private_native_pixels=True)['exact_sensor_pixel_binding']


def test_private_required_capture_fields_cannot_be_inferred_from_other_events():
    for where,key in [('raw','frame_id'),('raw','capture_wall'),('raw','capture_sim_time'),
        ('raw','encoded_wall'),('publish','capture_wall'),('publish','capture_sim_time'),
        ('publish','wall_clock'),('budget','capture_wall'),('budget','capture_sim_time'),
        ('request','capture_sim_time')]:
        events,raw,consumed=private_sequence()
        row=raw[1] if where=='raw' else events[0] if where=='publish' else events[1]['sensor_budget'] if where=='budget' else events[2]
        row.pop(key)
        assert not smoke.stage_measurements(events,raw,consumed,private_native_pixels=True)['exact_sensor_pixel_binding']


def test_private_publication_is_required_for_every_raw_frame_not_only_native():
    events,raw,consumed=private_sequence()
    raw[2]=dict(raw[1],frame_id=2,capture_wall=101.,capture_sim_time=6.,encoded_wall=101.04)
    assert not smoke.stage_measurements(events,raw,consumed,private_native_pixels=True)['exact_sensor_pixel_binding']
    events.append(dict(events[0],frame_id=2,capture_wall=101.,capture_sim_time=6.,wall_time=101.01))
    assert smoke.stage_measurements(events,raw,consumed,private_native_pixels=True)['exact_sensor_pixel_binding']


def test_explicitly_unpublished_tail_does_not_claim_native_input_or_hash_mismatch():
    events,raw,consumed=private_sequence()
    raw[2]=dict(raw[1],frame_id=2,capture_wall=101.,capture_sim_time=6.,encoded_wall=101.04)
    reject=dict(event='private_publish_rejected',frame_id=2,capture_wall=101.,capture_sim_time=6.,
        wall_time=101.01,wall_clock='provider_monotonic',reason='runtime_stopped')
    events.append(reject)
    result=smoke.stage_measurements(events,raw,consumed,private_native_pixels=True)
    assert result['exact_sensor_pixel_binding']
    assert result['unpublished_private_frames']=={2:'runtime_stopped'}
    assert result['stages']['exposure_to_private_pixels']['sample_count']==1
    for key,value in [('reason','guessed_release_ack'),('capture_wall',101.0001),
        ('capture_sim_time',6.0001),('wall_clock','linux_local'),('wall_time',101.041)]:
        bad=copy.deepcopy(events);bad[-1][key]=value
        assert not smoke.stage_measurements(bad,raw,consumed,private_native_pixels=True)['exact_sensor_pixel_binding']
    events.append(dict(events[2],frame_id=2,capture_sim_time=6.))
    assert not smoke.stage_measurements(events,raw,consumed,private_native_pixels=True)['exact_sensor_pixel_binding']


def test_rejected_and_published_duplicate_frame_is_not_a_valid_explanation():
    events,raw,consumed=private_sequence()
    events.append(dict(events[0],event='private_publish_rejected',reason='capture_revoked'))
    assert not smoke.stage_measurements(events,raw,consumed,private_native_pixels=True)['exact_sensor_pixel_binding']


def test_explicit_fast_codec_requires_recorded_unchanged_extension_identity():
    plan=smoke.build_plan('wsl_stdio_bgr_v2',private_native_pixels=True,raw_base64_codec='pybase64_1_5_1')
    m=measured();m['configuration']=copy.deepcopy(plan['configuration'])
    assert not smoke.classify(m,plan=plan)['live_static_chain_qualified']
    m['raw_codec_identity_unchanged']=True
    assert smoke.classify(m,plan=plan)['live_static_chain_qualified']
    m['raw_codec_identity_unchanged']=False
    assert not smoke.classify(m,plan=plan)['live_static_chain_qualified']
    for codec in ('automatic','pybase64',None,True):
        try:smoke.build_plan('wsl_stdio_bgr_v2',raw_base64_codec=codec)
        except ValueError:pass
        else:raise AssertionError('unreviewed codec accepted')


def test_deferred_rgb_diagnostic_requires_exact_postclose_actual_pixel_proof():
    events,raw,consumed=private_sequence()
    raw[1]['shape']=[1080,1440,3]
    for event in (events[2],events[3]):
        event.update(raw_rgb_sha256=None,raw_bgr_sha256='b'*64,episode=2,binding_epoch=3,
            observed_seq=7,capture_sim_time=5.,observation_sim_time=5.01,
            rgb_trace_strategy='archived_bgr_postclose_exact_channel_swap')
    proof=dict(frame_id=1,original_capture_wall=100.,original_capture_sim_time=5.,
        original_control_time_ns=5010000000,observation_sim_time=5.01,
        request_identities=[dict(observed_seq=7,episode=2,binding_epoch=3)],
        raw_bgr_sha256='b'*64,derived_rgb_sha256='a'*64,raw_rgb_sha256='a'*64,
        strategy='archived_bgr_postclose_exact_channel_swap',image_bytes=4665600,shape=[1080,1440,3])
    audit=dict(schema='polar.live.native-pixel-audit.v1',clean=True,errors=[],proofs=[proof])
    assert not smoke.stage_measurements(events,raw,consumed,private_native_pixels=True)['exact_sensor_pixel_binding']
    assert smoke.stage_measurements(events,raw,consumed,private_native_pixels=True,pixel_audit=audit)['exact_sensor_pixel_binding']
    for key,value in [('original_capture_wall',100.00001),('original_capture_sim_time',5.00001),
        ('original_control_time_ns',5010000001),('raw_bgr_sha256','c'*64),
        ('derived_rgb_sha256','c'*64),('raw_rgb_sha256','c'*64),('strategy','guessed'),
        ('image_bytes',3),('shape',[1,1,3])]:
        bad=copy.deepcopy(audit);bad['proofs'][0][key]=value
        assert not smoke.stage_measurements(events,raw,consumed,private_native_pixels=True,pixel_audit=bad)['exact_sensor_pixel_binding']
    bad=copy.deepcopy(audit);bad['proofs'][0]['request_identities'][0]['observed_seq']=8
    assert not smoke.stage_measurements(events,raw,consumed,private_native_pixels=True,pixel_audit=bad)['exact_sensor_pixel_binding']
    for value in (None,dict(audit,clean=False),dict(audit,errors=['missing_BRG']),dict(audit,proofs=[])):
        assert not smoke.stage_measurements(events,raw,consumed,private_native_pixels=True,pixel_audit=value)['exact_sensor_pixel_binding']
    plan=smoke.build_plan('wsl_stdio_bgr_v2',private_native_pixels=True)
    m=measured();m['configuration']=copy.deepcopy(plan['configuration']);m['postclose_actual_pixel_audit']=False
    assert not smoke.classify(m,plan=plan)['live_static_chain_qualified']
