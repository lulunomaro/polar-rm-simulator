"""Own-model-only gravity feedforward through existing bounded position controls.

For the verified pitch joint axis (0,-1,0), positive pitch raises the barrel.
The own barrel COM rotated about this axis is (cx*cos(q)-cz*sin(q), cy, ...).
Gravity therefore exerts generalized torque -m*g*(cx*cos(q)-cz*sin(q)).
Add its negative to the unchanged position actuator by increasing ctrl by tau/kp.
No Coriolis compensation, integral controller, enemy state or hit feedback is used.
"""
from dataclasses import asdict,replace
import math


def close_vector(values,expected,tolerance=1e-12):
    return len(values)==len(expected) and all(abs(float(a)-b)<=tolerance for a,b in zip(values,expected))


class OwnGravityCompensator:
    def __init__(self,model,own_id='red_sentry'):
        # Every robot-specific read is indexed by the explicit OWN body/joint/actuator.
        # The model object and indices are not retained after scalar extraction.
        joint=model.joint(own_id+'__gimbal_pitch').id
        body=model.body(own_id+'__pitch').id
        actuator=model.actuator(own_id+'__aim_pitch').id
        yaw_actuator=model.actuator(own_id+'__aim_yaw').id
        if int(model.jnt_bodyid[joint])!=body:
            raise ValueError('Own pitch joint/body linkage does not match verified contract')
        if not close_vector(model.jnt_axis[joint],[0.,-1.,0.]) or not close_vector(model.jnt_pos[joint],[0.,0.,0.]):
            raise ValueError('Only the verified own pitch axis/pivot is supported')
        if not close_vector(model.body_quat[body],[1.,0.,0.,0.]):
            raise ValueError('Own pitch body has an unverified fixed rotation')
        self.mass=float(model.body_mass[body])
        self.com=tuple(float(x) for x in model.body_ipos[body])
        if abs(float(model.body_subtreemass[body])-self.mass)>1e-12:
            raise ValueError('Additional own pitch descendants need an explicitly derived gravity model')
        gravity=tuple(float(x) for x in model.opt.gravity)
        if abs(gravity[0])+abs(gravity[1])>1e-12 or gravity[2]>=0:
            raise ValueError('Only verified vertical downward world gravity is supported')
        self.gravity=-gravity[2]
        self.kp=float(model.actuator_gainprm[actuator,0])
        self.kv=-float(model.actuator_biasprm[actuator,2])
        if self.kp<=0 or not close_vector(model.actuator_biasprm[actuator,:3],[0.,-self.kp,-self.kv]):
            raise ValueError('Own pitch actuator must retain its original position-control form')
        if not close_vector(model.actuator_gear[actuator],[1.,0.,0.,0.,0.,0.]):
            raise ValueError('Unexpected own actuator gear')
        if int(model.actuator_trnid[actuator,0])!=joint or not bool(model.actuator_ctrllimited[actuator]):
            raise ValueError('Own pitch actuator bounds/transmission are not verified')
        if not bool(model.actuator_ctrllimited[yaw_actuator]):
            raise ValueError('Own yaw actuator must retain bounded control')
        self.pitch_range=tuple(float(x) for x in model.actuator_ctrlrange[actuator])
        self.yaw_range=tuple(float(x) for x in model.actuator_ctrlrange[yaw_actuator])
        self.joint_pitch_range=tuple(float(x) for x in model.jnt_range[joint])
        self.joint_damping=float(model.dof_damping[int(model.jnt_dofadr[joint])])
        self.provenance=dict(own_body=own_id+'__pitch',own_pitch_joint=own_id+'__gimbal_pitch',
                             own_pitch_actuator=own_id+'__aim_pitch',own_yaw_actuator=own_id+'__aim_yaw',
                             own_mass_kg=self.mass,own_com_m=self.com,gravity_m_s2=gravity,
                             kp=self.kp,kv=self.kv,joint_damping=self.joint_damping,
                             pitch_ctrlrange=self.pitch_range,yaw_ctrlrange=self.yaw_range,
                             pitch_joint_range=self.joint_pitch_range,
                             formula='tau_g=m*g*(cx*cos(own_pitch)-cz*sin(own_pitch)); ctrl_pitch=clip(raw_ref+tau_g/kp,original bounds)',
                             prohibited_inputs_not_used=['enemy bodies or pose','whole-system qfrc_bias','projectiles or hits','camera target truth'],
                             unchanged='All physical model, gain, damping, joint and actuator range arrays are read-only')

    def torque(self,own_pitch):
        if not math.isfinite(own_pitch):
            raise ValueError('Own measured pitch must be finite')
        cx,_,cz=self.com
        return self.mass*self.gravity*(cx*math.cos(own_pitch)-cz*math.sin(own_pitch))

    def apply(self,raw_command,own_observation):
        own_pitch=float(own_observation.own_qpos[4])
        tau=self.torque(own_pitch)
        raw_pitch=float(raw_command.gimbal_pitch)
        raw_yaw=float(raw_command.gimbal_yaw)
        if not math.isfinite(raw_pitch) or not math.isfinite(raw_yaw):
            raise ValueError('Own reference must be finite')
        unclipped=raw_pitch+tau/self.kp
        ctrl_pitch=min(self.pitch_range[1],max(self.pitch_range[0],unclipped))
        ctrl_yaw=min(self.yaw_range[1],max(self.yaw_range[0],raw_yaw))
        command=replace(raw_command,gimbal_yaw=ctrl_yaw,gimbal_pitch=ctrl_pitch)
        audit=dict(measured_own_pitch_rad=own_pitch,raw_reference_yaw_rad=raw_yaw,raw_reference_pitch_rad=raw_pitch,
                   gravity_torque_nm=tau,gravity_ctrl_offset_rad=tau/self.kp,
                   compensated_unclipped_pitch_ctrl_rad=unclipped,actual_pitch_ctrl_rad=ctrl_pitch,
                   actual_yaw_ctrl_rad=ctrl_yaw,pitch_ctrl_clamped=unclipped!=ctrl_pitch,yaw_ctrl_clamped=raw_yaw!=ctrl_yaw,
                   raw_fire=bool(raw_command.fire),actual_fire=bool(command.fire),
                   fire_policy='Feedforward never grants fire; the source gate and no-tracking inhibition are unchanged')
        return command,audit
