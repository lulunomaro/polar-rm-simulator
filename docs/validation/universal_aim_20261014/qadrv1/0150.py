from pathlib import Path
import numpy as np
import mujoco
from .contracts import Observation, Command
from .ballistics import Projectile, sphere_box_toi
from .judge import TestJudge

class Simulation:
    def __init__(self, render=True, occluder=True):
        xml = Path(__file__).with_name('harness.xml').read_text()
        if not occluder:
            xml = '\n'.join(x for x in xml.splitlines() if 'name="occluder"' not in x)
        self.model = mujoco.MjModel.from_xml_string(xml)
        self.data = mujoco.MjData(self.model)
        self.renderer = mujoco.Renderer(self.model, 240, 320) if render else None
        self.episode = -1
        self.reset()

    def reset(self):
        self.episode += 1
        mujoco.mj_resetData(self.model, self.data)
        mujoco.mj_forward(self.model, self.data)
        self.judge = TestJudge()
        self.projectiles = []
        self.shot_counter = 0
        self.paused = False
        self.command = Command()

    @property
    def time(self): return float(self.data.time)

    def image(self, camera='aim'):
        if self.renderer is None: raise RuntimeError('Rendering disabled')
        self.renderer.update_scene(self.data, camera=camera)
        self.draw_projectiles(self.renderer.scene)
        return self.renderer.render().copy()

    def draw_projectiles(self, scene):
        for projectile in self.projectiles:
            if scene.ngeom >= scene.maxgeom: break
            mujoco.mjv_initGeom(scene.geoms[scene.ngeom],mujoco.mjtGeom.mjGEOM_SPHERE,
                np.array([projectile.radius]*3),projectile.position,np.eye(3).reshape(9),
                np.array([1.,.8,.1,1.],dtype=np.float32))
            scene.ngeom+=1

    def observe(self, include_rgb=True):
        return Observation(self.episode, self.time, self.image() if include_rgb else np.empty((0,0,3),dtype=np.uint8), 50.,
            tuple(self.data.qpos[:5]), tuple(self.data.qvel[:5]), 200, self.judge.ammo,
            odom_xyyaw=(float(self.data.qpos[0]),float(self.data.qpos[1]-1.8),float(self.data.qpos[2])),
            odom_vxyw=tuple(self.data.qvel[:3]), ranges=self.scan(),
            range_angles=tuple(np.linspace(-np.pi,np.pi,65)[:-1]))

    def scan(self):
        # Ideal 2-D range sensor at chassis height. No geom IDs exposed.
        position=self.data.xpos[self.model.body('robot').id].copy()
        position[2]=.25
        angles=np.linspace(-np.pi,np.pi,65)[:-1]+self.data.qpos[2]
        ranges=[]
        for angle in angles:
            direction=np.array([np.cos(angle),np.sin(angle),0.])
            geom_id=np.array([-1],dtype=np.int32)
            distance=mujoco.mj_ray(self.model,self.data,position,direction,None,1,
                self.model.body('robot').id,geom_id)
            ranges.append(float(min(distance,8.)) if distance>=0 else 8.)
        return tuple(ranges)

    def fire(self):
        if self.paused or not self.judge.can_fire(self.time): return None
        uid = f'{self.episode}:{self.shot_counter}'
        if not self.judge.fired(uid, self.time): return None
        self.shot_counter += 1
        site = self.model.site('muzzle').id
        direction = self.data.site_xmat[site].reshape(3,3)[:,0]
        # Includes muzzle translational velocity from chassis/gimbal motion.
        jacp = np.zeros((3,self.model.nv)); jacr = np.zeros_like(jacp)
        mujoco.mj_jacSite(self.model,self.data,jacp,jacr,site)
        velocity = direction*22.5 + jacp @ self.data.qvel
        self.projectiles.append(Projectile(uid,self.data.site_xpos[site].copy(),velocity,self.time))
        return uid

    def step(self, command=None, target_motion=0.):
        if self.paused: return
        if command is not None: self.command = command
        c = self.command
        values = [c.force_x,c.force_y,c.yaw_torque,c.gimbal_yaw,c.gimbal_pitch,target_motion]
        if not np.isfinite(values).all(): raise ValueError('Nonfinite command')
        self.data.ctrl[:] = values
        if c.fire: self.fire()
        before = self.data.geom_xpos.copy()
        dt = self.model.opt.timestep
        mujoco.mj_step(self.model,self.data)
        # Forward synchronizes world geometry to the newly integrated qpos.
        mujoco.mj_forward(self.model,self.data)
        remaining = []
        colliders = [self.model.geom(n).id for n in ['target_body','target_armor','backwall']]
        occluder = mujoco.mj_name2id(self.model,mujoco.mjtObj.mjOBJ_GEOM,'occluder')
        if occluder >= 0: colliders.append(occluder)
        for p in self.projectiles:
            start = p.position.copy()
            end = start+p.velocity*dt+np.array([0.,0.,-4.905*dt*dt])
            contacts = []
            for g in colliders:
                toi = sphere_box_toi(start,end,before[g],self.data.geom_xpos[g],
                    self.data.geom_xmat[g].reshape(3,3),self.model.geom_size[g],p.radius)
                if toi is not None: contacts.append((toi,self.model.geom(g).name))
            if end[2] <= p.radius:
                t = max(0.,(start[2]-p.radius)/(start[2]-end[2])) if start[2]!=end[2] else 0.
                contacts.append((t,'floor'))
            if contacts:
                t, geom = min(contacts)
                self.judge.impact(p.uid,geom,self.time-dt+t*dt,start+(end-start)*t)
            elif self.time-p.born < 3.:
                p.position=end; p.velocity[2]-=9.81*dt; remaining.append(p)
        self.projectiles=remaining

    def close(self):
        if self.renderer: self.renderer.close()
