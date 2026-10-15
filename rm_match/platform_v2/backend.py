"""Trusted MuJoCo boundary; not passed to algorithm instances or HTTP clients."""
from __future__ import annotations
from dataclasses import asdict
import math
import threading
import time

class MuJoCoBackend:
    """Current no-GL qualification backend, registry taken from the loaded scene.

    The existing 3v3 core and judge remain unchanged. Supplying a different backend
    preserves the platform protocol; this does not qualify a new roster or ruleset.
    """
    def __init__(self,sim=None,*,camera=False,virtual_resupply="disabled",navigation_sensors=None,clock=time.perf_counter):
        from .resupply import VirtualResupply
        self._resupply=VirtualResupply(virtual_resupply)
        if sim is None:
            from ..match_engine import MatchSimulation
            if navigation_sensors is not None:
                from ..navigation_sensors import navigation_model_xml
                from ..match_model import make_match_xml
                if camera:
                    from .camera import camera_model_xml
                    xml=camera_model_xml()
                else:xml=make_match_xml()
                sim=MatchSimulation(render=False,model_xml=navigation_model_xml(xml,navigation_sensors))
            elif camera:
                from .camera import camera_model_xml
                sim=MatchSimulation(render=False,model_xml=camera_model_xml())
            else:sim=MatchSimulation(render=False)
        self._sim=sim
        self._navigation_sensors=None
        if navigation_sensors is not None:
            from ..navigation_sensors import NavigationSensors
            self._navigation_sensors=NavigationSensors(sim,navigation_sensors,clock=clock)
        self.robot_ids=tuple(sim.robot_ids)
        self.timestep=float(sim.model.opt.timestep)
        self._authority=None
        self.last_commands={}
        self._gimbal_hold={}
        self._gimbal_was_active={r:False for r in self.robot_ids}
        # Immutable model-derived cache. Never read model/data in HTTP threads.
        from .spin import capability
        import mujoco
        self._control_caps={}
        for rid in self.robot_ids:
            try:
                m=sim.model;a=int(sim.aindices[rid][2]);j=int(m.actuator_trnid[a,0])
                mapping=dict(joint_transmission=int(m.actuator_trntype[a])==int(mujoco.mjtTrn.mjTRN_JOINT),
                    hinge_joint=int(m.jnt_type[j])==int(mujoco.mjtJoint.mjJNT_HINGE),
                    axis_positive_z=list(map(float,m.jnt_axis[j]))==[0.,0.,1.],
                    own_qpos=int(m.jnt_qposadr[j])==int(sim.qindices[rid][2]),
                    own_dof=int(m.jnt_dofadr[j])==int(sim.vindices[rid][2]),
                    unit_gear=list(map(float,m.actuator_gear[a]))==[1.,0.,0.,0.,0.,0.],
                    fixed_unit_gain=int(m.actuator_gaintype[a])==int(mujoco.mjtGain.mjGAIN_FIXED) and float(m.actuator_gainprm[a,0])==1.,
                    no_bias=int(m.actuator_biastype[a])==int(mujoco.mjtBias.mjBIAS_NONE),
                    no_dynamics=int(m.actuator_dyntype[a])==int(mujoco.mjtDyn.mjDYN_NONE),
                    control_limited=bool(m.actuator_ctrllimited[a]),no_force_limit=not bool(m.actuator_forcelimited[a]),
                    ctrl_min=float(m.actuator_ctrlrange[a,0]),ctrl_max=float(m.actuator_ctrlrange[a,1]))
            except (KeyError,IndexError,ValueError,TypeError,OverflowError):mapping={}
            self._control_caps[rid]=capability(mapping)
        self.last_motion_feedback={}
        # Model indices/ranges do not change during one loaded simulation.
        self._pose_indices={r:tuple(sim.qindices[r])+tuple(sim.vindices[r][:3]) for r in self.robot_ids}
        self._yaw_ctrlrange={r:tuple(map(float,sim.model.actuator_ctrlrange[sim.aindices[r][2]])) for r in self.robot_ids}

    def declared_spin_capabilities(self):
        import copy
        return copy.deepcopy(self._control_caps)

    def _check(self):
        thread=threading.get_ident()
        if self._authority is None:self._authority=thread
        if thread!=self._authority:raise RuntimeError('Physics backend accessed outside its authority thread')

    @property
    def episode(self):
        self._check();return self._sim.episode

    @property
    def sim_time(self):
        self._check();return float(self._sim.time)

    def declared_sensor_support(self):
        support={r:["odometry","ranges"] for r in self.robot_ids}
        if self._navigation_sensors is not None:
            for r in self._navigation_sensors.config.robot_ids:support[r]+=['pointcloud','imu']
        return support

    def navigation_sensor_packet(self,rid):
        self._check()
        return None if self._navigation_sensors is None else self._navigation_sensors.packet(rid)

    def navigation_capture_valid(self,rid,episode,budget,sim_time):
        self._check()
        return bool(self._navigation_sensors and self._navigation_sensors.capture_valid(rid,episode,budget,sim_time))

    def prepare_navigation_sensors(self):
        """Authority-only sampling before the runtime acquires its control lock."""
        producer=getattr(self,'_navigation_sensors',None)
        if producer is None:return
        self._check();producer.capture()

    def sensor_sample(self,rid):
        self._check()
        # Only the pre-existing own-sensor API is accessed. Never enumerate
        # opponents or derive hidden target labels in the algorithm feed.
        return self._sim.observe(rid,include_rgb=False,include_ranges=True)

    def own_pose(self,rid):
        self._check();s=self._sim
        ix=self._pose_indices[rid];q=s.data.qpos;v=s.data.qvel
        return dict(yaw=float(q[ix[2]]),gimbal_yaw=float(q[ix[3]]),gimbal_pitch=float(q[ix[4]]),
                    vx=float(v[ix[5]]),vy=float(v[ix[6]]),wz=float(v[ix[7]]))

    def allowed(self,rid):
        self._check();s=self._sim
        return bool(s.phase=='running' and not s.paused and not s.emergency_stop
                    and not s.judge.terminal and s.judge.robots[rid].alive)

    def validate_target(self,rid,channel,value):
        self._check()
        if channel=='motion':return True  # Contract already enforces bounded velocity.
        if channel=='gimbal':
            s=self._sim
            for key,index in [('yaw_rad',3),('pitch_rad',4)]:
                low,high=s.model.actuator_ctrlrange[s.aindices[rid][index]]
                if not float(low)<=value[key]<=float(high):return False
        return True

    def neutralize(self):
        self._check()
        from ..contracts import Command
        s=self._sim;commands={}
        for rid in self.robot_ids:
            p=self.own_pose(rid)
            self._gimbal_hold[rid]=(p['gimbal_yaw'],p['gimbal_pitch'])
            self._gimbal_was_active[rid]=False
            c=Command(gimbal_yaw=p['gimbal_yaw'],gimbal_pitch=p['gimbal_pitch'])
            commands[rid]=c
            s.data.ctrl[s.aindices[rid]]=[0.,0.,0.,c.gimbal_yaw,c.gimbal_pitch]
        s.commands=commands;self.last_commands={r:asdict(c) for r,c in commands.items()}

    def step(self,targets):
        return self._step(targets)

    def guarded_step(self,targets,guard,clock=time.monotonic):
        return self._step(targets,guard=guard,clock=clock)

    def _step(self,targets,guard=None,clock=time.monotonic):
        self._check()
        # Direct backend callers still sample here. Runtime already sampled this
        # data.time outside its lock; capture() keeps the exact original sample.
        self.prepare_navigation_sensors()
        from ..contracts import Command
        import numpy as np
        s=self._sim;commands={}
        if not hasattr(self,'_pose_indices'):
            # Also support explicitly supplied minimal/synthetic backend fixtures.
            self._pose_indices={r:tuple(s.qindices[r])+tuple(s.vindices[r][:3]) for r in self.robot_ids}
            self._yaw_ctrlrange={r:tuple(map(float,s.model.actuator_ctrlrange[s.aindices[r][2]])) for r in self.robot_ids}
        self._resupply.apply(s,self.allowed)
        for rid in self.robot_ids:
            pose=self.own_pose(rid);t=targets[rid]
            active=t['gimbal'] is not None and self.allowed(rid)
            if rid not in self._gimbal_hold or (self._gimbal_was_active[rid] and not active):
                self._gimbal_hold[rid]=(pose['gimbal_yaw'],pose['gimbal_pitch'])
            self._gimbal_was_active[rid]=active
            hold_yaw,hold_pitch=self._gimbal_hold[rid]
            if not self.allowed(rid):
                commands[rid]=Command(gimbal_yaw=pose['gimbal_yaw'],gimbal_pitch=pose['gimbal_pitch']);continue
            m=t['motion'];g=t['gimbal']
            if m is None:fx=fy=torque=0.
            else:
                c,ss=math.cos(pose['yaw']),math.sin(pose['yaw'])
                vx=c*m['vx_mps']-ss*m['vy_mps'];vy=ss*m['vx_mps']+c*m['vy_mps']
                fx=float(np.clip(28*(vx-pose['vx'])+8*vx,-60,60))
                fy=float(np.clip(28*(vy-pose['vy'])+8*vy,-60,60))
                from .spin import requested_yaw
                yaw_target=requested_yaw(m)
                raw=2*yaw_target+6*(yaw_target-pose['wz'])
                low,high=self._yaw_ctrlrange[rid]
                torque=float(np.clip(raw,low,high))
            commands[rid]=Command(force_x=fx,force_y=fy,yaw_torque=torque,
                gimbal_yaw=hold_yaw if g is None else g['yaw_rad'],
                gimbal_pitch=hold_pitch if g is None else g['pitch_rad'],fire=bool(t['fire']))
        # Guard is invoked by the engine immediately before each real actuator
        # write, not before potentially slower preparation/zone bookkeeping.
        def final(rid,command,phase,sampled_wall=None):
            from dataclasses import replace
            # The runtime guard may replace or mutate targets[rid]. Capture
            # revocation facts before calling it, and apply returned angles to
            # the real Command rather than merely updating runtime receipts.
            had_motion=targets[rid]['motion'] is not None
            had_gimbal=targets[rid]['gimbal'] is not None
            current=guard(rid,command,phase,sampled_wall)
            changes={}
            if had_motion and current['motion'] is None:
                changes.update(force_x=0.,force_y=0.,yaw_torque=0.)
            if current['gimbal'] is not None:
                changes.update(gimbal_yaw=current['gimbal']['yaw_rad'],gimbal_pitch=current['gimbal']['pitch_rad'])
            elif had_gimbal:
                pose=self.own_pose(rid)
                self._gimbal_hold[rid]=(pose['gimbal_yaw'],pose['gimbal_pitch'])
                self._gimbal_was_active[rid]=False
                changes.update(gimbal_yaw=pose['gimbal_yaw'],gimbal_pitch=pose['gimbal_pitch'])
            if not current['fire']:changes['fire']=False
            return replace(command,**changes) if changes else command
        integration_sim_time=self.sim_time
        s.step(commands,command_guard=final if guard is not None else None,integration_clock=clock if guard is not None else None)
        self.last_integration_timing=getattr(s,"last_integration_timing",None)
        self.last_commands={r:asdict(c) for r,c in s.commands.items()}
        from .spin import requested_yaw
        feedback={}
        for rid in self.robot_ids:
            m=targets[rid]['motion'];a=s.aindices[rid][2];pose=self.own_pose(rid)
            measured=float(pose['wz']);torque=float(s.data.actuator_force[a])
            valid=math.isfinite(measured) and math.isfinite(torque)
            is_spin=bool(m is not None and m.get('mode')=='spin_v1')
            target=requested_yaw(m) if m is not None else 0.
            lo,hi=self._yaw_ctrlrange[rid]
            feedback[rid]=dict(integration_sim_time=integration_sim_time,timestep_seconds=self.timestep,sample_sim_time=self.sim_time,measurement_valid=valid,
                measured_yaw_rate_rps=measured if valid else None,applied_yaw_torque_nm=torque if valid else None,
                target_yaw_rate_rps=target,spin_requested=is_spin,
                direction_resolved=('cw' if target<0 else 'ccw') if is_spin else None,
                saturated=abs(float(s.commands[rid].yaw_torque)-lo)<1e-9 or abs(float(s.commands[rid].yaw_torque)-hi)<1e-9)
        self.last_motion_feedback=feedback

    def display_snapshot(self):
        self._check();s=self._sim
        robots=[]
        for rid in self.robot_ids:
            robot=s.judge.robots[rid];p=self.own_pose(rid)
            xy=s.data.xpos[s.body_ids[rid]][:2]
            robots.append(dict(robot_id=rid,team=s.teams[rid],role=s.roles[rid],
                xy=[float(v) for v in xy],hp=float(robot.hp),max_hp=float(robot.max_hp),
                ammo=int(robot.ammo),heat=float(robot.heat),heat_max=float(robot.heat_max),
                alive=bool(robot.alive),**p))
        return dict(sim_time=float(s.time),sample_sim_time=float(s.time),episode=s.episode,
            display_schema='polar.sim.display.v2',remaining_seconds=max(0.,s.judge.duration_s-s.judge.sim_time),
            judge_sim_time=float(s.judge.sim_time),duration_seconds=float(s.judge.duration_s),
            victory_points=dict(s.judge.vp),attack_damage=dict(s.judge.attack_damage),
            team_coins=dict(s.judge.coins),virtual_resupply=self._resupply.status(),
            winner=s.judge.winner,terminal_reason=s.judge.terminal_reason,
            phase='finished' if s.judge.terminal else ('paused' if s.paused else s.phase),
            robots=robots,applied_commands=self.last_commands,
            source='simulator_truth_display_only',algorithm_input=False,
            camera={'available':False,'reason':'no_gl_stage'},
            ruleset='existing_verified_subset_3v3_core',scenario='existing_3v3_scene',
            limitations=['provisional_robot_dynamics','verified_subset_referee','no_gl_camera_unavailable',
                         'loopback_multiclient_only_not_cross_machine_LAN'])

    def close(self):
        self._check();self._sim.close()
