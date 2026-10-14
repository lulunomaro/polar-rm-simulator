"""Owned native transport shutdown, using harmless Python children, never RMCS."""
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from .rmcs_process import RMCSProcess


class CleanupTests(unittest.TestCase):
    def actor(self,directory):
        return RMCSProcess(sys.executable,Path(directory)/'unused-executor',directory,{},timeout=.1)

    def child(self,actor,ignore_term=False):
        interpreter=getattr(sys,'_base_executable',sys.executable)
        code='import signal,time; '
        if ignore_term:code+='signal.signal(signal.SIGTERM,signal.SIG_IGN); '
        code+='print("ready",flush=True); time.sleep(60)'
        actor.stderr=(actor.out/'stderr.log').open('w')
        actor.process=subprocess.Popen([interpreter,'-I','-c',code],stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=actor.stderr,text=True,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.assertEqual(actor.process.stdout.readline().strip(),'ready')
        return actor.process,actor.stderr

    def verify_cleanup(self,ignore_term=False):
        with tempfile.TemporaryDirectory() as directory:
            actor=self.actor(directory);child,errorlog=self.child(actor,ignore_term)
            try:
                before=time.monotonic();actor.close();elapsed=time.monotonic()-before
                self.assertLess(elapsed,2.)
                self.assertIsNotNone(child.poll());self.assertIsNone(actor.process)
                self.assertIsNone(actor.stderr);self.assertTrue(errorlog.closed)
                self.assertTrue(child.stdin.closed);self.assertTrue(child.stdout.closed)
                actor.close()  # Idempotent, no stale handle or directory lock.
            finally:
                if child.poll() is None:child.kill();child.wait(timeout=2.)
                actor.close()
            self.assertTrue((Path(directory)/'stderr.log').exists())

    def test_actual_child_terminated_and_reaped_with_all_owned_streams_closed(self):
        self.verify_cleanup()

    @unittest.skipUnless(os.name=='posix','SIGTERM-ignore is POSIX-only; Windows TerminateProcess is immediate')
    def test_actual_sigterm_ignoring_child_is_killed_and_reaped(self):
        self.verify_cleanup(ignore_term=True)

    def test_terminate_timeout_forces_kill_before_closing_buffered_stdin(self):
        class BufferedInput(io.StringIO):
            def close(stream):
                self.assertTrue(child.killed)
                super(BufferedInput,stream).close()
        class Child:
            def __init__(self):
                self.stdin=BufferedInput();self.stdout=io.StringIO();self.stderr=None;self.killed=False
            def poll(self):return None
            def terminate(self):pass
            def kill(self):self.killed=True
            def wait(self,timeout):
                if not self.killed:raise subprocess.TimeoutExpired('owned-child-fixture',timeout)
                return -9
        with tempfile.TemporaryDirectory() as directory:
            actor=self.actor(directory);child=Child();actor.process=child;actor.stderr=io.StringIO()
            errorlog=actor.stderr;actor.close()
            self.assertTrue(child.killed);self.assertTrue(child.stdin.closed)
            self.assertTrue(child.stdout.closed);self.assertTrue(errorlog.closed)
            self.assertIsNone(actor.process)

    def test_cleanup_finally_closes_resources_even_if_reap_reports_failure(self):
        class Child:
            stdin=io.StringIO();stdout=io.StringIO();stderr=None
            def poll(self):return None
            def terminate(self):pass
            def kill(self):pass
            def wait(self,timeout):raise subprocess.TimeoutExpired('unreapable-fixture',timeout)
        with tempfile.TemporaryDirectory() as directory:
            actor=self.actor(directory);child=Child();actor.process=child;errorlog=io.StringIO();actor.stderr=errorlog
            with self.assertRaises(subprocess.TimeoutExpired):actor.close()
            self.assertTrue(child.stdin.closed);self.assertTrue(child.stdout.closed);self.assertTrue(errorlog.closed)
            self.assertIsNone(actor.process);self.assertIsNone(actor.stderr)


if __name__=='__main__':unittest.main()
