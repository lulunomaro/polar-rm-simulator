"""Literal failed/successful quality reports, with independent raw verification."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
FILES=('acceptance_preset.log','source_provenance.log','interface_static.log','pytest.log','pytest.xml','manifest.json','preset.json')


def sha(raw):return hashlib.sha256(raw).hexdigest()


def archive(directory,label,quality=True):
    if not re.fullmatch('[a-z][a-z0-9]{0,7}',label):raise ValueError('short local archive label required')
    base=Path(directory).absolute()
    if not base.resolve().is_relative_to(ROOT/'artifacts'):raise ValueError('quality report must be inside owned artifacts')
    for component in (base,*base.parents):
        if component.is_symlink() or (hasattr(component,'is_junction') and component.is_junction()):raise ValueError('quality source alias')
    manifest=HERE/'PRESERVATION_MANIFEST.json'
    previous=json.loads(manifest.read_text()) if manifest.exists() else dict(files=[])
    rows=previous['files']
    names=FILES if quality else tuple(sorted(p.name for p in base.iterdir() if p.is_file()))
    for name in names:
        src=base/name
        if src.suffix not in ('.json','.log','.xml','.py'):raise ValueError('only explicit text report/source evidence allowed')
        if src.is_symlink():raise ValueError('report source link')
        raw=src.read_bytes()
        if len(raw)>4*1024*1024:raise ValueError('bounded quality text exceeded')
        text=raw.decode('utf8',errors='ignore')
        if re.search(r'Bearer [A-Za-z0-9._~-]{16,}|"(?:credential|admission_credential|password|api_key)"\s*:\s*"[A-Za-z0-9._~-]{16,}"',text,re.I):
            raise ValueError('literal secret in quality report')
        compressed=len(raw)>=65536
        dest=HERE/label/(name+'.gz' if compressed else name)
        if len(str(dest))>=240:raise ValueError('short archive path required')
        if compressed:
            stream=io.BytesIO()
            with gzip.GzipFile(filename='',mode='wb',fileobj=stream,mtime=0,compresslevel=3) as handle:handle.write(raw)
            encoded=stream.getvalue()
        else:encoded=raw
        if dest.exists():
            if dest.read_bytes()!=encoded:raise ValueError('immutable quality record already differs')
        else:
            dest.parent.mkdir(parents=True,exist_ok=True)
            with dest.open('xb') as stream:stream.write(encoded)
        stored=dest.read_bytes();restored=gzip.decompress(stored) if compressed else stored
        if restored!=raw or src.read_bytes()!=raw:raise ValueError('literal source/stored bytes changed')
        row=dict(source=src.relative_to(ROOT).as_posix(),stored_path=dest.relative_to(HERE).as_posix(),
                 original_bytes=len(raw),original_sha256=sha(raw),stored_bytes=len(stored),stored_sha256=sha(stored),
                 encoding='gzip_mtime0' if compressed else 'original_bytes',archive_input_unchanged=True)
        old=next((r for r in rows if r['stored_path']==row['stored_path']),None)
        if old is not None:
            if old!=row:raise ValueError('quality metadata changed')
        else:rows.append(row)
    groups=previous.get('runs',{})
    if quality:
        run=json.loads((base/'manifest.json').read_text())
        summary=dict(source_manifest=base.relative_to(ROOT).as_posix()+'/manifest.json',status=run['status'],
                     step_exit_codes={s['name']:s['exit_code'] for s in run['steps']},
                     source_unchanged_during_checks=run.get('source_unchanged_during_checks','not_recorded'),
                     milestone_accepted=run.get('milestone_accepted',False))
    else:
        summary=dict(source=base.relative_to(ROOT).as_posix(),scope='Actual Windows loopback HTTP repair only; not quality suite/nav2/ROS/WSL',
                     original_result_sha256=sha((base/'RESULT.json').read_bytes()))
    if label in groups and groups[label]!=summary:raise ValueError('quality run summary changed')
    groups[label]=summary
    report=dict(schema='polar.quality.wsl-navigation-preservation.v1',count=len(rows),files=sorted(rows,key=lambda r:r['stored_path']),runs=groups,
                archive_script_sha256=sha(Path(__file__).read_bytes()),qualification='Exact quality reports, not navigation/match/hardware acceptance')
    if manifest.exists():
        old=manifest.read_bytes();history=HERE/('PRESERVATION_'+sha(old)[:12]+'.json')
        if not history.exists():history.write_bytes(old)
    manifest.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(count=len(rows),manifest_sha256=sha(manifest.read_bytes()),archived_status=summary.get('status','HTTP_repair_evidence'))))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path);parser.add_argument('--label');parser.add_argument('--http-repair',action='store_true')
    args=parser.parse_args()
    if args.http_repair:
        archive(ROOT/'artifacts/operator-http413-20261014-before01','h0',quality=False)
        archive(ROOT/'artifacts/operator-http413-20261014-after01','h1',quality=False)
    elif args.source is not None and args.label is not None:archive(args.source,args.label)
    else:parser.error('provide --source/--label or --http-repair')
