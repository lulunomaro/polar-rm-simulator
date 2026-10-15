"""Read-only observer metrics. This object is never passed to robot policies."""
import math


class MatchEvidence:
    def __init__(self,sim):
        self.dt=float(sim.model.opt.timestep)
        self.spawn={r:tuple(sim.observe(r,False,False).odom_xyyaw[:2]) for r in sim.robot_ids}
        self.robots={r:dict(first_motion_s=None,first_control_entry_s=None,
            control_presence_s=0.,alive_s=0.,distance_m=0.,minimum_wall_distance_m=None) for r in sim.robot_ids}
        self.last_xy=dict(self.spawn)
        self.control_owner_s={'red':0.,'blue':0.,'none':0.}
        self.active_contacts={}
        self.contacts=[]
        self.frames=[]

    def tick(self,sim):
        for rid in sim.robot_ids:
            o=sim.observe(rid,False,False);xy=o.odom_xyyaw[:2];m=self.robots[rid]
            if m['first_motion_s'] is None and math.dist(xy,self.spawn[rid])>=.02:
                m['first_motion_s']=sim.time
            m['distance_m']+=math.dist(xy,self.last_xy[rid]);self.last_xy[rid]=xy
            if abs(xy[0])<=1.5 and abs(xy[1])<=1.5 and o.own_hp>0 and not o.own_weak:
                if m['first_control_entry_s'] is None:m['first_control_entry_s']=sim.time
                m['control_presence_s']+=self.dt
            if o.own_hp>0:m['alive_s']+=self.dt
            edge=min(6-abs(xy[0]),4-abs(xy[1]))
            if m['minimum_wall_distance_m'] is None or edge<m['minimum_wall_distance_m']:
                m['minimum_wall_distance_m']=edge
        self.control_owner_s[sim.judge.control_owner or 'none']+=self.dt
        now=set()
        for c in sim.data.contact[:sim.data.ncon]:
            names=tuple(sorted(sim.model.geom(int(g)).name for g in (c.geom1,c.geom2)))
            if 'arena_floor' in names:continue
            now.add(names)
            if names not in self.active_contacts:
                event=dict(start_s=sim.time,end_s=sim.time,geoms=list(names),min_distance_m=float(c.dist))
                self.contacts.append(event);self.active_contacts[names]=event
            event=self.active_contacts[names];event['end_s']=sim.time
            event['min_distance_m']=min(event['min_distance_m'],float(c.dist))
        for names in set(self.active_contacts)-now:del self.active_contacts[names]

    def snapshot(self,sim,nav):
        robots={}
        for rid,m in self.robots.items():
            p=nav[rid]
            robots[rid]={**m,'opening_intent_s':p.opening.started_at if sim.roles[rid]=='sentry' else None,
                'opening_arrival_s':p.opening.arrived_at if sim.roles[rid]=='sentry' else None,
                'last_mode':p.mode,'current_goal_reached':p.metrics.goal_reached,
                'replans':p.metrics.replans,'recoveries':p.metrics.recovery_count,
                'original_rule_calls':p.original_rule.calls,'llm_calls':0}
        return dict(robots=robots,control_owner_s=self.control_owner_s,chassis_contact_episodes=len(self.contacts),
            sensor_model='ideal own odometry + anonymous 64-ray ranges; RGB only for pixel aim/tactical contacts',
            nav_backend='sensor_grid_astar_velocity_baseline_NOT_ROS2_Nav2',
            tactical_backend='exact_upstream_rule_decide_RMUL_config_NOT_LLM',
            upstream_commit='6ff95524df1a6aadce7697e366ab32ac5e9bbafc',
            spawn_positions_unchanged=True,official_forced_center_rush=False,
            timebase='simulation seconds',cad_dynamics_calibrated=False)
