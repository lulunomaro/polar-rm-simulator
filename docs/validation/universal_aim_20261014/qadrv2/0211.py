"""Opt-in source-backed operator bridge. Ordinary stage2 runtime is unchanged.

All MuJoCo/native-source renders run on the physics owner's thread. Source work
never holds ControlGate.lock; every result is revalidated immediately before its
physics step. The viewer consumes the same warped camera image as the detector.
"""
from dataclasses import replace
import io
import math
import time
import xml.etree.ElementTree as ET

import mujoco
import numpy as np
from PIL import Image

from ..contracts import Command
from ..match_model import make_match_xml
from ..rmcs_stop_aim import configure_native_camera
from ..integrations.own_gravity import OwnGravityCompensator
from ..timing.plant import AuditedMatchSimulation
from .runtime import OperatorRuntime
from .source_aim import OperatorSourceAim,IDENTITY


SOURCE_ARMOR_PROFILE='role_v23'


class SourceOperatorRuntime(OperatorRuntime):
    def __init__(self,state,*,source_spec,source_out,render=True,camera_fps=2.,width=320,height=240,
                 source_factory=OperatorSourceAim,model_xml=None,display_renderer_factory=mujoco.Renderer):
        if not render:
            raise ValueError('Source autoaim requires native camera rendering; --no-render is incompatible')
        self.source=None;self.display_renderer=None;self.next_display_wall=0.;self.display_ai_index=0
        self.source_was_active=False;self.source_results_discarded=0
        self.source_error=None
        self.manual_gravity=None;self.manual_gravity_audit=None
        super().__init__(state,render=False,camera_fps=camera_fps,width=width,height=height)
        self.sim.close()
        self.armor_optical_profile=SOURCE_ARMOR_PROFILE if model_xml is None else 'custom_model_xml_unverified'
        if model_xml is None:
            root=ET.fromstring(configure_native_camera(make_match_xml(SOURCE_ARMOR_PROFILE)))
            root.find('option').set('timestep','.0005')
            model_xml=ET.tostring(root,encoding='unicode')
        self.sim=AuditedMatchSimulation(render=False,model_xml=model_xml)
        self._configure_selection()
        self.render_enabled=True
        self.manual_gravity=OwnGravityCompensator(self.sim.model,'red_sentry')
        self.source=source_factory(self.sim,source_spec,source_out)
        self.display_renderer=display_renderer_factory(self.sim.model,height,width)
        self.autoaim_status=dict(available=state.gate.robot_id=='red_sentry',active=False,
            requested=False,held=False,reason='module_disabled' if state.gate.robot_id=='red_sentry' else 'unsupported_robot',
            authority='manual',algorithm=IDENTITY,selected=False,in_fov=None,fov_applied=False,
            source_frame_seq=None,source_sim_time=None,fire_authority='manual_only',simulation_only=True,
            fov=dict(fov_degrees=85.,circle_radius_x_norm=.25,circle_radius_y_norm=.25))
        state.gate.source_autoaim_robots=('red_sentry',)
        state.gate.source_autoaim_ready=True
        self._publish()

    def start_camera(self):
        # No GL object migrates to a background thread in this mode.
        pass

    def _eligible(self,rid,reason):
        q=self.sim.data.qpos[self.sim.qindices[rid]]
        v=self.sim.data.qvel[self.sim.vindices[rid]]
        return (reason=='active' and np.isfinite(np.r_[q,v]).all()
                and self.sim.judge.robots[rid].alive and not self.sim.judge.terminal
                and not self.sim.paused and self.sim.phase=='running'
                and not self.sim.emergency_stop and self.camera_error is None)

    def _token(self):
        g=self.state.gate
        return (g.session_id,g.epoch,g.robot_id,g.safety_revision)

    def _publish_display(self,rid,rgb,obs,epoch,*,native=False,source_frame_seq=None):
        self.frame_seq+=1
        if native:
            image=Image.fromarray(rgb).resize((self.width,self.height),Image.Resampling.BILINEAR)
        else:image=Image.fromarray(rgb)
        buffer=io.BytesIO();image.save(buffer,format='JPEG',quality=85)
        meta=dict(epoch=epoch,robot_id=rid,frame_seq=self.frame_seq,sim_time=obs.sim_time,
                  width=self.width,height=self.height,source_frame_seq=source_frame_seq)
        if native:
            p=self.source.profile
            meta.update(native_width=p.width,native_height=p.height,source_camera=True,
                        calibration=dict(fx=p.fx,fy=p.fy,cx=p.cx,cy=p.cy,distortion=list(p.distortion)),
                        image_mapping='full_native_frame_resized',raw_algorithm_pixels=True)
        g=self.state.gate
        with g.lock:
            if epoch!=g.epoch or rid!=g.robot_id:return
            with self.state.lock:
                self.state.frame=buffer.getvalue();self.state.frame_meta=meta
            self.last_operator_frame=meta

    def _render_display_tick(self):
        if time.monotonic()<self.next_display_wall:return
        self.next_display_wall=time.monotonic()+1/self.camera_fps
        g=self.state.gate
        with g.lock:rid,epoch=g.robot_id,g.epoch
        o=self.sim.observe(rid,False,False)
        if rid=='red_sentry':
            # Native preview also works with the aim module off. It does not
            # deliver a detector frame or mutate source observation clocks.
            pending=self.source.pending_frame
            source_identity=self.source.identity
            if (pending is not None and self.source.latest_rgb is not None and source_identity is not None
                and source_identity[:3]==(g.session_id,epoch,rid)):
                rgb=self.source.latest_rgb
                captured=replace(o,sim_time=pending['capture_time_s'])
                self._publish_display(rid,rgb,captured,epoch,native=True,source_frame_seq=pending['frame_id'])
            else:
                renderer=self.source.renderer
                renderer.update_scene(self.sim.data,camera=rid+'__aim')
                self.sim.draw_projectiles(renderer.scene)
                rgb=self.source.warp.apply(renderer.render())
                self._publish_display(rid,rgb,o,epoch,native=True)
        else:
            r=self.display_renderer;r.update_scene(self.sim.data,camera=rid+'__aim')
            self.sim.draw_projectiles(r.scene)
            self._publish_display(rid,r.render().copy(),o,epoch)
        others=[r for r in self.sim.robot_ids if r!=rid]
        other=others[self.display_ai_index%len(others)];self.display_ai_index+=1
        obs=self.sim.observe(other,False,False)
        r=self.display_renderer;r.update_scene(self.sim.data,camera=other+'__aim')
        self.sim.draw_projectiles(r.scene);rgb=r.render().copy()
        captured=replace(obs,rgb=rgb,camera_sim_time=obs.sim_time,
                         camera_own_qpos=obs.own_qpos,camera_odom_xyyaw=obs.odom_xyyaw)
        with self.camera_lock:
            self.frame_seq+=1;self.frames[other]=(self.frame_seq,captured,time.monotonic(),epoch)

    def step_once(self):
        g=self.state.gate
        with self.lock:
            try:self._render_display_tick()
            except Exception as exc:
                self.camera_error=f'{type(exc).__name__}: {exc}';g.neutral('camera_error')
            if self.sim.time+1e-9>=self.next_nav_time:
                self._control_tick();self.next_nav_time=self.sim.time+.1
            with g.lock:
                value=g.sample();rid=g.robot_id;token=self._token()
                allowed=self._eligible(rid,g.reason)
                move=value.movement_requested()
                spin=g.active_mode.spin_enabled
            observation=self.sim.observe(rid,False,False)
            # Potentially slow real inference/rendering, deliberately outside
            # the input lock so HTTP focus/release packets remain responsive.
            try:
                if rid != 'red_sentry':
                    # Role admission is enforced here too, not just inside the
                    # source adapter. No unsupported robot can inherit source
                    # authority, even if an adapter incorrectly returns a pose.
                    self.source.disengage(observation,'unsupported_robot')
                    candidate=None
                else:
                    candidate=self.source.act_operator(observation,value.aim_request,identity=token,
                        allowed=allowed,move_requested=move,spin_requested=spin)
                if candidate is not None and not np.isfinite([candidate.gimbal_yaw,candidate.gimbal_pitch]).all():
                    raise ValueError('Nonfinite source gimbal command')
            except Exception as exc:
                self.source_error=f'{type(exc).__name__}: {exc}'
                self.source.error=self.source_error
                self.source.disengage(observation,'source_error')
                g.neutral('source_error');candidate=None
            with g.lock:
                g.sample()
                unchanged=self._token()==token
                valid=unchanged and self._eligible(rid,g.reason)
                stale=not unchanged or (allowed and not valid)
            if stale:
                self.source_results_discarded+=int(candidate is not None)
                self.source.disengage(observation,'input_changed_during_source')
                candidate=None
            with g.lock:
                g.sample();current_rid=g.robot_id
                # Final atomic recheck immediately before applying controls.
                valid=valid and self._token()==token and self._eligible(current_rid,g.reason)
                active=valid and not move and not spin and candidate is not None
                if self.source_was_active and not active:
                    q=self.sim.data.qpos[self.sim.qindices[current_rid]]
                    self.yaw_target,self.pitch_target=float(q[3]),float(q[4])
                manual_token=self._token()
                manual_before_active=self._eligible(current_rid,g.reason)
                self._discard_mouse_angle=active
                command=super()._operator_command(current_rid)
                # Manual construction samples the lease too; never overwrite
                # its freshly neutralized command with an older source result.
                g.sample()
                manual_generation_same=self._token()==manual_token
                manual_now_active=self._eligible(g.robot_id,g.reason)
                manual_safe=manual_generation_same and manual_now_active
                # Preserve the base runtime's latched hold on already-inactive
                # ticks. Re-anchoring every tick would follow gravity downward.
                manual_became_invalid=not manual_generation_same or (manual_before_active and not manual_now_active)
                if manual_became_invalid:
                    self._mode_feedback(g.robot_id,allowed=False,yaw_torque=0.,target_rate=0.,saturated=False)
                    if current_rid!=g.robot_id:self.commands[current_rid]=Command()
                    current_rid=g.robot_id
                    q=self.sim.data.qpos[self.sim.qindices[current_rid]]
                    if np.isfinite(q).all():
                        self.yaw_target,self.pitch_target=float(q[3]),float(q[4])
                        command=Command(gimbal_yaw=self.yaw_target,gimbal_pitch=self.pitch_target)
                    else:command=Command()
                valid=valid and self._token()==token and self._eligible(current_rid,g.reason)
                active=valid and manual_safe and not move and not spin and candidate is not None
                if active:
                    self.yaw_target=float(np.clip(candidate.gimbal_yaw,-3.14,3.14))
                    self.pitch_target=float(np.clip(candidate.gimbal_pitch,-.4,.5))
                    command=replace(command,gimbal_yaw=self.yaw_target,gimbal_pitch=self.pitch_target)
                    # Keep command.fire from the current manual request only.
                elif current_rid=='red_sentry':
                    own=self.sim.observe(current_rid,False,False)
                    if np.isfinite([*own.own_qpos,*own.own_qvel]).all():
                        # Same verified own-model feedforward already used by
                        # RMCSStopAim. No gain/model/fire/target tuning here.
                        command,self.manual_gravity_audit=self.manual_gravity.apply(command,own)
                self.source_was_active=active
                if not stale and self._token()==token:
                    self.autoaim_status=dict(self.source.feedback)
                else:
                    self.autoaim_status.update(available=current_rid=='red_sentry',active=False,
                        authority='manual',algorithm=IDENTITY,reason='input_changed_during_source',
                        source_frame_seq=None,source_sim_time=None,selected=False,in_fov=None,fov_applied=False)
                if not active and self.autoaim_status.get('active'):
                    # Source feedback describes its proposal; only this final
                    # safety gate knows whether the proposal was actuated.
                    self.autoaim_status.update(active=False,authority='manual',selected=False,
                        in_fov=None,fov_applied=False,
                        reason=g.reason if g.reason!='active' else 'source_result_not_applied')
                if self.source.error is not None:
                    self.autoaim_status.update(available=False,active=False,reason='source_error',authority='manual',error=self.source.error)
                elif current_rid != 'red_sentry':
                    self.autoaim_status.update(available=False,active=False,reason='unsupported_robot',
                        authority='manual',selected=False,in_fov=None,fov_applied=False,
                        source_frame_seq=None,source_sim_time=None,fire_authority='manual_only')
                    self.manual_gravity_audit=None
                g.source_autoaim_ready=self.source.error is None
                self.autoaim_status['input_revision']=g.safety_revision
                self.commands[current_rid]=command
                self.sim.step(self.commands)
            self.steps+=1
            if self.sim.time+1e-9>=self.next_publish_time or time.monotonic()>=self.next_publish_wall:
                self._publish();self.next_publish_time=self.sim.time+.05;self.next_publish_wall=time.monotonic()+.05
            self.last_step_wall=time.monotonic()

    def _publish(self):
        with self.state.gate.lock:
            self._publish_source_locked()

    def _publish_source_locked(self):
        super()._publish()
        if self.source is None:return
        with self.state.lock:
            if self.state.telemetry is None:return
            telemetry=dict(self.state.telemetry)
            camera=telemetry.get('camera',{})
            if camera.get('epoch')!=telemetry.get('epoch') or camera.get('robot_id')!=telemetry.get('robot_id'):
                camera.update(available=False,reason='camera_identity_not_ready')
            telemetry['operator_gimbal']=dict(authority='source_autoaim' if self.source_was_active else 'manual',
                manual_gravity_compensation=telemetry.get('robot_id')=='red_sentry',
                gravity_audit=self.manual_gravity_audit if not self.source_was_active else None,
                source_compensation='existing_source_wrapper_only; never applied twice')
            telemetry['source_runtime']=dict(identity=IDENTITY,armor_optical_profile=self.armor_optical_profile,physics_hz=2000,capture_hz=80,
                detector_hz=36,control_hz=100,display_fps=self.camera_fps,
                source_calls=self.source.source_calls,captured_frames=self.source.captured_frames,
                delivered_frames=self.source.delivered_frames,discarded_control_results=self.source_results_discarded,
                auto_fire=False,stationary_only=True,supported_robots=['red_sentry'],error=self.source.error)
            telemetry['limitations']=list(telemetry['limitations'])+[
                'source_autoaim_stationary_red_sentry_only','source_calibration_resolution_assumed',
                'source_inference_slows_simulation_wall_time','manual_fire_only']
            self.state.telemetry=telemetry

    def close(self):
        self.stop_event.set();self.state.gate.disable()
        if self.source is not None:self.source.close();self.source=None
        if self.display_renderer is not None:self.display_renderer.close();self.display_renderer=None
        self.sim.close()
