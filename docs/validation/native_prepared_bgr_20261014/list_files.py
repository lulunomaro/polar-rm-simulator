"""Enumerate exact permanent bytes; FILES.json cannot hash itself."""
import hashlib
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent
rows=[]
for p in sorted(HERE.rglob('*')):
    if p.is_file() and p.name!='FILES.json':
        assert not p.is_symlink()
        raw=p.read_bytes()
        rows.append({'path':p.relative_to(HERE).as_posix(),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
report={'schema':'polar.evidence.permanent-exact-files.v1','files':rows,'listed_files':len(rows),
        'total_listed_bytes':sum(r['bytes'] for r in rows),
        'self_file':'FILES.json','self_sha256':'deliberately excluded to avoid recursive self hash',
        'git_path_prefix':'docs/validation/native_prepared_bgr_20261014/'}
(HERE/'FILES.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
print(json.dumps({'listed_files':len(rows),'including_FILES_json':len(rows)+1,'total_listed_bytes':report['total_listed_bytes']}))
