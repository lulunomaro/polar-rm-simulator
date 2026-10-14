"""Independent Phase-B match navigation baselines; no inter-robot communication.

Public fixed arena XML is a permitted prior map. Enemy/teammate poses, judge internals
and physics data are never inputs. Role offsets, supply thresholds and purchase
batch sizes are scenario choices, not official tactical requirements.
"""
from dataclasses import dataclass
import math
from .arena import arena_worldbody, arena_metadata
from .contracts import Command, NavigationIntent
from .navigation import NavigationBaseline, OccupancyGrid, NavObservation, clamp
from .opening_strategy import OpeningRushSupervisor
from .original_decision_adapter import OriginalRuleAdapter


class StaticArenaGrid(OccupancyGrid):
    """Avoid fixed boxes the provisional planar chassis cannot climb."""
    def __init__(self):
        super().__init__(bounds=(-6.,6.,-4.,4.))
        self.static = set()
        self.fixed_boxes=[]
        for geom in arena_worldbody().findall('geom'):
            if geom.get('contype','1') == '0' or geom.get('type') != 'box': continue
            p = tuple(map(float,geom.get('pos','0 0 0').split()))
            size = tuple(map(float,geom.get('size').split()))
            if p[2]+size[2] <= .03: continue  # floor/decals
            self.fixed_boxes.append((p[0],p[1],size[0],size[1]))
            lo = self.cell((p[0]-size[0]-self.padding,p[1]-size[1]-self.padding))
            hi = self.cell((p[0]+size[0]+self.padding,p[1]+size[1]+self.padding))
            for ix in range(lo[0],hi[0]+1):
                for iy in range(lo[1],hi[1]+1):
                    x,y = self.center((ix,iy))
                    dx=max(0.,abs(x-p[0])-size[0]);dy=max(0.,abs(y-p[1])-size[1])
                    if math.hypot(dx,dy)<=self.padding+.05:self.static.add((ix,iy))
        self.blocked = set(self.static)

    def continuous_segment_clear(self,start,end):
        if not super().continuous_segment_clear(start,end):return False
        # Slab intersection against each box enlarged by the ORIGINAL padding.
        # This square expansion is conservative even at rectangular corners.
        for x,y,hx,hy in self.fixed_boxes:
            lo,hi=0.,1.
            for k,(center,half) in enumerate(((x,hx+self.padding),(y,hy+self.padding))):
                delta=end[k]-start[k]
                if abs(delta)<1e-12:
                    if not center-half<=start[k]<=center+half:lo,hi=1.,0.;break
                else:
                    t1,t2=(center-half-start[k])/delta,(center+half-start[k])/delta
                    lo=max(lo,min(t1,t2));hi=min(hi,max(t1,t2))
            if lo<=hi:return False
        return True

    def update(self,o):
        super().update(o)
        self.blocked |= self.static


@dataclass(frozen=True)
class MatchControlDecision:
    command: Command
    purchase_bundles: int = 0  # referee request only; never grants ammunition
    mode: str = 'hold'


def compose_navigation_and_aim(navigation: Command, aim: Command) -> Command:
    """Unambiguous field ownership: nav chassis forces; aim gimbal and trigger."""
    return Command(navigation.force_x,navigation.force_y,navigation.yaw_torque,
                   aim.gimbal_yaw,aim.gimbal_pitch,aim.fire)


