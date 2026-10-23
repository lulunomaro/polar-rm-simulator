"""Shared six-robot MuJoCo world. Physics truth is confined to world/referee APIs."""
from dataclasses import dataclass
import numpy as np
import mujoco
from .match_model import make_match_xml,ROSTER,SPAWNS
from .contracts import Observation,Command
from .competition_judge import MatchJudge
from .ballistics import swept_rotating_box_toi, interpolate_rotation

@dataclass
class MatchProjectile:
    uid: str
    owner: str
    caliber: str
    position: np.ndarray
    velocity: np.ndarray
    born: float
    radius: float

class MatchSimulation:
    def __init__(self,render=True,*,model_xml=None,roster=None,spawns=None,spectator_effects=None):
        self.spectator_effects=spectator_effects
        roster=ROSTER if roster is None else roster
        self.spawns=SPAWNS if spawns is None else spawns
        self.model=mujoco.MjModel.from_xml_string(make_match_xml() if model_xml is None else model_xml)
        self.data=mujoco.MjData(self.model)
        self.renderer=mujoco.Renderer(self.model,240,320) if render else None
        self.robot_ids=[r[0] for r in roster]
        self.teams={r:t for r,t,_ in roster};self.roles={r:p for r,_,p in roster}
        joints=['base_x','base_y','base_yaw','gimbal_yaw','gimbal_pitch']
        actuators=['drive_x','drive_y','drive_yaw','aim_yaw','aim_pitch']
        self.qindices={r:[self.model.jnt_qposadr[self.model.joint(r+'__'+n).id] for n in joints] for r in self.robot_ids}
        self.vindices={r:[self.model.jnt_dofadr[self.model.joint(r+'__'+n).id] for n in joints] for r in self.robot_ids}
        self.aindices={r:[self.model.actuator(r+'__'+n).id for n in actuators] for r in self.robot_ids}
        self.body_ids={r:self.model.body(r+'__robot').id for r in self.robot_ids}
        unsupported=[self.model.geom(g).name for g in range(self.model.ngeom)
            if self.model.geom_contype[g] and self.model.geom_type[g]!=mujoco.mjtGeom.mjGEOM_BOX]
        if unsupported:
            raise NotImplementedError('Projectile collision currently requires physical boxes; unsupported: '+str(unsupported))
        self.colliders=np.array([g for g in range(self.model.ngeom) if self.model.geom_type[g]==mujoco.mjtGeom.mjGEOM_BOX and self.model.geom_contype[g]],dtype=int)
        self.geom_owners={g:next((r for r in self.robot_ids if self.model.geom(g).name.startswith(r+'__')),None) for g in self.colliders}
        self.episode=-1;self.reset()

    @property
    def time(self):return float(self.data.time)

    def reset(self):
        self.episode+=1;mujoco.mj_resetData(self.model,self.data)
        for rid in self.robot_ids:self.data.qpos[self.qindices[rid][2]]=self.spawns[rid][2]
        mujoco.mj_forward(self.model,self.data)
        self.judge=MatchJudge(episode=self.episode);self.projectiles=[];self.projectile_counter=0
        if self.spectator_effects:self.spectator_effects.reset()
        self.paused=False;self.phase='running';self.emergency_stop=False
        self.commands={r:Command() for r in self.robot_ids}
        self.last_fired={r:-10. for r in self.robot_ids};self.contact_events=[]
        self._update_zones()

    def _update_zones(self):
        control=set();supply=set()
        for rid in self.robot_ids:
            x,y=self.data.xpos[self.body_ids[rid]][:2]
            if abs(x)<=1.5 and abs(y)<=1.5:control.add(rid)
            if self.teams[rid]=='red' and -6<=x<=-4.5 and 2<=y<=4:supply.add(rid)
            if self.teams[rid]=='blue' and 4.5<=x<=6 and -4<=y<=-2:supply.add(rid)
        self.judge.update_zone_presence(control=control,supply=supply)

    def image(self,camera='arena_overview',*,show_effects=False):
        if self.renderer is None:raise RuntimeError('Camera rendering disabled')
        if show_effects and camera in {r+'__aim' for r in self.robot_ids}:
            raise ValueError('Spectator auxiliary overlays are forbidden on actor camera output')
        self.renderer.update_scene(self.data,camera=camera);self.draw_projectiles(self.renderer.scene)
        if show_effects and self.spectator_effects:self.spectator_effects.draw(self.renderer.scene)
        return self.renderer.render().copy()

    def draw_projectiles(self,scene):
        for p in self.projectiles:
            if scene.ngeom>=scene.maxgeom:break
            mujoco.mjv_initGeom(scene.geoms[scene.ngeom],mujoco.mjtGeom.mjGEOM_SPHERE,
                np.array([p.radius]*3),p.position,np.eye(3).ravel(),np.array([1,.8,.1,1],dtype=np.float32))
            scene.ngeom+=1

    def scan(self,rid):
        origin=self.data.xpos[self.body_ids[rid]].copy();origin[2]=.25
        yaw=float(self.data.qpos[self.qindices[rid][2]])
        angles=np.linspace(-np.pi,np.pi,65)[:-1]+yaw
        # Keep the original 64 directions, physical group0/static geometry and
        # own-body exclusion, but cross the Python/C boundary only once. Repeated
        # mj_ray calls release/reacquire the GIL between every ray under load.
        directions=np.array([[np.cos(a),np.sin(a),0.] for a in angles],dtype=np.float64)
        ids=np.empty(64,dtype=np.int32);distances=np.empty(64,dtype=np.float64)
        # Infinite query cutoff preserves original nearest-hit semantics before
        # the existing 8m sensor saturation, including large distant geoms.
        mujoco.mj_multiRay(self.model,self.data,origin,directions.ravel(),
            np.array([1,0,0,0,0,0],dtype=np.uint8),True,self.body_ids[rid],
            ids,distances,None,64,float('inf'))
        return tuple(float(min(distance,8.)) if distance>=0 else 8. for distance in distances)

    def observe(self,rid,include_rgb=True,include_ranges=True):
        if rid not in self.robot_ids:raise KeyError(rid)
        q=self.data.qpos[self.qindices[rid]];v=self.data.qvel[self.vindices[rid]]
        xyz=self.data.xpos[self.body_ids[rid]];robot=self.judge.robots[rid]
        fovy=float(self.model.cam_fovy[self.model.camera(rid+'__aim').id])
        return Observation(self.episode,self.time,self.image(rid+'__aim') if include_rgb else np.empty((0,0,3),dtype=np.uint8),fovy,
            tuple(float(x) for x in q),tuple(float(x) for x in v),int(robot.hp),int(robot.ammo),
            robot_id=rid,odom_xyyaw=(float(xyz[0]),float(xyz[1]),float(q[2])),
            odom_vxyw=tuple(float(x) for x in v[:3]),ranges=self.scan(rid) if include_ranges else (),
            range_angles=tuple(np.linspace(-np.pi,np.pi,65)[:-1]),
            own_heat=float(robot.heat),own_weak=bool(robot.weak),team=self.teams[rid],role=self.roles[rid],
            remaining_seconds=max(0.,300-self.time),own_max_hp=float(robot.max_hp),
            match_phase='finished' if self.judge.terminal else ('paused' if self.paused else self.phase),
            emergency_stop=self.emergency_stop)

    def set_phase(self,phase):
        if phase not in ('preparing','countdown','running','paused','finished'):
            raise ValueError('Unknown match phase')
        if (self.judge.terminal or self.phase=='finished') and phase!='finished':
            raise ValueError('Reset the episode before restarting a finished match')
        self.phase=phase
        self.paused=phase=='paused'
        self.commands={r:Command() for r in self.robot_ids}
        self.data.ctrl[:]=0

    def _fire(self,rid):
        # Provisional mechanical feed rates, not a competition-rule assertion.
        interval=1. if self.roles[rid]=='hero' else 1/6
        if self.time-self.last_fired[rid]<interval-1e-9:return
        caliber='42mm' if self.roles[rid]=='hero' else '17mm'
        speed=12. if caliber=='42mm' else 22.5
        uid=f'{self.episode}:{self.projectile_counter}'
        if not self.judge.fire(rid,uid,self.time,muzzle_speed=speed):return
        self.projectile_counter+=1;self.last_fired[rid]=self.time
        site=self.model.site(rid+'__muzzle').id
        direction=self.data.site_xmat[site].reshape(3,3)[:,0]
        jacp=np.zeros((3,self.model.nv));jacr=np.zeros_like(jacp)
        mujoco.mj_jacSite(self.model,self.data,jacp,jacr,site)
        self.projectiles.append(MatchProjectile(uid,rid,caliber,self.data.site_xpos[site].copy(),
            speed*direction+jacp@self.data.qvel,self.time,.02125 if caliber=='42mm' else .0084))

    def step(self,commands=None,*,command_guard=None,integration_clock=None):
        if integration_clock is not None:self.last_integration_timing=None
        if self.paused or self.judge.terminal or self.phase!='running' or self.emergency_stop:
            self.commands={r:Command() for r in self.robot_ids};self.data.ctrl[:]=0
            return
        if commands:
            if set(commands)-set(self.robot_ids):raise ValueError('Unknown robot command')
            self.commands.update(commands)
        self._update_zones()
        for rid in self.robot_ids:
            c=self.commands[rid]
            # Trusted authority hook, never supplied to an algorithm. Final lease/
            # exposure gate at actual actuator consumption, after zone processing.
            if command_guard is not None:
                c=command_guard(rid,c,'actuator');self.commands[rid]=c
            values=[c.force_x,c.force_y,c.yaw_torque,c.gimbal_yaw,c.gimbal_pitch]
            if not np.isfinite(values).all():raise ValueError('Nonfinite command')
            if not self.judge.robots[rid].alive:values=[0,0,0,0,0]
            self.data.ctrl[self.aindices[rid]]=values
            if c.fire and command_guard is None:self._fire(rid)
        if self.spectator_effects:self.spectator_effects.update(self.time,self.projectiles,self.contact_events)
        before=self.data.geom_xpos.copy();rot0=self.data.geom_xmat.copy()
        dt=self.model.opt.timestep
        if command_guard is not None:
            # Recheck after geometry bookkeeping, immediately before integration.
            # No new fire is generated here; this may only revoke prepared input.
            for rid in self.robot_ids:
                c=command_guard(rid,self.commands[rid],'integration');self.commands[rid]=c
                values=[c.force_x,c.force_y,c.yaw_torque,c.gimbal_yaw,c.gimbal_pitch]
                if not np.isfinite(values).all():raise ValueError('Nonfinite guarded command')
                self.data.ctrl[self.aindices[rid]]=values if self.judge.robots[rid].alive else [0,0,0,0,0]
        integration_start=integration_clock() if integration_clock is not None else None
        if command_guard is not None and integration_start is not None:
            # One uniform entry sample is the logical latching instant for all
            # vehicles. Revoke at this known time, rather than only logging a
            # clock gap after the earlier per-car checks. Python is not hard RT.
            for rid in self.robot_ids:
                c=command_guard(rid,self.commands[rid],'integration_entry',integration_start)
                self.commands[rid]=c
                values=[c.force_x,c.force_y,c.yaw_torque,c.gimbal_yaw,c.gimbal_pitch]
                if not np.isfinite(values).all():raise ValueError('Nonfinite entry command')
                self.data.ctrl[self.aindices[rid]]=values if self.judge.robots[rid].alive else [0,0,0,0,0]
        if command_guard is not None:
            # Guarded network inputs must not spend ammo or spawn a projectile
            # before the final lease/window checks. Fire is a separate discrete
            # consumption point, with a fresh guard immediately before _fire.
            for rid in self.robot_ids:
                if not self.commands[rid].fire:continue
                c=command_guard(rid,self.commands[rid],'fire');self.commands[rid]=c
                values=[c.force_x,c.force_y,c.yaw_torque,c.gimbal_yaw,c.gimbal_pitch]
                if not np.isfinite(values).all():raise ValueError('Nonfinite fire-guarded command')
                self.data.ctrl[self.aindices[rid]]=values if self.judge.robots[rid].alive else [0,0,0,0,0]
                if c.fire:self._fire(rid)
        integration_call=integration_clock() if integration_clock is not None else None
        deadlines=getattr(command_guard,'integration_deadlines',{})
        # Entry receipts can take time to prepare. If an original active input
        # expires before mj_step, revoke through the SAME authority guard and
        # actual Command writer. No waiting, refreshed input or extra fire.
        # At most 3 channels per robot can expire under the authority lock.
        rounds=0
        while integration_call is not None and deadlines:
            expired=[rid for rid,deadline in deadlines.items() if integration_call>=deadline]
            if not expired:break
            rounds+=1
            if rounds>3*len(self.robot_ids):raise RuntimeError('Integration expiry guard made no progress')
            for rid in expired:
                c=command_guard(rid,self.commands[rid],'integration_expired')
                self.commands[rid]=c
                values=[c.force_x,c.force_y,c.yaw_torque,c.gimbal_yaw,c.gimbal_pitch]
                if not np.isfinite(values).all():raise ValueError('Nonfinite expired-input command')
                self.data.ctrl[self.aindices[rid]]=values if self.judge.robots[rid].alive else [0,0,0,0,0]
            integration_call=integration_clock()
        mujoco.mj_step(self.model,self.data);mujoco.mj_forward(self.model,self.data)
        if integration_clock is not None:self.last_integration_timing=dict(integration_start_wall=integration_start,integration_call_wall=integration_call,post_step_wall=integration_clock())
        self._advance_projectiles(before,rot0,dt)
        self.judge.tick(self.time)
        if self.spectator_effects:self.spectator_effects.update(self.time,self.projectiles,self.contact_events)

    def _advance_projectiles(self,before,rot0,dt):
        # No projectile means no swept collision query or hit to account for.
        # Spawning/authority/cooldown checks still happen at the original points.
        if not self.projectiles:return
        ids=self.colliders;centers=self.data.geom_xpos[ids]
        matrices=self.data.geom_xmat[ids].reshape(-1,3,3)
        extents=np.einsum('nij,nj->ni',np.abs(matrices),self.model.geom_size[ids])
        previous_matrices=rot0[ids].reshape(-1,3,3)
        ext0=np.einsum('nij,nj->ni',np.abs(previous_matrices),self.model.geom_size[ids])
        lo=np.minimum(before[ids]-ext0,centers-extents);hi=np.maximum(before[ids]+ext0,centers+extents)
        # Rotation between endpoints can bulge; conservative angular radius pad.
        traces=np.einsum('nij,nij->n',previous_matrices,matrices)
        angles=np.arccos(np.clip((traces-1)/2,-1,1))
        pads=(angles*np.linalg.norm(self.model.geom_size[ids],axis=1))[:,None]
        lo-=pads;hi+=pads
        alive=[];hit_batch=[];hit_event_indices=[]
        for p in self.projectiles:
            start=p.position;end=start+p.velocity*dt+np.array([0,0,-4.905*dt*dt])
            mask=np.all(np.maximum(start,end)+p.radius>=lo,axis=1)&np.all(np.minimum(start,end)-p.radius<=hi,axis=1)
            impacts=[]
            for index in np.flatnonzero(mask):
                g=int(ids[index])
                if self.geom_owners[g]==p.owner:continue
                t=swept_rotating_box_toi(start,end,before[g],self.data.geom_xpos[g],rot0[g].reshape(3,3),
                    self.data.geom_xmat[g].reshape(3,3),self.model.geom_size[g],p.radius)
                if t is not None:impacts.append((t,g))
            if impacts:
                t,g=min(impacts);point=start+(end-start)*t
                owner=self.geom_owners[g];name=self.model.geom(g).name
                speed=0.;valid=False
                if owner is not None and '__armor_' in name:
                    r,omega=interpolate_rotation(rot0[g].reshape(3,3),self.data.geom_xmat[g].reshape(3,3),t)
                    center=before[g]+(self.data.geom_xpos[g]-before[g])*t
                    local=r.T@(point-center)
                    closest=np.clip(local,-self.model.geom_size[g],self.model.geom_size[g]);normal=local-closest
                    if np.linalg.norm(normal)<1e-9:
                        axis=np.argmin(self.model.geom_size[g]-np.abs(local));normal=np.zeros(3);normal[axis]=1 if local[axis]>=0 else -1
                    normal=r@(normal/np.linalg.norm(normal))
                    # Contact point velocity includes rigid-body angular motion.
                    surface=point-normal*p.radius
                    point_velocity=(self.data.geom_xpos[g]-before[g])/dt+np.cross(omega/dt,surface-center)
                    relative=p.velocity+np.array([0,0,-9.81*dt*t])-point_velocity
                    speed=max(0.,float(-relative@normal))
                hit_batch.append((self.time-dt+t*dt,dict(projectile_uid=p.uid,shooter_id=p.owner,target_id=owner,armor_id=name if '__armor_' in name else None,normal_speed=speed,caliber=p.caliber)))
                hit_event_indices.append(len(self.contact_events))
                self.contact_events.append(dict(projectile=p.uid,owner=p.owner,geom=name,sim_time=self.time-dt+t*dt,
                    position=point.tolist(),normal_speed=speed,damage_applied=bool(valid)))
            elif self.time-p.born<3. and np.linalg.norm(end[:2])<20:
                p.position=end;p.velocity[2]-=9.81*dt;alive.append(p)
        if hit_batch:
            pending=sorted(zip(hit_batch,hit_event_indices),key=lambda item:item[0][0])
            while pending:
                when=pending[0][0][0];group=[];indices=[]
                while pending and abs(pending[0][0][0]-when)<1e-10:
                    (_,hit),index=pending.pop(0);group.append(hit);indices.append(index)
                results=self.judge.apply_hit_batch(group,when,episode=self.episode)
                for index,result in zip(indices,results):self.contact_events[index]["damage_applied"]=bool(result)
        self.projectiles=alive

    def close(self):
        if self.renderer:self.renderer.close()
