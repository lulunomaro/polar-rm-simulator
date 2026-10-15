"""Meaningful fail-closed report checks; no fake inference/physics success."""
import copy
import importlib.util
import math
import pytest
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


def test_explicit_host_thread_setting_needs_unchanged_actual_api_proof():
    plan=smoke.build_plan('wsl_stdio_v1',host_opencv_threads=1)
    m=measured();m['configuration']=copy.deepcopy(plan['configuration'])
    assert not smoke.classify(m,plan=plan)['live_static_chain_qualified']
    m['host_opencv_setting_unchanged']=True
    assert smoke.classify(m,plan=plan)['live_static_chain_qualified']
    for wrong in (False,1,None):
        m['host_opencv_setting_unchanged']=wrong
        assert not smoke.classify(m,plan=plan)['live_static_chain_qualified']


def test_async_pending_or_late_cannot_supply_required_timely_native_samples():
    plan=smoke.build_plan('wsl_async_bgr_v3')
    m=measured();m['configuration']=copy.deepcopy(plan['configuration'])
    m['original_async_transactions_accounted']=True
    assert smoke.classify(m,plan=plan)['live_static_chain_qualified']
    for key in ('native_results','distinct_native_actuated_frames'):
        candidate=copy.deepcopy(m);candidate[key]=0;candidate['async_pending_statuses']=100
        candidate['async_terminal_dispositions']={'async_late_discard':100}
        assert not smoke.classify(candidate,plan=plan)['live_static_chain_qualified']
    m['original_async_transactions_accounted']=False
    assert not smoke.classify(m,plan=plan)['live_static_chain_qualified']


def async_events():
    source=dict(robot_id='red_sentry',episode=1,binding_epoch=2,observed_seq=7,sim_time=.422,wall_deadline=100.08)
    shared=dict(request_id=1,source_context=source,**source,frame_id=7,exposure_timestamp_ns=410000000,
        control_time_ns=422000000,capture_sim_time=.410,raw_bgr_sha256='a'*64,bgr_bytes=4665600)
    response=dict(inference_calls=1,clock_time_ns=422000000,tracking=True)
    rows=[dict(shared,event='async_transport_request',wall_time=100.01),
        dict(shared,event='async_native_started',wall_time=100.02,native_stdin_complete=True),
        dict(shared,event='async_native_stdout',wall_time=100.04,response=response),
        dict(shared,event='async_result_accepted80',wall_time=100.05,response=response),
        dict(shared,event='native_result',wall_time=100.051,wall_clock='host_perf_counter',
             observation_sim_time=source['sim_time'],response=response)]
    return rows


def test_async_original_source_accounting_rejects_late_context_and_fake_native_count():
    rows=async_events()
    assert smoke.async_transaction_measurements(rows,{})['original_async_transactions_accounted']
    for index,field,value in ((2,'frame_id',8),(3,'wall_time',100.081),(4,'response',{}),(1,'native_stdin_complete',False)):
        candidate=copy.deepcopy(rows);candidate[index][field]=value
        assert not smoke.async_transaction_measurements(candidate,{})['original_async_transactions_accounted']
    rows=rows[:2]+[dict(rows[2],event='async_late_discard',wall_time=100.1)]
    result=smoke.async_transaction_measurements(rows,{})
    assert result['original_async_transactions_accounted'] and result['async_timely_accepted_results']==0
    assert result['async_terminal_dispositions']=={'async_late_discard':1}


def test_async_inflight_requires_original_owned_cleanup_proof():
    rows=async_events()[:2];r=rows[0]
    journal=cancel_evidence(r,'native_cancelled')
    assert smoke.async_transaction_measurements(rows,journal)['original_async_transactions_accounted']
    journal['CLEANUP.json']['clean']=False
    assert not smoke.async_transaction_measurements(rows,journal)['original_async_transactions_accounted']


