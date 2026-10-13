"""Synthetic report tests only; no physics, render or native inference."""
import copy
import importlib.util
from pathlib import Path
import unittest
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('offline_smoke',
    Path(__file__).resolve().parents[1]/'tools/smoke_offline_deployment.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)

class ClassificationTests(unittest.TestCase):
    def sample(self):
        return dict(state='COMPLETED', captures=24,
            counts={'native_request':13, 'native_result':13, 'fire_true':0,
                    'native_gimbal_consumed':0},
            driver={'errors':[], 'frame_decoded':True,
                'transport_before_cleanup':{'admitted_frame_count':24, 'request_errors':[],
                    'current':{'connected':True,'uncertain':False,'last_error':''}},
                'cleanup':dict(completed=True, quiesced=True, session_close_ack=True,
                    network_lifecycle_error_free=True, errors=[])},
            resources_closed=True, driver_exit=0)
    def test_display_pass_does_not_qualify_native_control(self):
        result=smoke.classify_result(**self.sample())
        self.assertTrue(result['diagnostic_transport_passed'])
        self.assertFalse(result['qualified_static_offline_chain'])
        self.assertFalse(result['live_default_qualified'])
        self.assertFalse(result['full_match_qualified'])
    def test_missing_driver_cleanup_or_frame_fails_closed(self):
        for key in ('cleanup','frame_decoded','transport_before_cleanup'):
            args=self.sample();args['driver'].pop(key)
            self.assertFalse(smoke.classify_result(**args)['diagnostic_transport_passed'])
    def test_cleanup_checks_all_acknowledgements(self):
        for key in ('completed','quiesced','session_close_ack','network_lifecycle_error_free'):
            args=self.sample();args['driver']['cleanup'][key]=False
            self.assertFalse(smoke.classify_result(**args)['clean_shutdown'])
        for key in ('errors',):
            args=self.sample();args['driver']['cleanup'][key]=['failed']
            self.assertFalse(smoke.classify_result(**args)['clean_shutdown'])
    def test_exit_errors_and_live_resources_fail_closed(self):
        for key,value in [('driver_exit',2),('resources_closed',False)]:
            args=self.sample();args[key]=value
            self.assertFalse(smoke.classify_result(**args)['diagnostic_transport_passed'])
        args=self.sample();args['driver']['errors']=['failed']
        self.assertFalse(smoke.classify_result(**args)['diagnostic_transport_passed'])
    def test_capture_pairs_and_fire_are_required(self):
        cases=[('captures',23),('state','HALTED')]
        for key,value in cases:
            args=self.sample();args[key]=value
            self.assertFalse(smoke.classify_result(**args)['diagnostic_transport_passed'])
        for key,value in [('native_request',12),('native_result',12),('fire_true',1)]:
            args=self.sample();args['counts'][key]=value
            self.assertFalse(smoke.classify_result(**args)['diagnostic_transport_passed'])
    def test_transport_fault_cannot_be_hidden_by_old_frame(self):
        for key,value in [('connected',False),('uncertain',True),('last_error','failed')]:
            args=self.sample();args['driver']['transport_before_cleanup']['current'][key]=value
            self.assertFalse(smoke.classify_result(**args)['diagnostic_transport_passed'])
        args=self.sample();args['driver']['transport_before_cleanup']['request_errors']=[{'error':'failed'}]
        self.assertFalse(smoke.classify_result(**args)['diagnostic_transport_passed'])

    def test_active_control_still_never_qualifies_live(self):
        args=self.sample();args['counts']['native_gimbal_consumed']=1
        result=smoke.classify_result(**args)
        self.assertTrue(result['qualified_static_offline_chain'])
        self.assertFalse(result['live_default_qualified'])

class CleanupTests(unittest.TestCase):
    def test_cleanup_failure_does_not_skip_remaining_resources(self):
        calls=[];errors=[]
        def boom():
            calls.append('runtime_close')
            raise RuntimeError('close failed')
        worker=SimpleNamespace(close=lambda:calls.append('native_stop'),
            thread=SimpleNamespace(join=lambda timeout:calls.append('native_join')))
        camera=SimpleNamespace(stop=lambda:calls.append('camera_stop'),
            wait_closed=lambda timeout:calls.append('camera_join') or True)
        http=SimpleNamespace(is_alive=lambda:True,join=lambda timeout:calls.append('http_join'))
        server=SimpleNamespace(shutdown=lambda:calls.append('http_shutdown'),
            server_close=lambda:calls.append('http_close'))
        closed=smoke.cleanup_resources(camera=camera,
            runtime=SimpleNamespace(close=boom,worker=worker),driver=None,
            server=server,http=http,errors=errors)
        self.assertTrue(closed)
        self.assertEqual(len(errors),1)
        self.assertEqual(calls,['runtime_close','camera_stop','camera_join','native_stop',
            'native_join','http_shutdown','http_close','http_join'])

if __name__=='__main__':unittest.main()
