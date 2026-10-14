"""Prepared PB compute engine for the generic canonical JSONL peer, Linux only."""
from __future__ import annotations
import argparse
import json
import os
import threading
import time
from .aim_jsonl_peer import run_aim_plugin
from .pb_aim_ros_peer import PBAimBridge,PBAimRosTransport,checked_mount
from .pb_aim_stack import PBAlgorithmStack,load_stack,checked_ref
from .ros2_bridge import BridgeSettings
from ..platform_v2.contracts import ContractError

class PBAimEngine:
    def __init__(self,spec,*,stack=None,transport_factory=None,clock=None):
        self.spec=spec;self.stack=stack if stack is not None else PBAlgorithmStack(spec)
        settings=BridgeSettings(spec['adapter_id'],'aim','pb_aim_jsonl_peer',spec['namespace']+'/input',
            spec['namespace']+'/result',spec['domain_id'],.08)
        self.core=PBAimBridge(settings,**({} if clock is None else {'clock':clock}))
        self.transport=None;self.transport_factory=transport_factory;self._prepared=False;self._reset=False
        self.clock=time.monotonic if clock is None else clock
        self._close_started=False;self._cleanup_error=None;self._reset_attempted=False

    def prepare(self):
        if self._prepared or self._close_started:raise ContractError('pb_aim_prepare_once')
        # environment_ref is trusted local and hash bound. No external setup.sh
        # is sourced; the standard owned Humble process environment is data.
        _,raw=checked_ref(self.spec['environment']);environment=json.loads(raw)
        values=environment.get('process_environment',environment.get('environment'))
        if type(values) is not dict or any(type(k) is not str or type(v) is not str for k,v in values.items()):
            raise ContractError('pb_aim_owned_environment_required')
        env=os.environ.copy();env.update(values);env['ROS_DOMAIN_ID']=str(self.spec['domain_id'])
        # The peer's ROS context and child algorithms must use the same domain.
        os.environ['ROS_DOMAIN_ID']=str(self.spec['domain_id'])
        self.stack.start(env)
        if self.transport_factory is None:
            self.transport=PBAimRosTransport.__new__(PBAimRosTransport)
            self.transport.__init__(self.core,self.spec['namespace'],None,
                run_uuid=self.spec['run_uuid'],calibration_id=self.spec['calibration_id'])
        else:self.transport=self.transport_factory(self.core,self.spec)
        self.transport.wait_ready(1.)
        self.stack.check_alive();self._prepared=True

    def reset(self,context):
        if not self._prepared or self._reset_attempted:raise ContractError('pb_aim_actual_prepare_then_single_reset')
        self._reset_attempted=True
        self.stack.check_alive()
        mount,_=checked_mount(self.spec['mount']['path'],self.spec['mount']['sha256'],context['robot_id'])
        self.core.reset(context,{})
        self.transport.configure(dict(context),mount,1.)
        self.stack.check_alive();self._reset=True

    def __call__(self,bundle,observation):
        if not self._reset:raise ContractError('pb_aim_real_reset_required')
        self.stack.check_alive()
        # The core revalidates the full public observation. No empty base64 or
        # private snapshot is disguised as a public observation.v2.
        return self.core.exchange(observation,self.transport)

    def close(self):
        if self._close_started:
            if self._cleanup_error is not None:raise self._cleanup_error
            return
        self._close_started=True;deadline=self.clock()+1.;errors=[]
        try:self.core.close()
        except BaseException as exc:errors.append(exc)
        # A single owned closer bounds potentially blocking ROS shutdown. A
        # live closer after the shared budget is unfinished cleanup, never a
        # successful inner or outer process-tree proof.
        closer=None
        if self.transport is not None:
            def close_transport():
                try:self.transport.close()
                except BaseException as exc:errors.append(exc)
            closer=threading.Thread(target=close_transport,name='pb-aim-ros-close',daemon=True)
            self._close_thread=closer
            closer.start()
        # Ask children to terminate/reap first with one shared one-second
        # budget. The generic outer birth-bound group owner remains the
        # authoritative proof for descendants if any inner operation fails.
        try:self.stack.close(max(0.,deadline-self.clock()))
        except BaseException as exc:errors.append(exc)
        if closer is not None:
            closer.join(max(0.,deadline-self.clock()))
            if closer.is_alive():errors.append(ContractError('pb_aim_ros_close_unfinished'))
        if errors:
            self._cleanup_error=ContractError('pb_aim_engine_cleanup_incomplete')
            raise self._cleanup_error from errors[0]

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stack-ref',required=True);parser.add_argument('--stack-sha256',required=True)
    args=parser.parse_args(argv)
    def factory():
        spec=load_stack(args.stack_ref,args.stack_sha256);engine=PBAimEngine(spec)
        try:engine.prepare()
        except BaseException as original:
            try:engine.close()
            except BaseException as cleanup:
                failure=ContractError('pb_aim_prepare_failed_and_cleanup_incomplete: '+type(original).__name__)
                failure.cleanup_error=cleanup
                raise failure from original
            raise
        return engine
    # The generic peer's real prepare ACK occurs only after this factory has
    # returned. No image, fake generation, inference or physics is submitted.
    return run_aim_plugin(factory)
if __name__=='__main__':raise SystemExit(main())