class MatchNavigationPolicy:
    label = 'independent_role_navigation_baseline'

    def __init__(self):
        self.supply_centers={team:tuple(arena_metadata()['coordinates'][team+'_supply_center'][:2]) for team in ('red','blue')}
        self.nav=NavigationBaseline(bounds=(-6.,6.,-4.,4.),max_speed=1.)
        self.opening=OpeningRushSupervisor()
        self.reset(-1)

    def reset(self,episode):
        self.episode=episode
        self.nav.reset(episode)
        self.nav.grid=StaticArenaGrid()
        self.opening.reset(episode)
        self.original_rule=OriginalRuleAdapter()
        self.last_tactical_time=-math.inf
        self.last_tactical_decision=None
        self.last_purchase=-math.inf
        self.mode=None
        self.resupplying=False
        self.opening_egress_released=False
        self.events=[]
        self.robot_id=None
        self.supply_hold=None
        self.total_distance_m=0.
        self.last_xy=None
        self.last_decision=MatchControlDecision(Command())
        self.desired_velocity=(0.,0.)

    @property
    def metrics(self): return self.nav.metrics

    def _event(self,o,kind,**data):
        self.events.append(dict(episode=o.episode,robot_id=o.robot_id,sim_time=o.sim_time,
                                type=kind,source=self.label,**data))

    @staticmethod
    def _egress_clearance(o,direction):
        """Rectangular chassis corridor for the dense legal starting bay.

        The planner's 0.5m circle initially overlaps neighboring parked robots.
        The fixture's real 0.31x0.26m half-footprint plus 0.06m margin fits; this
        checked swept rectangle is used ONLY along the known straight bay lanes.
        """
        yaw=o.odom_xyyaw[2]
        dx=direction[0]*math.cos(yaw)+direction[1]*math.sin(yaw)
        dy=-direction[0]*math.sin(yaw)+direction[1]*math.cos(yaw)
        along_half=abs(dx)*.31+abs(dy)*.26+.06
        across_half=abs(dy)*.31+abs(dx)*.26+.06
        clearance=o.range_max
        if not o.ranges or not any(math.isfinite(r) and r>0 for r in o.ranges):return 0.
        for r,a in zip(o.ranges,o.range_angles):
            if not math.isfinite(r) or r<=0 or r>=o.range_max-.02:continue
            px,py=r*math.cos(a),r*math.sin(a)
            along=px*dx+py*dy;across=abs(px*dy-py*dx)
            if along>0 and across<across_half:clearance=min(clearance,along-along_half)
        return max(0.,clearance)

    def decide(self,o):
        if o.episode!=self.episode:self.reset(o.episode)
        self.desired_velocity=(0.,0.)
        if self.robot_id is None:self.robot_id=o.robot_id
        if self.robot_id!=o.robot_id:raise ValueError('One policy instance per robot is required')
        if o.team not in ('red','blue') or o.role not in ('hero','infantry','sentry'):
            raise ValueError('Unknown team/role')
        if o.odom_xyyaw is None:raise ValueError('World odometry required')
        safety=self.opening.decide(o)
        if not safety.enabled:
            # No stale route, force, purchase, or trigger survives a phase gate.
            self.nav.intent=None;self.nav.path=[];self.nav.progress.clear()
            if safety.mode!=self.mode:
                self._event(o,'match_navigation_mode',mode=safety.mode)
            self.mode=safety.mode
            self.last_decision=MatchControlDecision(Command(),0,safety.mode)
            return self.last_decision
        side=1 if o.team=='red' else -1
        x,y=o.odom_xyyaw[:2]
        in_egress_corridor=side*x < -3.95 and side*y > -1.7
        # Sentry bay egress is a one-shot opening privilege, not a route for
        # later supply returns. Once outside, at center, or handed to an active
        # recovery, normal navigation owns motion for the rest of this episode.
        # Update before the supply branch too, so retreat cannot hide an exit.
        if o.role=='sentry' and (not in_egress_corridor or self.opening.arrived_at is not None
                                or o.sim_time < self.nav.recover_until):
            self.opening_egress_released=True
        if self.last_xy is not None:self.total_distance_m+=math.dist((x,y),self.last_xy)
        self.last_xy=(x,y)
        supply=self.supply_centers[o.team]
        in_supply=abs(x-supply[0])<=.75 and abs(y-supply[1])<=1.
        max_hp=getattr(o,'own_max_hp',0) or {'hero':350,'infantry':300,'sentry':400}[o.role]
        weak=getattr(o,'own_weak',False)
        low_ammo=o.role!='sentry' and o.ammo<=({'hero':1,'infantry':10}.get(o.role,0))
        # Hysteresis prevents oscillation around low HP/ammo thresholds.
        if weak or o.own_hp<max_hp*.4 or low_ammo:self.resupplying=True
        if self.resupplying and o.own_hp>=max_hp*.85 and not weak and not low_ammo:
            self.resupplying=False
        purchase=0
        if o.own_hp<=0:
            mode='dead'
            command=Command()
        elif self.resupplying:
            mode='supply'
            # Keep current lane when already in supply; do not converge all robots
            # onto one point merely to request ammo/heal.
            if not in_supply:self.supply_hold=None
            if in_supply and self.supply_hold is None:self.supply_hold=(x,y)
            goal=self.supply_hold if in_supply else (supply[0],supply[1]+side*{'hero':-.5,'infantry':0.,'sentry':.4}[o.role])
            self.nav.set_intent(NavigationIntent('RETREAT',goal,'scenario resupply baseline'))
            command=self.nav.act(o)
            self.desired_velocity=self.nav.last_velocity_target
            if in_supply and low_ammo and o.sim_time>=1. and o.sim_time-self.last_purchase>=1.:
                purchase=5
                self.last_purchase=o.sim_time
                self._event(o,'ammo_purchase_requested',bundles=purchase)
        else:
            mode='control'
            # Static role assignment only. No friend positions or shared intent.
            # Sentry owns the control entry lane; scripted support robots take
            # rear firing stations, rather than plugging the opponent's entry.
            goal={'hero':(-3.8*side,-3.0*side),'infantry':(-.6*side,-2.6*side),
                  'sentry':(-.6*side,-1.2*side)}[o.role]
            intent=NavigationIntent('HOLD',goal,'scenario control-zone baseline')
            if o.role=='sentry':
                if safety.intent is not None:
                    mode=safety.mode
                    intent=safety.intent
                else:
                    if o.sim_time-self.last_tactical_time>=.5 or self.last_tactical_decision is None:
                        self.last_tactical_decision=self.original_rule.decide(o)
                        self.last_tactical_time=o.sim_time
                        self._event(o,'original_rule_decision',record=self.original_rule.last_record)
                    d=self.last_tactical_decision
                    p=d['target_point']
                    goal=(p['x'],p['y'])
                    mode={'RETREAT':'supply','ENGAGE':'engage'}.get(d['behavior'],'occupation')
                    # In this UL occupation scenario, patrol means defend the
                    # configured center station; vision engagements stay inside.
                    if d['behavior']=='ENGAGE':
                        goal=(clamp(goal[0],-1.1,1.1),clamp(goal[1],-1.1,1.1))
                    intent=NavigationIntent('HOLD' if mode=='occupation' else d['behavior'],goal,d['reason'])
            self.nav.set_intent(intent)
            # Dense starting bays fit rectangular bodies but not the planner's
            # conservative circular inflation. Preprogrammed stagger + local
            # sensed-clear corridor egress avoids a shared-start deadlock.
            # This timing/route is a scenario controller, not an official rule.
            self.supply_hold=None
            if in_egress_corridor and (o.role!='sentry' or not self.opening_egress_released):
                mode='opening_egress' if o.role=='sentry' else 'supply_departure'
                # Keep the original spawn positions. Non-sentries shift into
                # the inner bay lane while the sentry takes the outer lane.
                # These are public-map role routes, without teammate poses.
                direction=((float(side),0.) if o.role!='sentry' and side*x < -4.4
                           else (0.,-float(side)))
                clearance=self._egress_clearance(o,direction)
                # No time-based sentry delay. A measured obstruction may brake
                # physical motion while the center intent remains active.
                remaining=max(0.,clearance-.20)
                speed=min(1.0 if o.role=='sentry' else .75,remaining*1.6,
                    math.sqrt(2*.65*remaining))
                if direction[0]:speed=min(speed,max(0.,-4.25-side*x)*1.5)
                if o.role!='sentry' and not direction[0] and o.sim_time<12.:
                    # Symmetric support staging, not a sentry delay. Both teams
                    # clear their own bay lane, then give the opening runner
                    # first access to the narrow platform exit.
                    speed=0.
                    mode='support_stage'
                vx,vy=o.odom_vxyw[:2]
                self.desired_velocity=(direction[0]*speed,direction[1]*speed)
                command=Command(force_x=clamp(28*(direction[0]*speed-vx)+8*direction[0]*speed,-60.,60.),
                    force_y=clamp(28*(direction[1]*speed-vy)+8*direction[1]*speed,-60.,60.))
            else:
                self.nav.max_speed=1.4 if o.role=='sentry' else 1.
                command=self.nav.act(o)
                self.desired_velocity=self.nav.last_velocity_target
        # A supply nav.act above can START recovery on this very observation.
        # Latch that handoff now, even if the next observation arrives late.
        if o.role=='sentry' and o.sim_time < self.nav.recover_until:
            self.opening_egress_released=True
        if mode!=self.mode:
            self._event(o,'match_navigation_mode',mode=mode)
            self.mode=mode
        self.nav.metrics.distance_travelled_m=self.total_distance_m
        self.last_decision=MatchControlDecision(command,purchase,mode)
        return self.last_decision

    def act(self,o):
        """Controller-compatible call; purchase request available in last_decision."""
        return self.decide(o).command
