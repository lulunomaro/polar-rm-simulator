"""Optional trusted-local JSONL <-> ROS 2 String envelope bridge.

No ROS import at module import time. The host adapter remains deadline/lease
authority; a remote host's monotonic wall_deadline is an opaque echo value here.
"""
from __future__ import annotations
import argparse
from dataclasses import dataclass
import json
import math
import os
import re
import sys
import time

from ..platform_v2.contracts import (ContractError,IDENTITY,exact,integer,string,
    validate_observation,validate_action)

JSONL_SCHEMA='polar.sim.adapter.jsonl.v1'
ENVELOPE_SCHEMA='polar.sim.ros2.envelope.v1'
MAX_REQUEST=12*1024*1024
MAX_RESPONSE=64*1024


class BridgeError(ContractError):pass


def parse_json(raw,limit):
    if type(raw) is str:
        if len(raw)>limit:raise BridgeError('ros2_message_oversized')
        try:raw=raw.encode('utf8')
        except UnicodeError:raise BridgeError('ros2_invalid_utf8') from None
    if type(raw) is not bytes or len(raw)>limit:raise BridgeError('ros2_message_oversized')
    def pairs(items):
        value={}
        for key,item in items:
            if key in value:raise BridgeError('ros2_duplicate_json_key')
            value[key]=item
        return value
    def constant(_):raise BridgeError('ros2_nonfinite_json')
    try:return json.loads(raw.decode('utf8'),object_pairs_hook=pairs,parse_constant=constant)
    except (UnicodeError,ValueError,RecursionError) as exc:
        if isinstance(exc,BridgeError):raise
        raise BridgeError('ros2_invalid_json') from None


def encode_json(value,limit):
    try:raw=json.dumps(value,allow_nan=False,separators=(',',':')).encode('utf8')
    except (ValueError,TypeError,RecursionError):raise BridgeError('ros2_invalid_json') from None
    if len(raw)>limit:raise BridgeError('ros2_message_oversized')
    return raw


@dataclass(frozen=True)
class BridgeSettings:
    adapter_id:str
    kind:str
    node_name:str
    observation_topic:str
    action_topic:str
    domain_id:int
    response_timeout:float=.08

    def __post_init__(self):
        if type(self.adapter_id) is not str or not re.fullmatch(r'custom_[a-z0-9_]{1,100}',self.adapter_id):raise BridgeError('ros2_custom_adapter_id_required')
        if type(self.kind) is not str or self.kind not in ('navigation','aim'):raise BridgeError('ros2_invalid_kind')
        if type(self.node_name) is not str or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}',self.node_name):raise BridgeError('ros2_invalid_node')
        for topic in (self.observation_topic,self.action_topic):
            if type(topic) is not str or len(topic)>256 or not re.fullmatch(r'(?:/[A-Za-z_][A-Za-z0-9_]*)+',topic):raise BridgeError('ros2_invalid_topic')
        if self.observation_topic==self.action_topic:raise BridgeError('ros2_topics_must_differ')
        if type(self.domain_id) is not int or not 0<=self.domain_id<=101:raise BridgeError('ros2_invalid_local_domain')
        if type(self.response_timeout) not in (float,int) or not math.isfinite(self.response_timeout) or not 0<self.response_timeout<=.25:raise BridgeError('ros2_invalid_response_budget')


