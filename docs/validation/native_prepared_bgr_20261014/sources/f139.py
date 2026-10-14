"""Owned actual-pixel evidence IO, harmless CPU/file fixtures only."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
import queue
from unittest.mock import patch
from .native_evidence import ActualFrameEvidenceWriter,NativeEvidenceError,NativeEvidenceBusy,FRAME_BYTES

RAW=bytes([53])*FRAME_BYTES
SHA=hashlib.sha256(RAW).hexdigest()


class EvidenceTests(unittest.TestCase):
    def test_submit_between_empty_read_and_wait_does_not_lose_wakeup(self):
        entered=threading.Event();release=threading.Event();original=queue.Queue
        class RaceQueue(original):
            first=True
            def get_nowait(self):
                if self.first:
                    self.first=False;entered.set();release.wait(2.);raise queue.Empty
                return super().get_nowait()
        with tempfile.TemporaryDirectory() as directory:
            with patch('rm_match.platform_v2.native_evidence.queue.Queue',RaceQueue):
                writer=ActualFrameEvidenceWriter(directory)
            try:
                self.assertTrue(entered.wait(1.));writer.submit(1,RAW,SHA);release.set()
                self.assertTrue(writer.close(1.)['clean'])
            finally:release.set();writer.close(1.)

    def test_actual_bytes_manifest_verified_and_io_only_runs_on_worker(self):
        ids=[]
        class Writer(ActualFrameEvidenceWriter):
            def _write_frame(self,*args):ids.append(threading.get_ident());super()._write_frame(*args)
        with tempfile.TemporaryDirectory() as directory:
            writer=Writer(directory);writer.submit(1,RAW,SHA);result=writer.close()
            self.assertTrue(result['clean']);self.assertEqual(result['written'],1)
            self.assertEqual(ids,[writer.thread.ident]);self.assertNotEqual(ids[0],threading.get_ident())
            path=Path(directory)/'sensor_1.bgr';self.assertEqual(path.read_bytes(),RAW)
            manifest=json.loads((Path(directory)/'sensor_1.json').read_text())
            self.assertEqual(manifest['sha256'],hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(manifest['bytes'],FRAME_BYTES);writer.close()
            path.unlink()  # No open file or directory handle survives close.

    def test_running_and_one_pending_busy_is_explicit_close_drains_both(self):
        entered=threading.Event();release=threading.Event()
        class Writer(ActualFrameEvidenceWriter):
            def _write_frame(self,*args):entered.set();release.wait(3.);super()._write_frame(*args)
        with tempfile.TemporaryDirectory() as directory:
            writer=Writer(directory)
            try:
                writer.submit(1,RAW,SHA);self.assertTrue(entered.wait(1.))
                second=bytes([54])*FRAME_BYTES;second_sha=hashlib.sha256(second).hexdigest()
                writer.submit(2,second,second_sha);start=time.perf_counter()
                with self.assertRaises(NativeEvidenceBusy):writer.submit(3,RAW,SHA)
                self.assertLess(time.perf_counter()-start,.1)
                writer.request_stop()
                with self.assertRaisesRegex(NativeEvidenceError,'stopped'):writer.submit(3,RAW,SHA)
                release.set();status=writer.close(1.)
                self.assertTrue(status['clean']);self.assertEqual(status['submitted'],2);self.assertEqual(status['written'],2)
                self.assertEqual((Path(directory)/'sensor_1.bgr').read_bytes(),RAW)
                self.assertEqual((Path(directory)/'sensor_2.bgr').read_bytes(),second)
                self.assertFalse((Path(directory)/'sensor_3.bgr').exists())
            finally:release.set();writer.close(1.)

    def test_stalled_io_close_is_bounded_and_never_falsely_clean(self):
        entered=threading.Event();release=threading.Event()
        class Writer(ActualFrameEvidenceWriter):
            def _write_frame(self,*args):entered.set();release.wait(3.);super()._write_frame(*args)
        with tempfile.TemporaryDirectory() as directory:
            writer=Writer(directory)
            try:
                writer.submit(1,RAW,SHA);self.assertTrue(entered.wait(1.));writer.submit(2,RAW,SHA)
                start=time.perf_counter()
                with self.assertRaisesRegex(NativeEvidenceError,'shutdown_incomplete'):writer.close(.02)
                self.assertLess(time.perf_counter()-start,.15)
                self.assertFalse(writer.shutdown_status['clean']);self.assertTrue(writer.shutdown_status['worker_alive'])
                self.assertEqual(writer.shutdown_status['submitted'],2)
                release.set();self.assertTrue(writer.close(1.)['clean'])
            finally:release.set();writer.close(1.)

    def test_wrong_sha_is_worker_failure_and_accepted_pending_still_saved(self):
        entered=threading.Event();release=threading.Event()
        class Writer(ActualFrameEvidenceWriter):
            def _write_frame(self,*args):entered.set();release.wait(3.);super()._write_frame(*args)
        with tempfile.TemporaryDirectory() as directory:
            writer=Writer(directory)
            try:
                writer.submit(1,RAW,'0'*64);self.assertTrue(entered.wait(1.));writer.submit(2,RAW,SHA);release.set()
                with self.assertRaises(NativeEvidenceError):writer.close(1.)
                self.assertEqual(writer.shutdown_status['failed'],1);self.assertEqual(writer.shutdown_status['written'],1)
                self.assertEqual((Path(directory)/'sensor_2.bgr').read_bytes(),RAW)
                with self.assertRaisesRegex(NativeEvidenceError,'failed'):writer.submit(3,RAW,SHA)
            finally:release.set();writer.thread.join(2.)

    def test_invalid_mutable_size_sha_and_frame_paths_are_rejected_before_accept(self):
        with tempfile.TemporaryDirectory() as directory:
            writer=ActualFrameEvidenceWriter(directory)
            try:
                for frame,raw,digest in [('..',RAW,SHA),(-1,RAW,SHA),(True,RAW,SHA),(1,bytearray(RAW),SHA),
                        (1,RAW[:-1],SHA),(1,RAW,'not-a-sha'),(1,RAW,SHA.upper())]:
                    with self.subTest(frame=frame,size=len(raw)),self.assertRaises(NativeEvidenceError):writer.submit(frame,raw,digest)
                self.assertEqual(writer.submitted,0)
                writer.submit(2,RAW,SHA)
                with self.assertRaisesRegex(NativeEvidenceError,'replayed'):writer.submit(2,RAW,SHA)
                with self.assertRaisesRegex(NativeEvidenceError,'regressed'):writer.submit(1,RAW,SHA)
            finally:writer.close(1.)

    def test_existing_frame_is_not_overwritten_and_io_failure_is_not_clean(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'sensor_1.bgr';path.write_bytes(b'preserve history')
            writer=ActualFrameEvidenceWriter(directory);writer.submit(1,RAW,SHA)
            with self.assertRaises(NativeEvidenceError):writer.close(1.)
            self.assertEqual(path.read_bytes(),b'preserve history');self.assertFalse(writer.shutdown_status['clean'])

    def test_directory_alias_rejected_before_worker_writes_outside(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/'target';target.mkdir();alias=root/'alias'
            if os.name=='nt':
                result=subprocess.run(['cmd','/c','mklink','/J',str(alias),str(target)],capture_output=True)
                if result.returncode:self.skipTest('Junction creation unavailable')
            else:alias.symlink_to(target,target_is_directory=True)
            try:
                with self.assertRaisesRegex(NativeEvidenceError,'reparse'):ActualFrameEvidenceWriter(alias)
                self.assertEqual(list(target.iterdir()),[])
            finally:os.rmdir(alias) if os.name=='nt' else alias.unlink()

    def test_directory_redirected_after_submit_is_rejected_before_io(self):
        entered=threading.Event();release=threading.Event()
        class Writer(ActualFrameEvidenceWriter):
            def _write_frame(self,*args):entered.set();release.wait(3.);super()._write_frame(*args)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);out=root/'out';target=root/'elsewhere';target.mkdir();moved=root/'moved'
            writer=Writer(out)
            try:
                writer.submit(1,RAW,SHA);self.assertTrue(entered.wait(1.));out.rename(moved)
                if os.name=='nt':
                    result=subprocess.run(['cmd','/c','mklink','/J',str(out),str(target)],capture_output=True)
                    if result.returncode:moved.rename(out);self.skipTest('Junction creation unavailable')
                else:out.symlink_to(target,target_is_directory=True)
                release.set()
                with self.assertRaises(NativeEvidenceError):writer.close(1.)
                self.assertEqual(list(target.iterdir()),[]);self.assertFalse(writer.shutdown_status['clean'])
            finally:
                release.set();writer.thread.join(2.)
                if moved.exists():
                    os.rmdir(out) if os.name=='nt' else out.unlink();moved.rename(out)


if __name__=='__main__':unittest.main()
