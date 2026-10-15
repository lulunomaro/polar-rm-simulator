"""Explicit local patch identities and real disposable Git checkout; no Qt/model."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
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


def planned(tmp_path,root,path):
    return launcher.plan(SimpleNamespace(port=8766,max_wall_seconds=1.,camera_fps=15.,real_time_factor=1.,
        client_root=root,client_patch_manifest=path,out=tmp_path/'fresh',native_spec=tmp_path/'native.local.json',
        sim_python=Path(sys.executable),client_python=Path(sys.executable),
        adapters_json=None,gl='egl'))


def test_explicit_deployment_plan_pins_manifest_without_starting_or_applying(tmp_path):
    root,path,value,base=fixture(tmp_path)
    with patch.object(launcher,'CLIENT_COMMIT',base),patch.object(launcher.subprocess,'Popen') as start:
        p=planned(tmp_path,root,path)
        assert p['client_patch_manifest']==str(path.absolute())
        assert p['client_patch']==launcher.client_patch_identity(path)
        assert p['client_argv'][1]==str(root/'main.py')
        assert (root/'main.py').read_bytes()==b'old\n'
        assert not (tmp_path/'fresh').exists()
        start.assert_not_called()


def test_explicit_setup_uses_same_manifest_for_apply_and_postcheck(tmp_path):
    root,path,value,base=fixture(tmp_path);target=tmp_path/'new-client'
    with patch.object(launcher,'CLIENT_COMMIT',base):
        identity=launcher.client_patch_identity(path)
        with patch.object(launcher,'run_checked') as run,patch.object(launcher,'check_client',return_value={'client_patch':identity}) as check:
            result=launcher.setup_client(target,run=True,patch_manifest=path)
        assert result['client_patch']==identity
        assert result['client_patch_manifest']==str(path)
        assert run.call_count==5
        assert result['commands'][-1][-2:]==['--manifest',str(path)]
        check.assert_called_once_with(target,patch_manifest=path)


def test_explicit_setup_rejects_different_postcheck_identity(tmp_path):
    root,path,value,base=fixture(tmp_path)
    with patch.object(launcher,'CLIENT_COMMIT',base),patch.object(launcher,'run_checked'), \
         patch.object(launcher,'check_client',return_value={'client_patch':{}}):
        with pytest.raises(ValueError,match='changed_during_setup'):
            launcher.setup_client(tmp_path/'new-client',run=True,patch_manifest=path)


def report_for(p):
    return dict(ready_to_attempt=True,checks=[
        dict(name='pinned_client',ok=True,detail={'client_patch':p['client_patch']}),
        dict(name='own_t2_native_assets',ok=True,detail={'spec_sha256':'a'*64})])


def test_selected_doctor_checks_the_planned_manifest_and_rejects_new_identity(tmp_path):
    root,path,value,base=fixture(tmp_path)
    with patch.object(launcher,'CLIENT_COMMIT',base):
        p=planned(tmp_path,root,path)
        with patch.object(launcher,'python_probe',return_value={}),patch.object(launcher,'run_checked',side_effect=ValueError('no native fixture')), \
             patch.object(launcher,'check_client',return_value={'client_patch':{}}) as check:
            report=launcher.doctor(p)
        selected=next(c for c in report['checks'] if c['name']=='pinned_client')
        assert selected['ok'] is False and 'changed_after_plan' in selected['error']
        check.assert_called_once_with(str(root),patch_manifest=str(path))


@pytest.mark.parametrize('race',['missing_doctor_pin','changed_after_doctor','changed_before_server'])
def test_selected_launch_races_cannot_start_processes(tmp_path,race):
    root,path,value,base=fixture(tmp_path);inspect_client(root,path,run=True)
    with patch.object(launcher,'CLIENT_COMMIT',base):
        p=planned(tmp_path,root,path);report=report_for(p)
        if race=='missing_doctor_pin':
            report['checks']=report['checks'][1:]
        if race=='changed_after_doctor':
            path.write_bytes(path.read_bytes()+b'\n')
        original_check=launcher._check_planned_client;checked=[]
        def recheck(plan):
            checked.append(True)
            if len(checked)==2:path.write_bytes(path.read_bytes()+b'\n')
            return original_check(plan)
        original_start=subprocess.Popen;application_starts=[]
        def start(argv,*args,**kwargs):
            if argv[0]=='git':return original_start(argv,*args,**kwargs)
            application_starts.append(argv)
            raise AssertionError('Application process must not start')
        with patch.object(launcher,'doctor',return_value=report),patch.object(launcher.subprocess,'Popen',side_effect=start):
            if race=='changed_before_server':
                with patch.object(launcher,'_check_planned_client',side_effect=recheck),patch('builtins.print'):
                    assert launcher.launch(p)==2
                result=json.loads((tmp_path/'fresh/launch_result.json').read_bytes())
                assert 'client_patch_changed_after_plan' in result['error']
            else:
                with pytest.raises(ValueError,match='doctor_pin|changed_after_plan'):
                    launcher.launch(p)
                assert not (tmp_path/'fresh').exists()
            assert not application_starts


def test_selected_smoke_pair_is_explicit_and_rechecked_with_real_git_source(tmp_path):
    from tools.smoke_wsl_native_live import selected_client_identity,selected_client_plan
    root,path,value,base=fixture(tmp_path);inspect_client(root,path,run=True)
    a=SimpleNamespace(client_root=root,client_patch_manifest=path)
    with patch.object(launcher,'CLIENT_COMMIT',base):
        selected=selected_client_plan(a)
        assert selected['client_root']==str(root)
        assert selected_client_identity(a)['client_patch']==selected['client_patch']
        (root/'main.py').write_bytes(b'changed after selection\n')
        with pytest.raises(ValueError):selected_client_identity(a)


def test_smoke_omitted_manifest_keeps_legacy_helper_call():
    from tools.smoke_wsl_native_live import selected_client_identity,selected_client_plan
    a=SimpleNamespace(client_root=Path('unexecuted-legacy-client'))
    with patch.object(launcher,'check_client',return_value={'fixture':True}) as check:
        assert selected_client_identity(a)=={'fixture':True}
        assert selected_client_plan(a) is None
        check.assert_called_once_with(a.client_root)


def test_selected_client_rechecked_after_ready_before_credential_handoff(tmp_path):
    root,path,value,base=fixture(tmp_path)
    with patch.object(launcher,'CLIENT_COMMIT',base):p=planned(tmp_path,root,path)
    identity={'client_patch':p['client_patch']};report=report_for(p)
    class Server:
        returncode=None
        stdout=io.BytesIO(b'{"synthetic_ready":true}\n')
        def poll(self):return self.returncode
        def terminate(self):self.returncode=0
        def kill(self):self.returncode=-9
        def wait(self,timeout):return self.returncode
    server=Server()
    with patch.object(launcher,'doctor',return_value=report),patch.object(launcher,'check_client',
         side_effect=[identity,identity,{'client_patch':{}}]) as check, \
         patch.object(launcher,'verify_ready'),patch.object(launcher.subprocess,'Popen',return_value=server) as start, \
         patch('builtins.print'):
        assert launcher.launch(p)==2
    assert check.call_count==3
    assert all(c.args==(str(root),) and c.kwargs=={'patch_manifest':str(path)} for c in check.call_args_list)
    assert start.call_count==1 and server.returncode==0
    assert 'POLAR_SIM_ADMISSION_CREDENTIAL' not in start.call_args.kwargs['env']
    result=json.loads((tmp_path/'fresh/launch_result.json').read_bytes())
    assert result['reason']=='launch_error' and 'client_patch_changed_after_plan' in result['error']
