"""Pure async protocol/lifecycle fixtures. No WSL, native child, NN or camera."""
import copy
import errno
import hashlib
import json
from pathlib import Path
import queue
import threading
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from rm_match.integrations import wsl_aim_async_worker as worker
from rm_match.integrations.wsl_aim_async import WslAsyncAimProcess,NativeAimPending


def header(frame=7,seq=1,request=1):
    raw=b'\x1c'*worker.MAX_IMAGE
    source=dict(robot_id='red_sentry',episode=9,binding_epoch=1,observed_seq=seq,sim_time=.422,wall_deadline=100.08)
    image=dict(encoding='bgr8',width=1440,height=1080,stride_bytes=4320,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),path='actual_binding/sensor_input.bgr')
    frame=dict(schema='rmcs-mujoco-actor-frame-v1',episode=9,frame_id=frame,exposure_timestamp_ns=410000000,
        capture_time_s=.410,own_referee_id=7,own_team='red',image=image,camera={},own={})
    h=dict(schema=worker.SCHEMA,event='control',id=request,image_bytes=len(raw),timeout_s=.07,source_context=source,
        packet=dict(control_time_ns=422000000,time_s=.422,frame=frame,operator_fov={}))
    return h,raw


def response(calls=1):
    return dict(status='ok',runner_identity='rmcs-sim-operator-fov-v1',clock_time_ns=422000000,
        direction_frame='world',tracking=True,detector_executed=True,frame_accepted=True,inference_calls=calls,
        direction=[1.,0.,0.],robot_center=[4.,0.,0.])


def actor(tmp_path):
    a=object.__new__(WslAsyncAimProcess)
    a._async_lock=threading.RLock();a._async_wake=threading.Event();a._inflight=None;a._fault=None
    a._last_frame=-1;a._last_seq=-1;a._generation=None;a._trace_event=None
    a._stop=threading.Event();a._broken=threading.Event();a._transaction=threading.Lock()
    a._incoming=queue.Queue(maxsize=2);a._outgoing=queue.Queue(maxsize=1)
    a.ready={};a.process=object();a.timeout=.08;a._serial=0;a.fov={};a.out=tmp_path
    a.evidence_out=None;a.diagnostics=[];a.cleanup=None;a._threads=[]
    return a


def slot(a,h,*,abandoned=False,started=True):
    a._inflight=dict(header=h,deadline=100.08,host_started=100.,started=started,abandoned=abandoned,terminal=None,
        transport_write_attempted=False,transport_write_in_progress=False,transport_bytes_written=0,
        transport_expected_bytes=worker.MAX_IMAGE+1024)


def reply(h,event='result'):
    frame=h['packet']['frame']
    m=dict(schema=worker.SCHEMA,transport=worker.TRANSPORT,event=event,id=h['id'],source_context=copy.deepcopy(h['source_context']),
        frame_id=frame['frame_id'],exposure_timestamp_ns=frame['exposure_timestamp_ns'],control_time_ns=h['packet']['control_time_ns'],
        image_sha256=frame['image']['sha256'],bgr_bytes=worker.MAX_IMAGE,clock_domain='linux_local_diagnostic_only')
    if event=='result':m.update(response=response(),native_elapsed_linux_s=.045)
    if event=='native_started':m.update(native_stdin_complete=True,native_stdin_bytes_written=1729,native_stdin_expected_bytes=1729)
    return m


def packet(a,h,raw):
    frame=copy.deepcopy(h['packet']['frame']);frame['image']['path']=str(a.out/'sensor_input.bgr')
    return dict(episode=9,frame=frame,control_time_ns=422000000,host_deadline=h['source_context']['wall_deadline'],image_bytes=raw)


def test_one_original_compute_and_late_resource_completion_do_not_retag_source():
    h,_=header();model=worker.NativeComputeSlot();model.begin(h,10.)
    with pytest.raises(ValueError,match='concurrent'):model.begin(header(8,2,2)[0],10.01)
    result=model.complete(response(),10.13)
    assert result['native_elapsed_linux_s']==pytest.approx(.13) and result['id']==1
    assert result['source_context']==h['source_context'] and result['frame_id']==7
    assert result['exposure_timestamp_ns']==410000000 and result['control_time_ns']==422000000
    assert model.current is None
    # This >80ms completion is not authority success; only the host can judge
    # its own original deadline. Next real image must be genuinely newer.
    model.begin(header(8,2,2)[0],11.);assert model.complete(response(2),11.03)['frame_id']==8


