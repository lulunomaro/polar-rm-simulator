"""Duration qualification uses actual physics, never teardown time."""
import math

def completed_physics_duration(steps,timestep,physics_elapsed,requested_seconds):
    if type(steps) is not int or steps<0:return False
    values=(timestep,physics_elapsed,requested_seconds)
    if any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in values):return False
    # The last integration entry may precede the wall deadline by one scheduled
    # step. Bound tolerance to that sampling boundary, not a control window.
    return physics_elapsed>=requested_seconds-2*timestep and steps*timestep>=requested_seconds-timestep
