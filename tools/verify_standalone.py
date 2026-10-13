"""Check the pinned extraction and syntax without importing simulator code."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def main():
    manifest = json.loads((ROOT / 'EXTRACTION_MANIFEST.json').read_text())
    if manifest['source_commit'] != '7663ae744d69b27813abaefeaa9ae3e73be46a9f':
        raise ValueError('Unexpected pinned source commit')
    if len(manifest['files']) != 190 or len(manifest['derived_files']) != 1:
        raise ValueError('Expected 190 unchanged source files and one attributed fixture')
    seen = set()
    for row in manifest['files'] + manifest['derived_files']:
        relative = Path(row['path'])
        if relative.is_absolute() or '..' in relative.parts or relative.as_posix() in seen:
            raise ValueError('Unsafe or duplicate manifest path')
        seen.add(relative.as_posix())
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError('Missing or nonregular source: ' + row['path'])
        data = path.read_bytes()
        git_sha = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        if (len(data) != row['size'] or git_sha != row['git_blob_sha1']
                or hashlib.sha256(data).hexdigest() != row['sha256']):
            raise ValueError('Source bytes differ: ' + row['path'])
    if manifest['copied_file_count'] + manifest['adapted_source_file_count'] + manifest['excluded_source_file_count'] != manifest['original_subtree_file_count']:
        raise ValueError('Source partition is inconsistent')
    def function_body(relative):
        value = (ROOT / relative).read_text()
        node = next(n for n in ast.parse(value).body
                    if isinstance(n, ast.FunctionDef) and n.name == 'rule_decide')
        return ast.get_source_segment(value, node)
    original_body = function_body('upstream_reference/sentry_decide_server.py')
    if original_body != function_body('rm_match/upstream_rule.py'):
        raise ValueError('Original deterministic rule body changed')
    if hashlib.sha256(original_body.encode()).hexdigest() != manifest['derived_files'][0]['function_sha256']:
        raise ValueError('Original deterministic rule body hash changed')
    counts = {}
    for suffix in ('.py', '.json', '.xml'):
        files = [p for p in ROOT.rglob('*' + suffix)
                 if not any(part in {'.git', '.venv', '__pycache__', 'artifacts', 'build', 'dist'}
                            for part in p.relative_to(ROOT).parts)]
        for path in files:
            if suffix == '.py':
                ast.parse(path.read_bytes(), filename=str(path.relative_to(ROOT)))
            elif suffix == '.json':
                json.loads(path.read_text())
            else:
                ET.parse(path)
        counts[suffix] = len(files)
    result = {'unchanged_source_blobs_verified': len(manifest['files']), 'derived_fixtures_verified': len(manifest['derived_files']), 'syntax_files': counts,
              'scope': 'static extraction only; no physics, native execution, renderer or external service'}
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