def test_watchdog_and_wrong_clock_or_inference_count_are_real_faults():
    h,_=header();model=worker.NativeComputeSlot();model.begin(h,10.)
    with pytest.raises(TimeoutError,match='watchdog'):model.complete(response(),11.)
    assert model.current is not None
    r=response();r['clock_time_ns']+=1
    with pytest.raises(ValueError):model.complete(r,10.03)
    with pytest.raises(ValueError,match='inference_count'):model.complete(response(2),10.03)


def lost_target_response(calls=1):
    # Original main.cpp num/vec emits three JSON nulls for kNaN points.
    return dict(response(calls),tracking=False,should_shoot=False,
                direction=[None,None,None],robot_center=[None,None,None])


def test_original_lost_target_is_a_completed_inference_then_next_source_recovers():
    h,_=header();model=worker.NativeComputeSlot();model.begin(h,10.)
    value=lost_target_response();result=model.complete(value,10.04)
    assert result['response']==value and result['source_context']==h['source_context']
    assert model.current is None and model.inferences==1
    model.begin(header(8,2,2)[0],11.)
    recovered=model.complete(response(2),11.03)
    assert recovered['frame_id']==8 and recovered['response']['tracking'] is True


@pytest.mark.parametrize('tracking,vector',[
    (True,[None,None,None]),(False,[None,0.,None]),(False,[False,0.,0.]),
    (False,[float('inf'),0.,0.]),(False,None),(False,[]),
])
@pytest.mark.parametrize('field',['direction','robot_center'])
def test_no_target_contract_does_not_admit_active_nulls_or_malformed_points(tracking,vector,field):
    h,_=header();value=lost_target_response();value['tracking']=tracking;value[field]=vector
    with pytest.raises(ValueError):worker.checked_response(value,h)


@pytest.mark.parametrize('late',[False,True])
def test_host_lost_target_keeps_original_context_and_late_disposition(tmp_path,late):
    a=actor(tmp_path);h,_=header();slot(a,h,abandoned=late)
    message=reply(h);message['response']=lost_target_response()
    with patch('rm_match.integrations.wsl_aim_async.time.perf_counter',return_value=100.13 if late else 100.04):
        a._handle_message(message)
    assert not a._broken.is_set() and not a._stop.is_set()
    row=a.diagnostics[-1]
    assert row['source_context']==h['source_context'] and row['response']==lost_target_response()
    assert row['event']==('async_late_discard' if late else 'async_native_stdout')
    if late:assert a._inflight is None and a._incoming.empty()
    else:assert a._inflight['terminal']==dict(kind='result',response=lost_target_response())


@pytest.mark.parametrize('field,value',[('binding_epoch',True),('observed_seq',1.),('wall_deadline',float('inf'))])
def test_six_original_context_types_cannot_be_aliased(field,value):
    h,_=header();h['source_context'][field]=value
    with pytest.raises(ValueError):worker.checked_header(h,{})


def test_original_capture_clock_geometry_and_generation_replay_rejected():
    h,_=header();worker.checked_header(h,{})
    for change in ('future','bool_width','scope','extra'):
        m=copy.deepcopy(h)
        if change=='future':m['packet']['frame']['exposure_timestamp_ns']=430000000
        if change=='bool_width':m['packet']['frame']['image']['width']=True
        if change=='scope':m['source_context']['episode']=10
        if change=='extra':m['packet']['truth']=[1,2]
        with pytest.raises(ValueError):worker.checked_header(m,{})
    model=worker.NativeComputeSlot();model.begin(h,10.);model.complete(response(),10.03)
    with pytest.raises(ValueError,match='replayed'):model.begin(h,10.04)
    foreign=header(8,2,2)[0];foreign['source_context']['binding_epoch']=2
    with pytest.raises(ValueError,match='generation'):model.begin(foreign,10.05)


