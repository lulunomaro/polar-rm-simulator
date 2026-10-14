"""Unit ROS message stand-ins only; no DDS, TF producer, planner or SIL execution."""
import json
import math
from types import SimpleNamespace as NS
import threading
import unittest
from unittest.mock import patch
import sys

from tools.qa_pb_navigation_sil import (AlgorithmObserver,MAX_RECORDED_PATH_POSES,
    recorded_pose,recorded_transform,recorded_goal_uuid,recorded_path_result)


def header(sec=12,ns=345,frame='map'):
    return NS(stamp=NS(sec=sec,nanosec=ns),frame_id=frame)


def pose(x=2.,y=-3.,sec=12,ns=345):
    return NS(header=header(sec,ns),pose=NS(position=NS(x=x,y=y,z=.1),
        orientation=NS(x=0.,y=0.,z=.2,w=.98)))


def transform():
    value=pose()
    return NS(header=value.header,child_frame_id='base_link',
        transform=NS(translation=value.pose.position,rotation=value.pose.orientation))


def handle():
    return NS(goal_id=NS(uuid=list(range(16))),accepted=True)


def result():
    return NS(status=4,result=NS(path=NS(header=header(13,123),
        poses=[pose(sec=13,ns=123),pose(3.,-3.,sec=13,ns=456)]),
        planning_time=NS(sec=0,nanosec=100023)))


def observer():
    value=AlgorithmObserver.__new__(AlgorithmObserver)
    value.namespace='/polar_sil_0123456789abcdef/red_sentry'
    value.action_request_id='a'*32;value.action_request_seq=1;value.rows=[];value.lock=threading.Lock()
    value.receive_clock='host_perf_counter'
    return value


