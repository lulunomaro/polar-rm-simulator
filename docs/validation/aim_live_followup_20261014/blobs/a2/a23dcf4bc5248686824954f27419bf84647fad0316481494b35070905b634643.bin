"""Single physics authority with isolated, bounded per-robot algorithm slots.

Adapters get copied, validated JSON observations. An explicitly enabled local
experiment also permits sealed actual pixels to two reviewed exact native
classes. This is a data boundary, not a Python sandbox for malicious code.
"""
from __future__ import annotations
import copy
import json
import math
import queue
import sys
import threading
import time
from .control import ControlPlane, Rejected, KINDS


def json_copy(value):
    return json.loads(json.dumps(value,allow_nan=False))


def _loaded_native_class():
    """Recognize an already constructed native adapter without loading vision."""
    module=sys.modules.get(__package__+'.native_adapter')
    cls=getattr(module,'NativeSourceAdapter',None) if module is not None else None
    return cls if isinstance(cls,type) else None


def _reviewed_native_instance(instance,cls):
    if cls is None or not isinstance(instance,cls):return False
    from .native_observation import reviewed_native_instance
    return reviewed_native_instance(instance)


def _exception_location(exc,phase):
    """Bounded code locations only: never exception arguments, locals or inputs."""
    frames=[];tb=exc.__traceback__
    while tb is not None:
        frames.append(dict(file=tb.tb_frame.f_code.co_filename[-256:],
            function=tb.tb_frame.f_code.co_name[:64],line=tb.tb_lineno))
        if len(frames)>6:frames.pop(0)
        tb=tb.tb_next
    return dict(phase=phase,frames=frames)


class AdapterSlot:
    """At most one running and one replaceable pending task, per robot/kind.

    A stalled adapter cannot create new threads on rebind. It can make this slot
    unavailable until process restart, but the authority and other slots never
    wait on it. Lifecycle calls run on the same slot thread, outside all locks.
    """
    def __init__(self,registry,clock):
        self.registry=registry;self.clock=clock
        self.pending=queue.Queue(maxsize=1);self.results=queue.Queue(maxsize=1)
        self.stop=threading.Event();self.dropped=0;self.running=False;self.lifecycle_error=None
        self._instance=None;self._lifecycle_lock=threading.Lock()
        self.thread=threading.Thread(target=self._run,name='sim-v2-adapter',daemon=True)
        self.thread.start()

    @staticmethod
    def _latest(q,value):
        replaced=False
        while True:
            try:q.put_nowait(value);return replaced
            except queue.Full:
                try:q.get_nowait();replaced=True
                except queue.Empty:pass

    def submit(self,job):
        if self._latest(self.pending,job):self.dropped+=1

    @staticmethod
    def _cancel_native(instance):
        # Arbitrary Python cancel/close hooks may hang. Call only the reviewed
        # base implementation for loaded native or exact reviewed JSON types.
        cls=_loaded_native_class()
        if cls is not None and isinstance(instance,cls):
            cls.cancel(instance);return
        module=sys.modules.get('rm_match.deployment.json_adapter')
        base=vars(module).get('JsonLineAdapter') if module is not None else None
        if not isinstance(base,type):return
        for module_name,class_name in (
            ('rm_match.deployment.json_adapter','JsonLineAdapter'),
            ('rm_match.deployment.aim_plugin','AimPluginAdapter'),
            ('rm_match.deployment.wsl_jsonl','WslAimPluginAdapter')):
            loaded=sys.modules.get(module_name)
            reviewed=vars(loaded).get(class_name) if loaded is not None else None
            if type(instance) is reviewed:
                base.cancel(instance);return

    def _run(self):
        instance=None;identity=None;failed_identity=None
        try:
            while not self.stop.is_set():
                try:job=self.pending.get(timeout=.05)
                except queue.Empty:continue
                if job.get('deactivate'):
                    if instance is not None:
                        try:instance.close()
                        except BaseException as exc:self.lifecycle_error=type(exc).__name__
                    instance=None;identity=None
                    with self._lifecycle_lock:self._instance=None
                    continue
                if self.clock()>=job['observation']['wall_deadline']:continue
                started_wall=self.clock();self.running=True;error=None;value=None;private_rejected=False
                phase='admission';admission_timings={};discarded_reason=None;exception_diagnostic=None
                try:
                    b=job['binding'];o=job['observation']
                    current=(o['robot_id'],job['kind'],o['episode'],b['epoch'])
                    if current==failed_identity:
                        continue  # Sticky worker fault until an explicit new generation.
                    if current!=identity:
                        if instance is not None:instance.close()
                        instance=None;identity=None
                        phase='create';phase_started=self.clock()
                        try:instance=self.registry.create(b['adapter_id'],json_copy(b['config']))
                        finally:admission_timings['create_s']=self.clock()-phase_started
                        with self._lifecycle_lock:self._instance=instance
                        if self.stop.is_set():
                            self._cancel_native(instance)
                            break
                        phase='reset';phase_started=self.clock()
                        try:instance.reset(dict(episode=o['episode'],robot_id=o['robot_id'],binding_epoch=b['epoch']))
                        finally:admission_timings['reset_s']=self.clock()-phase_started
                        identity=current
                    if self.stop.is_set():break
                    # Raw-image validation/JSON copying is CPU work on this worker,
                    # never on physics or HTTP threads.
                    from .contracts import validate_observation
                    NativeSourceAdapter=_loaded_native_class()
                    phase='admission_deadline_recheck'
                    if self.clock()>=o['wall_deadline']:
                        # Setup is not algorithm execution. Discard this old
                        # exposure, retaining the reviewed instance for a NEW
                        # original-budget job of the same generation.
                        discarded_reason='original_deadline_expired_after_admission'
                    elif job.get('native_pixels') is not None:
                        if b['adapter_id']!='aim_native_rmcs_v1' or not _reviewed_native_instance(instance,NativeSourceAdapter):
                            # Never hand a private object to a custom class/hook.
                            # Retry this generation through the complete public DTO.
                            private_rejected=True
                        else:
                            phase='private_authority_recheck';phase_started=self.clock()
                            allowed=job['native_camera_check']()
                            admission_timings['authority_recheck_s']=self.clock()-phase_started
                            if not allowed:
                                discarded_reason=('original_deadline_expired_before_act' if self.clock()>=o['wall_deadline']
                                    else 'authority_revoked_before_act')
                            else:
                                phase='private_native_act';phase_started=self.clock()
                                try:
                                    value=json_copy(NativeSourceAdapter._act_native_pixels(instance,o,job['native_pixels'],
                                        consumer=job['native_consumer'],budget=job['sensor_budget'],now=self.clock()))
                                finally:admission_timings['act_s']=self.clock()-phase_started
                    elif (NativeSourceAdapter is not None and isinstance(instance,NativeSourceAdapter)
                        and getattr(instance.act,'__func__',None) is NativeSourceAdapter.act):
                        phase='public_native_validation';decoded={};o=validate_observation(o,image_bytes=decoded,image_token=job.get('pixel_token'))
                        phase='public_native_act';phase_started=self.clock()
                        try:value=json_copy(NativeSourceAdapter._act_validated(instance,o,decoded['raw']))
                        finally:admission_timings['act_s']=self.clock()-phase_started
                    else:
                        phase='public_validation';o=validate_observation(o)
                        phase='public_act';phase_started=self.clock()
                        try:value=json_copy(instance.act(copy.deepcopy(o)))
                        finally:admission_timings['act_s']=self.clock()-phase_started
                    # Validate before publishing into the latest-result slot: an
                    # invalid result must not be overwritten by a later good one.
                    from .contracts import validate_action
                    if not private_rejected and not discarded_reason:
                        phase='action_validation'
                        from .navigation_contracts import NAV_SCHEMA,NAV_PROFILE,NAV_STATUS_SCHEMA,validate_navigation_status
                        from .aim_contracts import AIM_STATUS_SCHEMA,AIM_PLUGIN_CONTRACT,validate_aim_status
                        metadata=self.registry.get(b['adapter_id']).descriptor
                        if (metadata.get('observation_profile')==NAV_PROFILE and o['schema']==NAV_SCHEMA
                            and type(value) is dict and value.get('schema')==NAV_STATUS_SCHEMA):
                            value=validate_navigation_status(value,o)
                        elif (metadata.get('kind')=='aim' and metadata.get('aim_plugin_contract')==AIM_PLUGIN_CONTRACT
                            and type(value) is dict and value.get('schema')==AIM_STATUS_SCHEMA):
                            value=validate_aim_status(value,o)
                        else:value=validate_action(value,o,metadata)
                except BaseException as exc:
                    error=type(exc).__name__;failed_identity=current;exception_diagnostic=_exception_location(exc,phase)
                finally:self.running=False
                self._latest(self.results,dict(job=job,value=value,error=error,private_rejected=private_rejected,
                    discarded_reason=discarded_reason,admission_timings=admission_timings,exception_diagnostic=exception_diagnostic,
                    started_wall=started_wall,completed=self.clock()))
                if error and instance is not None:
                    try:instance.close()
                    except BaseException as exc:self.lifecycle_error=type(exc).__name__
                    instance=None;identity=None
                    with self._lifecycle_lock:self._instance=None
        finally:
            if instance is not None:
                try:instance.close()
                except BaseException as exc:self.lifecycle_error=type(exc).__name__
            with self._lifecycle_lock:self._instance=None

    def poll(self):
        try:return self.results.get_nowait()
        except queue.Empty:return None

    def close(self):
        self.stop.set()
        # No plugin action or blocking close here. Reviewed native adapters expose
        # a nonblocking cancel hook; the worker remains the close/reap owner.
        with self._lifecycle_lock:instance=self._instance
        if instance is not None:
            try:self._cancel_native(instance)
            except BaseException as exc:self.lifecycle_error=type(exc).__name__


