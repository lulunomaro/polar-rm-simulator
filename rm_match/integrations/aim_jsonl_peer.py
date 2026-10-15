"""Reusable bounded JSONL entry for locally reviewed aim implementations.

Supply compute(bundle, detached_observation) from the actual algorithm wrapper.
No implicit no-target, hold, firing, frame retimestamp or algorithm fallback.
"""
from __future__ import annotations
import os
import copy
import sys
from .aim_camera_codec import prepare_aim_input
from .ros2_bridge import parse_json,encode_json,MAX_REQUEST,MAX_RESPONSE,JSONL_SCHEMA
from ..platform_v2.contracts import ContractError,IDENTITY,exact,identity,validate_observation,validate_action
from ..platform_v2.aim_contracts import AIM_STATUS_SCHEMA,validate_aim_status

def serve_aim_plugin(compute,input_stream,output_stream,*,capabilities=None):
    # This local wrapper declaration is independent of the host's challenge.
    # Echoing an arbitrary requested contract cannot opt an algorithm into it.
    from ..deployment.aim_plugin import CAPABILITIES,CAPABILITY_SCHEMA_V2,validate_capabilities
    selected=validate_capabilities(CAPABILITIES if capabilities is None else capabilities)
    negotiated=selected['schema']==CAPABILITY_SCHEMA_V2
    def check_capabilities(request):
        if negotiated and validate_capabilities(request['capabilities'])!=selected:
            raise ContractError('aim_peer_capabilities_mismatch')
    def acknowledgement(op):
        value=dict(schema=JSONL_SCHEMA,op=op,ok=True)
        if negotiated:value['capabilities']=copy.deepcopy(selected)
        return value
    context=None;last_seq=-1;prepared=False
    while True:
        raw=input_stream.readline(MAX_REQUEST+1)
        if not raw:return
        if len(raw)>MAX_REQUEST or not raw.endswith(b'\n'):raise ContractError('aim_jsonl_line_oversized_or_partial')
        request=parse_json(raw,MAX_REQUEST)
        if type(request) is not dict or request.get('schema')!=JSONL_SCHEMA:raise ContractError('aim_jsonl_schema')
        op=request.get('op')
        if op=='prepare':
            exact(request,('schema','op','config')+(('capabilities',) if negotiated else ()),'aim_peer_prepare')
            exact(request['config'],(),'aim_peer_config')
            check_capabilities(request)
            if prepared or context is not None:raise ContractError('aim_peer_prepare_once_before_reset')
            # The actual compute factory has already returned. This acknowledges
            # resource initialization only; it supplies no image or generation.
            prepared=True;response=acknowledgement('prepare')
        elif op=='reset':
            exact(request,('schema','op','context','config')+(('capabilities',) if negotiated else ()),'aim_peer_reset')
            exact(request['context'],('episode','robot_id','binding_epoch'),'aim_peer_context')
            exact(request['config'],(),'aim_peer_config')
            check_capabilities(request)
            if context is not None:raise ContractError('aim_peer_reset_once')
            # Reuse canonical scalar identity checks without inventing deadlines.
            identity(dict(request['context'],observed_seq=0,sim_time=0.,wall_deadline=0.))
            next_context=dict(request['context'])
            reset=getattr(compute,'reset',None)
            if reset is not None:
                if not callable(reset):raise ContractError('aim_compute_reset_callable_required')
                reset(dict(next_context))
            context=next_context;response=acknowledgement('reset')
        elif op=='act':
            exact(request,('schema','op','observation'),'aim_peer_act')
            if context is None:raise ContractError('aim_peer_reset_required')
            o,bundle=prepare_aim_input(request['observation'])
            if negotiated:
                from ..platform_v2.adapters import require_sensors
                require_sensors(o,('camera','odometry'))
            if context is None or any(type(o[k]) is not type(v) or o[k]!=v for k,v in context.items()):raise ContractError('aim_peer_generation')
            if o['observed_seq']<=last_seq:raise ContractError('aim_peer_replayed_observation')
            value=compute(bundle,copy.deepcopy(o))
            if type(value) is dict and value.get('schema')==AIM_STATUS_SCHEMA:
                field='status';value=validate_aim_status(value,o)
            else:
                field='action';value=validate_action(value,o,dict(kind='aim',output_modes=['gimbal_target']))
            last_seq=o['observed_seq'];response=dict(schema=JSONL_SCHEMA,op='act',ok=True,**{field:value})
        else:raise ContractError('aim_peer_operation')
        output_stream.write(encode_json(response,MAX_RESPONSE-1)+b'\n');output_stream.flush()

def run_aim_plugin(compute_factory,*,capabilities=None):
    """Wrapper entry: defer algorithm loading until stdout is protocol-safe.

    Manifest selects the reviewed wrapper executable; HTTP never selects this
    callable/import/model. Foreign wall_deadline remains an opaque echo here.
    """
    sys.stdout.flush();protocol=os.fdopen(os.dup(sys.stdout.fileno()),'wb',buffering=0)
    os.dup2(sys.stderr.fileno(),sys.stdout.fileno());compute=None;code=0
    try:
        compute=compute_factory()
        if not callable(compute):raise ContractError('aim_compute_callable_required')
        serve_aim_plugin(compute,sys.stdin.buffer,protocol,capabilities=capabilities)
    except KeyboardInterrupt:code=130
    except Exception:print('aim_plugin_failed',file=sys.stderr,flush=True);code=2
    finally:
        try:
            close=getattr(compute,'close',None)
            if close is not None:close()
        except Exception:print('aim_plugin_shutdown_incomplete',file=sys.stderr,flush=True);code=2
        finally:protocol.close()
    return code
