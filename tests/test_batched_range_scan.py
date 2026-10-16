"""Real batch/scalar ray equivalence; no inference, ideal target or realtime acceptance."""
from unittest.mock import patch

import mujoco
import numpy as np
import pytest

from rm_match.match_engine import MatchSimulation
from rm_match.platform_v2.camera import camera_model_xml


def original_scalar_scan(sim,rid):
    """Pre-change algorithm, independent public single-ray API."""
    origin=sim.data.xpos[sim.body_ids[rid]].copy();origin[2]=.25
    yaw=float(sim.data.qpos[sim.qindices[rid][2]]);ranges=[]
    for angle in np.linspace(-np.pi,np.pi,65)[:-1]+yaw:
        gid=np.array([-1],dtype=np.int32)
        distance=mujoco.mj_ray(sim.model,sim.data,origin,np.array([np.cos(angle),np.sin(angle),0.]),
            np.array([1,0,0,0,0,0],dtype=np.uint8),1,sim.body_ids[rid],gid)
        ranges.append(float(min(distance,8.)) if distance>=0 else 8.)
    return tuple(ranges)


@pytest.fixture(scope='module')
def simulation():
    sim=MatchSimulation(render=False,model_xml=camera_model_xml())
    try:yield sim
    finally:sim.close()


@pytest.mark.parametrize('rid',[team+'_'+role for team in ('red','blue') for role in ('hero','infantry','sentry')])
@pytest.mark.parametrize('yaw',[-3.1,-1.,0.,.2,1.,3.1])
def test_batch_matches_original_64_rays_across_all_robot_bodies_and_rotations(simulation,rid,yaw):
    sim=simulation;sim.reset();sim.data.qpos[sim.qindices[rid][2]]=yaw
    mujoco.mj_forward(sim.model,sim.data)
    before={key:getattr(sim.data,key).copy() for key in ('qpos','qvel','ctrl')};stamp=sim.time
    expected=original_scalar_scan(sim,rid);actual=sim.scan(rid)
    assert actual==expected
    assert len(actual)==64 and all(type(v) is float and 0<=v<=8. for v in actual)
    assert stamp==sim.time
    for key,value in before.items():np.testing.assert_array_equal(getattr(sim.data,key),value)


@pytest.mark.parametrize('xy',[(-3.5,3.),(-1.2,3.),(0.,0.),(3.,-2.),(-6.,0.),(0.,8.),(20.,20.)])
def test_original_occlusion_and_8m_saturation_remain_at_translated_origins(simulation,xy):
    from rm_match.match_model import SPAWNS
    sim=simulation;sim.reset();rid='red_infantry'
    for axis in (0,1):sim.data.qpos[sim.qindices[rid][axis]]=xy[axis]-SPAWNS[rid][axis]
    mujoco.mj_forward(sim.model,sim.data)
    actual=sim.scan(rid);assert actual==original_scalar_scan(sim,rid)
    if xy==(20.,20.):assert 8. in actual


def test_one_batch_call_keeps_original_filter_origin_and_directions(simulation):
    sim=simulation;sim.reset();rid='blue_sentry';batch=mujoco.mj_multiRay
    with patch.object(mujoco,'mj_multiRay',wraps=batch) as called, \
         patch.object(mujoco,'mj_ray',side_effect=AssertionError('per-ray Python call')):
        actual=sim.scan(rid)
    assert called.call_count==1 and len(actual)==64
    model,data,origin,vectors,groups,static,excluded,ids,distances,normals,count,cutoff=called.call_args.args
    assert model is sim.model and data is sim.data and count==64 and static is True
    assert excluded==sim.body_ids[rid] and cutoff==float('inf') and normals is None
    np.testing.assert_array_equal(groups,[1,0,0,0,0,0])
    expected_origin=sim.data.xpos[sim.body_ids[rid]].copy();expected_origin[2]=.25
    np.testing.assert_array_equal(origin,expected_origin)
    angles=np.linspace(-np.pi,np.pi,65)[:-1]+float(sim.data.qpos[sim.qindices[rid][2]])
    np.testing.assert_array_equal(vectors.reshape(64,3),[[np.cos(a),np.sin(a),0.] for a in angles])


def test_motion_and_reset_do_not_reuse_old_sensor_results(simulation):
    from rm_match.contracts import Command
    sim=simulation;sim.reset();rid='red_infantry';first=sim.scan(rid)
    for _ in range(80):sim.step({rid:Command(force_x=3.,force_y=1.,yaw_torque=.2)})
    current=sim.scan(rid);assert current==original_scalar_scan(sim,rid) and current!=first
    sim.reset();assert sim.scan(rid)==first


def test_observation_keeps_ranges_angles_own_state_and_original_sample_time(simulation):
    sim=simulation;sim.reset();rid='red_infantry'
    expected=original_scalar_scan(sim,rid);observed=sim.observe(rid,include_rgb=False)
    assert observed.ranges==expected and observed.range_angles==tuple(np.linspace(-np.pi,np.pi,65)[:-1])
    assert observed.sim_time==sim.time and observed.robot_id==rid and observed.episode==sim.episode
    assert observed.rgb.shape==(0,0,3)
    with patch.object(sim,'scan',side_effect=AssertionError('disabled ranges sampled')):
        assert sim.observe(rid,include_rgb=False,include_ranges=False).ranges==()
