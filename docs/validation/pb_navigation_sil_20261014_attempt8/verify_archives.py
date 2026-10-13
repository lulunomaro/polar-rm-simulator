"""Two byte/source verification passes; generate fresh indexes for the two owned archives."""
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def verify(directory):
    index_path = directory / 'INDEX.json'
    if index_path.exists():
        raise ValueError('fresh index required')
    manifest_bytes = (directory / 'MANIFEST.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    rows = manifest['files']
    assert manifest['count'] == len(rows)
    assert len({r['stored_path'] for r in rows}) == len(rows)
    for _ in range(2):
        for row in rows:
            stored = (directory / row['stored_path']).read_bytes()
            raw = gzip.decompress(stored) if row['encoding'] == 'gzip_mtime0' else stored
            assert len(stored) == row['stored_bytes'] and sha(stored) == row['stored_sha256']
            assert len(raw) == row['original_bytes'] and sha(raw) == row['original_sha256']
            assert (ROOT / row['source']).read_bytes() == raw
            if 'existing_gzip_payload_sha256' in row:
                assert sha(gzip.decompress(stored)) == row['existing_gzip_payload_sha256']
        assert (directory / 'MANIFEST.json').read_bytes() == manifest_bytes
    inventory = []
    for path in sorted(directory.rglob('*')):
        if not path.is_file():
            continue
        assert not path.is_symlink()
        raw = path.read_bytes()
        for _ in range(2):
            assert path.read_bytes() == raw
        inventory.append({'path': path.relative_to(directory).as_posix(),
                          'bytes': len(raw), 'sha256': sha(raw)})
    result = {
        'schema': 'polar.pb-navigation-frozen-evidence-index.v1',
        'manifest': 'MANIFEST.json', 'manifest_sha256': sha(manifest_bytes),
        'copied_payload_count': len(rows),
        'groups': dict(sorted(Counter(r['stored_path'].split('/')[0] for r in rows).items())),
        'original_total_bytes': manifest['original_total_bytes'],
        'stored_total_bytes': manifest['stored_total_bytes'],
        'independent_full_payload_verification_passes': 2,
        'all_sources_unchanged': True,
        'local_files_verified_twice': inventory,
        'inventory_excludes_self': True,
        'qualification': manifest['qualification'],
    }
    if (directory / 'INDEPENDENT_AUDIT.json').exists():
        audit = json.loads((directory / 'INDEPENDENT_AUDIT.json').read_bytes())
        assert audit['passed'] and audit['commands'] == 18 and audit['consumed_steps'] == 779
        result['actual_receipt_audit'] = {'commands': 18, 'consumed_steps': 779,
            'all_receipts_verified': True,
            'goal_path_qualification': 'goal/path/status from frozen action-future RESULT and bound harness; raw controller reached-goal log corroborates, no independent original goal-TF/path snapshot'}
    index_path.write_text(json.dumps(result, indent=2) + '\n', encoding='utf8')
    index_bytes = index_path.read_bytes()
    assert json.loads(index_bytes) == result
    print(json.dumps({'archive': directory.name, 'payload_count': len(rows),
                      'manifest_sha256': sha(manifest_bytes), 'index_sha256': sha(index_bytes),
                      'all_sources_unchanged': True, 'verification_passes': 2}))


if __name__ == '__main__':
    verify(HERE.parent / 'pb_navigation_dispatch_20261014')
    verify(HERE)
