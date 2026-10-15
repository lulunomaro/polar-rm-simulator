"""Strict OccupancyGrid bounds only; no occupancy, pose inference or planning.

The caller supplies metadata from its actual owned costmap and the same actual
map-frame estimate used for feedback. Containment does not promise a free cell,
reachable goal, calibrated competition field or successful navigation.
"""
from __future__ import annotations

import copy
import math

from ..platform_v2.contracts import ContractError, exact, finite, integer, vector


def _stamp(value):
    exact(value,("sec","nanosec"),"costmap_stamp")
    integer(value["sec"],"costmap_sec",0,2147483647)
    integer(value["nanosec"],"costmap_nanosec",0,999999999)


def validate_costmap_metadata(value):
    """Return a detached, nonempty native OccupancyGrid metadata snapshot."""
    value=copy.deepcopy(value)
    exact(value,("header","info","data_length"),"costmap_metadata")
    exact(value["header"],("stamp","frame_id"),"costmap_header")
    _stamp(value["header"]["stamp"])
    if type(value["header"]["frame_id"]) is not str or value["header"]["frame_id"]!="map":
        raise ContractError("costmap_map_frame_required")
    info=value["info"]
    exact(info,("map_load_time","resolution","width","height","origin"),"costmap_info")
    _stamp(info["map_load_time"])
    resolution=finite(info["resolution"],"costmap_resolution",0,1e9)
    if resolution<=0:raise ContractError("costmap_positive_resolution_required")
    width=integer(info["width"],"costmap_width",1,2**32-1)
    height=integer(info["height"],"costmap_height",1,2**32-1)
    if integer(value["data_length"],"costmap_data_length")!=width*height:
        raise ContractError("costmap_data_length_mismatch")
    origin=info["origin"]
    exact(origin,("position","orientation"),"costmap_origin")
    exact(origin["position"],("x","y","z"),"costmap_origin_position")
    exact(origin["orientation"],("x","y","z","w"),"costmap_origin_orientation")
    vector([origin["position"][k] for k in "xyz"],3,"costmap_origin_position")
    q=vector([origin["orientation"][k] for k in "xyzw"],4,"costmap_origin_orientation",-1,1)
    if abs(sum(v*v for v in q)-1)>1e-6:raise ContractError("costmap_origin_quaternion_not_unit")
    if not math.isfinite(width*resolution) or not math.isfinite(height*resolution):
        raise ContractError("costmap_bounds_not_finite")
    return value


def contains_map_position(metadata,position_m):
    """Fail closed for missing/malformed metadata or non-map 3-D positions.

    Apply the inverse original origin quaternion, then the exact half-open grid
    extent. No epsilon expansion, clamping, occupancy sampling or fallback pose.
    """
    try:
        value=validate_costmap_metadata(metadata)
        p=vector(position_m,3,"costmap_start_position")
    except (ContractError,TypeError,KeyError,OverflowError):
        return False
    info=value["info"];origin=info["origin"]
    vx,vy,vz=[p[i]-origin["position"][k] for i,k in enumerate("xyz")]
    x,y,z=[-origin["orientation"][k] for k in "xyz"];w=origin["orientation"]["w"]
    # q^-1 * v * q, preserving the native map origin rotation.
    tx,ty,tz=2*(y*vz-z*vy),2*(z*vx-x*vz),2*(x*vy-y*vx)
    local_x=vx+w*tx+(y*tz-z*ty)
    local_y=vy+w*ty+(z*tx-x*tz)
    return (0<=local_x<info["width"]*info["resolution"]
        and 0<=local_y<info["height"]*info["resolution"])