@pytest.mark.parametrize('raw',[b'{"id":1,"id":2}',b'{"x":NaN}',b'{"x":1e999}'])
def test_strict_json_rejects_duplicate_and_nonfinite(raw):
    with pytest.raises(ValueError):worker.parse_json(raw)


def test_cold_late_stdout_is_saved_and_never_new_frame_result(tmp_path):
    a=actor(tmp_path);h,_=header();slot(a,h,abandoned=True)
    with patch('rm_match.integrations.wsl_aim_async.time.perf_counter',return_value=100.13):a._handle_message(reply(h))
    assert not a.busy and not a._stop.is_set() and a._incoming.empty()
    e=a.diagnostics[-1];assert e['event']=='async_late_discard' and e['frame_id']==7
    assert e['response']==response() and e['source_context']==h['source_context']
    assert e['wall_deadline']==100.08 and e['control_time_ns']==422000000


def test_after_pending_but_before_deadline_is_distinct_unconsumed_not_accepted(tmp_path):
    a=actor(tmp_path);h,_=header();slot(a,h,abandoned=True)
    with patch('rm_match.integrations.wsl_aim_async.time.perf_counter',return_value=100.077):a._handle_message(reply(h))
    assert a.diagnostics[-1]['event']=='async_after_pending_discard' and not a.busy
    assert not any(e['event']=='async_result_accepted80' for e in a.diagnostics)


def test_late_reader_timer_race_keeps_pending_terminal_not_sticky_fault(tmp_path):
    a=actor(tmp_path);h,_=header();slot(a,h)
    with patch('rm_match.integrations.wsl_aim_async.time.perf_counter',return_value=100.081):a._handle_message(reply(h))
    assert a._inflight['terminal']==dict(kind='late_discard') and not a._broken.is_set()


@pytest.mark.parametrize('change',['id','epoch','frame','clock','bgr','unstarted','nonfinite'])
def test_original_inflight_pairing_or_bad_stdout_rejected(tmp_path,change):
    a=actor(tmp_path);h,_=header();slot(a,h,started=change!='unstarted');m=reply(h)
    if change=='id':m['id']=2
    if change=='epoch':m['source_context']['binding_epoch']=True
    if change=='frame':m['frame_id']=8
    if change=='clock':m['control_time_ns']+=1
    if change=='bgr':m['image_sha256']='0'*64
    if change=='nonfinite':m['response']['direction'][0]=float('inf')
    with pytest.raises(ValueError):a._handle_message(m)
    assert a._inflight is not None


def test_busy_is_immediate_typed_pending_for_current_context_without_new_image(tmp_path):
    a=actor(tmp_path);h,raw=header();slot(a,h);current=header(8,2,2)[0]['source_context']
    with patch('rm_match.integrations.wsl_aim_async.time.perf_counter',return_value=100.01):
        result=a.control(dict(host_deadline=current['wall_deadline']),source_context=current)
    assert type(result) is NativeAimPending and result.reason=='native_compute_inflight'
    assert result.source_context==current and result.submitted is False and a._outgoing.empty()
    detached=result.source_context;detached['observed_seq']=100
    assert result.source_context['observed_seq']==2 and not a._stop.is_set()


@pytest.mark.parametrize('actual_fault',[False,True])
def test_owner_stop_during_control_is_distinct_from_an_existing_real_fault(tmp_path,actual_fault):
    a=actor(tmp_path);h,raw=header();source=h['source_context']
    def stopped(_):
        if actual_fault:a._fault='OSError:fixture genuine failure'
        a._stop.set()
    a._async_wake.wait=stopped
    with patch('rm_match.integrations.wsl_aim_async.time.perf_counter',return_value=100.01):
        if actual_fault:
            with pytest.raises(RuntimeError,match='genuine failure'):
                a.control(packet(a,h,raw),source_context=source)
            assert a._fault=='OSError:fixture genuine failure' and a._broken.is_set()
        else:
            value=a.control(packet(a,h,raw),source_context=source)
            assert type(value) is NativeAimPending and value.reason=='owned_stop_requested'
            assert value.source_context==source and value.request_id==1 and not value.submitted
            assert a._fault is None and not a._broken.is_set()
            assert a._inflight is not None and a._inflight['abandoned']
            assert not any(r['event']=='async_native_fault' for r in a.diagnostics)
            assert not any(r['event']=='async_result_accepted80' for r in a.diagnostics)


