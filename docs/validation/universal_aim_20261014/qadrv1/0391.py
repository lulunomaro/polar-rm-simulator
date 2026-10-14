"""Fake transport contract tests; these do not qualify actual DDS or ROS 2."""
import builtins
import base64
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from rm_match.integrations.ros2_bridge import (BridgeError,BridgeSettings,
    EnvelopeBridge,ENVELOPE_SCHEMA,JSONL_SCHEMA,MAX_RESPONSE,parse_json,serve)
from rm_match.integrations.ros2_bridge_transport import RclpyTransport
from rm_match.platform_v2.contracts import FRAMES,IDENTITY,action_for,ContractError


def observation(seq=1,**changes):
    value=dict(schema='polar.sim.observation.v2',robot_id='red_sentry',episode=2,
        binding_epoch=3,observed_seq=seq,sim_time=1.,wall_deadline=987654321.,
        frames=dict(FRAMES),own=dict(team='red',role='sentry',qpos=[0.]*5,qvel=[0.]*5,
            odom_xyyaw=[0.]*3,odom_vxyw=[0.]*3,hp=100.,ammo=10.,heat=0.,alive=True),
        referee=dict(phase='running',remaining_seconds=299.,emergency_stop=False),
        sensors=dict(camera=dict(available=False,reason='unit_fixture_no_camera'),
            ranges=dict(available=False,reason='unit_fixture_no_ranges')))
    value.update(changes);return value


def settings(kind='navigation'):
    return BridgeSettings('custom_ros2_'+kind,kind,'polar_unit_'+kind,
        '/polar/unit_'+kind+'/observation','/polar/unit_'+kind+'/action',78,.08)


def action(o,kind='navigation'):
    if kind=='navigation':return action_for(o,kind,'velocity_body',dict(frame='base_link',vx_mps=.2,vy_mps=0.,wz_rps=0.))
    return action_for(o,kind,'gimbal_target',dict(frame='base_link',yaw_rad=.1,pitch_rad=.2,active=True,confidence=None,fire_permission=False))


def envelope(a,kind='navigation'):
    return json.dumps(dict(schema=ENVELOPE_SCHEMA,type='action',adapter_id=settings(kind).adapter_id,action=a),allow_nan=False)


class Clock:
    def __init__(self):self.now=100.
    def __call__(self):return self.now
    def advance(self,seconds):self.now+=seconds


class FakeTransport:
    """Explicit test-only transport; production code never imports this class."""
    def __init__(self,core,kind='navigation'):self.core=core;self.kind=kind;self.rows=[];self.deliver=True
    def publish(self,payload):self.rows.append(payload)
    def wait_ready(self,timeout):pass
    def spin_once(self,timeout):
        if self.deliver:
            self.deliver=False;o=json.loads(self.rows[-1])['observation'];self.core.receive_action(envelope(action(o,self.kind),self.kind))
        else:self.core.clock.advance(timeout)


