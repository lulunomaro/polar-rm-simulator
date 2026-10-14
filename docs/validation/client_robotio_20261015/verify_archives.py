"""Verify literal/gzip records and package coverage, without executing algorithms."""
from pathlib import Path
import gzip,hashlib,json
ROOT=Path(__file__).resolve().parent
def sha(raw):return hashlib.sha256(raw).hexdigest()
def checked_path(name):
    path=Path(name)
    assert not path.is_absolute() and '..' not in path.parts
    return ROOT/path
def main():
    manifest=json.loads((ROOT/'PRESERVATION_MANIFEST.json').read_bytes())
    originals=set();stored=set()
    for row in manifest['records']:
        assert row['original_path'] not in originals and row['stored_path'] not in stored
        originals.add(row['original_path']);stored.add(row['stored_path'])
        assert row['compression'] in ('literal','gzip')
        raw=checked_path(row['stored_path']).read_bytes()
        assert len(raw)==row['stored_bytes'] and sha(raw)==row['stored_sha256']
        decoded=gzip.decompress(raw) if row['compression']=='gzip' else raw
        assert len(decoded)==row['original_bytes'] and sha(decoded)==row['original_sha256']
    files=json.loads((ROOT/'FILES.json').read_bytes())['files'];listed=set()
    for row in files:
        assert row['path'] not in listed;listed.add(row['path'])
        raw=checked_path(row['path']).read_bytes()
        assert len(raw)==row['bytes'] and sha(raw)==row['sha256']
    actual={p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    assert actual==listed|{'FILES.json'}
    print(json.dumps(dict(preserved_records=len(originals),package_files=len(actual),all_exact=True,
        scope='integrity only; no algorithms/physics/milestone acceptance')))
if __name__=='__main__':main()
