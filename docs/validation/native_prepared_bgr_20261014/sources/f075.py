"""Opt-in stationary red-sentry source adapter for the local sports simulation.

Actual RMCS detector/PnP/tracker/control are unchanged. The independently rebuilt
headless adapter gates detector candidates before source selection. This adapter
never authorizes firing. It must run on the physics owner thread with a separately
configured native camera/model; the UI display stream is not an algorithm clock.
The caller MUST recheck the live session/epoch/robot/lease after this synchronous
call, before applying a result; HTTP input can change while inference is running.
"""
from dataclasses import asdict,replace
import json,math,select
from pathlib import Path

from ..contracts import Command
from ..rmcs_stop_aim import RMCSStopAim, sha
from ..integrations.rmcs_process import RMCSProcess
from .autoaim import parse_aim_request

IDENTITY='rmcs-sim-operator-fov-v1'

class OperatorFovProcess(RMCSProcess):
    def __init__(self,*args,fov,**kwargs):
        super().__init__(*args,**kwargs);self.fov=fov
    def control(self,packet):
        request=dict(control_time_ns=packet['control_time_ns'],
                     time_s=packet['control_time_ns']/1e9,frame=packet['frame'],operator_fov=self.fov)
        if self.process.poll() is not None:raise RuntimeError('Operator source process exited')
        self.process.stdin.write(json.dumps(request,allow_nan=False)+'\n');self.process.stdin.flush()
        ready,_,_=select.select([self.process.stdout],[],[],self.timeout)
        if not ready:raise TimeoutError('Operator source response timeout')
        response=json.loads(self.process.stdout.readline())
        if (response.get('status')!='ok' or response.get('runner_identity')!=IDENTITY
            or response.get('clock_time_ns')!=packet['control_time_ns']
            or response.get('direction_frame')!='world'
            or type(response.get('tracking')) is not bool):
            raise ValueError('Operator source identity/clock/output mismatch: '+str(response))
        return dict(response,episode=packet['episode'],should_control=response['tracking'])


