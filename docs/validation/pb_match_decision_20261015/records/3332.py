"""Offline contract validation; never calls an LLM, network or robot hardware."""
import math
from .contracts import NavigationIntent

def parse_navigation_intent(payload):
    allowed={'ENGAGE','INTERCEPT','HOLD','HARASS','PATROL','RETREAT'}
    if payload.get('behavior') not in allowed: raise ValueError('Unknown behavior')
    point=payload.get('target_point')
    if not isinstance(point,dict) or not all(k in point for k in ('x','y')):
        raise ValueError('Expected target_point {x,y}')
    x,y=float(point['x']),float(point['y'])
    if not all(math.isfinite(v) for v in (x,y)): raise ValueError('Nonfinite goal')
    return NavigationIntent(payload['behavior'],(x,y),str(payload.get('reason','')))
