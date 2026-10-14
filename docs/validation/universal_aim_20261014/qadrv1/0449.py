"""Frozen-image API replay through real native/pixel adapters, not live tracking QA."""
import sys
if not __debug__:raise SystemExit('Run without -O: validation is required')
import argparse
import base64
import hashlib
import json
import time
from pathlib import Path
import numpy as np
from PIL import Image
from rm_match.contracts import Observation
from rm_match.platform_v2.contracts import build_observation,validate_action
from rm_match.platform_v2.adapters import default_registry

def main():
    p=argparse.ArgumentParser();p.add_argument('--source-spec',required=True);p.add_argument('--image',required=True);p.add_argument('--frame-record',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    out=Path(a.out);out.mkdir(parents=True,exist_ok=False)
    image=np.array(Image.open(a.image).convert('RGB'));record=json.loads(Path(a.frame_record).read_text());frame=record.get('request_frame',record);own=frame['own'];intr=frame['camera'];h,w=image.shape[:2]
    decoded_sha=hashlib.sha256(np.ascontiguousarray(image[:,:,::-1]).tobytes()).hexdigest()
    assert frame['image']['encoding']=='bgr8' and frame['image']['sha256']==decoded_sha, 'Recorded image identity mismatch'
    assert own['camera_optical_from_pitchlink_rotation']==[[0,-1,0],[0,0,-1],[1,0,0]], 'Recorded extrinsic mismatch'
    registry=default_registry(native_spec=a.source_spec,native_out=out/'native');results=[]
    for aid in ('aim_pixel_baseline_v1','aim_native_rmcs_v1'):
        adapter=registry.create(aid,{'fov_degrees':180.,'circle_radius_x_norm':2.,'circle_radius_y_norm':2.} if aid=='aim_native_rmcs_v1' else {})
        adapter.reset(dict(episode=0,robot_id='red_sentry',binding_epoch=1))
        try:
            for seq,t in enumerate((0.,.4,.42,.45)):
                raw=Observation(episode=0,sim_time=t,rgb=image,fovy_degrees=60.,own_qpos=tuple(own['joint_positions']),own_qvel=tuple(own['joint_velocities']),own_hp=own['hp'],ammo=own['ammo'],robot_id='red_sentry',odom_xyyaw=tuple(own['base_odom_xyyaw']),odom_vxyw=tuple(own['base_odom_vxyw']),own_heat=own['heat'],team='red',role='sentry',remaining_seconds=300.-t)
                camera=dict(available=True,reason='available',frame_id=seq,capture_sim_time=t,own_qpos_at_capture=list(raw.own_qpos),own_qvel_at_capture=list(raw.own_qvel),own_odom_at_capture=list(raw.odom_xyyaw),own_odom_velocity_at_capture=list(raw.odom_vxyw),image=dict(encoding='rgb8',width=w,height=h,stride_bytes=w*3,data_base64=base64.b64encode(image.tobytes()).decode()),intrinsics=dict(**intr,distortion_model='brown_conrady_5'),extrinsics=dict(parent_frame='gimbal_link',translation_m=own['camera_position_pitchlink_m'],rotation_xyzw=[-.5,.5,-.5,.5],calibration_id='frozen_source_sensor_profile'),provenance='simulated_raw_camera')
                o=build_observation(raw,binding_epoch=1,observed_seq=seq,wall_deadline=time.monotonic()+3.,camera=camera)
                action=validate_action(adapter.act(o),o,registry.get(aid).descriptor)
                assert action['command']['fire_permission'] is False
                results.append(dict(adapter_id=aid,observed_seq=seq,command=action['command']))
        finally:adapter.close()
    report=dict(scope='Frozen-image adapter API replay. Image and own pose repeated at synthetic simulation timestamps; no live camera, physics, tracking stability, network latency or automatic firing qualification.',source_image_sha256=hashlib.sha256(Path(a.image).read_bytes()).hexdigest(),decoded_bgr_sha256=decoded_sha,frame_record_sha256=hashlib.sha256(Path(a.frame_record).read_bytes()).hexdigest(),source_spec_sha256=hashlib.sha256(Path(a.source_spec).read_bytes()).hexdigest(),binary_sha256=hashlib.sha256(Path(json.loads(Path(a.source_spec).read_text())['binary']).read_bytes()).hexdigest(),wrapper_sha256=hashlib.sha256((Path(__file__).absolute().parents[2]/'rm_match/platform_v2/native_adapter.py').read_bytes()).hexdigest(),entry_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),results=results,native_process_started=bool(list((out/'native').glob('binding_*/rmcs_stderr.log'))))
    assert report['native_process_started'];(out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'native_process_started':True,'actions_validated':len(results)}))
if __name__=='__main__':main()
