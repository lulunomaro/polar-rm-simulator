"""Pure source/protocol examples. No ELF, NN, renderer, hardware or live claim."""
import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import signal
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from adapters.native.tongji import jsonl_wrapper as wrapper
from tools.prepare_tongji_aim_plugin import blob,head_bytes,calibration_config,CPP
from tools import prepare_tongji_aim_plugin as generator
from rm_match.platform_v2.test_contracts import sample
from rm_match.platform_v2.contracts import IDENTITY


def packet_fixture(tmp_path):
    o=sample(True);c=o['sensors']['camera'];i=c['intrinsics'];im=c['image']
    profile=dict(width=im['width'],height=im['height'],**{k:i[k] for k in ('fx','fy','cx','cy','distortion')})
    # Deliberately different capture/current joints: only capture drives Solver.
    c['own_qpos_at_capture'][3:]=[.25,.12];o['own']['qpos'][3:]=[.8,-.3]
    o['wall_deadline']=1000000000.5
    o,packet,raw=wrapper.public_packet(o,profile,tmp_path/'sensor.bgr')
    return o,profile,packet,raw


def result(packet,control=True):
    return dict(schema=wrapper.NATIVE_SCHEMA,op='compute',ok=True,
        **{k:packet[k] for k in ('frame_id','capture_ns','control_ns')},
        input_bgr_sha256=packet['image']['sha256'],detector_executed=True,detections=1,
        targets=1,tracker_state='tracking',control=control,would_fire=control,
        yaw_rad=.4 if control else None,pitch_rad=-.2 if control else None,
        clock_policy='original_source_ns_differences',reference_frame='stationary_capture_origin_inertial')


def test_exact_actual_channels_capture_own_and_foreign_clock_preserved(tmp_path):
    o,_,p,bgr=packet_fixture(tmp_path)
    rgb=base64.b64decode(o['sensors']['camera']['image']['data_base64'],validate=True)
    assert bgr[0::3]==rgb[2::3] and bgr[1::3]==rgb[1::3] and bgr[2::3]==rgb[0::3]
    assert p['image']['sha256']==hashlib.sha256(bgr).hexdigest()
    assert p['capture_ns']==p['control_ns']==1000000000
    assert p['gimbal_quaternion_wxyz']==wrapper.source_quaternion([0,0,0,.25,.12],[0,0,0])
    key,a=wrapper.result_for(o,p,result(p));assert key=='action'
    assert all(type(a[k]) is type(o[k]) and a[k]==o[k] for k in IDENTITY)
    assert a['command']['pitch_rad']==.2 and a['command']['yaw_rad']==pytest.approx(.4)
    assert a['command']['fire_permission'] is False and a['command']['confidence'] is None
    assert a['wall_deadline']==1000000000.5


def test_inertial_yaw_converted_to_base_link_without_team_names(tmp_path):
    o,_,p,_=packet_fixture(tmp_path);o['robot_id']='other_example_27';o['own']['odom_xyyaw'][2]=.3
    _,a=wrapper.result_for(o,p,result(p));assert a['command']['yaw_rad']==pytest.approx(.1)
    assert a['robot_id']=='other_example_27'


@pytest.mark.parametrize('key,value',[('frame_id',True),('capture_ns',1000000001),('control_ns',True),
    ('input_bgr_sha256','0'*64),('detector_executed',False),('detections',True),('targets',-1),
    ('clock_policy','linux_now'),('reference_frame','truth'),('yaw_rad',float('nan')),('pitch_rad',True),
    ('tracker_state','invented')])
def test_native_identity_type_clock_and_actual_pixel_mismatch_reject(tmp_path,key,value):
    o,_,p,_=packet_fixture(tmp_path);r=result(p);r[key]=value
    with pytest.raises(ValueError):wrapper.result_for(o,p,r)


def test_no_target_and_original_missed_detection_do_not_fabricate_action(tmp_path):
    o,_,p,_=packet_fixture(tmp_path);r=result(p,False);r.update(targets=0,detections=0,tracker_state='lost')
    key,s=wrapper.result_for(o,p,r);assert key=='status' and s['status']=='no_target'
    r=result(p);r['tracker_state']='temp_lost'
    key,s=wrapper.result_for(o,p,r);assert key=='status' and s['status']=='pending_result'


