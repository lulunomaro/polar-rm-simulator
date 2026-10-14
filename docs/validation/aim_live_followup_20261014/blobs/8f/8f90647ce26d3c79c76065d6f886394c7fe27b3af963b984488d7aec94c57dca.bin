"""Local scheduling scopes only; no renderer, WSL, inference or physics."""
import contextlib
import importlib.util
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pytest
from rm_match.platform_v2 import host_scheduling as helper


class FakeAffinity:
    def __init__(self, reads=None):
        self.state=(2,0xff);self.changes=[];self.reads=iter(reads) if reads else None
    def read(self):
        if self.reads:
            value=next(self.reads)
            if isinstance(value,BaseException):raise value
            return value
        return self.state
    def replace(self,group,mask):
        previous=self.state;self.state=(group,mask);self.changes.append(self.state);return previous
    def processor_count(self,group):
        assert group==2
        return 8


def test_defaults_do_not_set_or_load_windows_api_even_on_linux():
    with patch.object(helper.sys,'setswitchinterval') as set_switch,patch.object(helper,'_WindowsAffinityAPI') as api:
        with helper.PythonSwitchInterval() as switch,helper.AuthorityThreadAffinity() as affinity:
            assert helper.scheduling_qualified(dict(switch=switch,affinity=affinity))
        set_switch.assert_not_called();api.assert_not_called()


@pytest.mark.parametrize('value',[True,False,0,.099,10.001,float('nan'),float('inf'),'1',{},None])
def test_invalid_switch_values_reject_without_changing_process(value):
    with patch.object(helper.sys,'setswitchinterval') as setter:
        with pytest.raises(ValueError):helper.switch_interval_ms(value)
        setter.assert_not_called()


def test_actual_cpython_switch_restores_after_body_exception():
    original=sys.getswitchinterval();scope=helper.PythonSwitchInterval(1.)
    with pytest.raises(RuntimeError,match='body'):
        with scope:
            assert abs(sys.getswitchinterval()-.001)<1.01e-6
            assert scope.record['applied'] and not scope.record['restored']
            raise RuntimeError('body')
    assert abs(sys.getswitchinterval()-original)<1.01e-6
    assert scope.record['restored'] and scope.record['original_ms']==original*1000


def test_switch_entry_query_failure_restores_and_propagates():
    scope=helper.PythonSwitchInterval(1.)
    with patch.object(helper.sys,'getswitchinterval',side_effect=[.005,RuntimeError('read_failed'),.005]),\
            patch.object(helper.sys,'setswitchinterval') as setter:
        with pytest.raises(RuntimeError,match='read_failed'):scope.__enter__()
    assert setter.call_args_list[0].args==(.001,)
    assert setter.call_args_list[-1].args==(.005,)
    assert scope.record['restored']


def test_explicit_affinity_linux_rejects_without_api_or_fallback():
    with patch.object(helper.sys,'platform','linux'),patch.object(helper,'_WindowsAffinityAPI') as api:
        with pytest.raises(RuntimeError,match='requires Windows'):
            with helper.AuthorityThreadAffinity(0x10):pass
        api.assert_not_called()


@pytest.mark.parametrize('value',[True,False,0,-1,2**64,1.,'0x10',None])
def test_invalid_masks_rejected(value):
    with pytest.raises(ValueError):helper.affinity_mask(value)


def test_group_preserved_effective_readback_and_restore_after_exception():
    api=FakeAffinity();scope=helper.AuthorityThreadAffinity(0x10)
    with patch.object(helper.sys,'platform','win32'),patch.object(helper,'_WindowsAffinityAPI',return_value=api):
        with pytest.raises(ValueError,match='body'):
            with scope:
                assert api.state==(2,0x10)
                assert scope.record['effective_mask']==0x10 and scope.record['cpu_group']==2
                assert scope.record['thread_id']==threading.get_native_id()
                raise ValueError('body')
    assert api.state==(2,0xff) and scope.record['restored']


@pytest.mark.parametrize('failed_read',[RuntimeError('query_failed'),(2,0x20),(3,0x10)])
def test_failed_entry_readback_restores_original_without_silent_fallback(failed_read):
    api=FakeAffinity([(2,0xff),failed_read,(2,0xff)])
    scope=helper.AuthorityThreadAffinity(0x10)
    with patch.object(helper.sys,'platform','win32'),patch.object(helper,'_WindowsAffinityAPI',return_value=api):
        with pytest.raises(RuntimeError):scope.__enter__()
    assert api.state==(2,0xff) and scope.record['restored']


