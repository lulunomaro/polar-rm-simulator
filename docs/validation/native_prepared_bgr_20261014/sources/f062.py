"""Portable, offline navigation BASELINE, not the repository's deployed LLM policy.

Inputs are own odometry, finite-range anonymous rays and explicit intent. Unknown
space is provisionally traversable; this is not a certified navigation stack.
No MuJoCo data/model or opponent truth is available to this module.
"""
from dataclasses import dataclass, field
from collections import deque
import heapq
import math
from .contracts import Command, NavigationIntent


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


@dataclass(frozen=True)
class NavObservation:
    episode: int
    robot_id: str
    sim_time: float
    xy_yaw: tuple[float, float, float]
    velocity_xy: tuple[float, float]
    ranges: tuple[float, ...]
    angles: tuple[float, ...]  # body-relative radians, same order as ranges
    range_max: float = 8.0
    alive: bool = True

    @classmethod
    def from_observation(cls, o):
        """Common platform adapter: world x/y/yaw, world x/y velocity, SI units."""
        if o.odom_xyyaw is None or o.odom_vxyw is None:
            raise ValueError('Navigation requires explicit world-frame odometry')
        return cls(o.episode, o.robot_id, o.sim_time, tuple(o.odom_xyyaw),
                   tuple(o.odom_vxyw[:2]), tuple(o.ranges), tuple(o.range_angles),
                   o.range_max, o.own_hp > 0)


@dataclass
class NavMetrics:
    distance_travelled_m: float = 0.0
    replans: int = 0
    recovery_count: int = 0
    goal_reached: bool = False
    min_observed_clearance_m: float | None = None
    events: list = field(default_factory=list)


