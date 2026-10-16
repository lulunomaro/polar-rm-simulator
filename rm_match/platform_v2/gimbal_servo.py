"""Explicit own-model servo option; never target estimation or authority."""
from dataclasses import replace
import math

MODES=('position','position_gravity_v1')


def servo_mode(value):
    if type(value) is not str or value not in MODES:
        raise ValueError('gimbal servo must be position or position_gravity_v1')
    return value


def yaw_gain(value):
    if type(value) not in (int,float) or not 1.<=value<=4. or not math.isfinite(value):
        raise ValueError('gimbal yaw gain must be finite within 1..4')
    return float(value)


class GravityPositionServo:
    def __init__(self,model,robot_ids,*,yaw_position_gain=1.):
        self.yaw_position_gain=yaw_gain(yaw_position_gain)
        import mujoco
        from ..integrations.own_gravity import OwnGravityCompensator,close_vector
        self.controllers={}
        for rid in robot_ids:
            controller=OwnGravityCompensator(model,rid)
            # The scalar gravity formula requires planar ancestors: translations
            # in world XY and hinges about world Z, with no fixed frame tilt.
            body=int(model.body_parentid[model.body(rid+'__pitch').id])
            while body:
                if not close_vector(model.body_quat[body],[1.,0.,0.,0.]):
                    raise ValueError('Gravity servo requires verified planar own ancestors')
                for j in range(int(model.body_jntadr[body]),int(model.body_jntadr[body]+model.body_jntnum[body])):
                    axis=model.jnt_axis[j];kind=int(model.jnt_type[j])
                    if kind==int(mujoco.mjtJoint.mjJNT_HINGE):
                        valid=close_vector(axis,[0.,0.,1.]) or close_vector(axis,[0.,0.,-1.])
                    else:
                        valid=kind==int(mujoco.mjtJoint.mjJNT_SLIDE) and abs(float(axis[2]))<1e-12
                    if not valid:raise ValueError('Gravity servo requires verified planar own ancestor joints')
                body=int(model.body_parentid[body])
            self.controllers[rid]=controller
        self.last={}
        self.provenance={rid:c.provenance for rid,c in self.controllers.items()}

    def apply(self,rid,command,own_pitch,phase,*,own_yaw=None,yaw_feedback_enabled=True):
        c=self.controllers[rid]
        if not math.isfinite(command.gimbal_yaw) or not math.isfinite(command.gimbal_pitch):
            raise ValueError('Gravity servo requires finite own references')
        torque=c.torque(float(own_pitch));offset=torque/c.kp
        pitch=min(c.pitch_range[1],max(c.pitch_range[0],command.gimbal_pitch+offset))
        yaw_request=command.gimbal_yaw
        if type(yaw_feedback_enabled) is not bool:raise ValueError('Explicit yaw feedback state required')
        if self.yaw_position_gain!=1. and yaw_feedback_enabled:
            if type(own_yaw) not in (int,float) or not math.isfinite(own_yaw):
                raise ValueError('Yaw feedback requires finite measured own yaw')
            # Outer position feedback around the original bounded actuator.
            # This is neither target prediction nor a retained expired reference.
            yaw_request+=(self.yaw_position_gain-1.)*(command.gimbal_yaw-own_yaw)
        yaw=min(c.yaw_range[1],max(c.yaw_range[0],yaw_request))
        self.last[rid]=dict(phase=phase,own_pitch_rad=float(own_pitch),raw_yaw_rad=command.gimbal_yaw,
            raw_pitch_rad=command.gimbal_pitch,gravity_torque_nm=torque,ctrl_offset_rad=offset,
            yaw_position_gain=self.yaw_position_gain,yaw_feedback_enabled=yaw_feedback_enabled,yaw_feedback_own_rad=own_yaw,
            ctrl_pitch_rad=pitch,ctrl_yaw_rad=yaw,clamped=pitch!=command.gimbal_pitch+offset or yaw!=yaw_request)
        return replace(command,gimbal_yaw=yaw,gimbal_pitch=pitch)
