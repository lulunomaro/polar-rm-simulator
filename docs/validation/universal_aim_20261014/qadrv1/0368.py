"""Explicit fake transport/JSONL fixture checks, not actual PB navigation."""
import base64
from copy import deepcopy
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import time
import unittest

from rm_match.integrations.pb_navigation_bridge import (NavigationSettings, NavigationBridge,
    BridgeError, sensor_bundle, sourced_result, navigation_status, serve_navigation, JSONL_SCHEMA)
from rm_match.integrations.pb_navigation_adapter import (PBNavigationAdapter, register_pb_navigation,MANIFEST_SCHEMA)
from rm_match.deployment.json_adapter import JsonLineAdapter
from rm_match.platform_v2.adapters import Registry
from rm_match.platform_v2.contracts import ContractError, IDENTITY, action_for
from rm_match.platform_v2.navigation_contracts import NAV_SCHEMA, NAV_FRAMES, POINT_ENCODING


def observation(seq=1,frame=1,start=900000000,end=1000000000):
    ext=dict(parent_frame='base_link',translation_m=[0.,0.,.5],rotation_xyzw=[0.,0.,0.,1.],calibration_id='unit_sensor_fixture')
    data=b''.join(struct.pack('<fffIBBBx',x,0.,0.,offset,reflectivity,0x10,line) for x,offset,reflectivity,line in [(1.,0,24,0),(2.,98000000,32,3)])
    return dict(schema=NAV_SCHEMA,robot_id='red_sentry',episode=2,binding_epoch=3,observed_seq=seq,
        sim_time=end*1e-9,wall_deadline=987654321.,frames=dict(NAV_FRAMES),
        own=dict(team='red',role='sentry',hp=100.,ammo=10.,heat=0.,alive=True),
        referee=dict(phase='running',remaining_seconds=299.,emergency_stop=False),
        sensors=dict(pointcloud=dict(available=True,reason='available',frame_id=frame,acquisition_start_ns=start,
            acquisition_end_ns=end,capture_sim_time=end*1e-9,frame='livox_frame',encoding=POINT_ENCODING,
            point_count=2,data_base64=base64.b64encode(data).decode(),range_min_m=.1,range_max_m=20.,
            time_quantization_ns=2000000,provenance='mujoco_ray_cast_nonrepeating_profile_v1',profile_sha256='1'*64,extrinsics=ext),
            imu=dict(available=True,reason='available',frame='livox_frame',capture_sim_time=end*1e-9,extrinsics=deepcopy(ext),
                provenance='mujoco_gyro_accelerometer_v1',samples=[dict(sample_sim_ns=t,angular_velocity_rps=[.1,.2,.3],
                    linear_acceleration_mps2=[0.,0.,9.81]) for t in range(start,end+1,2000000)])))


def action(o):return action_for(o,'navigation','velocity_body',dict(frame='base_link',vx_mps=.2,vy_mps=.1,wz_rps=.3))


def result(o):return sourced_result(o,action(o),cloud_frame_id=o['sensors']['pointcloud']['frame_id'],
    localization_stamp_ns=o['sensors']['pointcloud']['acquisition_end_ns'],
    controller_stamp_ns=round(o['sim_time']*1e9),controller_id=NavigationSettings().controller_id)


class Clock:
    def __init__(self):self.now=100.
    def __call__(self):return self.now


class FakeTransport:
    def __init__(self,core,response=None,odom=None):self.core=core;self.response=response;self.odom=odom;self.bundles=[]
    def publish_bundle(self,bundle,request):self.bundles.append((bundle,json.loads(request)))
    def spin_once(self,timeout):
        if self.odom is not None:self.core.receive_odom_stamp(self.odom);self.odom=None
        if self.response is not None:self.core.receive_result(json.dumps(self.response));self.response=None
        else:self.core.clock.now+=timeout
    def wait_ready(self,timeout):pass


