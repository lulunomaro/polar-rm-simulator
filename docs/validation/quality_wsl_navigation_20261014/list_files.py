"""Exact payload/metadata inventory, excluding the inventory itself."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
dest=HERE/'FILES.json';rows=[]
for p in sorted(HERE.rglob('*')):
    if not p.is_file() or p==dest:continue
    if p.is_symlink():raise ValueError('inventory link')
    raw=p.read_bytes();rows.append(dict(path=p.relative_to(HERE).as_posix(),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
dest.write_text(json.dumps(dict(count=len(rows),files=rows,excluded_self='FILES.json'),indent=2)+'\n',encoding='utf8')
print(json.dumps(dict(count=len(rows),inventory_sha256=hashlib.sha256(dest.read_bytes()).hexdigest())))