def test_original_expired_authority_returns_pending_without_any_new_native_compute(tmp_path):
    a=actor(tmp_path);h,_=header()
    with patch('rm_match.integrations.wsl_aim_async.time.perf_counter',return_value=101.):
        result=a.control(dict(host_deadline=100.08),source_context=h['source_context'])
    assert type(result) is NativeAimPending and not result.submitted and not a.busy and not a._stop.is_set()


def test_control_accepts_only_timely_real_reply_after_complete_native_input(tmp_path):
    a=actor(tmp_path);h,raw=header();p=packet(a,h,raw)
    def complete(timeout):
        sent=json.loads(a._outgoing.get_nowait()[0]);a._handle_message(reply(sent,'native_started'));a._handle_message(reply(sent))
    a._async_wake.wait=complete
    with patch('rm_match.integrations.wsl_aim_async.time.perf_counter',return_value=100.01):
        result=a.control(p,source_context=h['source_context'])
    assert result['episode']==9 and result['should_control'] is True and not a.busy
    assert [e['event'] for e in a.diagnostics]==['async_transport_request','async_native_started','async_native_stdout','async_result_accepted80']


def test_timeout_pending_preserves_model_until_original_late_result_then_next_fresh_frame(tmp_path):
    a=actor(tmp_path);h,raw=header();p=packet(a,h,raw);clock=[100.]
    def pending(timeout):clock[0]=100.076
    a._async_wake.wait=pending
    with patch('rm_match.integrations.wsl_aim_async.time.perf_counter',side_effect=lambda:clock[0]):
        result=a.control(p,source_context=h['source_context'])
    assert type(result) is NativeAimPending and a.busy and not a._stop.is_set()
    sent=json.loads(a._outgoing.get_nowait()[0])
    with patch('rm_match.integrations.wsl_aim_async.time.perf_counter',return_value=100.13):
        a._handle_message(reply(sent,'native_started'));a._handle_message(reply(sent))
    assert not a.busy and a.diagnostics[-1]['event']=='async_late_discard'
    assert not any(e['event']=='async_result_accepted80' for e in a.diagnostics)


@pytest.mark.parametrize('value',[None,True,-.1,1.,float('inf')])
def test_linux_elapsed_diagnostic_is_bounded_and_not_a_foreign_authority_clock(tmp_path,value):
    a=actor(tmp_path);h,_=header();slot(a,h);m=reply(h);m['native_elapsed_linux_s']=value
    with pytest.raises(ValueError,match='elapsed'):a._handle_message(m)
    m=reply(h);m['clock_domain']='host_perf_counter'
    with pytest.raises(ValueError,match='clock_domain'):a._handle_message(m)


def test_native_optional_time_is_original_not_reticked():
    h,_=header();r=response();r['time_s']=.423
    with pytest.raises(ValueError,match='response_time'):worker.checked_response(r,h)