class PlatformRuntime:
    def __init__(self,backend,*,registry=None,clock=time.perf_counter,observation_period=.05,
                 action_ttl=.2,control=None,camera=None,trace=None,enable_native_pixels=False):
        from .adapters import default_registry
        self.camera=camera;self.trace=trace;self.output_budgets={};self.output_authorizations={};self.real_time_factor=1.
        self.backend=backend;self.registry=registry or default_registry();self.clock=clock
        if type(enable_native_pixels) is not bool:raise ValueError('Invalid local native pixel experiment')
        if enable_native_pixels:
            # Definition-only imports during local setup, never an algorithm
            # warm-up, exposure or native process request.
            from . import native_observation
        self.enable_native_pixels=enable_native_pixels;self._native_pixels_denied={};self._private_outputs=set()
        self.control=control or ControlPlane(backend.robot_ids,clock=clock,spin_capabilities=backend.declared_spin_capabilities() if hasattr(backend,'declared_spin_capabilities') else {})
        if tuple(self.control.robot_ids)!=tuple(backend.robot_ids):raise ValueError('Registry/backend mismatch')
        if not 0<observation_period<=.2 or not 0<action_ttl<=.25:raise ValueError('Invalid scheduling bounds')
        self.observation_period=observation_period;self.action_ttl=action_ttl
        self.slots={};self.outputs={};self.observed={};self.next_observation={};self.status={};self._navigation_samples={}
        self._fault_epochs={};self._slot_bound={};self._own_samples={};self._camera_samples={};self._aim_status_context={}
        self.stop_event=threading.Event();self.cache_lock=threading.Lock()
        self.cached={'runtime_state':'starting','telemetry_available':False}
        self._authority=None;self._episode=None;self.steps=0;self.last_step_wall=None;self.error=None
        self._started=self.clock();self._closed=False

    def _trace(self,event,**values):
        if self.trace is not None:self.trace(dict(event=event,wall_time=self.clock(),**values))

    @staticmethod
    def _budget_valid(budget,now,sim_time):
        return budget is None or (budget['capture_wall']<=now<budget['wall_deadline']
            and budget['capture_sim_time']<=sim_time<=budget['sim_deadline'])

    def _check_authority(self):
        current=threading.get_ident()
        if self._authority is None:self._authority=current
        if self._authority!=current:raise RuntimeError('Only one thread may advance physics')

    def capabilities(self,token):
        # Session/watch identity comes from ControlPlane; model metadata is cached.
        with self.control.lock:
            session=self.control._session(token)
            with self.cache_lock:episode=self.cached.get('episode')
            return dict(capability_schema='rm.sim.platform.capabilities.v1',session_id=session.sid,
                watch_robot_id=session.watch_robot_id,watch_epoch=session.watch_epoch,episode=episode,
                robots=[dict(robot_id=r,spin_control=copy.deepcopy(self.control._spin_capabilities.get(r,dict(version=1,available=False,reason='unsupported_yaw_actuator_mapping')))) for r in self.control.visible_robot_ids(token)])

    def adapter_descriptors(self):
        return self.registry.descriptors()

    def adapter_catalog(self,token=None):
        support=self.backend.declared_sensor_support() if hasattr(self.backend,'declared_sensor_support') else {}
        robots=[]
        for rid in self.control.robot_ids:
            if token is not None and rid not in self.control.visible_robot_ids(token):continue
            sensors=list(support.get(rid,[]))
            if self.camera is not None and 'camera' not in sensors:sensors.append('camera')
            robots.append(dict(robot_id=rid,declared_sensors=sensors))
        result=dict(adapter_ui_version=1,adapter_activation_version=1,
                    adapters=self.adapter_descriptors(),robots=robots,
                    readiness='declared_support_only',fire_authority='manual_only')
        if token is not None:result['control_capabilities']=self.capabilities(token)
        return result

    @staticmethod
    def _binding_active(b,now):
        return b['owner'] is not None and (not b.get('activation_required',False)
            or (b.get('activation_seq',-1)>=0 and now<b.get('activation_expires',0.)))

    def bind(self,token,robot_id,kind,lease_epochs,adapter_id,config):
        # Never call adapter constructors on an HTTP thread.
        with self.control.lock:
            session=self.control._session(token,True)
            self.control.authorize_robot(session,robot_id)
        try:spec=self.registry.get(adapter_id)
        except (KeyError,ValueError):raise Rejected('unknown_adapter',404)
        descriptor=spec.descriptor
        if not descriptor.get('available',True):raise Rejected('adapter_unavailable:'+descriptor.get('reason','unknown'),409)
        if descriptor.get('supported_robots') is not None and robot_id not in descriptor['supported_robots']:
            raise Rejected('adapter_robot_unsupported',400)
        if descriptor['kind']!=kind:raise Rejected('adapter_kind_mismatch',400)
        try:encoded=json.dumps(config,allow_nan=False)
        except (ValueError,TypeError):raise Rejected('invalid_config',400)
        if len(encoded.encode())>4096:raise Rejected('config_too_large',413)
        with self.control.lock:
            if self.camera is not None and 'camera' in descriptor['required_sensors']:
                desired=self._camera_desired(self.control.snapshot())
                if robot_id not in desired and len(desired)>=self.camera.max_views:raise Rejected('camera_view_capacity',429)
            return self.control.bind(token,robot_id,kind,lease_epochs,adapter_id,json.loads(encoded))

    @staticmethod
    def _camera_binding(rid,kind,b):return ('adapter',rid,kind,b['owner'],b['epoch'])

    def _registry_capability(self,adapter_id,key):
        query=getattr(self.registry,'capability',None)
        if callable(query):return query(adapter_id,key)
        # Existing duck-typed local registries retain their live get semantics.
        from .contracts import ContractError
        if type(key) is not str or key not in ('stationary_only','requires_camera'):
            raise ContractError('unknown_adapter_capability')
        metadata=self.registry.get(adapter_id).descriptor
        if key=='stationary_only':return bool(metadata.get(key,False))
        return 'camera' in metadata['required_sensors']

    def _camera_desired(self,snapshot):
        desired={}
        for watch in self.control.watches():
            desired.setdefault(watch['robot_id'],set()).add(('watch',watch['session_id'],watch['watch_epoch']))
        for rid in self.control.robot_ids:
            for kind in KINDS:
                b=snapshot['bindings'][rid][kind]
                if b['owner'] is not None and self._registry_capability(b['adapter_id'],'requires_camera'):
                    desired.setdefault(rid,set()).add(self._camera_binding(rid,kind,b))
        return desired

    def watch(self,token,rid):
        with self.control.lock:
            session=self.control._session(token)
            if rid is not None:self.control.authorize_robot(session,rid)
            if self.camera is not None and rid is not None:
                desired=self._camera_desired(self.control.snapshot())
                # Remove this session's previous watch before checking capacity.
                old=self.control.watch_sample(token)
                key=('watch',old['session_id'],old['watch_epoch'])
                desired={r:tokens-{key} for r,tokens in desired.items()}
                desired={r:t for r,t in desired.items() if t}
                if rid not in desired and len(desired)>=self.camera.max_views:raise Rejected('camera_view_capacity',429)
            return self.control.watch(token,rid)

    def frame(self,token):
        # Lock order is always control -> camera. There is no render work here.
        with self.control.lock:
            session=self.control._session(token)
            watch=self.control.watch_sample(token)
            rid=watch['robot_id'];epoch=self._episode
            if rid is not None:self.control.authorize_robot(session,rid)
            reason='runtime_stopped' if self.control.stopped else ('not_watching' if rid is None else 'no_gl_stage')
            if self.control.stopped or rid is None or self.camera is None:
                value=dict(available=False,reason=reason,robot_id=rid,episode=epoch,watch_epoch=watch['watch_epoch'])
            else:value=self.camera.display_frame(rid,epoch,('watch',watch['session_id'],watch['watch_epoch']),watch['watch_epoch'])
            if session.role=='operator':
                from .state_projection import operator_camera_display
                return operator_camera_display(value)
            if not session.audit_authorized:raise Rejected('audit_authorization_required',403)
            return value

    def _collect(self,snapshot,sim_time):
        from .contracts import validate_action
        now=self.clock()
        for key,slot in self.slots.items():
            rid,kind=key;b=snapshot['bindings'][rid][kind]
            output=self.outputs.get(key)
            if output is not None and (output['binding_epoch']!=b['epoch'] or now>=output['wall_deadline']
                                      or not 0<=sim_time-output['sim_time']<=self.action_ttl
                                      or output['episode']!=self._episode or output['robot_id']!=rid
                                      or not self._budget_valid(self.output_budgets.get(key),now,sim_time)
                                      or not self._private_output_valid(key,b,sim_time)):
                self.outputs.pop(key,None)
                self.status[key]='expired_or_rebound'
            result=slot.poll()
            if result is None:continue
            job=result['job'];o=job['observation'];old=job['binding'];budget=job.get('sensor_budget')
            self._trace('adapter_result',robot_id=rid,kind=kind,binding_epoch=old['epoch'],observed_seq=o['observed_seq'],episode=o['episode'],observation_sim_time=o['sim_time'],wall_deadline=o['wall_deadline'],sensor_budget=budget,sample_identity=job.get('sample_identity'),operator_authorization=job.get('operator_authorization'),started_wall=result.get('started_wall'),completed_wall=result['completed'],error=result['error'],command=result['value'].get('command') if result['value'] else None,
                discarded_reason=result.get('discarded_reason'),admission_timings=result.get('admission_timings'),exception_diagnostic=result.get('exception_diagnostic'))
            if b['owner'] is None or (b['epoch'],b['owner'],b['lease_epochs'])!=(old['epoch'],old['owner'],old['lease_epochs']):
                continue
            if result.get('discarded_reason'):
                self.status[key]='sample_discarded:'+result['discarded_reason'];continue
            if result.get('private_rejected'):
                self._native_pixels_denied[key]=(b['epoch'],b['owner'])
                self._camera_samples.pop(key,None);self.next_observation.pop(key,None)
                self.status[key]='waiting_for_public_camera';continue
            if self._fault_epochs.get(key)==b['epoch']:
                self.outputs.pop(key,None)
                continue  # No queued or late same-generation result can recover a fault.
            if result['error']:
                self.outputs.pop(key,None);self.status[key]='adapter_error:'+result['error'];self._fault_epochs[key]=b['epoch'];continue
            if (o['robot_id']!=rid or o['episode']!=self._episode
                or now>=o['wall_deadline'] or not 0<=sim_time-o['sim_time']<=self.action_ttl
                or not self._budget_valid(budget,now,sim_time)
                or not self._camera_budget_current(rid,kind,b,budget,sim_time,private=job.get('native_pixels') is not None)):
                self.outputs.pop(key,None);self.status[key]='late_result';continue
            try:
                from .navigation_contracts import NAV_STATUS_SCHEMA,validate_navigation_status
                from .aim_contracts import AIM_STATUS_SCHEMA,AIM_PLUGIN_CONTRACT,validate_aim_status
                if result['value'].get('schema')==NAV_STATUS_SCHEMA:
                    metadata=self.registry.get(b['adapter_id']).descriptor
                    if metadata.get('observation_profile')!='pointcloud_imu_v1':raise ValueError('navigation_status_profile')
                    status=validate_navigation_status(result['value'],o)
                    self.outputs.pop(key,None);self.output_budgets.pop(key,None);self.output_authorizations.pop(key,None)
                    self.status[key]='waiting_for_navigation:'+status['status']
                    continue
                if result['value'].get('schema')==AIM_STATUS_SCHEMA:
                    metadata=self.registry.get(b['adapter_id']).descriptor
                    if kind!='aim' or metadata.get('aim_plugin_contract')!=AIM_PLUGIN_CONTRACT:
                        raise ValueError('aim_status_contract')
                    status=validate_aim_status(result['value'],o)
                    current=self.outputs.get(key)
                    if current and status['observed_seq']<=current['observed_seq']:
                        raise ValueError('replayed aim status')
                    self.outputs.pop(key,None);self.output_budgets.pop(key,None);self.output_authorizations.pop(key,None)
                    self._private_outputs.discard(key)
                    self.status[key]='waiting_for_aim:'+status['status']
                    self._remember_aim_status(key,b,o,budget,status['status'])
                    self._trace('aim_status',robot_id=rid,binding_epoch=old['epoch'],
                        observed_seq=o['observed_seq'],episode=o['episode'],status=status['status'],
                        camera_frame_id=o['sensors']['camera'].get('frame_id'),command=None)
                    continue
                action=validate_action(result['value'],o,self.registry.get(b['adapter_id']).descriptor)
                if action['kind']!=kind:raise ValueError('kind mismatch')
                current=self.outputs.get(key)
                if current and action['observed_seq']<=current['observed_seq']:raise ValueError('replayed result')
                self.outputs[key]=action;self.output_budgets[key]=budget;self.output_authorizations[key]=job.get('operator_authorization');self.status[key]='active'
                if job.get('native_pixels') is not None:self._private_outputs.add(key)
                else:self._private_outputs.discard(key)
                if kind=='aim':
                    self._remember_aim_status(key,b,o,budget,
                        'result_available' if action['command']['active'] else 'no_target')
            except (ValueError,TypeError,KeyError):
                self.outputs.pop(key,None);self.status[key]='invalid_result';self._fault_epochs[key]=b['epoch']

    def _remember_aim_status(self,key,b,o,budget,status):
        """UI metadata only, bound to the original source and owner; not motion."""
        fid=(budget or {}).get('frame_id')
        if type(fid) is not int:fid=o.get('sensors',{}).get('camera',{}).get('frame_id')
        if type(fid) is not int or fid<0:return
        self._aim_status_context[key]=dict(episode=o['episode'],binding_epoch=o['binding_epoch'],
            adapter_id=b['adapter_id'],status=status,observed_seq=o['observed_seq'],
            wall_deadline=o['wall_deadline'],source_frame_id=fid,
            owner=b['owner'],lease_epoch=b['lease_epochs'].get('gimbal'))

    def _private_camera_valid(self,rid,kind,b,budget,sim_time):
        check=getattr(self.camera,'native_capture_valid',None)
        return bool(callable(check) and check(rid,self._episode,self._camera_binding(rid,kind,b),budget,sim_time))

    def _private_job_valid(self,rid,kind,b,budget,sim_time):
        # This detached single-car authority recheck runs ONCE on the worker,
        # not on the 500Hz consumption path. No backend API is used here.
        with self.control.lock:
            state=self.control.snapshot_robot(rid);current=state['bindings'][rid][kind];now=self.clock()
            if (state['stopped'] or current['owner'] is None
                or (current['epoch'],current['owner'],current['lease_epochs'])!=(b['epoch'],b['owner'],b['lease_epochs'])
                or not self._binding_active(current,now)):return False
            for channel,epoch in b['lease_epochs'].items():
                lease=state['leases'][rid][channel]
                if lease['owner']!=b['owner'] or lease['epoch']!=epoch or now>=lease['expires']:return False
            return self._private_camera_valid(rid,kind,current,budget,sim_time)

    def _private_output_valid(self,key,b,sim_time):
        return self._camera_budget_current(*key,b,self.output_budgets.get(key),sim_time,private=key in self._private_outputs)

    def _camera_budget_current(self,rid,kind,b,budget,sim_time,*,private=False):
        if budget is None:return True
        if budget.get('source')=='navigation_sensor_v1':
            check=getattr(self.backend,'navigation_capture_valid',None)
            return kind=='navigation' and callable(check) and bool(check(rid,self._episode,budget,sim_time))
        if private:return self._private_camera_valid(rid,kind,b,budget,sim_time)
        check=getattr(self.camera,'sensor_capture_valid',None)
        # Preserve legacy duck-typed camera providers' existing budget API.
        return not callable(check) or bool(check(rid,self._episode,self._camera_binding(rid,kind,b),budget,sim_time))

    @staticmethod
    def _own_refresh_profile(kind,b,spec):
        # Bounded, trusted synchronous-ray rule profile only. Camera, custom
        # adapters and legacy bindings retain their original scheduling.
        return (kind=='navigation' and b.get('activation_required') is True
                and b['adapter_id']=='nav_rule_v1'
                and set(spec['required_sensors'])=={'odometry','ranges'})

    def _own_refresh_due(self,key,b,sim_time,now):
        old=self._own_samples.get(key)
        identity=(self._episode,b['epoch'],b['owner'])
        return bool(old and old['identity']==identity
            and now-old['wall_capture_end']>=self.observation_period
            and sim_time>old['sim_time']
            and b['activation_window_id']!=old['window_id']
            and b['activation_expires']>old['activation_expires'])

    def _schedule(self,snapshot,sim_time):
        from .contracts import build_observation,validate_observation
        for rid in self.control.robot_ids:
            raw=None;capture_start=None;capture_end=None
            for kind in KINDS:
                key=(rid,kind);b=snapshot['bindings'][rid][kind]
                if b['owner'] is None:
                    self._own_samples.pop(key,None)
                    self._camera_samples.pop(key,None)
                    self._navigation_samples.pop(key,None)
                    if self._slot_bound.pop(key,False) and key in self.slots:self.slots[key].submit({'deactivate':True})
                    continue
                if not self._binding_active(b,self.clock()):
                    self.status[key]='waiting_for_operator_activation';continue
                if self._fault_epochs.get(key)==b['epoch']:continue
                self._slot_bound[key]=True
                schedule_identity=(b['epoch'],b['owner'])
                previous=self.next_observation.get(key)
                spec=self.registry.get(b['adapter_id']).descriptor
                if spec.get('observation_profile')=='pointcloud_imu_v1':
                    self._schedule_navigation(rid,kind,b,spec,sim_time)
                    continue
                own_refresh=self._own_refresh_profile(kind,b,spec)
                private_pixels=(self.enable_native_pixels and getattr(self.camera,'enable_native_pixels',False)
                    and kind=='aim' and b['adapter_id']=='aim_native_rmcs_v1'
                    and self._native_pixels_denied.get(key)!=schedule_identity)
                camera_identity=getattr(self.camera,'native_sensor_identity' if private_pixels else 'sensor_identity',None)
                camera_paced=(spec.get('schedule_on_camera_frame') is True
                    and 'camera' in spec['required_sensors'] and callable(camera_identity))
                next_camera=None
                if camera_paced:
                    latest=camera_identity(rid,self._episode,self._camera_binding(rid,kind,b),sim_time,
                        min(self.action_ttl,spec.get('max_camera_age_wall_s',self.action_ttl),spec.get('max_camera_age_sim_s',self.action_ttl)))
                    if latest is not None:
                        next_camera=(self._episode,*schedule_identity,latest[0])
                        if self._camera_samples.get(key)==next_camera:continue
                reason='simulation_period'
                if previous and previous[0]==schedule_identity and sim_time<previous[1]:
                    if next_camera is not None:reason='new_camera_frame'
                    elif own_refresh and self._own_refresh_due(key,b,sim_time,self.clock()):reason='new_activation_own_sample'
                    else:continue
                elif next_camera is not None:reason='new_camera_frame'
                try:
                    if raw is None:
                        capture_start=self.clock();raw=self.backend.sensor_sample(rid);capture_end=self.clock()
                    seq=self.observed.get(key,0)+1;self.observed[key]=seq
                    camera=None;budget=None;pixel_token=None;native_pixels=None
                    spec=self.registry.get(b['adapter_id']).descriptor
                    if self.camera is not None and 'camera' in spec['required_sensors']:
                        if private_pixels:
                            packet=self.camera.native_sensor_packet(rid,self._episode,self._camera_binding(rid,kind,b),sim_time,self.action_ttl)
                            native_pixels=packet['pixels'];budget=packet['budget']
                        else:
                            packet=self.camera.sensor_packet(rid,self._episode,self._camera_binding(rid,kind,b),sim_time,self.action_ttl)
                            camera=packet['camera'];budget=packet['budget'];pixel_token=packet.get('pixel_token')
                        if budget is not None:
                            budget['sim_deadline']=min(budget['sim_deadline'],budget['capture_sim_time']+min(self.action_ttl,spec.get('max_camera_age_sim_s',self.action_ttl)))
                            budget['wall_deadline']=min(budget['wall_deadline'],budget['capture_wall']+min(self.action_ttl,spec.get('max_camera_age_wall_s',self.action_ttl)))
                    observation=validate_observation(build_observation(raw,binding_epoch=b['epoch'],observed_seq=seq,
                        wall_deadline=self.clock()+self.action_ttl))
                    if own_refresh and (not math.isfinite(raw.sim_time)
                        or abs(raw.sim_time-sim_time)>.5e-9
                        or (observation['sensors']['ranges']['available'] and
                            abs(observation['sensors']['ranges']['capture_sim_time']-sim_time)>.5e-9)):
                        raise ValueError('fresh_own_sample_time_mismatch')
                    if b.get('activation_required',False):observation['wall_deadline']=min(observation['wall_deadline'],b['activation_expires'])
                    if camera is not None:observation['sensors']['camera']=camera
                    if budget is not None:observation['wall_deadline']=min(observation['wall_deadline'],budget['wall_deadline'])
                    if (observation['robot_id']!=rid or observation['episode']!=self._episode
                        or not 0<=sim_time-observation['sim_time']<=self.action_ttl):
                        raise ValueError('sensor_authority_identity_or_time_mismatch')
                except Exception as exc:
                    self._own_samples.pop(key,None)
                    self.outputs.pop(key,None);self._fault_epochs[key]=b['epoch']
                    self.status[key]='sensor_error:'+type(exc).__name__
                    if key in self.slots:self.slots[key].submit({'deactivate':True})
                    continue
                spec=self.registry.get(b['adapter_id']).descriptor
                missing=[name for name in spec['required_sensors']
                         if not (all(observation['own'][k] is not None for k in ('odom_xyyaw','odom_vxyw'))
                                 if name=='odometry' else ((name=='camera' and native_pixels is not None)
                                     or observation['sensors'].get(name,{}).get('available',False)))]
                self.next_observation[key]=(schedule_identity,sim_time+self.observation_period)
                sample_identity=None
                if own_refresh:
                    sample_identity=dict(episode=self._episode,robot_id=rid,sim_time=observation['sim_time'],
                        sim_ns=round(observation['sim_time']*1e9),wall_capture_start=capture_start,wall_capture_end=capture_end)
                    self._own_samples[key]=dict(identity=(self._episode,b['epoch'],b['owner']),
                        sim_time=observation['sim_time'],wall_capture_end=capture_end,
                        window_id=b['activation_window_id'],activation_expires=b['activation_expires'])
                    if self.clock()>=observation['wall_deadline']:
                        self.status[key]='sample_authorization_expired'
                        self._trace('adapter_sample_rejected',robot_id=rid,kind=kind,binding_epoch=b['epoch'],
                            observed_seq=seq,reason='original_authorization_expired',sample_identity=sample_identity,
                            wall_deadline=observation['wall_deadline'])
                        continue
                if missing:
                    self.outputs.pop(key,None);self.status[key]='required_sensor_unavailable:'+','.join(missing);continue
                if budget is not None and not self._budget_valid(budget,self.clock(),sim_time):
                    self.status[key]='camera_sample_expired'
                    self._trace('adapter_sample_rejected',robot_id=rid,kind=kind,binding_epoch=b['epoch'],
                        observed_seq=seq,reason='original_camera_deadline_expired',sensor_budget=budget,
                        wall_deadline=observation['wall_deadline'])
                    continue
                if camera_paced and budget is not None:
                    # Publication can advance between the cheap identity peek
                    # and this atomic sensor packet. Bind the ACTUAL job frame.
                    next_camera=(self._episode,*schedule_identity,budget['frame_id'])
                    if self._camera_samples.get(key)==next_camera:continue
                if key not in self.slots:
                    self.slots[key]=AdapterSlot(self.registry,self.clock)
                if next_camera is not None:self._camera_samples[key]=next_camera
                self._trace('adapter_enqueue',robot_id=rid,kind=kind,binding_epoch=b['epoch'],episode=self._episode,observed_seq=seq,observation_sim_time=observation['sim_time'],wall_deadline=observation['wall_deadline'],sensor_budget=budget,schedule_reason=reason,sample_identity=sample_identity,operator_authorization={f:b.get(f) for f in ('epoch','activation_required','activation_seq','activation_expires','activation_window_id','activation_window_deadline')})
                job=dict(kind=kind,binding=b,observation=observation,sensor_budget=budget,pixel_token=pixel_token,sample_identity=sample_identity,operator_authorization={f:b.get(f) for f in ('epoch','activation_required','activation_seq','activation_expires','activation_window_id','activation_window_deadline')})
                if native_pixels is not None:
                    job.update(native_pixels=native_pixels,native_consumer=self._camera_binding(rid,kind,b),
                        native_camera_check=lambda rid=rid,kind=kind,b=b,budget=budget,sim_time=sim_time:self._private_job_valid(rid,kind,b,budget,sim_time))
                self.slots[key].submit(job)
                if key not in self.outputs:self.status[key]='waiting_for_adapter'

    def _schedule_navigation(self,rid,kind,b,spec,sim_time):
        """Only explicit local profiles receive the pose-free sensor protocol."""
        from .navigation_contracts import build_navigation_observation
        key=(rid,kind)
        try:
            if kind!='navigation' or set(spec['required_sensors'])!={'pointcloud','imu'}:
                raise ValueError('navigation_sensor_profile_capabilities')
            provider=getattr(self.backend,'navigation_sensor_packet',None)
            packet=provider(rid) if callable(provider) else None
            if packet is None:
                self.status[key]='waiting_for_navigation_sensors';return
            cloud=packet['sensors']['pointcloud']
            sample=(self._episode,b['epoch'],b['owner'],cloud['frame_id'])
            if self._navigation_samples.get(key)==sample:return
            if packet['robot_id']!=rid or packet['episode']!=self._episode:
                raise ValueError('navigation_sensor_identity_mismatch')
            age=min(self.action_ttl,.15)
            budget=dict(source='navigation_sensor_v1',frame_id=cloud['frame_id'],
                profile_sha256=cloud['profile_sha256'],capture_wall=packet['capture_wall'],
                capture_sim_time=cloud['capture_sim_time'],wall_deadline=packet['capture_wall']+age,
                sim_deadline=cloud['capture_sim_time']+age)
            deadline=budget['wall_deadline']
            if b.get('activation_required',False):deadline=min(deadline,b['activation_expires'])
            seq=self.observed.get(key,0)+1
            observation=build_navigation_observation(packet,binding_epoch=b['epoch'],observed_seq=seq,wall_deadline=deadline)
            if (not self._budget_valid(budget,self.clock(),sim_time) or self.clock()>=deadline
                or not self._camera_budget_current(rid,kind,b,budget,sim_time)):
                self.status[key]='navigation_sensor_expired';return
            self.observed[key]=seq;self._navigation_samples[key]=sample
            if key not in self.slots:self.slots[key]=AdapterSlot(self.registry,self.clock)
            authorization={f:b.get(f) for f in ('epoch','activation_required','activation_seq','activation_expires',
                'activation_window_id','activation_window_deadline')}
            validated_cloud=observation['sensors']['pointcloud']
            cloud_acquisition=dict(frame_id=budget['frame_id'],
                acquisition_start_ns=validated_cloud['acquisition_start_ns'],
                acquisition_end_ns=validated_cloud['acquisition_end_ns'],profile_sha256=budget['profile_sha256'])
            self._trace('adapter_enqueue',robot_id=rid,kind=kind,binding_epoch=b['epoch'],episode=self._episode,
                observed_seq=seq,observation_sim_time=observation['sim_time'],wall_deadline=deadline,
                sensor_budget=budget,cloud_acquisition=cloud_acquisition,
                schedule_reason='new_navigation_scan',operator_authorization=authorization)
            self.slots[key].submit(dict(kind=kind,binding=b,observation=observation,sensor_budget=budget,
                operator_authorization=authorization))
            if key not in self.outputs:self.status[key]='waiting_for_navigation'
        except Exception as exc:
            self.outputs.pop(key,None);self._fault_epochs[key]=b['epoch'];self.status[key]='sensor_error:'+type(exc).__name__
            if key in self.slots:self.slots[key].submit({'deactivate':True})

    def _targets(self,snapshot,sim_time,*,sampled_wall=None):
        now=self.clock() if sampled_wall is None else sampled_wall;result={}
        for rid in snapshot['robot_ids']:
            leases=snapshot['leases'][rid];bindings=snapshot['bindings'][rid]
            t=dict(motion=None,gimbal=None,fire=False)
            for channel in ('motion','gimbal','fire'):
                l=leases[channel]
                if l['owner'] is None or now>=l['expires'] or (channel=='motion' and l.get('mode_fault',False)):continue
                if channel=='fire':
                    t['fire']=bool(l['input'] and now<l['input_expires'] and l['input']['fire']);continue
                kind='navigation' if channel=='motion' else 'aim';b=bindings[kind]
                if b['owner'] is None:
                    t[channel]=l['input'] if now<l['input_expires'] else None
                    continue
                if not self._binding_active(b,now):continue
                output=self.outputs.get((rid,kind))
                if (output is not None and output['binding_epoch']==b['epoch']
                    and output['robot_id']==rid and output['episode']==self._episode
                    and now<output['wall_deadline'] and 0<=sim_time-output['sim_time']<=self.action_ttl
                    and self._budget_valid(self.output_budgets.get((rid,kind)),now,sim_time)
                    and self._private_output_valid((rid,kind),b,sim_time)):
                    command=output['command']
                    if kind=='navigation' or command['active']:
                        if self.backend.validate_target(rid,channel,command):t[channel]=command
                        else:self.status[rid,kind]='robot_limit_rejected'
            aim_binding=bindings['aim']
            if aim_binding['owner'] is not None and self._registry_capability(aim_binding['adapter_id'],'stationary_only'):
                pose=self.backend.own_pose(rid)
                from .spin import requested_yaw
                requested_motion=t['motion'] is not None and (any(abs(t['motion'][k])>1e-9 for k in ('vx_mps','vy_mps')) or abs(requested_yaw(t['motion']))>1e-9)
                measured_motion=abs(pose['wz'])>.03 or (pose['vx']**2+pose['vy']**2)**.5>.03
                if requested_motion or measured_motion:
                    t['gimbal']=None;self.status[rid,'aim']='stationary_required'
            if not self.backend.allowed(rid):t=dict(motion=None,gimbal=None,fire=False)
            result[rid]=t
        return result

    def step_once(self):
        self._check_authority()
        if self.stop_event.is_set() or self.control.stopped:return False
        episode=self.backend.episode
        if self._episode is not None and self._episode!=episode:
            self.control.reset_episode();self.outputs.clear();self._own_samples.clear();self._camera_samples.clear();self._navigation_samples.clear();self._private_outputs.clear();self._native_pixels_denied.clear();self._aim_status_context.clear()
        self._episode=episode
        sim_time=self.backend.sim_time
        prepare=getattr(self.backend,'prepare_navigation_sensors',None)
        if callable(prepare):prepare()
        snapshot=self.control.snapshot()
        if self.camera is not None:
            try:self.camera.capture_from_authority(self.backend._sim,self._camera_desired(snapshot))
            except Exception as exc:
                self.camera.fault(type(exc).__name__)  # Camera faults never stop physics or lease expiry.
        self._collect(snapshot,sim_time)
        self._schedule(snapshot,sim_time)
        # Linearization point: recheck ownership/expiry immediately before applying
        # commands. A release/bind accepted by HTTP cannot race a stale write.
        # Only the short authoritative physics step holds this lock, not sensors,
        # rendering, plugin construction or inference.
        with self.control.lock:
            current=self.control.snapshot()
            targets=self._targets(current,sim_time)
            apply_wall=self.clock()
            consumed=[]
            guard_cache={}
            guard_revision=[current['revision']]
            guard_state=[current]
            def command_guard(rid,command,phase,sampled_wall=None):
                # The control lock spans this entire integration. Expiry and the
                # revision are still checked at EVERY consumption boundary; a
                # revocation/rebind invalidates all detached cached metadata.
                # Input/window/result expiry is independently checked by _targets
                # with a fresh clock (or the uniform integration-entry sample).
                # Re-copying unchanged binding configs 18 times per 2ms step
                # provides no additional authority and competes for the GIL.
                self.control._expire()
                if self.control.revision!=guard_revision[0]:
                    guard_state[0]=self.control.snapshot()
                    guard_revision[0]=guard_state[0]['revision'];guard_cache.clear()
                if rid not in guard_cache:
                    state=guard_state[0]
                    guard_cache[rid]=dict(robot_ids=[rid],leases={rid:state['leases'][rid]},
                                         bindings={rid:state['bindings'][rid]})
                guard_snapshot=guard_cache[rid]
                # Prepare detached evidence before sampling the logical consume
                # boundary. A second clock read for the receipt could cross the
                # original deadline after _targets had already authorized input.
                receipt=dict(episode=self._episode,robot_id=rid,phase=phase,
                    binding_epoch=guard_snapshot['bindings'][rid]['aim']['epoch'],
                    adapter_authorizations={k:{f:guard_snapshot['bindings'][rid][k].get(f) for f in ('epoch','owner','adapter_id','activation_required','activation_seq','activation_expires','activation_window_id','activation_window_deadline')} for k in KINDS},
                    adapter_output_authorizations={k:copy.deepcopy(value) if (value:=self.output_authorizations.get((rid,k))) is not None else None for k in KINDS},
                    manual_inputs={c:{k:guard_snapshot['leases'][rid][c].get(k) for k in ('owner','epoch','seq','expires','input_expires','input_window_id','input_window_deadline')} for c in ('motion','gimbal','fire')},
                    budget=copy.deepcopy(budget) if (budget:=self.output_budgets.get((rid,'aim'))) is not None else None)
                # The engine's uniform integration-entry sample remains its
                # original logical latch for all cars. Other phases take a new
                # sample here; Python scheduling cannot promise hard real time.
                consume_wall=self.clock() if sampled_wall is None else sampled_wall
                consume_sim_time=self.backend.sim_time
                checked=self._targets(guard_snapshot,consume_sim_time,sampled_wall=consume_wall)[rid]
                # Every displayed applied target reflects the final guard too.
                targets[rid]=checked
                # Validated motion/spin/gimbal command fields are flat scalars;
                # copying their small dictionaries detaches evidence without
                # traversing nonexistent commands for every idle robot/phase.
                receipt_target=dict(checked,motion=dict(checked['motion']) if checked['motion'] is not None else None,
                    gimbal=dict(checked['gimbal']) if checked['gimbal'] is not None else None)
                receipt.update(consume_wall=consume_wall,consume_sim_time=consume_sim_time,target=receipt_target)
                consumed.append(receipt)
                return checked
            if hasattr(self.backend,'guarded_step'):self.backend.guarded_step(targets,command_guard,clock=self.clock)
            else:self.backend.step(targets)
        for receipt in consumed:self._trace('actuator_consumed',**receipt)
        if getattr(self.backend,'last_integration_timing',None):
            self._trace('integration_boundary',episode=self._episode,sim_time=sim_time,targets=targets,output_budgets={r:self.output_budgets.get((r,'aim')) for r in self.control.robot_ids},**self.backend.last_integration_timing)
        self._trace('physics_apply',apply_wall=apply_wall,sim_time=sim_time,episode=self._episode,targets=targets,output_budgets={r:self.output_budgets.get((r,'aim')) for r in self.control.robot_ids},aim_bindings={r:current['bindings'][r]['aim']['epoch'] for r in self.control.robot_ids})
        self.steps+=1;self.last_step_wall=self.clock()
        display=self.backend.display_snapshot()
        if self.camera is not None:
            display['camera']=self.camera.status()
            display['limitations']=[v for v in display.get('limitations',[]) if v!='no_gl_camera_unavailable']
            display['scenario']='existing_3v3_scene_role_v23_optics'
        # Index receipts once; serialize each retained entry/final only once.
        # The complete phase stream still goes to _trace above. A final receipt
        # is shared between the two display indexes, never with live control.
        receipt_index={r:dict(entry=None,final=None) for r in self.control.robot_ids}
        for receipt in consumed:
            indexed=receipt_index[receipt['robot_id']]
            indexed['final']=receipt
            if receipt['phase']=='integration_entry':indexed['entry']=receipt
        detached=json_copy(dict(targets=targets,feedback=getattr(self.backend,'last_motion_feedback',{}),
                                receipts=receipt_index))
        display.update(runtime_state='running',telemetry_available=True,steps=self.steps,
            clock_profile=dict(kind='wall_deadline_live',simulation_time_unit='seconds',wall_clock='server_monotonic',real_time_factor_limit=self.real_time_factor),
            authority_thread=self._authority,applied_targets=detached['targets'],
            motion_feedback=detached['feedback'],
            spin_consumption_receipts=detached['receipts'],
            manual_consumption_receipts={r:detached['receipts'][r]['final'] for r in self.control.robot_ids},
            algorithm_status={r:{k:self.status.get((r,k),'unbound') if current['bindings'][r][k]['owner'] else 'unbound'
                for k in KINDS} for r in self.control.robot_ids},
            algorithm_status_context={r:{'aim':dict(self._aim_status_context[(r,'aim')])}
                for r in self.control.robot_ids if (r,'aim') in self._aim_status_context
                and self.status.get((r,'aim')) in ('active','waiting_for_aim:no_target','waiting_for_aim:pending_result')},
            worker_limits=dict(max_slots=2*len(self.control.robot_ids),created=len(self.slots),
                max_pending_per_slot=1,max_running_per_slot=1,dropped=sum(s.dropped for s in self.slots.values()),
                lifecycle_errors=sum(s.lifecycle_error is not None for s in self.slots.values())))
        with self.cache_lock:self.cached=display
        return True

    def snapshot(self,token):
        # Current lease state and historical applied sample have separate stamps.
        from .state_projection import project_state
        with self.control.lock:
            session=self.control._session(token)
            control=self.control.snapshot(token)
            with self.cache_lock:value=copy.deepcopy(self.cached)
            value['control']=control
            value['applied_sample_is_historical']=True
            return project_state(value,control,session_id=session.sid,role=session.role,
                                 allowed_robots=session.allowed_robots,audit_authorized=session.audit_authorized)

    def health(self):
        with self.cache_lock:
            return dict(runtime_state=self.cached['runtime_state'],steps=self.steps,
                error=self.error,transport='loopback_only',cross_machine_LAN_verified=False)

    def run(self,*,max_wall_seconds=None,real_time_factor=1.):
        if type(real_time_factor) not in (int,float) or not 0<real_time_factor<=1:raise ValueError('real_time_factor must be within (0, 1]')
        self.real_time_factor=float(real_time_factor)
        self._check_authority();start=self.clock();deadline=start
        try:
            while not self.stop_event.is_set() and not self.control.stopped:
                if max_wall_seconds is not None and self.clock()-start>=max_wall_seconds:break
                self.step_once()
                # Keep the wall-clock origin: an OS/GIL/render stall must not
                # permanently discard physical steps. While behind, integrate
                # the original dt without sleeping; when caught up, wait again.
                # Every catch-up step still gates commands on ACTUAL wall time,
                # and never waits for an algorithm or refreshes its timestamps.
                deadline+=self.backend.timestep/real_time_factor
                if sys.platform=='win32' and self.clock is time.perf_counter:
                    # Event.wait uses a coarse Windows wait; a sub-2ms remainder
                    # can sleep an entire scheduler tick. CPython's sleep uses a
                    # high-resolution waitable timer without global timer changes.
                    # Check stop at most every 5ms and retain the original deadline.
                    while not self.stop_event.is_set() and not self.control.stopped:
                        remaining=deadline-self.clock()
                        if remaining<=0:break
                        time.sleep(min(remaining,.005))
                else:self.stop_event.wait(max(0.,deadline-self.clock()))
        except Exception as exc:
            self.error=type(exc).__name__
            raise
        finally:self.close()

    def request_stop(self):
        self.stop_event.set();self.control.stop()
        if self.camera is not None:self.camera.stop()

    def _shutdown_workers(self):
        return dict(self.slots)

    def close(self):
        self._check_authority()
        if self._closed:return
        self._closed=True;self.request_stop()
        workers=self._shutdown_workers()
        for slot in workers.values():slot.close()
        # One wall budget for ALL slots, not N independent waits. This occurs
        # only during shutdown, after authority revocation, never a physics tick.
        join_started=time.perf_counter();join_deadline=join_started+1.5
        for slot in workers.values():
            thread=getattr(slot,'thread',None)
            if thread is not None:thread.join(max(0.,join_deadline-time.perf_counter()))
        unfinished=[dict(robot_id=r,kind=k) for (r,k),slot in workers.items()
                    if getattr(slot,'thread',None) is not None and slot.thread.is_alive()]
        faults=[dict(robot_id=r,kind=k,error=slot.lifecycle_error) for (r,k),slot in workers.items() if getattr(slot,'lifecycle_error',None)]
        self.shutdown_status=dict(clean=not unfinished and not faults,unfinished_slots=unfinished,
                                  lifecycle_errors=faults,join_budget_s=1.5,join_elapsed_s=time.perf_counter()-join_started)
        if not self.shutdown_status['clean'] and self.error is None:self.error='adapter_shutdown_incomplete'
        # Zero actuator intent on the authority thread; no simulated time jump.
        neutral={r:dict(motion=None,gimbal=None,fire=False) for r in self.control.robot_ids}
        self.backend.neutralize()
        display=self.backend.display_snapshot()
        if self.camera is not None:display['camera']=self.camera.status()
        display.update(runtime_state='error' if self.error else 'stopped',telemetry_available=True,
            steps=self.steps,applied_targets=neutral,error=self.error,shutdown_status=self.shutdown_status)
        with self.cache_lock:self.cached=display
        self.backend.close()
