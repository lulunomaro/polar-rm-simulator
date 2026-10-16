"""Acceptance decision vs log publication; original authority never extends."""
import copy
from unittest.mock import patch
import pytest
from tests.test_wsl_native_live_classification import smoke,async_events
from tests.test_wsl_aim_async import actor,header,packet,reply


def decision_events():
    rows=async_events()
    rows[0]['original_host_deadline']=100.08
    rows[3].update(wall_time=100.081,acceptance_decision_wall=100.05,
        original_host_deadline=100.08,wall_clock='host_perf_counter')
    rows[-1].update(event='native_response_expired_before_action',wall_time=100.082)
    return rows


def test_original_check_before_deadline_and_delayed_log_are_distinct_from_withheld_response():
    rows=decision_events();r=smoke.async_transaction_measurements(rows,{})
    assert r['original_async_transactions_accounted']
    assert r['async_timely_accepted_results']==r['async_expired_before_action']==1
    assert r['async_wrapper_native_results']==0
    assert rows[3]['wall_time']>rows[3]['wall_deadline'] and rows[3]['acceptance_decision_wall']<rows[3]['wall_deadline']


@pytest.mark.parametrize('fault',['missing_decision','at_deadline','after_log','before_stdout','nan','bool','wrong_clock',
    'missing_internal_deadline','changed_internal_deadline','changed_request_deadline','fake_native_success'])
def test_new_metadata_never_rescues_old_or_invalid_authority(fault):
    rows=decision_events();row=rows[3]
    if fault=='missing_decision':row.pop('acceptance_decision_wall')
    elif fault=='at_deadline':row['acceptance_decision_wall']=100.08
    elif fault=='after_log':row['acceptance_decision_wall']=100.082
    elif fault=='before_stdout':row['acceptance_decision_wall']=100.03
    elif fault=='nan':row['acceptance_decision_wall']=float('nan')
    elif fault=='bool':row['acceptance_decision_wall']=True
    elif fault=='wrong_clock':row['wall_clock']='linux_local_diagnostic_only'
    elif fault=='missing_internal_deadline':row.pop('original_host_deadline')
    elif fault=='changed_internal_deadline':row['original_host_deadline']=100.09
    elif fault=='changed_request_deadline':rows[0]['original_host_deadline']=100.04
    else:rows[-1]['event']='native_result'
    assert not smoke.async_transaction_measurements(rows,{})['original_async_transactions_accounted']


def test_actual_control_samples_its_existing_check_without_backdating_log(tmp_path):
    a=actor(tmp_path);h,raw=header();p=packet(a,h,raw);clock=[100.01]
    original_record=a._record
    def record(event,**fields):
        if event=='async_result_accepted80':clock[0]=100.081
        return original_record(event,**fields)
    a._record=record
    def complete(_timeout):
        sent=__import__('json').loads(a._outgoing.get_nowait()[0])
        a._handle_message(reply(sent,'native_started'));a._handle_message(reply(sent))
        clock[0]=100.079
    a._async_wake.wait=complete
    with patch('rm_match.integrations.wsl_aim_async.time.perf_counter',side_effect=lambda:clock[0]):
        response=a.control(p,source_context=h['source_context'])
    event=a.diagnostics[-1]
    assert event['event']=='async_result_accepted80'
    assert event['acceptance_decision_wall']==100.079 and event['wall_time']==100.081
    assert event['source_context']['wall_deadline']==100.08
    assert response['episode']==h['source_context']['episode']
