"""Finalize exact package inventory; FILES excludes itself to avoid recursion."""
import hashlib,json,stat
from pathlib import Path
ROOT=Path(__file__).resolve().parent
rows=[]
for path in sorted(ROOT.rglob('*')):
    if path.is_dir():continue
    if path.name=='FILES.json':continue
    info=path.lstat()
    if path.is_symlink() or getattr(info,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400):
        raise ValueError('Linked package file refused')
    raw=path.read_bytes()
    rows.append(dict(path=path.relative_to(ROOT).as_posix(),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
value=dict(schema='polar.evidence.package-inventory.v1',files=rows,
    file_count_excluding_self=len(rows),total_bytes_excluding_self=sum(row['bytes'] for row in rows),
    scope='Actual package files; FILES.json excluded from its own list')
(ROOT/'FILES.json').write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps({key:child for key,child in value.items() if key!='files'}))
