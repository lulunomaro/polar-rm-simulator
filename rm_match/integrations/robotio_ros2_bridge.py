"""Optional ROS 2 envelope route for generic pointcloud navigation/decision.

Uses the actual rclpy transport; imports remain optional. Algorithm nodes must
echo original context and negotiate capabilities. Bare/latest Twist or Pose
messages are not silently associated with a simulator request.
"""
from __future__ import annotations
import argparse
import copy
from dataclasses import dataclass
import os
import sys
import time
from .ros2_bridge import (BridgeError,BridgeSettings,parse_json,encode_json,
    ENVELOPE_SCHEMA,JSONL_SCHEMA,MAX_REQUEST,MAX_RESPONSE)
from ..platform_v2.contracts import IDENTITY,exact,identity

@dataclass(frozen=True)
class RobotIOSettings:
    adapter_id:str
    kind:str
    node_name:str
    observation_topic:str
    action_topic:str
    domain_id:int
    response_timeout:float=.05
    goal_input:bool=False
    def __post_init__(self):
        BridgeSettings(self.adapter_id,'navigation',self.node_name,self.observation_topic,self.action_topic,self.domain_id,self.response_timeout)
        if self.kind not in ('navigation','decision') or type(self.kind) is not str or type(self.goal_input) is not bool:
            raise BridgeError('robotio_ros2_kind_or_goal_profile')
        if self.kind=='decision' and self.goal_input:raise BridgeError('robotio_decision_not_navigation')
        if self.response_timeout>(.05 if self.kind=='navigation' else .15):raise BridgeError('robotio_ros2_original_budget')

class RobotIOEnvelopeBridge:
    def __init__(self,settings,*,clock=time.monotonic):
        self.settings=settings;self.clock=clock;self.context=None;self._pending=None
        self._response=None;self._deadline=None;self._seq=-1;self._closed=False
        self._negotiating=False;self._negotiated=False
        if settings.kind=='navigation':
            from ..deployment.navigation_plugin import CAPABILITIES
            self.capabilities=dict(copy.deepcopy(CAPABILITIES),goal_input_modes=['decision_intent_v1'] if settings.goal_input else [])
        else:
            from ..deployment.decision_plugin import CAPABILITIES
            self.capabilities=copy.deepcopy(CAPABILITIES)
    def reset(self,context,config):
        if self._closed or self.context is not None:raise BridgeError('robotio_ros2_reset_once')
        exact(config,(),'robotio_ros2_binding_config');exact(context,('episode','robot_id','binding_epoch'),'robotio_ros2_context')
        identity(dict(context,observed_seq=0,sim_time=0.,wall_deadline=0.))
        self.context=dict(context)
    def negotiate(self,transport):
        if self.context is None or self._negotiated:raise BridgeError('robotio_ros2_negotiation_state')
        self._deadline=self.clock()+1.;self._negotiating=True;self._response=None
        transport.wait_ready(max(0.,self._deadline-self.clock()))
        if self.clock()>=self._deadline:raise BridgeError('robotio_ros2_graph_budget')
        transport.publish(encode_json(dict(schema=ENVELOPE_SCHEMA,type='capabilities_request',
            adapter_id=self.settings.adapter_id,context=self.context,capabilities=self.capabilities),MAX_REQUEST).decode())
        while self._response is None:
            self._check_deadline();transport.spin_once(min(.005,max(0.,self._deadline-self.clock())))
        self._check_deadline();self._negotiating=False;self._response=None;self._negotiated=True
    def _check_deadline(self):
        if self._closed or self._deadline is None or self.clock()>=self._deadline:
            self._pending=None;self._response=None;raise BridgeError('robotio_ros2_response_expired')
    def begin(self,observation,intent=None):
        if not self._negotiated or self._closed or self._pending is not None or self._response is not None:
            raise BridgeError('robotio_ros2_not_ready_or_pending')
        self._deadline=self.clock()+self.settings.response_timeout
        if self.settings.kind=='navigation':
            from ..platform_v2.navigation_contracts import validate_navigation_observation
            from ..deployment.navigation_plugin import validate_intent
            o=validate_navigation_observation(observation)
            if self.settings.goal_input:
                if intent is None:raise BridgeError('robotio_ros2_goal_intent_required')
                intent=validate_intent(intent,o)
            elif intent is not None:raise BridgeError('robotio_ros2_goal_input_unsupported')
        else:
            from ..platform_v2.decision_contracts import validate_decision_observation
            o=validate_decision_observation(observation)
            if intent is not None:raise BridgeError('robotio_ros2_decision_intent_input')
        if any(type(o[k]) is not type(v) or o[k]!=v for k,v in self.context.items()) or o['observed_seq']<=self._seq:
            raise BridgeError('robotio_ros2_observation_context_or_sequence')
        packet=dict(schema=ENVELOPE_SCHEMA,type='observation',adapter_id=self.settings.adapter_id,observation=o)
        if intent is not None:packet['intent']=intent
        payload=encode_json(packet,MAX_REQUEST).decode();self._check_deadline()
        self._pending=o;self._seq=o['observed_seq'];return payload
    def receive_action(self,payload):
        self._check_deadline();value=parse_json(payload,MAX_RESPONSE)
        if self._negotiating:
            exact(value,('schema','type','adapter_id','context','capabilities'),'robotio_ros2_capability_response')
            if value['type']!='capabilities' or value['context']!=self.context or any(type(value['context'].get(k)) is not type(v) for k,v in self.context.items()):
                raise BridgeError('robotio_ros2_capability_context')
            if value['capabilities']!=self.capabilities:raise BridgeError('robotio_ros2_capability_mismatch')
            if self.settings.kind=='navigation':
                from ..deployment.navigation_plugin import validate_capabilities
            else:
                from ..deployment.decision_plugin import validate_capabilities
            validate_capabilities(value['capabilities']);field='capabilities';result=value[field]
        else:
            if self._pending is None or self._response is not None:raise BridgeError('robotio_ros2_no_pending_request')
            if self.settings.kind=='decision':field='intent'
            else:field='status' if type(value) is dict and value.get('type')=='status' else 'action'
            exact(value,('schema','type','adapter_id',field),'robotio_ros2_response')
            if value['type']!=field:raise BridgeError('robotio_ros2_response_kind')
            if field=='intent':
                from ..platform_v2.decision_contracts import validate_decision_intent
                result=validate_decision_intent(value[field],self._pending)
            else:
                from ..deployment.navigation_plugin import validate_result
                wanted,result=validate_result(value[field],self._pending)
                if wanted!=field:raise BridgeError('robotio_ros2_response_kind')
        if type(value['schema']) is not str or value['schema']!=ENVELOPE_SCHEMA or type(value['adapter_id']) is not str or value['adapter_id']!=self.settings.adapter_id:
            raise BridgeError('robotio_ros2_route_mismatch')
        self._check_deadline();self._response=result
    def exchange(self,o,transport,intent=None):
        transport.publish(self.begin(o,intent))
        while self._response is None:
            self._check_deadline();transport.spin_once(min(.005,max(0.,self._deadline-self.clock())))
        self._check_deadline();result=self._response;self._response=None;self._pending=None;return result
    def close(self):self._closed=True;self._pending=None;self._response=None