def test_invalid_group_cpu_selection_does_not_change_affinity():
    api=FakeAffinity()
    with patch.object(helper.sys,'platform','win32'),patch.object(helper,'_WindowsAffinityAPI',return_value=api):
        with pytest.raises(ValueError,match='unavailable CPUs'):
            with helper.AuthorityThreadAffinity(1<<8):pass
    assert api.changes==[]


def test_restore_failure_is_explicit_and_not_qualified():
    api=FakeAffinity([(2,0xff),(2,0x10),(2,0x20)])
    scope=helper.AuthorityThreadAffinity(0x10)
    with patch.object(helper.sys,'platform','win32'),patch.object(helper,'_WindowsAffinityAPI',return_value=api):
        with pytest.raises(RuntimeError,match='restoration'):
            with scope:pass
    assert not scope.record['restored'] and not helper.scheduling_qualified({'affinity':scope.record})


def test_other_thread_cannot_restore_pseudohandle_affinity():
    api=FakeAffinity();scope=helper.AuthorityThreadAffinity(0x10);errors=[]
    with patch.object(helper.sys,'platform','win32'),patch.object(helper,'_WindowsAffinityAPI',return_value=api):
        with scope:
            def wrong_thread():
                try:scope.close()
                except RuntimeError as exc:errors.append(str(exc))
            thread=threading.Thread(target=wrong_thread);thread.start();thread.join(1.)
            assert errors==['Authority affinity must be restored by its owning thread']
            assert api.state==(2,0x10)
    assert scope.record['restored']


@pytest.mark.skipif(sys.platform!='win32',reason='Actual WinAPI current-thread ownership requires Windows')
def test_actual_windows_thread_effective_affinity_and_restoration():
    # Select one CPU already allowed for this newly owned harmless thread.
    results=[];errors=[]
    def own_thread():
        try:
            api=helper._WindowsAffinityAPI();original=api.read()
            mask=original[1]&-original[1]
            scope=helper.AuthorityThreadAffinity(mask)
            with scope:
                assert api.read()==(original[0],mask)
            assert api.read()==original
            results.append(scope.record)
        except BaseException as exc:errors.append(exc)
    thread=threading.Thread(target=own_thread,name='harmless-affinity-readback');thread.start();thread.join(2.)
    assert not thread.is_alive() and not errors and len(results)==1
    assert results[0]['applied'] and results[0]['restored']
    print('ACTUAL_WINDOWS_AFFINITY_READBACK='+json.dumps(results[0],sort_keys=True))


