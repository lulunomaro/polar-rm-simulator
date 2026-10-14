"""Framing/owned poll-thread fixtures only; no WSL, ROS, NN, GL or physics."""
import copy
import hashlib
import json
import stat
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from rm_match.deployment import wsl_jsonl_worker as worker
from rm_match.deployment.wsl_jsonl import validate_cleanup,validate_io_metrics
from rm_match.platform_v2.contracts import ContractError
from tests.test_wsl_jsonl import proof
from tests.test_wsl_jsonl_stop_poll import metrics


def test_actual_large_line_all_chunks_reconstruct_without_repeated_prefix_scan():
    raw=json.dumps({'schema':worker.SCHEMA,'op':'act','image':'A'*6_225_000},separators=(',',':')).encode()+b'\n'
    framer=worker.RequestFramer();seen=[]
    for offset in range(0,len(raw),65536):
        prior=framer.searched;part=raw[offset:offset+65536]
        result=framer.feed(part,pending=False)
        if result is None:
            assert framer.searched-prior==len(part)
        else:seen.append(result)
    assert seen==[raw[:-1]] and not framer.buffer
    assert worker.strict_json(seen[0])['image']=='A'*6_225_000


@pytest.mark.parametrize('chunk_size',[1,2,3,17,65536])
def test_framing_handles_split_unicode_and_lf_at_any_boundary(chunk_size):
    raw=json.dumps({'op':'act','note':'装甲板\n字串'},ensure_ascii=False).encode()+b'\n'
    framer=worker.RequestFramer();lines=[]
    for offset in range(0,len(raw),chunk_size):
        value=framer.feed(raw[offset:offset+chunk_size],pending=False)
        if value is not None:lines.append(value)
    assert lines==[raw[:-1]]
    assert worker.strict_json(lines[0])['note']=='装甲板\n字串'


def test_partial_tail_is_preserved_but_two_complete_lines_or_pending_line_rejected():
    framer=worker.RequestFramer()
    assert framer.feed(b'{"op":"reset"}\n{"op":',pending=False)==b'{"op":"reset"}'
    assert framer.buffer==b'{"op":' and framer.searched==len(framer.buffer)
    assert framer.feed(b'"act"}\n',pending=False)==b'{"op":"act"}'
    for raw,pending in ((b'{}\n{}\n',False),(b'{}\n',True)):
        with pytest.raises(ValueError,match='concurrent'):worker.RequestFramer().feed(raw,pending=pending)
    partial=worker.RequestFramer()
    assert partial.feed(b'{',pending=True) is None
    with pytest.raises(ValueError,match='concurrent'):partial.feed(b'}\n',pending=True)


def test_limit_applies_to_line_plus_terminator_and_retained_tail_without_large_allocation():
    framer=worker.RequestFramer(limit=4)
    assert framer.feed(b'123',pending=False) is None
    assert framer.feed(b'\n',pending=False)==b'123'
    assert framer.feed(b'1234',pending=False) is None
    with pytest.raises(ValueError,match='oversized'):framer.feed(b'5',pending=False)
    assert len(framer.buffer)==4


@pytest.mark.parametrize('raw',[b'{"x":1,"x":2}\n',b'{"x":NaN}\n',b'{"x":Infinity}\n'])
def test_complete_framed_line_still_receives_strict_json_validation(raw):
    line=worker.RequestFramer().feed(raw,pending=False)
    with pytest.raises(ValueError):worker.strict_json(line)


class BlockingToken:
    def __init__(self):self.entered=threading.Event();self.release=threading.Event()
    def lstat(self):
        self.entered.set()
        if not self.release.wait(2.):raise RuntimeError('fixture release timeout')
        raise FileNotFoundError()


