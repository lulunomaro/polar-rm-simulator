"""Opt-in actual rclpy/DDS + subprocess JSONL test with explicit test fixtures.

POLAR_RUN_ACTUAL_ROS2_BRIDGE=1 requires real rclpy/std_msgs. A missing runtime
then fails rather than skips. This does not run a navigation/detection algorithm
or physics and is not SIL/HIL/full-match qualification.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

from rm_match.integrations.ros2_bridge import ENVELOPE_SCHEMA,JSONL_SCHEMA
from rm_match.platform_v2.contracts import FRAMES,IDENTITY,action_for


@unittest.skipUnless(os.environ.get('POLAR_RUN_ACTUAL_ROS2_BRIDGE')=='1','actual ROS 2 explicitly disabled; fake transport tests are separate')
class ActualRos2BridgeTests(unittest.TestCase):
    def test_actual_dds_peer_subprocess_jsonl_identity_and_clean_exit(self):
        # No mock import or alternate transport in this opt-in test.
        import rclpy
        from rclpy.context import Context
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.qos import QoSProfile,HistoryPolicy,ReliabilityPolicy,DurabilityPolicy
        from std_msgs.msg import String
        root=Path(__file__).resolve().parents[1];adapter_id='custom_ros2_actual_fixture'
        namespace='/polar/actual_fixture_'+str(os.getpid())
        observation_topic=namespace+'/observation';action_topic=namespace+'/action'
        o=dict(schema='polar.sim.observation.v2',robot_id='red_sentry',episode=2,binding_epoch=3,
            observed_seq=1,sim_time=1.,wall_deadline=987654321.,frames=dict(FRAMES),
            own=dict(team='red',role='sentry',qpos=[0.]*5,qvel=[0.]*5,odom_xyyaw=[0.]*3,
                odom_vxyw=[0.]*3,hp=100.,ammo=10.,heat=0.,alive=True),
            referee=dict(phase='running',remaining_seconds=299.,emergency_stop=False),
            sensors=dict(camera=dict(available=False,reason='explicit_dds_unit_fixture_no_camera'),
                ranges=dict(available=False,reason='explicit_dds_unit_fixture_no_ranges')))
        expected=action_for(o,'navigation','velocity_body',dict(frame='base_link',vx_mps=0.,vy_mps=0.,wz_rps=0.))
        packets=[];errors=[];stop=threading.Event();child=None;worker=None;node=None;executor=None
        context=Context()
        with patch.dict(os.environ,dict(ROS_DOMAIN_ID='79',ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST',
                ROS_STATIC_PEERS='',ROS_LOCALHOST_ONLY='1',RMW_IMPLEMENTATION='rmw_fastrtps_cpp')):
            try:
                rclpy.init(args=[],context=context,domain_id=79)
                node=rclpy.create_node('polar_actual_fixture_peer_'+str(os.getpid()),context=context,
                    use_global_arguments=False,enable_rosout=False,start_parameter_services=False)
                qos=QoSProfile(history=HistoryPolicy.KEEP_LAST,depth=1,reliability=ReliabilityPolicy.BEST_EFFORT,durability=DurabilityPolicy.VOLATILE)
                publisher=node.create_publisher(String,action_topic,qos)
                def received(message):
                    try:
                        packet=json.loads(message.data);packets.append(packet)
                        if packet.get('adapter_id')!=adapter_id:raise AssertionError('unexpected route')
                        obs=packet['observation']
                        a=action_for(obs,'navigation','velocity_body',dict(frame='base_link',vx_mps=0.,vy_mps=0.,wz_rps=0.))
                        reply=String();reply.data=json.dumps(dict(schema=ENVELOPE_SCHEMA,type='action',adapter_id=adapter_id,action=a),allow_nan=False)
                        publisher.publish(reply)
                    except Exception as exc:errors.append(type(exc).__name__)
                node.create_subscription(String,observation_topic,received,qos)
                executor=SingleThreadedExecutor(context=context);executor.add_node(node)
                def run_peer():
                    try:
                        while not stop.is_set():executor.spin_once(timeout_sec=.01)
                    except Exception as exc:errors.append(type(exc).__name__)
                worker=threading.Thread(target=run_peer,name='actual-ros2-fixture-peer');worker.start()
                command=[sys.executable,'-u','-m','rm_match.integrations.ros2_bridge',
                    '--adapter-id',adapter_id,'--kind','navigation','--node-name','polar_actual_fixture_bridge',
                    '--observation-topic',observation_topic,'--action-topic',action_topic,'--domain-id','79']
                child=subprocess.Popen(command,cwd=root,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                requests=[dict(schema=JSONL_SCHEMA,op='reset',context={k:o[k] for k in ('episode','robot_id','binding_epoch')},config={}),
                    dict(schema=JSONL_SCHEMA,op='act',observation=o)]
                stdout,stderr=child.communicate(b''.join(json.dumps(row).encode()+b'\n' for row in requests),timeout=8.)
                self.assertEqual(child.returncode,0,stderr.decode(errors='replace')[-4096:])
                replies=[json.loads(line) for line in stdout.splitlines()]
                self.assertEqual(replies,[dict(schema=JSONL_SCHEMA,op='reset',ok=True),dict(schema=JSONL_SCHEMA,op='act',ok=True,action=expected)])
                self.assertEqual(packets,[dict(schema=ENVELOPE_SCHEMA,type='observation',adapter_id=adapter_id,observation=o)])
                self.assertEqual({k:replies[1]['action'][k] for k in IDENTITY},{k:o[k] for k in IDENTITY})
                self.assertEqual(errors,[])
            finally:
                if child is not None:
                    if child.poll() is None:
                        child.terminate()
                        try:child.wait(1.)
                        except subprocess.TimeoutExpired:child.kill();child.wait(1.)
                    for stream in (child.stdin,child.stdout,child.stderr):
                        if stream is not None:stream.close()
                stop.set()
                if worker is not None:
                    worker.join(.5);self.assertFalse(worker.is_alive(),'actual ROS peer did not stop')
                if executor is not None:self.assertTrue(executor.shutdown(timeout_sec=.15))
                if node is not None:node.destroy_node()
                rclpy.try_shutdown(context=context)
                self.assertFalse(context.ok(),'actual ROS context still active')
        print(json.dumps(dict(scope='actual DDS/JSONL explicit fixture; no physics or navigation algorithm',
            domain_id=79,bridge_pid=child.pid,bridge_exitcode=child.returncode,
            peer_thread_alive=worker.is_alive(),ros_context_ok=context.ok(),
            protocol_replies=len(replies),observations=len(packets),six_identity_echo=True,
            fixture_zero_motion=True,clean_shutdown=True)),flush=True)


if __name__=='__main__':unittest.main()