def supervise_fixture(monkeypatch,tmp_path,chunks,*,cleanup_clean=True,late_ready=False,stop_before_spawn=False,stop_after_reads=None):
    """Mock OS boundaries only: no subprocess/ROS/WSL/NN is created."""
    clock=[0.];spawn=[];cleaned=[];closed=[]
    class Stream:
        def __init__(self,fd):self.fd=fd
        def fileno(self):return self.fd
        def close(self):closed.append(self.fd)
    child=SimpleNamespace(pid=999,stdin=Stream(10),stdout=Stream(11),poll=lambda:None)
    class Owner:
        def attach(self,c):return dict(pid=c.pid,pgid=c.pid,run_id='a'*32,supervisor_pid=998,boot_id='test',leader_start_ticks=1)
        def cleanup(self):
            cleaned.append(True)
            return dict(clean=cleanup_clean,reaped=cleanup_clean,group_empty=cleanup_clean,remaining_members=[] if cleanup_clean else [999],errors=[] if cleanup_clean else ['fixture_remaining'])
    original_tmp=tempfile.TemporaryDirectory
    monkeypatch.setattr(worker.tempfile,'TemporaryDirectory',lambda **kw:original_tmp(prefix=kw['prefix'],dir=tmp_path))
    monkeypatch.setattr(worker,'LinuxOwnedProcessGroup',Owner)
    monkeypatch.setattr(worker.signal,'signal',lambda *args:None)
    monkeypatch.setattr(worker.os,'set_blocking',lambda *args:None)
    monkeypatch.setattr(worker.os,'chmod',lambda *args:None)
    monkeypatch.setattr(worker.time,'monotonic',lambda:clock[0])
    def popen(*args,**kwargs):spawn.append(kwargs);return child
    monkeypatch.setattr(worker.subprocess,'Popen',popen)
    def ready(pid):
        if late_ready:clock[0]=16.
        return {'syscall':'read','fd':0}
    monkeypatch.setattr(worker,'_stdin_wait',ready)
    reads=iter(chunks);read_count=[0]
    def read(fd,size):
        data=next(reads);read_count[0]+=1
        if read_count[0]==stop_after_reads:
            (out/'STOP').write_bytes(b'cancel\n');clock[0]+=.006
        return data
    monkeypatch.setattr(worker.os,'read',read)
    def payload_read(fd,payload,received):
        data=read(fd,len(payload)-received);payload[received:received+len(data)]=data
        return len(data)
    monkeypatch.setattr(worker,'_read_payload_into',payload_read)
    monkeypatch.setattr(worker.os,'write',lambda fd,data:len(data))
    def select_fds(*args):clock[0]+=.001;return [0],[1] if args[1] else [],[]
    monkeypatch.setattr(worker.select,'select',select_fds)
    out=tmp_path/'out';out.mkdir()
    if stop_before_spawn:(out/'STOP').write_text('stop')
    code=worker.supervise(['harmless-mocked-child'],out,{},spec_sha='b'*64)
    return out,code,spawn,cleaned,closed


@pytest.mark.parametrize('partial',[b'{"schema":',b'{}\npartial'])
def test_partial_header_or_invalid_header_eof_is_fault_and_child_cleanup_proved(monkeypatch,tmp_path,partial):
    out,code,spawn,cleaned,closed=supervise_fixture(monkeypatch,tmp_path,[partial,b''])
    assert code==2 and len(spawn)==1 and cleaned==[True] and closed==[10,11]
    error=json.loads((out/'SUPERVISOR_ERROR.json').read_text())
    assert error['event']=='error' and error['inflight'] is None
    cleanup=json.loads((out/'CLEANUP.json').read_text())
    assert cleanup['clean'] is True and cleanup['tmpfs_removed'] is True
    # Clean resource teardown does not turn this protocol fault into success.
    assert (out/'PRE_NATIVE_EXIT.json').exists() is False


def test_empty_eof_is_normal_with_zero_inference_and_owned_cleanup(monkeypatch,tmp_path):
    out,code,spawn,cleaned,closed=supervise_fixture(monkeypatch,tmp_path,[b''])
    assert code==0 and cleaned==[True] and len(spawn)==1
    start=json.loads((out/'STARTUP.json').read_text());assert start['inference_calls']==0
    assert json.loads((out/'CLEANUP.json').read_text())['reason']=='host_eof'
    assert not (out/'SUPERVISOR_ERROR.json').exists()


def test_read0_after_startup_deadline_cannot_mint_ready(monkeypatch,tmp_path):
    out,code,spawn,cleaned,closed=supervise_fixture(monkeypatch,tmp_path,[],late_ready=True)
    assert code==2 and cleaned==[True] and len(spawn)==1
    assert not (out/'STARTUP.json').exists()
    assert json.loads((out/'SUPERVISOR_ERROR.json').read_text())['error_type']=='TimeoutError'


def test_stop_after_tmpfs_setup_before_spawn_has_no_native_child(monkeypatch,tmp_path):
    out,code,spawn,cleaned,closed=supervise_fixture(monkeypatch,tmp_path,[],stop_before_spawn=True)
    assert code==2 and spawn==[] and cleaned==[] and closed==[]
    assert not (out/'OWNED_CHILD.json').exists() and not (out/'CLEANUP.json').exists()
    assert not list(tmp_path.glob('polar-aim-async-*'))


