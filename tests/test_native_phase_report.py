"""Deterministic phase association and original live classification boundaries."""
import copy
import pytest
from tools.native_phase_report import summarize
from tools import smoke_wsl_native_live as smoke


def row(phase,wall,cpu,thread=1,**fields):
    return dict(phase=phase,wall_ns=wall,thread_cpu_ns=cpu,thread_id=thread,**fields)


def snapshot(rows,**fields):
    return dict(schema='polar.sim.numeric-phase-probe.v1',rows=rows,capacity=100,
        retained=len(rows),attempted=len(rows),dropped=0,complete=True,**fields)


def test_signed_residual_is_not_clamped_or_called_gil_wait():
    result=summarize(snapshot([row('authority_step_start',100,50,detail=7),row('authority_step_end',200,160,detail=7)]))
    span=result['spans'][0]
    assert span['wall_sum_s']==100/1e9 and span['thread_cpu_sum_s']==110/1e9
    assert span['wall_minus_thread_cpu_sum_s']==-10/1e9
    assert span['negative_residual_count']==1


def test_cross_thread_cpu_and_different_original_source_cannot_pair():
    rows=[row('write_start',100,50,thread=1,wall_deadline=123.),
          row('write_end',200,90,thread=2,wall_deadline=123.),
          row('write_end',300,110,thread=1,wall_deadline=124.),
          row('write_end',400,120,thread=1,wall_deadline=123)]
    result=summarize(snapshot(rows))
    assert result['spans']==[]
    assert result['unmatched_start_count']==1 and result['unmatched_end_count']==3


def test_nested_inclusive_spans_remain_separate_and_overflow_is_explicit():
    value=snapshot([row('step_start',100,20),row('collect_start',120,25),
                    row('collect_end',150,35),row('step_end',200,50)])
    value.update(complete=False,dropped=7,attempted=11)
    result=summarize(value)
    assert result['retention_complete'] is False and result['dropped']==7
    assert len(result['spans'])==2


def test_queue_and_reader_links_keep_cross_thread_cpu_absent_and_exact_typed_source():
    rows=[row('async_queue_put',100,10,thread=1,request_id=5,wall_deadline=123.),
          row('async_queue_get',150,900,thread=2,request_id=5,wall_deadline=123.),
          row('async_reader_entry',200,1000,thread=3,request_id=5,wall_deadline=123.,detail='result'),
          row('async_reader_validated',230,1010,thread=3,request_id=5,wall_deadline=123.,detail='result'),
          row('async_caller_return',250,50,thread=1,request_id=5,wall_deadline=123.,detail='accepted'),
          row('async_queue_get',170,40,thread=1,request_id=5,wall_deadline=123)]
    linked=summarize(snapshot(rows))['linked_intervals']
    assert linked['outgoing_queue']['wall']['count']==1
    assert linked['outgoing_queue']['same_thread_cpu']['count']==0
    assert linked['outgoing_queue']['cross_thread_count']==1
    assert linked['reader_parse_validate']['wall']['p50_ms']==30/1e6
    assert linked['reader_parse_validate']['same_thread_cpu']['p50_ms']==10/1e6
    assert linked['validated_result_to_accepted_caller']['same_thread_cpu']['count']==0


@pytest.mark.parametrize('mode',[1,None,'yes'])
def test_profile_plan_requires_explicit_boolean(mode):
    with pytest.raises(ValueError):smoke.build_plan('wsl_async_bgr_v3',profile_phases=mode)


def test_profile_opt_in_does_not_rewrite_base_plan_or_deadlines():
    original=copy.deepcopy(smoke.PLAN)
    assert smoke.build_plan('wsl_stdio_v1')==original
    plan=smoke.build_plan('wsl_async_bgr_v3',profile_phases=True)
    assert plan['configuration']['camera_native_budget_s']==.08
    assert plan['configuration']['server_input_window_s']==.15
    assert plan['configuration']['host_phase_capacity']==262144
    assert plan['configuration']['authority_phase_detail_stride']==50
    assert plan['criteria']['host_phase_trace_complete'] is True
    assert smoke.PLAN==original
    with pytest.raises(ValueError):smoke.build_plan('wsl_stdio_bgr_v2',profile_phases=True)


def test_coarse_cpu_accounting_is_reported_without_inventing_subphase_precision():
    value=snapshot([row('step_start',100,15625000),row('step_end',200,15625000),
                    row('step_start',20000000,31250000),row('step_end',20000100,31250000)])
    result=summarize(value)
    assert result['observed_thread_cpu_accounting'][0]['min_positive_observed_increment_ns']==15625000
    assert result['spans'][0]['thread_cpu']['p50_ms']==0.
    assert 'unresolved' in result['observed_thread_cpu_accounting'][0]['note']


@pytest.mark.parametrize('complete',[False,None,1])
def test_profile_classification_cannot_treat_incomplete_or_untyped_trace_as_success(complete):
    from pathlib import Path
    import runpy
    measured=runpy.run_path(str(Path(__file__).with_name('test_wsl_native_live_classification.py')))['measured']()
    plan=smoke.build_plan('wsl_async_bgr_v3',profile_phases=True)
    measured.update(configuration=copy.deepcopy(plan['configuration']),original_async_transactions_accounted=True,
        host_phase_trace_complete=complete)
    assert smoke.classify(measured,plan=plan)['checks']['host_phase_trace_complete'] is False
    measured['host_phase_trace_complete']=True
    assert smoke.classify(measured,plan=plan)['live_static_chain_qualified'] is True
