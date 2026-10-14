"""Read-only literal/gzip verifier for this small checkpoint."""
from pathlib import Path
import argparse,gzip,hashlib,json

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--originals',action='store_true')
    args=parser.parse_args()
    archive=Path(__file__).resolve().parent
    root=archive.parents[2]
    raw=(archive/'PRESERVATION_MANIFEST.json').read_bytes()
    digest=lambda data:hashlib.sha256(data).hexdigest()
    expected='9a7eb7bc5f0409465998afeefae566dec676783c17271da0ea1a2668600465d4'
    if digest(raw)!=expected:raise ValueError('Preservation manifest changed')
    rows=json.loads(raw)['records']
    for row in rows:
        path=archive/row['stored_path']
        if path.is_symlink() or not path.resolve().is_relative_to(archive):raise ValueError('Payload path changed')
        payload=path.read_bytes()
        if len(payload)!=row['stored_bytes'] or digest(payload)!=row['stored_sha256']:raise ValueError('Stored bytes changed: '+row['stored_path'])
        if row['codec'] not in ('gzip','literal'):raise ValueError('Unknown codec')
        original=gzip.decompress(payload) if row['codec']=='gzip' else payload
        if len(original)!=row['original_bytes'] or digest(original)!=row['original_sha256']:raise ValueError('Original bytes changed: '+row['original_path'])
        if args.originals:
            source=root/row['original_path']
            if not source.resolve().is_relative_to(root) or source.read_bytes()!=original:raise ValueError('Workspace original changed: '+row['original_path'])
    print(json.dumps(dict(verified=True,files=len(rows),workspace_originals_checked=args.originals,manifest_sha256=expected)))
    return 0

if __name__=='__main__':raise SystemExit(main())