def cancel_evidence(request,event='input_cancelled',*,full_payload=False):
    from rm_match.integrations.wsl_aim_async_worker import SCHEMA,TRANSPORT
    identity=dict(run_id='a'*32,supervisor_pid=998,pid=999,pgid=999,boot_id='test-boot',leader_start_ticks=1,
        spec_sha256='b'*64,transport=TRANSPORT)
    ready=dict(event='ready',schema=SCHEMA,transport=TRANSPORT,run_id=identity['run_id'],supervisor_pid=998,
        native_pid=999,spec_sha256='b'*64,native_ticks=0,inference_calls=0,camera_captures=0,physics_steps=0)
    source=dict(schema=SCHEMA,transport=TRANSPORT,id=request['request_id'],source_context=copy.deepcopy(request['source_context']),
        frame_id=request['frame_id'],exposure_timestamp_ns=request['exposure_timestamp_ns'],control_time_ns=request['control_time_ns'],
        image_sha256=request['raw_bgr_sha256'],bgr_bytes=4665600,clock_domain='linux_local_diagnostic_only')
    terminal=dict(source,event=event,reason='host_cancel',ownership=copy.deepcopy(identity))
    journal=dict(schema=SCHEMA,transport=TRANSPORT,ownership=copy.deepcopy(identity),events=[copy.deepcopy(ready)],inflight_at_close=None)
    trace=[dict(event='closed',clean=True,linux_child_reaped=True,native_not_spawned=False,errors=[])]
    if event=='native_cancelled':
        terminal.update(native_stdin_bytes_written=1729,native_stdin_expected_bytes=1729,native_stdout_buffer_bytes=0)
        journal['events'].append(terminal)
    elif event=='input_cancelled':
        journal['events'].append(dict(source,event='input_header_received',header_validated=True,received_bgr_bytes=1024))
        terminal.update(phase='validated_payload' if full_payload else 'receiving_payload',header_validated=True,
            received_bgr_bytes=4665600 if full_payload else 1024,payload_sha256_verified=full_payload,
            verified_image_sha256=request['raw_bgr_sha256'] if full_payload else None,
            native_stdin_bytes_written=0,native_compute_started=False)
        journal['events'].append(terminal)
    else:
        terminal=dict(request,event='async_cancelled_before_write',phase='queued',reason='host_cancel',writer_joined=True,
            transport_write_attempted=False,transport_write_in_progress=False,transport_bytes_written=0,
            transport_expected_bytes=4667000,ownership=copy.deepcopy(identity))
        trace.insert(0,terminal)
    return {'OWNED_CHILD.json':copy.deepcopy(identity),'STARTUP.json':ready,'NATIVE_EVENTS.json':journal,'HOST_TRACE.json':trace,
        'CLEANUP.json':dict(identity,reason='host_cancel',clean=True,reaped=True,group_empty=True,tmpfs_removed=True,remaining_members=[],errors=[])}


@pytest.mark.parametrize('kind',['unwritten','partial','full'])
def test_phase_specific_pre_native_cancellation_accounts_only_original_source_not_inference(kind):
    rows=async_events()[:1]
    evidence=cancel_evidence(rows[0],'async_cancelled_before_write' if kind=='unwritten' else 'input_cancelled',full_payload=kind=='full')
    result=smoke.async_transaction_measurements(rows,evidence)
    assert result['original_async_transactions_accounted'] and result['async_incomplete_transactions']==0
    assert result['async_actual_complete_stdin']==result['async_timely_accepted_results']==result['async_owned_cancelled_at_close']==0
    assert result['async_owned_unwritten_cancelled_at_close']==(1 if kind=='unwritten' else 0)
    assert result['async_owned_input_cancelled_at_close']==(0 if kind=='unwritten' else 1)


@pytest.mark.parametrize('change',['missing_owner','cleanup_false','not_reaped','group_alive','tmpfs_alive','wrong_run',
    'wrong_birth','wrong_ready','bool_ready','wrong_row_owner','no_host_join','missing_header','wrong_admission_transport',
    'wrong_admission_schema','wrong_admission_clock','wrong_robot','typed_seq','typed_sim','wrong_hash','bad_phase',
    'unverified_full','false_native_zero','conflicting_start','conflicting_result','duplicate_cancel','fault_ledger','fault_trace'])