class OperatorSourceAim(RMCSStopAim):
    def __init__(self,sim,spec_path,out):
        spec=json.loads(Path(spec_path).read_text())
        if spec.get('operator_identity')!=IDENTITY:
            raise ValueError('Explicit operator FOV spec required; frozen benchmark is not interchangeable')
        if spec.get('frozen_build',{}).get('binary_sha256')!=sha(spec['binary']):
            raise ValueError('Operator FOV binary hash mismatch')
        if abs(float(sim.model.opt.timestep)-.0005)>1e-12:
            raise ValueError('Operator source requires 2000Hz physics; do not inherit display cadence')
        self.fov=None
        self.requested_fov=dict(fov_degrees=85.,circle_radius_x_norm=.25,circle_radius_y_norm=.25)
        super().__init__(sim,spec_path,out,client_factory=self._factory)
        self.source_label='SIM OPERATOR RMCS FOV';self.identity=None
        self.pending_frame=None;self.selected_id=None;self.capture_bucket=-1
        self.control_bucket=-1;self.captured_frames=0;self.feedback={}
        self.latest_command=None;self.status='not_requested';self.requested=False;self.held=False;self.last_detector_summary={}
        self.provenance.update(operator_identity=IDENTITY,physics_hz=2000,source_capture_hz=80,
            source_control_hz=100,source_detector_hz=36,source_capture_and_inference_hz=None,
            frame_delivery='Native 80Hz simulation-time captures; newest frame selected at rational 36Hz opportunities on 100Hz source control ticks',
            source_fire_authority='none; source fire is never applied; bridge retains separate manual-fire authority',
            qualification_scope='Stationary red_sentry simulation operator integration; no full match or hardware qualification')
        (self.out/'provenance.json').write_text(json.dumps(self.provenance,indent=2))
    def _factory(self,*args,**kwargs):
        return OperatorFovProcess(*args,fov=self.fov,timeout=2.,**kwargs)
    def _new_segment(self,o):
        segment=self.out/f'segment_{self.segment+1:03d}';segment.mkdir(exist_ok=True)
        (segment/'tracking_mode').write_text('multi_ekf\n')
        self.pending_frame=None;self.selected_id=None
        super()._new_segment(o)
    def _close_segment(self,o,reason):
        super()._close_segment(o,reason)
        self.pending_frame=None;self.selected_id=None;self.latest_command=None;self.last_detector_summary={}
    def capture(self,o):
        if self.pending_frame is None or self.pending_frame['frame_id']==self.selected_id:return None
        self.selected_id=self.pending_frame['frame_id'];self.delivered_frames+=1
        return self.pending_frame
    def disengage(self,o,reason):
        self._close_segment(o,reason);self.gate.reset();self.status=reason
        self.control_bucket=-1;self.capture_bucket=-1
        return self._feedback(None,reason)
    def _feedback(self,command,reason):
        response=self.latest_response or {}
        self.feedback=dict(available=reason not in ('unsupported_robot','source_error','own_motion_requested','chassis_motion','origin_drift','referee_or_emergency_gate','invalid_own_state'),requested=self.requested,held=self.held,active=command is not None,authority='source_autoaim' if command else 'manual',
            reason=reason,algorithm=IDENTITY,source_frame_seq=self.selected_id,
            source_sim_time=response.get('result_exposure_time_s') if response.get('result_exposure_time_s') is not None else self.last_accepted_s,selected=command is not None,
            in_fov=True if command is not None else None,
            fov_applied=self.client is not None and self.last_detector_summary.get('sim_time') is not None and self.fov==self.requested_fov,fov=self.requested_fov,
            fov_raw2d=self.last_detector_summary.get('fov_raw2d'),fov_admitted2d=self.last_detector_summary.get('fov_admitted2d'),
            fov_rejected2d=self.last_detector_summary.get('fov_rejected2d'),
            fov_counts_sim_time=self.last_detector_summary.get('sim_time'),fov_counts_frame_seq=self.last_detector_summary.get('frame_seq'),fire_authority='manual_only',
            simulation_only=True,supported_robot='red_sentry',stationary_only=True)
        return command
    def act_operator(self,o,request,*,identity,allowed,move_requested=False,spin_requested=False):
        request=parse_aim_request(asdict(request))
        self.requested,self.held=request.enabled,request.hold
        fov={k:v for k,v in asdict(request).items() if k not in ('enabled','hold')}
        self.requested_fov=fov
        if self.error is not None:return self.disengage(o,'source_error')
        reason=None
        if o.robot_id!='red_sentry':reason='unsupported_robot'
        elif not allowed:reason='operator_ineligible'
        elif not request.enabled:reason='module_disabled'
        elif not request.hold:reason='right_button_released'
        elif move_requested or spin_requested:reason='own_motion_requested'
        if reason:return self.disengage(o,reason)
        if identity!=self.identity or fov!=self.fov:
            self.disengage(o,'identity_or_fov_changed');self.identity=identity;self.fov=fov
        # Check motion/referee every physics step, including between source ticks.
        if not self.gate.update(o,'occupation',(0.,0.)):
            reason=self.gate.reason;self._close_segment(o,reason)
            return self._feedback(None,reason)
        step=round(o.sim_time*2000)
        bucket=step*80//2000
        if self.client and bucket!=self.capture_bucket:
            self.pending_frame=super().capture(o);self.delivered_frames-=1
            self.captured_frames+=1;self.capture_bucket=bucket
        control_bucket=step//20
        if control_bucket!=self.control_bucket:
            self.control_bucket=control_bucket
            candidate=super().act(o,'occupation',(0.,0.))
            response=self.latest_response or {}
            if response.get('detector_executed'):
                self.last_detector_summary={k:response.get(k) for k in ('fov_raw2d','fov_admitted2d','fov_rejected2d')}
                self.last_detector_summary.update(sim_time=response.get('result_exposure_time_s'),frame_seq=self.selected_id)
            age=response.get('target_age_s')
            fresh=(isinstance(age,(int,float)) and math.isfinite(age) and 0<=age<=.08)
            accepted=(response.get('should_control') is True and response.get('observation_shoot_allowed') is True
                      and fresh and self.error is None)
            # Do not reinterpret ballistic fire permission. Manual fire stays in
            # the caller's separate existing operator/referee path.
            self.latest_command=replace(candidate,fire=False) if accepted else None
        if self.error:
            return self._feedback(None,'source_error')
        if self.latest_command is not None and (self.last_accepted_s is None or not 0<=o.sim_time-self.last_accepted_s<=.08):
            self.latest_command=None
            return self._feedback(None,'source_observation_stale')
        return self._feedback(self.latest_command,'source_tracking' if self.latest_command else 'no_admitted_source_target')
