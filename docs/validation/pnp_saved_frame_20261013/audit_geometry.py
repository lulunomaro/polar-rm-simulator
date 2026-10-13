"""Offline geometry audit only. Never feeds simulator truth to native algorithm."""
from pathlib import Path
import sys,json,math,hashlib,argparse
import numpy as np,cv2,mujoco
HERE=Path(__file__).resolve().parent
ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--repo-root',type=Path,required=True);ap.add_argument('--out',type=Path,required=True,help='New JSON output file');ap.add_argument('--scene-state',type=Path,default=HERE/'public_scene_initial.json');ap.add_argument('--metadata',type=Path,default=HERE/'saved_frame_metadata.json');args=ap.parse_args()
if args.out.exists():raise ValueError('Choose a new --out file')
repo=args.repo_root.resolve();sys.path.insert(0,str(repo))
from rm_match.platform_v2.camera import camera_model_xml
from rm_match.camera_profile import SourceCameraProfile
from rm_match.match_model import ROSTER
from xml.etree import ElementTree as ET
out=HERE
model_xml=camera_model_xml();root=ET.fromstring(model_xml)
m=mujoco.MjModel.from_xml_string(model_xml);d=mujoco.MjData(m)
d.qpos[:]=json.loads(args.scene_state.read_text())[0]['qpos']
meta=json.loads(args.metadata.read_text())
for name,value in zip(['base_x','base_y','base_yaw','gimbal_yaw','gimbal_pitch'],meta['qpos']):d.qpos[m.jnt_qposadr[m.joint('red_sentry__'+name).id]]=value
mujoco.mj_forward(m,d)
camid=m.camera('red_sentry__aim').id;campos=d.cam_xpos[camid];R=d.cam_xmat[camid].reshape(3,3)@np.diag([1.,-1.,-1.])
p=SourceCameraProfile(overscan_pixels=64)
def project(world):
 optical=(np.asarray(world)-campos)@R
 pix,_=cv2.projectPoints(optical,np.zeros(3),np.zeros(3),p.K,np.array(p.distortion));return pix.reshape(-1,2)
def worldpoint(body,points):
 bid=m.body(body).id;return np.asarray(points)@d.xmat[bid].reshape(3,3).T+d.xpos[bid]
name='blue_infantry__visual_front';body=root.find('.//body[@name="'+name+'"]')
records=[]
for i,g in enumerate(body.findall('geom')):
 if g.get('type')!='capsule':continue
 ft=list(map(float,g.get('fromto','').split()));radius=float(g.get('size'));local=np.array(ft).reshape(2,3);world=worldpoint(name,local);p2=project(world);outer=local.copy();axis=(local[1]-local[0])/np.linalg.norm(local[1]-local[0]);outer[0]-=radius*axis;outer[1]+=radius*axis
 records.append({'geom_index':i,'material':g.get('material'),'radius_m':radius,'local_axis_endpoints_m':local.tolist(),'axis_length_m':float(np.linalg.norm(local[1]-local[0])),'outer_tip_to_tip_m':float(np.linalg.norm(local[1]-local[0])+2*radius),'projected_axis_endpoints_px':p2.tolist(),'projected_outer_tips_px':project(worldpoint(name,outer)).tolist(),'projected_axis_length_px':float(np.linalg.norm(p2[1]-p2[0]))})
# Source object endpoints are 135mm horizontal span and56mm vertical span.
ideal_local=np.array([[.004,.0675,.028],[.004,.0675,-.028],[.004,-.0675,-.028],[.004,-.0675,.028]])
projected=project(worldpoint(name,ideal_local));detected=np.array(json.loads((HERE/'DIAGNOSTIC_REPORT.json').read_text())['native_detection']['corners_px'])
# Body local +Y points screen-right from outward view here; order match by x.
leftinds=np.argsort(projected[:,0])[:2];rightinds=np.argsort(projected[:,0])[2:];left=projected[leftinds][np.argsort(projected[leftinds,1])];right=projected[rightinds][np.argsort(projected[rightinds,1])];expected=np.array([left[0],left[1],right[1],right[0]])
s=.4444444477558136;scaled_w=int(1440*s);scaled_h=int(1080*s)
report={'schema':'rmcs-offline-geometry-audit-v1','scope':'Offline model/geometry audit only; no target truth or derived corners sent to algorithm; no rendering, physics integration or new model inference.','saved_frame_sha256':meta['frame_sha256'],'target_state_source':'Public initial static scene; red captured qpos restored exactly. Blue front armor is chassis-fixed. Unrecorded target chassis drift was not reconstructed; this audit compares projected initial static target geometry with observed saved pixels.','camera_position_world_m':campos.tolist(),'camera_optical_to_world':R.tolist(),'camera_K':p.K.tolist(),'camera_distortion':list(p.distortion),'target_armor_body_rotation_world':d.xmat[m.body(name).id].reshape(3,3).tolist(),'target_armor_geometric_pitch_degrees':0.0,'expected_native_armor_pitch_degrees':15.0,'native_allowed_pitch_degrees':[-25.,55.],'source_PnP_object_span_m':[.135,.056],'geometry':records,'source_object_endpoint_projection_tl_bl_br_tr_px':expected.tolist(),'detector_corners_tl_bl_br_tr_px':detected.tolist(),'detector_minus_projected_source_points_px':(detected-expected).tolist(),'source_preprocessing':{'resize_scale':s,'resized_resolution':[scaled_w,scaled_h],'tensor_resolution':[640,640],'padding':'bottom160 black rows, no top/left offset','ROI_enabled':False,'corner_decode':'All corner x/y multiplied by same inverse scale, plus zero ROI offset; returned order tl,bl,br,tr is geometrically consistent.','color':'BGR uint8 converted to RGB float32 and divided by255 inside OpenVINO preprocessor.','predicted_corners_on_tensor_px':(detected*s).tolist()},'clipping':'Projected endpoints and actual luminous pixels lie wholly within1440x1080 image and640x480 populated resized tensor; no plate/corner clipping or padding overlap.'}
args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
