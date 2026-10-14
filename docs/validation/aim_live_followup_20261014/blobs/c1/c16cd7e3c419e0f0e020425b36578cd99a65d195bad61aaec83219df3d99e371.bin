"""Selection transaction and real-MuJoCo CPU regressions. No hardware transport.

Source tests explicitly use a named test double to probe arbitration races;
these tests alone do not qualify native detector execution or Qt behavior.
"""
import json
import threading
import unittest

from .protocol import ControlGate, OperatorInput, ModeRequest, ROBOT_IDS
from .server import BridgeState
from .test_protocol import Clock
from . import test_protocol as http_fixture
from . import test_runtime as runtime_fixture
from . import test_source_runtime as source_fixture


def selection(gate, requested='blue_hero', selection_id=0, **changes):
    message=dict(session_id=gate.session_id,epoch=gate.epoch,robot_id=gate.robot_id,
        selection_id=selection_id,requested_robot_id=requested,sent_at_ms=gate.wall()*1000)
    message.update(changes)
    return message


def control(gate, seq=1, **changes):
    message=dict(session_id=gate.session_id,epoch=gate.epoch,robot_id=gate.robot_id,
        seq=seq,sent_at_ms=gate.wall()*1000,focus=True,deadman=True,fire=False,
        vx_mps=0.,vy_mps=0.,yaw_rate_rps=0.,pitch_rate_rps=0.)
    message.update(changes)
    return message


class SelectionGateTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock()
        self.g=ControlGate(wall=self.clock,monotonic=self.clock,session_id='selection-unit')
        self.g.configure_selection(ROBOT_IDS)
        self.state=BridgeState(self.g)
    def test_selection_transaction_neutralizes_and_preserves_session(self):
        self.g.accept(control(self.g,fire=True,vx_mps=1.,
            mode_request=dict(spin_enabled=True,spin_direction='cw',spin_speed_dps=120,
                              chassis_follow='free',spin_origin='on_hit'),
            mouse_angle=dict(generation=7,yaw_total_rad=.2,pitch_total_rad=.1),
            aim_request=dict(enabled=True,hold=True,fov_degrees=85,
                             circle_radius_x_norm=.25,circle_radius_y_norm=.25)))
        self.g.consume_mouse_angle()
        ack=self.state.select_robot(selection(self.g))
        self.assertTrue(ack['accepted']);self.assertEqual(ack['reason'],'robot_selected')
        self.assertEqual((ack['session_id'],ack['previous_epoch'],ack['epoch']),('selection-unit',0,1))
        self.assertEqual((ack['previous_robot_id'],ack['robot_id']),('red_infantry','blue_hero'))
        self.assertEqual(self.g.sample(),OperatorInput());self.assertEqual(self.g.requested_mode,ModeRequest())
        self.assertFalse(self.g.active_mode.spin_enabled);self.assertEqual(self.g.last_seq,-1)
        self.assertEqual(self.g.mouse_consumed,(0.,0.));self.assertEqual(self.g.mouse_revoked_generation,7)
        self.assertTrue(ack['requires_rearm']);self.assertFalse(ack['match_reset'])
        self.assertTrue(self.g.selection_requires_release)
    def test_new_identity_requires_release_before_active_input(self):
        self.state.select_robot(selection(self.g))
        ack=self.g.accept(control(self.g,fire=True))
        self.assertFalse(ack['accepted']);self.assertEqual(ack['reason'],'selection_release_required')
        self.assertTrue(self.g.accept(control(self.g,seq=2,deadman=False))['accepted'])
        self.assertFalse(self.g.selection_requires_release)
        self.assertEqual(self.g.sample(),OperatorInput())
        self.assertTrue(self.g.accept(control(self.g,seq=3))['accepted'])
    def test_invalid_release_does_not_unlock_barrier(self):
        self.state.select_robot(selection(self.g))
        self.assertFalse(self.g.accept(control(self.g,deadman=False,fire='false'))['accepted'])
        self.assertTrue(self.g.selection_requires_release)
    def test_old_control_and_old_mouse_generation_cannot_replay(self):
        old=control(self.g,mouse_angle=dict(generation=9,yaw_total_rad=.7,pitch_total_rad=.1))
        self.assertTrue(self.g.accept(old)['accepted'])
        self.state.select_robot(selection(self.g))
        self.assertEqual(self.g.accept(old)['reason'],'epoch_mismatch')
        self.g.accept(control(self.g,seq=1,deadman=False))
        self.assertEqual(self.g.accept(control(self.g,seq=2,mouse_angle=old['mouse_angle']))['reason'],'revoked_mouse_generation')
        self.assertTrue(self.g.accept(control(self.g,seq=3,mouse_angle=dict(generation=10,yaw_total_rad=0.,pitch_total_rad=0.)))['accepted'])
        self.assertEqual(self.g.consume_mouse_angle(),(0.,0.))
    def test_replay_never_increments_epoch_twice(self):
        request=selection(self.g)
        self.assertTrue(self.state.select_robot(request)['accepted'])
        ack=self.state.select_robot(request)
        self.assertFalse(ack['accepted']);self.assertEqual(ack['reason'],'epoch_mismatch')
        self.assertEqual(self.g.epoch,1)
        ack=self.state.select_robot(selection(self.g,selection_id=0))
        self.assertFalse(ack['accepted']);self.assertEqual(ack['reason'],'selection_out_of_order')
        self.assertEqual(self.g.epoch,1)
    def test_same_robot_is_explicit_rebind_and_also_requires_release(self):
        ack=self.state.select_robot(selection(self.g,requested=self.g.robot_id))
        self.assertTrue(ack['accepted']);self.assertEqual(self.g.epoch,1)
        self.assertTrue(self.g.selection_requires_release)
    def test_invalid_requests_neutralize_without_switching(self):
        cases=[None,[],{},selection(self.g,extra=True),
            selection(self.g,session_id='old'),selection(self.g,epoch=True),selection(self.g,epoch=1),
            selection(self.g,robot_id='blue_sentry'),selection(self.g,selection_id=True),
            selection(self.g,selection_id=-1),selection(self.g,selection_id=2**53),
            selection(self.g,selection_id=1.5),selection(self.g,sent_at_ms=float('nan')),
            selection(self.g,sent_at_ms=10**1000),selection(self.g,sent_at_ms=self.clock()*1000-250),
            selection(self.g,sent_at_ms=self.clock()*1000+51),selection(self.g,requested='red_engineer'),
            selection(self.g,requested=['blue_hero']),selection(self.g,requested='RED_HERO')]
        for request in cases:
            with self.subTest(request=str(request)[:160]):
                self.g.last_seq=-1
                self.assertTrue(self.g.accept(control(self.g,fire=True,vx_mps=1.))['accepted'])
                ack=self.state.select_robot(request)
                self.assertFalse(ack['accepted']);self.assertEqual(self.g.epoch,0)
                self.assertEqual(self.g.robot_id,'red_infantry');self.assertEqual(self.g.last_selection_id,-1)
                self.assertEqual(self.g.sample(),OperatorInput())
    def test_unregistered_or_missing_or_disabled_robot_is_rejected(self):
        self.g.selection_robots=()
        self.assertEqual(self.state.select_robot(selection(self.g))['reason'],'selection_unavailable')
        self.g.configure_selection(('red_infantry',))
        self.assertEqual(self.state.select_robot(selection(self.g))['reason'],'unknown_selection_robot')
        self.g.disable()
        self.assertEqual(self.state.select_robot(selection(self.g,requested='red_infantry'))['reason'],'simulation_stopped')
    def test_all_six_roles_have_truthful_capabilities(self):
        self.g.source_autoaim_robots=('red_sentry',);self.g.source_autoaim_ready=True
        profiles=self.g.session()['robot_profiles']
        self.assertEqual({r['robot_id'] for r in profiles},set(ROBOT_IDS))
        self.assertEqual([r['robot_id'] for r in profiles if r['capabilities']['automatic_targeting']],['red_sentry'])
        for index,rid in enumerate(ROBOT_IDS):
            self.assertTrue(self.state.select_robot(selection(self.g,rid,index))['accepted'])
            s=self.g.session()
            self.assertEqual(s['capabilities']['automatic_targeting'],rid=='red_sentry')
            self.assertEqual(s['last_selection_id'],index)
            self.assertFalse(s['capabilities']['power_guard'])
            self.assertEqual(s['first_person_camera'],rid+'__aim')
    def test_source_error_removes_available_capability_from_profiles(self):
        self.g.source_autoaim_robots=('red_sentry',);self.g.source_autoaim_ready=False
        self.assertFalse(any(p['capabilities']['automatic_targeting'] for p in self.g.session()['robot_profiles']))
    def test_cached_measurements_and_camera_are_cleared_atomically(self):
        self.state.publish(dict(session_id=self.g.session_id,epoch=0,robot_id=self.g.robot_id,
            phase='running',own={'hp':123},own_damage={'total_damage':20}),b'old-camera',
            dict(epoch=0,robot_id=self.g.robot_id,frame_seq=8))
        self.state.select_robot(selection(self.g))
        t=self.state.snapshot()
        self.assertFalse(t['telemetry_available']);self.assertIsNone(t['own_damage'])
        self.assertIsNone(t['own']);self.assertIsNone(self.state.frame);self.assertEqual(self.state.frame_meta,{})
    def test_concurrent_selection_has_one_winner(self):
        request=selection(self.g)
        results=[];barrier=threading.Barrier(3)
        def work():
            barrier.wait();results.append(self.state.select_robot(request))
        threads=[threading.Thread(target=work) for _ in range(2)]
        for t in threads:t.start()
        barrier.wait()
        for t in threads:t.join()
        self.assertEqual(sum(r['accepted'] for r in results),1)
        self.assertEqual(self.g.epoch,1);self.assertEqual(self.g.sample(),OperatorInput())


