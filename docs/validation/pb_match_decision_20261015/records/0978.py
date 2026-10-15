"""Real wall clock checks: no fabricated sensor frames or algorithm results."""
import sys
import threading
import time
import unittest
from .runtime import PlatformRuntime
from .test_runtime import FakeBackend


class WallPacingTests(unittest.TestCase):
    def test_real_wall_rate_never_exceeds_configured_limit_by_more_than_one_step(self):
        backend=FakeBackend();runtime=PlatformRuntime(backend)
        started=time.perf_counter();runtime.run(max_wall_seconds=.06,real_time_factor=.5)
        elapsed=time.perf_counter()-started
        self.assertGreater(runtime.steps,0)
        self.assertLessEqual(backend.sim_time,.5*elapsed+backend.timestep)

    @unittest.skipUnless(sys.platform=='win32','Windows high-resolution wait branch')
    def test_stop_interrupts_long_physics_wait_without_waiting_for_next_step(self):
        backend=FakeBackend();backend.timestep=.5;runtime=PlatformRuntime(backend)
        errors=[]
        def run():
            try:runtime.run(max_wall_seconds=1)
            except BaseException as exc:errors.append(exc)
        thread=threading.Thread(target=run);thread.start()
        try:
            deadline=time.perf_counter()+1
            while runtime.steps==0 and time.perf_counter()<deadline:time.sleep(.001)
            self.assertGreater(runtime.steps,0)
            runtime.request_stop();thread.join(.2)
            self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
        finally:runtime.request_stop();thread.join(1)