class EnvelopeBridge:
    """Single-threaded core: one pending observation and one bounded response.

    Only the rclpy executor thread calls receive_action. Tests can inject a
    transport explicitly; the production entry never substitutes a fake one.
    """
    def __init__(self,settings,*,clock=time.monotonic):
        self.settings=settings;self.clock=clock;self.context=None
        self._pending=None;self._response=None;self._deadline=None
        self._last_seq=-1;self._closed=False
        self.capabilities=dict(kind=settings.kind,output_modes=[
            'velocity_body' if settings.kind=='navigation' else 'gimbal_target'])

    def reset(self,context,config):
        if self._closed or self.context is not None:raise BridgeError('ros2_reset_once_per_process')
        exact(context,('episode','robot_id','binding_epoch'),'ros2_reset_context')
        integer(context['episode'],'episode');integer(context['binding_epoch'],'binding_epoch');string(context['robot_id'],'robot_id')
        exact(config,(),'ros2_binding_config')
        self.context=dict(context)

    def begin(self,observation):
        if self._closed or self.context is None:raise BridgeError('ros2_not_reset')
        if self._pending is not None or self._response is not None:raise BridgeError('ros2_pending_capacity')
        deadline=self.clock()+self.settings.response_timeout
        o=validate_observation(observation)
        if any(type(o[k]) is not type(v) or o[k]!=v for k,v in self.context.items()):raise BridgeError('ros2_observation_context_mismatch')
        if o['observed_seq']<=self._last_seq:raise BridgeError('ros2_observation_sequence_not_increasing')
        payload=encode_json(dict(schema=ENVELOPE_SCHEMA,type='observation',adapter_id=self.settings.adapter_id,observation=o),MAX_REQUEST)
        if self.clock()>=deadline:raise BridgeError('ros2_response_timeout')
        self._last_seq=o['observed_seq'];self._deadline=deadline;self._pending=o
        return payload.decode('utf8')

    def receive_action(self,payload):
        if self._closed or self._pending is None:raise BridgeError('ros2_no_pending_observation')
        if self.clock()>=self._deadline:
            self._pending=None;raise BridgeError('ros2_response_timeout')
        envelope=parse_json(payload,MAX_RESPONSE)
        exact(envelope,('schema','type','adapter_id','action'),'ros2_action_envelope')
        for key,wanted in (('schema',ENVELOPE_SCHEMA),('type','action'),('adapter_id',self.settings.adapter_id)):
            if type(envelope[key]) is not str or envelope[key]!=wanted:raise BridgeError('ros2_action_route_mismatch')
        action=validate_action(envelope['action'],self._pending,self.capabilities)
        if any(type(action[k]) is not type(self._pending[k]) or action[k]!=self._pending[k] for k in IDENTITY):raise BridgeError('ros2_action_identity_mismatch')
        if self.settings.kind=='aim' and action['command']['fire_permission']:raise BridgeError('ros2_automatic_fire_forbidden')
        if self.clock()>=self._deadline:
            self._pending=None;raise BridgeError('ros2_response_timeout')
        self._response=action;self._pending=None

    def poll(self):
        if self._closed:raise BridgeError('ros2_closed')
        if self._deadline is not None and self.clock()>=self._deadline:
            self._pending=None;self._response=None;raise BridgeError('ros2_response_timeout')
        value=self._response;self._response=None
        return value

    def exchange(self,observation,transport):
        payload=self.begin(observation);transport.publish(payload)
        while True:
            action=self.poll()
            if action is not None:return action
            transport.spin_once(min(.005,max(0.,self._deadline-self.clock())))

    def close(self):
        self._closed=True;self._pending=None;self._response=None


def serve(core,transport,input_stream,output_stream):
    """Bounded binary JSONL I/O. No fallback action or unsolicited stdout line."""
    while True:
        raw=input_stream.readline(MAX_REQUEST+1)
        if not raw:return
        if len(raw)>MAX_REQUEST or not raw.endswith(b'\n'):raise BridgeError('ros2_jsonl_missing_or_oversized_line')
        request=parse_json(raw,MAX_REQUEST)
        if type(request) is not dict or type(request.get('schema')) is not str or request['schema']!=JSONL_SCHEMA:raise BridgeError('ros2_unknown_jsonl_schema')
        op=request.get('op')
        if type(op) is not str:raise BridgeError('ros2_unknown_operation')
        if op=='reset':
            exact(request,('schema','op','context','config'),'ros2_reset_request');core.reset(request['context'],request['config'])
            transport.wait_ready(1.)
            response=dict(schema=JSONL_SCHEMA,op=op,ok=True)
        elif op=='act':
            exact(request,('schema','op','observation'),'ros2_act_request')
            response=dict(schema=JSONL_SCHEMA,op=op,ok=True,action=core.exchange(request['observation'],transport))
        else:raise BridgeError('ros2_unknown_operation')
        output_stream.write(encode_json(response,MAX_RESPONSE-1)+b'\n');output_stream.flush()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adapter-id',required=True);parser.add_argument('--kind',required=True,choices=('navigation','aim'))
    parser.add_argument('--node-name',required=True);parser.add_argument('--observation-topic',required=True)
    parser.add_argument('--action-topic',required=True);parser.add_argument('--domain-id',required=True,type=int)
    parser.add_argument('--response-timeout',type=float,default=.08)
    args=parser.parse_args(argv);core=None;transport=None;exit_code=0
    # All ROS/library console output, including C fd1 writes, goes to stderr.
    # Only this saved descriptor writes JSONL back to the host's owned pipe.
    sys.stdout.flush();protocol=os.fdopen(os.dup(sys.stdout.fileno()),'wb',buffering=0)
    os.dup2(sys.stderr.fileno(),sys.stdout.fileno())
    try:
        settings=BridgeSettings(**vars(args));core=EnvelopeBridge(settings)
        from .ros2_bridge_transport import RclpyTransport
        transport=RclpyTransport(settings,core.receive_action)
        serve(core,transport,sys.stdin.buffer,protocol)
    except KeyboardInterrupt:exit_code=130
    except Exception as exc:
        # No payload, credential, command or external exception text is logged.
        reason=str(exc) if isinstance(exc,ContractError) else 'ros2_bridge_runtime_failed'
        print(reason,file=sys.stderr,flush=True);exit_code=2
    finally:
        if core is not None:core.close()
        try:
            if transport is not None:transport.close()
        except Exception:
            print('ros2_shutdown_incomplete',file=sys.stderr,flush=True);exit_code=2
        finally:protocol.close()
    return exit_code


if __name__=='__main__':raise SystemExit(main())
