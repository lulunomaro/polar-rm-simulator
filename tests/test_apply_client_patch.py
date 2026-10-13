"""Patch validation uses disposable repositories, never the user's client tree."""
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from tools.apply_client_patch import inspect_client


def command(root,*args):
    return subprocess.check_output(['git',*args],cwd=root,stderr=subprocess.DEVNULL)


def digest(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def fixture(tmp_path):
    root=tmp_path/'client';root.mkdir();command(root,'init')
    (root/'client.py').write_bytes(b'old\n');(root/'unrelated.py').write_bytes(b'keep\n')
    command(root,'add','.');command(root,'-c','user.name=Unit Test','-c','user.email=test@example.invalid','commit','-m','fixture')
    base=command(root,'rev-parse','HEAD').decode().strip()
    patch=(b'diff --git a/client.py b/client.py\n--- a/client.py\n+++ b/client.py\n@@ -1 +1 @@\n-old\n+new\n'
           b'diff --git a/new_test.py b/new_test.py\nnew file mode 100644\n--- /dev/null\n+++ b/new_test.py\n@@ -0,0 +1 @@\n+new test\n')
    (tmp_path/'change.patch').write_bytes(patch)
    manifest=dict(schema='polar.sim.own_client_patch.v1',base_commit=base,patch_file='change.patch',patch_sha256=digest(patch),
                  files={'client.py':dict(before_sha256=digest(b'old\n'),after_sha256=digest(b'new\n')),
                         'new_test.py':dict(before_sha256=None,after_sha256=digest(b'new test\n'))})
    path=tmp_path/'manifest.json';path.write_text(json.dumps(manifest),encoding='utf-8')
    return root,path


def test_dry_then_explicit_apply_then_idempotent(fixture):
    root,manifest=fixture
    dry=inspect_client(root,manifest)
    assert dry['status']=='verified_unpatched' and dry['apply_required']
    assert (root/'client.py').read_bytes().replace(b'\r\n',b'\n')==b'old\n'
    assert not (root/'new_test.py').exists()
    applied=inspect_client(root,manifest,run=True)
    assert applied['status']=='verified_patched' and applied['applied']
    again=inspect_client(root,manifest,run=True)
    assert again['status']=='verified_patched' and not again['applied']
    assert not command(root,'diff','--cached','--name-only')


def test_refuses_wrong_base_and_preserves_client(fixture):
    root,manifest=fixture;data=json.loads(manifest.read_text());data['base_commit']='0'*40
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='HEAD'):inspect_client(root,manifest,run=True)
    assert not (root/'new_test.py').exists()


@pytest.mark.parametrize('case',['unrelated_tracked','partial_expected','unexpected_new_file','staged'])
def test_refuses_unexpected_or_partial_changes(fixture,case):
    root,manifest=fixture
    if case=='unrelated_tracked':(root/'unrelated.py').write_text('changed\n')
    if case=='partial_expected':(root/'client.py').write_text('new\n')
    if case=='unexpected_new_file':(root/'new_test.py').write_text('unexpected\n')
    if case=='staged':
        (root/'client.py').write_text('new\n');command(root,'add','client.py')
    before={p.name:p.read_bytes() for p in root.glob('*.py')}
    with pytest.raises(ValueError):inspect_client(root,manifest,run=True)
    assert {p.name:p.read_bytes() for p in root.glob('*.py')}==before


def test_tampered_patch_is_rejected(fixture):
    root,manifest=fixture;patch=manifest.parent/'change.patch';patch.write_bytes(patch.read_bytes()+b'\n')
    with pytest.raises(ValueError,match='SHA256'):inspect_client(root,manifest,run=True)


def test_crlf_source_checkout_is_supported(fixture):
    root,manifest=fixture
    command(root,'config','core.autocrlf','true')
    (root/'client.py').write_bytes(b'old\r\n')
    assert inspect_client(root,manifest)['status']=='verified_unpatched'


def test_linux_git_over_windows_crlf_checkout_uses_only_per_command_filters(fixture):
    root,manifest=fixture
    command(root,'config','core.autocrlf','false')
    # EOL alone makes unpatched files look dirty with Linux's default filter.
    (root/'client.py').write_bytes(b'old\r\n')
    (root/'unrelated.py').write_bytes(b'keep\r\n')
    assert command(root,'diff','HEAD','--name-only')
    assert inspect_client(root,manifest)['status']=='verified_unpatched'
    assert command(root,'config','--get','core.autocrlf').decode().strip()=='false'
    (root/'unrelated.py').write_bytes(b'changed\r\n')
    with pytest.raises(ValueError,match='Unexpected tracked changes'):inspect_client(root,manifest,run=True)


def test_crlf_change_to_explicit_non_text_file_is_still_rejected(fixture):
    root,manifest=fixture
    (root/'.gitattributes').write_text('unrelated.py -text\n',encoding='utf-8')
    command(root,'add','.gitattributes')
    command(root,'-c','user.name=Unit Test','-c','user.email=test@example.invalid','commit','-m','binary fixture')
    data=json.loads(manifest.read_text());data['base_commit']=command(root,'rev-parse','HEAD').decode().strip()
    manifest.write_text(json.dumps(data))
    (root/'unrelated.py').write_bytes(b'keep\r\n')
    with pytest.raises(ValueError,match='Unexpected tracked changes'):inspect_client(root,manifest)
