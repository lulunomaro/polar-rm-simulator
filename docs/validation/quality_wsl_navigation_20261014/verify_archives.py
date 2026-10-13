"""Independent raw/stored quality payload byte check, no tests/ROS/WSL rerun."""
import gzip
import hashlib
import json
from pathlib import Path,PurePosixPath

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
manifest=HERE/'PRESERVATION_MANIFEST.json';value=json.loads(manifest.read_text());rows=[]
for item in value['files']:
    rel=PurePosixPath(item['stored_path'])
    if rel.is_absolute() or '..' in rel.parts:raise ValueError('unsafe quality payload path')
    dest=HERE/item['stored_path']
    if dest.is_symlink() or not dest.resolve().is_relative_to(HERE):raise ValueError('quality archive alias')
    raw=dest.read_bytes()
    if len(raw)!=item['stored_bytes'] or hashlib.sha256(raw).hexdigest()!=item['stored_sha256']:raise ValueError('stored quality identity changed')
    original=gzip.decompress(raw) if item['encoding']=='gzip_mtime0' else raw
    if len(original)!=item['original_bytes'] or hashlib.sha256(original).hexdigest()!=item['original_sha256']:raise ValueError('raw quality identity changed')
    if (ROOT/item['source']).read_bytes()!=original:raise ValueError('original quality evidence changed')
    if item['encoding']=='gzip_mtime0' and int.from_bytes(raw[4:8],'little')!=0:raise ValueError('nonzero gzip mtime')
    rows.append(dict(path=item['stored_path'],raw_sha256=hashlib.sha256(original).hexdigest(),verified=True))
report=dict(schema='polar.quality.archive-byte-verification.v1',count=len(rows),manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
            all_raw_stored_original_bytes_equal=True,files=rows,scope='Archive identity verification only; does not claim source unchanged during quality run')
index=HERE/'INDEX.json'
if index.exists():
    old=index.read_bytes();history=HERE/('INDEX_'+hashlib.sha256(old).hexdigest()[:12]+'.json')
    if not history.exists():history.write_bytes(old)
index.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
print(json.dumps(dict(count=len(rows),manifest_sha256=report['manifest_sha256'],index_sha256=hashlib.sha256(index.read_bytes()).hexdigest())))