class SelectionHTTPTests(unittest.TestCase):
    setUp=http_fixture.HTTPTests.setUp
    tearDown=http_fixture.HTTPTests.tearDown
    request=http_fixture.HTTPTests.request
    def post(self,message,headers=None):
        return self.request('POST','/select_robot',json.dumps(message),headers or {'Content-Type':'application/json'})
    def test_http_selection_then_new_session_and_not_ready_data(self):
        self.state.gate.configure_selection(ROBOT_IDS)
        old=selection(self.state.gate)
        code,data,_=self.post(old);ack=json.loads(data)
        self.assertEqual(code,200);self.assertTrue(ack['accepted'])
        s=json.loads(self.request('GET','/session')[1])
        self.assertEqual(s['robot_id'],'blue_hero');self.assertEqual(s['last_selection_id'],0)
        self.assertTrue(s['capabilities']['robot_selection']);self.assertEqual(s['endpoints']['select_robot'],'/select_robot')
        self.assertFalse(json.loads(self.request('GET','/telemetry')[1])['telemetry_available'])
        self.assertEqual(self.request('GET','/frame.jpg')[0],503)
        self.assertEqual(self.post(old)[0],409)
    def test_http_old_control_rejected_after_selection(self):
        g=self.state.gate;g.configure_selection(ROBOT_IDS);old=control(g,fire=True)
        self.post(selection(g))
        code,data,_=self.request('POST','/control',json.dumps(old),{'Content-Type':'application/json'})
        self.assertEqual(code,409);self.assertEqual(json.loads(data)['reason'],'epoch_mismatch')
        self.assertFalse(g.sample().fire)
    def test_selection_keeps_loopback_origin_and_host_guards(self):
        g=self.state.gate;g.configure_selection(ROBOT_IDS)
        for hdr in ({'Host':'evil.invalid'},{'Origin':'http://evil.invalid'}):
            self.assertEqual(self.post(selection(g),dict(hdr,**{'Content-Type':'application/json'}))[0],403)
        self.assertEqual(g.epoch,0)
    def test_malformed_selection_clears_active_input(self):
        g=self.state.gate;g.configure_selection(ROBOT_IDS)
        for body,headers,status in [('{}',{},415),('{"x":NaN}',{'Content-Type':'application/json'},400),
                                     ('x'*4097,{'Content-Type':'application/json'},413)]:
            g.last_seq=-1;g.accept(control(g,fire=True))
            self.assertEqual(self.request('POST','/select_robot',body,headers)[0],status)
            self.assertEqual(g.sample(),OperatorInput());self.assertEqual(g.epoch,0)


