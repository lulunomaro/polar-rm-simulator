"""CPU fault/identity tests use an explicit fake renderer, never qualification pixels."""
import base64
import copy
import threading
import time
import unittest
import numpy as np
from .backend import MuJoCoBackend
from .camera import CameraProvider
from .control import Rejected
from .runtime import PlatformRuntime
from .test_control import Clock
from .test_runtime import TestRegistry

class FakeRenderer:
    def __init__(self,model,profile):self.profile=profile;self.thread=threading.get_ident()
    def render(self,cap):
        if threading.get_ident()!=self.thread:raise RuntimeError('GL thread migration')
        p=self.profile;return np.full((p.height,p.width,3),30 if cap.robot_id.startswith('red') else 190,dtype=np.uint8)
    def close(self):
        if threading.get_ident()!=self.thread:raise RuntimeError('GL close thread migration')

class CameraTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.backend=MuJoCoBackend(camera=True)
        self.provider=CameraProvider(self.backend._sim,clock=self.clock,renderer_factory=FakeRenderer,total_fps=15)
        self.runtime=PlatformRuntime(self.backend,clock=self.clock,camera=self.provider)
        self.p=self.runtime.control;self.a=self.p.open_session('operator')['token'];self.b=self.p.open_session('operator')['token'];self.o=self.p.open_session('spectator')['token']
    def tearDown(self):
        self.runtime.close();self.provider.wait_closed()
    def tick(self,dt=.1):self.clock.advance(dt);self.runtime.step_once()
    def until(self,predicate,seconds=3):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            if predicate():return
            time.sleep(.005)
        self.fail('Timed out')
    def rendered(self,n=1):self.until(lambda:self.provider.rendered>=n)
    def test_three_sessions_two_robots_and_spectator_no_lease(self):
        self.runtime.watch(self.a,'red_sentry');self.runtime.watch(self.b,'blue_sentry');self.runtime.watch(self.o,'red_sentry')
        self.tick();self.rendered();self.tick();self.rendered(2)
        fa,fb,fo=[self.runtime.frame(t) for t in (self.a,self.b,self.o)]
        self.assertEqual([f['robot_id'] for f in (fa,fb,fo)],['red_sentry','blue_sentry','red_sentry'])
        self.assertTrue(all(f['available'] for f in (fa,fb,fo)));self.assertEqual(fa['frame_seq'],fo['frame_seq'])
        self.assertNotEqual(fa['image']['data_base64'],fb['image']['data_base64'])
        with self.assertRaises(Rejected):self.p.claim(self.o,'red_sentry',['motion'])
        self.assertTrue(all(l['owner'] is None for row in self.p.snapshot()['leases'].values() for l in row.values()))
    def test_switch_watch_and_repeat_watch_require_new_capture(self):
        first=self.runtime.watch(self.a,'red_sentry');self.tick();self.rendered()
        self.assertTrue(self.runtime.frame(self.a)['available'])
        second=self.runtime.watch(self.a,'red_sentry');self.assertGreater(second['watch_epoch'],first['watch_epoch'])
        self.assertFalse(self.runtime.frame(self.a)['available'])
        self.runtime.watch(self.a,'blue_sentry');self.assertFalse(self.runtime.frame(self.a)['available'])
        self.tick();self.rendered(2);self.assertEqual(self.runtime.frame(self.a)['robot_id'],'blue_sentry')
    def test_clear_watch_returns_no_image_or_old_identity(self):
        self.runtime.watch(self.a,'red_sentry');self.tick();self.rendered();self.runtime.watch(self.a,None)
        frame=self.runtime.frame(self.a);self.assertEqual(frame['reason'],'not_watching');self.assertIsNone(frame['robot_id']);self.assertNotIn('image',frame)
    def test_expired_frame_never_restamped(self):
        self.runtime.watch(self.a,'red_sentry');self.tick();self.rendered();first=self.runtime.frame(self.a)
        self.clock.advance(2.6);late=self.runtime.frame(self.a)
        self.assertFalse(late['available']);self.assertEqual(late['reason'],'camera_expired');self.assertNotIn('image',late)
        self.assertEqual(first['capture_wall_monotonic'],self.clock()-2.6)
    def test_episode_change_rejects_all_old_caches(self):
        self.runtime.watch(self.a,'red_sentry');self.tick();self.rendered();old=self.runtime.frame(self.a)
        self.backend._sim.reset();self.runtime.step_once();frame=self.runtime.frame(self.a)
        self.assertFalse(frame['available']);self.assertNotEqual(old['episode'],frame['episode'])
    def test_stop_clears_available_frames(self):
        self.runtime.watch(self.a,'red_sentry');self.tick();self.rendered();self.runtime.request_stop()
        frame=self.runtime.frame(self.a);self.assertFalse(frame['available']);self.assertEqual(frame['reason'],'runtime_stopped');self.assertEqual(self.provider.status()['cached'],0)
    def test_own_exposure_pose_and_calibration_are_copy_stable(self):
        sim=self.backend._sim;rid='red_sentry';self.runtime.watch(self.a,rid)
        q=sim.data.qpos[sim.qindices[rid]].copy();v=sim.data.qvel[sim.vindices[rid]].copy();self.tick();self.rendered()
        frame=self.runtime.frame(self.a)
        self.assertEqual(frame['source'],'operator_camera_display_v1')
        self.assertNotIn('own_qpos_at_capture',frame);self.assertNotIn('own_odom_at_capture',frame)
        watch=self.p.watch_sample(self.a);key=('watch',watch['session_id'],watch['watch_epoch'])
        sensor=self.provider.sensor_camera(rid,self.backend.episode,key,self.backend.sim_time,.2)
        np.testing.assert_array_equal(sensor['own_qpos_at_capture'],q);np.testing.assert_array_equal(sensor['own_qvel_at_capture'],v)
        self.assertEqual(frame['image']['width'],1440);self.assertEqual(frame['image']['height'],1080)
        ext=frame['calibration']['extrinsics'];self.assertEqual(ext['translation_m'],[.24,0.,.06])
        self.assertIn(rid,ext['calibration_id']);self.assertTrue(frame['full_frame']);self.assertFalse(frame['algorithm_input'])
        self.assertLessEqual(frame['capture_sim_time'],sim.time)
    def test_wrong_consumer_robot_episode_and_stale_algorithm_denied(self):
        self.runtime.watch(self.a,'red_sentry');self.tick();self.rendered();watch=self.p.watch_sample(self.a)
        key=('watch',watch['session_id'],watch['watch_epoch'])
        for rid,ep,c in [('blue_sentry',0,key),('red_sentry',1,key),('red_sentry',0,('adapter','red_sentry','aim','x',1))]:
            self.assertFalse(self.provider.sensor_camera(rid,ep,c,self.backend.sim_time,.2)['available'])
        sensor=self.provider.sensor_camera('red_sentry',0,key,self.backend.sim_time,.2)
        self.assertTrue(sensor['available']);self.assertEqual(sensor['image']['encoding'],'rgb8')
        self.assertNotIn('robots',sensor);self.assertNotIn('model',sensor);self.assertNotIn('targets',sensor)
        self.clock.advance(.21);self.assertFalse(self.provider.sensor_camera('red_sentry',0,key,self.backend.sim_time,.2)['available'])
    def test_algorithm_receives_only_own_raw_capture_with_binding_generation(self):
        class Registry(TestRegistry):
            def get(self,name):
                result=super().get(name)
                if name=='aim':result.descriptor['required_sensors']=['camera']
                return result
        registry=Registry();self.runtime.registry=registry
        # This two-tick handoff test advances physics by .002s per tick. The
        # production .05s polling period cannot elapse by sleeping without
        # authority ticks. Use a one-physics-tick period for this fixture only;
        # the algorithm .2s freshness/deadline remains unchanged.
        self.runtime.observation_period=self.backend.timestep
        epochs=self.p.claim(self.a,'red_sentry',['gimbal'])['lease_epochs']
        binding=self.runtime.bind(self.a,'red_sentry','aim',epochs,'aim',{})
        # Keep the fake camera wall clock fixed on tick two so a concurrent
        # second capture cannot replace the intentionally inspected first frame.
        self.tick();self.rendered();self.tick(dt=0.);self.until(lambda:bool(registry.seen))
        observation=registry.seen[0];camera=observation['sensors']['camera']
        self.assertEqual(observation['robot_id'],'red_sentry');self.assertEqual(camera['image']['encoding'],'rgb8')
        self.assertEqual(camera['frame_id'],1);self.assertEqual(observation['binding_epoch'],binding['binding_epoch'])
        self.assertNotIn('robots',observation);self.assertNotIn('targets',observation);self.assertNotIn('calibration',observation)
        self.assertEqual(camera['own_qpos_at_capture'],[0.,0.,0.,0.,0.])
        self.p.unbind(self.a,'red_sentry','aim',epochs)
        rebound=self.runtime.bind(self.a,'red_sentry','aim',epochs,'aim',{})
        identity=('adapter','red_sentry','aim',self.p.watch_sample(self.a)['session_id'],rebound['binding_epoch'])
        self.assertFalse(self.provider.sensor_camera('red_sentry',0,identity,self.backend.sim_time,.2)['available'])

    def test_subscription_does_not_renew_lease(self):
        epochs=self.p.claim(self.a,'red_sentry',['motion'])['lease_epochs'];self.runtime.watch(self.a,'blue_sentry')
        self.clock.advance(1.01);self.runtime.watch(self.a,'red_sentry')
        self.assertIsNone(self.p.snapshot()['leases']['red_sentry']['motion']['owner'])
    def test_capacity_and_unknown_robot_fail_without_control_change(self):
        self.provider.max_views=1;self.runtime.watch(self.a,'red_sentry')
        with self.assertRaises(Rejected):self.runtime.watch(self.b,'blue_sentry')
        with self.assertRaises(Rejected):self.runtime.watch(self.b,'missing')
        self.assertIsNone(self.p.watch_sample(self.b)['robot_id'])
        self.runtime.watch(self.a,'blue_sentry');self.assertEqual(self.p.watch_sample(self.a)['robot_id'],'blue_sentry')
    def test_display_uses_judge_actual_values(self):
        sim=self.backend._sim;r=sim.judge.robots['red_sentry'];r.hp=312;r.ammo=321;r.heat=51
        value=self.backend.display_snapshot();row=next(x for x in value['robots'] if x['robot_id']=='red_sentry')
        self.assertEqual([row[k] for k in ('hp','max_hp','ammo','heat','heat_max')],[312.,400.,321,51.,260.])
        self.assertEqual(value['remaining_seconds'],300.);self.assertEqual(value['victory_points'],sim.judge.vp)
        self.assertEqual(value['source'],'simulator_truth_display_only');self.assertFalse(value['algorithm_input'])
    def test_snapshot_copy_only_authority_thread(self):
        self.runtime.watch(self.a,'red_sentry');self.tick();errors=[]
        def wrong():
            try:self.provider.capture_from_authority(self.backend._sim,{})
            except Exception as exc:errors.append(type(exc).__name__)
        t=threading.Thread(target=wrong);t.start();t.join();self.assertEqual(errors,['RuntimeError'])
    def test_no_gl_keeps_camera_explicitly_unavailable(self):
        r=PlatformRuntime(MuJoCoBackend());token=r.control.open_session('spectator')['token']
        try:r.watch(token,'red_sentry');r.step_once();self.assertEqual(r.frame(token)['reason'],'no_gl_stage')
        finally:r.close()