class GoalEvidenceTests(unittest.TestCase):
    def test_goal_tf_and_goal_can_be_independently_recomputed_without_now_or_truth(self):
        original=transform();goal=pose(3.,-3.)
        source=recorded_transform(original);selected=recorded_pose(goal)
        self.assertEqual(selected['header'],source['header'])
        translation=source['transform']['translation']
        self.assertEqual([selected['pose']['position']['x']-translation['x'],
                          selected['pose']['position']['y']-translation['y']],[1.,0.])
        self.assertEqual(source['header']['stamp'],{'sec':12,'nanosec':345})
        self.assertEqual(selected['pose']['orientation'],source['transform']['rotation'])
        original.header.stamp.nanosec=999
        self.assertEqual(source['header']['stamp']['nanosec'],345)
        self.assertNotIn('qpos',json.dumps(source))

    def test_full_path_original_stamps_duration_and_uuid_preserved(self):
        original=result();saved=recorded_path_result(original,handle())
        original.result.path.poses.clear()
        self.assertEqual(saved['status'],4)
        self.assertEqual(saved['goal_uuid'],'000102030405060708090a0b0c0d0e0f')
        self.assertEqual(len(saved['path']['poses']),2)
        self.assertEqual(saved['path']['header']['stamp'],{'sec':13,'nanosec':123})
        self.assertEqual(saved['path']['poses'][1]['header']['stamp'],{'sec':13,'nanosec':456})
        self.assertEqual(saved['path']['poses'][1]['pose']['position']['x'],3.)
        self.assertEqual(saved['planning_time'],{'sec':0,'nanosec':100023})
        self.assertNotIn('source_stamp_ns',saved)  # no flattened substituted stamp

    def test_failed_empty_path_keeps_real_action_status_and_default_message_header(self):
        original=result();original.status=6
        original.result.path.poses=[];original.result.path.header=header(0,0,'')
        saved=recorded_path_result(original,handle())
        self.assertEqual(saved['status'],6);self.assertEqual(saved['path']['poses'],[])
        self.assertEqual(saved['path']['header'],{'stamp':{'sec':0,'nanosec':0},'frame_id':''})

    def test_nonfinite_unbounded_bad_stamp_and_wrong_tf_frames_rejected(self):
        for field,bad in [('x',math.nan),('x',math.inf),('x',True),('x',1000001.)]:
            with self.subTest(bad=bad):
                value=pose();setattr(value.pose.position,field,bad)
                with self.assertRaises(ValueError):recorded_pose(value)
        for sec,ns in [(True,0),(1,.5),(1,1000000000),(-1,0)]:
            with self.subTest(sec=sec,ns=ns):
                with self.assertRaises(ValueError):recorded_pose(pose(sec=sec,ns=ns))
        value=transform();value.child_frame_id='camera_init'
        with self.assertRaises(ValueError):recorded_transform(value)
        value=transform();value.header.frame_id='odom'
        with self.assertRaises(ValueError):recorded_transform(value)

    def test_path_bound_status_type_and_exact_uuid_bytes_rejected(self):
        value=result();value.result.path.poses=[pose()]*(MAX_RECORDED_PATH_POSES+1)
        with self.assertRaisesRegex(ValueError,'path_oversized'):recorded_path_result(value,handle())
        for status in (True,4.,7):
            value=result();value.status=status
            with self.assertRaises(ValueError):recorded_path_result(value,handle())
        for uuid in ([0]*15,[0]*15+[True],[0]*15+[256]):
            with self.assertRaises(ValueError):recorded_goal_uuid(NS(goal_id=NS(uuid=uuid)))

    def test_recorder_binds_unique_request_namespace_action_and_only_observer_receive_clock(self):
        value=observer();payload=recorded_path_result(result(),handle())
        with patch('tools.qa_pb_navigation_sil.time.perf_counter',return_value=456.):
            value.record_algorithm('planner_path_result',action_name=value.namespace+'/compute_path_to_pose',
                                   planner_id='GridBased',use_start=False,**payload)
        row=value.rows[0]
        self.assertEqual(row['receive_wall'],456.)
        self.assertEqual(row['receive_clock'],'host_perf_counter')
        self.assertEqual(row['value']['action_request_id'],'a'*32)
        self.assertEqual(row['value']['action_request_seq'],1)
        self.assertEqual(row['value']['namespace'],value.namespace)
        self.assertEqual(row['value']['path'],payload['path'])
        self.assertEqual(row['value']['schema'],'polar.pb.algorithm-action-evidence.v1')
        with self.assertRaises(ValueError):value.record_algorithm('arbitrary_input')
        with self.assertRaises(ValueError):value.record_algorithm('goal_source_tf',invalid=math.nan)
        with self.assertRaises(ValueError):value.record_algorithm('planner_path_result',oversized='a'*(2*1024*1024))
        self.assertEqual(len(value.rows),1)

    def test_ending_lookup_records_original_tf_immediately_without_publishing_or_now_stamp(self):
        value=observer();source=transform();calls=[]
        def lookup(parent,child,when):
            calls.append((parent,child,when));return source
        value.buffer=NS(lookup_transform=lookup)
        fake_time=object()
        with patch.dict(sys.modules,{'rclpy.time':NS(Time=lambda:fake_time)}),\
                patch('tools.qa_pb_navigation_sil.time.perf_counter',return_value=789.):
            value.record_ending_estimate()
        self.assertEqual(calls,[('map','base_link',fake_time)])
        row=value.rows[0];self.assertEqual(row['topic_kind'],'ending_estimated_tf')
        self.assertEqual(row['receive_wall'],789.)
        self.assertEqual(row['value']['transform']['header']['stamp'],{'sec':12,'nanosec':345})
        self.assertTrue(row['value']['postprocess_only'])
        self.assertFalse(row['value']['algorithm_input'])
        self.assertFalse(row['value']['groundtruth_frame_comparison_qualified'])

    def test_missing_ending_tf_is_explicit_not_synthesized_and_before_any_goal_is_allowed(self):
        value=observer();value.action_request_id=None;value.action_request_seq=0
        def lookup(*args):raise LookupError('no actual tf')
        value.buffer=NS(lookup_transform=lookup)
        with patch.dict(sys.modules,{'rclpy.time':NS(Time=lambda:object())}):value.record_ending_estimate()
        row=value.rows[0]
        self.assertEqual(row['topic_kind'],'ending_estimated_tf_unavailable')
        self.assertEqual(row['value']['error_type'],'LookupError')
        self.assertNotIn('transform',row['value'])
        self.assertIsNone(row['value']['action_request_id'])
        with self.assertRaises(ValueError):value.record_algorithm('planner_goal_accepted')

    def test_request_metadata_cannot_alias_bool_sequence_or_invalid_local_id(self):
        for name,bad in [('action_request_seq',True),('action_request_seq',1.),
                         ('action_request_id','a'*31),('action_request_id','G'*32)]:
            value=observer();setattr(value,name,bad)
            with self.subTest(name=name,bad=bad):
                with self.assertRaises(ValueError):value.record_algorithm('goal_source_tf')
                self.assertEqual(value.rows,[])

    def test_real_ros_uint8_containers_preserve_all_uuid_bytes_without_scalar_int_coercion(self):
        from array import array
        import numpy as np
        original=bytes([0,255,128,127,*range(12)])
        for value in (original,bytearray(original),array('B',original),list(original),tuple(original),
                      np.frombuffer(original,dtype=np.uint8).copy()):
            with self.subTest(container=type(value).__name__):
                self.assertEqual(recorded_goal_uuid(NS(goal_id=NS(uuid=value))),original.hex())
        value=np.frombuffer(original,dtype=np.uint8).copy()
        snapshot=recorded_goal_uuid(NS(goal_id=NS(uuid=value)))
        value[:]=0
        self.assertEqual(snapshot,original.hex())

    def test_uuid_numeric_aliases_wrong_numpy_dtype_shape_and_signed_arrays_rejected(self):
        from array import array
        import numpy as np
        invalid=(np.zeros(16,dtype=np.int64),np.zeros(16,dtype=np.int8),np.zeros(16,dtype=np.float64),
            np.zeros(16,dtype=np.bool_),np.zeros((4,4),dtype=np.uint8),np.zeros(15,dtype=np.uint8),
            array('b',[0]*16),array('I',[0]*16),[np.uint8(0)]*16,bytes(15),bytearray(17))
        for value in invalid:
            with self.subTest(container=type(value).__name__,dtype=str(getattr(value,'dtype',''))):
                with self.assertRaises(ValueError):recorded_goal_uuid(NS(goal_id=NS(uuid=value)))

    def test_uuid_unknown_iterable_is_not_called_as_a_conversion_fallback(self):
        class Unknown:
            def __iter__(self):raise AssertionError('unreviewed iterable executed')
        with self.assertRaises(ValueError):recorded_goal_uuid(NS(goal_id=NS(uuid=Unknown())))

    def test_linux_receive_clock_is_explicit_and_does_not_retag_ros_stamp(self):
        value=observer();value.receive_clock='linux_local_perf_counter'
        with patch('tools.qa_pb_navigation_sil.time.perf_counter',return_value=87.5):
            value.record_algorithm('goal_source_tf',transform=recorded_transform(transform()))
        self.assertEqual(value.rows[0]['receive_clock'],'linux_local_perf_counter')
        self.assertEqual(value.rows[0]['receive_wall'],87.5)
        self.assertEqual(value.rows[0]['value']['transform']['header']['stamp'],{'sec':12,'nanosec':345})

    def test_receive_clock_invalid_enum_or_type_rejected_before_ros_import(self):
        namespace='/polar_sil_'+'a'*32+'/red_sentry'
        for clock in (None,True,'linux_monotonic','host_to_linux_converted'):
            with self.subTest(clock=clock):
                with self.assertRaisesRegex(ValueError,'observer_receive_clock_required'):
                    AlgorithmObserver(namespace,84,receive_clock=clock)


if __name__=='__main__':unittest.main()
