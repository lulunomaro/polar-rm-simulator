"""Actual RMCS native process, enabled only on a stable stationary chassis.

No moving-origin compensation is asserted. Every move/death/phase exit closes the
process, clears fire and discards tracking; the next stationary segment restarts.
"""
from dataclasses import replace,asdict
from pathlib import Path
import hashlib,json,math,os
import numpy as np
import mujoco
from .camera_profile import SourceCameraProfile,SourceLensWarp
from .contracts import Command
from .integrations.rmcs_contract import own_state,command_from_direction,rotation
from .integrations.rmcs_process import RMCSProcess
from .integrations.own_gravity import OwnGravityCompensator


class StationaryGate:
    def __init__(self,speed_m_s=.03,yaw_rate_rad_s=.03,hold_s=.4,max_segment_drift_m=.025):
        self.speed_limit=speed_m_s;self.yaw_rate_limit=yaw_rate_rad_s;self.hold_s=hold_s
        self.max_segment_drift=max_segment_drift_m;self.reset()
    def reset(self):
        self.stable_since=None;self.anchor=None;self.active=False;self.reason='not_started'
        self.episode=None;self.last_time=None
    def update(self,o,mode,desired_velocity=(0.,0.)):
        new_epoch=self.episode is not None and o.episode!=self.episode
        reversed_time=self.last_time is not None and o.sim_time<self.last_time
        self.episode=o.episode;self.last_time=o.sim_time
        if new_epoch or reversed_time:
            ok=False;reason='episode_changed' if new_epoch else 'time_reversed'
        elif o.odom_xyyaw is None or o.odom_vxyw is None or not np.isfinite((*o.odom_xyyaw,*o.odom_vxyw,o.sim_time,o.own_hp,*desired_velocity)).all():
            ok=False;reason='invalid_own_state'
        elif o.match_phase!='running' or o.emergency_stop or o.own_hp<=0 or o.own_weak:
            ok=False;reason='referee_or_emergency_gate'
        elif mode not in ('occupation','engage'):
            ok=False;reason='navigation_moving_or_resupply'
        elif len(desired_velocity)!=2 or math.hypot(*desired_velocity)>1e-6:
            ok=False;reason='navigation_motion_requested'
        elif math.hypot(*o.odom_vxyw[:2])>self.speed_limit or abs(o.odom_vxyw[2])>self.yaw_rate_limit:
            ok=False;reason='chassis_motion'
        else:ok=True;reason='settling'
        if not ok:
            self.stable_since=None;self.anchor=None;self.active=False;self.reason=reason;return False
        if self.anchor is not None and math.dist(self.anchor,o.odom_xyyaw[:2])>self.max_segment_drift:
            self.stable_since=None;self.anchor=None;self.active=False;self.reason='origin_drift';return False
        if self.stable_since is None:self.stable_since=o.sim_time;self.anchor=tuple(o.odom_xyyaw[:2])
        self.active=o.sim_time-self.stable_since>=self.hold_s-1e-9
        self.reason='stationary_source_aim' if self.active else reason
        return self.active


def source_fire_allowed(response,o,last_accepted_s,*,max_visual_age=.08,require_observation_contract=False):
    if not response or not response.get('tracking') or not response.get('should_shoot'):return False,'source_gate'
    if require_observation_contract and response.get('observation_shoot_allowed') is not True:
        return False,'source_observation_gate'
    age=response.get('target_age_s')
    if age is None or not math.isfinite(float(age)) or not 0<=age<=max_visual_age:return False,'source_target_age'
    if last_accepted_s is None or not 0<=o.sim_time-last_accepted_s<=max_visual_age:return False,'visual_lease'
    d=np.asarray(response.get('direction'),dtype=float)
    if d.shape!=(3,) or not np.isfinite(d).all() or np.linalg.norm(d)<1e-9:return False,'invalid_direction'
    return True,'source_permission_fresh'


def update_visual_lease(response,frame,now,previous,*,repaired=False):
    """Original 3D lease, or candidate's completed selected-observation lease.

    A completed-result exposure timestamp is never replaced by control time.
    This also prevents repeated/cached completion fields from renewing old data.
    """
    if repaired:
        if response.get('completed_result_event'):
            t=response.get('result_exposure_time_s')
            return (float(t) if response.get('completed_result_observed_now') is True
                    and frame is not None and response.get('frame_accepted') is True
                    and response.get('detector_executed') is True
                    and isinstance(t,(int,float)) and math.isfinite(t) and t>0 and 0<=now-t<=.08 else None)
        if response.get('observation_shoot_allowed') is not True:return None
        return previous
    if frame is not None and response.get('detector_executed'):
        return now if response.get('frame_stats',{}).get('accepted3d',0)>0 else None
    return previous


