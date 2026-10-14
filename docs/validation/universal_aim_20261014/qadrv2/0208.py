"""Human operator adapter over the existing shared-world match and referee.

The model is immutable. Physics owns the live MjData; rendering uses a copied
MjData on its own thread and never holds the physics lock during rendering.
"""
from __future__ import annotations

from dataclasses import asdict, replace
import io
import math
import threading
import time

import mujoco
import numpy as np
from PIL import Image

from ..contracts import Command
from ..match_engine import MatchSimulation
from ..match_controllers import MatchNavigationPolicy
from ..match_pixel_aim import MatchPixelAim
from .protocol import SCHEMA
from .autoaim import AutoAimAuthority, AutoAimRequest


class OperatorRuntime:
    def __init__(self, state, *, render=True, camera_fps=2., width=320, height=240):
        if not 0 < camera_fps <= 15:
            raise ValueError('camera_fps must be > 0 and <= 15')
        if not 64 <= width <= 1280 or not 48 <= height <= 720:
            raise ValueError('Camera size exceeds bounded renderer limits')
        self.state=state
        self.sim=MatchSimulation(render=False)
        self._configure_selection()
        self.lock=threading.RLock()
        self.camera_lock=threading.Lock()
        self.stop_event=threading.Event()
        self.render_enabled=render
        self.camera_fps=camera_fps
        self.width,self.height=width,height
        self.camera_thread=None
        self.camera_error=None
        self.frames={}
        self.frame_seq=0
        self.last_operator_frame=None
        self.ai_frames_seen={}
        self.nav={r:MatchNavigationPolicy() for r in self.sim.robot_ids}
        self.aim={r:MatchPixelAim() for r in self.sim.robot_ids}
        self.ai_commands={r:Command() for r in self.sim.robot_ids}
        self.commands={r:Command() for r in self.sim.robot_ids}
        self.next_nav_time=0.
        self.next_publish_time=0.
        self.next_publish_wall=0.
        self.yaw_target=self.pitch_target=None
        self.last_identity=None
        self.operator_was_active=False
        self.wall_start=time.monotonic()
        self.last_step_wall=self.wall_start
        self.steps=0
        self.operator_modes={}
        self.autoaim_authority=AutoAimAuthority()
        self.autoaim_status=self.autoaim_authority.evaluate(AutoAimRequest(),allowed=False,reason='no_control')
        self._mode_feedback(self.state.gate.robot_id,allowed=False,yaw_torque=0.,target_rate=0.,saturated=False)
        self._publish()

    def _configure_selection(self):
        """Advertise only the roles backed by this actual loaded SIM model."""
        for rid in self.sim.robot_ids:
            robot = self.sim.judge.robots.get(rid)
            if (robot is None or rid != f'{robot.team}_{robot.role}'
                or rid not in self.sim.qindices or rid not in self.sim.vindices
                or rid not in self.sim.aindices or rid not in self.sim.body_ids
                or mujoco.mj_name2id(self.sim.model,mujoco.mjtObj.mjOBJ_CAMERA,rid+'__aim') < 0):
                raise ValueError('Invalid simulation robot binding: '+rid)
        self.state.gate.configure_selection(self.sim.robot_ids)

    def start_camera(self):
        if self.render_enabled and self.camera_thread is None:
            self.camera_thread=threading.Thread(target=self._camera_loop,name='operator-camera',daemon=True)
            self.camera_thread.start()

    def _snapshot_for_camera(self, copied_data, rid):
        with self.lock:
            mujoco.mj_copyData(copied_data,self.sim.model,self.sim.data)
            observation=self.sim.observe(rid,include_rgb=False,include_ranges=False)
            # These are rendered physical spheres, not auxiliary trajectories.
            spheres=[(p.radius,p.position.copy()) for p in self.sim.projectiles]
            epoch=self.state.gate.epoch
        return observation,spheres,epoch

    def _camera_loop(self):
        renderer=None
        try:
            renderer=mujoco.Renderer(self.sim.model,self.height,self.width)
            data=mujoco.MjData(self.sim.model)
            ai_index=0
            while not self.stop_event.is_set():
                started=time.monotonic()
                selected=self.state.gate.robot_id
                others=[r for r in self.sim.robot_ids if r != selected]
                # Keep the selected operator's view first, then one AI camera.
                # The five unchanged pixel policies are camera-rate limited;
                # this demonstrator does not claim the frozen match timing.
                targets=[selected,others[ai_index % len(others)]]
                ai_index+=1
                for rid in targets:
                    if self.stop_event.is_set():break
                    observation,spheres,epoch=self._snapshot_for_camera(data,rid)
                    renderer.update_scene(data,camera=rid+'__aim')
                    for radius,position in spheres:
                        scene=renderer.scene
                        if scene.ngeom >= scene.maxgeom:break
                        mujoco.mjv_initGeom(scene.geoms[scene.ngeom],mujoco.mjtGeom.mjGEOM_SPHERE,
                            np.array([radius]*3),position,np.eye(3).ravel(),np.array([1,.8,.1,1],dtype=np.float32))
                        scene.ngeom+=1
                    rgb=renderer.render().copy()
                    captured=replace(observation,rgb=rgb,camera_sim_time=observation.sim_time,
                                     camera_own_qpos=observation.own_qpos,camera_odom_xyyaw=observation.odom_xyyaw)
                    with self.camera_lock:
                        self.frame_seq+=1
                        self.frames[rid]=(self.frame_seq,captured,time.monotonic(),epoch)
                    if rid == selected:
                        buffer=io.BytesIO();Image.fromarray(rgb).save(buffer,format='JPEG',quality=85)
                        meta=dict(epoch=epoch,robot_id=rid,frame_seq=self.frame_seq,
                                  sim_time=observation.sim_time,width=self.width,height=self.height)
                        # Discard an old camera result if the operator identity changed.
                        with self.state.gate.lock:
                            if epoch == self.state.gate.epoch and rid == self.state.gate.robot_id:
                                with self.state.lock:
                                    self.state.frame=buffer.getvalue();self.state.frame_meta=meta
                                self.last_operator_frame=meta
                self.stop_event.wait(max(0.,1/self.camera_fps-(time.monotonic()-started)))
        except Exception as exc:
            self.camera_error=f'{type(exc).__name__}: {exc}'
            self.state.gate.neutral('camera_error')
        finally:
            if renderer is not None:renderer.close()

    def _operator_command(self, rid):
        gate=self.state.gate
        value=gate.sample()
        input_token=(gate.session_id,gate.epoch,gate.robot_id,gate.safety_revision)
        q=self.sim.data.qpos[self.sim.qindices[rid]]
        v=self.sim.data.qvel[self.sim.vindices[rid]]
        identity=(gate.session_id,gate.epoch,rid)
        if not np.isfinite(q).all() or not np.isfinite(v).all():
            gate.neutral('invalid_physics_state')
            if self.last_identity is not None and self.last_identity[2] != rid:
                self.commands[self.last_identity[2]] = Command()
            self.last_identity = None
            self.yaw_target = self.pitch_target = 0.
            self.operator_was_active = False
            self.autoaim_status = self.autoaim_authority.evaluate(
                AutoAimRequest(), allowed=False, reason='invalid_physics_state')
            self._mode_feedback(rid, allowed=False, yaw_torque=0., target_rate=0., saturated=False)
            return Command()
        if identity != self.last_identity:
            if self.last_identity is not None:
                previous_rid=self.last_identity[2]
                previous_q=self.sim.data.qpos[self.sim.qindices[previous_rid]]
                # A changed selection must not leave the previous robot's last
                # manual trigger/drive held until its next navigation tick.
                self.commands[previous_rid]=Command(
                    gimbal_yaw=float(previous_q[3]) if np.isfinite(previous_q[3]) else 0.,
                    gimbal_pitch=float(previous_q[4]) if np.isfinite(previous_q[4]) else 0.)
                self.ai_commands[previous_rid] = self.commands[previous_rid]
                self.ai_frames_seen.pop(previous_rid, None)
            self.ai_commands[rid] = Command(gimbal_yaw=float(q[3]),gimbal_pitch=float(q[4]))
            self.ai_frames_seen.pop(rid, None)
            if (self.last_operator_frame is not None and
                (self.last_operator_frame.get('epoch'),self.last_operator_frame.get('robot_id')) != (gate.epoch,rid)):
                self.last_operator_frame = None
            self.yaw_target,self.pitch_target=float(q[3]),float(q[4])
            self.operator_was_active=False
            self.last_identity=identity
        allowed=(gate.reason == 'active' and self.sim.judge.robots[rid].alive
                 and not self.sim.judge.terminal and not self.sim.paused
                 and self.sim.phase == 'running' and not self.sim.emergency_stop
                 and self.camera_error is None)
        self.autoaim_status=self.autoaim_authority.evaluate(value.aim_request,allowed=allowed,
                                                            reason=gate.reason,identity=identity)
        if not allowed:
            gate.consume_mouse_angle(discard=True)
            self._mode_feedback(rid,allowed=False,yaw_torque=0.,target_rate=0.,saturated=False)
            # Remove drive/trigger immediately; holding the measured gimbal pose
            # avoids an unsafe snap to zero. The physical chassis may coast.
            if self.operator_was_active:
                self.yaw_target,self.pitch_target=float(q[3]),float(q[4])
            self.operator_was_active=False
            return Command(gimbal_yaw=self.yaw_target,gimbal_pitch=self.pitch_target)
        self.operator_was_active=True
        dt=float(self.sim.model.opt.timestep)
        mouse_yaw,mouse_pitch=gate.consume_mouse_angle(discard=getattr(self,"_discard_mouse_angle",False))
        self.yaw_target=float(np.clip(self.yaw_target+value.yaw_rate_rps*dt+mouse_yaw,-3.14,3.14))
        self.pitch_target=float(np.clip(self.pitch_target+value.pitch_rate_rps*dt+mouse_pitch,-.4,.5))
        mode=gate.active_mode
        reference_yaw=float(q[2])
        if value.drive_axes is not None:
            if mode.chassis_follow == 'field': reference_yaw=0.
            elif mode.chassis_follow == 'gimbal': reference_yaw=math.remainder(float(q[2]),2*math.pi)+math.remainder(float(q[3]),2*math.pi)
            forward,left=value.drive_axes.forward_mps,value.drive_axes.left_mps
        else:
            forward,left=value.vx_mps,value.vy_mps
        # Compute from current physical own pose, never from client telemetry or
        # the commanded gimbal target. All yaws are radians, CCW from above.
        reference_yaw=math.atan2(math.sin(reference_yaw),math.cos(reference_yaw))
        c,s=math.cos(reference_yaw),math.sin(reference_yaw)
        vx=c*forward-s*left
        vy=s*forward+c*left
        # Existing provisional velocity-servo gains; never teleport the body.
        raw_fx=28*(vx-float(v[0]))+8*vx
        raw_fy=28*(vy-float(v[1]))+8*vy
        fx=float(np.clip(raw_fx,-60,60))
        fy=float(np.clip(raw_fy,-60,60))
        sign=-1. if mode.spin_direction == 'cw' else 1.
        target_rate=sign*math.radians(mode.spin_speed_dps) if mode.spin_enabled else 0.
        # This is a provisional yaw-rate servo through the existing actuator,
        # not a teleport, calibrated chassis-power model or firmware emulator.
        raw_torque=2.*target_rate+6.*(target_rate-float(v[2])) if gate.mode_request_explicit else 0.
        actuator=self.sim.aindices[rid][2]
        lo,hi=self.sim.model.actuator_ctrlrange[actuator]
        yaw_torque=float(np.clip(raw_torque,lo,hi))
        self._mode_feedback(rid,allowed=True,yaw_torque=yaw_torque,target_rate=target_rate,
                            saturated=abs(raw_torque-yaw_torque)>1e-9,
                            drive=dict(reference_yaw_rad=reference_yaw,
                                world_velocity_target_mps=[vx,vy],applied_world_force_n=[fx,fy],
                                saturated=abs(raw_fx-fx)>1e-9 or abs(raw_fy-fy)>1e-9))
        # Consumption samples wall expiry too. Never return stale drive/fire
        # from the earlier input snapshot after it has neutralized the lease.
        gate.sample()
        if gate.reason != 'active' or input_token != (gate.session_id,gate.epoch,gate.robot_id,gate.safety_revision):
            self.yaw_target,self.pitch_target=float(q[3]),float(q[4])
            self.operator_was_active=False
            self._mode_feedback(rid,allowed=False,yaw_torque=0.,target_rate=0.,saturated=False)
            self.autoaim_status=self.autoaim_authority.evaluate(AutoAimRequest(),allowed=False,reason=gate.reason)
            return Command(gimbal_yaw=self.yaw_target,gimbal_pitch=self.pitch_target)
        return Command(fx,fy,yaw_torque,self.yaw_target,self.pitch_target,value.fire)

    def _mode_feedback(self,rid,*,allowed,yaw_torque,target_rate,saturated,drive=None):
        gate=self.state.gate
        mode=gate.active_mode
        measured=float(self.sim.data.qvel[self.sim.vindices[rid][2]])
        if not math.isfinite(measured): measured=None
        reason=gate.reason
        if allowed:
            reason='torque_saturated' if saturated else ('spin_active' if mode.spin_enabled else 'spin_off')
        elif gate.reason == 'active':
            reason='robot_or_simulation_safety_gate'
        velocity=self.sim.data.qvel[self.sim.vindices[rid]][:2]
        measurement_valid=bool(np.isfinite(velocity).all())
        measured_velocity=[float(v) if math.isfinite(float(v)) else 0. for v in velocity]
        drive_feedback=dict(active=bool(allowed),mode=mode.chassis_follow if allowed else 'free',
            input_revision=gate.safety_revision,
            input_kind=('drive_axes' if gate.input.drive_axes is not None else 'legacy_chassis') if allowed else 'legacy_chassis',
            reference_yaw_rad=0.,world_velocity_target_mps=[0.,0.],
            measured_world_velocity_mps=measured_velocity,measurement_valid=measurement_valid,applied_world_force_n=[0.,0.],
            saturated=False,reason='active' if allowed else reason,
            coordinate_frame='world',units=dict(velocity='m/s',force='N',yaw='rad'),
            automatic_chassis_yaw_follow=False)
        if allowed and drive is not None: drive_feedback.update(drive)
        requested=asdict(gate.requested_mode)
        if not gate.mode_origin_explicit:requested.pop('spin_origin')
        self.operator_modes=dict(
            supported=dict(spin=True,chassis_follow=['free'],chassis_drive_modes=['free','gimbal','field'],chassis_drive_frame_version=1,power_guard=False,
                           buffer_protect=False,auto_spin_on_hit=True,world_stabilized_gimbal=False),
            requested=requested,request_seq=gate.mode_request_seq,
            effective=dict(spin_enabled=bool(allowed and mode.spin_enabled),
                direction_resolved=('cw' if mode.spin_direction == 'cw' else 'ccw') if allowed and mode.spin_enabled else None,
                spin_speed_dps=mode.spin_speed_dps if allowed and mode.spin_enabled else 0.,
                target_yaw_rate_rps=target_rate if allowed else 0.,chassis_follow=mode.chassis_follow if allowed else 'free',
                spin_origin=mode.spin_origin if allowed and mode.spin_enabled else None),
            effective_seq=gate.last_seq if allowed else None,reason=reason,drive=drive_feedback,
            measured=dict(chassis_yaw_rate_rps=measured,yaw_torque=yaw_torque),
            saturated=bool(saturated),coordinate_frame='chassis_body',
            gimbal_yaw_frame='relative_to_chassis',simulation_only=True)

    def _control_tick(self):
        selected=self.state.gate.robot_id
        with self.camera_lock:frames=dict(self.frames)
        for rid in self.sim.robot_ids:
            obs=self.sim.observe(rid,include_rgb=False)
            decision=self.nav[rid].decide(obs)
            # Preserve the existing scenario's automatic virtual ammo purchase
            # in the supply zone, including for the human-controlled infantry.
            if decision.purchase_bundles:
                self.sim.judge.purchase_ammo(rid,bundles=decision.purchase_bundles,episode=self.sim.episode)
            if rid == selected:continue
            frame=frames.get(rid)
            allowed=obs.match_phase == 'running' and not obs.emergency_stop and obs.own_hp > 0
            ac=self.ai_commands[rid]
            if frame is not None:
                seq,captured,wall,epoch=frame
                if seq != self.ai_frames_seen.get(rid) and epoch == self.state.gate.epoch:
                    ac=self.aim[rid].act(captured)
                    self.ai_frames_seen[rid]=seq
                    self.ai_commands[rid]=ac
                if time.monotonic()-wall > 3. or self.sim.time-captured.sim_time > 3.:
                    ac=Command(gimbal_yaw=obs.own_qpos[3],gimbal_pitch=obs.own_qpos[4])
            else:
                ac=Command(gimbal_yaw=obs.own_qpos[3],gimbal_pitch=obs.own_qpos[4])
            if not allowed:ac=Command()
            self.commands[rid]=replace(ac,force_x=decision.command.force_x,
                                      force_y=decision.command.force_y,yaw_torque=decision.command.yaw_torque)

    def step_once(self):
        with self.lock:
            if self.sim.time+1e-9 >= self.next_nav_time:
                self._control_tick();self.next_nav_time=self.sim.time+.1
            with self.state.gate.lock:
                rid=self.state.gate.robot_id
                self.commands[rid]=self._operator_command(rid)
                self.sim.step(self.commands)
            self.steps+=1
            if self.sim.time+1e-9 >= self.next_publish_time or time.monotonic() >= self.next_publish_wall:
                self._publish();self.next_publish_time=self.sim.time+.05
                self.next_publish_wall=time.monotonic()+.05
            self.last_step_wall=time.monotonic()

    def _robot(self,rid):
        r=self.sim.judge.robots[rid]
        q=self.sim.data.qpos[self.sim.qindices[rid]]
        xyz=self.sim.data.xpos[self.sim.body_ids[rid]]
        return dict(robot_id=rid,team=r.team,role=r.role,hp=float(r.hp),max_hp=float(r.max_hp),
                    ammo=int(r.ammo),heat=float(r.heat),heat_max=float(r.heat_max),
                    xy=[float(xyz[0]),float(xyz[1])],chassis_yaw=float(q[2]),
                    gimbal_yaw=float(q[3]),world_gimbal_yaw=float(q[2]+q[3]),
                    chassis_yaw_rate_rps=float(self.sim.data.qvel[self.sim.vindices[rid][2]]),
                    pitch=float(q[4]),alive=bool(r.alive))

    def _publish(self):
        with self.state.gate.lock:
            self._publish_locked()

    def _publish_locked(self):
        gate=self.state.gate
        rid=gate.robot_id
        if self.last_identity != (gate.session_id, gate.epoch, rid):
            return  # No current-identity physical/control sample yet.
        elapsed=max(time.monotonic()-self.wall_start,1e-9)
        phase='finished' if self.sim.judge.terminal else self.sim.phase
        camera=dict(self.last_operator_frame or {})
        camera_ready=(camera.get('epoch') == gate.epoch and camera.get('robot_id') == rid)
        camera.update(available=camera_ready,first_person=True,
                      robot_id=rid,overlays=False,error=self.camera_error)
        if not camera_ready:
            camera=dict(available=False,first_person=True,robot_id=rid,epoch=gate.epoch,
                        overlays=False,error=self.camera_error,reason='camera_identity_not_ready')
        events=[event for event in self.sim.judge.events[-200:] if event.get('type')!='presence'][-20:]
        mode_feedback=dict(self.operator_modes)
        mode_feedback['drive']=dict(mode_feedback.get('drive',{}),
            measured_world_velocity_mps=[float(v) for v in self.sim.data.qvel[self.sim.vindices[rid]][:2]],
            applied_world_force_n=[float(v) for v in self.sim.data.ctrl[self.sim.aindices[rid]][:2]])
        mode_feedback['measured']=dict(
            chassis_yaw_rate_rps=float(self.sim.data.qvel[self.sim.vindices[rid][2]]),
            yaw_torque=float(self.sim.data.ctrl[self.sim.aindices[rid][2]]))
        telemetry=dict(schema=SCHEMA,session_id=gate.session_id,epoch=gate.epoch,robot_id=rid,
            sim_time=self.sim.time,phase=phase,countdown=None,
            remaining_seconds=max(0.,300-self.sim.time),own=self._robot(rid),
            own_damage=dict(schema='polar.sim.projectile_damage.v1',
                source='simulator_judge_actual_projectile_damage',
                session_id=gate.session_id,epoch=gate.epoch,robot_id=rid,
                episode=self.sim.judge.episode,sim_time=self.sim.time,
                **self.sim.judge.projectile_damage[rid]),
            robots=[self._robot(r) for r in self.sim.robot_ids],map_source='simulator_truth_display_only',
            vp=dict(self.sim.judge.vp),control_owner=self.sim.judge.control_owner,
            terminal_reason=self.sim.judge.terminal_reason,events=events,camera=camera,
            simulation_only=True,hardware_transport=False,
            applied_operator_command=asdict(self.commands[rid]),
            performance=dict(wall_seconds=elapsed,physics_seconds=self.sim.time,
                             real_time_factor=self.sim.time/elapsed,camera_target_fps=self.camera_fps),
            limitations=['provisional_robot_dynamics','verified_subset_referee',
                         'five_ai_cameras_rate_limited','no_real_time_fps_guarantee'],
            automatic_virtual_supply_purchase=True,operator_modes=mode_feedback,
            autoaim=dict(self.autoaim_status))
        self.state.publish(telemetry)

    def run(self, *, max_seconds=300., max_wall_seconds=None):
        self.start_camera()
        deadline=time.monotonic()
        while not self.stop_event.is_set():
            if self.sim.time >= max_seconds or self.sim.judge.terminal:break
            if max_wall_seconds is not None and time.monotonic()-self.wall_start >= max_wall_seconds:break
            self.step_once()
            # Do not catch up an unbounded backlog after expensive CPU work.
            deadline=max(deadline+float(self.sim.model.opt.timestep),time.monotonic())
            self.stop_event.wait(max(0.,deadline-time.monotonic()))
        self.state.gate.disable('finished' if self.sim.judge.terminal else 'stopped')
        with self.lock:
            rid=self.state.gate.robot_id
            self.commands[rid]=self._operator_command(rid)
            self.sim.commands[rid]=self.commands[rid]
            self.sim.data.ctrl[self.sim.aindices[rid]]=0
            self._publish()
        self.state.stop('finished' if self.sim.judge.terminal else 'stopped')

    def close(self):
        self.stop_event.set();self.state.gate.disable()
        if self.camera_thread is not None:self.camera_thread.join(timeout=15.)
        # MatchSimulation owns no GL object. Avoid freeing MjData/model while a
        # renderer might still be finishing; the thread retains this runtime.
        self.sim.close()
