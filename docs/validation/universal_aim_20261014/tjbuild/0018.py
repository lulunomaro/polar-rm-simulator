#!/usr/bin/env python3
"""Public JSONL protocol wrapper for a locally verified native aim example.

The transport is common; source identity and stationary capability are instance
metadata. No team name selects authority, native mode, sensor truth or deadlines.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import select
import signal
import stat
import subprocess
import sys
import tempfile
import time

SCHEMA='polar.sim.adapter.jsonl.v1'
NATIVE_SCHEMA='polar.native.aim-compute.v1'
MAX_REQUEST=12*1024*1024
MAX_RESPONSE=65536


def checked_native_ready(value):
    if (type(value) is not dict or set(value)!={'schema','op','ok','inference_calls'}
        or type(value['schema']) is not str or value['schema']!=NATIVE_SCHEMA
        or type(value['op']) is not str or value['op']!='ready' or value['ok'] is not True
        or type(value['inference_calls']) is not int or value['inference_calls']!=0):
        raise ValueError('native_zero_tick_ready')
    return dict(value)


def strict_json(raw):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('duplicate_json_key')
            result[key]=value
        return result
    def invalid(_):raise ValueError('nonfinite_json')
    def number(text):
        value=float(text)
        if not math.isfinite(value):raise ValueError('nonfinite_json')
        return value
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=invalid,parse_float=number)


def read_checked(path,sha,limit):
    if type(sha) is not str or len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha):raise ValueError('local_sha256')
    supplied=Path(path)
    if not supplied.is_absolute() or '..' in supplied.parts:raise ValueError('local_asset_path')
    path=Path(os.path.abspath(path))
    for part in (path,*path.parents):
        row=part.lstat()
        if stat.S_ISLNK(row.st_mode) or getattr(row,'st_file_attributes',0)&0x400:raise ValueError('local_asset_alias')
    before=path.stat()
    if not path.is_file() or before.st_size>limit:raise ValueError('local_asset_bound')
    raw=path.read_bytes();after=path.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns) or hashlib.sha256(raw).hexdigest()!=sha:
        raise ValueError('local_asset_hash')
    return raw


def validate_instance(value):
    """Trusted local instance, checked before importing the simulation package."""
    fields={'schema','repo_root','binary','binary_sha256','config','config_sha256','calibration','models','enemy_color','evidence_out'}
    if type(value) is not dict or set(value)!=fields or value['schema']!='polar.owned-native-aim-instance.v1':raise ValueError('local_instance_schema')
    if value['enemy_color'] not in ('red','blue'):raise ValueError('instance_enemy_color')
    binary=read_checked(value['binary'],value['binary_sha256'],64*1024*1024)
    if len(binary)<64 or binary[:6]!=b'\x7fELF\x02\x01' or binary[18:20]!=b'\x3e\x00':raise ValueError('linux_x86_64_elf_required')
    config=strict_json(read_checked(value['config'],value['config_sha256'],65536))
    if type(config) is not dict or config.get('enemy_color')!=value['enemy_color']:raise ValueError('instance_config_identity')
    if type(value['models']) is not dict or set(value['models'])!={'yolov5.xml','yolov5.bin','tiny_resnet.onnx'}:raise ValueError('instance_model_refs')
    from tools.prepare_tongji_aim_plugin import MODEL_BLOBS,blob,calibration_config
    for name,ref in value['models'].items():
        if type(ref) is not dict or set(ref)!={'path','sha256'}:raise ValueError('instance_model_ref')
        if blob(read_checked(ref['path'],ref['sha256'],32*1024*1024))!=MODEL_BLOBS[name]:raise ValueError('instance_fixed_model_blob')
    if (config.get('yolov5_model_path')!=value['models']['yolov5.xml']['path']
        or config.get('classify_model')!=value['models']['tiny_resnet.onnx']['path']
        or Path(value['models']['yolov5.xml']['path']).with_suffix('.bin')!=Path(value['models']['yolov5.bin']['path'])):
        raise ValueError('instance_model_config_mismatch')
    expected,_=calibration_config(config,model_dir=Path(value['models']['yolov5.xml']['path']).parent,
                                  enemy_color=value['enemy_color'],camera=value['calibration'])
    for name in ('camera_matrix','distort_coeffs','R_gimbal2imubody','R_camera2gimbal','t_camera2gimbal','yaw_offset','pitch_offset','device'):
        if config.get(name)!=expected[name]:raise ValueError('instance_calibration_config_mismatch')
    return value


def source_quaternion(qpos,odom):
    """Own capture-state only: Rz(body+yaw_joint) Ry(-pitch_joint)."""
    yaw=odom[2]+qpos[3];pitch=qpos[4]
    cy,sy=math.cos(yaw/2),math.sin(yaw/2);cp,sp=math.cos(pitch/2),math.sin(pitch/2)
    return [cy*cp,sy*sp,-cy*sp,sy*cp]


def public_packet(observation,profile,path):
    from rm_match.platform_v2.contracts import validate_observation,OBS_SCHEMA
    decoded={};o=validate_observation(observation,image_bytes=decoded)
    if o['schema']!=OBS_SCHEMA:raise ValueError('camera_observation_required')
    camera=o['sensors']['camera']
    if not camera['available']:raise ValueError('camera_unavailable')
    if not 0<=o['sim_time']-camera['capture_sim_time']<=.08:raise ValueError('original_camera_age')
    image=camera['image'];intr=camera['intrinsics'];ext=camera['extrinsics']
    if (image['width'],image['height'],image['stride_bytes'])!=(profile['width'],profile['height'],profile['width']*3):
        raise ValueError('unsupported_calibrated_resolution')
    if any(abs(intr[key]-profile[key])>1e-8 for key in ('fx','fy','cx','cy')) or intr['distortion']!=profile['distortion']:
        raise ValueError('instance_calibration_mismatch')
    if (ext['parent_frame']!='gimbal_link' or ext['translation_m']!=[.24,0.,.06]
        or ext['rotation_xyzw'] not in ([-.5,.5,-.5,.5],[.5,-.5,.5,-.5])):
        raise ValueError('instance_camera_mount_mismatch')
    qpos=camera['own_qpos_at_capture'];odom=camera['own_odom_at_capture']
    if odom is None or camera['own_odom_velocity_at_capture'] is None:raise ValueError('capture_own_odometry_required')
    velocity=camera['own_odom_velocity_at_capture'];current=o['own']['odom_vxyw']
    if current is None or max(math.hypot(*velocity[:2]),math.hypot(*current[:2]))>.03 or max(abs(velocity[2]),abs(current[2]))>.03:
        raise ValueError('stationary_capability_only')
    raw=decoded['raw']
    if len(raw)!=profile['width']*profile['height']*3:raise ValueError('decoded_image_bound')
    if image['encoding']=='rgb8':
        bgr=bytearray(len(raw));bgr[0::3]=raw[2::3];bgr[1::3]=raw[1::3];bgr[2::3]=raw[0::3];raw=bytes(bgr)
    elif image['encoding']!='bgr8':raise ValueError('image_encoding')
    packet=dict(schema=NATIVE_SCHEMA,op='compute',frame_id=camera['frame_id'],
        capture_ns=round(camera['capture_sim_time']*1e9),control_ns=round(o['sim_time']*1e9),
        image=dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest(),width=image['width'],height=image['height'],
            stride_bytes=image['stride_bytes'],bytes=len(raw)),
        gimbal_quaternion_wxyz=source_quaternion(qpos,odom),bullet_speed=22.5)
    return o,packet,raw


def result_for(observation,packet,result):
    from rm_match.platform_v2.contracts import action_for,validate_action
    from rm_match.platform_v2.aim_contracts import aim_status_for
    expected={'schema','op','ok','frame_id','capture_ns','control_ns','input_bgr_sha256','detector_executed','detections','targets',
              'tracker_state','control','would_fire','yaw_rad','pitch_rad','clock_policy','reference_frame'}
    if type(result) is not dict or set(result)!=expected or result['schema']!=NATIVE_SCHEMA or result['op']!='compute' or result['ok'] is not True:
        raise ValueError('native_result_contract')
    for key in ('frame_id','capture_ns','control_ns'):
        if type(result[key]) is not int or result[key]!=packet[key]:raise ValueError('native_result_clock_identity')
    if result['input_bgr_sha256']!=packet['image']['sha256'] or result['detector_executed'] is not True:
        raise ValueError('native_result_actual_pixels')
    if (type(result['control']) is not bool or type(result['would_fire']) is not bool
        or any(type(result[k]) is not int or result[k]<0 for k in ('detections','targets'))
        or result['clock_policy']!='original_source_ns_differences'
        or result['reference_frame']!='stationary_capture_origin_inertial'):
        raise ValueError('native_result_types')
    if type(result['tracker_state']) is not str or result['tracker_state'] not in ('lost','detecting','tracking','temp_lost','switching'):
        raise ValueError('native_tracker_state')
    if ((not result['control'] and result['would_fire']) or
        (result['control'] and (result['targets']==0 or result['tracker_state']=='lost'))):
        raise ValueError('native_result_control_consistency')
    # The original tracker may predict after missed detections. This example
    # emits no authority for such a target; its result keeps the real state.
    if result['tracker_state'] in ('temp_lost','switching'):
        return 'status',aim_status_for(observation,'pending_result')
    if not result['control']:
        if result['yaw_rad'] is not None or result['pitch_rad'] is not None:raise ValueError('inactive_native_angles')
        return 'status',aim_status_for(observation,'no_target' if not result['targets'] else 'pending_result')
    for key in ('yaw_rad','pitch_rad'):
        if type(result[key]) not in (int,float) or not math.isfinite(result[key]):raise ValueError('native_result_angle')
    # Original planner yaw is the inertial bearing about the stationary origin.
    # Public actuator yaw is about base_link and pitch is positive UP. The
    # upstream planner explicitly returns -Trajectory.pitch (positive down).
    # This converts references, not detections or truth.
    own_yaw=observation['own']['odom_xyyaw'][2]
    yaw=result['yaw_rad']-own_yaw
    command=dict(frame='base_link',yaw_rad=math.atan2(math.sin(yaw),math.cos(yaw)),pitch_rad=-result['pitch_rad'],
                 active=True,confidence=None,fire_permission=False)
    action=action_for(observation,'aim','gimbal_target',command)
    return 'action',validate_action(action,observation,dict(kind='aim',output_modes=['gimbal_target']))


class NativeProcess:
    def __init__(self,spec,directory):
        from rm_match.integrations.owned_linux_group import LinuxOwnedProcessGroup
        from rm_match.platform_v2.native_evidence import ActualFrameEvidenceWriter
        self.owner=LinuxOwnedProcessGroup();self.child=None;self.stderr=None;self.closed=False
        self.directory=directory;self.evidence=Path(spec['evidence_out']);self.cleanup=None;self.writer=None
        self.ready=None;self.compute_attempts=0
        try:
            self.writer=ActualFrameEvidenceWriter(self.evidence/'actual_frames')
            self.stderr=(self.evidence/'native_stderr.log').open('xb')
            self.child=subprocess.Popen([spec['binary'],spec['config'],str(directory)],stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,stderr=self.stderr,bufsize=0,start_new_session=True,cwd=directory)
            self.owner.attach(self.child)
            os.set_blocking(self.child.stdin.fileno(),False)
            os.set_blocking(self.child.stdout.fileno(),False)
            self.ready=checked_native_ready(self.receive(time.perf_counter()+20.))
            (self.evidence/'NATIVE_READY.json').write_text(json.dumps(self.ready,allow_nan=False)+'\n')
        except BaseException:
            self.close();raise
    def archive(self,packet,pixels):
        return self.writer.submit(packet['frame_id'],pixels,packet['image']['sha256'])
    def receive(self,deadline):
        data=bytearray()
        while time.perf_counter()<deadline:
            if self.child.poll() is not None:raise RuntimeError('native_exited')
            readable,_,_=select.select([self.child.stdout.fileno()],[],[],min(.005,max(0.,deadline-time.perf_counter())))
            if time.perf_counter()>=deadline:raise TimeoutError('native_local_deadline')
            if not readable:continue
            raw=os.read(self.child.stdout.fileno(),MAX_RESPONSE+1)
            if not raw:raise EOFError('native_stdout_eof')
            data.extend(raw)
            if len(data)>MAX_RESPONSE:raise ValueError('native_reply_bound')
            if b'\n' in data:
                line,_,tail=data.partition(b'\n')
                if tail:raise ValueError('multiple_native_replies')
                result=strict_json(bytes(line))
                if time.perf_counter()>=deadline:raise TimeoutError('native_local_deadline')
                return result
        raise TimeoutError('native_local_deadline')
    def compute(self,packet):
        deadline=time.perf_counter()+.08
        raw=json.dumps(packet,allow_nan=False,separators=(',',':')).encode()+b'\n'
        if len(raw)>MAX_RESPONSE:raise ValueError('native_request_bound')
        self.compute_attempts=getattr(self,'compute_attempts',0)+1
        written=0
        while written<len(raw):
            left=deadline-time.perf_counter()
            if left<=0:raise TimeoutError('native_local_deadline')
            _,writable,_=select.select([],[self.child.stdin.fileno()],[],min(.005,left))
            if time.perf_counter()>=deadline:raise TimeoutError('native_local_deadline')
            if not writable:continue
            try:count=os.write(self.child.stdin.fileno(),raw[written:])
            except BlockingIOError:continue
            if count<=0:raise EOFError('native_stdin_closed')
            written+=count
        return self.receive(deadline)
    def close(self):
        if self.closed:return
        self.closed=True;errors=[];process_status=None;evidence_status=None
        try:process_status=self.owner.cleanup()
        except BaseException as error:errors.append(type(error).__name__+':'+str(error))
        if self.writer is not None:
            try:evidence_status=self.writer.close(timeout=.15)
            except BaseException as error:
                evidence_status=self.writer.shutdown_status;errors.append(type(error).__name__+':'+str(error))
        for stream in (None if self.child is None else self.child.stdin,None if self.child is None else self.child.stdout,self.stderr):
            if stream is not None:
                try:stream.close()
                except BaseException as error:errors.append(type(error).__name__+':'+str(error))
        self.cleanup=dict(clean=not errors and process_status is not None and process_status.get('clean') is True
            and (self.writer is None or (evidence_status is not None and evidence_status.get('clean') is True)),
            process=process_status,evidence=evidence_status,errors=errors)
        (self.evidence/'NATIVE_CLEANUP.json').write_text(json.dumps(self.cleanup,indent=2)+'\n')
        if self.cleanup.get('clean') is not True:raise RuntimeError('native_cleanup_incomplete')


def run(spec,*,native_factory=NativeProcess):
    from rm_match.platform_v2.contracts import validate_observation
    from rm_match.platform_v2.aim_contracts import aim_status_for
    context=None;last_frame=-1;last_seq=-1;anchor=None;process=None;count=0;prepared=False
    def stop(*_):raise SystemExit(0)
    previous={s:signal.signal(s,stop) for s in (signal.SIGTERM,signal.SIGINT)}
    try:
      with tempfile.TemporaryDirectory(prefix='polar-aim-',dir='/dev/shm') as tmp:
        directory=Path(tmp);os.chmod(directory,0o700)
        process=native_factory(spec,directory)
        try:
            # Constructor returned only after real native model/resource ready.
            # This also guards the legacy reset-without-prepare path.
            checked_native_ready(process.ready)
            while True:
                raw=sys.stdin.buffer.readline(MAX_REQUEST+1)
                if not raw:break
                if len(raw)>MAX_REQUEST or not raw.endswith(b'\n'):raise ValueError('public_line_bound_or_partial')
                message=strict_json(raw)
                if type(message) is not dict or message.get('schema')!=SCHEMA:raise ValueError('public_jsonl_schema')
                if message.get('op')=='prepare':
                    if (set(message)!={'schema','op','config'} or type(message['config']) is not dict or message['config']
                        or prepared or context is not None or count!=0 or process.compute_attempts!=0):
                        raise ValueError('prepare_once_before_reset')
                    ready=checked_native_ready(process.ready)
                    prepared=True;reply=dict(schema=SCHEMA,op='prepare',ok=True)
                    # This records actual ready proof, not a sensor/result ACK.
                    with (Path(spec['evidence_out'])/'PUBLIC_PREPARE.json').open('x',encoding='utf-8') as log:
                        log.write(json.dumps(dict(reply=reply,native_ready=ready,compute_attempts=0),allow_nan=False)+'\n')
                elif message.get('op')=='reset':
                    if set(message)!={'schema','op','context','config'} or context is not None or message['config']!={}:raise ValueError('reset_contract')
                    candidate=message['context']
                    if type(candidate) is not dict or set(candidate)!={'episode','robot_id','binding_epoch'}:raise ValueError('reset_context')
                    if any(type(candidate[k]) is not int or candidate[k]<0 for k in ('episode','binding_epoch')) or type(candidate['robot_id']) is not str or not candidate['robot_id']:
                        raise ValueError('reset_context_types')
                    context=dict(candidate);reply=dict(schema=SCHEMA,op='reset',ok=True)
                elif message.get('op')=='act':
                    if set(message)!={'schema','op','observation'} or context is None:raise ValueError('act_contract')
                    o=validate_observation(message['observation'])
                    if any(type(o[k]) is not type(v) or o[k]!=v for k,v in context.items()):raise ValueError('observation_context')
                    if o['observed_seq']<=last_seq:raise ValueError('replayed_observation')
                    last_seq=o['observed_seq']
                    camera=o['sensors']['camera']
                    if o['own']['team'] not in ('red','blue') or o['own']['team']==spec['enemy_color']:
                        raise ValueError('instance_enemy_color_mismatch')
                    if (not o['own']['alive'] or o['referee']['phase']!='running' or o['referee']['emergency_stop']
                        or not camera['available'] or camera['frame_id']<=last_frame):
                        key,value='status',aim_status_for(o,'pending_result')
                    else:
                        o,packet,pixels=public_packet(o,spec['calibration'],directory/'sensor.bgr')
                        position=camera['own_odom_at_capture'][:2]
                        if anchor is None:anchor=list(position)
                        if math.dist(position,anchor)>.025:raise ValueError('stationary_origin_moved')
                        process.archive(packet,pixels)
                        (directory/'sensor.bgr').write_bytes(pixels)
                        count+=1
                        if count>1024:raise ValueError('bounded_native_evidence')
                        request=dict(event='native_request',packet=packet,public_identity={k:o[k] for k in
                            ('robot_id','episode','binding_epoch','observed_seq','sim_time','wall_deadline')})
                        with (Path(spec['evidence_out'])/'NATIVE_REQUESTS.jsonl').open('a',encoding='utf-8') as log:
                            log.write(json.dumps(request,allow_nan=False)+'\n')
                        result=process.compute(packet);key,value=result_for(o,packet,result);last_frame=camera['frame_id']
                        with (Path(spec['evidence_out'])/'NATIVE_REQUESTS.jsonl').open('a',encoding='utf-8') as log:
                            log.write(json.dumps(dict(event='native_result',frame_id=packet['frame_id'],result=result),allow_nan=False)+'\n')
                    reply=dict(schema=SCHEMA,op='act',ok=True,**{key:value})
                else:raise ValueError('public_operation')
                sys.stdout.write(json.dumps(reply,allow_nan=False,separators=(',',':'))+'\n');sys.stdout.flush()
        finally:
            # A repeated TERM must not interrupt bounded owned-group cleanup.
            for s in previous:signal.signal(s,signal.SIG_IGN)
            process.close()
    finally:
        for s,handler in previous.items():signal.signal(s,handler)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec',type=Path,required=True);parser.add_argument('--spec-sha256',required=True)
    args=parser.parse_args()
    value=strict_json(read_checked(args.spec,args.spec_sha256,65536))
    if type(value) is not dict or type(value.get('repo_root')) is not str:raise ValueError('local_instance_schema')
    # Bootstrap imports use only a pinned local repository supplied by the
    # administrator; no network, observation or model selects an import path.
    root=Path(os.path.abspath(value['repo_root']))
    if not Path(value['repo_root']).is_absolute() or '..' in Path(value['repo_root']).parts:raise ValueError('repo_alias')
    for part in (root,*root.parents):
        row=part.lstat()
        if stat.S_ISLNK(row.st_mode) or getattr(row,'st_file_attributes',0)&0x400:raise ValueError('repo_alias')
    sys.path.insert(0,str(root))
    validate_instance(value)
    evidence=Path(os.path.abspath(value['evidence_out']))
    if '..' in Path(value['evidence_out']).parts or evidence.exists() or evidence!=args.spec.absolute().parent/'evidence':raise ValueError('fresh_bound_evidence_required')
    evidence.mkdir(mode=0o700)
    run(value)


if __name__=='__main__':main()