class BridgeContractTests(unittest.TestCase):
    def core(self,kind='navigation'):
        clock=Clock();core=EnvelopeBridge(settings(kind),clock=clock);o=observation()
        core.reset({k:o[k] for k in ('episode','robot_id','binding_epoch')},{})
        return core,clock,o

    def test_full_observation_and_action_preserved_and_foreign_wall_clock_is_only_echo(self):
        core,clock,o=self.core();transport=FakeTransport(core)
        result=core.exchange(o,transport)
        self.assertEqual(json.loads(transport.rows[0]),dict(schema=ENVELOPE_SCHEMA,type='observation',adapter_id=settings().adapter_id,observation=o))
        self.assertEqual(result,action(o));self.assertEqual(result['wall_deadline'],987654321.)
        self.assertEqual(clock(),100.)

    def test_full_sensor_dto_fields_pass_unchanged_and_caller_mutation_does_not_rebind_pending(self):
        core,_,o=self.core();raw=b'\x01\x02\x03\x04\x05\x06'
        camera=dict(available=True,reason='available',frame_id=17,capture_sim_time=1.,
            own_qpos_at_capture=[0.]*5,own_qvel_at_capture=[0.]*5,own_odom_at_capture=[0.]*3,
            own_odom_velocity_at_capture=[0.]*3,image=dict(encoding='rgb8',width=2,height=1,
                stride_bytes=6,data_base64=base64.b64encode(raw).decode()),
            intrinsics=dict(fx=1.,fy=1.,cx=.5,cy=0.,distortion_model='brown_conrady_5',distortion=[0.]*5),
            extrinsics=dict(parent_frame='gimbal_link',translation_m=[0.]*3,rotation_xyzw=[0.,0.,0.,1.],calibration_id='explicit_pixel_unit_fixture'),provenance='simulated_raw_camera')
        o['sensors']['camera']=camera;o['sensors']['ranges']=dict(available=True,reason='available',
            ranges_m=[1.,2.],angles_rad=[0.,1.],range_max_m=8.,capture_sim_time=1.,frame='base_link',provenance='ideal_simulated_range')
        original=deepcopy(o);wire=core.begin(o)
        o['sensors']['camera']['frame_id']=18;o['sensors']['camera']['image']['data_base64']='AAAA'
        o['observed_seq']=2;o['own']['qpos'][0]=999.
        self.assertEqual(json.loads(wire)['observation'],original)
        core.receive_action(envelope(action(original)));self.assertEqual(core.poll(),action(original))

    @unittest.skipIf(importlib.util.find_spec('rclpy') is not None,'negative real-process check requires ROS to be absent')
    def test_real_missing_dependency_process_fails_without_protocol_output(self):
        root=Path(__file__).resolve().parents[1]
        cmd=[sys.executable,'-u','-m','rm_match.integrations.ros2_bridge','--adapter-id','custom_ros2_missing',
            '--kind','navigation','--node-name','polar_missing','--observation-topic','/polar/missing/observation',
            '--action-topic','/polar/missing/action','--domain-id','78']
        result=subprocess.run(cmd,cwd=root,input=b'',capture_output=True,timeout=5.)
        self.assertEqual(result.returncode,2);self.assertEqual(result.stdout,b'')
        self.assertEqual(result.stderr.strip(),b'ros2_rclpy_std_msgs_unavailable')

    def test_cli_separates_python_and_c_stdout_with_explicit_fake_transport(self):
        # Only a test child receives this explicit fake transport injection.
        # Production entry has no switch/environment to enable a fake backend.
        script='''
import json,os
from rm_match.integrations import ros2_bridge as bridge,ros2_bridge_transport as transport
from rm_match.platform_v2.contracts import action_for
class TestOnlyFake:
    def __init__(self,settings,receive):
        self.settings=settings;self.receive=receive;print('fake Python ROS console')
        os.write(1,b'fake C ROS console\\n')
    def wait_ready(self,timeout):print('fake discovery console')
    def publish(self,payload):
        obs=json.loads(payload)['observation']
        a=action_for(obs,'navigation','velocity_body',dict(frame='base_link',vx_mps=.2,vy_mps=0.,wz_rps=0.))
        self.receive(json.dumps(dict(schema=bridge.ENVELOPE_SCHEMA,type='action',adapter_id=self.settings.adapter_id,action=a)))
    def spin_once(self,timeout):raise AssertionError('immediate explicit fixture already responded')
    def close(self):print('fake close console')
transport.RclpyTransport=TestOnlyFake
raise SystemExit(bridge.main(['--adapter-id','custom_ros2_navigation','--kind','navigation','--node-name','polar_fake_stdout','--observation-topic','/polar/fake/observation','--action-topic','/polar/fake/action','--domain-id','78']))
'''
        root=Path(__file__).resolve().parents[1];o=observation()
        packets=[dict(schema=JSONL_SCHEMA,op='reset',context={k:o[k] for k in ('episode','robot_id','binding_epoch')},config={}),dict(schema=JSONL_SCHEMA,op='act',observation=o)]
        result=subprocess.run([sys.executable,'-u','-c',script],cwd=root,
            input=b''.join(json.dumps(p).encode()+b'\n' for p in packets),capture_output=True,timeout=5.)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
        replies=[json.loads(row) for row in result.stdout.splitlines()]
        self.assertEqual(replies,[dict(schema=JSONL_SCHEMA,op='reset',ok=True),dict(schema=JSONL_SCHEMA,op='act',ok=True,action=action(o))])
        self.assertIn(b'fake Python ROS console',result.stderr);self.assertIn(b'fake C ROS console',result.stderr)

    def test_each_identity_mismatch_is_rejected_without_consuming_pending(self):
        for key in IDENTITY:
            core,_,o=self.core();core.begin(o);a=action(o)
            a[key]='blue_sentry' if key=='robot_id' else a[key]+1
            with self.subTest(key=key),self.assertRaises(ContractError):core.receive_action(envelope(a))
            core.receive_action(envelope(action(o)));self.assertEqual(core.poll(),action(o))

    def test_numeric_echo_type_and_bool_are_not_relabelled(self):
        for key,new in [('sim_time',1),('episode',True),('wall_deadline',987654321)]:
            core,_,o=self.core();core.begin(o);a=action(o);a[key]=new
            with self.subTest(key=key),self.assertRaises(ContractError):core.receive_action(envelope(a))

    def test_route_unknown_fields_twist_and_non_json_values_reject(self):
        variants=[];o=observation();original=json.loads(envelope(action(o)))
        for key,new in [('schema','future'),('type','observation'),('adapter_id','custom_other')]:
            value=deepcopy(original);value[key]=new;variants.append(json.dumps(value))
        value=deepcopy(original);value['frame_header']={'stamp':1};variants.append(json.dumps(value))
        variants.extend([json.dumps({'linear':{'x':1},'angular':{'z':0}}),'NaN','{"schema":"a","schema":"b"}','not JSON'])
        for value in variants:
            core,_,o=self.core();core.begin(o)
            with self.subTest(value=value[:60]),self.assertRaises(ContractError):core.receive_action(value)

    def test_local_expiry_duplicate_and_new_generation_cannot_reuse_old_action(self):
        core,clock,o=self.core();core.begin(o);clock.advance(.08)
        with self.assertRaisesRegex(BridgeError,'timeout'):core.receive_action(envelope(action(o)))
        with self.assertRaisesRegex(BridgeError,'no_pending'):core.receive_action(envelope(action(o)))
        newer=EnvelopeBridge(settings(),clock=clock);n=observation(binding_epoch=4)
        newer.reset({k:n[k] for k in ('episode','robot_id','binding_epoch')},{})
        newer.begin(n)
        with self.assertRaises(ContractError):newer.receive_action(envelope(action(o)))
        newer.receive_action(envelope(action(n)))
        with self.assertRaisesRegex(BridgeError,'no_pending'):newer.receive_action(envelope(action(n)))

    def test_single_pending_capacity_and_sequence_high_water(self):
        core,_,o=self.core();core.begin(o)
        with self.assertRaisesRegex(BridgeError,'pending_capacity'):core.begin(observation(2))
        core.receive_action(envelope(action(o)))
        with self.assertRaisesRegex(BridgeError,'pending_capacity'):core.begin(observation(2))
        core.poll()
        for seq in (0,1):
            with self.subTest(seq=seq),self.assertRaisesRegex(BridgeError,'sequence'):core.begin(observation(seq))
        core.begin(observation(2))

    def test_oversize_utf8_duplicate_keys_and_nested_nonfinite_are_rejected(self):
        for raw in ('x'*(MAX_RESPONSE+1),'猫'*(MAX_RESPONSE//2),b'\xff','{"a":{"b":1,"b":2}}','{"x":Infinity}'):
            with self.subTest(prefix=str(raw)[:20]),self.assertRaises(BridgeError):parse_json(raw,MAX_RESPONSE)
        core,_,o=self.core();core.begin(o)
        with self.assertRaisesRegex(BridgeError,'oversized'):core.receive_action('x'*(MAX_RESPONSE+1))

    def test_observation_strict_and_reset_binding_config_cannot_select_commands_or_topics(self):
        for config in ({'command':['wrong']},{'node_name':'wrong'},{'action_topic':'/wrong'}):
            core=EnvelopeBridge(settings())
            with self.subTest(config=config),self.assertRaises(ContractError):core.reset(dict(episode=2,robot_id='red_sentry',binding_epoch=3),config)
        core,_,o=self.core()
        with self.assertRaisesRegex(BridgeError,'reset_once'):core.reset(dict(core.context),{})
        for changes in ({'episode':3},{'robot_id':'blue_sentry'},{'binding_epoch':4},{'future_truth':{'world_xy':[1.,2.]}}):
            with self.subTest(changes=changes),self.assertRaises(ContractError):core.begin(observation(**changes))

    def test_no_automatic_fire_and_no_action_rewrite(self):
        core,_,o=self.core('aim');core.begin(o);a=action(o,'aim');a['command']['fire_permission']=True
        with self.assertRaisesRegex(BridgeError,'automatic_fire'):core.receive_action(envelope(a,'aim'))
        accepted=action(o,'aim');core.receive_action(envelope(accepted,'aim'));self.assertEqual(core.poll(),accepted)

    def test_timeout_after_parsing_and_before_delivery_not_refreshed(self):
        core,clock,o=self.core();core.begin(o);original=__import__('rm_match.integrations.ros2_bridge',fromlist=['validate_action']).validate_action
        def delayed(*args):value=original(*args);clock.advance(.08);return value
        with patch('rm_match.integrations.ros2_bridge.validate_action',delayed),self.assertRaisesRegex(BridgeError,'timeout'):core.receive_action(envelope(action(o)))
        core,clock,o=self.core();core.begin(o);core.receive_action(envelope(action(o)));clock.advance(.08)
        with self.assertRaisesRegex(BridgeError,'timeout'):core.poll()

    def test_jsonl_output_only_real_reset_and_matching_action(self):
        core=EnvelopeBridge(settings(),clock=Clock());transport=FakeTransport(core);o=observation()
        rows=[dict(schema=JSONL_SCHEMA,op='reset',context={k:o[k] for k in ('episode','robot_id','binding_epoch')},config={}),dict(schema=JSONL_SCHEMA,op='act',observation=o)]
        source=io.BytesIO(b''.join(json.dumps(row).encode()+b'\n' for row in rows));target=io.BytesIO()
        serve(core,transport,source,target);replies=[json.loads(row) for row in target.getvalue().splitlines()]
        self.assertEqual(replies,[dict(schema=JSONL_SCHEMA,op='reset',ok=True),dict(schema=JSONL_SCHEMA,op='act',ok=True,action=action(o))])

    def test_timeout_missing_line_and_unknown_operation_have_no_synthetic_reply(self):
        core,_,o=self.core();transport=FakeTransport(core);transport.deliver=False;target=io.BytesIO()
        with self.assertRaisesRegex(BridgeError,'timeout'):serve(core,transport,io.BytesIO(json.dumps(dict(schema=JSONL_SCHEMA,op='act',observation=o)).encode()+b'\n'),target)
        self.assertEqual(target.getvalue(),b'')
        for raw in (b'{}',b'{"schema":"polar.sim.adapter.jsonl.v1","op":"control"}\n'):
            target=io.BytesIO()
            with self.subTest(raw=raw),self.assertRaises(BridgeError):serve(core,transport,io.BytesIO(raw),target)
            self.assertEqual(target.getvalue(),b'')

    def test_reset_graph_failure_emits_no_success_ack_or_observation(self):
        core=EnvelopeBridge(settings(),clock=Clock());transport=FakeTransport(core)
        def missing(timeout):raise BridgeError('ros2_algorithm_graph_unavailable')
        transport.wait_ready=missing;target=io.BytesIO();o=observation()
        request=dict(schema=JSONL_SCHEMA,op='reset',context={k:o[k] for k in ('episode','robot_id','binding_epoch')},config={})
        with self.assertRaisesRegex(BridgeError,'graph_unavailable'):serve(core,transport,io.BytesIO(json.dumps(request).encode()+b'\n'),target)
        self.assertEqual(target.getvalue(),b'');self.assertEqual(transport.rows,[])

    def test_invalid_fixed_settings_and_missing_dependency_explicit_failure(self):
        good=settings()
        for key,value in [('adapter_id','aim_native_rmcs_v1'),('kind','fire'),('node_name','--ros-args'),('action_topic','/cmd_vel:=/other'),('domain_id',True),('domain_id',102),('response_timeout',float('nan')),('response_timeout',1.)]:
            changes=dict(vars(good));changes[key]=value
            with self.subTest(key=key),self.assertRaises(BridgeError):BridgeSettings(**changes)
        original=builtins.__import__
        def unavailable(name,*args,**kwargs):
            if name=='rclpy' or name.startswith('rclpy.'):raise ModuleNotFoundError('unit forced missing ROS')
            return original(name,*args,**kwargs)
        with patch.dict('os.environ',{},clear=True),patch('builtins.__import__',unavailable),self.assertRaisesRegex(BridgeError,'rclpy_std_msgs_unavailable'):
            RclpyTransport(good,lambda _:None)


if __name__=='__main__':unittest.main()