class RMCSStopAim:
    def __init__(self,sim,spec_path,out,*,client_factory=RMCSProcess):
        self.sim=sim;self.rid='red_sentry';self.out=Path(out);self.out.mkdir(parents=True,exist_ok=True)
        self.spec=json.loads(Path(spec_path).read_text());self.profile=SourceCameraProfile(overscan_pixels=64)
        if self.spec.get('id') not in ('original_upstream','repaired_observation_intercept_m038'):
            raise ValueError('Only the two explicitly reviewed local source identities are supported')
        self.repaired=self.spec['id']!='original_upstream'
        self.source_label='REPAIRED RMCS' if self.repaired else 'ORIGINAL RMCS'
        self.warp=SourceLensWarp(self.profile)
        self.renderer=mujoco.Renderer(sim.model,self.profile.render_height,self.profile.render_width)
        self.gravity=OwnGravityCompensator(sim.model,self.rid)
        self.gate=StationaryGate();self.factory=client_factory;self.client=None;self.segment=0;self.frame_id=0
        self.last_bucket=-1;self.latest_rgb=None;self.latest_response=None;self.last_accepted_s=None
        self.command=Command();self.status='navigation_moving';self.raw_ref=(0.,-.08)
        self.error=None
        self.events=[];self.last_status=None;self.source_calls=0;self.delivered_frames=0;self.tracking_ticks=0;self.fire_ticks=0
        self.pose_checks=verify_own_contract(sim,self.rid)
        self.files={str(Path(self.spec[k]).resolve()):sha(self.spec[k]) for k in ('binary','executor_yaml','autoaim_config')}
        self.spec_path=Path(spec_path).resolve();self.files[str(self.spec_path)]=sha(self.spec_path)
        expected=self.spec.get('frozen_build',{}).get('binary_sha256')
        if expected and sha(self.spec['binary'])!=expected:raise ValueError('Frozen source binary hash mismatch')
        if self.spec.get('runtime_mode_file'):
            mode=Path(self.spec['runtime_mode_file'])
            if mode.read_text().strip()!=self.spec['runtime_mode_expected']:raise ValueError('Runtime mode differs from the frozen spec')
            self.files[str(mode.resolve())]=sha(mode)
        model=Path(self.spec['model_share'])/'shenzhen-0526.onnx';self.files[str(model.resolve())]=sha(model)
        self.io=(self.out/'source_io.jsonl').open('w')
        self.provenance=dict(spec=self.spec,source_artifacts=self.files,camera=self.profile.manifest(),
            pose_contract_checks=self.pose_checks,gravity_feedforward=self.gravity.provenance,
            physics_hz=500,source_control_hz=100,source_capture_and_inference_hz=36,
            frame_delivery='instantaneous capture at processing opportunities; 20/30ms rational cadence, no 80Hz capture claim',
            stationary=dict(speed_m_s=.03,yaw_rate_rad_s=.03,hold_s=.4,max_segment_origin_drift_m=.025),
            additional_fire_gates=dict(visual_lease_s=.08,source_target_age_s=.08,actuator_saturation='inhibit',alignment_max_rad=.05),
            no_claim='No moving-origin tracker compensation, real hardware throughput, real MVS, or calibrated exposure blur.')
        (self.out/'provenance.json').write_text(json.dumps(self.provenance,indent=2))

    def _new_segment(self,o):
        self.segment+=1
        env=os.environ.copy();env.update(AUTOAIM_CONFIG=str(Path(self.spec['autoaim_config']).resolve()),
            RMCS_HEADLESS_SHARE=str(Path(self.spec['model_share']).resolve()),ORT_DISABLE_TELEMETRY='1')
        env.update({str(k):str(v) for k,v in self.spec.get('environment',{}).items()})
        self.client=self.factory(self.spec['binary'],self.spec['executor_yaml'],self.out/f'segment_{self.segment:03d}',env)
        self.client.reset(dict(episode=o.episode,sim_time_ns=round(o.sim_time*1e9),own_referee_id=7))
        self.last_accepted_s=None;self.latest_response=None;self.last_bucket=-1
        self.events.append(dict(type='source_segment_started',t=o.sim_time,segment=self.segment,
            own_pose=list(o.odom_xyyaw),stable_since=self.gate.stable_since))

    def _close_segment(self,o,reason):
        if self.client:
            self.client.close();self.client=None
            self.events.append(dict(type='source_segment_cleared',t=o.sim_time,segment=self.segment,reason=reason))
        self.last_accepted_s=None;self.latest_response=None

    def capture(self,o):
        self.renderer.update_scene(self.sim.data,camera=self.rid+'__aim')
        self.sim.draw_projectiles(self.renderer.scene)
        rgb=self.warp.apply(self.renderer.render());self.latest_rgb=rgb
        bgr=np.ascontiguousarray(rgb[...,::-1]);path=self.out/'latest_source_input.bgr';path.write_bytes(bgr.tobytes())
        frame=dict(schema='rmcs-mujoco-actor-frame-v1',episode=o.episode,frame_id=self.frame_id,
            exposure_timestamp_ns=round(o.sim_time*1e9),capture_time_s=o.sim_time,own_referee_id=7,own_team='red',
            image=dict(encoding='bgr8',width=self.profile.width,height=self.profile.height,stride_bytes=self.profile.width*3,
                bytes=bgr.nbytes,sha256=hashlib.sha256(bgr.tobytes()).hexdigest(),path=str(path.resolve())),
            camera=self.profile.adapter_intrinsics(),own=own_state(o))
        frame['camera']['distortion']=frame['camera']['distortion'].tolist()
        self.frame_id+=1;self.delivered_frames+=1
        return frame

    def act(self,o,mode,desired_velocity=(0.,0.)):
        try:
            return self._act(o,mode,desired_velocity)
        except Exception as exc:
            self.error=type(exc).__name__+': '+str(exc)
            self.status='source_error_fire_off'
            self.command=Command(gimbal_yaw=float(o.own_qpos[3]),gimbal_pitch=float(o.own_qpos[4]),fire=False)
            try:self._close_segment(o,'source_error')
            except Exception:pass
            self.events.append(dict(type='source_error',t=o.sim_time,error=self.error))
            return self.command

    def _act(self,o,mode,desired_velocity=(0.,0.)):
        runtime=getattr(self,'spec',{}).get('runtime_mode_file')
        if runtime and Path(runtime).read_text().strip()!=self.spec['runtime_mode_expected']:
            raise ValueError('Frozen runtime mode changed; stopping without substitution')
        eligible=self.gate.update(o,mode,desired_velocity)
        fire=False;fire_reason='chassis_not_stationary';response=None;frame=None;audit={}
        if not eligible:
            self._close_segment(o,self.gate.reason)
            # Deterministic centre scan uses public map and OWN pose only.
            x,y,base=o.odom_xyyaw
            yaw=math.atan2(-y,-x)-base+.35*math.sin(o.sim_time*.7)
            self.raw_ref=(math.atan2(math.sin(yaw),math.cos(yaw)),-.08)
            raw=Command(gimbal_yaw=self.raw_ref[0],gimbal_pitch=self.raw_ref[1],fire=False)
            self.status=self.gate.reason
        else:
            if self.client is None:self._new_segment(o)
            step=round(o.sim_time*500);bucket=step*36//500
            if bucket!=self.last_bucket:
                frame=self.capture(o);self.last_bucket=bucket
            packet=dict(episode=o.episode,control_time_ns=round(o.sim_time*1e9),frame=frame)
            response=self.client.control(packet);self.source_calls+=1;self.latest_response=response
            if frame is not None and response.get('detector_executed'):
                # A newly processed negative observation revokes the outer fire
                # lease immediately. Cached frame_stats on control-only ticks
                # cannot refresh it. This still does not establish selected-
                # target identity in the unmodified original source.
                self.last_accepted_s=update_visual_lease(response,frame,o.sim_time,self.last_accepted_s,repaired=getattr(self,'repaired',False))
                if self.last_accepted_s is not None and not (self.out/'first_accepted_source_input.png').exists():
                    from PIL import Image
                    Image.fromarray(self.latest_rgb).save(self.out/'first_accepted_source_input.png')
            else:
                self.last_accepted_s=update_visual_lease(response,frame,o.sim_time,self.last_accepted_s,repaired=getattr(self,'repaired',False))
            prefix='repaired' if getattr(self,'repaired',False) else 'original'
            if response.get('should_control'):
                raw=command_from_direction(response,o);self.raw_ref=(raw.gimbal_yaw,raw.gimbal_pitch)
                self.tracking_ticks+=1;self.status=prefix+'_RMCS_tracking_stationary'
            else:
                x,y,base=o.odom_xyyaw
                yaw=math.atan2(-y,-x)-base+.35*math.sin(o.sim_time*.7)
                self.raw_ref=(math.atan2(math.sin(yaw),math.cos(yaw)),-.08)
                raw=Command(gimbal_yaw=self.raw_ref[0],gimbal_pitch=self.raw_ref[1]);self.status=prefix+'_RMCS_search_stationary'
            fire,fire_reason=source_fire_allowed(response,o,self.last_accepted_s,require_observation_contract=getattr(self,'repaired',False))
            yaw_error=abs(math.atan2(math.sin(raw.gimbal_yaw-o.own_qpos[3]),math.cos(raw.gimbal_yaw-o.own_qpos[3])))
            pitch_error=abs(raw.gimbal_pitch-o.own_qpos[4])
            if yaw_error>.05 or pitch_error>.05:fire=False;fire_reason='own_gimbal_not_aligned'
            raw=replace(raw,fire=fire)
        command,audit=self.gravity.apply(raw,o)
        self.last_actuator_saturated=bool(audit['pitch_ctrl_clamped'] or audit['yaw_ctrl_clamped'])
        if self.last_actuator_saturated:
            command=replace(command,fire=False);fire_reason='actuator_saturation'
        if command.fire:self.fire_ticks+=1
        self.command=command
        if self.status!=self.last_status:
            self.events.append(dict(type='source_aim_state',t=o.sim_time,state=self.status));self.last_status=self.status
        # Actor input is logged separately from any evaluator-world truth.
        self.io.write(json.dumps(dict(t=o.sim_time,segment=self.segment,state=self.status,
            own=own_state(o),navigation_desired_velocity=list(desired_velocity),request_frame=frame,source_response=response,
            raw_reference=asdict(raw),gravity=audit,applied=asdict(command),fire_gate_reason=fire_reason),allow_nan=False)+'\n')
        return command

    def close(self):
        if self.client:self.client.close();self.client=None
        self.renderer.close();self.io.close()
        changed=[p for p,h in self.files.items() if sha(p)!=h]
        (self.out/'source_events.json').write_text(json.dumps(self.events,indent=2))
        result=dict(segments=self.segment,source_control_ticks=self.source_calls,delivered_native_frames=self.delivered_frames,
            tracking_ticks=self.tracking_ticks,fire_permission_ticks=self.fire_ticks,
            source_artifacts_unchanged=not changed,changed_files=changed)
        (self.out/'integration_summary.json').write_text(json.dumps(result,indent=2))
        if changed:raise RuntimeError('Source artifacts changed during run')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def configure_native_camera(xml):
    import xml.etree.ElementTree as ET
    profile=SourceCameraProfile(overscan_pixels=64);root=ET.fromstring(xml)
    root.find('visual/global').set('offwidth',str(profile.render_width));root.find('visual/global').set('offheight',str(profile.render_height))
    root.find('.//camera[@name="red_sentry__aim"]').set('fovy',str(profile.ideal_fovy_degrees))
    return ET.tostring(root,encoding='unicode')


def verify_own_contract(sim,rid):
    o=sim.observe(rid,False,False);own=own_state(o)
    pitch=sim.model.body(rid+'__pitch').id;camera=sim.model.camera(rid+'__aim').id;muzzle=sim.model.site(rid+'__muzzle').id
    R=rotation(o.odom_xyyaw[2]+o.own_qpos[3],o.own_qpos[4]);origin=np.asarray(own['yaw_origin_world_m'])
    errors=dict(pitch_rotation=float(np.max(np.abs(R-sim.data.xmat[pitch].reshape(3,3)))),
        camera_optical_rotation=float(np.max(np.abs(np.diag([1.,-1.,-1.])@sim.data.cam_xmat[camera].reshape(3,3).T@R-np.asarray(own['camera_optical_from_pitchlink_rotation'])))),
        camera_translation_m=float(np.linalg.norm(origin+R@np.asarray(own['camera_position_pitchlink_m'])-sim.data.cam_xpos[camera])),
        muzzle_translation_m=float(np.linalg.norm(origin+R@np.asarray(own['muzzle_position_pitchlink_m'])-sim.data.site_xpos[muzzle])))
    if max(errors.values())>1e-9:raise ValueError('Own pose/extrinsic contract failed: '+str(errors))
    return errors
