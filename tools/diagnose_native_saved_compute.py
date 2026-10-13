#!/usr/bin/env python3
"""Linux-local saved real sensor-frame compute diagnostic, never live evidence."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import traceback
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def _saved_json(text):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('Duplicate saved JSON field')
            result[key]=value
        return result
    def nonfinite(value):raise ValueError('Nonfinite saved JSON value')
    return json.loads(text,object_pairs_hook=pairs,parse_constant=nonfinite)


def _saved_checked_path(path,root):
    path=Path(os.path.abspath(path))
    if not path.is_relative_to(root):raise ValueError('Saved input outside run root')
    for part in (path,*path.parents):
        info=part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
            raise ValueError('Saved input reparse/symlink path')
    return path


def _saved_read(path,root,max_bytes):
    path=_saved_checked_path(path,root);before=path.lstat()
    if not stat.S_ISREG(before.st_mode):raise ValueError('Saved input must be a regular file')
    if before.st_size>max_bytes:raise ValueError('Saved input exceeds bounded size')
    descriptor=os.open(path,os.O_RDONLY|getattr(os,'O_BINARY',0)|getattr(os,'O_NOFOLLOW',0))
    with os.fdopen(descriptor,'rb') as stream:
        opened=os.fstat(stream.fileno());content=stream.read(max_bytes+1)
    after=_saved_checked_path(path,root).lstat()
    identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)
    if len(content)>max_bytes or identity(before)!=identity(opened) or identity(opened)!=identity(after):
        raise ValueError('Saved input changed while reading')
    return content


def select_saved_native_input(run_root):
    """Select exactly one archived real frame; portable, with no native imports."""
    root=Path(os.path.abspath(run_root));_saved_checked_path(root,root)
    requests=[]
    for line in _saved_read(root/'ledger.jsonl',root,16*1024*1024).decode('utf-8').splitlines():
        row=_saved_json(line)
        if type(row) is not dict:raise ValueError('Saved ledger row must be an object')
        if row.get('event')=='native_request':requests.append(row)
    if len(requests)!=1:raise ValueError('Exactly one preserved native request required')
    request=requests[0];frame_id=request.get('frame_id');expected_sha=request.get('raw_bgr_sha256')
    if type(frame_id) is not int or frame_id<0:raise ValueError('Invalid saved request frame_id')
    if type(expected_sha) is not str or not re.fullmatch('[0-9a-f]{64}',expected_sha):
        raise ValueError('Invalid saved request pixel SHA')
    candidates=[]
    for directory,dirs,files in os.walk(root,followlinks=False):
        for name in dirs:_saved_checked_path(Path(directory)/name,root)
        for name in files:
            path=Path(directory)/name
            if name=='sensor_input.bgr':candidates.append(('legacy_sensor_input_bgr',path,None,None))
            elif name==f'sensor_{frame_id}.json':
                if path.parent.name!='actual_frames':raise ValueError('Saved manifest outside actual_frames')
                manifest_bytes=_saved_read(path,root,4096)
                manifest=_saved_json(manifest_bytes.decode('utf-8'))
                fields={'schema','frame_id','width','height','stride_bytes','bytes','encoding','file','sha256'}
                if type(manifest) is not dict or set(manifest)!=fields:raise ValueError('Invalid saved manifest fields')
                for key,value in [('frame_id',frame_id),('width',1440),('height',1080),('stride_bytes',4320),('bytes',4665600)]:
                    if type(manifest[key]) is not int or manifest[key]!=value:raise ValueError('Invalid saved manifest '+key)
                expected_file=f'sensor_{frame_id}.bgr'
                if (manifest['schema']!='polar.sim.actual_native_frame_evidence.v1'
                    or manifest['encoding']!='bgr8' or manifest['file']!=expected_file
                    or manifest['sha256']!=expected_sha):raise ValueError('Invalid saved manifest identity')
                candidates.append(('v2_actual_frame_manifest',path.parent/expected_file,path,hashlib.sha256(manifest_bytes).hexdigest()))
    if len(candidates)!=1:raise ValueError('Saved input missing or ambiguous candidates')
    kind,source,manifest,manifest_sha=candidates[0];content=_saved_read(source,root,4665600)
    if len(content)!=4665600 or hashlib.sha256(content).hexdigest()!=expected_sha:
        raise ValueError('Saved actual pixel identity mismatch')
    return dict(request=request,content=content,source=source,manifest=manifest,
        input_format=kind,sha256=expected_sha,
        provenance=dict(format=kind,frame_id=frame_id,source=source.relative_to(root).as_posix(),
            manifest=None if manifest is None else manifest.relative_to(root).as_posix(),manifest_sha256=manifest_sha,
            image_sha256=expected_sha))


def distribution(values):
    values=sorted(values)
    def p(q):
        if not values:return None
        x=q*(len(values)-1);i=int(x);j=min(i+1,len(values)-1)
        return (values[i]+(values[j]-values[i])*(x-i))*1000
    return dict(samples=len(values),p50_ms=p(.5),p95_ms=p(.95),p99_ms=p(.99),max_ms=max(values)*1000 if values else None)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-root',required=True,type=Path)
    p.add_argument('--native-spec',required=True,type=Path)
    p.add_argument('--out',required=True,type=Path)
    a=p.parse_args()
    if sys.platform!='linux':raise RuntimeError('Run only in Linux, no Windows/host clock inference')
    from rm_match.deployment.profile import validate_t2_spec
    from rm_match.camera_profile import SourceCameraProfile
    from rm_match.integrations.rmcs_contract import own_state
    from rm_match.integrations.wsl_operator_worker import _stdin_wait,validate_sensor_frame
    from rm_match.operator.source_aim import OperatorFovProcess
    spec,spec_sha=validate_t2_spec(a.native_spec)
    root=Path(os.path.abspath(a.run_root));out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    def write(name,value):
        (out/name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    saved=select_saved_native_input(root)
    request=saved['request'];content=saved['content'];image_sha=saved['sha256']
    write('SAVED_INPUT_PROVENANCE.json',saved['provenance'])
    image=out/'saved_input.bgr';image.write_bytes(content)
    captured=request['own_at_capture'];profile=SourceCameraProfile()
    own=own_state(SimpleNamespace(own_qpos=captured['own_qpos_at_capture'],own_qvel=captured['own_qvel_at_capture'],
        odom_xyyaw=captured['own_odom_at_capture'],odom_vxyw=captured['own_odom_velocity_at_capture'],
        own_hp=0,ammo=0,own_heat=0))
    # These optional fields were not archived in the trace; they are not used by
    # the original native Runner. Omit them rather than fabricate measurements.
    for name in ('hp','ammo','heat'):own.pop(name)
    frame=dict(schema='rmcs-mujoco-actor-frame-v1',episode=request['episode'],frame_id=request['frame_id'],
        exposure_timestamp_ns=round(request['capture_sim_time']*1e9),capture_time_s=request['capture_sim_time'],
        own_referee_id=7,own_team='red',image=dict(encoding='bgr8',width=1440,height=1080,stride_bytes=4320,
            bytes=4665600,sha256=image_sha,path=str(image)),camera=dict(fx=profile.fx,fy=profile.fy,cx=profile.cx,
            cy=profile.cy,distortion=list(profile.distortion)),own=own)
    packet=dict(episode=request['episode'],control_time_ns=round(request['observation_sim_time']*1e9),frame=frame)
    validate_sensor_frame(frame);write('ORIGINAL_RECONSTRUCTED_PACKET.json',packet)
    fs=[]
    for i in range(15):
        start=time.perf_counter();raw=image.read_bytes();read=time.perf_counter()
        sha=hashlib.sha256(raw).hexdigest();hashed=time.perf_counter()
        json.dumps(packet,allow_nan=False);encoded=time.perf_counter()
        assert sha==image_sha
        fs.append(dict(sample=i,read_s=read-start,sha256_s=hashed-read,json_encode_s=encoded-hashed))
    env=os.environ.copy();env.update(spec.get('environment',{}))
    env.update(AUTOAIM_CONFIG=spec['autoaim_config'],RMCS_HEADLESS_SHARE=spec['model_share'],ORT_DISABLE_TELEMETRY='1')
    cases=[];errors=[]
    # Same packet fifteen times in one process, plus three independent fresh
    # first-inference cases. Duplicate exposure is rejected by original gates.
    for name,count in [('same_packet_15',15),('fresh_first_1',1),('fresh_first_2',1),('fresh_first_3',1)]:
        process=OperatorFovProcess(spec['binary'],spec['executor_yaml'],out/name,env,
            fov=dict(fov_degrees=180.,circle_radius_x_norm=1.,circle_radius_y_norm=1.),timeout=2.)
        rows=[];child=None;readiness=None;start=time.perf_counter();error=None;cleanup=None
        try:
            (out/name).mkdir(parents=True,exist_ok=False)
            (out/name/'tracking_mode').write_text(spec['runtime_mode_contents'])
            process.reset(dict(episode=request['episode']));child=process.process
            deadline=time.perf_counter()+15
            while time.perf_counter()<deadline:
                readiness=_stdin_wait(child.pid)
                if readiness:break
                if child.poll() is not None:raise RuntimeError('Native exited before ready')
                time.sleep(.005)
            if readiness is None:raise TimeoutError('Original ELF read(0) readiness exceeded 15s')
            startup=time.perf_counter()-start
            for i in range(count):
                begin=time.perf_counter();response=process.control(packet);end=time.perf_counter()
                row=dict(sample=i,linux_local_request_perf=begin,linux_local_response_perf=end,
                    response_s=end-begin,response=response)
                rows.append(row)
                # Persist each real response before computing aggregate reports.
                write(name+'_responses.json',rows)
        except BaseException as exc:
            error=type(exc).__name__+':'+str(exc);errors.append(dict(case=name,error=error))
            (out/(name+'_exception.txt')).write_text(traceback.format_exc(),encoding='utf-8')
            startup=time.perf_counter()-start
        finally:
            close_start=time.perf_counter()
            try:process.close()
            except BaseException as exc:
                errors.append(dict(case=name,error='close:'+type(exc).__name__+':'+str(exc)))
            cleanup=dict(close_s=time.perf_counter()-close_start,pid=None if child is None else child.pid,
                returncode=None if child is None else child.poll(),
                proc_absent=child is not None and not Path('/proc/'+str(child.pid)).exists(),
                stdin_closed=child is not None and child.stdin.closed,stdout_closed=child is not None and child.stdout.closed)
        cases.append(dict(case=name,startup_s=startup,zero_tick_readiness=readiness,error=error,cleanup=cleanup,
            responses=rows,actual_detector_samples=sum(x['response']['detector_executed'] is True for x in rows)))
    first=[x['responses'][0]['response_s'] for x in cases if x['responses'] and x['responses'][0]['response']['detector_executed']]
    duplicates=[x['response_s'] for x in cases[0]['responses'][1:] if not x['response']['detector_executed']]
    report=dict(schema='polar.linux.saved-native-compute.v1',scope='Offline Linux-local compute/FS diagnostic only; cannot supplement failed live control',
        clock_domain='Linux time.perf_counter only, never subtract Windows/QPC time',
        spec_sha256=spec_sha,binary_sha256=spec['sha256']['binary'],model_sha256=spec['model_sha256'],
        source_identity=spec['source_identity'],actual_image_sha256=image_sha,saved_input=saved['provenance'],
        preserved_capture_ns=packet['frame']['exposure_timestamp_ns'],preserved_control_ns=packet['control_time_ns'],
        timestamp_or_pixel_changes=False,own_fields_omitted_not_archived=['hp','ammo','heat'],
        ready_before_capture_or_inference=True,live_80ms_budget_changed=False,
        diagnostic_response_timeout_s=2.,cases=cases,errors=errors,
        fresh_valid_first_inference=distribution(first),duplicate_noninference_responses=distribution(duplicates),
        filesystem_stages={k:distribution([x[k] for x in fs]) for k in ('read_s','sha256_s','json_encode_s')},
        filesystem_samples=fs)
    write('RESULT.json',report)
    write('EVIDENCE_MANIFEST.json',{str(x.relative_to(out)):hashlib.sha256(x.read_bytes()).hexdigest()
        for x in out.rglob('*') if x.is_file() and x.name!='EVIDENCE_MANIFEST.json'})
    print(json.dumps({k:report[k] for k in ('fresh_valid_first_inference','duplicate_noninference_responses','filesystem_stages','errors')},indent=2))
    return 0 if not errors and all(c['cleanup']['proc_absent'] for c in cases) else 2


if __name__=='__main__':
    raise SystemExit(main())