class OccupancyGrid:
    def __init__(self, bounds=(-10., 10., -8., 8.), resolution=.25, radius=.38, margin=.12):
        if resolution <= 0 or radius <= 0 or margin < 0:
            raise ValueError('Invalid grid geometry')
        if bounds[0] >= bounds[1] or bounds[2] >= bounds[3]:
            raise ValueError('Invalid bounds')
        self.bounds = bounds
        self.resolution = resolution
        self.padding = radius + margin
        self.hits = {}  # anonymous scan endpoints: cell -> last sim time
        self.blocked = set()
        self.hit_points = {}
        self.endpoint_history = []
        self.scan_blocked = set()
        self.has_scan = False
        self.last_start_connector = None

    def cell(self, p):
        return (int(math.floor((p[0]-self.bounds[0])/self.resolution)),
                int(math.floor((p[1]-self.bounds[2])/self.resolution)))

    def center(self, c):
        return (self.bounds[0]+(c[0]+.5)*self.resolution,
                self.bounds[2]+(c[1]+.5)*self.resolution)

    def inside(self, c):
        x,y = self.center(c)
        a,b,d,e = self.bounds
        return a+self.padding <= x <= b-self.padding and d+self.padding <= y <= e-self.padding

    def free(self, c):
        return self.inside(c) and c not in self.blocked

    def update(self, o):
        x,y,yaw = o.xy_yaw
        # Stale anonymous endpoints expire; current free rays also clear moved objects.
        self.hits = {c:t for c,t in self.hits.items() if o.sim_time-t < 3.}
        self.hit_points = {c:p for c,p in self.hit_points.items() if c in self.hits}
        self.endpoint_history = [(point,t) for point,t in self.endpoint_history if o.sim_time-t<3.]
        self.has_scan = any(math.isfinite(r) and r>0 for r in o.ranges)
        fresh = {}
        for r, angle in zip(o.ranges, o.angles):
            if not math.isfinite(r) or r <= 0:
                continue
            r = min(r, o.range_max)
            dx,dy = math.cos(yaw+angle), math.sin(yaw+angle)
            for k in range(int(max(0., r-self.resolution)/self.resolution)):
                d = k*self.resolution
                cell=self.cell((x+dx*d,y+dy*d))
                self.hits.pop(cell, None);self.hit_points.pop(cell,None)
            if r < o.range_max-.02:
                point=(x+dx*r,y+dy*r)
                # Continuous checks retain every still-fresh endpoint, even
                # if another hit reuses its cell or a coarse free ray clears
                # that cell. No point is erased before its own 3s expiry.
                self.endpoint_history.append((point,o.sim_time))
                fresh.setdefault(self.cell(point),[]).append(point)
        for c in fresh:
            self.hits[c] = o.sim_time
            self.hit_points[c] = fresh[c]
        n = math.ceil(self.padding/self.resolution)
        offsets = [(dx,dy) for dx in range(-n,n+1) for dy in range(-n,n+1)
                   if math.hypot(dx,dy)*self.resolution <= self.padding+self.resolution*.71]
        self.blocked = {(c[0]+dx,c[1]+dy) for c in self.hits for dx,dy in offsets}
        self.scan_blocked = set(self.blocked)

    def continuous_segment_clear(self, start, end):
        """Check the WHOLE segment against original-radius scan discs/bounds.

        Grid-cell quantization is not an obstacle in continuous space. Unknown
        externally injected cells are never bypassed; static subclasses must
        additionally check their actual inflated fixed geometry.
        """
        if not self.has_scan or self.blocked != self.scan_blocked | getattr(self,'static',set()):return False
        if any(c not in self.hit_points for c in self.hits):return False
        a,b,c,d=self.bounds;p=self.padding
        if any(not (a+p<=q[0]<=b-p and c+p<=q[1]<=d-p) for q in (start,end)):return False
        dx,dy=end[0]-start[0],end[1]-start[1];length2=dx*dx+dy*dy
        for (x,y),_ in self.endpoint_history:
            u=clamp(((x-start[0])*dx+(y-start[1])*dy)/max(length2,1e-15),0.,1.)
            if math.hypot(x-start[0]-u*dx,y-start[1]-u*dy)<=p:return False
        return True

    def plan(self, start, goal):
        self.last_start_connector=None
        s,g = self.cell(start),self.cell(goal)
        a,b,c,d = self.bounds
        if not (a <= start[0] <= b and c <= start[1] <= d) or not self.free(g):return []
        starts=[s]
        continuous=not self.free(s)
        if continuous:
            # Virtual unquantized start -> nearby free grid nodes. No occupied
            # cell is unmarked, and all subsequent A* edges retain inflation
            # and diagonal corner checks. The connector itself is checked
            # continuously, not just at the two endpoints.
            starts=[(s[0]+dx,s[1]+dy) for dx in range(-2,3) for dy in range(-2,3)
                    if self.free((s[0]+dx,s[1]+dy)) and self.continuous_segment_clear(
                        start,self.center((s[0]+dx,s[1]+dy)))]
            if not starts:return []
        costs={q:(math.dist(start,self.center(q))/self.resolution if continuous else 0.) for q in starts}
        parents={q:None for q in starts}
        queue=[(cost+math.dist(q,g),cost,q) for q,cost in costs.items()];heapq.heapify(queue)
        while queue:
            _,cost,c = heapq.heappop(queue)
            if cost != costs.get(c):continue
            if c == g:
                path=[c]
                while parents[path[-1]] is not None:path.append(parents[path[-1]])
                path=[self.center(q) for q in reversed(path)]
                if continuous:self.last_start_connector=path[0];path.insert(0,tuple(start))
                return path
            for dx,dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
                n=(c[0]+dx,c[1]+dy)
                if not self.free(n):continue
                if dx and dy and (not self.free((c[0]+dx,c[1])) or not self.free((c[0],c[1]+dy))):continue
                nc=cost+math.hypot(dx,dy)
                if nc<costs.get(n,math.inf):
                    costs[n],parents[n]=nc,c
                    heapq.heappush(queue,(nc+math.dist(n,g),nc,n))
        return []


