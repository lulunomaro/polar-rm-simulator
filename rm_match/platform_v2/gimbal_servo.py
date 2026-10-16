"""Explicit own-model servo option; never target estimation or authority."""
from dataclasses import replace
import math

MODES=('position','position_gravity_v1')


def servo_mode(value):
    if type(value) is not str or value not in MODES:
        raise ValueError('gimbal servo must be position or position_gravity_v1')
    return value


class GravityPositionServo:
    def __init__(self,model,robot_ids):
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

    def apply(self,rid,command,own_pitch,phase):
        c=self.controllers[rid]
        if not math.isfinite(command.gimbal_yaw) or not math.isfinite(command.gimbal_pitch):
            raise ValueError('Gravity servo requires finite own references')
        torque=c.torque(float(own_pitch));offset=torque/c.kp
        pitch=min(c.pitch_range[1],max(c.pitch_range[0],command.gimbal_pitch+offset))
        yaw=min(c.yaw_range[1],max(c.yaw_range[0],command.gimbal_yaw))
        self.last[rid]=dict(phase=phase,own_pitch_rad=float(own_pitch),raw_yaw_rad=command.gimbal_yaw,
            raw_pitch_rad=command.gimbal_pitch,gravity_torque_nm=torque,ctrl_offset_rad=offset,
            ctrl_pitch_rad=pitch,ctrl_yaw_rad=yaw,clamped=pitch!=command.gimbal_pitch+offset or yaw!=command.gimbal_yaw)
        return replace(command,gimbal_yaw=yaw,gimbal_pitch=pitch)