@pytest.mark.parametrize('change',[lambda o:o['own']['odom_vxyw'].__setitem__(0,.031),
    lambda o:o['sensors']['camera']['own_odom_velocity_at_capture'].__setitem__(2,.031),
    lambda o:o['sensors']['camera']['intrinsics'].__setitem__('fx',11.),
    lambda o:o['sensors']['camera']['extrinsics'].__setitem__('translation_m',[0.,0.,0.]),
    lambda o:o.__setitem__('sim_time',1.081)])
def test_capability_calibration_and_original_age_fail_closed(tmp_path,change):
    o,profile,_,_=packet_fixture(tmp_path);change(o)
    with pytest.raises(ValueError):wrapper.public_packet(o,profile,tmp_path/'sensor.bgr')


def test_text_normalization_never_applies_to_binary_weights():
    original=b'<model>\nweights\n';windows=original.replace(b'\n',b'\r\n')
    assert head_bytes(windows,blob(original),text=True)==(original,'crlf_to_original_git_lf')
    with pytest.raises(ValueError):head_bytes(windows,blob(original),text=False)
    raw=b'\x00\xff\r\n\x01';assert head_bytes(raw,blob(raw),text=False)[0]==raw


def test_original_algorithm_config_preserved_except_declared_calibration():
    original=dict(min_confidence=.8,min_detect_count=3,Q_yaw=[2,3],fire_thresh=.02,high_speed_delay_time=.03)
    camera=dict(width=1440,height=1080,fx=1700.,fy=1701.,cx=700.,cy=560.,distortion=[0.]*5)
    config,diff=calibration_config(original,model_dir=Path('/models'),enemy_color='blue',camera=camera)
    assert all(config[k]==v for k,v in original.items())
    assert config['device']=='CPU' and diff['t_camera2gimbal']['adapted']==[.24,0.,.06]
    assert all(not x.startswith('io/') for x in CPP)
    assert 'tasks/auto_aim/planner/tinympc/codegen.cpp' in CPP


@pytest.mark.parametrize('raw',[b'{"op":1,"op":2}',b'{"x":NaN}',b'{"x":1e999}'])
def test_json_duplicate_nonfinite_and_overflow_rejected(raw):
    with pytest.raises(ValueError):wrapper.strict_json(raw)


def test_compute_short_writes_are_exact_and_one_original_local_deadline():
    actor=object.__new__(wrapper.NativeProcess);actor.child=SimpleNamespace(stdin=SimpleNamespace(fileno=lambda:7))
    actor.receive=lambda deadline:deadline;sent=[]
    def write(fd,raw):
        assert fd==7;n=min(3,len(raw));sent.append(raw[:n]);return n
    with patch.object(wrapper.time,'perf_counter',return_value=10.),patch.object(wrapper.select,'select',return_value=([],[7],[])),patch.object(wrapper.os,'write',side_effect=write):
        assert actor.compute({'a':1})==10.08
    assert b''.join(sent)==b'{"a":1}\n'


def test_late_select_wake_cannot_write_native_input():
    actor=object.__new__(wrapper.NativeProcess);actor.child=SimpleNamespace(stdin=SimpleNamespace(fileno=lambda:7))
    with patch.object(wrapper.time,'perf_counter',side_effect=[10.,10.,10.081]),patch.object(wrapper.select,'select',return_value=([],[7],[])),patch.object(wrapper.os,'write') as write:
        with pytest.raises(TimeoutError):actor.compute({'a':1})
        write.assert_not_called()


def test_signal_handler_is_installed_before_model_startup_and_restored(tmp_path):
    original=signal.getsignal(signal.SIGTERM);seen=[]
    def factory(spec,directory):
        seen.append(signal.getsignal(signal.SIGTERM)!=original);raise SystemExit(0)
    tmp_factory=tempfile.TemporaryDirectory
    with patch.object(wrapper.tempfile,'TemporaryDirectory',side_effect=lambda **_:tmp_factory(dir=tmp_path)):
        with pytest.raises(SystemExit):wrapper.run({},native_factory=factory)
    assert seen==[True] and signal.getsignal(signal.SIGTERM)==original


