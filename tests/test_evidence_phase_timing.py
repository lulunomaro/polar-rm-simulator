"""Actual temporary-file evidence timings; no NN, GL, ROS or simulation."""
import copy
import hashlib
import threading
from unittest.mock import patch

import pytest

from rm_match.integrations.phase_timing import NumericPhaseProbe
from rm_match.platform_v2 import native_evidence as evidence


RAW=b'\x35'*evidence.FRAME_BYTES
SHA=hashlib.sha256(RAW).hexdigest()
SOURCE=dict(robot_id='red_infantry',episode=2,binding_epoch=3,observed_seq=11,sim_time=1,wall_deadline=100.08)
PHASES=['evidence_enqueue','evidence_dequeue','evidence_raw_hash_begin','evidence_raw_hash_end',
    'evidence_file_write_begin','evidence_file_write_end','evidence_file_hash_begin','evidence_file_hash_end',
    'evidence_manifest_write_begin','evidence_manifest_write_end','evidence_end']


def test_opt_in_retains_original_source_phase_order_and_exact_artifact_bytes_without_extra_hashes(tmp_path):
    real_sha=hashlib.sha256;outputs=[];hash_calls=[]
    for enabled in (False,True):
        calls=[]
        def counted(data=b''):
            calls.append(len(data));return real_sha(data)
        out=tmp_path/('timed' if enabled else 'default');probe=NumericPhaseProbe() if enabled else None
        with patch.object(evidence.hashlib,'sha256',side_effect=counted):
            writer=evidence.ActualFrameEvidenceWriter(out,phase_probe=probe)
            writer.submit(17,RAW,SHA,**({'source_context':SOURCE} if enabled else {}))
            assert writer.close(1.)['clean'] and not writer.thread.is_alive()
        outputs.append({p.name:p.read_bytes() for p in out.iterdir()});hash_calls.append(calls)
    assert outputs[0]==outputs[1] and set(outputs[0])=={'sensor_17.bgr','sensor_17.json'}
    assert outputs[0]['sensor_17.bgr']==RAW and hash_calls==[[evidence.FRAME_BYTES,0]]*2
    snapshot=probe.snapshot();rows=snapshot['rows']
    assert snapshot['complete'] and [r['phase'] for r in rows]==PHASES
    for row in rows:
        assert all(type(row[k]) is type(SOURCE[k]) and row[k]==SOURCE[k] for k in SOURCE)
        assert row['frame_id']==17 and row['pixel_sha256']==SHA and row['bytes_count']==evidence.FRAME_BYTES
        assert row['original_deadline']==SOURCE['wall_deadline'] and row['queue_depth'] in (0,1)
        assert all(type(value) in (type(None),str,int,float) for value in row.values())
    assert rows[0]['thread_id']==threading.get_ident()
    assert all(r['thread_id']==writer.thread.ident for r in rows[1:])
    assert [r['wall_ns'] for r in rows]==sorted(r['wall_ns'] for r in rows)
    assert [r['thread_cpu_ns'] for r in rows[1:]]==sorted(r['thread_cpu_ns'] for r in rows[1:])
    assert rows[-1]['detail']=='written'


def test_disabled_hot_path_never_calls_probe_new_clocks_or_context_projection(tmp_path):
    with patch.object(NumericPhaseProbe,'sample',side_effect=AssertionError('new timing clock disabled')), \
         patch.object(evidence,'_timing_source',side_effect=AssertionError('no diagnostic source copy')):
        writer=evidence.ActualFrameEvidenceWriter(tmp_path/'default')
        with patch.object(writer,'_mark_phase',side_effect=AssertionError('probe disabled')), \
             patch.object(writer.pending,'qsize',wraps=writer.pending.qsize) as occupancy:
            writer.submit(1,RAW,SHA)
            writer.thread.join(.01)
            assert occupancy.call_count==0  # Existing close, and only close, queries its status.
            assert writer.close(1.)['clean']
    assert writer.pending.maxsize==1


