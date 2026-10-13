"""Archive only frozen text evidence with exact raw/stored SHA and byte checks."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import re

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
GROUPS={
    'fail':'pb-rclcpp-dispatch-fixture-20261014',
    'dds':'pb-rclcpp-dispatch-fixture-20261014-02',
    'ctrl':'pb-controller-diag-build-20261014-01',
}
ALLOWED={'.json','.jsonl','.log','.txt','.yaml','.yml','.md','.py','.stdout','.stderr','.gz'}

def digest(raw):return hashlib.sha256(raw).hexdigest()

def archive():
    manifest=HERE/'MANIFEST.json'
    if manifest.exists():raise ValueError('fresh manifest required; no old archive overwrite')
    selected=[]
    for group,name in GROUPS.items():
        base=ROOT/'artifacts'/name
        files=list(base.glob('*'))
        for src in files:
            if not src.is_file() or src.suffix not in ALLOWED:continue
            if src.is_symlink() or any(p.is_symlink() for p in src.parents):raise ValueError('source link rejected')
            selected.append((src,Path(group)/src.relative_to(base)))
    selected.append((ROOT/'artifacts/pb-controller-diag-source-20261014-01/SOURCE_IDENTITY.json',Path('src/SOURCE_IDENTITY.json')))
    selected.append((ROOT/'tests/test_pb_controller_diagnostics.py',Path('fake/test_pb_controller_diagnostics.py')))
    rows=[]
    for src,relative in sorted(selected,key=lambda item:str(item[1])):
        raw=src.read_bytes()
        if len(raw)>24*1024*1024:raise ValueError('bounded text archive exceeded')
        if src.suffix!='.gz':
            text=raw.decode('utf8')
            if re.search(r'Bearer [A-Za-z0-9._~-]{16,}|"(?:credential|admission_credential|token)"\s*:\s*"[a-f0-9]{32,}"',text):
                raise ValueError('literal credential must not be archived:'+str(src))
        compressed=len(raw)>=65536 and src.suffix!='.gz'
        dest=HERE/(str(relative)+'.gz' if compressed else relative)
        if dest.exists() or len(str(dest))>=255:raise ValueError('fresh short destination required')
        dest.parent.mkdir(parents=True,exist_ok=True)
        if compressed:
            stream=io.BytesIO()
            with gzip.GzipFile(filename='',mode='wb',fileobj=stream,mtime=0,compresslevel=3) as handle:handle.write(raw)
            stored=stream.getvalue()
        else:stored=raw
        dest.write_bytes(stored)
        reread=dest.read_bytes();restored=gzip.decompress(reread) if compressed else reread
        if restored!=raw or src.read_bytes()!=raw:raise ValueError('archive bytes/source changed:'+str(src))
        row=dict(source=str(src.relative_to(ROOT)).replace('\\','/'),stored_path=str(dest.relative_to(HERE)).replace('\\','/'),
            original_bytes=len(raw),original_sha256=digest(raw),stored_bytes=len(reread),stored_sha256=digest(reread),
            encoding='gzip_mtime0' if compressed else 'original_bytes',decoded_bytes_identical=True,source_unchanged=True)
        if src.suffix=='.gz':
            row['existing_gzip_payload_sha256']=digest(gzip.decompress(raw))
            if gzip.decompress(reread)!=gzip.decompress(raw):raise ValueError('existing gzip payload changed')
        rows.append(row)
    result=dict(schema='polar.pb-navigation-dispatch-evidence.v1',files=rows,count=len(rows),
        original_total_bytes=sum(r['original_bytes'] for r in rows),stored_total_bytes=sum(r['stored_bytes'] for r in rows),
        archive_script_sha256=digest(Path(__file__).read_bytes()),all_raw_and_stored_verified=True,
        qualification='frozen actual synthetic DDS dispatch + diagnostic controller build/load text; not SIL or navigation acceptance; no binaries bundled')
    manifest.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'count':len(rows),'manifest_sha256':digest(manifest.read_bytes()),
        'original_total_bytes':result['original_total_bytes'],'stored_total_bytes':result['stored_total_bytes']}))

if __name__=='__main__':archive()
