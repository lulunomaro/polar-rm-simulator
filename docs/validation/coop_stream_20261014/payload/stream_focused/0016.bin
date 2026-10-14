"""Pure local-clock/chunk readiness checks; no WSL, ROS, NN or rendering."""
import copy
import json
import stat
import threading
from types import SimpleNamespace
import pytest
from rm_match.deployment.wsl_jsonl_worker import StopTokenPoller
from rm_match.deployment.wsl_jsonl import validate_io_metrics,validate_cleanup
from rm_match.platform_v2.contracts import ContractError
from tests.test_wsl_jsonl import proof

class Clock:
    now=0.
    def __call__(self):return self.now
class Token:
    exists=False;mode=stat.S_IFREG;payload=None;checks=0
    def lstat(self):
        self.checks+=1
        if not self.exists:raise FileNotFoundError()
        return SimpleNamespace(st_mode=self.mode)
    def read_bytes(self):return json.dumps(self.payload).encode()

def setup():
    clock=Clock();token=Token();event=threading.Event()
    poller=StopTokenPoller(event,token,'run','sha',clock=clock)
    return clock,token,event,poller

def test_ten_thousand_immediately_ready_chunks_do_not_scan_drvfs_per_chunk():
    clock,token,event,p=setup();assert not p.stopped(force=True)
    for chunk in range(10001):
        clock.now=chunk*1e-6
        assert not p.stopped()
    assert p.checks==3 and token.checks==3  # 0, 5 ms, 10 ms
    assert p.cost_s==0.

def test_new_stop_is_discovered_at_five_ms_boundary_without_timestamp_refresh():
    clock,token,event,p=setup();p.stopped(force=True)
    clock.now=.00001;token.exists=True;token.payload=dict(run_id='run',spec_sha256='sha')
    assert not p.stopped()
    clock.now=.004999;assert not p.stopped()
    clock.now=.005;assert p.stopped()
    assert token.checks==2

def test_memory_event_is_immediate_even_with_file_not_due_and_invalid_clock():
    clock,token,event,p=setup();p.stopped(force=True);checks=token.checks
    event.set();clock.now=float('nan')
    assert p.stopped() and token.checks==checks

@pytest.mark.parametrize('payload',[dict(run_id='other',spec_sha256='sha'),
    dict(run_id='run',spec_sha256='other'),dict(run_id='run',spec_sha256='sha',unknown=True)])
def test_forced_pre_spawn_check_refuses_wrong_identity_even_before_next_due(payload):
    clock,token,event,p=setup();p.stopped(force=True)
    clock.now=.001;token.exists=True;token.payload=payload
    with pytest.raises(ValueError,match='identity mismatch'):p.stopped(force=True)
    assert token.checks==2

def test_link_and_nonregular_token_still_fail_closed():
    for mode in (stat.S_IFLNK,stat.S_IFDIR):
        clock,token,event,p=setup();token.exists=True;token.mode=mode
        with pytest.raises(ValueError):p.stopped(force=True)

def test_real_token_wrong_run_and_real_link_are_checked_without_running_worker(tmp_path):
    clock=Clock();path=tmp_path/'STOP';path.write_text(json.dumps(dict(run_id='wrong',spec_sha256='sha')))
    with pytest.raises(ValueError,match='identity mismatch'):
        StopTokenPoller(threading.Event(),path,'run','sha',clock=clock).stopped(force=True)
    path.unlink();target=tmp_path/'token';target.write_text('{}')
    try:path.symlink_to(target)
    except OSError:pytest.skip('Windows symbolic-link privilege unavailable')
    with pytest.raises(ValueError,match='link rejected'):
        StopTokenPoller(threading.Event(),path,'run','sha',clock=clock).stopped(force=True)

def test_local_clock_regression_cannot_suppress_future_file_checks():
    clock,token,event,p=setup();clock.now=1.;p.stopped(force=True);clock.now=.999
    with pytest.raises(ValueError,match='regressed'):p.stopped()

def test_check_cost_is_measured_at_real_check_not_every_ready_chunk():
    clock,token,event,p=setup()
    def delayed_stat():
        token.checks+=1;clock.now+=.0002;raise FileNotFoundError()
    token.lstat=delayed_stat
    assert not p.stopped(force=True)
    clock.now=.004;assert not p.stopped()
    clock.now=.005;assert not p.stopped()
    assert p.checks==2 and p.cost_s==pytest.approx(.0004)

def metrics():
    return dict(clock='linux_monotonic',input_chunks=96,input_bytes=6220800,complete_requests=1,
        stop_file_checks=5,stop_check_cost_s=.0001,last_request=dict(first_read_wall=10.,last_read_wall=10.01,
            queued_wall=10.02,peer_write_completed_wall=10.03,response_received_wall=10.04))

def test_cleanup_optional_scalar_metrics_and_old_shape_are_both_valid():
    record,hello=proof();assert validate_cleanup(record,'run','sha',hello)==record
    record['io_metrics']=metrics()
    assert validate_cleanup(record,'run','sha',hello)['io_metrics']==metrics()
    partial=metrics();partial['last_request'].update(queued_wall=None,peer_write_completed_wall=None,response_received_wall=None)
    assert validate_io_metrics(partial)==partial
    empty=metrics();empty.update(input_chunks=0,input_bytes=0,complete_requests=0)
    empty['last_request']={k:None for k in empty['last_request']}
    assert validate_io_metrics(empty)==empty

@pytest.mark.parametrize('mutate',[
    lambda x:x.update(input_chunks=True),lambda x:x.update(input_bytes=2**53),
    lambda x:x.update(input_bytes=96*65536+1),lambda x:x.update(input_bytes=95),
    lambda x:x.update(complete_requests=97),
    lambda x:x.update(complete_requests=-1),lambda x:x.update(stop_check_cost_s=float('nan')),
    lambda x:x.update(stop_check_cost_s=True),lambda x:x.update(clock='windows_perf_counter'),
    lambda x:x.update(sensor_body='forbidden'),lambda x:x['last_request'].update(response_received_wall=float('inf')),
    lambda x:x['last_request'].update(first_read_wall=True),lambda x:x['last_request'].update(queued_wall=9.),
    lambda x:x['last_request'].update(queued_wall=None),lambda x:x['last_request'].update(unknown=1),
    lambda x:x.update(complete_requests=0),lambda x:x.update(input_chunks=0)])
def test_metrics_reject_unknown_nonfinite_bool_count_and_partial_time_mismatch(mutate):
    value=metrics();mutate(value)
    with pytest.raises(ContractError):validate_io_metrics(value)
