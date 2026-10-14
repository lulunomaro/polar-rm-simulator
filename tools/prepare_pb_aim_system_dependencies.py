"""Private apt plan and SHA-verified extraction for seven PB Humble packages.

Only existing signed index snapshots are used. No apt update/install, setup
scripts, hardware processes or changes to the original Humble prefix.
APT resolves against the existing installed system; complete extraction does
not imply this new prefix is a standalone transitive runtime closure.
Execution belongs to the root's Ubuntu22.04 resource window.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from tools.build_pb_aim_plugins import PACKAGES,manifest_files,read_checked,digest,literal_json,filesystem_type,run_owned

SIGNED_INDEX_SHA='e1648aac9fd647861fe9534f9da02a54baeef992e6f40c606e871ef5f05a78cb'
ROS_KEY_SHA='4a91c49af0d6f0016108b93698782b596c27ccd836937e18e0e36c3347dc602f'
OFFICIAL_HOSTS={'archive.ubuntu.com','security.ubuntu.com','packages.ros.org'}
SCHEMA='polar.pb-aim-system-dependencies.v1'

def requested_packages(source,dependencies):
    deps=set()
    for kind,root in (('source',source),('dependencies',dependencies)):
        _,files=manifest_files(root,kind)
        for rel,raw in files.items():
            if rel.startswith('src/') and rel.endswith('/package.xml'):
                deps.update(e.text for e in ET.fromstring(raw) if e.tag in ('depend','build_depend','build_export_depend','buildtool_depend','exec_depend'))
    deps-=set(PACKAGES);deps.discard('eigen');deps.add('ament_cmake_auto')
    if any(not re.fullmatch('[a-z][a-z0-9_]*',name) for name in deps):raise ValueError('unexpected_ros_dependency_name')
    return sorted({'ros-humble-'+name.replace('_','-') for name in deps}|{'libeigen3-dev','libopencv-dev','nlohmann-json3-dev'})

def parse_uri_lines(text):
    rows=[]
    for line in text.splitlines():
        match=re.fullmatch(r"'([^']+)' (\S+) ([0-9]+) (MD5Sum|SHA256):([0-9a-f]+)",line)
        if not match:continue
        url=urllib.parse.urlparse(match[1]);filename=match[2]
        if (url.scheme not in ('http','https') or url.hostname not in OFFICIAL_HOSTS or url.username or url.password
            or url.port not in (None,80,443) or url.query or url.fragment or '/ubuntu/' not in url.path):
            raise ValueError('nonofficial_deb_url')
        if Path(filename).name!=filename or not filename.endswith('.deb'):raise ValueError('unsafe_deb_filename')
        rows.append(dict(url=match[1],file=filename,bytes=int(match[3]),uri_hash_kind=match[4],uri_hash=match[5]))
    return rows

def bind_signed_debs(rows,package_text,index_name):
    wanted={urllib.parse.unquote(urllib.parse.urlparse(row['url']).path).split('/ubuntu/',1)[1]:row for row in rows}
    for block in package_text.split('\n\n'):
        fields={}
        for line in block.splitlines():
            if line and not line.startswith(' ') and ': ' in line:
                key,value=line.split(': ',1);fields[key]=value
        if fields.get('Filename') not in wanted:continue
        row=wanted[fields['Filename']]
        if int(fields['Size'])!=row['bytes']:continue
        expected=fields.get('MD5sum' if row['uri_hash_kind']=='MD5Sum' else 'SHA256')
        if expected!=row['uri_hash']:continue
        if not re.fullmatch('[0-9a-f]{64}',fields['SHA256']):raise ValueError('signed_sha_missing')
        if 'sha256' in row and row['sha256']!=fields['SHA256']:raise ValueError('ambiguous_signed_deb')
        row.update(package=fields['Package'],version=fields['Version'],sha256=fields['SHA256'],index=index_name)

def private_apt_options(out):
    out=Path(out)
    return ['-o','Dir::State::lists='+str(out/'apt-lists'),'-o','Dir::State::status=/var/lib/dpkg/status',
        '-o','Dir::Etc::sourcelist='+str(out/'apt-sources.list'),'-o','Dir::Etc::sourceparts=-',
        '-o','Dir::Cache='+str(out/'apt-cache'),'-o','APT::Get::List-Cleanup=false']

def prefix_files(prefix):
    rows={}
    for path in sorted(Path(prefix).rglob('*')):
        rel=path.relative_to(prefix).as_posix()
        if path.is_symlink():rows[rel]=dict(type='symlink',target=os.readlink(path))
        elif path.is_file():rows[rel]=dict(type='file',sha256=digest(path.read_bytes()),bytes=path.stat().st_size)
    return rows

def checked_extra_prefix(manifest_path,sha):
    path=Path(manifest_path).absolute();value=literal_json(read_checked(path,sha))
    if value.get('schema')!=SCHEMA or value.get('complete') is not True or value.get('maintainer_scripts_executed') is not False:
        raise ValueError('complete_owned_extra_prefix_required')
    prefix=Path(value['prefix'])
    if prefix!=path.parent/'prefix' or prefix.is_symlink() or not prefix.is_dir():raise ValueError('extra_prefix_scope')
    actual=prefix_files(prefix)
    if actual!=value['files']:raise ValueError('extra_prefix_byte_or_link_changed')
    return prefix,value

def download_candidates(url):
    parsed=urllib.parse.urlparse(url)
    # Exact same host/path only. Prefer TLS because the observed WSL HTTP
    # route timed out. One final TLS retry, never an unrelated mirror.
    secure=parsed._replace(scheme='https').geturl()
    return [secure,url,secure] if parsed.scheme=='http' else [url,url]

def download_verified(row,target,*,caches=(),open_url=None,clock=time.perf_counter,on_attempt=None):
    target=Path(target);open_url=urllib.request.urlopen if open_url is None else open_url
    attempts=row.setdefault('download_attempts',[]);started=clock();deadline=started+180.
    def save(value):
        attempts.append(value)
        if on_attempt is not None:on_attempt()
    if target.exists():
        raw=read_checked(target,row['sha256'])
        if len(raw)!=row['bytes']:raise ValueError('existing_deb_size_mismatch')
        save(dict(kind='existing_output',verified_sha256=row['sha256'],bytes=len(raw)))
        return target
    for cache in caches:
        file=Path(cache)/row['file']
        if not file.exists():continue
        try:
            raw=read_checked(file,row['sha256'])
            if len(raw)!=row['bytes']:raise ValueError('cache_size_mismatch')
            with target.open('xb') as handle:handle.write(raw)
            read_checked(file,row['sha256']);read_checked(target,row['sha256'])
            save(dict(kind='cache',path=str(file),verified_sha256=row['sha256'],bytes=len(raw),ok=True))
            row['download_final_url']=None;row['download_source']='verified_full_cache';return target
        except (ValueError,OSError) as exc:
            save(dict(kind='cache',path=str(file),ok=False,error_type=type(exc).__name__,error=str(exc)))
            if target.exists():raise ValueError('cache_copy_failed_after_creation') from exc
    origin=urllib.parse.urlparse(row['url'])
    for number,url in enumerate(download_candidates(row['url'])):
        attempt_start=clock()
        if attempt_start>=deadline:break
        partial=target.with_name(target.name+'.attempt'+str(number+1)+'.partial')
        event=dict(kind='network',attempt=number+1,requested_url=url,original_url=row['url'],ok=False,bytes=0)
        try:
            remaining=deadline-clock()
            if remaining<=0:raise TimeoutError('deb_total_budget_before_open')
            with open_url(url,timeout=min(30.,remaining)) as response,partial.open('xb') as handle:
                final=response.geturl();actual=urllib.parse.urlparse(final)
                if (actual.hostname!=origin.hostname or actual.path!=origin.path or actual.query or actual.fragment
                    or actual.username or actual.password or actual.scheme not in ('http','https') or actual.port not in (None,80,443)):
                    raise ValueError('redirect_outside_official_exact_asset')
                event['response_final_url']=final
                read=getattr(response,'read1',response.read)
                while True:
                    if clock()>=deadline or clock()-attempt_start>=90.:raise TimeoutError('deb_attempt_or_total_budget')
                    chunk=read(65536)
                    if not chunk:break
                    event['bytes']+=len(chunk)
                    if event['bytes']>row['bytes']:raise ValueError('deb_signed_size_exceeded')
                    handle.write(chunk)
            raw=partial.read_bytes()
            if clock()>=deadline or clock()-attempt_start>=90.:raise TimeoutError('deb_completed_after_budget')
            if len(raw)!=row['bytes'] or digest(raw)!=row['sha256']:raise ValueError('deb_SHA_or_size_mismatch:'+row['file'])
            partial.rename(target);event.update(ok=True,verified_sha256=row['sha256'],elapsed_seconds=clock()-attempt_start)
            save(event);row['download_final_url']=event['response_final_url'];row['download_source']='network';return target
        except (OSError,ValueError,TimeoutError) as exc:
            event.update(error_type=type(exc).__name__,error=str(exc),elapsed_seconds=clock()-attempt_start)
            if partial.exists():event.update(partial_bytes=partial.stat().st_size,partial_sha256=digest(partial.read_bytes()))
            save(event)
    raise TimeoutError('deb_verified_download_exhausted:'+row['file'])

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--signed-snapshots',type=Path,default=ROOT/'artifacts/pb2025-humble-environment-20261013')
    parser.add_argument('--source',type=Path,default=ROOT/'artifacts/pb2025-aim-source-20261014-03')
    parser.add_argument('--dependencies',type=Path,default=ROOT/'artifacts/pb2025-aim-dependency-compat-20261014-03')
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--run',action='store_true',required=True)
    parser.add_argument('--cache',type=Path,action='append',default=[])
    args=parser.parse_args(argv);out=args.out.absolute();old=args.signed_snapshots.absolute()
    if sys.platform!='linux' or 'VERSION_ID="22.04"' not in Path('/etc/os-release').read_text():raise ValueError('Ubuntu22.04 required')
    if (out.exists() or any(p.is_symlink() for p in (out,*out.parents)) or not str(out).startswith('/root/polar-pb-aim-system-deps-')
        or filesystem_type(str(out),Path('/proc/self/mountinfo').read_text())!='ext4'):raise ValueError('fresh_owned_ext4_root_required')
    signedraw=read_checked(old/'SIGNED_INDEX_MANIFEST.json',SIGNED_INDEX_SHA);signed=literal_json(signedraw)
    key=read_checked(old/'ros-archive-keyring.gpg',ROS_KEY_SHA)
    requested=requested_packages(args.source,args.dependencies)
    out.mkdir(parents=True);(out/'apt-lists').mkdir();(out/'apt-cache/archives/partial').mkdir(parents=True)
    (out/'debs').mkdir();prefix=out/'prefix';prefix.mkdir()
    (out/'ros-archive-keyring.gpg').write_bytes(key);(out/'SIGNED_INDEX_MANIFEST.json').write_bytes(signedraw)
    commands=[];inputs={str(old/'SIGNED_INDEX_MANIFEST.json'):SIGNED_INDEX_SHA,
        str(old/'ros-archive-keyring.gpg'):ROS_KEY_SHA};planned=[];complete=False;error=None
    def run(command,name,timeout=60):
        row=run_owned(command,dict(os.environ),out/(name+'.log'),timeout);commands.append(row)
        if row['exit_code']!=0 or row['error'] or not row['cleanup']['clean']:raise ValueError('command_failed:'+name)
        return (out/(name+'.log')).read_text()
    try:
        rows=list(signed['ubuntu_signed_packages'])+[dict(file='packages.ros.org_ros2_ubuntu_dists_jammy_main_binary-amd64_Packages',
            sha256=signed['ros_packages_sha256'],release='packages.ros.org_ros2_ubuntu_dists_jammy_InRelease')]
        releases=set()
        for row in rows:
            filename=row['file'];release=row['release']
            if Path(filename).name!=filename or Path(release).name!=release:raise ValueError('signed_index_path')
            if release not in releases:
                source=old/'apt-lists'/release;raw=source.read_bytes();inputs[str(source)]=digest(raw)
                (out/'apt-lists'/release).write_bytes(raw)
                keyring=out/'ros-archive-keyring.gpg' if release.startswith('packages.ros.org') else Path('/usr/share/keyrings/ubuntu-archive-keyring.gpg')
                run(['/usr/bin/gpgv','--keyring',str(keyring),str(out/'apt-lists'/release)],'signature-'+str(len(releases)))
                releases.add(release)
            raw=read_checked(old/'apt-lists'/filename,row['sha256'])
            relative=filename.split('_dists_',1)[1].split('_',1)[1].replace('_','/')
            match=re.search(r'^ ([a-f0-9]{64}) +([0-9]+) '+re.escape(relative)+r'$',(out/'apt-lists'/release).read_text(),re.M)
            if not match or match[1]!=digest(raw) or int(match[2])!=len(raw):raise ValueError('signed_release_index_mismatch:'+filename)
            inputs[str(old/'apt-lists'/filename)]=digest(raw);(out/'apt-lists'/filename).write_bytes(raw)
        sources=''.join('deb http://archive.ubuntu.com/ubuntu/ '+suite+' main restricted universe multiverse\n' for suite in ('jammy','jammy-updates','jammy-backports'))
        sources+='deb http://security.ubuntu.com/ubuntu/ jammy-security main restricted universe multiverse\n'
        sources+='deb [signed-by='+str(out/'ros-archive-keyring.gpg')+'] http://packages.ros.org/ros2/ubuntu jammy main\n'
        (out/'apt-sources.list').write_bytes(sources.encode())
        status=Path('/var/lib/dpkg/status');inputs[str(status)]=digest(status.read_bytes())
        options=private_apt_options(out)
        run(['/usr/bin/apt-get',*options,'--simulate','--no-install-recommends','--reinstall','install',*requested],'apt-simulate')
        uris=run(['/usr/bin/apt-get',*options,'--print-uris','--yes','--download-only','--no-install-recommends','--reinstall','install',*requested],'apt-print-uris')
        planned=parse_uri_lines(uris)
        if not planned:raise ValueError('empty_download_plan')
        for index in sorted((out/'apt-lists').glob('*_Packages')):bind_signed_debs(planned,index.read_text(),index.name)
        if any('sha256' not in row for row in planned):raise ValueError('deb_missing_signed_SHA')
        (out/'DOWNLOAD_PLAN.json').write_bytes((json.dumps(planned,indent=2)+'\n').encode())
        for number,row in enumerate(planned):
            def save_progress():(out/'DOWNLOAD_PROGRESS.json').write_bytes((json.dumps(planned,indent=2)+'\n').encode())
            file=download_verified(row,out/'debs'/row['file'],caches=[old/'debs',*args.cache],on_attempt=save_progress)
            run(['/usr/bin/dpkg-deb','--extract',str(file),str(prefix)],'extract-'+str(number))
            row['download_and_extract_complete']=True
            (out/'DOWNLOAD_PROGRESS.json').write_bytes((json.dumps(planned,indent=2)+'\n').encode())
        for path,wanted in inputs.items():read_checked(path,wanted)
        requested_packages(args.source,args.dependencies)
        complete=True
    except BaseException as exc:error=type(exc).__name__+':'+str(exc)
    finally:
        record=dict(schema=SCHEMA,complete=complete,error=error,prefix=str(prefix),files=prefix_files(prefix),
            requested=requested,packages=planned,commands=commands,input_files_sha256=inputs,
            signed_index_manifest_sha256=SIGNED_INDEX_SHA,ros_key_sha256=ROS_KEY_SHA,
            tool_sha256=digest(Path(__file__).read_bytes()),helper_sha256=digest((ROOT/'tools/build_pb_aim_plugins.py').read_bytes()),
            maintainer_scripts_executed=False,
            system_install=False,original_prefix_modified=False,nodes_started=False,model_loaded=False)
        file=out/'DEPENDENCY_PREFIX.json';file.write_bytes((json.dumps(record,indent=2)+'\n').encode())
        print(json.dumps(dict(complete=complete,error=error,manifest=str(file),manifest_sha256=digest(file.read_bytes()))),flush=True)
    return 0 if complete else 2

if __name__=='__main__':raise SystemExit(main())