def test_cleanup_failure_cannot_be_reported_clean_even_on_normal_eof(monkeypatch,tmp_path):
    out,code,spawn,cleaned,closed=supervise_fixture(monkeypatch,tmp_path,[b''],cleanup_clean=False)
    assert json.loads((out/'CLEANUP.json').read_text())['clean'] is False


def test_exception_after_supervisor_entry_cannot_claim_native_not_spawned(monkeypatch,tmp_path):
    monkeypatch.setattr(worker.signal,'signal',lambda *args:None)
    monkeypatch.setattr(worker,'_stat',lambda pid:{'start_ticks':1})
    original_read=Path.read_text
    monkeypatch.setattr(Path,'read_text',lambda self,*a,**k:'test-boot' if self.as_posix().endswith('/proc/sys/kernel/random/boot_id') else original_read(self,*a,**k))
    monkeypatch.setattr(worker,'validate_linux_spec',lambda *a:({'autoaim_config':'config','model_share':'models','binary':'ELF','executor_yaml':'yaml'},'b'*64))
    def fail(*a,**k):raise OSError('fixture final cleanup evidence failure after entry')
    monkeypatch.setattr(worker,'supervise',fail)
    out=tmp_path/'new';assert worker.prepare_and_supervise('spec','b'*64,out,{})==2
    assert not (out/'PRE_NATIVE_EXIT.json').exists()
    result=json.loads((out/'SPAWN_OR_CLEANUP_UNPROVED.json').read_text())
    assert result['clean'] is False and result['native_spawn_attempted']=='unknown_after_supervisor_entry'


def test_writer_preserves_exact_header_plus_actual_bytes_across_short_writes(tmp_path):
    a=actor(tmp_path);h,raw=header();slot(a,h,started=False);sent=b'{"synthetic_protocol_fixture":true}\n'
    a._outgoing.put((sent,raw,100.08,1));collected=bytearray()
    class Stream:
        def write(self,view):
            n=min(65536,len(view));collected.extend(view[:n])
            if len(collected)==len(sent)+len(raw):a._stop.set()
            return n
    with patch('rm_match.integrations.wsl_aim_async.time.perf_counter',return_value=100.01):
        a._write(SimpleNamespace(stdin=Stream()))
    assert bytes(collected)==sent+raw and not a._broken.is_set()
    assert a._inflight['transport_bytes_written']==len(sent)+len(raw)
    assert a._inflight['transport_write_attempted'] is True and a._inflight['transport_write_in_progress'] is False


@pytest.mark.parametrize('count',[True,-1,worker.MAX_IMAGE+worker.MAX_LINE+1])
def test_invalid_writer_return_is_fault_not_full_input_proof(tmp_path,count):
    a=actor(tmp_path);h,raw=header();slot(a,h,started=False)
    a._outgoing.put((b'{}\n',raw,100.08,1))
    with patch('rm_match.integrations.wsl_aim_async.time.perf_counter',return_value=100.01):
        a._write(SimpleNamespace(stdin=SimpleNamespace(write=lambda view:count)))
    assert a._broken.is_set() and a._stop.is_set()
    assert a.diagnostics[-1]['event']=='async_native_fault' and a.diagnostics[-1]['frame_id']==7


def test_writer_expired_before_first_byte_is_pending_without_native_or_model_stop(tmp_path):
    a=actor(tmp_path);h,raw=header();slot(a,h,started=False,abandoned=True)
    a._outgoing.put((b'{}\n',raw,100.08,1));writes=[]
    original=a._outgoing.get
    def once(*args,**kwargs):
        if a._outgoing.empty():a._stop.set();raise queue.Empty
        return original(*args,**kwargs)
    a._outgoing.get=once
    with patch('rm_match.integrations.wsl_aim_async.time.perf_counter',return_value=100.09):
        a._write(SimpleNamespace(stdin=SimpleNamespace(write=lambda data:writes.append(data))))
    assert not writes and not a._broken.is_set() and a._inflight is None
    assert a.diagnostics[-1]['event']=='async_discarded_before_write'


