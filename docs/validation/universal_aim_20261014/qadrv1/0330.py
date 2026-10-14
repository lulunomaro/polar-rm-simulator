import math
import pytest
from rm_match.navigation import OccupancyGrid,NavObservation,NavigationBaseline
from rm_match.match_controllers import StaticArenaGrid
from rm_match.contracts import NavigationIntent


def walls(xy,t=0.):
    angles=tuple(-math.pi+2*math.pi*k/64 for k in range(64));ranges=[]
    for a in angles:
        dx,dy=math.cos(a),math.sin(a);distances=[8.]
        if abs(dx)>1e-10:distances.append(((6 if dx>0 else -6)-xy[0])/dx)
        if abs(dy)>1e-10:distances.append(((4 if dy>0 else -4)-xy[1])/dy)
        ranges.append(min(distances))
    return NavObservation(0,'red_sentry',t,(*xy,0.),(0.,0.),tuple(ranges),angles)


def test_near_wall_quantized_blocked_start_has_continuous_same_padding_connection():
    g=StaticArenaGrid();start=(-5.250000215,-3.42994263);g.update(walls(start))
    assert g.padding==.5 and not g.free(g.cell(start))
    path=g.plan(start,(0.,0.))
    assert path and path[0]==start and g.last_start_connector==path[1]
    assert g.continuous_segment_clear(start,path[1])
    assert all(g.free(g.cell(p)) for p in path[1:])
    # Translation is not a teleport and the controller must not skip a short
    # connector via the ordinary 0.32m waypoint lookahead.
    n=NavigationBaseline(bounds=(-6,6,-4,4));n.reset(0);n.grid=StaticArenaGrid()
    n.set_intent(NavigationIntent('INTERCEPT',(0.,0.)))
    v=n.velocity(walls(start));assert 0<math.hypot(*v)<=.4
    assert n.last_status=='continuous_start_connector' and n.intent.target_point==(0.,0.)


def test_segment_interior_collision_is_rejected_even_if_endpoints_clear():
    g=OccupancyGrid(bounds=(-4,4,-4,4));o=NavObservation(0,'r',0.,(-1.,0.,0.),(0.,0.),(1.,),(0.,))
    g.update(o)
    assert math.dist((-1.,0.),(0.,0.))>g.padding and math.dist((1.,0.),(0.,0.))>g.padding
    assert not g.continuous_segment_clear((-1.,0.),(1.,0.))
    assert not g.continuous_segment_clear((-1.,.5),(1.,.5))  # exact boundary is not clear
    assert g.continuous_segment_clear((-1.,.6),(1.,.6))


def test_fixed_obstacle_diagonal_corner_cannot_be_cut():
    g=StaticArenaGrid();g.fixed_boxes=[(0.,0.,.25,.25)];g.static=set()
    g.update(NavObservation(0,'r',0.,(-1.,1.,0.),(0.,0.),(8.,),(0.,)))
    assert not g.continuous_segment_clear((-1.,0.),(0.,1.))
    assert g.continuous_segment_clear((-1.,1.),(1.,1.))


def test_no_scan_or_unknown_cells_cannot_be_bypassed():
    g=OccupancyGrid(bounds=(-4,4,-4,4));assert not g.continuous_segment_clear((0.,0.),(1.,0.))
    g.update(NavObservation(0,'r',0.,(0.,0.,0.),(0.,0.),(8.,),(0.,)))
    g.blocked.add(g.cell((.5,.5)))
    assert not g.continuous_segment_clear((0.,0.),(1.,0.))


def test_truly_enclosed_stops_without_fake_recovery_and_retains_live_intent():
    n=NavigationBaseline(bounds=(-6,6,-4,4));n.reset(0);n.set_intent(NavigationIntent('INTERCEPT',(0.,0.)))
    angles=tuple(-math.pi+2*math.pi*k/64 for k in range(64))
    for t in (0.,.5,1.,1.5,2.,2.5,3.):
        o=NavObservation(0,'r',t,(-2.,-2.,0.),(0.,0.),(.38,)*64,angles)
        assert n.velocity(o)==(0.,0.)
    assert n.metrics.recovery_count==0 and n.last_status=='blocked_no_safe_escape'
    assert n.intent.target_point==(0.,0.)
    # Once measurements become free, the same intent can resume; no stale
    # blocking latch, new goal, episode reset, or world-state injection needed.
    v=n.velocity(NavObservation(0,'r',3.1,(-2.,-2.,0.),(0.,0.),(8.,)*64,angles))
    assert math.hypot(*v)>0 and n.intent.target_point==(0.,0.)


def test_same_cell_new_endpoint_never_erases_still_fresh_old_endpoint():
    # Independent review counterexample 56: replacing same-cell points admitted
    # a connector passing 0.44594m from old data, below the unchanged .5m margin.
    start=(.6268867333208157,-.022363818603972713)
    old=(.08167464680990341,.019813419713287022)
    new=(.09196291346304052,.2104761387901572)
    end=(.125,-.625)
    def o(point,t):
        return NavObservation(0,'r',t,(*start,0.),(0.,0.),(math.dist(start,point),),
            (math.atan2(point[1]-start[1],point[0]-start[0]),))
    g=OccupancyGrid(bounds=(-4,4,-4,4));g.update(o(old,0.));g.update(o(new,.1))
    assert g.cell(old)==g.cell(new) and g.cell(old) in g.hits
    assert any(math.dist(point,old)<1e-12 for point,t in g.endpoint_history)
    assert not g.continuous_segment_clear(start,end)
    # A new point cannot renew an old sample indefinitely either. After its
    # declared 3s expiry the old sample disappears while the new one remains.
    g.update(o(new,3.01))
    assert not any(math.dist(point,old)<1e-12 for point,t in g.endpoint_history)
    assert g.continuous_segment_clear(start,end)


def test_coarse_free_ray_does_not_prematurely_drop_continuous_point_evidence():
    g=OccupancyGrid(bounds=(-4,4,-4,4));start=(-1.,0.)
    g.update(NavObservation(0,'r',0.,(*start,0.),(0.,0.),(1.,),(0.,)))
    g.update(NavObservation(0,'r',.1,(*start,0.),(0.,0.),(8.,),(0.,)))
    assert not g.hits  # normal grid keeps its original free-ray behavior
    assert not g.continuous_segment_clear(start,(1.,0.))  # connector is more conservative