class SelectionRuntimeTests(unittest.TestCase):
    setUp=runtime_fixture.RuntimeTests.setUp
    tearDown=runtime_fixture.RuntimeTests.tearDown
    send=runtime_fixture.RuntimeTests.send
    tick=runtime_fixture.RuntimeTests.tick
    def test_switch_after_manual_fire_spin_neutralizes_both_without_resetting_world(self):
        from .test_modes import mode
        r=self.runtime;g=self.state.gate
        self.send(fire=True,vx_mps=1.,mode_request=mode());self.tick(2)
        before_time=r.sim.time;before_hp={rid:j.hp for rid,j in r.sim.judge.robots.items()}
        before_episode=r.sim.episode
        ack=self.state.select_robot(selection(g,'blue_hero'))
        self.assertTrue(ack['accepted']);self.tick();r._publish()
        for rid in ('red_infantry','blue_hero'):
            c=r.commands[rid]
            self.assertEqual((c.force_x,c.force_y,c.yaw_torque,c.fire),(0.,0.,0.,False))
        self.assertGreater(r.sim.time,before_time);self.assertEqual(r.sim.episode,before_episode)
        self.assertEqual(before_hp,{rid:j.hp for rid,j in r.sim.judge.robots.items()})
        t=self.state.snapshot();self.assertEqual(t['own']['role'],'hero')
        self.assertFalse(t['operator_modes']['effective']['spin_enabled']);self.assertFalse(t['camera']['available'])
    def test_damage_ledger_preserved_and_new_identity_provides_fresh_baseline(self):
        r=self.runtime;g=self.state.gate;j=r.sim.judge
        self.tick()
        self.assertTrue(j.fire('red_sentry','prior-hit',r.sim.time))
        self.assertTrue(j.apply_hit('prior-hit','red_sentry','blue_hero','front',20.,r.sim.time))
        before={rid:dict(value) for rid,value in j.projectile_damage.items()}
        self.state.select_robot(selection(g,'blue_hero'));self.tick();r._publish()
        self.assertEqual(j.projectile_damage,before)
        damage=self.state.snapshot()['own_damage']
        self.assertEqual((damage['robot_id'],damage['epoch'],damage['total_damage']),('blue_hero',1,20.))
        self.assertFalse(self.state.snapshot()['operator_modes']['effective']['spin_enabled'])
        self.state.select_robot(selection(g,'red_infantry',1));self.tick();r._publish()
        self.assertEqual(self.state.snapshot()['own_damage']['total_damage'],0.)
        self.assertEqual(j.projectile_damage,before)
    def test_old_camera_metadata_never_claims_selected_camera_ready(self):
        r=self.runtime;g=self.state.gate;self.tick()
        r.last_operator_frame=dict(epoch=0,robot_id=g.robot_id,frame_seq=44,width=320,height=240)
        self.state.select_robot(selection(g));self.tick();r._publish()
        camera=self.state.snapshot()['camera']
        self.assertFalse(camera['available']);self.assertEqual(camera['robot_id'],'blue_hero')
        self.assertNotIn('frame_seq',camera)
    def test_robot_roster_is_validated_against_actual_camera(self):
        from unittest.mock import patch
        with patch('rm_match.operator.runtime.mujoco.mj_name2id',return_value=-1):
            with self.assertRaisesRegex(ValueError,'Invalid simulation robot binding'):
                self.runtime._configure_selection()
    def test_selected_robot_has_no_autonomous_motion_before_fresh_rearm(self):
        g=self.state.gate;self.tick()
        for index,rid in enumerate(ROBOT_IDS):
            self.state.select_robot(selection(g,rid,index));self.tick(5)
            c=self.runtime.commands[rid]
            self.assertEqual((c.force_x,c.force_y,c.yaw_torque,c.fire),(0.,0.,0.,False))


class SelectionSourceRaceTests(unittest.TestCase):
    setUp=source_fixture.SourceArbitrationTests.setUp
    tearDown=source_fixture.SourceArbitrationTests.tearDown
    send=source_fixture.SourceArbitrationTests.send
    request=None
    def test_http_thread_switch_during_source_inference_discards_old_result(self):
        g=self.gate;r=self.runtime
        result=[]
        def hook():
            thread=threading.Thread(target=lambda:result.append(self.state.select_robot(selection(g,'blue_sentry'))))
            thread.start();thread.join(timeout=.5)
            self.assertFalse(thread.is_alive(),'HTTP selection waited on inference/physics lock')
        r.source.hook=hook;r.step_once()
        self.assertTrue(result[0]['accepted']);self.assertEqual(g.robot_id,'blue_sentry')
        self.assertFalse(r.autoaim_status['active']);self.assertFalse(r.autoaim_status['available'])
        self.assertEqual(r.autoaim_status['reason'],'unsupported_robot')
        self.assertNotAlmostEqual(r.commands['blue_sentry'].gimbal_yaw,.4)
        self.assertFalse(r.commands['blue_sentry'].fire);self.assertGreater(r.source_results_discarded,0)
    def test_unsupported_role_never_calls_source_or_inherits_source_capabilities(self):
        r=self.runtime;g=self.gate
        self.state.select_robot(selection(g,'blue_sentry'))
        g.accept(control(g,deadman=False));g.accept(control(g,seq=2))
        def prohibited():raise AssertionError('Unsupported robot reached source detector adapter')
        r.source.hook=prohibited;r.step_once()
        self.assertEqual(r.autoaim_status['reason'],'unsupported_robot')
        self.assertFalse(g.session()['capabilities']['automatic_targeting'])
        self.assertFalse(r.commands['blue_sentry'].fire)
    def test_return_to_supported_robot_requires_new_release_and_explicit_aim(self):
        r=self.runtime;g=self.gate
        self.state.select_robot(selection(g,'blue_sentry'));r.step_once()
        self.state.select_robot(selection(g,'red_sentry',1));r.step_once()
        self.assertTrue(g.session()['capabilities']['automatic_targeting'])
        self.assertEqual(g.sample(),OperatorInput());self.assertTrue(g.selection_requires_release)
        self.assertFalse(r.autoaim_status['active']);self.assertFalse(r.commands['red_sentry'].fire)


if __name__=='__main__':unittest.main()
