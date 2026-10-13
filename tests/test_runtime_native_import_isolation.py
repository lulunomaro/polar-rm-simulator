"""Adapter dispatch isolation; actual JSON child, no ROS/GL/native executable."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


class NativeImportIsolationTests(unittest.TestCase):
    def test_navigation_enqueue_acquisition_is_exact_validated_original_scan(self):
        from tests.test_navigation_runtime import NavigationRuntimeTests
        fixture=NavigationRuntimeTests();fixture.setUp();events=[];calls=[]
        fixture.runtime.trace=events.append
        provider=fixture.backend.navigation_sensor_packet
        def counted(robot_id):
            calls.append(robot_id);return provider(robot_id)
        fixture.backend.navigation_sensor_packet=counted
        cloud=fixture.backend.packet['sensors']['pointcloud']
        cloud.update(frame_id=7,acquisition_start_ns=70000000)
        fixture.backend.packet['sensors']['imu']['samples'][0]['sample_sim_ns']=70000000
        original_capture=fixture.backend.packet['capture_wall']
        try:
            fixture.tick();fixture.wait_for_response(1)
            enqueue=next(e for e in events if e['event']=='adapter_enqueue')
            actual=fixture.seen[0]['sensors']['pointcloud']
            self.assertEqual(calls,['alpha'],'Trace must not resample the sensor')
            self.assertEqual(enqueue['cloud_acquisition'],{key:actual[key] for key in
                ('frame_id','acquisition_start_ns','acquisition_end_ns','profile_sha256')})
            self.assertEqual(enqueue['cloud_acquisition']['acquisition_start_ns'],70000000)
            self.assertEqual(enqueue['cloud_acquisition']['profile_sha256'],enqueue['sensor_budget']['profile_sha256'])
            self.assertEqual(enqueue['cloud_acquisition']['frame_id'],enqueue['sensor_budget']['frame_id'])
            self.assertEqual(enqueue['sensor_budget']['capture_wall'],original_capture)
            self.assertEqual(fixture.backend.packet['capture_wall'],original_capture)
            self.assertIs(type(enqueue['cloud_acquisition']['frame_id']),int)
            cloud.update(frame_id=8,acquisition_start_ns=90000000,profile_sha256='b'*64)
            self.assertEqual(enqueue['cloud_acquisition']['frame_id'],7)
            self.assertEqual(enqueue['cloud_acquisition']['profile_sha256'],'0'*64)
        finally:fixture.tearDown()

    def test_fresh_navigation_and_json_slots_never_attempt_vision_import(self):
        code=r'''
import importlib.abc,json,pathlib,sys,time,unittest
blocked=('cv2','rm_match.platform_v2.native_adapter','rm_match.platform_v2.native_image',
    'rm_match.platform_v2.wsl_native_adapter')
class RejectVision(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if any(fullname==p or fullname.startswith(p+'.') for p in blocked):
            raise AssertionError('non_native_attempted_vision_import:'+fullname)
sys.meta_path.insert(0,RejectVision())
from tests.test_navigation_runtime import NavigationRuntimeTests
suite=unittest.defaultTestLoader.loadTestsFromTestCase(NavigationRuntimeTests)
result=unittest.TextTestRunner(verbosity=2).run(suite)
assert result.wasSuccessful() and result.testsRun==3
from rm_match.platform_v2.runtime import AdapterSlot,_loaded_native_class,_reviewed_native_instance
from rm_match.platform_v2.adapters import Registry
from rm_match.platform_v2.test_contracts import sample
from rm_match.deployment.json_adapter import register_json_adapters
registry=Registry();register_json_adapters(registry,pathlib.Path('examples/adapters.json'))
slot=AdapterSlot(registry,time.perf_counter)
try:
    observation=sample();observation['wall_deadline']=time.perf_counter()+2.
    job=dict(observation=observation,kind='navigation',binding=dict(epoch=observation['binding_epoch'],
        adapter_id='custom_navigation_example',config={}))
    slot.submit(job);response=slot.results.get(timeout=3.)
    assert response['error'] is None,response
    assert response['value']['kind']=='navigation'
    assert response['value']['command']['vx_mps']==0.
    process=slot._instance.process
    assert process.poll() is None
finally:
    slot.close();slot.thread.join(2.)
assert not slot.thread.is_alive() and slot.lifecycle_error is None
assert process.poll() is not None
class Custom:
    def cancel(self):raise AssertionError('arbitrary cancellation hook invoked')
AdapterSlot._cancel_native(Custom())
assert _loaded_native_class() is None
assert _reviewed_native_instance(Custom(),None) is False
assert not any(any(name==p or name.startswith(p+'.') for p in blocked) for name in sys.modules)
print(json.dumps({'fresh_process':True,'navigation_runtime_cases':3,'actual_json_child_reaped':True,
    'vision_import_attempts':0,'qualification':'dispatch/JSON fixture only; no ROS/navigation/native acceptance'}))
'''
        result=subprocess.run([sys.executable,'-c',code],cwd=ROOT,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
        record=json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(record['vision_import_attempts'],0)
        self.assertTrue(record['actual_json_child_reaped'])

    def test_loaded_native_subclass_uses_reviewed_base_cancel_only(self):
        from rm_match.platform_v2.native_adapter import NativeSourceAdapter
        from rm_match.platform_v2.runtime import AdapterSlot,_loaded_native_class,_reviewed_native_instance
        class CustomNative(NativeSourceAdapter):
            def cancel(self):raise AssertionError('custom override must not run on authority')
            def act(self,observation):raise AssertionError('custom act must not be mistaken for reviewed private act')
        instance=object.__new__(CustomNative)
        self.assertIs(_loaded_native_class(),NativeSourceAdapter)
        self.assertFalse(_reviewed_native_instance(instance,NativeSourceAdapter))
        with patch.object(NativeSourceAdapter,'cancel') as cancel:
            AdapterSlot._cancel_native(instance)
        cancel.assert_called_once_with(instance)


if __name__=='__main__':unittest.main()
