"""Simulation-only ModList request and fail-closed source-authority boundary.

This module is not a detector, tracker, or firing controller. The source RMCS
operator adapter is currently unavailable; request support never grants control.
FOV admission is pure image/calibration geometry for a future source integration.
No simulator, enemy pose, map, networking, or hardware interfaces are accepted.
"""
from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True)
class AutoAimRequest:
    enabled: bool = False
    hold: bool = False
    fov_degrees: float = 85.
    circle_radius_x_norm: float = .25
    circle_radius_y_norm: float = .25


def _number(value, low, high, *, positive=False):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value) and low <= value <= high and (not positive or value > 0)
    except (OverflowError, ValueError):
        return False


def parse_aim_request(payload=None):
    """Absent field preserves v1 clients; present requests must be complete."""
    if payload is None:
        return AutoAimRequest()
    names=set(AutoAimRequest.__dataclass_fields__)
    if not isinstance(payload, dict) or set(payload) != names:
        raise ValueError('invalid_aim_request')
    for key in ('enabled', 'hold'):
        if type(payload[key]) is not bool:
            raise ValueError('invalid_aim_request_'+key)
    for key,low,high in [('fov_degrees',10,180),
                         ('circle_radius_x_norm',0,2),('circle_radius_y_norm',0,2)]:
        if not _number(payload[key],low,high,positive=True):
            raise ValueError('invalid_aim_request_'+key)
    return AutoAimRequest(**payload)


@dataclass(frozen=True)
class ImageCalibration:
    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float

    def valid(self):
        return (type(self.width) is int and type(self.height) is int
                and 1 <= self.width <= 16384 and 1 <= self.height <= 16384
                and all(_number(v,-1e8,1e8) for v in (self.fx,self.fy,self.cx,self.cy))
                and self.fx > 0 and self.fy > 0
                and 0 <= self.cx < self.width and 0 <= self.cy < self.height)


def fov_admission(center_px, calibration, request):
    """Intersect source-pixel ellipse and full-angle cone; fail closed.

    center_px must come from source camera perception, already undistorted using
    the calibration supplied here. Nominal MuJoCo pinhole pixels need no warp.
    Circle is centered on image center; angular cone on optical principal point.
    This checks image-space range, NOT a metric distance estimate or target ID.
    """
    if not isinstance(calibration, ImageCalibration) or not calibration.valid():
        return False, 'invalid_calibration'
    try:
        request=parse_aim_request(asdict(request))
        if len(center_px) != 2 or not all(_number(v,-1e8,1e8) for v in center_px):
            return False,'invalid_detection_center'
    except (TypeError, ValueError):
        return False,'invalid_request_or_center'
    x,y=center_px;c=calibration
    if not (0 <= x < c.width and 0 <= y < c.height):
        return False,'outside_image'
    dx=(x-c.width*.5)/(request.circle_radius_x_norm*c.width)
    dy=(y-c.height*.5)/(request.circle_radius_y_norm*c.height)
    if dx*dx+dy*dy > 1.+1e-12:
        return False,'outside_circle'
    # atan avoids tan(90deg) overflow at the advertised full-angle 180 maximum.
    angle=math.degrees(math.atan(math.hypot((x-c.cx)/c.fx,(y-c.cy)/c.fy)))
    if angle > request.fov_degrees*.5+1e-12:
        return False,'outside_angle'
    return True,'inside_fov'


class AutoAimAuthority:
    """Unavailable source adapter remains unavailable even after valid requests.

    Do not add an available=True switch: enablement requires a separately tested
    source integration with fresh observations, identity and reset semantics.
    """
    def evaluate(self, request, *, allowed, reason='inactive', identity=None):
        # Validate internal callers too. Wire rejection must neutral the lease.
        request=parse_aim_request(asdict(request))
        if not allowed:
            state_reason=reason if reason != 'active' else 'operator_ineligible'
        elif not request.enabled:
            state_reason='module_disabled'
        elif not request.hold:
            state_reason='right_button_released'
        else:
            state_reason='source_adapter_unavailable'
        return dict(requested=request.enabled,held=request.hold,available=False,
                    active=False,reason=state_reason,authority='manual',
                    algorithm='unavailable',source_frame_seq=None,
                    source_sim_time=None,selected=False,in_fov=None,
                    fov_applied=False,fov=asdict(request),
                    fire_authority='manual_only',simulation_only=True)
