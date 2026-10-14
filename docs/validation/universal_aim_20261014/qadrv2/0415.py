#!/usr/bin/env python3
"""Verify the pinned own Qt client patch. Dry-run by default; --run applies it.

Reject another HEAD, staged changes, unexpected tracked edits, partial patches,
or an unexpected file at a new patch path. No commit, reset, checkout or push.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'client_patches' / 'CLIENT_PATCH_MANIFEST.json'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def source_sha(data):
    return sha(data.replace(b'\r\n', b'\n'))


def git(root, *args):
    # DrvFs presents a Windows CRLF checkout to Linux Git. Use the same text
    # clean filter on both hosts, and disregard synthetic executable bits;
    # binary/-text attributes and every source-content hash remain enforced.
    # Never rewrite the checkout's persistent Git configuration.
    result = subprocess.run(['git','-c','core.autocrlf=true','-c','core.filemode=false',*args],cwd=root,capture_output=True)
    if result.returncode:
        raise ValueError('git '+args[0]+' failed: '+result.stderr.decode(errors='replace').strip())
    return result.stdout


def inspect_client(client_root, manifest_path=MANIFEST, *, run=False):
    root=Path(client_root).resolve(); manifest_path=Path(manifest_path).resolve()
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('schema')!='polar.sim.own_client_patch.v1':raise ValueError('Unsupported client patch manifest')
    head=git(root,'rev-parse','HEAD').decode().strip()
    if head!=manifest['base_commit']:raise ValueError('Client HEAD differs from fixed base_commit')
    if git(root,'diff','--cached','--name-only','-z'):raise ValueError('Staged tracked changes are not permitted')
    patch=(manifest_path.parent/manifest['patch_file']).resolve()
    if patch.parent!=manifest_path.parent:raise ValueError('Patch path outside manifest directory')
    if sha(patch.read_bytes())!=manifest['patch_sha256']:raise ValueError('Patch SHA256 mismatch')
    files=manifest['files']
    changed={p.decode('utf-8') for p in git(root,'diff','HEAD','--name-only','-z').split(b'\0') if p}
    if changed-set(files):raise ValueError('Unexpected tracked changes: '+', '.join(sorted(changed-set(files))))
    before=True;after=True
    for name,row in files.items():
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('Unsafe patch file path')
        path=root/relative
        if path.is_symlink() or not path.resolve().is_relative_to(root):raise ValueError('Patch file is outside client tree')
        actual=None if not path.exists() else source_sha(path.read_bytes())
        if row['before_sha256'] is not None:
            original=source_sha(git(root,'show',head+':'+name))
            if original!=row['before_sha256']:raise ValueError('Manifest original file hash differs from pinned git blob: '+name)
        before &= actual==row['before_sha256']
        after &= actual==row['after_sha256']
    if not before and not after:raise ValueError('Unexpected or partially applied client file hashes')
    applied=False
    if before:
        git(root,'apply','--check',str(patch))
        if run:
            git(root,'apply',str(patch));applied=True
            for name,row in files.items():
                if source_sha((root/name).read_bytes())!=row['after_sha256']:
                    raise ValueError('Applied file hash does not match manifest: '+name)
            after=True
    return dict(schema='polar.sim.own_client_patch.check.v1',client_root=str(root),base_commit=head,
                patch_sha256=manifest['patch_sha256'],status='verified_patched' if after else 'verified_unpatched',
                apply_required=not after,applied=applied,dry_run=not run,
                source_hash_scope='UTF-8 file bytes with CRLF normalized to LF',
                git_clean_profile='per-command core.autocrlf=true and core.filemode=false; attributes honored',
                qualification='Own client at fixed base plus reviewed patch; not original byte-exact client')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client-root',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,default=MANIFEST)
    parser.add_argument('--run',action='store_true')
    args=parser.parse_args()
    try:result=inspect_client(args.client_root,args.manifest,run=args.run)
    except (ValueError,OSError,KeyError) as exc:
        print(json.dumps(dict(status='rejected',error=str(exc))));return 2
    print(json.dumps(result,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
