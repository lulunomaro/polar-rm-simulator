"""Independent payload identity pass; no ROS/physics/process execution."""
import gzip
import hashlib
import json
from pathlib import Path,PurePosixPath

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def digest(raw):return hashlib.sha256(raw).hexdigest()


def main():
    manifest=HERE/'MANIFEST.json';value=json.loads(manifest.read_text());rows=[];seen=set()
    for row in value['files']:
        relative=PurePosixPath(row['stored_path'])
        if relative.is_absolute() or '..' in relative.parts or row['stored_path'] in seen:raise ValueError('invalid archive path')
        seen.add(row['stored_path']);path=HERE/row['stored_path']
        if path.is_symlink() or not path.resolve().is_relative_to(HERE):raise ValueError('escaped archive payload')
        raw=path.read_bytes()
        if len(raw)!=row['stored_bytes'] or digest(raw)!=row['stored_sha256']:raise ValueError('stored bytes mismatch')
        original=gzip.decompress(raw) if row['encoding']=='gzip_mtime0' else raw
        if len(original)!=row['original_bytes'] or digest(original)!=row['original_sha256']:raise ValueError('raw bytes mismatch')
        if row['encoding']=='gzip_mtime0' and int.from_bytes(raw[4:8],'little')!=0:raise ValueError('gzip mtime is not zero')
        if row.get('executed_sha256') and digest(original)!=row['executed_sha256']:raise ValueError('execution source mismatch')
        if row.get('saved_snapshot_path') and (ROOT/row['saved_snapshot_path']).read_bytes()!=original:
            raise ValueError('saved exact historical source changed')
        # Historical source snapshots intentionally differ from later workspace.
        # Archived artifacts themselves must remain byte-identical to originals.
        if not row.get('source_origin') and (ROOT/row['source']).read_bytes()!=original:raise ValueError('original artifact changed')
        rows.append(dict(stored_path=row['stored_path'],stored_sha256=digest(raw),raw_sha256=digest(original),verified=True))
    if len(rows)!=value['count']:raise ValueError('manifest count mismatch')
    scripts={p.name:digest(p.read_bytes()) for p in (HERE/'archive_evidence.py',Path(__file__),HERE/'README.md',HERE/'MISSING_OBSERVATIONS.json')}
    report=dict(schema='polar.pb-wsl-navigation-independent-index.v1',manifest_sha256=digest(manifest.read_bytes()),
                count=len(rows),all_payloads_verified=True,files=rows,local_file_sha256=scripts,
                scope='Independent stored/raw/execution-source byte checks; no rerun of fixture or navigation')
    index=HERE/'INDEX.json'
    if index.exists():
        old=index.read_bytes();history=HERE/('INDEX_'+digest(old)[:12]+'.json')
        if not history.exists():history.write_bytes(old)
    index.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(count=len(rows),manifest_sha256=report['manifest_sha256'],index_sha256=digest((HERE/'INDEX.json').read_bytes()))))


if __name__=='__main__':main()
