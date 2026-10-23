"""Bounded nonblocking receipt fairness and exact partial-byte accounting."""
import pytest
from rm_match.integrations import wsl_aim_async_worker as worker


def progress(received=0):
    return dict(received=received,read_calls=0,batches=0,would_blocks=0,bytes_read=0)


def reader(monkeypatch,parts):
    calls=[];parts=iter(parts)
    def read(fd,payload,received):
        calls.append((fd,received))
        part=next(parts)
        if isinstance(part,BaseException):raise part
        if len(part)<=len(payload)-received:payload[received:received+len(part)]=part
        return len(part)
    monkeypatch.setattr(worker,'_read_payload_into',read)
    return calls


def test_multiple_fragments_complete_same_owned_buffer_without_outer_poll(monkeypatch):
    payload=bytearray(8);payload[:2]=b'ab';p=progress(2)
    calls=reader(monkeypatch,[b'cd',b'ef',b'gh'])
    assert worker._drain_payload(0,payload,p,deadline=1.,clock=lambda:0.)==8
    assert payload==b'abcdefgh' and len(calls)==3 and p['bytes_read']==6 and p['batches']==1


@pytest.mark.parametrize('parts,received',[( [BlockingIOError()],0),([b'ab',BlockingIOError()],2)])
def test_would_block_yields_without_spinning_or_losing_partial_bytes(monkeypatch,parts,received):
    p=progress();calls=reader(monkeypatch,parts)
    assert worker._drain_payload(0,bytearray(8),p,deadline=1.,clock=lambda:0.)==received
    assert p['would_blocks']==1 and len(calls)==len(parts) and p['bytes_read']==received


def test_continuously_readable_pipe_yields_after_maximum_read_count(monkeypatch):
    p=progress();calls=reader(monkeypatch,[b'a']*100)
    assert worker._drain_payload(0,bytearray(100),p,deadline=1.,clock=lambda:0.)==16
    assert len(calls)==16


def test_continuously_readable_pipe_yields_at_original_one_ms_fairness_bound(monkeypatch):
    p=progress();calls=reader(monkeypatch,[b'a']*100)
    times=iter([0.,0.,.0005,.001])
    assert worker._drain_payload(0,bytearray(100),p,deadline=1.,clock=lambda:next(times))==2
    assert len(calls)==2


@pytest.mark.parametrize('clock',[lambda:1.,lambda:1.1])
def test_original_watchdog_expiry_does_not_read_any_further_byte(monkeypatch,clock):
    p=progress();calls=reader(monkeypatch,[b'a'])
    with pytest.raises(TimeoutError):worker._drain_payload(0,bytearray(8),p,deadline=1.,clock=clock)
    assert not calls


def test_watchdog_crossing_inside_batch_preserves_exact_received_count(monkeypatch):
    p=progress();calls=reader(monkeypatch,[b'ab',b'cd']);times=iter([.999,.999,1.])
    with pytest.raises(TimeoutError):worker._drain_payload(0,bytearray(8),p,deadline=1.,clock=lambda:next(times))
    assert p['received']==p['bytes_read']==2 and len(calls)==1


@pytest.mark.parametrize('end,error',[(b'',EOFError),(b'1234567',ValueError),(OSError('io failure'),OSError)])
def test_eof_overflow_and_io_fault_keep_progress_and_are_never_success(monkeypatch,end,error):
    p=progress();reader(monkeypatch,[b'ab',end])
    with pytest.raises(error):worker._drain_payload(0,bytearray(8),p,deadline=1.,clock=lambda:0.)
    assert p['received']==p['bytes_read']==2 and p['read_calls']==2


def test_input_diagnostic_write_failure_does_not_skip_owned_child_cleanup(monkeypatch,tmp_path):
    import json
    from tests.test_wsl_aim_async import supervise_fixture
    original=worker._record
    def record(out,name,data):
        if name=='INPUT_IO.json':raise OSError('diagnostic write failed')
        return original(out,name,data)
    monkeypatch.setattr(worker,'_record',record)
    out,_,_,cleaned,_=supervise_fixture(monkeypatch,tmp_path,[b''])
    assert cleaned==[True]
    cleanup=json.loads((out/'CLEANUP.json').read_bytes())
    assert cleanup['reaped'] and cleanup['group_empty'] and cleanup['tmpfs_removed']
    assert cleanup['clean'] is False and 'input_io_evidence:OSError' in cleanup['errors']
