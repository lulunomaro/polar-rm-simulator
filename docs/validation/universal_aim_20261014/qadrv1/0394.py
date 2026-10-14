"""Startup tool instrumentation/real JSONL process tests; no ROS/NN/GPU."""
from contextlib import ExitStack
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from rm_match.deployment.json_adapter import register_json_adapters
from rm_match.platform_v2.adapters import Registry
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('ros_startup_diagnostic',ROOT/'tools/diagnose_ros2_jsonl_startup.py')
tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)


class StartupDiagnosticTests(unittest.TestCase):
    def test_manifest_commands_fixed_and_bootstrap_separately_hash_bound(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td);prefix=out/'owned-prefix'
            module,aid,namespace=tool.write_manifest(out,prefix,mode='module',python=sys.executable)
            row=json.loads(module.read_text())['adapters'][0]
            self.assertEqual(row['command'][:4],[sys.executable,'-u','-m','rm_match.integrations.ros2_bridge'])
            self.assertEqual(row['required_sensors'],[]);self.assertTrue(aid.startswith('custom_'))
            bootstrap,_,_=tool.write_manifest(out,prefix,mode='prefix-bootstrap',python=sys.executable)
            command=json.loads(bootstrap.read_text())['adapters'][0]['command']
            self.assertEqual(command[3],'--bridge-child');self.assertEqual(command[-1],tool.sha(out/'bridge_bootstrap.json'))
            with self.assertRaisesRegex(ValueError,'spec changed'):tool.run_bridge_child(out/'bridge_bootstrap.json','0'*64)

    def test_environment_is_local_scoped_and_does_not_export_operator_secret(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{'POLAR_SIM_ADMISSION_CREDENTIAL':'never copied','PYTHONHOME':'unsafe'},clear=True):
            root=Path(td);prefix=root/'prefix';out=root/'out';out.mkdir();ros=prefix/'opt/ros/lyrical'
            package=ros/'lib/python3.14/site-packages/rclpy';package.mkdir(parents=True);(package/'__init__.py').write_text('')
            (ros/'lib/librmw_fastrtps_cpp.so').write_bytes(b'explicit unit fake file, not loaded')
            (root/'EXTRACTION.json').write_text(json.dumps({'prefix':str(prefix)}))
            with patch.object(tool,'ARTIFACT',root):
                env=tool.local_environment(prefix,out)
                self.assertNotIn('POLAR_SIM_ADMISSION_CREDENTIAL',env);self.assertNotIn('PYTHONHOME',env)
                self.assertEqual(env['ROS_AUTOMATIC_DISCOVERY_RANGE'],'LOCALHOST');self.assertEqual(env['ROS_STATIC_PEERS'],'')
                self.assertEqual(env['RMW_IMPLEMENTATION'],'rmw_fastrtps_cpp')
                other=root/'other';other.mkdir()
                with self.assertRaisesRegex(ValueError,'Unverified ROS prefix'):tool.local_environment(other,out)

    def adapter(self,out,*,delay=0.):
        # Explicit standard-library pipe fixture, not a fake ROS installation.
        code='''import json,sys,time
for line in sys.stdin:
 r=json.loads(line);time.sleep(DELAY)
 reply={'schema':'polar.sim.adapter.jsonl.v1','op':r['op'],'ok':True}
 if r['op']=='act':
  o=r['observation'];reply['action']={'schema':'polar.sim.action.v2',**{k:o[k] for k in ('robot_id','episode','binding_epoch','observed_seq','sim_time','wall_deadline')},'kind':'navigation','mode':'velocity_body','command':{'frame':'base_link','vx_mps':0.,'vy_mps':0.,'wz_rps':0.}}
 print(json.dumps(reply),flush=True)
'''.replace('DELAY',repr(delay))
        manifest=out/'local.json';manifest.write_text(json.dumps(dict(schema='polar.sim.adapter.jsonl.v1',adapters=[dict(
            adapter_id='custom_startup_pipe_fixture',kind='navigation',label='Explicit JSONL unit process fixture',
            command=[sys.executable,'-u','-c',code],cwd=str(ROOT),required_sensors=[])])))
        registry=Registry();register_json_adapters(registry,manifest)
        return registry.create('custom_startup_pipe_fixture',{})

    def test_measured_real_adapter_reset_action_and_owned_cleanup(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td);adapter=self.adapter(out);report={}
            with tool.measured_adapter(adapter,report,out/'stderr.log'):
                adapter.reset(dict(robot_id='red_sentry',episode=1,binding_epoch=1))
                self.assertIs(adapter.clock,time.perf_counter)
                o=tool.fixture_observation(time.perf_counter()+.08);a=adapter.act(o)
                self.assertEqual(a['wall_deadline'],o['wall_deadline'])
            self.assertEqual(report['exchanges'][0]['original_timeout_s'],2.)
            self.assertTrue(report['exchanges'][0]['accepted']);self.assertTrue(report['exchanges'][1]['accepted'])
            self.assertFalse(report['adapter_io_thread_alive']);self.assertTrue(all(c['reaped'] and c['pipes_closed'] for c in report['owned_children']))

    def test_original_two_second_timeout_is_not_extended_and_child_thread_clean(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td);adapter=self.adapter(out,delay=2.2);report={}
            with tool.measured_adapter(adapter,report,out/'stderr.log'):
                with self.assertRaises(Exception):adapter.reset(dict(robot_id='red_sentry',episode=1,binding_epoch=1))
            reset=report['exchanges'][0]
            self.assertEqual(reset['original_timeout_s'],2.);self.assertFalse(reset['accepted'])
            # elapsed includes the adapter's owned-process cleanup on rejection.
            self.assertGreaterEqual(reset['elapsed_s'],2.);self.assertLess(reset['elapsed_s'],4.)
            self.assertFalse(report['adapter_io_thread_alive']);self.assertTrue(all(c['reaped'] and c['pipes_closed'] for c in report['owned_children']))


if __name__=='__main__':unittest.main()