def test_file_call_cannot_block_ingress_or_hide_unfinished_thread_at_shared_deadline():
    token=BlockingToken();stop=threading.Event();poller=worker.StopTokenPoller(stop,token,'run','sha')
    owned=worker.OwnedStopPollThread(poller);owned.start()
    try:
        assert token.entered.wait(.5)
        # Do actual framing while the separate file call is demonstrably blocked.
        framer=worker.RequestFramer()
        assert framer.feed(b'{"op":"act"}\n',pending=False)==b'{"op":"act"}'
        assert not owned.join_until(time.perf_counter()+.01)
        record,hello=proof();record.update(stop_poll_thread_started=True,stop_poll_thread_stopped=False,
            stop_poll_error_type=None,stop_poll_error_kind=None,clean=False)
        with pytest.raises(ContractError,match='stop_poll_cleanup'):validate_cleanup(record,'run','sha',hello)
    finally:
        token.release.set();owned.join_until(time.perf_counter()+1.)
    assert not owned.thread.is_alive()


@pytest.mark.parametrize('payload,mode,kind',[
    ({'run_id':'wrong','spec_sha256':'sha'},stat.S_IFREG,'identity_mismatch'),
    ({'run_id':'run','spec_sha256':'wrong'},stat.S_IFREG,'identity_mismatch'),
    ({'run_id':'run','spec_sha256':'sha'},stat.S_IFLNK,'link_rejected'),
    ({'run_id':'run','spec_sha256':'sha'},stat.S_IFDIR,'nonregular_token')])
def test_poll_fault_sets_memory_cancel_and_still_fails_clean_proof(payload,mode,kind):
    token=SimpleNamespace(lstat=lambda:SimpleNamespace(st_mode=mode),read_bytes=lambda:json.dumps(payload).encode())
    stop=threading.Event();poller=worker.StopTokenPoller(stop,token,'run','sha')
    owned=worker.OwnedStopPollThread(poller);owned.start()
    assert stop.wait(.5) and owned.join_until(time.perf_counter()+1.)
    assert owned.error_type=='ValueError' and poller.fault_kind==kind
    record,hello=proof();record.update(stop_poll_thread_started=True,stop_poll_thread_stopped=True,
        stop_poll_error_type=owned.error_type,stop_poll_error_kind=kind)
    with pytest.raises(ContractError):validate_cleanup(record,'run','sha',hello)


def test_memory_cancel_wakes_sleeping_poller_without_waiting_for_next_file_check():
    token=SimpleNamespace(lstat=lambda:(_ for _ in ()).throw(FileNotFoundError()))
    stop=threading.Event();owned=worker.OwnedStopPollThread(worker.StopTokenPoller(stop,token,'run','sha'))
    owned.start();stop.set()
    assert owned.join_until(time.perf_counter()+.5) and owned.error_type is None


def test_start_failure_is_auditable_and_no_false_thread_cleanliness():
    stop=threading.Event();owned=worker.OwnedStopPollThread(worker.StopTokenPoller(stop,None,'run','sha'))
    with patch.object(owned.thread,'start',side_effect=RuntimeError('fixture start failure')):
        with pytest.raises(RuntimeError):owned.start()
    assert not owned.started and stop.is_set() and owned.error_type=='RuntimeError'
    assert owned.poller.fault_kind=='thread_error' and owned.join_until(time.perf_counter())


def test_stop_sample_counts_and_cost_are_completed_check_snapshot_only():
    token=BlockingToken();stop=threading.Event();poller=worker.StopTokenPoller(stop,token,'run','sha')
    owned=worker.OwnedStopPollThread(poller);owned.start()
    try:
        assert token.entered.wait(.5)
        assert poller.checks==1 and poller.cumulative==(0,0.)
        samples=worker.request_metrics(1.,2.,poller.cumulative,poller.cumulative)
        assert samples['stop_checks_at_first_read']==samples['stop_checks_at_last_read']==0
    finally:token.release.set();owned.join_until(time.perf_counter()+1.)
    assert poller.cumulative[0]==1 and poller.cumulative[1]>=0


@pytest.mark.parametrize('stop_payload',[
    dict(run_id='wrong',spec_sha256='unused'),dict(run_id='run',spec_sha256='wrong')])
