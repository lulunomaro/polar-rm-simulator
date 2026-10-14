"""Verify literal/gzip preserved records and package bytes without executing tests."""
from pathlib import Path
import gzip,hashlib,json
ROOT=Path(__file__).resolve().parent
def sha(raw):return hashlib.sha256(raw).hexdigest()
def main():
    manifest=json.loads((ROOT/'PRESERVATION_MANIFEST.json').read_bytes())
    for r in manifest['records']:
        p=Path(r['stored_path'])
        assert not p.is_absolute() and '..' not in p.parts
        raw=(ROOT/p).read_bytes();assert len(raw)==r['stored_bytes'] and sha(raw)==r['stored_sha256']
        decoded=gzip.decompress(raw) if r['compression']=='gzip' else raw
        assert len(decoded)==r['original_bytes'] and sha(decoded)==r['original_sha256']
    files=json.loads((ROOT/'FILES.json').read_bytes())['files']
    for r in files:
        p=Path(r['path']);assert not p.is_absolute() and '..' not in p.parts
        raw=(ROOT/p).read_bytes();assert len(raw)==r['bytes'] and sha(raw)==r['sha256']
    assert {p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file() and '__pycache__' not in p.parts}=={r['path'] for r in files}|{'FILES.json'}
    print(json.dumps(dict(preserved_records=len(manifest['records']),package_files=len(files),all_exact=True,scope='integrity only, no algorithms/physics/milestone acceptance')))
if __name__=='__main__':main()
