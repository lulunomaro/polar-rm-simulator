"""Configuration/supervisor checks; no ROS navigation, renderer or live acceptance."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import threading
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import Mock,patch
from tools.pb_navigation_stack import DDS_ENVIRONMENT,NODES,PBNavigationStack,StackFault,adapt_parameters,checked_json,namespace_checked

NS='/polar_sil_'+'a'*32+'/red_sentry'

def parameters():
    reality={k:{'ros__parameters':{'use_sim_time':False}} for k in NODES}
    reality['point_lio']['ros__parameters'].update({'filter_size_map':0.2,'point_filter_num':8,
        'mapping':{'satu_acc':4.0,'acc_norm':1.0,'lidar_meas_cov':.01}})
    reality['planner_server']['ros__parameters']['GridBased']={'plugin':'nav2_smac_planner/SmacPlannerHybrid'}
    reality['controller_server']['ros__parameters']['FollowPath']={'plugin':'pb_omni_pid_pursuit_controller::OmniPidPursuitController',
        'translation_kp':3.0,'translation_ki':.1,'translation_kd':.3,'enable_rotation':False}
    for name,frame in [('local_costmap','odom'),('global_costmap','map')]:
        reality[name]={name:{'ros__parameters':{'global_frame':frame,'robot_base_frame':'gimbal_yaw_fake',
            'intensity_voxel_layer':{'plugin':'pb_nav2_costmap_2d::IntensityVoxelLayer','terrain_map':{'topic':'<robot_namespace>/terrain_map'}}}}}
    generation={'nodes':[{'package':'point_lio','parameters':[{'mapping.acc_norm':9.81,'prior_pcd.enable':False}]}]}
    return reality,copy.deepcopy(reality),generation

class StackConfigurationTests(unittest.TestCase):
    def test_namespace_domain_are_exact_and_fresh(self):
        self.assertEqual(namespace_checked(NS),NS)
        for bad in ('/red_sentry','/polar_sil_a/red_sentry',NS+'/other'):
            with self.assertRaises(ValueError):namespace_checked(bad)
        for bad in (True,84.0,83):
            with self.assertRaises(ValueError):PBNavigationStack({},'unused',domain_id=bad)
        a=PBNavigationStack({},'unused');b=PBNavigationStack({},'unused')
        self.assertNotEqual(a.namespace,b.namespace)

    def test_algorithm_tuning_preserved_and_units_equivalent(self):
        reality,sim,generation=parameters();before=copy.deepcopy(reality)
        result,changes=adapt_parameters(reality,sim,generation,NS)
        lio=result[NS+'/point_lio']['ros__parameters']
        self.assertEqual(lio['mapping.satu_acc'],39.24)
        self.assertEqual(lio['mapping.lidar_meas_cov'],.01)
        self.assertEqual(lio['point_filter_num'],8)
        self.assertEqual(lio['filter_size_map'],.2)
        controller=result[NS+'/controller_server']['ros__parameters']
        self.assertEqual(controller['FollowPath.translation_kp'],3.0)
        self.assertFalse(controller['FollowPath.enable_rotation'])
        self.assertEqual(controller['FollowPath.v_linear_max'],1.0)
        self.assertEqual(controller['FollowPath.v_angular_max'],2.0)
        self.assertEqual(result[NS+'/local_costmap/local_costmap']['ros__parameters']['global_frame'],'odom')
        self.assertEqual(result[NS+'/global_costmap/global_costmap']['ros__parameters']['global_frame'],'map')
        for key in ('local_costmap','global_costmap'):
            self.assertEqual(result[NS+'/'+key+'/'+key]['ros__parameters']['robot_radius'],.38)
            self.assertTrue(any(c['node']==key and c['parameter']=='robot_radius' and 'not real sentry CAD' in c['reason'] for c in changes))
        self.assertEqual(reality,before)
        self.assertTrue(any(c['parameter']=='mapping.satu_acc' and 'SI' in c['reason'] for c in changes))

    def test_opt_in_diagnostics_only_adds_two_metadata_parameters(self):
        original, original_changes=adapt_parameters(*parameters(),NS)
        enabled, changes=adapt_parameters(*parameters(),NS,diagnostics=True)
        for node,key in [('point_lio','pb.dispatch_diagnostics'),('controller_server','polar_sourced.diagnostics')]:
            self.assertNotIn(key,original[NS+'/'+node]['ros__parameters'])
            self.assertIs(enabled[NS+'/'+node]['ros__parameters'].pop(key),True)
        self.assertEqual(enabled,original)
        diagnostic_keys={'pb.dispatch_diagnostics','polar_sourced.diagnostics'}
        self.assertEqual([c for c in changes if c['parameter'] not in diagnostic_keys],original_changes)
        self.assertEqual([c['parameter'] for c in changes if c['parameter'] in diagnostic_keys],['pb.dispatch_diagnostics','polar_sourced.diagnostics'])
        self.assertFalse(PBNavigationStack({},'unused').diagnostics)
        for bad in (1,'true',None):
            with self.subTest(value=bad):
                with self.assertRaisesRegex(ValueError,'diagnostics_boolean'):
                    adapt_parameters(*parameters(),NS,diagnostics=bad)
                with self.assertRaisesRegex(ValueError,'diagnostics_boolean'):
                    PBNavigationStack({},'unused',diagnostics=bad)

    def test_slam_tf_enabled_without_prior_or_fake_frame(self):
        result,_=adapt_parameters(*parameters(),NS)
        self.assertEqual(result[NS+'/slam_toolbox']['ros__parameters']['transform_publish_period'],.02)
        self.assertEqual(result[NS+'/slam_toolbox']['ros__parameters']['scan_topic'],NS+'/obstacle_scan')
        for key in ('loam_interface','sensor_scan_generation'):
            self.assertEqual(result[NS+'/'+key]['ros__parameters']['base_frame'],'base_link')
        self.assertNotIn(NS+'/fake_vel_transform',result)
        self.assertNotIn(NS+'/map_server',result)

    def test_alternative_algorithm_or_frames_rejected(self):
        for node,key,value in [('planner_server','GridBased','other'),('controller_server','FollowPath','other')]:
            reality,sim,generation=parameters();reality[node]['ros__parameters'][key]['plugin']=value
            with self.assertRaises(ValueError):adapt_parameters(reality,sim,generation,NS)
        reality,sim,generation=parameters();reality['local_costmap']['local_costmap']['ros__parameters']['global_frame']='map'
        with self.assertRaises(ValueError):adapt_parameters(reality,sim,generation,NS)

    def test_json_duplicate_and_nonfinite_rejected(self):
        with TemporaryDirectory() as temp:
            p=Path(temp)/'manifest.json'
            for raw in ('{"a":1,"a":2}','{"a":NaN}'):
                p.write_text(raw)
                with self.assertRaises(ValueError):checked_json(p)

    def test_generation_alias_fault_stops_group(self):
        for value in (True,1.0):
            with TemporaryDirectory() as temp:
                stack=PBNavigationStack({},Path(temp)/'fresh')
                with self.assertRaisesRegex(StackFault,'generation_fault'):
                    stack.poll_health({'robot_id':'red_sentry','episode':0,'binding_epoch':value})
                self.assertTrue(stack.closed)
                self.assertEqual(stack.health_error,'generation_changed')
                self.assertTrue(stack.cleanup['clean'])

    def test_concurrent_stop_waits_for_actual_failed_cleanup(self):
        stack=PBNavigationStack({},'unused');entered=threading.Event();release=threading.Event();returned=threading.Event();rows=[]
        def cleanup(grace):
            stack.closed=True;entered.set()
            self.assertTrue(release.wait(timeout=1))
            return {'clean':False,'errors':['fixture_cleanup_failed']}
        stack._stop_owned=cleanup
        first=threading.Thread(target=lambda:rows.append(stack.stop()))
        second=threading.Thread(target=lambda:(rows.append(stack.stop()),returned.set()))
        first.start();self.assertTrue(entered.wait(1));second.start()
        self.assertFalse(returned.wait(.02))
        self.assertIsNone(stack.cleanup)
        release.set();first.join(1);second.join(1)
        self.assertEqual(len(rows),2)
        self.assertTrue(all(row['clean'] is False for row in rows))
        self.assertEqual(rows[0],rows[1])

    def test_stop_rechecks_actual_asset_sha(self):
        with TemporaryDirectory() as temp:
            p=Path(temp)/'binary';p.write_bytes(b'original')
            from tools.pb_navigation_stack import sha
            stack=PBNavigationStack({'assets':{'owned':{'path':str(p),'sha256':sha(p)}}},Path(temp)/'out')
            p.write_bytes(b'changed')
            result=stack.stop()
            self.assertFalse(result['assets_unchanged'])
            self.assertFalse(result['clean'])
            self.assertIn('algorithm_assets_changed',result['errors'])

    def test_spin_requires_owned_executor(self):
        stack=PBNavigationStack({},'unused')
        with self.assertRaisesRegex(StackFault,'executor_missing'):stack._spin(0)
        stack.executor=Mock();stack._spin(-1)
        stack.executor.spin_once.assert_called_once_with(timeout_sec=0.0)

    def test_supervisor_dds_scope_matches_children_and_restores_on_failure(self):
        for failure in (False,True):
            stack=PBNavigationStack({},'unused');seen=[]
            rclpy=Mock();executors=Mock()
            def init(**kwargs):
                seen.append({key:os.environ.get(key) for key in DDS_ENVIRONMENT})
                self.assertEqual(kwargs['domain_id'],84)
                self.assertIs(kwargs['context'],stack.context)
            rclpy.init.side_effect=init
            if failure:rclpy.create_node.side_effect=RuntimeError('fixture_node_failure')
            with patch.dict(os.environ,{'ROS_LOCALHOST_ONLY':'0','ROS_DOMAIN_ID':'83'},clear=False):
                os.environ.pop('RMW_IMPLEMENTATION',None)
                before={key:os.environ.get(key) for key in DDS_ENVIRONMENT}
                with patch.dict(sys.modules,{'rclpy':rclpy,'rclpy.executors':executors}):
                    if failure:
                        with self.assertRaisesRegex(RuntimeError,'fixture_node_failure'):stack._create_lifecycle_client()
                    else:stack._create_lifecycle_client()
                self.assertEqual({key:os.environ.get(key) for key in DDS_ENVIRONMENT},before)
            self.assertEqual(seen,[DDS_ENVIRONMENT])
            self.assertEqual(stack.events[-1]['initialized'],not failure)
            self.assertTrue(stack.events[-1]['process_environment_restored'])

    def test_executor_shutdown_order_and_failure_are_visible(self):
        stack=PBNavigationStack({},'unused');calls=[]
        stack.node=Mock();stack.context=Mock();stack.executor=Mock()
        stack.executor.shutdown.side_effect=lambda **kwargs:calls.append('shutdown') or False
        stack.executor.remove_node.side_effect=lambda node:calls.append('remove')
        stack.node.destroy_node.side_effect=lambda:calls.append('destroy')
        stack.context.try_shutdown.side_effect=lambda:calls.append('context')
        result=stack.stop()
        self.assertEqual(calls,['shutdown','remove','destroy','context'])
        self.assertFalse(result['clean'])
        self.assertIn('executor_shutdown_incomplete',result['errors'])

    @unittest.skipUnless(sys.platform=='linux' and sys.version_info[:2]==(3,10),'actual Humble Python 3.10 context check')
    def test_actual_humble_owned_context_does_not_init_global_executor(self):
        try:import rclpy
        except ImportError:self.skipTest('Humble rclpy unavailable')
        from rclpy.utilities import get_default_context
        before=get_default_context().ok()
        stack=PBNavigationStack({},'unused')
        try:
            stack._create_lifecycle_client();stack._spin(0)
            self.assertIs(stack.executor.context,stack.context)
            self.assertEqual(get_default_context().ok(),before)
            self.assertTrue(stack.context.ok())
        finally:result=stack.stop()
        self.assertTrue(result['clean'])
        self.assertFalse(stack.context.ok())

    @unittest.skipUnless(sys.platform=='linux' and sys.version_info[:2]==(3,10),'actual Humble isolated lifecycle fixture')
    def test_actual_humble_localhost_lifecycle_discovery_restored_parent_env(self):
        try:import rclpy
        except ImportError:self.skipTest('Humble rclpy unavailable')
        fixture='''import json,os,signal,sys
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.lifecycle import LifecycleNode,TransitionCallbackReturn
class HarmlessLifecycle(LifecycleNode):
    def on_configure(self,state):return TransitionCallbackReturn.SUCCESS
context=rclpy.context.Context()
rclpy.init(args=[],context=context,domain_id=84)
node=HarmlessLifecycle('controller_server',namespace=sys.argv[1],context=context,use_global_arguments=False)
executor=SingleThreadedExecutor(context=context);executor.add_node(node)
running=True
def terminate(*args):
    global running
    running=False
signal.signal(signal.SIGTERM,terminate)
print(json.dumps({'node':node.get_fully_qualified_name(),'dds':{k:os.environ.get(k) for k in ('ROS_DOMAIN_ID','ROS_LOCALHOST_ONLY','RMW_IMPLEMENTATION')},'sensor_frames':0,'physics_steps':0}),flush=True)
try:
    while running and context.ok():executor.spin_once(timeout_sec=.02)
finally:
    executor.shutdown(timeout_sec=.15);executor.remove_node(node);node.destroy_node();context.try_shutdown()
'''
        with TemporaryDirectory() as temp:
            stack=PBNavigationStack({},Path(temp)/'out');stack.out.mkdir()
            log=(stack.out/'fixture.log').open('wb');stack.logs['fixture']=log
            child_env=os.environ.copy();child_env.update(DDS_ENVIRONMENT)
            child=subprocess.Popen([sys.executable,'-c',fixture,stack.namespace],env=child_env,
                stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            stack.processes['fixture']=child;started=time.perf_counter()
            try:
                with patch.dict(os.environ,{'ROS_DOMAIN_ID':'83','ROS_LOCALHOST_ONLY':'0'},clear=False):
                    before={key:os.environ.get(key) for key in DDS_ENVIRONMENT}
                    stack._create_lifecycle_client()
                    self.assertEqual({key:os.environ.get(key) for key in DDS_ENVIRONMENT},before)
                stack._lifecycle('controller_server',1)  # Existing 10-second service/reply gates.
                self.assertEqual(stack._lifecycle('controller_server'),2)
            finally:cleanup=stack.stop()
            self.assertTrue(cleanup['clean'],cleanup)
            child_record=json.loads((stack.out/'fixture.log').read_text().splitlines()[0])
            self.assertEqual(child_record['dds'],DDS_ENVIRONMENT)
            self.assertEqual(child_record['node'],stack.namespace+'/controller_server')
            print(json.dumps({'qualification':'actual isolated harmless ROS lifecycle service, no navigation acceptance',
                'node':child_record['node'],'service_paths':[stack.namespace+'/controller_server/change_state',stack.namespace+'/controller_server/get_state'],
                'dds':child_record['dds'],'elapsed_s':time.perf_counter()-started,'state':2,'sensor_frames':0,'physics_steps':0,
                'parent_environment_restored':True,'cleanup':cleanup}),flush=True)

    @unittest.skipUnless(sys.platform=='linux','POSIX owned process group check')
    def test_fault_reaps_own_harmless_process_preserves_other_group(self):
        with TemporaryDirectory() as temp:
            stack=PBNavigationStack({},Path(temp)/'out');stack.out.mkdir()
            owned=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],start_new_session=True)
            other=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],start_new_session=True)
            stack.processes={'harmless':owned}
            try:
                with self.assertRaises(StackFault):stack.poll_health({'robot_id':'red_sentry','episode':1,'binding_epoch':1})
                self.assertIsNotNone(owned.poll())
                self.assertIsNone(other.poll())
                self.assertEqual(stack.stop(),stack.cleanup)
                self.assertTrue(stack.cleanup['clean'])
            finally:
                other.terminate();other.wait(timeout=2)

if __name__=='__main__':unittest.main()
