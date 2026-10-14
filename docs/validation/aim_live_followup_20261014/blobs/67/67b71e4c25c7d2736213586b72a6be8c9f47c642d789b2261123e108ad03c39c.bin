"""A wall-clock stall consumes real time but must not erase physics debt."""
import unittest
from .runtime import PlatformRuntime
from .test_control import Clock
from .test_runtime import FakeBackend


class RuntimePacingTests(unittest.TestCase):
    def test_catches_up_original_steps_after_stall_without_exceeding_wall_budget(self):
        clock=Clock();clock.now=0.
        class StallBackend(FakeBackend):
            def step(self,targets):
                clock.advance(.012 if len(self.step_threads)==2 else .002)
                super().step(targets)
        backend=StallBackend()
        runtime=PlatformRuntime(backend,clock=clock)
        requested=[]
        def wait(seconds):
            self.assertGreaterEqual(seconds,0.)
            requested.append(seconds);clock.advance(seconds)
        runtime.stop_event.wait=wait
        start=clock()
        runtime.run(max_wall_seconds=.05)
        self.assertEqual(runtime.steps,5)
        self.assertAlmostEqual(backend.sim_time,.05)
        self.assertLessEqual(backend.sim_time,clock()-start+backend.timestep)
        self.assertTrue(any(seconds==0 for seconds in requested))
        self.assertTrue(any(seconds>0 for seconds in requested))
        self.assertEqual(backend.timestep,.01)

    def test_reduced_rtf_is_paced_against_same_wall_origin(self):
        clock=Clock();clock.now=0.;backend=FakeBackend();runtime=PlatformRuntime(backend,clock=clock)
        runtime.stop_event.wait=lambda seconds:clock.advance(seconds)
        runtime.run(max_wall_seconds=.1,real_time_factor=.5)
        self.assertAlmostEqual(backend.sim_time,.05)
        self.assertEqual(runtime.steps,5)


if __name__=='__main__':unittest.main()