def load_smoke():
    path=Path(__file__).resolve().parents[1]/'tools/smoke_wsl_native_live.py'
    spec=importlib.util.spec_from_file_location('_scheduling_smoke_fixture',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_harness_restores_switch_even_when_preparation_fails(tmp_path):
    smoke=load_smoke();original=sys.getswitchinterval();args=SimpleNamespace(out=tmp_path/'fresh',
        host_python_switch_interval_ms=1.,authority_affinity_mask=None)
    def failed_setup(*_):
        assert abs(sys.getswitchinterval()-.001)<1.01e-6
        raise RuntimeError('preparation_failed')
    with patch.object(smoke,'_run',side_effect=failed_setup),pytest.raises(RuntimeError,match='preparation_failed'):
        smoke.run(args)
    assert abs(sys.getswitchinterval()-original)<1.01e-6
    record=json.loads((args.out/'HOST_SCHEDULING.json').read_text())
    assert record['python_switch_interval']['restored']


def test_harness_existing_evidence_never_overwritten(tmp_path):
    smoke=load_smoke();path=tmp_path/'HOST_SCHEDULING.json';path.write_bytes(b'preserved')
    with pytest.raises(ValueError,match='Fresh output'):smoke.run(SimpleNamespace(out=tmp_path))
    assert path.read_bytes()==b'preserved'


def test_harness_explicit_settings_require_real_restoration_proof():
    smoke=load_smoke()
    path=Path(__file__).with_name('test_wsl_native_live_classification.py')
    spec=importlib.util.spec_from_file_location('_classification_scheduling_fixture',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    plan=smoke.build_plan('wsl_stdio_v1',host_python_switch_interval_ms=1.,authority_affinity_mask=0x10)
    measured=module.measured();measured['configuration']=plan['configuration']
    for value in (None,False,1):
        measured['host_scheduling_applied_and_restored']=value
        assert not smoke.classify(measured,plan=plan)['live_static_chain_qualified']
    measured['host_scheduling_applied_and_restored']=True
    assert smoke.classify(measured,plan=plan)['live_static_chain_qualified']
    assert plan['configuration']['camera_native_budget_s']==.08
    assert plan['configuration']['server_input_window_s']==.15


@pytest.mark.parametrize('argument,value',[
    ('--host-python-switch-interval-ms','nan'),('--host-python-switch-interval-ms','inf'),
    ('--host-python-switch-interval-ms','0.09'),('--host-python-switch-interval-ms','10.01'),
    ('--authority-affinity-mask','0'),('--authority-affinity-mask','-1'),
    ('--authority-affinity-mask','0x10000000000000000')])
def test_bad_cli_settings_reject_before_resource_initialization(argument,value):
    from rm_match.platform_v2 import __main__ as cli
    smoke=load_smoke()
    with patch('rm_match.platform_v2.admission.AdmissionPolicy.from_manifest') as policy,\
            patch.object(cli,'MuJoCoBackend') as backend:
        with pytest.raises(SystemExit):cli.main(['--admission-manifest','fixture.json',argument,value])
        policy.assert_not_called();backend.assert_not_called()
    with patch.object(smoke,'run') as run:
        with pytest.raises(SystemExit):smoke.main([argument,value])
        run.assert_not_called()


def test_linux_cli_affinity_rejected_before_any_resource_even_plan():
    from rm_match.platform_v2 import __main__ as cli
    smoke=load_smoke()
    with patch.object(helper.sys,'platform','linux'),\
            patch('rm_match.platform_v2.admission.AdmissionPolicy.from_manifest') as policy:
        with pytest.raises(SystemExit):cli.main(['--admission-manifest','fixture.json','--authority-affinity-mask','0x10'])
        with pytest.raises(SystemExit):smoke.main(['--authority-affinity-mask','0x10'])
        policy.assert_not_called()


class SchedulingCliLifecycleTests(unittest.TestCase):
    def fixture(self,fail=None):
        path=Path(__file__).with_name('test_platform_wsl_navigation_cli.py')
        spec=importlib.util.spec_from_file_location('_host_scheduling_cli_fixture',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module.CliLifecycleTests.setup(self,fail=fail)

    def test_switch_precedes_model_preparation_and_restores_after_setup_failure(self):
        from rm_match.platform_v2 import __main__ as cli
        events,created=self.fixture(fail='backend');original=sys.getswitchinterval()
        def registry(**_):
            self.assertAlmostEqual(sys.getswitchinterval(),.001,places=6)
            events.append('registry');return object()
        with patch('rm_match.platform_v2.adapters.default_registry',side_effect=registry),\
                self.assertRaisesRegex(ValueError,'backend_failed'):
            cli.main(['--admission-manifest','fixture.json','--host-python-switch-interval-ms','1'])
        self.assertAlmostEqual(sys.getswitchinterval(),original,places=6)
        rows=[json.loads(row) for row in created['stdout'].getvalue().splitlines()]
        self.assertTrue(rows[-1]['host_scheduling']['python_switch_interval']['restored'])

    def test_affinity_only_run_and_cleanup_restore_on_run_failure(self):
        from rm_match.platform_v2 import __main__ as cli
        events,created=self.fixture(fail='run');api=FakeAffinity()
        with patch.object(helper,'_WindowsAffinityAPI',return_value=api),self.assertRaisesRegex(ValueError,'run_failed'):
            cli.main(['--admission-manifest','fixture.json','--authority-affinity-mask','0x10'])
        rows=[json.loads(row) for row in created['stdout'].getvalue().splitlines()]
        self.assertFalse(rows[0]['host_scheduling']['authority_affinity']['applied'])
        self.assertTrue(rows[-1]['host_scheduling']['authority_affinity']['restored'])
        self.assertIn('runtime_close',events);self.assertEqual(api.state,(2,0xff))

    def test_explicit_codec_passed_to_provider_and_actual_identity_reported(self):
        from rm_match.platform_v2 import __main__ as cli
        events,created=self.fixture();calls=[]
        class Camera:
            _raw_encoder_metadata={'codec':'pybase64_1_5_1','origin':'fixture_identity_only'}
            def __init__(self,*args,**kwargs):calls.append(kwargs)
            def stop(self):pass
            def wait_closed(self,timeout):return True
        with patch('rm_match.platform_v2.camera.CameraProvider',Camera):
            cli.main(['--admission-manifest','fixture.json','--camera','--raw-base64-codec','pybase64_1_5_1'])
        self.assertEqual(calls[0]['raw_base64_codec'],'pybase64_1_5_1')
        self.assertEqual(json.loads(created['stdout'].getvalue())['raw_codec_identity'],Camera._raw_encoder_metadata)
