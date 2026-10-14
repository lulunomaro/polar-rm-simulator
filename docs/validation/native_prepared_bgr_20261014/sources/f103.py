"""Bounded asynchronous preservation of actual immutable native BGR pixels.

Evidence IO never runs on submit/authority threads. A failed or busy writer is
an explicit error, never permission to omit an accepted frame or claim cleanup.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import queue
import threading
import time

FRAME_BYTES=1440*1080*3


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
        for chunk in iter(lambda:stream.read(64*1024),b''):digest.update(chunk)
    return digest.hexdigest()


class ActualFrameEvidenceWriter:
    def __init__(self,out):
        self.out=_checked_directory(out);self.out.mkdir(parents=True,exist_ok=True)
        _checked_directory(self.out)
        self.pending=queue.Queue(maxsize=1);self.stop=threading.Event();self.wake=threading.Event()
        self.lock=threading.Lock();self.error=None;self.last_submitted=-1
        self.submitted=0;self.written=0;self.failed=0;self.running=False;self.last_written=None
        self.shutdown_status=None
        self.thread=threading.Thread(target=self._run,name='native-actual-frame-evidence',daemon=True)
        self.thread.start()

    def submit(self,frame_id,immutable_bgr_bytes,expected_sha256):
        if type(frame_id) is not int or not 0<=frame_id<=2**53-1:raise NativeEvidenceError('invalid_evidence_frame_id')
        if type(immutable_bgr_bytes) is not bytes or len(immutable_bgr_bytes)!=FRAME_BYTES:
            raise NativeEvidenceError('invalid_actual_bgr_bytes')
        if (type(expected_sha256) is not str or len(expected_sha256)!=64
                or any(c not in '0123456789abcdef' for c in expected_sha256)):
            raise NativeEvidenceError('invalid_evidence_sha256')
        # No IO, checksum scan, wait or replace here. Queue storage owns only
        # immutable bytes, one running frame and at most one pending frame.
        with self.lock:
            if self.error is not None:raise NativeEvidenceError('actual_frame_evidence_failed') from self.error
            if self.stop.is_set():raise NativeEvidenceError('actual_frame_evidence_stopped')
            if frame_id<=self.last_submitted:raise NativeEvidenceError('evidence_frame_replayed_or_regressed')
            try:self.pending.put_nowait((frame_id,immutable_bgr_bytes,expected_sha256))
            except queue.Full:raise NativeEvidenceBusy('actual_frame_evidence_queue_full') from None
            self.last_submitted=frame_id;self.submitted+=1
        self.wake.set()
        return dict(frame_id=frame_id,file='sensor_'+str(frame_id)+'.bgr',accepted=True)

    def _write_frame(self,frame_id,raw,expected):
        _checked_directory(self.out)
        digest=hashlib.sha256(raw).hexdigest()
        if digest!=expected:raise NativeEvidenceError('actual_bgr_sha256_mismatch')
        path=self.out/('sensor_'+str(frame_id)+'.bgr')
        # Exclusive files preserve earlier attempts instead of silently replacing
        # them. Integer-only names cannot carry user-supplied path components.
        with path.open('xb') as stream:
            count=stream.write(raw)
            if count!=len(raw):raise NativeEvidenceError('actual_bgr_short_write')
        _checked_directory(self.out)
        if path.is_symlink() or path.resolve()!=path or path.stat().st_size!=FRAME_BYTES or _file_sha(path)!=expected:
            raise NativeEvidenceError('actual_bgr_file_verification_failed')
        manifest=dict(schema='polar.sim.actual_native_frame_evidence.v1',frame_id=frame_id,
            file=path.name,encoding='bgr8',width=1440,height=1080,stride_bytes=4320,bytes=FRAME_BYTES,sha256=expected)
        with (self.out/('sensor_'+str(frame_id)+'.json')).open('x',encoding='utf8',newline='\n') as stream:
            json.dump(manifest,stream,sort_keys=True);stream.write('\n')

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
            frame_id,raw,expected=job
            try:
                self._write_frame(frame_id,raw,expected)
                with self.lock:self.written+=1;self.last_written=frame_id
            except BaseException as exc:
                with self.lock:
                    if self.error is None:self.error=exc
                    self.failed+=1;self.stop.set()
                # Drain every already accepted pending frame even after a fault;
                # the failed frame remains explicitly unqualified on close.
            finally:
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
