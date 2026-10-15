"""Native metadata bounds only; no ROS, occupancy prediction or planning."""
import copy
import math

import pytest

from rm_match.integrations.pb_costmap_readiness import contains_map_position,validate_costmap_metadata
from rm_match.platform_v2.contracts import ContractError


def metadata(*,width=2,height=1,resolution=1.,origin=(0.,0.,0.),yaw=0.):
    return dict(header=dict(stamp=dict(sec=1,nanosec=0),frame_id="map"),
        info=dict(map_load_time=dict(sec=0,nanosec=0),width=width,height=height,resolution=resolution,
            origin=dict(position=dict(zip("xyz",origin)),orientation=dict(x=0.,y=0.,z=math.sin(yaw/2),w=math.cos(yaw/2)))),
        data_length=width*height)


def test_half_open_original_bounds_no_clamping_or_inflation():
    grid=metadata()
    assert contains_map_position(grid,[0.,0.,0.])
    assert contains_map_position(grid,[1.999,.999,0.])
    for point in ([-.001,.5,0.],[2.,.5,0.],[.5,1.,0.],[.5,-.001,0.]):
        assert contains_map_position(grid,point) is False


def test_actual_rotated_and_translated_origin_is_inverted():
    grid=metadata(origin=(3.,-2.,0.),yaw=math.pi/2)
    assert contains_map_position(grid,[2.25,-1.75,0.])  # local [.25,.75]
    assert not contains_map_position(grid,[2.25,.25,0.])  # local [2.25,.75]
    assert not contains_map_position(grid,[3.25,-1.75,0.])  # local [.25,-.25]


def test_resolution_and_native_data_length_are_used_without_inspecting_occupancy():
    grid=metadata(width=4,height=4,resolution=.25)
    assert contains_map_position(grid,[.99,.99,0.]) and not contains_map_position(grid,[1.,.5,0.])
    assert "data" not in grid  # this gate cannot promise collision-free motion


@pytest.mark.parametrize("mutate",[
    lambda g:g["header"].update(frame_id="odom"),
    lambda g:g["header"]["stamp"].update(sec=True),
    lambda g:g["header"]["stamp"].update(nanosec=1000000000),
    lambda g:g["info"].update(width=True),lambda g:g["info"].update(width=0),
    lambda g:g["info"].update(height=1.),lambda g:g["info"].update(resolution=0.),
    lambda g:g["info"].update(resolution=float("nan")),lambda g:g["info"].update(resolution=True),
    lambda g:g.update(data_length=1),lambda g:g.update(data_length=2.),
    lambda g:g["info"]["origin"]["position"].update(x=float("inf")),
    lambda g:g["info"]["origin"]["orientation"].update(w=0.),
    lambda g:g["info"]["origin"]["orientation"].update(z=True),
    lambda g:g.update(enemy_truth=[1.,2.]),
])
def test_missing_or_malformed_native_metadata_never_marks_navigation_ready(mutate):
    grid=metadata();mutate(grid)
    assert contains_map_position(grid,[.5,.5,0.]) is False
    with pytest.raises(ContractError):validate_costmap_metadata(grid)


@pytest.mark.parametrize("value",[None,{},True])
def test_unavailable_map_is_false(value):
    assert contains_map_position(value,[.5,.5,0.]) is False


@pytest.mark.parametrize("point",[[True,.5,0.],[float("nan"),.5,0.],[.5,.5],[.5,.5,float("inf")]])
def test_invalid_position_is_never_replaced_with_an_old_or_ideal_pose(point):
    assert contains_map_position(metadata(),point) is False


def test_validated_metadata_is_detached_from_later_message_mutation():
    original=metadata();selected=validate_costmap_metadata(original)
    original["info"]["origin"]["position"]["x"]=100.
    assert contains_map_position(selected,[.5,.5,0.])
    assert not contains_map_position(original,[.5,.5,0.])
