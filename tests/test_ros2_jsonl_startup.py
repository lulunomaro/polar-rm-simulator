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
    def assert_actual_owned_cleanup(self,adapter,child,report):
        # Windows uses birth-bound CreateProcessW rather than Popen; the old
        # instrumentation's owned_children list can legitimately be empty.
        # Require the real adapter/child proof instead of vacuous all([]).
        self.assertIsNotNone(child)
        report['direct_owned_child']=dict(pid=child.pid,returncode=child.poll(),
            pipes_closed=all(s is None or s.closed for s in (child.stdin,child.stdout)))
        report['owned_adapter_cleanup']=adapter.shutdown_status
        self.assertGreater(child.pid,0);self.assertIsNotNone(child.poll())
        self.assertTrue(report['direct_owned_child']['pipes_closed'])
        self.assertTrue(adapter.shutdown_status['clean'])
        self.assertTrue(adapter.shutdown_status['io_thread_stopped'])
        ownership=adapter.shutdown_status['ownership']
        self.assertTrue(ownership['clean']);self.assertTrue(ownership['reaped'])
        self.assertTrue(ownership['group_empty'])

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
                report['reset_entry']=time.perf_counter()
                adapter.reset(dict(robot_id='red_sentry',episode=1,binding_epoch=1))
                report['reset_return']=time.perf_counter()
                child=adapter.process
                self.assertIs(adapter.clock,time.perf_counter)
                o=tool.fixture_observation(time.perf_counter()+.08);a=adapter.act(o)
                self.assertEqual(a['wall_deadline'],o['wall_deadline'])
            reset=report['exchanges'][0]
            self.assertGreater(reset['original_timeout_s'],0.)
            self.assertLessEqual(reset['original_timeout_s'],2.)
            self.assertLess(report['reset_return']-report['reset_entry'],2.)
            # Independent entrance clock includes process ownership/startup;
            # exchange has only what remains of the original total budget.
            self.assertAlmostEqual(reset['begin']+reset['original_timeout_s'],
                report['reset_entry']+2.,delta=.02)
            self.assertTrue(report['exchanges'][0]['accepted']);self.assertTrue(report['exchanges'][1]['accepted'])
            self.assertFalse(report['adapter_io_thread_alive']);self.assertTrue(all(c['reaped'] and c['pipes_closed'] for c in report['owned_children']))
            self.assert_actual_owned_cleanup(adapter,child,report)
            print('STARTUP_RESET_TIMING '+json.dumps(report,sort_keys=True))

    def test_original_two_second_timeout_is_not_extended_and_child_thread_clean(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td);adapter=self.adapter(out,delay=2.2);report={}
            real_open=adapter._open_owned_process;real_close=adapter.close;owned=[]
            def delayed_owned_start():
                report['owned_start_entry']=time.perf_counter()
                # Real resource preparation latency, not an injected clock or
                # fake process. Then launch the actual 2.2s stdlib child.
                time.sleep(.3)
                real_open()
                owned.append(adapter.process)
                report['owned_start_return']=time.perf_counter()
            def measured_close(*args,**kwargs):
                report.setdefault('first_cleanup_entry',time.perf_counter())
                return real_close(*args,**kwargs)
            with patch.object(adapter,'_open_owned_process',delayed_owned_start),patch.object(adapter,'close',measured_close):
                with tool.measured_adapter(adapter,report,out/'stderr.log'):
                    report['reset_entry']=time.perf_counter()
                    try:
                        with self.assertRaises(Exception):adapter.reset(dict(robot_id='red_sentry',episode=1,binding_epoch=1))
                    finally:report['reset_failure_return']=time.perf_counter()
            reset=report['exchanges'][0]
            self.assertGreater(reset['original_timeout_s'],0.)
            self.assertLessEqual(reset['original_timeout_s'],1.7)
            self.assertFalse(reset['accepted'])
            self.assertIn(reset['error_type'],('Empty','TimeoutError'))
            self.assertGreaterEqual(report['owned_start_return']-report['owned_start_entry'],.3)
            self.assertAlmostEqual(reset['begin']+reset['original_timeout_s'],
                report['reset_entry']+2.,delta=.02)
            # Timeout must happen at the aggregate 2s boundary, rather than
            # granting another 2s after the deliberately slow owned startup.
            control_elapsed=report['first_cleanup_entry']-report['reset_entry']
            self.assertGreaterEqual(control_elapsed,2.-.02)
            self.assertLess(control_elapsed,2.15)
            # elapsed includes the adapter's owned-process cleanup on rejection.
            self.assertGreaterEqual(reset['elapsed_s'],reset['original_timeout_s'])
            self.assertLess(report['reset_failure_return']-report['reset_entry'],3.7)
            self.assertLess(report['reset_failure_return']-report['first_cleanup_entry'],1.7)
            self.assertFalse(report['adapter_io_thread_alive']);self.assertTrue(all(c['reaped'] and c['pipes_closed'] for c in report['owned_children']))
            self.assertEqual(len(owned),1)
            self.assert_actual_owned_cleanup(adapter,owned[0],report)
            print('STARTUP_RESET_TIMING '+json.dumps(report,sort_keys=True))


if __name__=='__main__':unittest.main()