def closed_actor(tmp_path):
    a=actor(tmp_path);h,_=header();slot(a,h,started=False,abandoned=True);a._stop.set()
    identity=dict(run_id='a'*32,supervisor_pid=998,pid=999,pgid=999,boot_id='test-boot',leader_start_ticks=1,
        spec_sha256='b'*64,transport=worker.TRANSPORT)
    a.cleanup=dict(identity,reason='host_cancel',clean=True,reaped=True,group_empty=True,tmpfs_removed=True,
        remaining_members=[],errors=[])
    a.ready=dict(run_id=identity['run_id'],supervisor_pid=998,native_pid=999,spec_sha256='b'*64,transport=worker.TRANSPORT)
    a._threads=[SimpleNamespace(is_alive=lambda:False)]
    return a


def test_zero_write_cancellation_is_only_certified_after_real_writer_join_and_owned_cleanup(tmp_path):
    a=closed_actor(tmp_path)
    a._record('closed',clean=True,linux_child_reaped=True,native_not_spawned=False,errors=[])
    proof=a.diagnostics[0]
    assert proof['event']=='async_cancelled_before_write' and proof['transport_bytes_written']==0
    assert proof['source_context']==a._inflight['header']['source_context']
    assert proof['ownership']['run_id']=='a'*32 and proof['writer_joined'] is True
    assert a._inflight['terminal']=={'kind':'cancelled_before_write'}
    # A second resource close must not invent another terminal.
    a._record('closed',clean=True)
    assert sum(r['event']=='async_cancelled_before_write' for r in a.diagnostics)==1


@pytest.mark.parametrize('change',['attempted','blocked','partial','writer_alive','no_threads','bad_cleanup','foreign_ready','already_started','fault','broken'])
def test_zero_count_alone_never_proves_cancelled_before_write(tmp_path,change):
    a=closed_actor(tmp_path)
    if change=='attempted':a._inflight['transport_write_attempted']=True
    elif change=='blocked':a._inflight['transport_write_in_progress']=True
    elif change=='partial':a._inflight['transport_bytes_written']=1
    elif change=='writer_alive':a._threads=[SimpleNamespace(is_alive=lambda:True)]
    elif change=='no_threads':a._threads=[]
    elif change=='bad_cleanup':a.cleanup['clean']=False
    elif change=='foreign_ready':a.ready['native_pid']=1000
    elif change=='fault':a._fault='ValueError:unrecognized supervisor message'
    elif change=='broken':a._broken.set()
    else:a._inflight['started']=True
    a._record('closed',clean=True)
    assert not any(r['event']=='async_cancelled_before_write' for r in a.diagnostics)


def test_write_exception_with_zero_returned_bytes_remains_uncertain(tmp_path):
    a=closed_actor(tmp_path);a._stop.clear();h,raw=header();a._outgoing.put((b'{}\n',raw,100.08,1))
    def failed(view):raise BrokenPipeError('actual write may have transferred bytes')
    with patch('rm_match.integrations.wsl_aim_async.time.perf_counter',return_value=100.01):
        a._write(SimpleNamespace(stdin=SimpleNamespace(write=failed)))
    assert a._inflight['transport_write_attempted'] is True and a._inflight['transport_write_in_progress'] is True
    assert a._inflight['transport_bytes_written']==0
    a._record('closed',clean=True)
    assert not any(r['event']=='async_cancelled_before_write' for r in a.diagnostics)


@pytest.mark.parametrize('full_payload',[False,True])
def test_validated_input_cancel_retains_actual_receive_phase_without_claiming_native_compute(monkeypatch,tmp_path,full_payload):
    h,raw=header();encoded=json.dumps(h).encode()+b'\n'
    chunks=[encoded+raw[:1024]]+([raw[1024:]] if full_payload else [])
    out,code,spawn,cleaned,_=supervise_fixture(monkeypatch,tmp_path,chunks,stop_after_reads=len(chunks))
    assert code in (None,0) and len(spawn)==1 and cleaned==[True]
    journal=json.loads((out/'NATIVE_EVENTS.json').read_text());rows=journal['events']
    admission=next(r for r in rows if r['event']=='input_header_received')
    cancel=next(r for r in rows if r['event']=='input_cancelled')
    assert admission['source_context']==h['source_context']==cancel['source_context']
    assert cancel['received_bgr_bytes']==(worker.MAX_IMAGE if full_payload else 1024)
    assert cancel['phase']==('validated_payload' if full_payload else 'receiving_payload')
    assert cancel['payload_sha256_verified'] is full_payload
    assert cancel['verified_image_sha256']==(h['packet']['frame']['image']['sha256'] if full_payload else None)
    assert cancel['native_compute_started'] is False and cancel['native_stdin_bytes_written']==0
    assert not any(r['event'] in ('native_started','native_cancelled','result') for r in rows)
    assert journal['inflight_at_close'] is None and journal['ownership']['run_id']=='a'*32