class NavigationBridgeTests(unittest.TestCase):
    def test_generation_clock_and_static_tf_are_validated_trusted_local_topics(self):
        settings=NavigationSettings(clock_topic='/polar_sil_unit/red_sentry/clock',tf_static_topic='/polar_sil_unit/red_sentry/tf_static')
        self.assertTrue(settings.clock_topic.startswith('/polar_sil_unit/'))
        for change in [dict(clock_topic='relative'),dict(tf_static_topic='/bad/../tf'),dict(clock_topic='/livox/imu')]:
            with self.subTest(change=change),self.assertRaises(BridgeError):NavigationSettings(**change)

    def core(self):
        clock=Clock();c=NavigationBridge(NavigationSettings(expected_episode=2,expected_binding_epoch=3),clock=clock);o=observation()
        c.reset({k:o[k] for k in ('robot_id','episode','binding_epoch')},{})
        return c,clock,o

    def test_exact_pixels_offsets_and_imu_no_orientation(self):
        o=observation();b=sensor_bundle(o)
        self.assertEqual(b['custom']['timebase'],900000000)
        self.assertEqual(b['custom']['header']['stamp'],dict(sec=0,nanosec=900000000))
        self.assertEqual(b['custom']['points'][1],dict(x=2.,y=0.,z=0.,offset_time=98000000,reflectivity=32,tag=16,line=3))
        self.assertEqual(b['pointcloud']['data'],base64.b64decode(o['sensors']['pointcloud']['data_base64']))
        self.assertEqual(b['pointcloud']['point_step'],20);self.assertEqual(b['pointcloud']['row_step'],40)
        self.assertEqual(b['imu'][0]['header']['stamp'],dict(sec=0,nanosec=900000000))
        self.assertEqual(b['imu'][-1]['header']['stamp'],dict(sec=1,nanosec=0))
        self.assertEqual(b['imu'][0]['orientation_covariance'][0],-1)
        self.assertNotIn('orientation',b['imu'][0]);self.assertNotIn('odom',b)
        o['sensors']['imu']['samples'][0]['angular_velocity_rps'][0]=100
        self.assertEqual(b['imu'][0]['angular_velocity'][0],.1)

    def test_sourced_action_original_identity_and_foreign_deadline_echo(self):
        c,clock,o=self.core();t=FakeTransport(c,result(o));kind,a=c.exchange(o,t)
        self.assertEqual(kind,'action');self.assertEqual(a,action(o))
        req=t.bundles[0][1]
        for k in IDENTITY:self.assertEqual(req[k],o[k])
        self.assertEqual(a['wall_deadline'],987654321.);self.assertLess(clock(),100.05)

    def test_waiting_has_no_command_and_same_instance_accepts_next_actual_scan(self):
        c,_,o=self.core();kind,v=c.exchange(o,FakeTransport(c))
        self.assertEqual(kind,'status');self.assertEqual(v,navigation_status(o,'pending_localization'));self.assertNotIn('command',v)
        nxt=observation(2,2,1000000000,1100000000)
        kind,v=c.exchange(nxt,FakeTransport(c,odom=1100000000))
        self.assertEqual(kind,'status');self.assertEqual(v['status'],'no_associated_command')
        nxt=observation(3,3,1100000000,1200000000)
        self.assertEqual(c.exchange(nxt,FakeTransport(c,result(nxt))),('action',action(nxt)))

    def test_delayed_old_result_bare_twist_missing_source_and_future_odom_rejected(self):
        for edit in ('oldseq','epochbool','oldframe','oldodom','futurecontroller','source_missing','twist','overspeed','unknown'):
            with self.subTest(edit=edit):
                c,_,o=self.core();c.begin(o);r=result(o)
                if edit=='oldseq':r['action']['observed_seq']=0
                elif edit=='epochbool':r['action']['episode']=True
                elif edit=='oldframe':r['source']['cloud_frame_id']=0
                elif edit=='oldodom':r['source']['localization_stamp_ns']=899999999
                elif edit=='futurecontroller':r['source']['controller_stamp_ns']=1000000001
                elif edit=='source_missing':del r['source']
                elif edit=='twist':r=dict(linear=dict(x=.2,y=0,z=0),angular=dict(z=0))
                elif edit=='overspeed':r['action']['command']['wz_rps']=-6.
                else:r['source']['world_xy']=[1,2]
                with self.assertRaises(ContractError):c.receive_result(json.dumps(r))
                self.assertIsNone(c._result)

    def test_mutation_cannot_relabel_or_replace_pending_and_expired_result_rejects(self):
        c,clock,o=self.core();original=deepcopy(o);c.begin(o)
        o['observed_seq']=999;o['sensors']['pointcloud']['frame_id']=888
        c.receive_result(json.dumps(result(original)));self.assertEqual(c._result,action(original))
        c,clock,o=self.core();c.begin(o);clock.now+=.05
        with self.assertRaises(BridgeError):c.receive_result(json.dumps(result(o)))

    def test_duplicate_and_reset_and_old_frame_rejected(self):
        c,_,o=self.core();c.begin(o);c.receive_result(json.dumps(result(o)))
        with self.assertRaises(BridgeError):c.receive_result(json.dumps(result(o)))
        with self.assertRaises(BridgeError):c.reset(c.context,{})
        c._pending=None;c._result=None
        with self.assertRaises(BridgeError):c.begin(observation(2,1))

    def test_stack_explicit_expected_generation_rejects_rebind_and_episode_alias(self):
        for episode,epoch in ((1,3),(2,4),(True,3)):
            with self.subTest(episode=episode,epoch=epoch):
                c=NavigationBridge(NavigationSettings(expected_episode=2,expected_binding_epoch=3))
                with self.assertRaises(ContractError):c.reset(dict(robot_id='red_sentry',episode=episode,binding_epoch=epoch),{})

    def test_jsonl_status_exact_shape(self):
        c,_,o=self.core();inp=io.BytesIO((json.dumps(dict(schema=JSONL_SCHEMA,op='act',observation=o))+'\n').encode());out=io.BytesIO()
        serve_navigation(c,FakeTransport(c),inp,out);r=json.loads(out.getvalue())
        self.assertEqual(set(r),{'schema','op','ok','status'});self.assertEqual(r['status'],navigation_status(o,'pending_localization'))