def test_native_stdout_logging_only_and_original_target_overload_is_used():
    source=(Path(__file__).resolve().parents[1]/'adapters/native/tongji/runner.cpp').read_text()
    assert 'plan=planner_.plan(target,speed)' in source and 'planner_.plan(std::optional' not in source
    assert 'std::cout.rdbuf(std::cerr.rdbuf())' in source
    assert 'tracker_->track(armors,exposure)' in source and 'yolo_.detect(bgr' in source


def serve_fixture(tmp_path,rows,*,native_ready=None,fail_startup=False):
    original=tempfile.TemporaryDirectory;output=io.StringIO();closed=[];seen=[]
    evidence=tmp_path/'evidence';evidence.mkdir()
    o,profile,_,_=packet_fixture(tmp_path)
    class FakeNative:
        def __init__(self,spec,directory):
            if fail_startup:raise RuntimeError('synthetic_model_init_failure')
            self.directory=directory;self.compute_attempts=0
            self.ready=(dict(schema=wrapper.NATIVE_SCHEMA,op='ready',ok=True,inference_calls=0)
                if native_ready is None else native_ready)
        def archive(self,p,pixels):assert hashlib.sha256(pixels).hexdigest()==p['image']['sha256']
        def compute(self,p):
            self.compute_attempts+=1;seen.append(p);return result(p,False)
        def close(self):closed.append(True)
    stdin=SimpleNamespace(buffer=io.BytesIO(b''.join(json.dumps(r).encode()+b'\n' for r in rows)))
    with patch.object(wrapper.tempfile,'TemporaryDirectory',side_effect=lambda **_:original(dir=tmp_path)),\
         patch.object(wrapper.sys,'stdin',stdin),patch.object(wrapper.sys,'stdout',output):
        wrapper.run(dict(calibration=profile,enemy_color='blue',evidence_out=str(evidence)),native_factory=FakeNative)
    return [json.loads(r) for r in output.getvalue().splitlines()],seen,closed,evidence


def reset(o):
    return dict(schema=wrapper.SCHEMA,op='reset',context={k:o[k] for k in ('episode','robot_id','binding_epoch')},config={})


def act(o):return dict(schema=wrapper.SCHEMA,op='act',observation=o)
def prepare():return dict(schema=wrapper.SCHEMA,op='prepare',config={})


def test_jsonl_reset_actual_fake_result_identity_and_durable_record(tmp_path):
    o,_,_,_=packet_fixture(tmp_path)
    rows,seen,closed,evidence=serve_fixture(tmp_path,[reset(o),act(o)])
    assert rows[0]==dict(schema=wrapper.SCHEMA,op='reset',ok=True)
    assert rows[1]['status']['status']=='pending_result' and len(seen)==1 and closed==[True]
    records=[wrapper.strict_json(line) for line in (evidence/'NATIVE_REQUESTS.jsonl').read_text().splitlines()]
    record=records[0];assert [r['event'] for r in records]==['native_request','native_result']
    assert record['public_identity']['wall_deadline']==o['wall_deadline']
    assert record['packet']['capture_ns']==1000000000
    # This fixture is explicitly synthetic. It tests persistence and protocol,
    # not detection, native resource ownership or real-time acceptance.


def test_paused_public_episode_does_not_call_native_or_issue_action(tmp_path):
    o,_,_,_=packet_fixture(tmp_path);o['referee']['phase']='paused'
    rows,seen,closed,_=serve_fixture(tmp_path,[reset(o),act(o)])
    assert rows[1]['status']['status']=='pending_result' and not seen and closed==[True]


def test_replayed_public_sequence_is_rejected_and_native_is_closed(tmp_path):
    o,_,_,_=packet_fixture(tmp_path)
    with pytest.raises(ValueError,match='replayed_observation'):serve_fixture(tmp_path,[reset(o),act(o),act(o)])


def test_bound_file_hash_changed_and_lexical_escape_rejected(tmp_path):
    file=tmp_path/'source';file.write_bytes(b'original');sha=hashlib.sha256(b'original').hexdigest()
    assert wrapper.read_checked(file,sha,16)==b'original'
    file.write_bytes(b'changed')
    with pytest.raises(ValueError,match='local_asset_hash'):wrapper.read_checked(file,sha,16)
    with pytest.raises(ValueError,match='local_asset_path'):wrapper.read_checked(tmp_path/'x'/'..'/'source',sha,16)