class BlockingCameraTests(unittest.TestCase):
    def test_display_stall_does_not_hold_sensor_or_refresh_deadline(self):
        entered=threading.Event();release=threading.Event();clock=Clock()
        class SlowDisplay(CameraProvider):
            def _encode_display(self,cap,rgb):
                entered.set();release.wait(3)
                return super()._encode_display(cap,rgb)
        backend=MuJoCoBackend(camera=True)
        provider=SlowDisplay(backend._sim,clock=clock,renderer_factory=FakeRenderer,total_fps=15)
        key=('adapter','red_sentry','aim','fixture',1)
        try:
            provider.capture_from_authority(backend._sim,{'red_sentry':{key}})
            self.assertTrue(entered.wait(2))
            packet=provider.sensor_packet('red_sentry',0,key,backend.sim_time,.08)
            self.assertTrue(packet['camera']['available'])
            self.assertEqual(packet['budget']['capture_wall'],1000.)
            self.assertAlmostEqual(packet['budget']['wall_deadline'],1000.08)
            self.assertFalse(provider.display_frame('red_sentry',0,key,1)['available'])
            clock.advance(.081)
            self.assertEqual(provider.sensor_packet('red_sentry',0,key,backend.sim_time,.08)['camera']['reason'],'camera_expired')
            release.set()
            deadline=time.monotonic()+2
            while provider.rendered==0 and time.monotonic()<deadline:time.sleep(.005)
            display=provider.display_frame('red_sentry',0,key,1)
            self.assertTrue(display['available']);self.assertEqual(display['capture_wall_monotonic'],1000.)
            self.assertFalse(provider.sensor_packet('red_sentry',0,key,backend.sim_time,.08)['camera']['available'])
        finally:
            release.set();provider.stop();self.assertTrue(provider.wait_closed());backend.close()

    def test_blocked_display_has_latest_bounded_queue_and_no_rebind_leak(self):
        entered=threading.Event();release=threading.Event();clock=Clock()
        class SlowDisplay(CameraProvider):
            def _encode_display(self,cap,rgb):
                entered.set();release.wait(3)
                return super()._encode_display(cap,rgb)
        backend=MuJoCoBackend(camera=True)
        provider=SlowDisplay(backend._sim,clock=clock,renderer_factory=FakeRenderer,total_fps=15,max_views=1)
        old=('adapter','red_sentry','aim','fixture',1);new=(*old[:-1],2)
        try:
            provider.capture_from_authority(backend._sim,{'red_sentry':{old}})
            self.assertTrue(entered.wait(2))
            for i in range(2,6):
                clock.advance(.07);provider.capture_from_authority(backend._sim,{'red_sentry':{new}})
                deadline=time.monotonic()+2
                while provider.raw_published<i and time.monotonic()<deadline:time.sleep(.005)
                self.assertEqual(provider.raw_published,i)
            status=provider.status()
            self.assertLessEqual(status['display_pending'],1)
            self.assertLessEqual(status['max_display_pending_seen'],1)
            self.assertGreaterEqual(status['display_dropped'],2)
            self.assertFalse(provider.sensor_camera('red_sentry',0,old,backend.sim_time,.08)['available'])
            self.assertTrue(provider.sensor_camera('red_sentry',0,new,backend.sim_time,.08)['available'])
            release.set();deadline=time.monotonic()+2
            while provider.rendered==0 and time.monotonic()<deadline:time.sleep(.005)
            display=provider.display_frame('red_sentry',0,new,1)
            self.assertTrue(display['available']);self.assertEqual(display['frame_seq'],5)
            self.assertFalse(provider.display_frame('red_sentry',0,old,1)['available'])
        finally:
            release.set();provider.stop();self.assertTrue(provider.wait_closed());backend.close()

    def test_display_codec_failure_is_explicit_and_keeps_sensor_usable(self):
        class BrokenDisplay(CameraProvider):
            def _encode_display(self,cap,rgb):raise ValueError('fixture codec failure')
        backend=MuJoCoBackend(camera=True)
        provider=BrokenDisplay(backend._sim,renderer_factory=FakeRenderer)
        key=('fixture',1)
        try:
            provider.capture_from_authority(backend._sim,{'red_sentry':{key}})
            deadline=time.monotonic()+2
            while provider.display_error is None and time.monotonic()<deadline:time.sleep(.005)
            self.assertEqual(provider.display_error,'ValueError');self.assertIsNone(provider.error)
            self.assertTrue(provider.sensor_camera('red_sentry',0,key,backend.sim_time,.08)['available'])
            self.assertEqual(provider.display_frame('red_sentry',0,key,1)['reason'],'display_error:ValueError')
        finally:provider.stop();self.assertTrue(provider.wait_closed());backend.close()

    def test_render_stall_never_blocks_release_physics_or_shutdown(self):
        entered=threading.Event();release=threading.Event();closed=[]
        class Blocked(FakeRenderer):
            def render(self,cap):entered.set();release.wait(4);return super().render(cap)
            def close(self):super().close();closed.append(threading.get_ident())
        backend=MuJoCoBackend(camera=True);provider=CameraProvider(backend._sim,renderer_factory=Blocked,total_fps=15)
        runtime=PlatformRuntime(backend,camera=provider);p=runtime.control;tkn=p.open_session('operator')['token']
        runtime.watch(tkn,'red_sentry');epochs=p.claim(tkn,'red_sentry',['motion'])['lease_epochs']
        p.control(tkn,'red_sentry','motion',epochs['motion'],0,dict(frame='base_link',vx_mps=.3,vy_mps=0.,wz_rps=0.),.2)
        authority=threading.Thread(target=runtime.run,kwargs={'max_wall_seconds':5});authority.start()
        try:
            self.assertTrue(entered.wait(2));before=runtime.steps;start=time.monotonic();p.release(tkn,'red_sentry',epochs)
            self.assertLess(time.monotonic()-start,.15);time.sleep(.08);self.assertGreater(runtime.steps,before)
            # Release also revokes operator HUD/control evidence. Actual neutral
            # consumption is inspected only through the spectator audit plane.
            snap=runtime.snapshot(tkn);self.assertNotIn('red_sentry',snap['applied_targets'])
            audit=p.open_session('spectator')['token'];self.assertIsNone(runtime.snapshot(audit)['applied_targets']['red_sentry']['motion'])
            start=time.monotonic();runtime.request_stop();authority.join(1);self.assertFalse(authority.is_alive());self.assertLess(time.monotonic()-start,1)
            self.assertFalse(runtime.frame(tkn)['available']);self.assertLessEqual(provider.status()['pending'],6)
        finally:
            release.set();runtime.request_stop();authority.join(2);self.assertTrue(provider.wait_closed(2))
        self.assertEqual(len(closed),1);self.assertNotEqual(closed[0],backend._authority)
    def test_renderer_error_is_camera_only_failure(self):
        class Broken(FakeRenderer):
            def render(self,cap):raise RuntimeError('intentional unit fixture failure')
        b=MuJoCoBackend(camera=True);p=CameraProvider(b._sim,renderer_factory=Broken);r=PlatformRuntime(b,camera=p)
        t=r.control.open_session('spectator')['token'];r.watch(t,'red_sentry');r.step_once()
        try:
            deadline=time.monotonic()+2
            while p.error is None and time.monotonic()<deadline:time.sleep(.01)
            self.assertEqual(p.error,'RuntimeError');before=b.sim_time;r.step_once();self.assertGreater(b.sim_time,before)
            self.assertFalse(r.frame(t)['available']);self.assertIsNone(r.error)
        finally:r.close();p.wait_closed()

if __name__=='__main__':unittest.main()
