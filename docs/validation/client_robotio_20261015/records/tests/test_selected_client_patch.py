"""Explicit local patch identities and real disposable Git checkout; no Qt/model."""
import hashlib
import json
from pathlib import Path
import subprocess
from unittest.mock import patch
import pytest
from rm_match.deployment import launcher
from tools.apply_client_patch import inspect_client

def sha(raw):return hashlib.sha256(raw).hexdigest()

def fixture(tmp_path):
    root=tmp_path/'client';root.mkdir()
    subprocess.check_call(['git','init','--quiet'],cwd=root)
    for name in ('main.py','rm_client/ui/sim_platform_window.py','rm_client/sim_platform_adapters.py','requirements-core.txt'):
        selected=root/name;selected.parent.mkdir(parents=True,exist_ok=True);selected.write_bytes(b'old\n')
    subprocess.check_call(['git','add','.'],cwd=root)
    subprocess.check_call(['git','-c','user.name=Unit Test','-c','user.email=test@example.invalid','commit','--quiet','-m','fixture'],cwd=root)
    base=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
    raw=b'diff --git a/main.py b/main.py\n--- a/main.py\n+++ b/main.py\n@@ -1 +1 @@\n-old\n+new\n'
    (tmp_path/'change.patch').write_bytes(raw)
    manifest=dict(schema='polar.sim.own_client_patch.v1',base_commit=base,patch_file='change.patch',patch_sha256=sha(raw),
        files={'main.py':dict(before_sha256=sha(b'old\n'),after_sha256=sha(b'new\n'))})
    path=tmp_path/'manifest.json';path.write_bytes(json.dumps(manifest).encode())
    return root,path,manifest,base

def test_explicit_manifest_real_checkout_requires_exact_apply_then_verifies(tmp_path):
    root,path,value,base=fixture(tmp_path)
    with patch.object(launcher,'CLIENT_COMMIT',base):
        identity=launcher.client_patch_identity(path)
        assert identity['manifest_sha256']==sha(path.read_bytes())
        with pytest.raises(ValueError,match='explicit operator-state patch'):launcher.check_client(root,patch_manifest=path)
        assert (root/'main.py').read_bytes()==b'old\n'
        inspect_client(root,path,run=True)
        result=launcher.check_client(root,patch_manifest=path)
        assert result['patched_source_verified'] and result['client_patch']==identity

@pytest.mark.parametrize('name',['../change.patch','nested/change.patch','nested\\change.patch'])
def test_selected_patch_cannot_escape_its_local_manifest_directory(tmp_path,name):
    root,path,value,base=fixture(tmp_path);value['patch_file']=name;path.write_bytes(json.dumps(value).encode())
    with patch.object(launcher,'CLIENT_COMMIT',base),pytest.raises(ValueError,match='manifest directory'):
        launcher.client_patch_identity(path)

def test_explicit_manifest_rejects_changed_patch_and_foreign_base(tmp_path):
    root,path,value,base=fixture(tmp_path)
    with patch.object(launcher,'CLIENT_COMMIT',base):
        (tmp_path/'change.patch').write_bytes(b'foreign patch')
        with pytest.raises(ValueError,match='bytes differ'):launcher.client_patch_identity(path)
        value['base_commit']='0'*40;path.write_bytes(json.dumps(value).encode())
        with pytest.raises(ValueError,match='fixed own-client'):launcher.client_patch_identity(path)

def test_manifest_changed_during_actual_source_inspection_is_rejected(tmp_path):
    root,path,value,base=fixture(tmp_path);inspect_client(root,path,run=True)
    def raced(*args,**kwargs):
        result=inspect_client(*args,**kwargs)
        path.write_bytes(path.read_bytes()+b'\n')
        return result
    with patch.object(launcher,'CLIENT_COMMIT',base),patch('tools.apply_client_patch.inspect_client',side_effect=raced):
        with pytest.raises(ValueError,match='manifest changed during source verification'):
            launcher.check_client(root,patch_manifest=path)

def test_default_identity_retains_original_fixed_patch_bytes():
    path=launcher.ROOT/'client_patches/CLIENT_PATCH_MANIFEST.json'
    identity=launcher.client_patch_identity()
    assert identity['manifest_sha256']==sha(path.read_bytes())
    assert identity['patch_sha256']=='a889f79c20ff850c2531ed52f0bb3b8b55facf4f201efa5ccf45149bb7b1a331'
