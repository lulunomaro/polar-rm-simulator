"""Temporary synthetic audit fixtures only; no live/model/GPU qualification."""
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from tools.audit_live_native_pixels import audit_saved_native_pixels,STRATEGY,IMAGE_BYTES


@pytest.fixture
def evidence(tmp_path):
    native=tmp_path/'native/binding_test/actual_frames';native.mkdir(parents=True)
    bgr=b'\x19\x20\xff'*(IMAGE_BYTES//3);rgb=b'\xff\x20\x19'*(IMAGE_BYTES//3)
    sha=hashlib.sha256(bgr).hexdigest()
    raw=dict(frame_id=1,capture_wall=100.,capture_sim_time=.41,encoded_wall=100.04,
        shape=[1080,1440,3],raw_rgb_sha256=hashlib.sha256(rgb).hexdigest())
    request=dict(event='native_request',frame_id=1,observed_seq=7,episode=0,binding_epoch=1,robot_id='red_sentry',
        capture_sim_time=.41,observation_sim_time=.428,raw_bgr_sha256=sha,raw_rgb_sha256=None,rgb_trace_strategy=STRATEGY)
    enqueue=dict(event='adapter_enqueue',observed_seq=7,episode=0,binding_epoch=1,robot_id='red_sentry',kind='aim',
        sensor_budget=dict(frame_id=1,capture_wall=100.,capture_sim_time=.41))
    manifest=dict(schema='polar.sim.actual_native_frame_evidence.v1',frame_id=1,width=1440,height=1080,
        stride_bytes=4320,bytes=IMAGE_BYTES,encoding='bgr8',file='sensor_1.bgr',sha256=sha)
    def write(rows=None,frames=None):
        (tmp_path/'ledger.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in ([enqueue,request] if rows is None else rows)),encoding='utf-8')
        (tmp_path/'FRAME_BINDINGS.json').write_text(json.dumps({'1':raw} if frames is None else frames),encoding='utf-8')
        (native/'sensor_1.json').write_text(json.dumps(manifest),encoding='utf-8')
    (native/'sensor_1.bgr').write_bytes(bgr);write()
    return SimpleNamespace(root=tmp_path,native=native,bgr=bgr,raw=raw,request=request,
        enqueue=enqueue,manifest=manifest,write=write)


def test_postclose_same_actual_bytes_proves_original_clocks_and_request_identity(evidence):
    before=(evidence.root/'ledger.jsonl').read_bytes();r=audit_saved_native_pixels(evidence.root)
    assert r['clean'] and not r['errors'] and len(r['proofs'])==1
    p=r['proofs'][0]
    assert p['original_capture_wall']==100. and p['original_capture_sim_time']==.41
    assert p['original_control_time_ns']==428000000
    assert p['derived_rgb_sha256']==evidence.raw['raw_rgb_sha256']
    assert p['raw_bgr_sha256']==evidence.manifest['sha256']
    assert p['request_identities']==[dict(observed_seq=7,episode=0,binding_epoch=1)]
    assert (evidence.root/'ledger.jsonl').read_bytes()==before


def test_multiple_frames_and_duplicate_request_with_original_time_unchanged(evidence):
    m=dict(evidence.manifest,frame_id=2,file='sensor_2.bgr')
    (evidence.native/'sensor_2.json').write_text(json.dumps(m));(evidence.native/'sensor_2.bgr').write_bytes(evidence.bgr)
    raw2=dict(evidence.raw,frame_id=2,capture_wall=101.,capture_sim_time=.51)
    req2=dict(evidence.request,frame_id=2,observed_seq=8,capture_sim_time=.51,observation_sim_time=.528)
    enq2=dict(evidence.enqueue,observed_seq=8,sensor_budget=dict(frame_id=2,capture_wall=101.,capture_sim_time=.51))
    evidence.write(rows=[evidence.enqueue,evidence.request,evidence.request,enq2,req2],frames={'1':evidence.raw,'2':raw2})
    r=audit_saved_native_pixels(evidence.root);assert r['clean'] and len(r['proofs'])==2
    assert r['proofs'][0]['native_request_count']==2


@pytest.mark.parametrize('change',[dict(observation_sim_time=.429),dict(capture_sim_time=.42),dict(binding_epoch=2)])
def test_same_frame_changed_declared_time_or_context_is_not_deduplicated(evidence,change):
    evidence.write(rows=[evidence.enqueue,evidence.request,dict(evidence.request,**change)])
    assert not audit_saved_native_pixels(evidence.root)['clean']


@pytest.mark.parametrize('key,value',[('frame_id',2),('width',1439),('height',1079),('stride_bytes',4321),
    ('bytes',IMAGE_BYTES-1),('encoding','rgb8'),('schema','wrong'),('file','../sensor_1.bgr'),
    ('file','C:/foreign.bgr'),('sha256','0'*64),('frame_id',True)])
def test_manifest_tampering_never_produces_proof(evidence,key,value):
    evidence.manifest[key]=value;evidence.write();r=audit_saved_native_pixels(evidence.root)
    assert not r['clean'] and r['errors'] and not r['proofs']


@pytest.mark.parametrize('variant',['truncated','altered'])
def test_truncated_or_changed_pixels_fail(evidence,variant):
    contents=b'short' if variant=='truncated' else b'\x21'*IMAGE_BYTES
    (evidence.native/'sensor_1.bgr').write_bytes(contents)
    assert not audit_saved_native_pixels(evidence.root)['clean']


def test_missing_ambiguous_or_duplicate_json_manifest_fails(evidence):
    original=evidence.native/'sensor_1.json';original.unlink()
    assert not audit_saved_native_pixels(evidence.root)['clean']
    evidence.write();duplicate=evidence.root/'native/binding_other/actual_frames';duplicate.mkdir(parents=True)
    (duplicate/'sensor_1.json').write_bytes(original.read_bytes())
    assert not audit_saved_native_pixels(evidence.root)['clean']
    (duplicate/'sensor_1.json').unlink();original.write_text('{"frame_id":1,"frame_id":2}')
    assert not audit_saved_native_pixels(evidence.root)['clean']


@pytest.mark.parametrize('target,key,value',[('raw','raw_rgb_sha256','0'*64),('raw','frame_id',2),
    ('raw','shape',[1080,1440,4]),('raw','capture_sim_time',.42),('raw','capture_wall',101.),
    ('request','raw_bgr_sha256','0'*64),('request','raw_rgb_sha256','0'*64),
    ('request','rgb_trace_strategy','unchecked'),('request','control_time_ns',1)])
def test_original_raw_or_native_binding_mismatch_refused(evidence,target,key,value):
    getattr(evidence,target)[key]=value;evidence.write()
    assert not audit_saved_native_pixels(evidence.root)['clean']


def test_no_request_or_missing_original_frame_returns_errors_without_throw(evidence):
    evidence.write(rows=[evidence.enqueue]);assert not audit_saved_native_pixels(evidence.root)['clean']
    evidence.write(frames={});assert not audit_saved_native_pixels(evidence.root)['clean']
    assert not audit_saved_native_pixels(evidence.root/'missing')['clean']


def test_duplicate_frame_json_and_ambiguous_enqueue_refused(evidence):
    (evidence.root/'FRAME_BINDINGS.json').write_text('{"1":{},"1":{}}')
    assert not audit_saved_native_pixels(evidence.root)['clean']
    evidence.write(rows=[evidence.enqueue,evidence.enqueue,evidence.request])
    assert not audit_saved_native_pixels(evidence.root)['clean']


def test_reparse_image_refused_before_read_and_audit_returns_failure(evidence):
    path=evidence.native/'sensor_1.bgr';original=Path.lstat
    def lstat(p,*args,**kwargs):
        if p==path:return SimpleNamespace(st_mode=original(p).st_mode,st_file_attributes=0x400)
        return original(p,*args,**kwargs)
    with patch.object(Path,'lstat',lstat):
        r=audit_saved_native_pixels(evidence.root)
    assert not r['clean'] and r['errors']


def test_actual_symlink_image_is_refused_without_following_target(evidence,tmp_path):
    path=evidence.native/'sensor_1.bgr';target=tmp_path/'external_pixels.bgr';path.rename(target)
    try:os.symlink(target,path)
    except OSError:pytest.skip('Host lacks symlink creation privilege; reparse attribute unit still runs')
    r=audit_saved_native_pixels(evidence.root)
    assert not r['clean'] and r['errors']


def test_raw_and_request_json_duplicate_keys_and_private_request_id_refused(evidence):
    (evidence.root/'ledger.jsonl').write_text('{"event":"native_request","event":"native_request"}')
    assert not audit_saved_native_pixels(evidence.root)['clean']
    evidence.request['request_id']={'private_truth':1};evidence.write()
    assert not audit_saved_native_pixels(evidence.root)['clean']


@pytest.mark.parametrize('key,value',[('episode',False),('episode',0.),('binding_epoch',True),('binding_epoch',1.)])
def test_enqueue_integer_context_rejects_equal_boolean_or_float_aliases(evidence,key,value):
    evidence.enqueue[key]=value;evidence.write()
    assert not audit_saved_native_pixels(evidence.root)['clean']


@pytest.mark.parametrize('key,value',[('capture_wall',False),('control_time_ns',428000000.),
    ('control_time_ns',True),('exposure_timestamp_ns',410000000.),('exposure_timestamp_ns',False)])
def test_optional_original_request_clocks_have_exact_types(evidence,key,value):
    evidence.request[key]=value;evidence.write()
    assert not audit_saved_native_pixels(evidence.root)['clean']


@pytest.mark.parametrize('key',['capture_wall','capture_sim_time'])
def test_budget_boolean_clock_cannot_equal_original_zero_time(evidence,key):
    evidence.raw[key]=0.;evidence.enqueue['sensor_budget'][key]=False
    if key=='capture_sim_time':evidence.request[key]=0.
    evidence.write();assert not audit_saved_native_pixels(evidence.root)['clean']


def test_same_sequence_only_matches_request_robot_and_control_kind(evidence):
    foreign_robot=dict(evidence.enqueue,robot_id='blue_infantry')
    foreign_kind=dict(evidence.enqueue,kind='chassis')
    evidence.write(rows=[foreign_robot,foreign_kind,evidence.request])
    assert not audit_saved_native_pixels(evidence.root)['clean']
    evidence.write(rows=[foreign_robot,foreign_kind,evidence.enqueue,evidence.request])
    assert audit_saved_native_pixels(evidence.root)['clean']
    evidence.write(rows=[foreign_robot,evidence.enqueue,evidence.enqueue,evidence.request])
    assert not audit_saved_native_pixels(evidence.root)['clean']


def test_optional_exact_original_clocks_and_explicit_kind_preserve_proof(evidence):
    evidence.request.update(capture_wall=100.,control_time_ns=428000000,exposure_timestamp_ns=410000000,kind='aim')
    evidence.write();r=audit_saved_native_pixels(evidence.root)
    assert r['clean'] and r['proofs'][0]['original_control_time_ns']==428000000


def test_optional_boolean_capture_and_control_cannot_alias_valid_zero_clocks(evidence):
    evidence.raw.update(capture_wall=0.,capture_sim_time=0.)
    evidence.enqueue['sensor_budget'].update(capture_wall=0.,capture_sim_time=0.)
    evidence.request.update(capture_sim_time=0.,observation_sim_time=0.,capture_wall=0.,control_time_ns=0)
    evidence.write();assert audit_saved_native_pixels(evidence.root)['clean']
    for key in ('capture_wall','control_time_ns'):
        evidence.request[key]=False;evidence.write()
        assert not audit_saved_native_pixels(evidence.root)['clean']
        evidence.request[key]=0
