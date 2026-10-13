"""Final explicit Git staging inventory; does not modify payloads or INDEX."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
dest=HERE/'FILES.json'
rows=[]
for path in sorted(HERE.rglob('*')):
    if not path.is_file() or path==dest:continue
    if path.is_symlink():raise ValueError('archive inventory link')
    raw=path.read_bytes()
    rows.append(dict(path=path.relative_to(HERE).as_posix(),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
dest.write_text(json.dumps(dict(schema='polar.archive-file-inventory.v1',count=len(rows),files=rows,
    excluded_self='FILES.json',qualification='Exact inventory of payloads and derived archive metadata; no new navigation/test execution'),indent=2)+'\n',encoding='utf8')
print(json.dumps(dict(count=len(rows),inventory_sha256=hashlib.sha256(dest.read_bytes()).hexdigest())))
