"""Bounded asynchronous preservation of actual immutable native BGR pixels.

Evidence IO never runs on submit/authority threads. A failed or busy writer is
an explicit error, never permission to omit an accepted frame or claim cleanup.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import queue
import threading
import time

FRAME_BYTES=1440*1080*3
READBACK_CHUNK_BYTES=1024*1024
_SOURCE=('robot_id','episode','binding_epoch','observed_seq','sim_time','wall_deadline')


class NativeEvidenceError(RuntimeError):pass
class NativeEvidenceBusy(NativeEvidenceError):pass


def _checked_directory(path):
    path=Path(path).absolute()
    if '..' in path.parts:raise NativeEvidenceError('evidence_directory_traversal')
    for part in (path,*path.parents):
        try:stat=part.lstat()
        except FileNotFoundError:continue
        if part.is_symlink() or getattr(stat,'st_file_attributes',0)&0x400:
            raise NativeEvidenceError('evidence_directory_reparse')
    if path.resolve()!=path:raise NativeEvidenceError('evidence_directory_changed')
    return path


def _file_sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        # Keep the complete on-disk readback check. Larger bounded chunks avoid
        # dozens of Python read/update handoffs for each 4.66 MB native frame.
        for chunk in iter(lambda:stream.read(READBACK_CHUNK_BYTES),b''):digest.update(chunk)
    return digest.hexdigest()


def _timing_source(source):
    if source is None:return None
    if (type(source) is not dict or set(source)!=set(_SOURCE)
        or type(source['robot_id']) is not str or not 1<=len(source['robot_id'])<=128
        or any(type(source[k]) is not int or not 0<=source[k]<=2**53-1
            for k in ('episode','binding_epoch','observed_seq'))
        or any(type(source[k]) not in (int,float) or not math.isfinite(source[k]) or not 0<=source[k]<=1e12
            for k in ('sim_time','wall_deadline'))):raise NativeEvidenceError('invalid_evidence_phase_source')
    # Only immutable original scalar values travel with this same accepted job.
    return tuple(source[k] for k in _SOURCE)


class ActualFrameEvidenceWriter:
    def __init__(self,out,*,phase_probe=None):
        if phase_probe is not None and not callable(getattr(phase_probe,'mark',None)):
            raise ValueError('evidence_phase_probe_required')
        self._phase_probe=phase_probe;self._phase_source=None
        self.out=_checked_directory(out);self.out.mkdir(parents=True,exist_ok=True)
        _checked_directory(self.out)
        self.pending=queue.Queue(maxsize=1);self.stop=threading.Event();self.wake=threading.Event()
        self.lock=threading.Lock();self.error=None;self.last_submitted=-1
        self.submitted=0;self.written=0;self.failed=0;self.running=False;self.last_written=None
        self.shutdown_status=None
        self.thread=threading.Thread(target=self._run,name='native-actual-frame-evidence',daemon=True)
        self.thread.start()

    def can_submit(self):
        """Bounded capacity query, no pixels, IO, checksums or wait.

        Single adapter producer may skip an entire fresh frame before doing
        image work. Every already accepted frame still must be preserved.
        Writer failure/stopping remains an error, never mere backpressure.
        """
        with self.lock:
            if self.error is not None:raise NativeEvidenceError('actual_frame_evidence_failed') from self.error
            if self.stop.is_set():raise NativeEvidenceError('actual_frame_evidence_stopped')
            return not self.pending.full()

    def submit(self,frame_id,immutable_bgr_bytes,expected_sha256,*,source_context=None):
        if type(frame_id) is not int or not 0<=frame_id<=2**53-1:raise NativeEvidenceError('invalid_evidence_frame_id')
        if type(immutable_bgr_bytes) is not bytes or len(immutable_bgr_bytes)!=FRAME_BYTES:
            raise NativeEvidenceError('invalid_actual_bgr_bytes')
        if (type(expected_sha256) is not str or len(expected_sha256)!=64
                or any(c not in '0123456789abcdef' for c in expected_sha256)):
            raise NativeEvidenceError('invalid_evidence_sha256')
        # No IO, checksum scan, wait or replace here. Queue storage owns only
        # immutable bytes, one running frame and at most one pending frame.
        probe=self._phase_probe
        source=_timing_source(source_context) if probe is not None else None
        with self.lock:
            if self.error is not None:raise NativeEvidenceError('actual_frame_evidence_failed') from self.error
            if self.stop.is_set():raise NativeEvidenceError('actual_frame_evidence_stopped')
            if frame_id<=self.last_submitted:raise NativeEvidenceError('evidence_frame_replayed_or_regressed')
            job=((frame_id,immutable_bgr_bytes,expected_sha256) if probe is None
                else (frame_id,immutable_bgr_bytes,expected_sha256,source))
            try:self.pending.put_nowait(job)
            except queue.Full:raise NativeEvidenceBusy('actual_frame_evidence_queue_full') from None
            self.last_submitted=frame_id;self.submitted+=1
            if probe is not None:self._mark_phase('evidence_enqueue',frame_id,expected_sha256,source)
        self.wake.set()
        return dict(frame_id=frame_id,file='sensor_'+str(frame_id)+'.bgr',accepted=True)

    def _mark_phase(self,phase,frame_id,expected,source,*,detail=None):
        self._phase_probe.mark(phase,source=None if source is None else dict(zip(_SOURCE,source)),
            frame_id=frame_id,pixel_sha256=expected,original_deadline=None if source is None else source[-1],
            bytes_count=FRAME_BYTES,queue_depth=self.pending.qsize(),detail=detail)

    def _write_frame(self,frame_id,raw,expected):
        _checked_directory(self.out)
        probe=self._phase_probe
        if probe is not None:self._mark_phase('evidence_raw_hash_begin',frame_id,expected,self._phase_source)
        digest=hashlib.sha256(raw).hexdigest()
        if probe is not None:self._mark_phase('evidence_raw_hash_end',frame_id,expected,self._phase_source)
        if digest!=expected:raise NativeEvidenceError('actual_bgr_sha256_mismatch')
        path=self.out/('sensor_'+str(frame_id)+'.bgr')
        # Exclusive files preserve earlier attempts instead of silently replacing
        # them. Integer-only names cannot carry user-supplied path components.
        if probe is not None:self._mark_phase('evidence_file_write_begin',frame_id,expected,self._phase_source)
        with path.open('xb') as stream:
            count=stream.write(raw)
            if count!=len(raw):raise NativeEvidenceError('actual_bgr_short_write')
        if probe is not None:self._mark_phase('evidence_file_write_end',frame_id,expected,self._phase_source)
        _checked_directory(self.out)
        if path.is_symlink() or path.resolve()!=path or path.stat().st_size!=FRAME_BYTES:
            raise NativeEvidenceError('actual_bgr_file_verification_failed')
        if probe is not None:self._mark_phase('evidence_file_hash_begin',frame_id,expected,self._phase_source)
        digest=_file_sha(path)
        if probe is not None:self._mark_phase('evidence_file_hash_end',frame_id,expected,self._phase_source)
        if digest!=expected:raise NativeEvidenceError('actual_bgr_file_verification_failed')
        manifest=dict(schema='polar.sim.actual_native_frame_evidence.v1',frame_id=frame_id,
            file=path.name,encoding='bgr8',width=1440,height=1080,stride_bytes=4320,bytes=FRAME_BYTES,sha256=expected)
        if probe is not None:self._mark_phase('evidence_manifest_write_begin',frame_id,expected,self._phase_source)
        with (self.out/('sensor_'+str(frame_id)+'.json')).open('x',encoding='utf8',newline='\n') as stream:
            json.dump(manifest,stream,sort_keys=True);stream.write('\n')
        if probe is not None:self._mark_phase('evidence_manifest_write_end',frame_id,expected,self._phase_source)

    def _run(self):
        while True:
            try:job=self.pending.get_nowait()
            except queue.Empty:
                with self.lock:
                    if not self.pending.empty():continue
                    if self.stop.is_set():return
                    self.wake.clear()
                self.wake.wait();continue
            with self.lock:self.running=True
            probe=self._phase_probe
            if probe is None:frame_id,raw,expected=job
            else:
                frame_id,raw,expected,self._phase_source=job
                self._mark_phase('evidence_dequeue',frame_id,expected,self._phase_source)
            outcome='failed'
            try:
                self._write_frame(frame_id,raw,expected)
                with self.lock:self.written+=1;self.last_written=frame_id
                outcome='written'
            except BaseException as exc:
                with self.lock:
                    if self.error is None:self.error=exc
                    self.failed+=1;self.stop.set()
                # Drain every already accepted pending frame even after a fault;
                # the failed frame remains explicitly unqualified on close.
            finally:
                if probe is not None:
                    self._mark_phase('evidence_end',frame_id,expected,self._phase_source,detail=outcome)
                    self._phase_source=None
                with self.lock:self.running=False
                self.pending.task_done();job=None;raw=None

    def request_stop(self):
        with self.lock:self.stop.set()
        self.wake.set()

    def close(self,timeout=.15):
        if type(timeout) not in (int,float) or not 0<=timeout<=2.:raise ValueError('bounded_evidence_close_timeout_required')
        started=time.perf_counter();self.request_stop();self.thread.join(timeout)
        with self.lock:
            clean=(not self.thread.is_alive() and self.error is None and self.written==self.submitted)
            self.shutdown_status=dict(clean=clean,worker_alive=self.thread.is_alive(),submitted=self.submitted,
                written=self.written,failed=self.failed,pending=self.pending.qsize(),running=self.running,
                elapsed_s=time.perf_counter()-started,error_type=type(self.error).__name__ if self.error else None)
            error=self.error
        if not clean:
            raise NativeEvidenceError('actual_frame_evidence_shutdown_incomplete') from error
        return dict(self.shutdown_status)