def test_unvalidated_header_stop_has_no_source_specific_terminal(monkeypatch,tmp_path):
    out,code,_,_,_=supervise_fixture(monkeypatch,tmp_path,[b'{"schema":'],stop_after_reads=1)
    journal=json.loads((out/'NATIVE_EVENTS.json').read_text())
    assert code in (None,0) and journal['input_at_close']['header_validated'] is False
    assert not any(r['event'] in ('input_cancelled','native_cancelled','input_header_received') for r in journal['events'])


@pytest.mark.parametrize('kind',['epipe','windows109','windows232'])
def test_owned_stop_pipe_closure_is_only_interruption_candidate_with_original_unknown_write_state(tmp_path,kind):
    a=closed_actor(tmp_path);a._stop.clear();h,raw=header();a._outgoing.put((b'{}\n',raw,100.08,1));writes=[]
    class Stream:
        def write(self,view):
            writes.append(len(view))
            if len(writes)==1:return 97
            a._stop.set()
            if kind=='epipe':raise BrokenPipeError(errno.EPIPE,'owned receiver closed')
            error=OSError('owned Windows pipe closed');error.winerror=int(kind.removeprefix('windows'));raise error
    with patch('rm_match.integrations.wsl_aim_async.time.perf_counter',return_value=100.01):
        a._write(SimpleNamespace(stdin=Stream()))
    assert not a._broken.is_set() and a._fault is None
    candidate=next(r for r in a.diagnostics if r['event']=='async_transport_write_interrupted')
    assert candidate['source_context']==h['source_context'] and candidate['request_id']==1
    assert candidate['owned_stop_requested'] is True and candidate['transport_bytes_written']==97
    assert a._inflight['transport_write_attempted'] is True and a._inflight['transport_write_in_progress'] is True
    assert a._inflight['terminal'] is None and a._inflight['started'] is False
    a._record('closed',clean=True)
    assert not any(r['event'] in ('async_native_fault','async_cancelled_before_write','async_native_started','async_native_stdout') for r in a.diagnostics)


@pytest.mark.parametrize('kind',['pre_stop_epipe','previous_fault','previous_broken','unknown_after_stop','protocol_after_stop'])
def test_stopped_writer_never_washes_out_unknown_protocol_or_preexisting_fault(tmp_path,kind):
    a=closed_actor(tmp_path);a._stop.clear();h,raw=header();a._outgoing.put((b'{}\n',raw,100.08,1))
    def failed(view):
        if kind!='pre_stop_epipe':a._stop.set()
        if kind=='previous_fault':a._set_fault(ValueError('real protocol fault before pipe close'))
        elif kind=='previous_broken':a._broken.set()
        elif kind=='unknown_after_stop':raise OSError(errno.EIO,'unknown write failure')
        elif kind=='protocol_after_stop':raise ValueError('invalid original write')
        raise BrokenPipeError(errno.EPIPE,'pipe closed')
    with patch('rm_match.integrations.wsl_aim_async.time.perf_counter',return_value=100.01):
        a._write(SimpleNamespace(stdin=SimpleNamespace(write=failed)))
    assert a._broken.is_set() and a._fault is not None
    if kind=='previous_fault':assert 'real protocol fault' in a._fault
    assert not any(r['event']=='async_transport_write_interrupted' for r in a.diagnostics)
    a._record('closed',clean=True)
    assert not any(r['event']=='async_cancelled_before_write' for r in a.diagnostics)
