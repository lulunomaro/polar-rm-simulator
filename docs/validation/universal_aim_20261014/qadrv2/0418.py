#!/usr/bin/env python3
"""Postclose audit of archived actual pixels; never modifies live evidence."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from tools.diagnose_native_saved_compute import _saved_checked_path,_saved_read,_saved_json

SCHEMA='polar.live.native-pixel-audit.v1'
STRATEGY='archived_bgr_postclose_exact_channel_swap'
IMAGE_BYTES=1440*1080*3


def _sha(value):return type(value) is str and re.fullmatch('[0-9a-f]{64}',value) is not None
def _number(value):return type(value) in (int,float) and math.isfinite(value) and value>=0
def _integer(value):return type(value) is int and value>=0


def audit_saved_native_pixels(run_root):
    """Return complete proofs or explicit errors; audit failure cannot hide live FAIL."""
    result=dict(schema=SCHEMA,clean=False,proofs=[],errors=[],sources={},strategy=STRATEGY)
    try:
        root=Path(os.path.abspath(run_root));_saved_checked_path(root,root)
        ledger_bytes=_saved_read(root/'ledger.jsonl',root,16*1024*1024)
        frame_bytes=_saved_read(root/'FRAME_BINDINGS.json',root,16*1024*1024)
        result['sources']=dict(ledger_sha256=hashlib.sha256(ledger_bytes).hexdigest(),
            frame_bindings_sha256=hashlib.sha256(frame_bytes).hexdigest())
        frames=_saved_json(frame_bytes.decode('utf-8'))
        rows=[_saved_json(line) for line in ledger_bytes.decode('utf-8').splitlines()]
        if type(frames) is not dict or any(type(row) is not dict for row in rows):raise ValueError('Invalid saved audit objects')
        requests=[row for row in rows if row.get('event')=='native_request']
        if not requests:raise ValueError('No preserved native requests')
        groups={};enqueues={}
        for row in rows:
            if row.get('event')=='adapter_enqueue':enqueues.setdefault(row.get('observed_seq'),[]).append(row)
        for request in requests:
            fid=request.get('frame_id')
            if not _integer(fid):raise ValueError('Invalid native frame_id')
            groups.setdefault(fid,[]).append(request)
        manifests={}
        native=root/'native';_saved_checked_path(native,root)
        for directory,dirs,files in os.walk(native,followlinks=False):
            for name in dirs:_saved_checked_path(Path(directory)/name,root)
            for name in files:
                matched=re.fullmatch(r'sensor_(0|[1-9][0-9]*)\.json',name)
                if matched:
                    path=Path(directory)/name
                    if path.parent.name!='actual_frames' or not path.parent.parent.name.startswith('binding'):
                        raise ValueError('Manifest outside owned actual_frames binding')
                    manifests.setdefault(int(matched[1]),[]).append(path)
        for fid,group in sorted(groups.items()):
            try:
                raw=frames.get(str(fid))
                if (type(raw) is not dict or type(raw.get('frame_id')) is not int or raw['frame_id']!=fid
                    or raw.get('shape')!=[1080,1440,3] or any(type(v) is not int for v in raw.get('shape',[]))
                    or not _sha(raw.get('raw_rgb_sha256')) or not _number(raw.get('capture_wall'))
                    or not _number(raw.get('capture_sim_time'))):raise ValueError('Invalid original raw frame identity/shape')
                paths=manifests.get(fid,[])
                if len(paths)!=1:raise ValueError('Missing or ambiguous manifest for native frame')
                manifest_path=paths[0];manifest_bytes=_saved_read(manifest_path,root,4096)
                manifest=_saved_json(manifest_bytes.decode('utf-8'))
                expected=dict(schema='polar.sim.actual_native_frame_evidence.v1',frame_id=fid,encoding='bgr8',
                    width=1440,height=1080,stride_bytes=4320,bytes=IMAGE_BYTES,file=f'sensor_{fid}.bgr')
                if type(manifest) is not dict or set(manifest)!=set(expected)|{'sha256'}:raise ValueError('Invalid pixel manifest fields')
                for key,value in expected.items():
                    if type(manifest[key]) is not type(value) or manifest[key]!=value:raise ValueError('Invalid pixel manifest '+key)
                if not _sha(manifest['sha256']):raise ValueError('Invalid BGR manifest SHA')
                identities=[];original_time=None
                for request in group:
                    if not _sha(request.get('raw_bgr_sha256')) or request['raw_bgr_sha256']!=manifest['sha256']:
                        raise ValueError('Request BGR SHA mismatch')
                    declared_rgb=request.get('raw_rgb_sha256')
                    if declared_rgb is not None and declared_rgb!=raw['raw_rgb_sha256']:raise ValueError('Request RGB SHA mismatch')
                    if declared_rgb is None and request.get('rgb_trace_strategy')!=STRATEGY:
                        raise ValueError('Missing diagnostic RGB without reviewed archive strategy')
                    if (not _number(request.get('capture_sim_time')) or request['capture_sim_time']!=raw['capture_sim_time']
                        or not _number(request.get('observation_sim_time'))
                        or not _integer(request.get('observed_seq')) or not _integer(request.get('episode'))
                        or not _integer(request.get('binding_epoch'))):raise ValueError('Invalid native original clock/identity')
                    control_ns=round(request['observation_sim_time']*1e9)
                    if 'control_time_ns' in request and (not _integer(request['control_time_ns']) or request['control_time_ns']!=control_ns):
                        raise ValueError('Original native control clock mismatch')
                    if 'capture_wall' in request and (not _number(request['capture_wall']) or request['capture_wall']!=raw['capture_wall']):
                        raise ValueError('Original capture wall mismatch')
                    if 'exposure_timestamp_ns' in request and (not _integer(request['exposure_timestamp_ns'])
                        or request['exposure_timestamp_ns']!=round(raw['capture_sim_time']*1e9)):
                        raise ValueError('Original exposure clock mismatch')
                    robot=request.get('robot_id');kind=request.get('kind','aim')
                    if type(robot) is not str or not robot or type(kind) is not str or not kind:
                        raise ValueError('Missing native robot/kind scope')
                    time_identity=(request['capture_sim_time'],request['observation_sim_time'],control_ns,
                        request['episode'],request['binding_epoch'],robot,kind)
                    if original_time is not None and time_identity!=original_time:raise ValueError('Repeated frame changed original native time/context')
                    original_time=time_identity
                    matches=[row for row in enqueues.get(request['observed_seq'],[])
                        if type(row.get('robot_id')) is str and row['robot_id']==robot
                        and type(row.get('kind')) is str and row['kind']==kind
                        and _integer(row.get('observed_seq'))]
                    if len(matches)!=1:raise ValueError('Missing or ambiguous original enqueue')
                    enqueue=matches[0];budget=enqueue.get('sensor_budget')
                    if (type(budget) is not dict or type(budget.get('frame_id')) is not int or budget['frame_id']!=fid
                        or not _number(budget.get('capture_wall')) or not _number(budget.get('capture_sim_time'))
                        or budget.get('capture_wall')!=raw['capture_wall'] or budget.get('capture_sim_time')!=raw['capture_sim_time']
                        or not _integer(enqueue.get('episode')) or not _integer(enqueue.get('binding_epoch'))
                        or enqueue.get('episode')!=request['episode'] or enqueue.get('binding_epoch')!=request['binding_epoch']):
                        raise ValueError('Original enqueue capture/context mismatch')
                    identity={key:request[key] for key in ('observed_seq','episode','binding_epoch')}
                    if 'request_id' in request:
                        if not _integer(request['request_id']):raise ValueError('Invalid native request_id')
                        identity['request_id']=request['request_id']
                    if identity not in identities:identities.append(identity)
                image_path=manifest_path.parent/manifest['file'];bgr=_saved_read(image_path,root,IMAGE_BYTES)
                bgr_sha=hashlib.sha256(bgr).hexdigest()
                if len(bgr)!=IMAGE_BYTES or bgr_sha!=manifest['sha256']:raise ValueError('Archived BGR truncated/changed/SHA mismatch')
                rgb=bytearray(IMAGE_BYTES);rgb[0::3]=bgr[2::3];rgb[1::3]=bgr[1::3];rgb[2::3]=bgr[0::3]
                rgb_sha=hashlib.sha256(rgb).hexdigest()
                if rgb_sha!=raw['raw_rgb_sha256']:raise ValueError('Derived RGB does not match actual raw sensor SHA')
                result['proofs'].append(dict(frame_id=fid,original_capture_wall=raw['capture_wall'],
                    original_capture_sim_time=raw['capture_sim_time'],original_control_time_ns=original_time[2],
                    observation_sim_time=original_time[1],request_identities=identities,native_request_count=len(group),
                    raw_bgr_sha256=bgr_sha,derived_rgb_sha256=rgb_sha,raw_rgb_sha256=raw['raw_rgb_sha256'],
                    image=image_path.relative_to(root).as_posix(),manifest=manifest_path.relative_to(root).as_posix(),
                    manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),image_bytes=IMAGE_BYTES,shape=[1080,1440,3],strategy=STRATEGY))
            except Exception as exc:result['errors'].append(dict(frame_id=fid,error=type(exc).__name__+': '+str(exc)))
        result['clean']=not result['errors'] and len(result['proofs'])==len(groups)
    except Exception as exc:result['errors'].append(dict(error=type(exc).__name__+': '+str(exc)))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-root',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=False)
    result=audit_saved_native_pixels(args.run_root)
    (args.out/'PIXEL_AUDIT.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(clean=result['clean'],frames=len(result['proofs']),errors=result['errors'])))
    return 0 if result['clean'] else 2


if __name__=='__main__':raise SystemExit(main())