def test_out_of_range_original_plan_is_rejected_without_clamp(tmp_path):
    o,_,p,_=packet_fixture(tmp_path);r=result(p);r['pitch_rad']=2.
    with pytest.raises(ValueError):wrapper.result_for(o,p,r)


def test_process_clean_cannot_hide_failed_pixel_archive_drain(tmp_path):
    actor=object.__new__(wrapper.NativeProcess)
    actor.closed=False;actor.owner=SimpleNamespace(cleanup=lambda:dict(clean=True,reaped=True))
    actor.child=None;actor.stderr=io.BytesIO();actor.evidence=tmp_path
    class FailedWriter:
        shutdown_status=dict(clean=False,worker_alive=True,submitted=1,written=0)
        def close(self,timeout):assert timeout==.15;raise RuntimeError('archive_unfinished')
    actor.writer=FailedWriter()
    with pytest.raises(RuntimeError,match='native_cleanup_incomplete'):actor.close()
    row=wrapper.strict_json((tmp_path/'NATIVE_CLEANUP.json').read_text())
    assert row['clean'] is False and row['process']['clean'] is True and row['evidence']['worker_alive'] is True
    assert actor.stderr.closed


def test_native_request_error_does_not_skip_owned_process_cleanup(tmp_path):
    actor=object.__new__(wrapper.NativeProcess);actor.closed=False;actor.child=None;actor.stderr=None
    actor.evidence=tmp_path;actor.writer=None
    actor.owner=SimpleNamespace(cleanup=lambda:dict(clean=False,reaped=False))
    with pytest.raises(RuntimeError,match='native_cleanup_incomplete'):actor.close()
    assert wrapper.strict_json((tmp_path/'NATIVE_CLEANUP.json').read_text())['clean'] is False


def test_prepare_is_resource_ack_without_image_context_compute_or_generation(tmp_path):
    rows,seen,closed,evidence=serve_fixture(tmp_path,[prepare()])
    assert rows==[dict(schema=wrapper.SCHEMA,op='prepare',ok=True)] and not seen and closed==[True]
    assert not (evidence/'NATIVE_REQUESTS.jsonl').exists()
    proof=wrapper.strict_json((evidence/'PUBLIC_PREPARE.json').read_text())
    assert proof['native_ready']['inference_calls']==0 and proof['compute_attempts']==0


def test_prepare_reuses_real_ready_before_later_unchanged_reset_and_act(tmp_path):
    o,_,_,_=packet_fixture(tmp_path)
    rows,seen,closed,_=serve_fixture(tmp_path,[prepare(),reset(o),act(o)])
    assert [r['op'] for r in rows]==['prepare','reset','act'] and len(seen)==1 and closed==[True]
    assert rows[1]==dict(schema=wrapper.SCHEMA,op='reset',ok=True)
    # No additional setup time or new clock field is granted by reset ACK.
    assert set(rows[1])=={'schema','op','ok'}


@pytest.mark.parametrize('rows',[lambda o:[prepare(),prepare()],lambda o:[reset(o),prepare()],
    lambda o:[prepare(),act(o)],lambda o:[dict(prepare(),config={'warm':True})],
    lambda o:[dict(prepare(),observation=o)],lambda o:[dict(prepare(),config=[])],
    lambda o:[dict(prepare(),context={'episode':1})]])
def test_prepare_once_order_and_payload_contract_rejected(tmp_path,rows):
    o,_,_,_=packet_fixture(tmp_path)
    with pytest.raises(ValueError):serve_fixture(tmp_path,rows(o))


@pytest.mark.parametrize('ready',[{},dict(schema=wrapper.NATIVE_SCHEMA,op='ready',ok=True,inference_calls=False),
    dict(schema=wrapper.NATIVE_SCHEMA,op='ready',ok=True,inference_calls=1),
    dict(schema=wrapper.NATIVE_SCHEMA,op='compute',ok=True,inference_calls=0),
    dict(schema=wrapper.NATIVE_SCHEMA,op='ready',ok=1,inference_calls=0)])
