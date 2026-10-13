"""External goal-client setup and exact estimated-pose units; no ROS/WSL/SIL."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace as N
import unittest
from unittest.mock import patch

from tools import qa_pb_external_navigation_goal as tool


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,value):path.write_text(json.dumps(value));return dict(path=str(path),sha256=digest(path))
def pose_factory():
    return N(header=N(frame_id='',stamp=N(sec=0,nanosec=0)),pose=N(position=N(x=0.,y=0.,z=0.),
        orientation=N(x=0.,y=0.,z=0.,w=1.)))
def estimate():
    return N(header=N(frame_id='map',stamp=N(sec=19,nanosec=123)),child_frame_id='base_link',
        transform=N(translation=N(x=-2.,y=.25,z=.03),rotation=N(x=0.,y=0.,z=.1,w=.995)))


def costmap_message():
    from array import array
    return N(header=N(frame_id='map',stamp=N(sec=19,nanosec=200)),
        metadata=N(size_x=8,size_y=4,resolution=.5,layer='master',
            origin=N(position=N(x=-3.,y=-.5,z=0.),orientation=N(x=0.,y=0.,z=0.,w=1.)),
            map_load_time=N(sec=0,nanosec=0),update_time=N(sec=0,nanosec=0)),
        data=array('B',range(32)))


class ExternalGoalTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.root=Path(self.temp.name)
        self.out=self.root/'artifacts'/'peer';self.out.mkdir(parents=True)
        self.files=('source.py','supervisor.py')
        for name in self.files:(self.root/name).write_bytes(name.encode())
        python=self.root/'venv_python';python.write_bytes(b'not executed by units')
        self.environment=dict(venv_python=str(python),process_environment={'PYTHONDONTWRITEBYTECODE':'1'})
        self.envref=write(self.root/'env.json',self.environment)
        self.session=dict(schema='polar.pb.wsl-session-spec.v1',run_uuid='b'*32,
            namespace='/polar_sil_'+'b'*32+'/red_sentry',relative_test_goal=False,
            expected_generation=dict(robot_id='red_sentry',episode=0,binding_epoch=1),environment_ref=self.envref)
        self.sessionref=write(self.root/'session.json',self.session)
        self.spec=dict(schema=tool.SCHEMA,run_uuid='a'*32,session_run_uuid='b'*32,session_ref=self.sessionref,
            namespace=self.session['namespace'],domain_id=84,root_linux=str(self.root),out_linux=str(self.out),
            environment_ref=self.envref,source_sha256={name:digest(self.root/name) for name in self.files},
            goal_offset_m=[1.,0.],max_wall_seconds=60.)
        self.path=self.out/'EXTERNAL_SPEC.json';write(self.path,self.spec)
    def tearDown(self):self.temp.cleanup()
    def load(self):
        with patch.object(tool,'ROOT',self.root),patch.object(tool,'SOURCE_FILES',self.files):
            return tool.load_spec(self.path,digest(self.path))

    def test_production_session_only_and_same_environment_snapshot(self):
        spec,out=self.load();self.assertEqual(spec,self.spec);self.assertEqual(out,self.out)
        self.assertIs(spec['goal_offset_m'][0].__class__,float)
        for change in ('qa','namespace','generation_alias','environment'):
            session=copy.deepcopy(self.session)
            if change=='qa':session['relative_test_goal']=True
            elif change=='namespace':session['namespace']='/old'
            elif change=='generation_alias':session['expected_generation']['episode']=False
            else:session['environment_ref']['sha256']='f'*64
            self.spec['session_ref']=write(self.root/'session.json',session);write(self.path,self.spec)
            with self.subTest(change=change):
                with self.assertRaises(ValueError):self.load()

    def test_spec_identity_integer_alias_changed_source_reference_and_fixed_goal_rejected(self):
        original=copy.deepcopy(self.spec)
        for field,bad in [('domain_id',True),('domain_id',84.),('domain_id',85),('max_wall_seconds',True),
                          ('max_wall_seconds',float('nan')),('max_wall_seconds',61),('goal_offset_m',[1,0]),
                          ('goal_offset_m',[2.,0.]),('namespace','/old'),('schema','old')]:
            self.spec=copy.deepcopy(original);self.spec[field]=bad;write(self.path,self.spec)
            with self.subTest(field=field,bad=bad):
                with self.assertRaises(ValueError):self.load()
        write(self.path,original);(self.root/'source.py').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'source_changed'):self.load()
        (self.root/'source.py').write_bytes(b'source.py');(self.root/'env.json').write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError,'reference_changed'):self.load()

    def test_duplicate_overflow_nonfinite_and_oversize_json_do_not_load(self):
        for raw in (b'{"x":1,"x":2}',b'{"x":1e309}',b'{"x":NaN}',b' '* (tool.MAX_SPEC+1)):
            self.path.write_bytes(raw)
            with self.subTest(raw=raw[:30]):
                with self.assertRaises(ValueError):tool.snapshot(self.path)

    @unittest.skipUnless(hasattr(os,'symlink'),'symlink capability required')
    def test_spec_alias_is_rejected_even_with_identical_hash(self):
        alias=self.out/'alias.json'
        try:alias.symlink_to(self.path)
        except OSError as exc:self.skipTest('OS symlink permission unavailable: '+str(exc))
        with self.assertRaisesRegex(ValueError,'unaliased'):tool.snapshot(alias)

    def test_marker_does_not_allow_system_interpreter_and_python_env_is_scrubbed(self):
        marker=self.spec['run_uuid']+':'+self.envref['sha256']
        with patch.dict(os.environ,{'POLAR_EXTERNAL_GOAL_ENV':marker,'PYTHONDONTWRITEBYTECODE':'1',
                                    'PYTHONPATH':'untrusted','PYTHONHOME':'untrusted'},clear=True),\
             patch.object(sys,'executable','/usr/bin/python3'),patch.object(tool.os,'execve') as execute:
            tool.bootstrap(self.spec,self.environment,['--run'])
        execute.assert_called_once();python,argv,env=execute.call_args.args
        self.assertEqual(python,self.environment['venv_python'])
        self.assertEqual(argv[-1],'--run');self.assertNotIn('PYTHONPATH',env);self.assertNotIn('PYTHONHOME',env)
        with patch.dict(os.environ,{'POLAR_EXTERNAL_GOAL_ENV':marker,'PYTHONDONTWRITEBYTECODE':'1'},clear=True),\
             patch.object(sys,'executable',python),patch.object(tool.os,'execve') as execute:
            tool.bootstrap(self.spec,self.environment,['--run'])
        execute.assert_not_called()

    def test_exact_original_tf_only_selects_map_offset_and_keeps_stamp(self):
        source=estimate();goal,raw=tool.goal_from_estimate(source,pose_factory)
        self.assertEqual([goal.pose.position.x,goal.pose.position.y],[-1.,.25])
        self.assertEqual(raw['relative_offset_m'],[1.,0.])
        self.assertEqual(raw['goal']['header'],raw['transform']['header'])
        self.assertEqual(raw['goal']['header']['stamp'],{'sec':19,'nanosec':123})
        self.assertNotIn('qpos',json.dumps(raw))
        source.transform.translation.x=float('nan')
        with self.assertRaises(ValueError):tool.goal_from_estimate(source,pose_factory)

    def test_readonly_active_state_requires_both_real_integer_active_states(self):
        self.assertTrue(tool.gate_active(dict(controller_server=3,planner_server=3)))
        for value in ({},{'controller_server':3},{'controller_server':3.,'planner_server':3},
                      {'controller_server':True,'planner_server':3},{'controller_server':2,'planner_server':3}):
            with self.subTest(states=value):self.assertFalse(tool.gate_active(value))

    def test_client_source_has_no_lifecycle_activation_sensor_or_velocity_publish_calls(self):
        tree=ast.parse(Path(tool.__file__).read_text())
        names=[node.func.attr for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)]
        self.assertNotIn('drive_goal',names);self.assertNotIn('activate_navigation',names)
        self.assertNotIn('activate_controller',names);self.assertNotIn('publish',names)
        self.assertNotIn('ChangeState',Path(tool.__file__).read_text())

    def test_ready_is_absent_until_complete_atomic_replace_and_old_files_not_overwritten(self):
        target=self.out/'READY.json';value=dict(state='OBSERVING_NO_INPUT_PUBLISHED',pid=123)
        actual_replace=os.replace;observed=[]
        def replace(src,dst):
            self.assertFalse(target.exists())
            self.assertEqual(json.loads(Path(src).read_bytes()),value)
            observed.append((src,dst));actual_replace(src,dst)
        with patch.object(tool.os,'replace',side_effect=replace):tool.publish_json(target,value)
        self.assertEqual(len(observed),1);self.assertEqual(json.loads(target.read_bytes()),value)
        self.assertFalse((self.out/'READY.json.tmp').exists())
        before=target.read_bytes()
        with self.assertRaisesRegex(ValueError,'metadata_reuse'):tool.publish_json(target,{'new':True})
        self.assertEqual(target.read_bytes(),before)

    def test_incomplete_temp_and_invalid_payload_never_publish_ready(self):
        target=self.out/'READY.json';temporary=self.out/'READY.json.tmp';temporary.write_bytes(b'{')
        with self.assertRaisesRegex(ValueError,'metadata_reuse'):tool.publish_json(target,{'ready':True})
        self.assertFalse(target.exists());self.assertEqual(temporary.read_bytes(),b'{')
        temporary.unlink()
        with self.assertRaises(ValueError):tool.publish_json(target,{'value':float('nan')})
        self.assertFalse(target.exists());self.assertFalse(temporary.exists())

    def test_unfinished_observer_thread_cannot_report_clean_or_success(self):
        identity=dict(pid=123,start_ticks=4,boot_id='fixture')
        for errors,alive,clean in [([],False,True),([],True,False),(['close_error'],False,False)]:
            with self.subTest(errors=errors,alive=alive):
                record=tool.cleanup_record('a'*32,identity,errors,alive)
                self.assertIs(record['clean'],clean);self.assertIs(record['observer_thread_alive'],alive)
        with self.assertRaises(ValueError):tool.cleanup_record('a'*32,identity,[],1)

    def test_existing_lexical_parent_escape_and_canonical_outside_output_are_rejected(self):
        with TemporaryDirectory() as directory:
            base=Path(directory);root=base/'workspace';artifacts=root/'artifacts';artifacts.mkdir(parents=True)
            escape=base/'escape';escape.mkdir()
            value=copy.deepcopy(self.spec);value['root_linux']=str(root)
            for out in (artifacts/'..'/'..'/'escape',escape):
                with self.subTest(out=str(out)):
                    value['out_linux']=str(out)
                    spec_path=escape/'EXTERNAL_SPEC.json';write(spec_path,value)
                    with patch.object(tool,'ROOT',root),patch.object(tool,'SOURCE_FILES',self.files):
                        with self.assertRaisesRegex(ValueError,'unaliased|owned_output'):
                            tool.load_spec(spec_path,digest(spec_path))
            # Reading the same file via an explicit parent alias is also refused.
            with self.assertRaisesRegex(ValueError,'unaliased'):
                tool.snapshot(artifacts/'..'/'..'/'escape'/'EXTERNAL_SPEC.json')

    def test_actual_full_grid_metadata_data_hash_stamps_and_cell_indices_are_reproducible(self):
        message=costmap_message();grid,raw=tool.costmap_snapshot(message,1,123.4,'/ns/global_costmap/costmap_raw')
        _,saved=tool.goal_from_estimate(estimate(),pose_factory)
        decision=tool.geometry_decision(grid,raw,saved)
        self.assertTrue(decision['ready']);self.assertFalse(decision['costs_affect_predicate'])
        self.assertEqual(decision['start_cell'],{'in_bounds':True,'index_xy':[2,1],'cost':10})
        self.assertEqual(decision['goal_cell'],{'in_bounds':True,'index_xy':[4,1],'cost':12})
        self.assertEqual(grid['data_sha256'],hashlib.sha256(bytes(range(32))).hexdigest())
        self.assertEqual(grid['header']['stamp'],{'sec':19,'nanosec':200})
        self.assertEqual(decision['actual_tf']['header']['stamp'],{'sec':19,'nanosec':123})
        self.assertEqual(grid['metadata']['update_time'],{'sec':0,'nanosec':0})
        self.assertEqual(grid['receive_clock'],'linux_local_perf_counter')
        message.metadata.origin.position.x=50.;message.data[10]=255
        self.assertEqual(grid['metadata']['origin']['position']['x'],-3.);self.assertEqual(raw[10],10)

    def test_map_count_or_active_servers_do_not_override_outside_actual_costmap_geometry(self):
        _,saved=tool.goal_from_estimate(estimate(),pose_factory)
        message=costmap_message();message.metadata.origin.position.x=0.
        old,raw=tool.costmap_snapshot(message,1,123.,'/ns/global_costmap/costmap_raw')
        self.assertFalse(tool.geometry_decision(old,raw,saved)['ready'])
        message.metadata.origin.position.x=-3.
        current,raw=tool.costmap_snapshot(message,2,124.,'/ns/global_costmap/costmap_raw')
        self.assertTrue(tool.geometry_decision(current,raw,saved)['ready'])
        self.assertEqual(current['receipt_id'],2)

    def test_half_open_grid_lower_edge_valid_upper_edge_outside_without_clamping(self):
        _,saved=tool.goal_from_estimate(estimate(),pose_factory)
        message=costmap_message();message.metadata.origin.position.x=-2.;message.metadata.size_x=2
        message.data=bytes(8)
        grid,raw=tool.costmap_snapshot(message,1,123.,'/ns/global_costmap/costmap_raw')
        decision=tool.geometry_decision(grid,raw,saved)
        self.assertTrue(decision['start_cell']['in_bounds']);self.assertFalse(decision['goal_cell']['in_bounds'])
        self.assertEqual(decision['goal_cell']['index_xy'],[2,1]);self.assertIsNone(decision['goal_cell']['cost'])
        self.assertFalse(decision['ready'])
        source=estimate();source.transform.translation.x=-2.000000001
        _,saved=tool.goal_from_estimate(source,pose_factory)
        self.assertFalse(tool.geometry_decision(grid,raw,saved)['start_cell']['in_bounds'])

    def test_costs_unknown_and_lethal_never_replace_original_smac_feasibility_decision(self):
        _,saved=tool.goal_from_estimate(estimate(),pose_factory)
        for cost in (0,253,254,255):
            message=costmap_message();message.data[10]=cost;message.data[12]=cost
            grid,raw=tool.costmap_snapshot(message,1,123.,'/ns/global_costmap/costmap_raw')
            with self.subTest(cost=cost):
                decision=tool.geometry_decision(grid,raw,saved)
                self.assertTrue(decision['ready']);self.assertFalse(decision['planner_feasibility_qualified'])
                self.assertEqual(decision['start_cell']['cost'],cost)

    def test_invalid_raw_grid_shape_frame_numeric_aliases_nonfinite_and_data_refuse_readiness(self):
        for change in ('frame','width_bool','empty','too_big','zero_resolution','infinite_origin','rotated','short_data','bool_data','bad_uint8'):
            message=costmap_message()
            if change=='frame':message.header.frame_id='odom'
            elif change=='width_bool':message.metadata.size_x=True
            elif change=='empty':message.metadata.size_x=0
            elif change=='too_big':message.metadata.size_x=4096;message.metadata.size_y=4096
            elif change=='zero_resolution':message.metadata.resolution=0.
            elif change=='infinite_origin':message.metadata.origin.position.y=float('inf')
            elif change=='rotated':message.metadata.origin.orientation.z=.1
            elif change=='short_data':message.data=bytes(31)
            elif change=='bool_data':message.data=[False]*32
            else:message.data=[256]*32
            with self.subTest(change=change):
                with self.assertRaises(ValueError):tool.costmap_snapshot(message,1,123.,'/ns/global_costmap/costmap_raw')

    def test_ros_numpy_uint8_payload_and_wrong_dtype_are_exactly_distinguished(self):
        import numpy as np
        message=costmap_message();message.data=np.arange(32,dtype=np.uint8)
        _,raw=tool.costmap_snapshot(message,1,123.,'/ns/global_costmap/costmap_raw')
        self.assertEqual(raw,bytes(range(32)))
        for payload in (np.arange(32,dtype=np.int64),np.zeros(32,dtype=np.bool_),
                        np.arange(32,dtype=np.uint8).reshape(4,8)):
            message.data=payload
            with self.subTest(dtype=str(payload.dtype),shape=payload.shape):
                with self.assertRaises(ValueError):tool.costmap_snapshot(message,1,123.,'/ns/global_costmap/costmap_raw')


if __name__=='__main__':unittest.main()
