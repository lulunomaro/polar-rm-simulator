#!/usr/bin/env python3
"""Prepare a pinned upstream aim example. No compiler, download or inference."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
HEAD='bd9f5e798fa3c6dd3b483ae6627796afb41c608d'
MODEL_BLOBS={'yolov5.xml':'88b2f682f19dd232172fd8f3b8f5b4e1423bf8e5',
             'yolov5.bin':'e5f842740d73ceb9cbd0e21d63f2f166ae175014',
             'tiny_resnet.onnx':'1c2e6ec60e7c97e510885b2949a9fea101cc4f49'}
LOCAL_SOURCES=('CMakeLists.txt','runner.cpp','logger_stderr.cpp','jsonl_wrapper.py','fmt_armor_name_compat.hpp')
CPP=('tasks/auto_aim/armor.cpp','tasks/auto_aim/classifier.cpp','tasks/auto_aim/detector.cpp',
     'tasks/auto_aim/solver.cpp','tasks/auto_aim/target.cpp','tasks/auto_aim/tracker.cpp',
     'tasks/auto_aim/yolos/yolov5.cpp','tasks/auto_aim/planner/planner.cpp',
     'tasks/auto_aim/planner/tinympc/admm.cpp','tasks/auto_aim/planner/tinympc/tiny_api.cpp',
     'tasks/auto_aim/planner/tinympc/rho_benchmark.cpp','tasks/auto_aim/planner/tinympc/codegen.cpp','tools/extended_kalman_filter.cpp',
     'tools/math_tools.cpp','tools/img_tools.cpp','tools/trajectory.cpp')


def sha(raw):return hashlib.sha256(raw).hexdigest()
def blob(raw):return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()


def head_bytes(raw,expected,*,text):
    """Never normalize binary weights; CRLF text canonicalization is explicit."""
    if blob(raw)==expected:return raw,'original_git_bytes'
    normalized=raw.replace(b'\r\n',b'\n') if text else raw
    if text and blob(normalized)==expected:return normalized,'crlf_to_original_git_lf'
    raise ValueError('upstream_blob_mismatch')


def checked_read(path,max_bytes):
    path=Path(os.path.abspath(path))
    for part in (path,*path.parents):
        row=part.lstat()
        if part.is_symlink() or getattr(row,'st_file_attributes',0)&0x400:raise ValueError('source_reparse_or_symlink')
    before=path.stat()
    if not path.is_file() or before.st_size>max_bytes:raise ValueError('source_file_or_bound')
    raw=path.read_bytes();after=path.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns) or len(raw)!=before.st_size:
        raise ValueError('source_changed_during_read')
    return raw


def git(source,*args):
    result=subprocess.run(['git','-C',str(source),*args],capture_output=True,check=True)
    return result.stdout.decode('utf-8').strip()


def calibration_config(original,*,model_dir,enemy_color,camera):
    # Thresholds, tracking, MPC weights/delays remain the original source values.
    if enemy_color not in ('red','blue'):raise ValueError('enemy_color_enum')
    if type(camera) is not dict or set(camera)!={'width','height','fx','fy','cx','cy','distortion'}:
        raise ValueError('camera_profile_fields')
    if type(camera['width']) is not int or camera['width']!=1440 or type(camera['height']) is not int or camera['height']!=1080:
        raise ValueError('upstream_tracker_resolution_1440_1080')
    import math
    for name in ('fx','fy','cx','cy'):
        if type(camera[name]) not in (int,float) or not math.isfinite(camera[name]):raise ValueError('camera_profile_finite')
    if min(camera['fx'],camera['fy'])<=0 or type(camera['distortion']) is not list or len(camera['distortion'])!=5:
        raise ValueError('camera_profile_intrinsics')
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in camera['distortion']):raise ValueError('camera_distortion_finite')
    config=dict(original)
    overrides=dict(device='CPU',enemy_color=enemy_color,
        yolov5_model_path=str(model_dir/'yolov5.xml'),classify_model=str(model_dir/'tiny_resnet.onnx'),
        camera_matrix=[camera['fx'],0,camera['cx'],0,camera['fy'],camera['cy'],0,0,1],
        distort_coeffs=camera['distortion'],R_gimbal2imubody=[1,0,0,0,1,0,0,0,1],
        R_camera2gimbal=[0,0,1,-1,0,0,0,-1,0],t_camera2gimbal=[.24,0,.06],
        yaw_offset=0.,pitch_offset=0.)
    config.update(overrides)
    changes={key:dict(original=original.get(key),adapted=value) for key,value in overrides.items()}
    return config,changes


def write_instance(prepared,binary,out,*,source_identity_sha256,repo_root=ROOT):
    """Post-build registration input only; this does not claim live qualification."""
    from adapters.native.tongji.jsonl_wrapper import strict_json,validate_instance
    prepared=Path(os.path.abspath(prepared));out=Path(os.path.abspath(out));binary=Path(os.path.abspath(binary))
    if out.exists() or (out.parent/'evidence').exists():raise ValueError('fresh_instance_required')
    identity_raw=checked_read(prepared/'SOURCE_IDENTITY.json',256*1024)
    if sha(identity_raw)!=source_identity_sha256:raise ValueError('prepared_identity_changed')
    identity=strict_json(identity_raw)
    if identity.get('schema')!='polar.owned-native-aim-preparation.v1' or identity.get('source_head')!=HEAD:
        raise ValueError('prepared_identity_schema')
    config=prepared/'runtime_config.yaml';config_raw=checked_read(config,65536)
    if sha(config_raw)!=identity['runtime_config_sha256']:raise ValueError('prepared_config_changed')
    for rel,proof in identity['upstream'].items():
        if sha(checked_read(prepared/'upstream'/rel,2*1024*1024))!=proof['prepared_sha256']:raise ValueError('prepared_source_changed')
    for name,digest in identity['adapter_sources'].items():
        if sha(checked_read(prepared/name,256*1024))!=digest:raise ValueError('prepared_adapter_changed')
    refs={name:dict(path=str(prepared/'models'/name),sha256=proof['prepared_sha256']) for name,proof in identity['models'].items()}
    value=dict(schema='polar.owned-native-aim-instance.v1',repo_root=str(Path(repo_root).absolute()),
        binary=str(binary),binary_sha256=sha(checked_read(binary,64*1024*1024)),config=str(config),
        config_sha256=sha(config_raw),calibration=identity['calibration'],models=refs,
        enemy_color=strict_json(config_raw)['enemy_color'],evidence_out=str(out.parent/'evidence'))
    validate_instance(value)
    with out.open('x',encoding='utf-8') as stream:stream.write(json.dumps(value,indent=2,allow_nan=False)+'\n')
    return value


def prepare(source,model_root,out,*,camera,enemy_color,classifier=None):
    source=Path(os.path.abspath(source));model_root=Path(os.path.abspath(model_root));out=Path(os.path.abspath(out))
    for root in (source,model_root,out.parent):
        for part in (root,*root.parents):
            row=part.lstat()
            if part.is_symlink() or getattr(row,'st_file_attributes',0)&0x400:raise ValueError('root_alias')
    if git(source,'rev-parse','HEAD')!=HEAD:raise ValueError('fixed_upstream_head_required')
    if out.exists():raise ValueError('fresh_output_required')
    tree={}
    for line in git(source,'ls-tree','-r',HEAD).splitlines():
        metadata,rel=line.split('\t',1);mode,kind,digest=metadata.split()
        if kind=='blob':tree[rel]=(mode,digest)
    files=set(CPP)|{'LICENSE','configs/standard3.yaml'}
    for rel in tree:
        if rel.endswith(('.hpp','.h')) and rel.startswith(('tasks/auto_aim/','tasks/omniperception/','tools/','io/')):
            files.add(rel)
    originals={};source_hashes={}
    for rel in sorted(files):
        if tree[rel][0] not in ('100644','100755'):raise ValueError('upstream_regular_file_required')
        raw=checked_read(source/rel,2*1024*1024)
        normalized,policy=head_bytes(raw,tree[rel][1],text=True)
        originals[rel]=normalized
        source_hashes[rel]=dict(git_blob=tree[rel][1],input_sha256=sha(raw),prepared_sha256=sha(normalized),policy=policy)
    models={};model_proofs={}
    for name,digest in MODEL_BLOBS.items():
        if tree['assets/'+name][1]!=digest:raise ValueError('expected_model_tree_identity')
        original_path=Path(classifier) if name=='tiny_resnet.onnx' and classifier is not None else model_root/name
        raw=checked_read(original_path,32*1024*1024)
        canonical,policy=head_bytes(raw,digest,text=name.endswith('.xml'))
        models[name]=canonical;model_proofs[name]=dict(input_path=str(original_path),git_blob=digest,input_sha256=sha(raw),prepared_sha256=sha(canonical),bytes=len(canonical),policy=policy)
    import yaml
    original=yaml.safe_load(originals['configs/standard3.yaml'])
    config,changes=calibration_config(original,model_dir=out/'models',enemy_color=enemy_color,camera=camera)
    local=ROOT/'adapters/native/tongji'
    adapters={name:checked_read(local/name,256*1024) for name in LOCAL_SOURCES}
    out.mkdir(parents=True,exist_ok=False)
    for rel,raw in originals.items():
        target=out/'upstream'/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    for name,raw in models.items():
        target=out/'models'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    for name,raw in adapters.items():(out/name).write_bytes(raw)
    # JSON is valid YAML and preserves original numeric parameter values.
    (out/'runtime_config.yaml').write_text(json.dumps(config,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    metadata=dict(schema='polar.owned-native-aim-preparation.v1',source_head=HEAD,source_license='MIT',
        upstream=source_hashes,models=model_proofs,algorithm_sources=list(CPP),
        adapter_sources={name:sha(raw) for name,raw in adapters.items()},
        build_boundary_compatibility=dict(id='fmt_unscoped_armor_name_numeric_v1',
            header='fmt_armor_name_compat.hpp',header_sha256=sha(adapters['fmt_armor_name_compat.hpp']),
            translation_units=['tasks/auto_aim/detector.cpp','tasks/auto_aim/yolos/yolov5.cpp'],
            behavior='fmt::formatter<int> with static_cast<int>(ArmorName); no algorithm/source/model changes'),
        generator_sha256=sha(Path(__file__).read_bytes()),calibration=camera,configuration_changes=changes,
        runtime_config_sha256=sha((out/'runtime_config.yaml').read_bytes()),
        capabilities=dict(contract='camera_gimbal_v1',resolution=[1440,1080],stationary_capture_origin=True,
            supported_modes=['gimbal_target'],fire_authority='manual_only',hardware_io=False,
            moving_global_localization=False,inference_during_prepare=False),
        qualification='Prepared source/model/calibration only; no compilation/inference/client/live acceptance',
        build_commands_not_executed=[['cmake','-S',str(out),'-B',str(out/'build'),'-DCMAKE_BUILD_TYPE=Release','-DPOLAR_UPSTREAM_DIR='+str(out/'upstream')],
            ['cmake','--build',str(out/'build'),'--parallel','2']])
    (out/'SOURCE_IDENTITY.json').write_text(json.dumps(metadata,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    if any(sha(checked_read(source/rel,2*1024*1024))!=proof['input_sha256'] for rel,proof in source_hashes.items()):
        raise ValueError('upstream_source_changed_during_prepare')
    if any(sha(checked_read(proof['input_path'],32*1024*1024))!=proof['input_sha256'] for proof in model_proofs.values()):
        raise ValueError('model_source_changed_during_prepare')
    return metadata


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path);parser.add_argument('--model-root',type=Path)
    parser.add_argument('--out',type=Path);parser.add_argument('--camera-profile',type=Path)
    parser.add_argument('--classifier',type=Path,help='Optional separately verified original tiny_resnet.onnx')
    parser.add_argument('--enemy-color',choices=('red','blue'),default='blue')
    parser.add_argument('--prepare',action='store_true');args=parser.parse_args(argv)
    if not args.prepare:
        print(json.dumps(dict(source_head=HEAD,required_models=MODEL_BLOBS,algorithm_sources=CPP,
            scopes='Prepare only, explicit camera profile; no hardware/NN/compiler',required_dependencies=['OpenCV4','Eigen3','OpenVINO','yaml-cpp','fmt','spdlog','nlohmann_json','OpenSSL-Crypto']),indent=2));return 0
    for name in ('source_root','model_root','out','camera_profile'):
        if getattr(args,name) is None:parser.error('--'+name.replace('_','-')+' required')
    from adapters.native.tongji.jsonl_wrapper import strict_json
    camera=strict_json(checked_read(args.camera_profile,8192))
    print(json.dumps(prepare(args.source_root,args.model_root,args.out,camera=camera,enemy_color=args.enemy_color,classifier=args.classifier),indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