def serve(core,transport,input_stream,output_stream):
    while True:
        raw=input_stream.readline(MAX_REQUEST+1)
        if not raw:return
        if len(raw)>MAX_REQUEST or not raw.endswith(b'\n'):raise BridgeError('robotio_ros2_jsonl_line')
        packet=parse_json(raw,MAX_REQUEST)
        if type(packet) is not dict or packet.get('schema')!=JSONL_SCHEMA:raise BridgeError('robotio_ros2_schema')
        if packet.get('op')=='prepare':
            exact(packet,('schema','op','config'),'robotio_ros2_prepare');exact(packet['config'],(),'robotio_ros2_prepare_config')
            if core.context is not None:raise BridgeError('robotio_ros2_prepare_before_reset')
            transport.wait_ready(1.)
            result=dict(schema=JSONL_SCHEMA,op='prepare',ok=True)
            if core.settings.kind=='decision':result['capabilities']=copy.deepcopy(core.capabilities)
        elif packet.get('op')=='reset':
            exact(packet,('schema','op','context','config'),'robotio_ros2_reset')
            core.reset(packet['context'],packet['config']);core.negotiate(transport)
            result=dict(schema=JSONL_SCHEMA,op='reset',ok=True,capabilities=core.capabilities)
        elif packet.get('op')=='act':
            has_intent='intent' in packet
            exact(packet,('schema','op','observation','intent') if has_intent else ('schema','op','observation'),'robotio_ros2_act')
            value=core.exchange(packet['observation'],transport,packet.get('intent'))
            field='intent' if core.settings.kind=='decision' else 'status' if value.get('schema')=='polar.sim.navigation-status.v1' else 'action'
            result=dict(schema=JSONL_SCHEMA,op='act',ok=True,**{field:value})
        else:raise BridgeError('robotio_ros2_operation')
        output_stream.write(encode_json(result,MAX_RESPONSE-1)+b'\n');output_stream.flush()

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    for name in ('adapter-id','kind','node-name','observation-topic','action-topic'):p.add_argument('--'+name,required=True)
    p.add_argument('--domain-id',type=int,required=True);p.add_argument('--response-timeout',type=float,default=.05)
    p.add_argument('--goal-input',action='store_true');settings=RobotIOSettings(**vars(p.parse_args(argv)))
    sys.stdout.flush();protocol=os.fdopen(os.dup(sys.stdout.fileno()),'wb',buffering=0);os.dup2(sys.stderr.fileno(),sys.stdout.fileno())
    core=RobotIOEnvelopeBridge(settings);transport=None;code=0
    try:
        from .ros2_bridge_transport import RclpyTransport
        transport=RclpyTransport(settings,core.receive_action);serve(core,transport,sys.stdin.buffer,protocol)
    except KeyboardInterrupt:code=130
    except Exception:print('robotio_ros2_bridge_failed',file=sys.stderr,flush=True);code=2
    finally:
        core.close()
        try:
            if transport is not None:transport.close()
        except Exception:print('robotio_ros2_shutdown_incomplete',file=sys.stderr,flush=True);code=2
        protocol.close()
    return code

if __name__=='__main__':raise SystemExit(main())