def test_input_cancellation_requires_typed_original_header_and_same_actual_owned_endpoint(change):
    rows=async_events()[:1];evidence=cancel_evidence(rows[0]);journal=evidence['NATIVE_EVENTS.json'];terminal=journal['events'][-1]
    if change=='missing_owner':evidence.pop('OWNED_CHILD.json')
    elif change=='cleanup_false':evidence['CLEANUP.json']['clean']=False
    elif change=='not_reaped':evidence['CLEANUP.json']['reaped']=False
    elif change=='group_alive':evidence['CLEANUP.json']['remaining_members']=[999]
    elif change=='tmpfs_alive':evidence['CLEANUP.json']['tmpfs_removed']=False
    elif change=='wrong_run':evidence['CLEANUP.json']['run_id']='c'*32
    elif change=='wrong_birth':evidence['CLEANUP.json']['leader_start_ticks']=True
    elif change=='wrong_ready':evidence['STARTUP.json']['native_pid']=1000
    elif change=='bool_ready':journal['events'][0]['native_ticks']=False
    elif change=='wrong_row_owner':terminal['ownership']['run_id']='c'*32
    elif change=='no_host_join':evidence['HOST_TRACE.json'][0]['clean']=False
    elif change=='missing_header':journal['events'].pop(1)
    elif change=='wrong_admission_transport':journal['events'][1]['transport']='other'
    elif change=='wrong_admission_schema':journal['events'][1]['schema']='other'
    elif change=='wrong_admission_clock':journal['events'][1]['clock_domain']='host_perf_counter'
    elif change=='wrong_robot':terminal['source_context']['robot_id']='blue_sentry'
    elif change=='typed_seq':terminal['source_context']['observed_seq']=7.
    elif change=='typed_sim':terminal['source_context']['sim_time']=False
    elif change=='wrong_hash':terminal['image_sha256']='c'*64
    elif change=='bad_phase':terminal['phase']='unknown'
    elif change=='unverified_full':terminal['received_bgr_bytes']=4665600
    elif change=='false_native_zero':terminal['native_stdin_bytes_written']=False
    elif change=='conflicting_start':rows.append(dict(rows[0],event='async_native_started',native_stdin_complete=True))
    elif change=='conflicting_result':journal['events'].insert(1,dict(terminal,event='result'))
    elif change=='fault_ledger':rows.append(dict(rows[0],event='async_native_fault',error='unknown supervisor message'))
    elif change=='fault_trace':evidence['HOST_TRACE.json'].insert(0,dict(event='async_native_fault',error='unknown supervisor message'))
    else:journal['events'].append(copy.deepcopy(terminal))
    assert not smoke.async_transaction_measurements(rows,evidence)['original_async_transactions_accounted']


@pytest.mark.parametrize('change',['attempted','blocked','bytes','writer_alive','typed_id','header_observed','source_mismatch'])
def test_unwritten_cancellation_never_accepts_ambiguous_or_contradicted_zero_count(change):
    rows=async_events()[:1];evidence=cancel_evidence(rows[0],'async_cancelled_before_write')
    proof=evidence['HOST_TRACE.json'][0]
    if change=='attempted':proof['transport_write_attempted']=True
    elif change=='blocked':proof['transport_write_in_progress']=True
    elif change=='bytes':proof['transport_bytes_written']=1
    elif change=='writer_alive':proof['writer_joined']=False
    elif change=='typed_id':proof['request_id']=True
    elif change=='header_observed':evidence['NATIVE_EVENTS.json']['events'].append(dict(event='input_header_received',id=1))
    else:proof['source_context']=dict(proof['source_context'],observed_seq=8)
    assert not smoke.async_transaction_measurements(rows,evidence)['original_async_transactions_accounted']


def test_old_host_cancel_or_unknown_header_remains_incomplete_even_with_clean_owned_resources():
    rows=async_events()[:1];rows.append(dict(rows[0],event='async_control_cancelled',reason='owned_stop_requested'))
    evidence=cancel_evidence(rows[0]);evidence['NATIVE_EVENTS.json']['events']=evidence['NATIVE_EVENTS.json']['events'][:1]
    evidence['NATIVE_EVENTS.json']['input_at_close']={'header_validated':False,'header_bytes':11}
    result=smoke.async_transaction_measurements(rows,evidence)
    assert not result['original_async_transactions_accounted'] and result['async_incomplete_transactions']==1


def test_write_interruption_candidate_cannot_replace_independent_linux_terminal_or_add_native_samples():
    rows=async_events()[:1]
    candidate=dict(rows[0],event='async_transport_write_interrupted',owned_stop_requested=True,
        reason='owned_stop_pipe_closed',transport_bytes_written=0,transport_write_attempted=True,transport_write_in_progress=True)
    rows.append(candidate)
    without=smoke.async_transaction_measurements(rows,{})
    assert not without['original_async_transactions_accounted'] and without['async_incomplete_transactions']==1
    evidence=cancel_evidence(rows[0]);evidence['HOST_TRACE.json'].insert(0,copy.deepcopy(candidate))
    proven=smoke.async_transaction_measurements(rows,evidence)
    assert proven['original_async_transactions_accounted'] and proven['async_owned_input_cancelled_at_close']==1
    assert proven['async_actual_complete_stdin']==proven['async_wrapper_native_results']==proven['async_timely_accepted_results']==0
    evidence['NATIVE_EVENTS.json']['events'][-1]['source_context']['observed_seq']=8
    assert not smoke.async_transaction_measurements(rows,evidence)['original_async_transactions_accounted']


