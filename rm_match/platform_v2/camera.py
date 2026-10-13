"""Bounded camera pipeline. Only the authority copies live data; one worker owns GL.

Render jobs and caches are keyed by robot and carry capture-time consumer tokens.
The raw algorithm camera and JPEG display DTO are separate. No simulator or world
truth crosses the algorithm boundary. This is an immutable-model lifecycle: an
entire provider must be replaced for a new scene, never mutate its model in place.
"""
from __future__ import annotations
import base64
from collections import OrderedDict
import copy
from dataclasses import dataclass, replace
import hashlib
import io
import json
import threading
import time

MAX_VIEWS=8
MAX_JPEG_BYTES=2*1024*1024


def camera_model_xml():
    """Existing role_v23 optics and K/D; resize is not a new calibration."""
    import xml.etree.ElementTree as ET
    from ..camera_profile import SourceCameraProfile
    from ..match_model import make_match_xml
    p=SourceCameraProfile(overscan_pixels=64)
    root=ET.fromstring(make_match_xml('role_v23'))
    visual=root.find('visual/global')
    visual.set('offwidth',str(p.render_width));visual.set('offheight',str(p.render_height))
    for node in root.findall('.//camera'):
        if node.get('name','').endswith('__aim'):node.set('fovy',str(p.ideal_fovy_degrees))
    return ET.tostring(root,encoding='unicode')


@dataclass(frozen=True)
class Capture:
    robot_id: str
    episode: int
    frame_seq: int
    sim_time: float
    wall_time: float
    consumers: frozenset
    buffer: object
    own: dict
    projectiles: tuple


class MuJoCoCameraRenderer:
    """Construct, use and destroy all GL state on one worker thread."""
    def __init__(self,model,profile):
        import mujoco
        from ..camera_profile import SourceLensWarp
        self.mujoco=mujoco;self.warp=SourceLensWarp(profile)
        self.renderer=mujoco.Renderer(model,height=profile.render_height,width=profile.render_width)
    def render(self,capture):
        import numpy as np
        renderer=self.renderer;mujoco=self.mujoco
        renderer.update_scene(capture.buffer,camera=capture.robot_id+'__aim')
        # Physical projectile spheres only. No target labels/boxes/aim overlays.
        for radius,position in capture.projectiles:
            scene=renderer.scene
            if scene.ngeom>=scene.maxgeom:break
            mujoco.mjv_initGeom(scene.geoms[scene.ngeom],mujoco.mjtGeom.mjGEOM_SPHERE,
                np.array([radius]*3),position,np.eye(3).ravel(),np.array([1,.8,.1,1],dtype=np.float32))
            scene.ngeom+=1
        return self.warp.apply(renderer.render()).copy()
    def close(self):self.renderer.close()


