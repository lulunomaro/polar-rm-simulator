import os
os.environ.setdefault('MUJOCO_GL','egl');os.environ.setdefault('EGL_PLATFORM','surfaceless');os.environ.setdefault('OMP_NUM_THREADS','1')
import sys,json,time,hashlib,base64,io
from pathlib import Path
from dataclasses import replace
import xml.etree.ElementTree as ET
import numpy as np
import cv2
from PIL import Image
import mujoco
from rm_match.platform_v2.camera import camera_model_xml
from rm_match.match_engine import MatchSimulation
from rm_match.camera_profile import SourceCameraProfile,SourceLensWarp
from rm_match.platform_v2.contracts import build_observation,validate_observation
from rm_match.platform_v2.runtime import json_copy
out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=False)
scene=Path(sys.argv[2]);snap=min(json.loads(scene.read_text()),key=lambda s:abs(s['t']-18.))
records=[]
for width in (1440,640):
 p0=SourceCameraProfile(overscan_pixels=64);s=width/p0.width
 p=replace(p0,width=width,height=round(p0.height*s),fx=p0.fx*s,fy=p0.fy*s,cx=(p0.cx+.5)*s-.5,cy=(p0.cy+.5)*s-.5,overscan_pixels=round(64*s))
 root=ET.fromstring(camera_model_xml());v=root.find('visual/global');v.set('offwidth',str(p.render_width));v.set('offheight',str(p.render_height))
 for n in root.findall('.//camera'):
  if n.get('name','').endswith('__aim'):n.set('fovy',str(p.ideal_fovy_degrees))
 sim=MatchSimulation(render=False,model_xml=ET.tostring(root,encoding='unicode'));sim.data.qpos[:]=snap['qpos'];sim.data.qvel[:]=0;mujoco.mj_forward(sim.model,sim.data)
 t=time.monotonic();warp=SourceLensWarp(p);warp_init=time.monotonic()-t
 t=time.monotonic();r=mujoco.Renderer(sim.model,height=p.render_height,width=p.render_width);render_init=time.monotonic()-t
 from OpenGL.GL import glGetString,GL_RENDERER
 identity=glGetString(GL_RENDERER).decode()
 for i in range(4):
  t=time.monotonic();r.update_scene(sim.data,camera='red_sentry__aim');scene_s=time.monotonic()-t
  t=time.monotonic();ideal=r.render();render_s=time.monotonic()-t
  t=time.monotonic();rgb=warp.apply(ideal);warp_s=time.monotonic()-t
  t=time.monotonic();native=cv2.resize(rgb,(1440,1080),interpolation=cv2.INTER_LINEAR) if width!=1440 else rgb;up_s=time.monotonic()-t
  t=time.monotonic();b64=base64.b64encode(native.tobytes()).decode();b64_s=time.monotonic()-t
  t=time.monotonic();buf=io.BytesIO();Image.fromarray(native).save(buf,format='JPEG',quality=85);jpeg_s=time.monotonic()-t
  # Actual current own observation is sufficient for representative serialization cost.
  o=build_observation(sim.observe('red_sentry',include_rgb=False,include_ranges=True),binding_epoch=1,observed_seq=i,wall_deadline=time.monotonic()+.2)
  o['sensors']['camera']=dict(available=True,reason='available',frame_id=i,capture_sim_time=0.,own_qpos_at_capture=list(map(float,sim.data.qpos[sim.qindices['red_sentry']])),own_qvel_at_capture=[0.]*5,own_odom_at_capture=[0.]*3,own_odom_velocity_at_capture=[0.]*3,image=dict(encoding='rgb8',width=1440,height=1080,stride_bytes=4320,data_base64=b64),intrinsics=dict(fx=p0.fx,fy=p0.fy,cx=p0.cx,cy=p0.cy,distortion_model='brown_conrady_5',distortion=list(p0.distortion)),extrinsics=dict(parent_frame='gimbal_link',translation_m=[.24,0,.06],rotation_xyzw=[-.5,.5,-.5,.5],calibration_id='profile-probe'),provenance='simulated_raw_camera')
  t=time.monotonic();validate_observation(o);validate_s=time.monotonic()-t
  t=time.monotonic();json_copy(o);json_copy_s=time.monotonic()-t
  rec=dict(width=width,frame=i,renderer=identity,warp_init_s=warp_init,renderer_init_s=render_init,scene_s=scene_s,render_s=render_s,warp_s=warp_s,upsample_s=up_s,base64_s=b64_s,jpeg_s=jpeg_s,validate_s=validate_s,json_copy_s=json_copy_s,raw_sha256=hashlib.sha256(native.tobytes()).hexdigest(),render_sampling_profile=p.manifest())
  records.append(rec);print(json.dumps({k:v for k,v in rec.items() if k!='render_sampling_profile'}),flush=True)
  if i==3:Image.fromarray(native).save(out/f'render-{width}.png')
 r.close();sim.close()
(out/'results.json').write_text(json.dumps(dict(scope='render_only_profile_not_live_tracking',scene_sha256=hashlib.sha256(scene.read_bytes()).hexdigest(),records=records),indent=2))
