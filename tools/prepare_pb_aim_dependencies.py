"""Fixed PB dependency source copies, with only reviewed std_msgs metadata fixes."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.prepare_pb_aim_plugin import once

PINS={'auto_aim_interfaces':'5eab0e0464b6cfae7cf8ae0599109b3f5b623e3d',
    'pb_rm_interfaces':'66c8bee0d389b0eed9e84157c26d026b95ebae4c',
    'rmoss_core':'8209ec517dfbb7ecac613cf0c9534d67ff918b7d',
    'rmoss_interfaces':'424f50c831b3e74fa72446969362cdabb2e22cd1'}
PACKAGES={'auto_aim_interfaces':('auto_aim_interfaces',''),
    'pb_rm_interfaces':('pb_rm_interfaces',''),
    'rmoss_projectile_motion':('rmoss_core','rmoss_projectile_motion')}
sha=lambda raw:hashlib.sha256(raw).hexdigest()

def metadata_overlay(package,cmake,xml):
    if package not in ('auto_aim_interfaces','pb_rm_interfaces'):raise ValueError('Unsupported dependency metadata overlay')
    cmake=once(cmake,'find_package(geometry_msgs REQUIRED)',
        'find_package(geometry_msgs REQUIRED)\nfind_package(std_msgs REQUIRED)')
    xml=once(xml,'  <depend>geometry_msgs</depend>',
        '  <depend>geometry_msgs</depend>\n  <depend>std_msgs</depend>')
    if package=='pb_rm_interfaces':
        cmake=once(cmake,'  DEPENDENCIES\n    geometry_msgs\n)',
            '  DEPENDENCIES\n    geometry_msgs\n    std_msgs\n)')
    elif cmake.count('    std_msgs\n')!=1:raise ValueError('Original auto aim std_msgs declaration changed')
    return cmake,xml

def prepare(source_root,out):
    source_root=Path(source_root).absolute();out=Path(out).absolute()
    if out.exists() or out.is_relative_to(source_root) or source_root.is_relative_to(out):
        raise ValueError('Fresh independent dependency output required')
    snapshot={};repo_rows={};operations=[]
    def git(root,*args):
        argv=['git','-c','core.autocrlf=false','-c','core.filemode=false','-C',str(root),*args]
        result=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        operations.append(dict(argv=argv,exit_code=result.returncode,stdout=result.stdout.decode('utf-8',errors='replace'),
            stderr=result.stderr.decode('utf-8',errors='replace')))
        if result.returncode:raise ValueError('Pinned dependency Git verification failed')
        return result.stdout
    for repo,pin in PINS.items():
        root=source_root/repo
        if root.is_symlink() or not root.is_dir():raise ValueError('Pinned dependency root missing or symlink')
        if git(root,'rev-parse','HEAD').decode().strip()!=pin:raise ValueError('Pinned dependency commit mismatch: '+repo)
        if git(root,'status','--porcelain','--untracked-files=no'):raise ValueError('Pinned dependency tracked edits: '+repo)
        paths=[p for p in git(root,'ls-tree','-rz','--name-only',pin).decode().split('\0') if p]
        selected_packages=[(package,subpath) for package,(name,subpath) in PACKAGES.items() if name==repo]
        copied=[]
        for rel in paths:
            wanted=[package for package,subpath in selected_packages if not subpath or rel.startswith(subpath+'/')]
            notice=rel in ('LICENSE','NOTICE','LICENSE.md','LICENSE.txt')
            if not wanted and not notice:continue
            path=root/rel
            if path.is_symlink() or not path.is_file():raise ValueError('Dependency source symlink or missing: '+rel)
            raw=path.read_bytes();blob=git(root,'show',pin+':'+rel)
            # These checkouts were explicitly acquired with autocrlf disabled.
            # No checkout normalization or model stub is accepted here.
            if raw!=blob:raise ValueError('Pinned dependency bytes differ: '+repo+'/'+rel)
            key=repo+'/'+rel;snapshot[key]=(path,raw)
            copied.append(dict(path=rel,sha256=sha(raw),bytes=len(raw)))
        repo_rows[repo]=dict(commit=pin,inputs=copied)
    out.mkdir(parents=True)
    try:
        source_manifest={}
        for package,(repo,subpath) in PACKAGES.items():
            prefix=repo+'/' + (subpath+'/' if subpath else '')
            for key,(path,raw) in snapshot.items():
                if not key.startswith(prefix):continue
                rel=key[len(prefix):]
                destination=out/'src'/package/rel;destination.parent.mkdir(parents=True,exist_ok=True)
                destination.write_bytes(raw);source_manifest[str(destination.relative_to(out)).replace('\\','/')]=dict(original_sha256=sha(raw),source=key)
        for key,(path,raw) in snapshot.items():
            if Path(key).name not in ('LICENSE','NOTICE','LICENSE.md','LICENSE.txt'):continue
            target=out/'upstream_notices'/key;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        changed={}
        for package in ('auto_aim_interfaces','pb_rm_interfaces'):
            cmake=out/'src'/package/'CMakeLists.txt';xml=out/'src'/package/'package.xml'
            original_cmake=cmake.read_bytes();original_xml=xml.read_bytes()
            c,x=metadata_overlay(package,original_cmake.decode('utf-8'),original_xml.decode('utf-8'))
            for path,original,modified in ((cmake,original_cmake,c.encode()),(xml,original_xml,x.encode())):
                path.write_bytes(modified);rel=str(path.relative_to(out)).replace('\\','/')
                changed[rel]=dict(before_sha256=sha(original),after_sha256=sha(modified),
                    reason='Declare actual std_msgs/Header dependency explicitly; no message or algorithm changes')
        for key,(path,raw) in snapshot.items():
            if path.read_bytes()!=raw:raise ValueError('Dependency source changed during preparation: '+key)
        for repo,pin in PINS.items():
            if git(source_root/repo,'rev-parse','HEAD').decode().strip()!=pin:raise ValueError('Dependency commit changed during preparation')
        generated={str(p.relative_to(out)).replace('\\','/'):sha(p.read_bytes()) for p in out.rglob('*') if p.is_file()}
        manifest=dict(schema='polar.pb-aim-dependency-metadata-overlay.v1',generator_sha256=sha(Path(__file__).read_bytes()),
            helper_sources_sha256={'tools/prepare_pb_aim_plugin.py':sha((ROOT/'tools/prepare_pb_aim_plugin.py').read_bytes())},
            source_repositories=repo_rows,source_files=source_manifest,changed=changed,generated_sha256=generated,
            message_and_solver_bytes_unchanged=True,packages=list(PACKAGES),unused_source_repo='rmoss_interfaces',
            operations=operations,build=False,ROS=False,NN=False)
        (out/'SOURCE_MANIFEST.json').write_bytes((json.dumps(manifest,indent=2)+'\n').encode())
        return manifest
    except BaseException as exc:
        (out/'PREPARE_FAILED.json').write_bytes((json.dumps(dict(error_type=type(exc).__name__,error=str(exc)))+'\n').encode())
        raise

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(argv);result=prepare(args.source_root,args.out)
    print(json.dumps(dict(schema=result['schema'],packages=result['packages'],metadata_changes=len(result['changed']),build=False)))
    return 0
if __name__=='__main__':raise SystemExit(main())