class CameraProvider:
    def __init__(self,sim,*,clock=time.monotonic,total_fps=2.,max_frame_age_wall_s=2.5,
                 renderer_factory=MuJoCoCameraRenderer,max_views=MAX_VIEWS):
        import mujoco
        import numpy as np
        from ..camera_profile import SourceCameraProfile
        if not 0<total_fps<=15 or not .1<=max_frame_age_wall_s<=5:raise ValueError('Invalid camera timing bounds')
        if type(max_views) is not int or not 1<=max_views<=MAX_VIEWS:raise ValueError('Invalid camera view limit')
        if sim.renderer is not None:raise ValueError('Camera provider requires render=False live simulation')
        self.model=sim.model;self.clock=clock;self.total_fps=total_fps;self.ttl=max_frame_age_wall_s
        self.profile=SourceCameraProfile(overscan_pixels=64)
        self.ids=tuple(sim.robot_ids);self.max_views=min(max_views,len(self.ids));self.renderer_factory=renderer_factory
        self._q={r:tuple(sim.qindices[r]) for r in self.ids};self._v={r:tuple(sim.vindices[r]) for r in self.ids}
        self._body=dict(sim.body_ids);self.calibrations={}
        p=self.profile
        for rid in self.ids:
            camera=self.model.camera(rid+'__aim').id
            if self.model.cam_bodyid[camera]!=self.model.body(rid+'__pitch').id:raise ValueError('Camera parent mismatch')
            if abs(float(self.model.cam_fovy[camera])-p.ideal_fovy_degrees)>1e-7:raise ValueError('Camera optical profile mismatch')
            rot=np.empty(9);mujoco.mju_quat2Mat(rot,self.model.cam_quat[camera])
            optical=rot.reshape(3,3)@np.diag([1.,-1.,-1.]);q=np.empty(4);mujoco.mju_mat2Quat(q,optical.ravel())
            ext=dict(parent_frame='gimbal_link',translation_m=self.model.cam_pos[camera].tolist(),rotation_xyzw=[*q[1:].tolist(),float(q[0])])
            intr=dict(fx=p.fx,fy=p.fy,cx=p.cx,cy=p.cy,distortion_model='brown_conrady_5',distortion=list(p.distortion))
            digest=hashlib.sha256(json.dumps(dict(robot_id=rid,camera_name=rid+'__aim',intrinsics=intr,extrinsics=ext,profile=p.manifest()),sort_keys=True).encode()).hexdigest()
            ext['calibration_id']='role_v23:'+rid+':'+digest
            self.calibrations[rid]=dict(intrinsics=intr,extrinsics=ext,profile=p.manifest())
        self.lock=threading.Lock();self.wake=threading.Event();self.stopped=threading.Event()
        # At most max_views pending snapshots plus one worker-owned snapshot.
        self.free=[mujoco.MjData(self.model) for _ in range(self.max_views+1)]
        self.pending=OrderedDict();self.cache={};self.desired={};self.episode=None;self.sequence=0
        self.next_capture=0.;self.cursor=0;self.authority=None;self.error=None;self.thread=None
        self.dropped=0;self.rendered=0;self.running=False;self.max_pending_seen=0;self.capture_count=0

    def start(self):
        with self.lock:
            if self.thread is not None or self.stopped.is_set():return
            self.thread=threading.Thread(target=self._loop,name='sim-v2-camera',daemon=True);self.thread.start()

    def _reset_locked(self,episode):
        self.episode=episode;self.cache.clear()
        for cap in self.pending.values():self.free.append(cap.buffer)
        self.pending.clear()

    def capture_from_authority(self,sim,desired):
        """Called only between authority steps, never from an HTTP/GL thread."""
        import mujoco
        current=threading.get_ident()
        if self.authority is None:self.authority=current
        if current!=self.authority:raise RuntimeError('Camera live copy outside physics authority')
        if sim.model is not self.model:raise RuntimeError('Scene replacement requires a new camera provider')
        now=self.clock()
        # Small lock only covers metadata and mj_copyData, never rendering/encode.
        with self.lock:
            if self.stopped.is_set():return
            if self.episode!=sim.episode:self._reset_locked(sim.episode)
            self.desired={r:frozenset(c) for r,c in desired.items() if c and r in self.ids}
            if len(self.desired)>self.max_views:raise ValueError('Camera view capacity exceeded')
            for rid in list(self.pending):
                if rid not in self.desired:self.free.append(self.pending.pop(rid).buffer);self.dropped+=1
            for rid in list(self.cache):
                if rid not in self.desired:self.cache.pop(rid)
            if self.error is not None or not self.desired or now<self.next_capture:return
            ordered=[r for r in self.ids if r in self.desired]
            rid=ordered[self.cursor%len(ordered)];self.cursor+=1
            old=self.pending.pop(rid,None)
            if old is not None:self.free.append(old.buffer);self.dropped+=1
            if not self.free:self.dropped+=1;return
            data=self.free.pop();mujoco.mj_copyData(data,self.model,sim.data)
            self.sequence+=1
            q=data.qpos[list(self._q[rid])];v=data.qvel[list(self._v[rid])];xy=data.xpos[self._body[rid]][:2]
            own=dict(own_qpos_at_capture=q.tolist(),own_qvel_at_capture=v.tolist(),
                own_odom_at_capture=[float(xy[0]),float(xy[1]),float(q[2])],own_odom_velocity_at_capture=v[:3].tolist())
            cap=Capture(rid,int(sim.episode),self.sequence,float(data.time),now,self.desired[rid],data,own,
                tuple((float(p.radius),p.position.copy()) for p in sim.projectiles))
            self.pending[rid]=cap;self.capture_count+=1;self.max_pending_seen=max(self.max_pending_seen,len(self.pending))
            self.next_capture=now+1/self.total_fps
        self.wake.set();self.start()

    def _encode(self,cap,rgb):
        import numpy as np
        from PIL import Image
        p=self.profile
        if rgb.dtype!=np.uint8 or rgb.shape!=(p.height,p.width,3):raise ValueError('Renderer image contract mismatch')
        camera=dict(available=True,reason='available',frame_id=cap.frame_seq,capture_sim_time=cap.sim_time,
            **cap.own,image=dict(encoding='rgb8',width=p.width,height=p.height,stride_bytes=p.width*3,
                data_base64=base64.b64encode(rgb.tobytes()).decode()),
            intrinsics=self.calibrations[cap.robot_id]['intrinsics'],extrinsics=self.calibrations[cap.robot_id]['extrinsics'],
            provenance='simulated_raw_camera')
        buffer=io.BytesIO();Image.fromarray(rgb).save(buffer,format='JPEG',quality=85)
        jpeg=buffer.getvalue()
        if len(jpeg)>MAX_JPEG_BYTES:raise ValueError('Display JPEG exceeds bounded capacity')
        return dict(camera=camera,jpeg=base64.b64encode(jpeg).decode(),
            capture=replace(cap,buffer=None,projectiles=()),encoded_wall=self.clock())

    def _loop(self):
        renderer=None
        try:
            renderer=self.renderer_factory(self.model,self.profile)
            while not self.stopped.is_set():
                with self.lock:
                    cap=self.pending.popitem(last=False)[1] if self.pending else None
                    self.running=cap is not None
                if cap is None:self.wake.wait(.05);self.wake.clear();continue
                try:
                    if self.clock()-cap.wall_time>self.ttl:result=None
                    else:result=self._encode(cap,renderer.render(cap))
                    with self.lock:
                        if (result is not None and not self.stopped.is_set() and cap.episode==self.episode
                            and self.clock()-cap.wall_time<=self.ttl
                            and cap.consumers.intersection(self.desired.get(cap.robot_id,()))):
                            self.cache[cap.robot_id]=result;self.rendered+=1
                        else:self.dropped+=1
                finally:
                    with self.lock:self.free.append(cap.buffer);self.running=False
        except BaseException as exc:
            with self.lock:self.error=type(exc).__name__;self.cache.clear()
        finally:
            if renderer is not None:
                try:renderer.close()
                except BaseException as exc:
                    with self.lock:self.error=type(exc).__name__;self.cache.clear()
            with self.lock:
                for cap in self.pending.values():self.free.append(cap.buffer)
                self.pending.clear();self.running=False

    def _get_locked(self,rid,episode,consumer,*,max_wall_age=None,sim_time=None,max_sim_age=None):
        if self.error:return None,'camera_error:'+self.error
        if self.stopped.is_set():return None,'runtime_stopped'
        if episode!=self.episode:return None,'episode_changed'
        result=self.cache.get(rid)
        if result is None:return None,'waiting_for_camera'
        cap=result['capture']
        if cap.robot_id!=rid or cap.episode!=episode or consumer not in cap.consumers:return None,'capture_generation_mismatch'
        age=self.clock()-cap.wall_time
        if not 0<=age<=min(self.ttl,max_wall_age if max_wall_age is not None else self.ttl):return None,'camera_expired'
        if sim_time is not None and not 0<=sim_time-cap.sim_time<=max_sim_age:return None,'camera_sim_expired'
        return result,'available'

    def sensor_packet(self,rid,episode,consumer,sim_time,ttl):
        """Atomic sensor plus trusted exposure budget; never refresh an old age.

        Budget is internal scheduling metadata, not an algorithm/world-truth DTO.
        """
        with self.lock:
            value,reason=self._get_locked(rid,episode,consumer,max_wall_age=ttl,sim_time=sim_time,max_sim_age=ttl)
            if value is None:return dict(camera=dict(available=False,reason=reason),budget=None)
            cap=value['capture']
            return dict(camera=copy.deepcopy(value['camera']),budget=dict(
                robot_id=rid,episode=episode,frame_id=cap.frame_seq,
                capture_wall=cap.wall_time,capture_sim_time=cap.sim_time,
                wall_deadline=cap.wall_time+ttl,sim_deadline=cap.sim_time+ttl))

    def sensor_camera(self,rid,episode,consumer,sim_time,ttl):
        return self.sensor_packet(rid,episode,consumer,sim_time,ttl)['camera']

    def display_frame(self,rid,episode,consumer,watch_epoch):
        with self.lock:
            value,reason=self._get_locked(rid,episode,consumer)
            result=dict(available=value is not None,reason=reason,robot_id=rid,episode=episode,watch_epoch=watch_epoch,
                max_frame_age_wall_s=self.ttl,source='simulated_raw_camera_display_jpeg',algorithm_input=False)
            if value:
                cap=value['capture'];p=self.profile
                result.update(frame_seq=cap.frame_seq,capture_sim_time=cap.sim_time,capture_wall_monotonic=cap.wall_time,
                    encode_completed_wall_monotonic=value['encoded_wall'],age_wall_s=self.clock()-cap.wall_time,
                    full_frame=True,**copy.deepcopy(cap.own),calibration=copy.deepcopy(self.calibrations[rid]),
                    image=dict(encoding='jpeg',width=p.width,height=p.height,data_base64=value['jpeg']))
            return result

    def status(self):
        with self.lock:return dict(available=not self.stopped.is_set() and self.error is None,
            reason='camera_error:'+self.error if self.error else ('runtime_stopped' if self.stopped.is_set() else 'enabled'),
            total_fps_limit=self.total_fps,max_frame_age_wall_s=self.ttl,max_views=self.max_views,
            max_renderer_threads=1,max_pending=self.max_views,max_data_buffers=self.max_views+1,
            max_cached_raw_bytes=self.max_views*self.profile.width*self.profile.height*3,
            max_cached_raw_base64_bytes=self.max_views*((self.profile.width*self.profile.height*3+2)//3*4),
            max_cached_jpeg_bytes=self.max_views*MAX_JPEG_BYTES,
            pending=len(self.pending),cached=len(self.cache),running=self.running,rendered=self.rendered,
            dropped=self.dropped,error=self.error,calibration_resolution_association='ASSUMED; absent from source YAML')

    def fault(self,reason):
        with self.lock:self.error=reason;self.cache.clear()
        self.stopped.set();self.wake.set()

    def stop(self):
        # No join in the physics/HTTP path. A stuck driver occupies one daemon only.
        self.stopped.set();self.wake.set()
        with self.lock:self.cache.clear();self.desired.clear();self._reset_locked(self.episode)

    def wait_closed(self,timeout=2.):
        thread=self.thread
        if thread:thread.join(timeout)
        return thread is None or not thread.is_alive()