def test_queued_source_is_frozen_and_probe_overflow_never_changes_bounded_evidence_or_bytes(tmp_path):
    entered=threading.Event();release=threading.Event();probe=NumericPhaseProbe(capacity=2)
    class Writer(evidence.ActualFrameEvidenceWriter):
        def _write_frame(self,*args):
            if args[0]==1:
                entered.set();assert release.wait(2.)
            return super()._write_frame(*args)
    writer=Writer(tmp_path,phase_probe=probe);source=copy.deepcopy(SOURCE)
    try:
        writer.submit(1,RAW,SHA,source_context=source);assert entered.wait(1.)
        source['robot_id']='blue_infantry';source['observed_seq']=12
        writer.submit(2,RAW,SHA,source_context=source)
        assert writer.pending.maxsize==1 and not writer.can_submit()
        with pytest.raises(evidence.NativeEvidenceBusy):writer.submit(3,RAW,SHA,source_context=source)
        release.set();status=writer.close(1.)
        assert status['clean'] and status['submitted']==status['written']==2 and status['failed']==0
        assert (tmp_path/'sensor_1.bgr').read_bytes()==(tmp_path/'sensor_2.bgr').read_bytes()==RAW
        assert not (tmp_path/'sensor_3.bgr').exists()
        snapshot=probe.snapshot();assert snapshot['retained']==2 and snapshot['dropped']>0 and not snapshot['complete']
        assert all(r['robot_id']==SOURCE['robot_id'] and r['observed_seq']==SOURCE['observed_seq'] for r in snapshot['rows'])
    finally:
        release.set();writer.close(1.)


@pytest.mark.parametrize('change',['extra','integer_alias','nonfinite','wrong_shape'])
def test_only_exact_finite_original_six_scalars_can_be_associated_with_a_timed_job(tmp_path,change):
    probe=NumericPhaseProbe();source=copy.deepcopy(SOURCE)
    if change=='extra':source['truth']=[0,0]
    elif change=='integer_alias':source['observed_seq']=11.
    elif change=='nonfinite':source['wall_deadline']=float('nan')
    else:source=False
    writer=evidence.ActualFrameEvidenceWriter(tmp_path,phase_probe=probe)
    try:
        with pytest.raises(evidence.NativeEvidenceError,match='phase_source'):
            writer.submit(1,RAW,SHA,source_context=source)
        assert writer.submitted==0 and probe.snapshot()['retained']==0
    finally:assert writer.close(1.)['clean']


def test_failed_original_checksum_is_still_failure_and_phase_end_does_not_claim_saved_pixels(tmp_path):
    probe=NumericPhaseProbe();writer=evidence.ActualFrameEvidenceWriter(tmp_path,phase_probe=probe)
    writer.submit(1,RAW,'0'*64,source_context=SOURCE)
    with pytest.raises(evidence.NativeEvidenceError,match='shutdown_incomplete'):writer.close(1.)
    assert not writer.thread.is_alive() and writer.shutdown_status['failed']==1
    rows=probe.snapshot()['rows']
    assert rows[-1]['phase']=='evidence_end' and rows[-1]['detail']=='failed'
    assert not any(r['phase']=='evidence_file_write_begin' for r in rows)
    assert list(tmp_path.iterdir())==[]


def test_missing_source_stays_explicitly_unassociated_and_invalid_probe_starts_no_worker(tmp_path):
    probe=NumericPhaseProbe();writer=evidence.ActualFrameEvidenceWriter(tmp_path/'unassociated',phase_probe=probe)
    writer.submit(1,RAW,SHA);assert writer.close(1.)['clean']
    assert all(all(r[k] is None for k in SOURCE) and r['original_deadline'] is None for r in probe.snapshot()['rows'])
    with pytest.raises(ValueError,match='phase_probe'):evidence.ActualFrameEvidenceWriter(tmp_path/'absent',phase_probe=False)
    assert not (tmp_path/'absent').exists()
