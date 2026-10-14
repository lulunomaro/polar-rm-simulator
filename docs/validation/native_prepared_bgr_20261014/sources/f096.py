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
from ..telemetry import TimingLedger
from .camera_pixels import encode_camera_pixels

MAX_VIEWS=8
MAX_JPEG_BYTES=2*1024*1024
RAW_BASE64_CHUNK_BYTES=192*1024  # Divisible by three: padding only in final chunk.


def encode_raw_base64(raw):
    """Same bytes as one b64encode, without a frame-sized GIL-held C call.

    Allocate exactly the required output, plus one bounded encoded chunk.
    Yield between chunks; original post-encoding identity/deadline checks remain
    responsible for rejecting stopped/expired captures, never restamping them.
    """
    view=memoryview(raw)
    output=bytearray(4*((len(view)+2)//3));written=0
    for offset in range(0,len(view),RAW_BASE64_CHUNK_BYTES):
        part=base64.b64encode(view[offset:offset+RAW_BASE64_CHUNK_BYTES])
        output[written:written+len(part)]=part;written+=len(part)
        if offset+RAW_BASE64_CHUNK_BYTES<len(view):time.sleep(0)
    return output.decode('ascii')


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
        from OpenGL.GL import glGetString, GL_RENDERER, GL_VENDOR, GL_VERSION
        def gl_text(key):
            value=glGetString(key)
            return value.decode(errors='replace') if value else None
        self.identity=dict(renderer=gl_text(GL_RENDERER),vendor=gl_text(GL_VENDOR),version=gl_text(GL_VERSION))
        self.last_timings={}
    def render(self,capture):
        import numpy as np
        renderer=self.renderer;mujoco=self.mujoco
        started=time.monotonic();renderer.update_scene(capture.buffer,camera=capture.robot_id+'__aim')
        # Physical projectile spheres only. No target labels/boxes/aim overlays.
        for radius,position in capture.projectiles:
            scene=renderer.scene
            if scene.ngeom>=scene.maxgeom:break
            mujoco.mjv_initGeom(scene.geoms[scene.ngeom],mujoco.mjtGeom.mjGEOM_SPHERE,
                np.array([radius]*3),position,np.eye(3).ravel(),np.array([1,.8,.1,1],dtype=np.float32))
            scene.ngeom+=1
        scene_done=time.monotonic();ideal=renderer.render();readback_done=time.monotonic()
        rgb=self.warp.apply(ideal).copy();warp_done=time.monotonic()
        self.last_timings=dict(scene_update=scene_done-started,render_readback=readback_done-scene_done,
                              lens_warp=warp_done-readback_done)
        return rgb
    def close(self):self.renderer.close()


class CameraProvider:
    def __init__(self,sim,*,clock=time.perf_counter,total_fps=2.,max_frame_age_wall_s=2.5,
                 renderer_factory=MuJoCoCameraRenderer,max_views=MAX_VIEWS,
                 enable_native_pixels=False,native_pixels_hook=None,raw_base64_codec='stdlib_chunked'):
        import mujoco
        import numpy as np
        from ..camera_profile import SourceCameraProfile
        if not 0<total_fps<=15 or not .1<=max_frame_age_wall_s<=5:raise ValueError('Invalid camera timing bounds')
        if type(max_views) is not int or not 1<=max_views<=MAX_VIEWS:raise ValueError('Invalid camera view limit')
        if type(enable_native_pixels) is not bool or (native_pixels_hook is not None and not callable(native_pixels_hook)):
            raise ValueError('Invalid local native pixel experiment')
        self.enable_native_pixels=enable_native_pixels;self.native_pixels_hook=native_pixels_hook
        if type(raw_base64_codec) is not str or raw_base64_codec not in ('stdlib_chunked','pybase64_1_5_1'):
            raise ValueError('Unknown local raw base64 codec')
        self.raw_base64_codec=raw_base64_codec;self._raw_encoder=None
        self._raw_encoder_metadata=dict(codec='stdlib_chunked',version=None,module=__name__,
            function='encode_raw_base64',extension_path=None,extension_sha256=None)
        if raw_base64_codec!='stdlib_chunked':
            # One verified native-code binding at local setup. The raw-only
            # factory selects this same cached binding by known enum, never a
            # freely supplied callable or a per-frame import/hash scan.
            from .base64_codec import load_raw_encoder,raw_encoder_metadata
            self._raw_encoder=load_raw_encoder(raw_base64_codec)
            self._raw_encoder_metadata=raw_encoder_metadata(raw_base64_codec)
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
        self.pending=OrderedDict();self.cache={};self.native_cache={};self.display_cache={};self.display_pending=OrderedDict()
        self.display_wake=threading.Event();self.display_thread=None;self.display_error=None;self.display_running=False
        self.desired={};self.episode=None;self.sequence=0
        self.next_capture=0.;self.cursor=0;self.authority=None;self.error=None;self.thread=None
        self.dropped=0;self.rendered=0;self.running=False;self.max_pending_seen=0;self.capture_count=0
        self.raw_published=0;self.display_dropped=0;self.max_display_pending_seen=0;self.renderer_identity=None
        self.timings=TimingLedger(('snapshot_copy','renderer_init','render_queue_wait','render_total',
                                  'scene_update','render_readback','lens_warp','raw_encode','jpeg_encode',
                                  'capture_to_raw','capture_to_display','capture_to_private_pixels'))

    def start(self):
        with self.lock:
            if self.thread is not None or self.stopped.is_set():return
            self.display_thread=threading.Thread(target=self._display_loop,name='sim-v2-display-encoder',daemon=True)
            self.display_thread.start()
            self.thread=threading.Thread(target=self._loop,name='sim-v2-camera',daemon=True);self.thread.start()

    def _reset_locked(self,episode):
        self.episode=episode;self.cache.clear();self.native_cache.clear();self.display_cache.clear();self.display_pending.clear()
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
            for rid in list(self.native_cache):
                if not self.native_cache[rid]['capture'].consumers.intersection(self.desired.get(rid,())):
                    self.native_cache.pop(rid)
            for values in (self.display_cache,self.display_pending):
                for rid in list(values):
                    if rid not in self.desired:values.pop(rid)
            if self.error is not None or not self.desired or now<self.next_capture:return
            ordered=[r for r in self.ids if r in self.desired]
            rid=ordered[self.cursor%len(ordered)];self.cursor+=1
            old=self.pending.pop(rid,None)
            if old is not None:self.free.append(old.buffer);self.dropped+=1
            if not self.free:self.dropped+=1;return
            data=self.free.pop();copy_started=self.clock();mujoco.mj_copyData(data,self.model,sim.data)
            self.timings.record('snapshot_copy',self.clock()-copy_started)
            self.sequence+=1
            q=data.qpos[list(self._q[rid])];v=data.qvel[list(self._v[rid])];xy=data.xpos[self._body[rid]][:2]
            own=dict(own_qpos_at_capture=q.tolist(),own_qvel_at_capture=v.tolist(),
                own_odom_at_capture=[float(xy[0]),float(xy[1]),float(q[2])],own_odom_velocity_at_capture=v[:3].tolist())
            cap=Capture(rid,int(sim.episode),self.sequence,float(data.time),now,self.desired[rid],data,own,
                tuple((float(p.radius),p.position.copy()) for p in sim.projectiles))
            self.pending[rid]=cap;self.capture_count+=1;self.max_pending_seen=max(self.max_pending_seen,len(self.pending))
            self.next_capture=now+1/self.total_fps
        self.wake.set();self.start()

    def _encode(self,cap,rgb,*,raw_bytes=None):
        """Raw sensor serialization only. Display compression has its own worker."""
        import numpy as np
        p=self.profile
        if rgb.dtype!=np.uint8 or rgb.shape!=(p.height,p.width,3):raise ValueError('Renderer image contract mismatch')
        if raw_bytes is None:raw_bytes=rgb.tobytes()
        payload,pixel_token=encode_camera_pixels(raw_bytes,robot_id=cap.robot_id,episode=cap.episode,
            frame_id=cap.frame_seq,capture_sim_time=cap.sim_time,encoding='rgb8',width=p.width,height=p.height,stride_bytes=p.width*3,
            raw_base64_codec=getattr(self,'raw_base64_codec','stdlib_chunked'))
        camera=dict(available=True,reason='available',frame_id=cap.frame_seq,capture_sim_time=cap.sim_time,
            **cap.own,image=dict(encoding='rgb8',width=p.width,height=p.height,stride_bytes=p.width*3,
                data_base64=payload),
            intrinsics=self.calibrations[cap.robot_id]['intrinsics'],extrinsics=self.calibrations[cap.robot_id]['extrinsics'],
            provenance='simulated_raw_camera')
        return dict(camera=camera,capture=replace(cap,buffer=None,projectiles=()),encoded_wall=self.clock(),pixel_token=pixel_token)

    def _pixel_event(self,event,cap,*,wall_time=None,reason=None):
        if self.native_pixels_hook is not None:
            row=dict(event=event,robot_id=cap.robot_id,episode=cap.episode,
                frame_id=cap.frame_seq,capture_wall=cap.wall_time,capture_sim_time=cap.sim_time,
                wall_time=self.clock() if wall_time is None else wall_time,wall_clock='provider_monotonic')
            if reason is not None:row['reason']=reason
            self.native_pixels_hook(row)

    def _publish_native_pixels(self,cap,rgb):
        """One actual immutable copy, before any public base64 encoding."""
        import numpy as np
        from .native_camera_snapshot import mint_native_snapshot
        p=self.profile
        if rgb.dtype!=np.uint8 or rgb.shape!=(p.height,p.width,3):raise ValueError('Renderer image contract mismatch')
        raw=rgb.tobytes()
        consumers=frozenset(c for c in cap.consumers if len(c)==5 and c[:3]==('adapter',cap.robot_id,'aim'))
        if consumers:
            calibration=self.calibrations[cap.robot_id]
            pixels=mint_native_snapshot(raw,robot_id=cap.robot_id,episode=cap.episode,frame_id=cap.frame_seq,
                capture_wall=cap.wall_time,capture_sim_time=cap.sim_time,consumers=consumers,
                width=p.width,height=p.height,stride_bytes=p.width*3,own=cap.own,
                intrinsics=calibration['intrinsics'],extrinsics=calibration['extrinsics'])
            detached=replace(cap,buffer=None,projectiles=(),consumers=consumers)
            with self.lock:
                observed_wall=self.clock()
                revoked=(self.stopped.is_set() or self.error is not None or cap.episode!=self.episode
                    or not consumers.intersection(self.desired.get(cap.robot_id,())))
                expired=not 0<=observed_wall-cap.wall_time<=min(self.ttl,.08)
                published=not revoked and not expired
                if published:
                    self.native_cache[cap.robot_id]=dict(capture=detached,pixels=pixels)
                    # Stamp the actual publication linearization point. The
                    # physics thread may enqueue before this hook is delivered.
                    published_wall=self.clock()
                elif self.stopped.is_set():reason='runtime_stopped'
                elif self.error is not None:reason='camera_fault'
                elif cap.episode!=self.episode:reason='episode_changed'
                else:reason='capture_revoked' if revoked else 'native_80ms_expired'
            if published:
                self.timings.record('capture_to_private_pixels',published_wall-cap.wall_time)
                self._pixel_event('private_pixels_published',cap,wall_time=published_wall)
            else:self._pixel_event('private_publish_rejected',cap,wall_time=observed_wall,reason=reason)
        else:self._pixel_event('private_publish_rejected',cap,reason='no_native_consumer')
        return raw

    def _encode_display(self,cap,rgb):
        from PIL import Image
        buffer=io.BytesIO();Image.fromarray(rgb).save(buffer,format='JPEG',quality=85)
        jpeg=buffer.getvalue()
        if len(jpeg)>MAX_JPEG_BYTES:raise ValueError('Display JPEG exceeds bounded capacity')
        return dict(jpeg=base64.b64encode(jpeg).decode(),
            capture=replace(cap,buffer=None,projectiles=()),encoded_wall=self.clock())

    def _current_locked(self,cap):
        return (not self.stopped.is_set() and self.error is None and cap.episode==self.episode
                and 0<=self.clock()-cap.wall_time<=self.ttl
                and bool(cap.consumers.intersection(self.desired.get(cap.robot_id,()))))

    def _display_loop(self):
        try:
            while not self.stopped.is_set():
                with self.lock:
                    job=self.display_pending.popitem(last=False)[1] if self.display_pending else None
                    self.display_running=job is not None
                if job is None:self.display_wake.wait(.05);self.display_wake.clear();continue
                cap,rgb=job
                try:
                    with self.lock:current=self._current_locked(cap)
                    if not current:
                        with self.lock:self.display_dropped+=1
                        continue
                    started=self.clock();result=self._encode_display(cap,rgb)
                    self.timings.record('jpeg_encode',self.clock()-started)
                    with self.lock:
                        if self._current_locked(cap):
                            self.display_cache[cap.robot_id]=result;self.rendered+=1
                            self.timings.record('capture_to_display',self.clock()-cap.wall_time)
                        else:self.display_dropped+=1
                finally:
                    with self.lock:self.display_running=False
        except BaseException as exc:
            # A display codec failure cannot invalidate the already published sensor.
            with self.lock:self.display_error=type(exc).__name__;self.display_cache.clear()
        finally:
            with self.lock:self.display_pending.clear();self.display_running=False

    def _loop(self):
        renderer=None
        try:
            started=self.clock();renderer=self.renderer_factory(self.model,self.profile)
            self.timings.record('renderer_init',self.clock()-started)
            with self.lock:self.renderer_identity=getattr(renderer,'identity',None)
            while not self.stopped.is_set():
                with self.lock:
                    cap=self.pending.popitem(last=False)[1] if self.pending else None
                    self.running=cap is not None
                if cap is None:self.wake.wait(.05);self.wake.clear();continue
                try:
                    self.timings.record('render_queue_wait',self.clock()-cap.wall_time)
                    if self.clock()-cap.wall_time>self.ttl:result=None
                    else:
                        started=self.clock();rgb=renderer.render(cap)
                        self.timings.record('render_total',self.clock()-started)
                        for stage,duration in getattr(renderer,'last_timings',{}).items():
                            self.timings.record(stage,duration)
                        started=self.clock()
                        if self.enable_native_pixels:
                            raw_bytes=self._publish_native_pixels(cap,rgb)
                            result=self._encode(cap,rgb,raw_bytes=raw_bytes)
                        else:result=self._encode(cap,rgb)
                        self.timings.record('raw_encode',self.clock()-started)
                        if self.enable_native_pixels:self._pixel_event('public_base64_complete',cap,wall_time=result['encoded_wall'])
                    with self.lock:
                        queue_display=False
                        if result is not None and self._current_locked(cap):
                            self.cache[cap.robot_id]=result;self.raw_published+=1
                            self.timings.record('capture_to_raw',self.clock()-cap.wall_time)
                            queue_display=self.display_error is None
                        else:self.dropped+=1
                    if queue_display:
                        # No image copying or percentile computation under the authority lock.
                        display_rgb=rgb.copy()
                        with self.lock:
                            if self._current_locked(cap) and self.display_error is None:
                                if cap.robot_id in self.display_pending:self.display_dropped+=1
                                # Detach from renderer-owned memory before the next render.
                                self.display_pending[cap.robot_id]=(result['capture'],display_rgb)
                                self.max_display_pending_seen=max(self.max_display_pending_seen,len(self.display_pending))
                                self.display_wake.set()
                            else:self.display_dropped+=1
                finally:
                    with self.lock:self.free.append(cap.buffer);self.running=False
        except BaseException as exc:
            with self.lock:self.error=type(exc).__name__;self.cache.clear();self.native_cache.clear();self.display_cache.clear()
        finally:
            if renderer is not None:
                try:renderer.close()
                except BaseException as exc:
                    with self.lock:self.error=type(exc).__name__;self.cache.clear();self.native_cache.clear();self.display_cache.clear()
            with self.lock:
                for cap in self.pending.values():self.free.append(cap.buffer)
                self.pending.clear();self.running=False

    def _get_locked(self,rid,episode,consumer,*,max_wall_age=None,sim_time=None,max_sim_age=None,display=False,native=False):
        if self.error:return None,'camera_error:'+self.error
        if self.stopped.is_set():return None,'runtime_stopped'
        if episode!=self.episode:return None,'episode_changed'
        if display and self.display_error:return None,'display_error:'+self.display_error
        result=(self.native_cache if native else (self.display_cache if display else self.cache)).get(rid)
        if result is None:return None,'waiting_for_display_encode' if display and rid in self.cache else 'waiting_for_camera'
        cap=result['capture']
        if (cap.robot_id!=rid or cap.episode!=episode or consumer not in cap.consumers
            or (getattr(self,'enable_native_pixels',False) and consumer not in self.desired.get(rid,()))):return None,'capture_generation_mismatch'
        age=self.clock()-cap.wall_time
        if not 0<=age<=min(self.ttl,max_wall_age if max_wall_age is not None else self.ttl):return None,'camera_expired'
        if sim_time is not None and not 0<=sim_time-cap.sim_time<=max_sim_age:return None,'camera_sim_expired'
        return result,'available'

    def sensor_identity(self,rid,episode,consumer,sim_time,ttl):
        """Cheap private scheduling identity with the exact sensor admission gates.

        Three original scalar timestamps only: no raw pixels, calibration, own
        state or deep copy. A cached exposure never receives a new timestamp.
        """
        with self.lock:
            value,_=self._get_locked(rid,episode,consumer,max_wall_age=ttl,sim_time=sim_time,max_sim_age=ttl)
            if value is None:return None
            cap=value['capture']
            return cap.frame_seq,cap.wall_time,cap.sim_time

    def sensor_packet(self,rid,episode,consumer,sim_time,ttl):
        """Atomic sensor plus trusted exposure budget; never refresh an old age.

        Budget is internal scheduling metadata, not an algorithm/world-truth DTO.
        """
        with self.lock:
            value,reason=self._get_locked(rid,episode,consumer,max_wall_age=ttl,sim_time=sim_time,max_sim_age=ttl)
            if value is None:return dict(camera=dict(available=False,reason=reason),budget=None,pixel_token=None)
            cap=value['capture']
            return dict(camera=copy.deepcopy(value['camera']),budget=dict(
                robot_id=rid,episode=episode,frame_id=cap.frame_seq,
                capture_wall=cap.wall_time,capture_sim_time=cap.sim_time,
                wall_deadline=cap.wall_time+ttl,sim_deadline=cap.sim_time+ttl),pixel_token=value.get('pixel_token'))

    def sensor_camera(self,rid,episode,consumer,sim_time,ttl):
        return self.sensor_packet(rid,episode,consumer,sim_time,ttl)['camera']

    def native_sensor_identity(self,rid,episode,consumer,sim_time,ttl):
        if not self.enable_native_pixels:return None
        with self.lock:
            value,_=self._get_locked(rid,episode,consumer,max_wall_age=min(ttl,.08),sim_time=sim_time,max_sim_age=min(ttl,.08),native=True)
            if value is None:return None
            cap=value['capture'];return cap.frame_seq,cap.wall_time,cap.sim_time

    def native_sensor_packet(self,rid,episode,consumer,sim_time,ttl):
        if not self.enable_native_pixels:return dict(pixels=None,budget=None)
        with self.lock:
            ttl=min(ttl,.08,self.ttl)
            value,_=self._get_locked(rid,episode,consumer,max_wall_age=ttl,sim_time=sim_time,max_sim_age=ttl,native=True)
            if value is None:return dict(pixels=None,budget=None)
            cap=value['capture']
            return dict(pixels=value['pixels'],budget=dict(robot_id=rid,episode=episode,frame_id=cap.frame_seq,
                capture_wall=cap.wall_time,capture_sim_time=cap.sim_time,wall_deadline=cap.wall_time+ttl,sim_deadline=cap.sim_time+ttl))

    def native_capture_valid(self,rid,episode,consumer,budget,sim_time):
        """Revoke pending/private outputs on fault, release and generation change."""
        with self.lock:
            return bool(self.enable_native_pixels and not self.error and not self.stopped.is_set()
                and episode==self.episode and consumer in self.desired.get(rid,())
                and budget is not None and budget['robot_id']==rid and budget['episode']==episode
                and budget['capture_wall']<=self.clock()<min(budget['wall_deadline'],budget['capture_wall']+.08)
                and budget['capture_sim_time']<=sim_time<=min(budget['sim_deadline'],budget['capture_sim_time']+.08))

    def sensor_capture_valid(self,rid,episode,consumer,budget,sim_time):
        """Cheap public result guard, including faults after packet delivery."""
        with self.lock:
            return bool(not self.error and not self.stopped.is_set() and episode==self.episode
                and consumer in self.desired.get(rid,()) and budget is not None
                and budget['capture_wall']<=self.clock()<min(budget['wall_deadline'],budget['capture_wall']+self.ttl)
                and budget['capture_sim_time']<=sim_time<=budget['sim_deadline'])

    def display_frame(self,rid,episode,consumer,watch_epoch):
        with self.lock:
            value,reason=self._get_locked(rid,episode,consumer,display=True)
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
            max_renderer_threads=1,max_display_encoder_threads=1,max_pending=self.max_views,max_data_buffers=self.max_views+1,
            max_display_pending=self.max_views,max_display_rgb_bytes=(self.max_views+2)*self.profile.width*self.profile.height*3,
            max_cached_raw_bytes=self.max_views*self.profile.width*self.profile.height*3,
            native_pixels_enabled=self.enable_native_pixels,native_cached=len(self.native_cache),
            raw_base64_codec=self.raw_base64_codec,
            max_native_cached_rgb_bytes=self.max_views*self.profile.width*self.profile.height*3 if self.enable_native_pixels else 0,
            max_cached_raw_base64_bytes=self.max_views*((self.profile.width*self.profile.height*3+2)//3*4),
            max_cached_jpeg_bytes=self.max_views*MAX_JPEG_BYTES,
            pending=len(self.pending),cached=len(self.cache),display_cached=len(self.display_cache),
            display_pending=len(self.display_pending),display_running=self.display_running,
            max_display_pending_seen=self.max_display_pending_seen,raw_published=self.raw_published,
            running=self.running,rendered=self.rendered,display_dropped=self.display_dropped,display_error=self.display_error,
            renderer_identity=copy.deepcopy(self.renderer_identity),timing_report_available=True,
            dropped=self.dropped,error=self.error,calibration_resolution_association='ASSUMED; absent from source YAML')

    def timing_report(self):
        """Read distributions from a diagnostic thread, outside physics/HTTP status."""
        return self.timings.snapshot()

    def fault(self,reason):
        with self.lock:self.error=reason;self.cache.clear();self.native_cache.clear();self.display_cache.clear();self.display_pending.clear()
        self.stopped.set();self.wake.set();self.display_wake.set()

    def stop(self):
        # No join in the physics/HTTP path. A stuck driver occupies one daemon only.
        self.stopped.set();self.wake.set();self.display_wake.set()
        with self.lock:self.cache.clear();self.desired.clear();self._reset_locked(self.episode)

    def wait_closed(self,timeout=2.):
        deadline=time.monotonic()+timeout
        for thread in (self.thread,self.display_thread):
            if thread:thread.join(max(0.,deadline-time.monotonic()))
        return all(thread is None or not thread.is_alive() for thread in (self.thread,self.display_thread))