def expired_wrapper_events(stamp=100.08):
    rows=async_events();rows[-1].update(event='native_response_expired_before_action',wall_time=stamp)
    return rows


@pytest.mark.parametrize('stamp',[100.08,100.081])
def test_bridge_acceptance_then_wrapper_expiry_is_accounted_without_timely_native_result(stamp):
    rows=expired_wrapper_events(stamp)
    result=smoke.async_transaction_measurements(rows,{})
    assert result['original_async_transactions_accounted'] and result['async_incomplete_transactions']==0
    assert result['async_timely_accepted_results']==1 and result['async_wrapper_native_results']==0
    assert result['async_expired_before_action']==1 and not any(r['event']=='native_result' for r in rows)
    # The existing qualification gate still needs actual timely result samples.
    plan=smoke.build_plan('wsl_async_bgr_v3');m=measured();m.update(result)
    m['configuration']=copy.deepcopy(plan['configuration']);m['native_results']=0
    assert not smoke.classify(m,plan=plan)['checks']['native_sample_count']


@pytest.mark.parametrize('change',['missing','duplicate','also_result','early','bad_clock','nonfinite','bool_time',
    'robot','episode','epoch','seq','seq_type','sim_type','deadline','frame','capture','hash','response','response_type',
    'missing_sim','not_accepted'])
def test_expired_wrapper_requires_unique_typed_original_source_response_and_real_expiry(change):
    rows=expired_wrapper_events();row=rows[-1]
    if change=='missing':rows.pop()
    elif change=='duplicate':rows.append(copy.deepcopy(row))
    elif change=='also_result':rows.append(dict(row,event='native_result',wall_time=100.05))
    elif change=='early':row['wall_time']=math.nextafter(100.08,-math.inf)
    elif change=='bad_clock':row['wall_clock']='linux_local_diagnostic_only'
    elif change=='nonfinite':row['wall_time']=float('inf')
    elif change=='bool_time':row['wall_time']=True
    elif change=='robot':row['robot_id']='blue_sentry'
    elif change=='episode':row['episode']=2
    elif change=='epoch':row['binding_epoch']=3
    elif change=='seq':row['observed_seq']=8
    elif change=='seq_type':row['observed_seq']=7.
    elif change=='sim_type':row['observation_sim_time']=False
    elif change=='deadline':row['wall_deadline']=100.081
    elif change=='frame':row['frame_id']=8
    elif change=='capture':row['capture_sim_time']=.411
    elif change=='hash':row['raw_bgr_sha256']='b'*64
    elif change=='response':row['response']={}
    elif change=='response_type':row['response']=dict(row['response'],inference_calls=True)
    elif change=='missing_sim':row.pop('observation_sim_time')
    else:rows.pop(3)
    assert not smoke.async_transaction_measurements(rows,{})['original_async_transactions_accounted']


def test_expiry_allows_only_documented_wrapper_fields_and_does_not_relabel_old_source():
    rows=expired_wrapper_events();response=rows[-1]['response']
    rows[-1]['response']=dict(response,episode=rows[-1]['episode'],should_control=True)
    assert smoke.async_transaction_measurements(rows,{})['original_async_transactions_accounted']
    rows[-1]['response']['new_clock']=200.
    assert not smoke.async_transaction_measurements(rows,{})['original_async_transactions_accounted']


def original_receipt():
    budget=dict(robot_id='red_infantry',episode=0,frame_id=22,capture_wall=132185.2877611,
        capture_sim_time=1.306000000000001,wall_deadline=132185.36776109997,sim_deadline=1.386000000000001)
    return dict(robot_id='red_infantry',episode=0,frame_id=22,consume_wall=132185.3630102,
        consume_sim_time=budget['sim_deadline'],budget=budget)


