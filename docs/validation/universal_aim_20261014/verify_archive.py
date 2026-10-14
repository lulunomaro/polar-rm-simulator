"""Verify preserved bytes independently; never execute algorithms or images."""
import gzip,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
manifest=json.loads((ROOT/'PRESERVATION_MANIFEST.json').read_text(encoding='utf8'))
for row in manifest['files']:
    path=ROOT/row['path'];stored=path.read_bytes()
    if path.is_symlink() or not path.resolve().is_relative_to(ROOT):raise ValueError('Unsafe archive path')
    assert len(stored)==row['stored_bytes'] and hashlib.sha256(stored).hexdigest()==row['stored_sha256']
    raw=gzip.decompress(stored) if row['encoding']=='gzip' else stored
    assert len(raw)==row['original_bytes'] and hashlib.sha256(raw).hexdigest()==row['original_sha256']
print(json.dumps(dict(files=len(manifest['files']),verified=True)))
