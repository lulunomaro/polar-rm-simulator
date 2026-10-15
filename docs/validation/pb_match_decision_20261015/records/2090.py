"""Cheap exposure identity uses real provider cache gates; no GL or pixels copied."""
from dataclasses import replace
import threading
import unittest
from .camera import CameraProvider,Capture


class ForbiddenPayload:
    def __deepcopy__(self,memo):raise AssertionError('Large/private camera payload copied')
    def __getitem__(self,key):raise AssertionError('Large/private camera payload accessed')


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.provider=CameraProvider.__new__(CameraProvider)
        self.p=self.provider;self.p.lock=threading.Lock();self.p.stopped=threading.Event()
        self.now=0.;self.p.clock=lambda:self.now;self.p.ttl=2.5;self.p.error=None;self.p.episode=7
        self.rid='red_sentry';self.key=('adapter',self.rid,'aim','session',11)
        self.capture=Capture(self.rid,7,45,0.,0.,frozenset({self.key}),ForbiddenPayload(),ForbiddenPayload(),())
        self.p.cache={self.rid:dict(capture=self.capture,camera=ForbiddenPayload(),rgb=ForbiddenPayload())}
        self.p.display_cache={};self.p.display_error=None

    def identity(self,**overrides):
        params=dict(rid=self.rid,episode=7,consumer=self.key,sim_time=0.,ttl=.08);params.update(overrides)
        return self.p.sensor_identity(**params)

    def test_valid_identity_only_three_original_scalars_no_private_copy(self):
        self.assertEqual(self.identity(),(45,0.,0.))
        self.now=.02;self.assertEqual(self.identity(sim_time=.02),(45,0.,0.))
        self.assertIs(self.p.cache[self.rid]['capture'],self.capture)
        self.assertEqual(set(self.p.cache),{self.rid})

    def test_expired_and_clock_regressing_exposure_never_restamped(self):
        for wall,sim in [(.080001,.04),(-.001,0.),(.04,.080001),(.04,-.001)]:
            with self.subTest(wall=wall,sim=sim):
                self.now=wall;self.assertIsNone(self.identity(sim_time=sim))
        self.now=.08;self.assertEqual(self.identity(sim_time=.08),(45,0.,0.))
        self.assertEqual((self.capture.wall_time,self.capture.sim_time),(0.,0.))

    def test_provider_wall_limit_not_extended_by_larger_consumer_ttl(self):
        self.p.ttl=.04;self.now=.041
        self.assertIsNone(self.identity(ttl=.2))

    def test_other_robot_episode_and_binding_consumer_denied(self):
        for extra in [dict(rid='blue_sentry'),dict(episode=8),dict(consumer=('adapter',self.rid,'aim','session',12)),dict(consumer=('adapter',self.rid,'aim','other',11))]:
            with self.subTest(extra=extra):self.assertIsNone(self.identity(**extra))
        self.p.cache[self.rid]['capture']=replace(self.capture,robot_id='blue_sentry')
        self.assertIsNone(self.identity())
        self.p.cache[self.rid]['capture']=replace(self.capture,episode=6)
        self.assertIsNone(self.identity())
        self.p.episode=6;self.assertIsNone(self.identity())

    def test_missing_cache_error_and_stop_denied(self):
        self.p.cache.clear();self.assertIsNone(self.identity())
        self.p.cache[self.rid]=dict(capture=self.capture,camera=ForbiddenPayload())
        self.p.error='renderer_failure';self.assertIsNone(self.identity())
        self.p.error=None;self.p.stopped.set();self.assertIsNone(self.identity())

    def test_raw_identity_available_before_jpeg_display_and_changes_only_new_capture(self):
        self.p.display_error='jpeg_failure'
        self.assertEqual(self.identity(),(45,0.,0.))
        self.p.cache[self.rid]['capture']=replace(self.capture,frame_seq=46,wall_time=.01,sim_time=.01)
        self.now=.02
        self.assertEqual(self.identity(sim_time=.02),(46,.01,.01))
        self.assertEqual(len(self.p.cache),1);self.assertEqual(len(self.p.display_cache),0)


if __name__=='__main__':unittest.main()