def test_original_absolute_sim_deadline_passes_despite_unrounded_float_difference():
    row=original_receipt();budget=row['budget']
    assert row['consume_sim_time']-budget['capture_sim_time']==.08000000000000007
    assert smoke.actuator_receipt_budget_checks(row)==dict(wall=True,sim=True)
    m=measured();m['actuator_budget_receipts']=[row]
    m['actuator_wall_ages_s']=[row['consume_wall']-budget['capture_wall']]
    m['actuator_sim_ages_s']=[row['consume_sim_time']-budget['capture_sim_time']]
    assert smoke.classify(m)['live_static_chain_qualified']
    assert m['actuator_sim_ages_s']==[.08000000000000007]
    # Reported raw differences must still exactly match their original receipts.
    m['actuator_sim_ages_s']=[.08]
    assert not smoke.classify(m)['checks']['actuator_sim_ages_s']


@pytest.mark.parametrize('axis',['wall','sim'])
def test_absolute_budget_boundary_is_exact_in_each_original_clock(axis):
    row=original_receipt();budget=row['budget']
    consume='consume_wall' if axis=='wall' else 'consume_sim_time';deadline='wall_deadline' if axis=='wall' else 'sim_deadline'
    capture='capture_wall' if axis=='wall' else 'capture_sim_time'
    row[consume]=math.nextafter(budget[capture],-math.inf)
    assert not smoke.actuator_receipt_budget_checks(row)[axis]
    row[consume]=math.nextafter(budget[deadline],-math.inf)
    assert smoke.actuator_receipt_budget_checks(row)[axis]
    row[consume]=budget[deadline]
    assert smoke.actuator_receipt_budget_checks(row)[axis] is (axis=='sim')
    row[consume]=math.nextafter(budget[deadline],math.inf)
    assert not smoke.actuator_receipt_budget_checks(row)[axis]


@pytest.mark.parametrize('change',['wrong_robot','wrong_episode','bool_episode','wrong_frame','bool_frame',
    'late_wall_budget','late_sim_budget','empty_budget','nonfinite','bool_consume','extra_budget','missing_budget'])
def test_receipt_requires_finite_typed_original_identity_and_unexpanded_80ms_budget(change):
    row=original_receipt();budget=row['budget']
    if change=='wrong_robot':row['robot_id']='blue_infantry'
    elif change=='wrong_episode':row['episode']=1
    elif change=='bool_episode':row['episode']=False
    elif change=='wrong_frame':row['frame_id']=23
    elif change=='bool_frame':budget['frame_id']=True
    elif change=='late_wall_budget':budget['wall_deadline']=math.nextafter(budget['capture_wall']+.08,math.inf)
    elif change=='late_sim_budget':budget['sim_deadline']=math.nextafter(budget['capture_sim_time']+.08,math.inf)
    elif change=='empty_budget':budget['sim_deadline']=budget['capture_sim_time']
    elif change=='nonfinite':row['consume_sim_time']=float('nan')
    elif change=='bool_consume':row['consume_wall']=True
    elif change=='extra_budget':budget['renewed_at']=200.
    else:row.pop('budget')
    assert not all(smoke.actuator_receipt_budget_checks(row).values())


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


def test_unstarted_runtime_is_unmeasured_and_cleanup_does_not_define_physics_rtf():
    for timing in ({},{'start':100.},{'start':100.,'end':99.}):
        result=smoke.run_durations(timing,0.)
        assert result['physics_wall_s'] is None and result['physics_rtf'] is None
    result=smoke.run_durations(dict(start=100.,physics_end=110.,end=111.),10.)
    assert result['physics_wall_s']==10. and result['run_and_cleanup_wall_s']==11.
    assert result['physics_rtf']==1. and result['run_and_cleanup_rtf']==10/11


def test_failed_preparation_evidence_is_only_collected_from_unique_fresh_directory(tmp_path):
    import json
    out=tmp_path/'binding_a/wsl_pipe_supervisor_a';out.mkdir(parents=True)
    (out/'HOST_TRACE.json').write_text(json.dumps([dict(event='startup_failed')]))
    evidence,collection=smoke.collect_transport_evidence(tmp_path,None)
    assert collection['candidate_count']==1 and 'HOST_TRACE.json' in evidence
    assert 'STARTUP.json' not in evidence and 'CLEANUP.json' not in evidence
    (tmp_path/'binding_b/wsl_pipe_supervisor_b').mkdir(parents=True)
    evidence,collection=smoke.collect_transport_evidence(tmp_path,None)
    assert evidence=={} and collection['candidate_count']==2


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