class HostAdapterTests(unittest.TestCase):
    def adapter(self):
        row=dict(adapter_id='custom_pb_navigation',kind='navigation',label='unit',required_sensors=['pointcloud','imu'])
        return PBNavigationAdapter({},registration=row,manifest='unused',manifest_sha='0'*64)

    def test_hook_default_illegal_response_behavior_unchanged(self):
        a=JsonLineAdapter.__new__(JsonLineAdapter)
        a._validate_response(dict(schema=JSONL_SCHEMA,op='reset',ok=True),dict(op='reset'))
        for value in (dict(schema=JSONL_SCHEMA,op='act',ok=True,status={}),dict(schema=JSONL_SCHEMA,op='act',ok=False,action={}),dict(schema=JSONL_SCHEMA,op='reset',ok=True,action={})):
            with self.subTest(value=value),self.assertRaises(ContractError):a._validate_response(value,dict(op='act'))

    def test_status_xor_action_and_strict_status_identity(self):
        a=self.adapter();o=observation();packet=dict(op='act',observation=o)
        s=dict(schema=JSONL_SCHEMA,op='act',ok=True,status=navigation_status(o,'pending_localization'))
        a._validate_response(s,packet)
        for edit in ('both','none','truth','oldseq','boolepoch'):
            with self.subTest(edit=edit):
                v=deepcopy(s)
                if edit=='both':v['action']=action(o)
                elif edit=='none':del v['status']
                elif edit=='truth':v['status']['command']={'vx_mps':0}
                elif edit=='oldseq':v['status']['observed_seq']=0
                else:v['status']['binding_epoch']=True
                with self.assertRaises(ContractError):a._validate_response(v,packet)

    def test_actual_jsonl_child_wait_status_preserves_child_and_cleanup(self):
        # This is an explicit fake child, not a ROS navigation qualification.
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);script=p/'fixture.py';manifest=p/'manifest.json'
            script.write_text('''import json,sys
for line in sys.stdin:
 r=json.loads(line);v=dict(schema=r['schema'],op=r['op'],ok=True)
 if r['op']=='act':
  o=r['observation'];v['status']=dict(schema='polar.sim.navigation-status.v1',kind='navigation',status='pending_localization',**{k:o[k] for k in ('robot_id','episode','binding_epoch','observed_seq','sim_time','wall_deadline')})
 print(json.dumps(v),flush=True)
''')
            manifest.write_text(json.dumps(dict(schema=MANIFEST_SCHEMA,adapters=[dict(adapter_id='custom_pb_navigation',label='explicit fake child fixture',command=[sys.executable,'-u',str(script)],cwd='.')])) )
            registry=Registry();register_pb_navigation(registry,manifest);a=registry.create('custom_pb_navigation',{})
            d=registry.get('custom_pb_navigation').descriptor
            self.assertEqual(d['supported_robots'],['red_sentry'])
            self.assertEqual(d['observation_profile'],'pointcloud_imu_v1')
            o=observation();o['wall_deadline']=time.perf_counter()+2
            try:
                a.reset({k:o[k] for k in ('robot_id','episode','binding_epoch')});pid=a.process.pid
                self.assertEqual(a.act(o)['status'],'pending_localization')
                nxt=observation(2,2,1000000000,1100000000);nxt['wall_deadline']=time.perf_counter()+2
                self.assertEqual(a.act(nxt)['observed_seq'],2);self.assertEqual(a.process.pid,pid);self.assertFalse(a.failed)
            finally:
                child=a.process;a.close()
            self.assertIsNotNone(child.poll());self.assertFalse(a.thread.is_alive());self.assertTrue(child.stdin.closed);self.assertTrue(child.stdout.closed)

    def test_manifest_hash_change_rejected_before_spawn_and_config_no_http_command(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'m.json';v=dict(schema=MANIFEST_SCHEMA,adapters=[dict(adapter_id='custom_pb_navigation',label='unit',command=[sys.executable,'-u','-c','pass'],cwd='.')])
            p.write_text(json.dumps(v));r=Registry();register_pb_navigation(r,p)
            with self.assertRaises(ContractError):r.create('custom_pb_navigation',dict(command=['bad']))
            a=r.create('custom_pb_navigation',{});p.write_text(json.dumps(v)+' ')
            with self.assertRaises(ContractError):a.reset(dict(robot_id='red_sentry',episode=1,binding_epoch=1))
            self.assertIsNone(a.process)


if __name__=='__main__':unittest.main()