def test_prepare_cannot_ack_unverified_or_warmed_native_ready(tmp_path,ready):
    with pytest.raises(ValueError,match='native_zero_tick_ready'):serve_fixture(tmp_path,[prepare()],native_ready=ready)


def test_model_initialization_failure_is_not_prepare_success(tmp_path):
    with pytest.raises(RuntimeError,match='synthetic_model_init_failure'):
        serve_fixture(tmp_path,[prepare()],fail_startup=True)


def test_fmt_compatibility_is_only_numeric_armor_name_and_two_original_translation_units():
    root=Path(__file__).resolve().parents[1]/'adapters/native/tongji'
    header=(root/'fmt_armor_name_compat.hpp').read_text()
    assert 'fmt::formatter<auto_aim::ArmorName> : fmt::formatter<int>' in header
    assert 'static_cast<int>(value)' in header and 'ARMOR_NAMES' not in header
    assert 'ArmorType>' not in header and 'Color>' not in header
    cmake=(root/'CMakeLists.txt').read_text()
    patch=cmake.split('set_source_files_properties(',1)[1].split('target_link_libraries',1)[0]
    assert '${POLAR_UPSTREAM_DIR}/tasks/auto_aim/detector.cpp' in patch
    assert '${POLAR_UPSTREAM_DIR}/tasks/auto_aim/yolos/yolov5.cpp' in patch
    assert '-include;${CMAKE_CURRENT_SOURCE_DIR}/fmt_armor_name_compat.hpp' in patch


def test_prepare_copies_and_hash_binds_new_fmt_header_without_modifying_source(tmp_path):
    """Synthetic Git/model bytes; actual file-copy and tamper gate, no compiler."""
    source=tmp_path/'source';models=tmp_path/'models';source.mkdir();models.mkdir();out=tmp_path/'prepared'
    originals={'tasks/auto_aim/armor.cpp':b'// synthetic nonalgorithm fixture\n',
        'LICENSE':b'synthetic license\n','configs/standard3.yaml':b'min_confidence: 0.8\n'}
    model_blobs={name:blob(name.encode()+b'\0') for name in generator.MODEL_BLOBS}
    for rel,raw in originals.items():
        path=source/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    for name in model_blobs:(models/name).write_bytes(name.encode()+b'\0')
    rows={**originals,**{'assets/'+name:name.encode()+b'\0' for name in model_blobs}}
    tree='\n'.join('100644 blob '+blob(raw)+'\t'+rel for rel,raw in rows.items())
    def fake_git(root,*args):
        assert root==source
        return generator.HEAD if args==('rev-parse','HEAD') else tree
    camera=dict(width=1440,height=1080,fx=1700.,fy=1701.,cx=700.,cy=560.,distortion=[0.]*5)
    before={rel:hashlib.sha256(raw).hexdigest() for rel,raw in originals.items()}
    # Isolate source copying from the optional preparation dependency. Actual
    # upstream YAML parsing remains required in production (no fallback).
    yaml_fixture=SimpleNamespace(safe_load=lambda raw:dict(min_confidence=.8))
    with patch.object(generator,'git',side_effect=fake_git),patch.object(generator,'CPP',('tasks/auto_aim/armor.cpp',)),\
         patch.object(generator,'MODEL_BLOBS',model_blobs),patch.dict(wrapper.sys.modules,{'yaml':yaml_fixture}):
        identity=generator.prepare(source,models,out,camera=camera,enemy_color='blue')
    header=out/'fmt_armor_name_compat.hpp';expected=hashlib.sha256(header.read_bytes()).hexdigest()
    assert identity['adapter_sources'][header.name]==expected
    assert identity['build_boundary_compatibility']['header_sha256']==expected
    assert all(hashlib.sha256((source/rel).read_bytes()).hexdigest()==sha for rel,sha in before.items())
    identity_sha=hashlib.sha256((out/'SOURCE_IDENTITY.json').read_bytes()).hexdigest()
    header.write_bytes(header.read_bytes()+b'\n// changed compatibility\n')
    binary=tmp_path/'synthetic_elf';binary.write_bytes(b'not executed')
    with pytest.raises(ValueError,match='prepared_adapter_changed'):
        generator.write_instance(out,binary,tmp_path/'instance.json',source_identity_sha256=identity_sha)
