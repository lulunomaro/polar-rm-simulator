"""Pure comparison-contract/partial-IO units; no ELF, ROS, WSL or renderer."""
import copy
import hashlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import compare_native_opencv_threads as tool


def properties(cv=32):
    return dict(valid=True, core_properties_known=True, record=dict(
        properties={key:dict(status='known', value=copy.deepcopy(value), reason=None)
                    for key, value in tool.EXPECTED.items()},
        cv_num_threads=dict(status='known', value=cv, reason=None)))


def saved_fixture():
    content = bytes(4665600)
    captured = dict(own_qpos_at_capture=[.1]*5, own_qvel_at_capture=[.2]*5,
                    own_odom_at_capture=[.3]*3, own_odom_velocity_at_capture=[.4]*3)
    request = dict(robot_id='red_sentry', episode=0, binding_epoch=1, observed_seq=9,
                   frame_id=8, capture_sim_time=.476, observation_sim_time=.486,
                   own_at_capture=captured)
    return dict(request=request, content=content, sha256=hashlib.sha256(content).hexdigest())


def response():
    return dict(status='ok', runner_identity='rmcs-sim-operator-fov-v1',
                clock_time_ns=486000000, direction_frame='world', tracking=True,
                detector_executed=True)


class ComparisonTests(unittest.TestCase):
    def test_pre_registered_abba_is_fixed_and_does_not_reuse_process_or_duplicate_frame(self):
        plan = tool.plan()
        self.assertEqual(plan['sequence'], ['default','cv1','cv1','default','default','cv1','cv1','default'])
        self.assertEqual(plan['fresh_processes'], 8)
        self.assertTrue(plan['no_warm_inference'])
        self.assertFalse(plan['live_budget_or_timestamp_changes'])
        self.assertEqual(plan['offline_first_response_timeout_s'], 2.)

    def test_environment_factor_is_exact_and_parent_env_remains_unchanged(self):
        base = {tool.CV_KEY:'64', 'OMP_NUM_THREADS':'1', 'ANOTHER':'value'}
        before = dict(base)
        a = tool.case_environment(base, 'default'); b = tool.case_environment(base, 'cv1')
        self.assertNotIn(tool.CV_KEY, a); self.assertEqual(b[tool.CV_KEY], '1')
        self.assertEqual({k for k in set(a)|set(b) if a.get(k)!=b.get(k)}, {tool.CV_KEY})
        self.assertEqual(base, before)
        with self.assertRaises(ValueError): tool.case_environment(base, 'cv2')

    def test_effective_cv_and_every_compiled_property_must_match_not_only_requested_env(self):
        tool.check_properties(properties(), 'default'); tool.check_properties(properties(1), 'cv1')
        for variant, row in [('cv1', properties()), ('default', properties(1))]:
            with self.subTest(variant=variant), self.assertRaises(ValueError):tool.check_properties(row, variant)
        for key in tool.PROPERTIES:
            row = properties(1); row['record']['properties'][key]['status'] = 'unknown'
            with self.subTest(key=key), self.assertRaises(ValueError):tool.check_properties(row, 'cv1')
        for key, value in [('num_streams',2),('inference_num_threads',1),('execution_devices',['GPU']),
                           ('inference_precision','bf16'),('enable_cpu_pinning',1),('performance_mode','THROUGHPUT')]:
            row = properties(1); row['record']['properties'][key]['value'] = value
            with self.subTest(key=key),self.assertRaises(ValueError):tool.check_properties(row,'cv1')
        row = properties(True)
        with self.assertRaises(ValueError): tool.check_properties(row, 'cv1')

    def test_reconstruction_keeps_original_exposure_control_pixels_and_captured_own(self):
        saved = saved_fixture(); received = []
        def own_factory(observation):
            received.append(observation)
            return dict(joint_positions=list(observation.own_qpos), hp=0, ammo=0, heat=0)
        profile = SimpleNamespace(fx=1.,fy=2.,cx=3.,cy=4.,distortion=[0.]*5)
        with patch.object(tool,'PIXEL_SHA',saved['sha256']):
            packet = tool.make_packet(saved, '/dev/shm/owned/actual.bgr', profile=profile, own_factory=own_factory)
        self.assertEqual(packet['control_time_ns'], 486000000); self.assertEqual(packet['time_s'], .486)
        self.assertEqual(packet['frame']['exposure_timestamp_ns'],476000000)
        self.assertEqual(packet['frame']['capture_time_s'],saved['request']['capture_sim_time'])
        self.assertEqual(packet['frame']['image']['sha256'],saved['sha256'])
        self.assertEqual(packet['frame']['own'],dict(joint_positions=[.1]*5))
        self.assertEqual(received[0].own_qvel,saved['request']['own_at_capture']['own_qvel_at_capture'])
        self.assertEqual(received[0].odom_xyyaw,saved['request']['own_at_capture']['own_odom_at_capture'])
        self.assertEqual(received[0].odom_vxyw,saved['request']['own_at_capture']['own_odom_velocity_at_capture'])
        self.assertEqual(set(packet),{'control_time_ns','time_s','frame','operator_fov'})

    def test_wrong_saved_scope_timestamp_or_tampered_pixels_fail_before_spawn(self):
        saved = saved_fixture()
        with patch.object(tool,'PIXEL_SHA',saved['sha256']):
            for key, value in [('frame_id',9),('capture_sim_time',.477),('observation_sim_time',.487),
                               ('episode',True),('binding_epoch',1.),('observed_seq',10),('robot_id','blue_sentry')]:
                bad = copy.deepcopy(saved); bad['request'][key] = value
                with self.subTest(key=key),self.assertRaises(ValueError):tool.check_saved(bad)
            bad = dict(saved, content=b'X'+saved['content'][1:])
            with self.assertRaises(ValueError):tool.check_saved(bad)
            bad = dict(saved, content=bytearray(saved['content']))
            with self.assertRaises(ValueError):tool.check_saved(bad)

    def test_first_response_requires_exact_original_clock_and_actual_detector_execution(self):
        tool.validate_response(response())
        for key, value in [('clock_time_ns',486000000.),('clock_time_ns',486000001),
                           ('detector_executed',False),('detector_executed',1),('tracking',1),
                           ('direction_frame','camera'),('runner_identity','legacy')]:
            bad = response();bad[key] = value
            with self.subTest(key=key),self.assertRaises(ValueError):tool.validate_response(bad)
        bad = response();bad['other'] = float('inf')
        with self.assertRaises(ValueError):tool.validate_response(bad)

    @staticmethod
    def child():
        return SimpleNamespace(stdin=SimpleNamespace(fileno=lambda:11),
                               stdout=SimpleNamespace(fileno=lambda:12),poll=lambda:None)

    def test_partial_write_counts_are_exact_and_one_reply_is_retained(self):
        wire = json.dumps(response()).encode()+b'\n'; evidence = {}
        with patch.object(tool.time,'perf_counter',return_value=1.),patch.object(tool.os,'set_blocking'),\
             patch.object(tool.select,'select',side_effect=[([], [11], []),([],[11],[]),([12],[],[])]),\
             patch.object(tool.os,'write',side_effect=[2,4]),patch.object(tool.os,'read',return_value=wire):
            row, raw = tool.first_transaction(self.child(),b'12345\n',evidence=evidence)
        self.assertEqual(row['stdin_written_bytes'],6);self.assertEqual(row['stdin_expected_bytes'],6)
        self.assertEqual(raw,wire);self.assertEqual(evidence['raw_response'],wire)

    def test_late_select_wake_never_delivers_request_or_accepts_response(self):
        now = [1.]
        def delayed_select(*args): now[0] = 3.1; return [12],[11],[]
        evidence = {}
        with patch.object(tool.time,'perf_counter',side_effect=lambda:now[0]),patch.object(tool.os,'set_blocking'),\
             patch.object(tool.select,'select',side_effect=delayed_select),patch.object(tool.os,'write') as write,\
             patch.object(tool.os,'read') as read,self.assertRaises(TimeoutError):
            tool.first_transaction(self.child(),b'123\n',evidence=evidence)
        write.assert_not_called();read.assert_not_called();self.assertEqual(evidence['stdin_written_bytes'],0)

    def test_zero_write_and_extra_reply_are_protocol_failures_not_fast_response(self):
        with patch.object(tool.time,'perf_counter',return_value=1.),patch.object(tool.os,'set_blocking'),\
             patch.object(tool.select,'select',return_value=([],[11],[])),patch.object(tool.os,'write',return_value=0),\
             self.assertRaises(BrokenPipeError):tool.first_transaction(self.child(),b'{}\n')
        wire = json.dumps(response()).encode()+b'\n{}\n'
        with patch.object(tool.time,'perf_counter',return_value=1.),patch.object(tool.os,'set_blocking'),\
             patch.object(tool.select,'select',return_value=([12],[11],[])),patch.object(tool.os,'write',return_value=3),\
             patch.object(tool.os,'read',return_value=wire),self.assertRaises(ValueError):
            tool.first_transaction(self.child(),b'{}\n')

    def test_failed_or_incomplete_first_frame_does_not_become_fast_valid_sample(self):
        good = dict(variant='default', errors=[], first_response=dict(response_s=.035),
                    phases=dict(first_frame_complete=True, completed_phases=[
                        dict(startup=False, phase='infer', elapsed_ns=23000000),
                        dict(startup=True, phase='model_compile', elapsed_ns=900000000)]))
        failed = copy.deepcopy(good); failed['errors'] = ['timeout']; failed['first_response']['response_s'] = .001
        partial = copy.deepcopy(good); partial['phases']['first_frame_complete'] = False
        result = tool.summarize_cases([good,failed,partial])
        self.assertEqual(result['default']['valid_first_cases'],1)
        self.assertEqual(result['default']['first_response']['samples'],1)
        self.assertAlmostEqual(result['default']['first_response']['p50_ms'],35.)
        self.assertNotIn('model_compile',result['default']['first_frame_phases'])
        self.assertEqual(result['cv1']['valid_first_cases'],0)


if __name__ == '__main__':unittest.main()
