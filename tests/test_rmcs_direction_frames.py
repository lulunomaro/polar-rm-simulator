"""Rotation/identity mechanics only; no native source or moving qualification."""
import copy
import math
from types import SimpleNamespace

import numpy as np
import pytest

from rm_match.integrations.rmcs_contract import command_from_direction


def observation(*,base=.0,yaw=.0,pitch=.0,time=1.,robot='red_infantry',episode=4):
    return SimpleNamespace(robot_id=robot,episode=episode,sim_time=time,
        own_qpos=(0.,0.,base,yaw,pitch),odom_xyyaw=(2.,-3.,base),wall_deadline=10.)


def axis_matrix(axis,angle):
    # Independent Rodrigues Cartesian rotation, rather than the helper's Euler
    # implementation. MuJoCo's pitch hinge axis is negative local Y.
    x,y,z=axis;c=math.cos(angle);s=math.sin(angle);v=1-c
    return np.array([[c+x*x*v,x*y*v-z*s,x*z*v+y*s],
                     [y*x*v+z*s,c+y*y*v,y*z*v-x*s],
                     [z*x*v-y*s,z*y*v+x*s,c+z*z*v]])


def oracle(direction,capture,current):
    cap_base=axis_matrix((0,0,1),capture.odom_xyyaw[2])
    cap_yaw=axis_matrix((0,0,1),capture.own_qpos[3])
    cap_pitch=axis_matrix((0,-1,0),capture.own_qpos[4])
    world=cap_base@cap_yaw@cap_pitch@np.asarray(direction)
    local=axis_matrix((0,0,1),current.odom_xyyaw[2]).T@world
    yaw=math.atan2(local[1],local[0]);reference=current.own_qpos[3]
    yaw=reference+math.atan2(math.sin(yaw-reference),math.cos(yaw-reference))
    return yaw,math.atan2(local[2],math.hypot(local[0],local[1])),world


@pytest.mark.parametrize('cap_angles,current_angles,direction',[
    ((.4,.3,.2),(1.1,-.4,-.1),(1.,0.,0.)),
    ((-.8,.6,-.25),(1.2,.4,.3),(.8,.1,.3)),
    ((3.,.5,.35),(-3.,2.9,-.2),(1.,-.3,.2)),
    ((-2.9,-.7,-.3),(2.8,-2.7,.2),(.6,.5,-.2)),
])
def test_capture_pitch_frame_uses_exposure_pose_then_current_base_cartesian_projection(cap_angles,current_angles,direction):
    capture=observation(base=cap_angles[0],yaw=cap_angles[1],pitch=cap_angles[2],time=.98)
    current=observation(base=current_angles[0],yaw=current_angles[1],pitch=current_angles[2])
    before=copy.deepcopy((capture.__dict__,current.__dict__))
    expected_yaw,expected_pitch,world=oracle(direction,capture,current)
    output=dict(should_control=True,should_shoot=False,direction=direction,direction_frame='pitch_link')
    actual=command_from_direction(output,current,capture_observation=capture)
    assert actual.gimbal_yaw==pytest.approx(expected_yaw)
    assert actual.gimbal_pitch==pytest.approx(expected_pitch) and not actual.fire
    world_command=command_from_direction({**output,'direction':world,'direction_frame':'world'},current)
    assert world_command.gimbal_yaw==pytest.approx(actual.gimbal_yaw)
    assert world_command.gimbal_pitch==pytest.approx(actual.gimbal_pitch)
    assert (capture.__dict__,current.__dict__)==before


def test_pitch_frame_requires_explicit_capture_instead_of_guessing_current_pose():
    with pytest.raises(ValueError,match='Explicit capture'):
        command_from_direction(dict(should_control=True,direction=[1.,0.,0.],direction_frame='pitch_link'),observation())


@pytest.mark.parametrize('field,value',[
    ('robot_id','blue_infantry'),('episode',5),('episode',True),
    ('sim_time',1.001),('sim_time',float('nan')),('sim_time',float('inf')),
    ('sim_time',None),('sim_time',True),('sim_time',-.01),
])
def test_capture_wrong_identity_future_or_invalid_time_is_rejected(field,value):
    capture=observation(time=.98);setattr(capture,field,value)
    with pytest.raises(ValueError):
        command_from_direction(dict(should_control=True,direction=[1.,0.,0.],direction_frame='pitch_link'),
            observation(),capture_observation=capture)


@pytest.mark.parametrize('field,value',[
    ('own_qpos',None),('own_qpos',(0.,0.,0.,0.)),('own_qpos',(0.,)*6),
    ('own_qpos',(0.,0.,0.,float('nan'),0.)),('own_qpos',(0.,0.,0.,0.,float('inf'))),
    ('own_qpos',('0','0','0','0','0')),('own_qpos',(True,)*5),
    ('odom_xyyaw',None),('odom_xyyaw',(0.,0.)),('odom_xyyaw',(0.,)*4),
    ('odom_xyyaw',(0.,0.,float('nan'))),('odom_xyyaw',(float('inf'),0.,0.)),
])
def test_capture_pose_requires_finite_five_joint_and_three_odometry_values(field,value):
    capture=observation(time=.98);setattr(capture,field,value)
    with pytest.raises(ValueError):
        command_from_direction(dict(should_control=True,direction=[1.,0.,0.],direction_frame='pitch_link'),
            observation(),capture_observation=capture)


@pytest.mark.parametrize('field,value',[
    ('own_qpos',None),('own_qpos',(0.,0.,0.)),('odom_xyyaw',None),
    ('odom_xyyaw',(0.,0.,float('nan'))),('sim_time',float('nan')),
])
def test_pitch_mapping_also_refuses_missing_or_nonfinite_current_pose_and_time(field,value):
    current=observation();setattr(current,field,value)
    with pytest.raises(ValueError):
        command_from_direction(dict(should_control=True,direction=[1.,0.,0.],direction_frame='pitch_link'),
            current,capture_observation=observation(time=.98))


def test_world_direction_behavior_ignores_unused_capture_argument():
    current=observation(base=.4,yaw=.2,pitch=.1)
    output=dict(should_control=True,should_shoot=False,direction=[math.cos(.7),math.sin(.7),0.],direction_frame='world')
    plain=command_from_direction(output,current)
    extra=command_from_direction(output,current,capture_observation=SimpleNamespace())
    assert plain==extra and plain.gimbal_yaw==pytest.approx(.3) and plain.gimbal_pitch==0.


def test_no_control_preserves_original_hold_without_any_capture_requirements():
    current=observation(base=.7,yaw=.3,pitch=.2)
    output=dict(should_control=False,should_shoot=True,direction_frame='pitch_link')
    hold=command_from_direction(output,current,capture_observation=SimpleNamespace())
    assert hold.gimbal_yaw==.3 and hold.gimbal_pitch==.2 and not hold.fire
    assert command_from_direction(output,current)==hold
