"""Finite-radius swept projectile collision for the harness's translating boxes.

No reliance on native CCD. Sphere-box contact uses the rounded-box Euclidean
signed distance, avoiding expanded-AABB phantom hits at corners. Geometry pose
is sampled each physics step; rotational swept boxes are NOT supported yet.
"""
from dataclasses import dataclass
import numpy as np

def sphere_box_toi(start, end, center0, center1, rotation, half_size, radius):
    p = rotation.T @ (np.asarray(start) - center0)
    v = rotation.T @ ((np.asarray(end)-start) - (center1-center0))
    speed = np.linalg.norm(v)
    def separation(t):
        return np.linalg.norm(np.maximum(np.abs(p+t*v)-half_size, 0.)) - radius
    t = 0.
    for _ in range(100):
        gap = separation(t)
        if gap <= 1e-9:
            return t
        if speed < 1e-12:
            return None
        t += gap/speed
        if t > 1.:
            return None
    # Near tangencies need a bounded convex minimum search, not a false hit.
    lo, hi = t, 1.
    for _ in range(60):
        a, b = (2*lo+hi)/3, (lo+2*hi)/3
        if separation(a) < separation(b): hi = b
        else: lo = a
    minimum = (lo+hi)/2
    if separation(minimum) > 1e-9: return None
    lo, hi = t, minimum
    for _ in range(60):
        mid = (lo+hi)/2
        if separation(mid) <= 1e-9: hi = mid
        else: lo = mid
    return hi

@dataclass
class Projectile:
    uid: str
    position: np.ndarray
    velocity: np.ndarray
    born: float
    radius: float = .0085

def swept_rotating_box_toi(start,end,center0,center1,rotation0,rotation1,half_size,radius):
    """Conservative advancement with translation+rotation distance bound.

Returns first contact within1e-10m; 2ms transform interpolation approximates the
continuous rigid-body path. No expanded-AABB acceptance, only broadphase.
"""
    relative=rotation0.T@rotation1
    angle=float(np.arccos(np.clip((np.trace(relative)-1)/2,-1,1)))
    if angle<1e-8:
        return sphere_box_toi(start,end,center0,center1,rotation0,half_size,radius)
    if angle>np.pi-.001: raise ValueError('Rotation jumped near pi in one physics step')
    axis=np.array([relative[2,1]-relative[1,2],relative[0,2]-relative[2,0],relative[1,0]-relative[0,1]])/(2*np.sin(angle))
    k=np.array([[0,-axis[2],axis[1]],[axis[2],0,-axis[0]],[-axis[1],axis[0],0]])
    delta=np.asarray(end)-start;movement=center1-center0
    bound=np.linalg.norm(delta-movement)+angle*np.linalg.norm(half_size)
    t=0.
    for _ in range(1000):
        a=angle*t;rotation=rotation0@(np.eye(3)+np.sin(a)*k+(1-np.cos(a))*(k@k))
        p=rotation.T@(start+delta*t-center0-movement*t)
        gap=np.linalg.norm(np.maximum(np.abs(p)-half_size,0.))-radius
        if gap<=1e-10:return t
        if bound<1e-12:return None
        t+=gap/bound
        if t>1:return None
    # Near-grazing motion makes conservative advancement converge slowly.
    # Interval subdivision uses the SAME Lipschitz distance bound to exclude
    # intervals, instead of assuming a unimodal distance curve or inventing hits.
    def gap_at(u):
        a=angle*u;rr=rotation0@(np.eye(3)+np.sin(a)*k+(1-np.cos(a))*(k@k))
        pp=rr.T@(start+delta*u-center0-movement*u)
        return float(np.linalg.norm(np.maximum(np.abs(pp)-half_size,0.))-radius)
    stack=[(t,1.,gap_at(t),gap_at(1.))]
    while stack:
        a,b,ga,gb=stack.pop()
        if ga<=1e-10:return a
        mid=(a+b)/2;gm=gap_at(mid);width=b-a
        if max(ga-bound*width,gb-bound*width,gm-bound*width/2)>1e-10:continue
        # A frozen-midpoint box has a convex distance along this linear path.
        # Its exact minimum, minus a rotational Hausdorff bound, is much tighter
        # for tangential sweeps than total path length (which would subdivide
        # millions of intervals for nanometre-clearance near misses).
        aa=angle*mid;frozen=rotation0@(np.eye(3)+np.sin(aa)*k+(1-np.cos(aa))*(k@k))
        def frozen_gap(u):
            pp=frozen.T@(start+delta*u-center0-movement*u)
            return float(np.linalg.norm(np.maximum(np.abs(pp)-half_size,0.))-radius)
        left,right=a,b
        for _ in range(60):
            u=(2*left+right)/3;v=(left+2*right)/3
            if frozen_gap(u)<frozen_gap(v):right=v
            else:left=u
        min_frozen=frozen_gap((left+right)/2)
        numeric_bound=np.linalg.norm(delta-movement)*(right-left)/2
        rotation_bound=np.linalg.norm(half_size)*angle*width/2
        if min_frozen-numeric_bound-rotation_bound>1e-10:continue
        if width<1e-10:
            if gm<=1e-10:return mid
            if gb<=1e-10:return b
            continue
        # Left first gives chronological earliest contact within1e-10 step time.
        stack.append((mid,b,gm,gb));stack.append((a,mid,ga,gm))
    return None

def interpolate_rotation(rotation0,rotation1,t):
    """SO(3) step interpolation plus world angular displacement vector."""
    relative=rotation0.T@rotation1
    angle=float(np.arccos(np.clip((np.trace(relative)-1)/2,-1,1)))
    if angle<1e-8:return rotation0,np.zeros(3)
    if angle>np.pi-.001:raise ValueError('Rotation jump near pi')
    axis=np.array([relative[2,1]-relative[1,2],relative[0,2]-relative[2,0],relative[1,0]-relative[0,1]])/(2*np.sin(angle))
    k=np.array([[0,-axis[2],axis[1]],[axis[2],0,-axis[0]],[-axis[1],axis[0],0]])
    a=angle*t
    return rotation0@(np.eye(3)+np.sin(a)*k+(1-np.cos(a))*(k@k)),rotation0@axis*angle
