"""Copy reviewed Humble runtime bytes to a fresh owned ext4 prefix; no nodes."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import time


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def remap_path(value,mappings):
    for source,target in sorted(mappings,key=lambda pair:len(str(pair[0])),reverse=True):
        if value==str(source) or value.startswith(str(source)+'/'):
            return str(target)+value[len(str(source)):]
    return value


def copy_tree_checked(source,destination,mappings,emit):
    source=Path(source);destination=Path(destination)
    if source.is_symlink() or not source.is_dir() or destination.exists() or destination.is_symlink():
        raise ValueError('fresh_unlinked_tree_required')
    def copy_one(src,dst):
        info=src.lstat();mode=stat.S_IMODE(info.st_mode)
        row={'source':str(src),'destination':str(dst),'source_mode':mode}
        if stat.S_ISLNK(info.st_mode):
            old=os.readlink(src);new=remap_path(old,mappings) if old.startswith('/') else old
            os.symlink(new,dst)
            if os.readlink(src)!=old or os.readlink(dst)!=new:raise ValueError('symlink_changed')
            row.update(kind='symlink',source_link=old,destination_link=new,mapped=old!=new)
        elif stat.S_ISDIR(info.st_mode):
            dst.mkdir()
            for child in sorted(src.iterdir()):copy_one(child,dst/child.name)
            shutil.copystat(src,dst,follow_symlinks=False)
            row.update(kind='directory')
        elif stat.S_ISREG(info.st_mode):
            h=hashlib.sha256()
            fd=os.open(src,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
            with os.fdopen(fd,'rb') as inp,dst.open('xb') as out:
                for block in iter(lambda:inp.read(1024*1024),b''):
                    h.update(block);out.write(block)
            shutil.copystat(src,dst,follow_symlinks=False)
            before=h.hexdigest();after=digest(src);copied=digest(dst)
            if before!=after or before!=copied:raise ValueError('copied_file_sha_mismatch')
            row.update(kind='file',bytes=info.st_size,source_sha256=before,destination_sha256=copied)
        else:raise ValueError('unsupported_source_node')
        row['destination_mode']=stat.S_IMODE(dst.lstat().st_mode)
        if row['destination_mode']!=mode:raise ValueError('copied_mode_mismatch')
        emit(row)
    copy_one(source,destination)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--environment',type=Path,required=True);p.add_argument('--environment-sha256',required=True)
    p.add_argument('--livox-install',type=Path,required=True);p.add_argument('--destination',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);args=p.parse_args(argv)
    if sys.platform!='linux':p.error('Linux ext4 ownership required')
    target=args.destination
    if not target.is_absolute() or target.parent!=Path('/root') or not target.name.startswith('polar-humble-ext4-'):
        p.error('fresh /root/polar-humble-ext4-* required')
    if target.exists() or target.is_symlink() or args.out.exists():p.error('fresh target and evidence required')
    if digest(args.environment)!=args.environment_sha256:raise ValueError('environment_sha_changed')
    original=json.loads(args.environment.read_bytes());source=args.environment.parent
    mapping=[(source/'venv',target/'venv'),(source/'prefix',target/'prefix'),
        (source/'compat',target/'compat'),(args.livox_install,target/'livox_ros_driver2')]
    root_mount=[line.split() for line in Path('/proc/mounts').read_text().splitlines() if line.split()[1]=='/']
    if len(root_mount)!=1 or root_mount[0][2]!='ext4':raise ValueError('destination_root_not_ext4')
    args.out.mkdir(parents=True);target.mkdir(mode=0o700);started=time.perf_counter()
    record={'schema':'polar.humble-ext4-runtime.v1','status':'copying','source_environment_sha256':args.environment_sha256,
        'destination':str(target),'filesystem':root_mount[0],'navigation_nodes_started':False,'physics_steps':0,
        'mappings':[{'source':str(a),'destination':str(b)} for a,b in mapping],'files':0,'bytes':0,'symlinks':0}
    try:
        with (args.out/'COPY_FILES.jsonl').open('x',buffering=256*1024) as proof:
            def emit(row):
                proof.write(json.dumps(row,separators=(',',':'))+'\n')
                if row['kind']=='file':record['files']+=1;record['bytes']+=row['bytes']
                if row['kind']=='symlink':record['symlinks']+=1
            for src,dst in mapping:
                print('COPY',str(src),str(dst),flush=True);copy_tree_checked(src,dst,mapping,emit)
        old_pth=source/'venv/lib/python3.10/site-packages/owned_humble.pth'
        new_pth=target/'venv/lib/python3.10/site-packages/owned_humble.pth'
        raw=old_pth.read_bytes()
        import_paths=[remap_path(line,mapping) for line in raw.decode().splitlines()]
        # Replace the old explicit ROS PYTHONPATH with the same checked paths in
        # the new owned .pth; JSON adapter intentionally scrubs PYTHONPATH.
        import_paths += [remap_path(part,mapping) for part in original['process_environment'].get('PYTHONPATH','').split(':') if part]
        derived='\n'.join(dict.fromkeys(import_paths))+'\n'
        new_pth.write_text(derived)
        pth_record={'source':str(old_pth),'destination':str(new_pth),'source_sha256':hashlib.sha256(raw).hexdigest(),
            'destination_sha256':digest(new_pth),'reason':'explicit owned import path relocation; /opt ROS paths retained'}
        (args.out/'DERIVED_PTH.json').write_text(json.dumps(pth_record,indent=2))
        process_env={key:':'.join(remap_path(part,mapping) for part in val.split(':')) for key,val in original['process_environment'].items()}
        process_env.pop('PYTHONPATH',None);process_env['PYTHONDONTWRITEBYTECODE']='1'
        compatible={'venv_python':str(target/'venv/bin/python'),'process_environment':process_env,
            'hardware_or_nodes_started':False,'derived_from_sha256':args.environment_sha256,
            'storage_profile':'ext4_byte_identical_runtime_v1','copy_manifest_sha256':digest(args.out/'COPY_FILES.jsonl'),
            'derived_pth_sha256':pth_record['destination_sha256']}
        (args.out/'ENVIRONMENT_COMPAT.json').write_text(json.dumps(compatible,indent=2))
        record.update(status='copied_and_verified',copy_manifest_sha256=compatible['copy_manifest_sha256'],
            environment_sha256=digest(args.out/'ENVIRONMENT_COMPAT.json'),derived_pth=pth_record,
            source_environment_unchanged=digest(args.environment)==args.environment_sha256,
            limitation='console script shebangs and CMake export text remain original bytes; use explicit new interpreter, runtime LD and AMENT paths, not copied build scripts')
    except BaseException as error:
        record.update(status='failed',error=repr(error));raise
    finally:
        record['elapsed_s']=time.perf_counter()-started
        (args.out/'MIGRATION_RESULT.json').write_text(json.dumps(record,indent=2));print(json.dumps(record),flush=True)


if __name__=='__main__':main()