def test_force_bad_identity_worker_branch_never_constructs_peer(tmp_path,stop_payload):
    raw=json.dumps(dict(run_id='run',source_sha256={},linux={})).encode();spec=tmp_path/'SPEC.json';spec.write_bytes(raw)
    digest=hashlib.sha256(raw).hexdigest();(tmp_path/'STOP').write_text(json.dumps(stop_payload))
    with patch('rm_match.deployment.wsl_jsonl.validate_linux_settings',return_value=dict(cwd=str(tmp_path),command=['/fake/python'])),\
            patch.object(worker.os,'access',return_value=True),patch.object(worker.os,'O_NOFOLLOW',0,create=True),\
            patch.object(worker,'OwnedJsonProcess') as spawn:
        assert worker.run(spec,digest)==2
        spawn.assert_not_called()
    cleanup=json.loads((tmp_path/'CLEANUP.json').read_bytes())
    assert cleanup['ownership']['not_spawned'] and cleanup['stop_poll_thread_stopped']
    assert not cleanup['stop_poll_thread_started'] and cleanup['stop_poll_error_kind']=='identity_mismatch'
    assert not cleanup['clean']


def extended_metrics():
    value=metrics();value['last_request'].update(stop_checks_at_first_read=1,stop_checks_at_last_read=3,
        stop_cost_at_first_read_s=.00001,stop_cost_at_last_read_s=.00005)
    return value


def test_old_cleanup_and_partial_new_samples_are_honest_and_detached():
    record,hello=proof();assert validate_cleanup(record,'run','sha',hello)==record
    record.update(stop_poll_thread_started=True,stop_poll_thread_stopped=True,
        stop_poll_error_type=None,stop_poll_error_kind=None,io_metrics=extended_metrics())
    checked=validate_cleanup(record,'run','sha',hello);checked['io_metrics']['last_request']['stop_checks_at_first_read']=99
    assert record['io_metrics']['last_request']['stop_checks_at_first_read']==1
    record['io_metrics']['last_request'].update(queued_wall=None,peer_write_completed_wall=None,response_received_wall=None)
    assert validate_cleanup(record,'run','sha',hello)==record
    empty=extended_metrics();empty.update(input_chunks=0,input_bytes=0,complete_requests=0)
    empty['last_request']={key:None for key in empty['last_request']}
    assert validate_io_metrics(empty)==empty


@pytest.mark.parametrize('change',[
    lambda r:r.pop('stop_poll_thread_started'),lambda r:r.pop('stop_poll_error_kind'),
    lambda r:r.update(stop_poll_thread_started=1),lambda r:r.update(stop_poll_thread_started=False),lambda r:r.update(stop_poll_thread_stopped=False),
    lambda r:r.update(stop_poll_error_kind='unexpected text'),lambda r:r.update(stop_poll_error_type=True),
    lambda r:r.update(stop_poll_error_type='ValueError',stop_poll_error_kind=None),
    lambda r:r.update(stop_poll_error_kind='identity_mismatch'),lambda r:r.update(extra_thread='unknown')])
def test_half_or_bad_thread_group_cannot_be_accepted(change):
    record,hello=proof();record.update(stop_poll_thread_started=True,stop_poll_thread_stopped=True,
        stop_poll_error_type=None,stop_poll_error_kind=None)
    change(record)
    with pytest.raises(ContractError):validate_cleanup(record,'run','sha',hello)


@pytest.mark.parametrize('change',[
    lambda r:r.pop('stop_cost_at_last_read_s'),lambda r:r.update(stop_checks_at_first_read=True),
    lambda r:r.update(stop_checks_at_last_read=6),lambda r:r.update(stop_cost_at_last_read_s=float('nan')),
    lambda r:r.update(stop_cost_at_last_read_s=.1),lambda r:r.update(stop_cost_at_last_read_s=0),
    lambda r:r.update(stop_checks_at_last_read=0),lambda r:r.update(stop_checks_at_first_read=None),
    lambda r:r.update(first_read_wall=None)])
def test_optional_stop_samples_reject_unknown_partial_nonfinite_and_regressed(change):
    value=extended_metrics();change(value['last_request'])
    with pytest.raises(ContractError):validate_io_metrics(value)