class NavigationBaseline:
    label = 'offline_sensor_astar_velocity_baseline'

    def __init__(self, bounds=(-10.,10.,-8.,8.), max_speed=1.3):
        self.bounds = bounds
        self.max_speed = max_speed
        self.intent = None
        self.reset(-1)

    def reset(self, episode):
        self.episode = episode
        self.grid = OccupancyGrid(self.bounds)
        self.metrics = NavMetrics()
        self.path = []
        self.last_plan = -math.inf
        self.last_time = None
        self.last_xy = None
        self.progress = deque()
        self.recover_until = -math.inf
        self.recovery_direction = (0.,0.)
        self.last_status = None
        self.last_velocity_target=(0.,0.)
        self.connector_target=None
        self.intent = None  # never carry a previous episode's goal forward

    def set_intent(self, intent):
        """Consume original repository JSON or NavigationIntent. Never call a model."""
        if isinstance(intent, dict):
            p = intent['target_point']
            intent = NavigationIntent(str(intent['behavior']), (float(p['x']),float(p['y'])),
                                      str(intent.get('reason','')))
        if not isinstance(intent, NavigationIntent) or not all(math.isfinite(v) for v in intent.target_point):
            raise ValueError('Invalid navigation intent')
        x,y = intent.target_point
        a,b,c,d = self.bounds
        if not (a <= x <= b and c <= y <= d):
            raise ValueError('Goal outside configured map bounds')
        changed = self.intent is None or intent.target_point != self.intent.target_point
        self.intent = intent
        if changed:
            self.path = []
            self.last_plan = -math.inf
            self.metrics.goal_reached = False
            self.progress.clear()
            self.connector_target=None

    def _event(self, o, kind, **data):
        self.metrics.events.append(dict(episode=o.episode,robot_id=o.robot_id,
                                       sim_time=o.sim_time,type=kind,source=self.label,**data))

    def _status(self, o, status):
        if status != self.last_status:
            self._event(o,'navigation_status',status=status)
            self.last_status = status

    def _clearance(self, o, direction):
        """Distance until padded footprint meets a sensed point in this corridor."""
        x,y = direction
        clearance = o.range_max
        for r,a in zip(o.ranges,o.angles):
            if not math.isfinite(r) or r <= 0 or r >= o.range_max-.02: continue
            px,py = r*math.cos(a+o.xy_yaw[2]),r*math.sin(a+o.xy_yaw[2])
            along,across = px*x+py*y,abs(px*y-py*x)
            if along > 0 and across < self.grid.padding:
                clearance = min(clearance, along-math.sqrt(self.grid.padding**2-across**2))
        return max(0.,clearance)

    def velocity(self, o):
        if not isinstance(o, NavObservation): o = NavObservation.from_observation(o)
        if o.episode != self.episode: self.reset(o.episode)
        if len(o.ranges) != len(o.angles): raise ValueError('Scan lengths differ')
        if not all(math.isfinite(v) for v in (*o.xy_yaw,*o.velocity_xy,o.sim_time,o.range_max)) or o.range_max <= 0:
            raise ValueError('Nonfinite or invalid odometry/time/range')
        if self.last_time is not None and o.sim_time < self.last_time:
            raise ValueError('Simulation time went backwards within episode')
        xy = o.xy_yaw[:2]
        if self.last_xy is not None:
            self.metrics.distance_travelled_m += math.dist(xy,self.last_xy)
        self.last_xy,self.last_time = xy,o.sim_time
        if not o.alive or self.intent is None:
            self._status(o,'disabled' if not o.alive else 'no_goal')
            return (0.,0.)
        if not o.ranges or not any(math.isfinite(r) and r>0 for r in o.ranges):
            self._status(o,'sensor_unavailable'); return (0.,0.)
        sensed = min((r-self.grid.padding for r in o.ranges if math.isfinite(r) and r>0), default=o.range_max)
        previous = self.metrics.min_observed_clearance_m
        self.metrics.min_observed_clearance_m = sensed if previous is None else min(previous,sensed)
        self.grid.update(o)
        goal = self.intent.target_point
        distance = math.dist(xy,goal)
        if distance < .24:
            if not self.metrics.goal_reached: self._event(o,'goal_reached',goal=list(goal))
            self.metrics.goal_reached = True
            self._status(o,'goal_reached'); return (0.,0.)
        if o.sim_time-self.last_plan >= .6 or not self.path or any(not self.grid.free(self.grid.cell(p)) for p in self.path[1:4]):
            self.path = self.grid.plan(xy,goal)
            self.connector_target=self.grid.last_start_connector
            self.last_plan = o.sim_time
            self.metrics.replans += 1
            self._event(o,'path_plan',success=bool(self.path),waypoints=len(self.path),goal=list(goal))
        if self.connector_target is not None and math.dist(xy,self.connector_target)>.04:
            # Do not skip this checked segment with the normal 0.32m waypoint
            # lookahead. Recheck against each fresh scan while traversing it.
            if not self.grid.continuous_segment_clear(xy,self.connector_target):
                self._status(o,'blocked_start_connector');return (0.,0.)
            distance=math.dist(xy,self.connector_target)
            direction=((self.connector_target[0]-xy[0])/distance,(self.connector_target[1]-xy[1])/distance)
            clearance=self._clearance(o,direction)
            speed=min(.4,distance*1.5,max(0.,clearance-.12)*1.8,math.sqrt(2*1.2*max(0.,clearance-.12)))
            self._status(o,'continuous_start_connector')
            return (direction[0]*speed,direction[1]*speed)
        self.connector_target=None
        while len(self.path)>1 and math.dist(xy,self.path[0])<.32: self.path.pop(0)
        self.progress.append((o.sim_time,xy))
        while self.progress and o.sim_time-self.progress[0][0]>2.5: self.progress.popleft()
        stuck = (len(self.progress)>1 and o.sim_time-self.progress[0][0]>=2.0
                 and math.dist(xy,self.progress[0][1])<.12)
        if stuck and o.sim_time >= self.recover_until:
            # Local escape uses only scan clearance. No teleport/reset of physics.
            directions = [(math.cos(k*math.pi/4),math.sin(k*math.pi/4)) for k in range(8)]
            # Respect the inflated map too: a low fixed obstacle may sit below
            # the range sensor plane. A recovery must not drive through it.
            safe = [d for d in directions if all(self.grid.free(self.grid.cell(
                (xy[0]+d[0]*step,xy[1]+d[1]*step))) for step in (.25,.5))]
            safe = [d for d in safe if self._clearance(o,d)>.15]
            if not safe:
                self._status(o,'blocked_no_safe_escape')
                return (0.,0.)
            self.recovery_direction = max(safe,key=lambda d:self._clearance(o,d))
            self.recover_until = o.sim_time+.8
            self.progress.clear()
            self.metrics.recovery_count += 1
            self._event(o,'stuck_recovery',duration_s=.8)
        if o.sim_time < self.recover_until:
            direction = self.recovery_direction
            speed = .4
            self._status(o,'recovering')
        elif self.path:
            p = self.path[0]
            length = math.dist(xy,p)
            direction = ((p[0]-xy[0])/max(length,1e-9),(p[1]-xy[1])/max(length,1e-9))
            speed = min(self.max_speed, distance*1.5)
            self._status(o,'tracking')
        else:
            self._status(o,'blocked'); return (0.,0.)
        clearance = self._clearance(o,direction)
        # Limited reaction/stopping horizon, conservatively assuming 1.2 m/s^2.
        speed = min(speed, max(0.,clearance-.12)*1.8, math.sqrt(2*1.2*max(0.,clearance-.12)))
        return (direction[0]*speed,direction[1]*speed)

    def act(self, o):
        """World velocity target -> bounded physical motor force, never qpos writes."""
        if not isinstance(o, NavObservation): o = NavObservation.from_observation(o)
        vx,vy = self.velocity(o)
        self.last_velocity_target=(vx,vy)
        # PD velocity servo plus harness viscous damping feedforward (8 N per m/s).
        fx = clamp(28*(vx-o.velocity_xy[0])+8*vx,-60.,60.)
        fy = clamp(28*(vy-o.velocity_xy[1])+8*vy,-60.,60.)
        return Command(force_x=fx,force_y=fy)
