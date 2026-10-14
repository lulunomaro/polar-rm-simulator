"""Small launcher identity/lifecycle mocks. No GUI, WSL, renderer or model."""
import copy
import hashlib
import io
import json
from pathlib import Path
import threading
from unittest.mock import patch
import pytest
from rm_match.deployment import coop_launcher as coop


def config():
    return dict(schema=coop.SCHEMA,client_root='external/polar-rm-client-state-review',
        client_python='.venv-client/Scripts/python.exe')


def test_dry_plan_exact_local_argv_and_manual_scope_without_any_spawn():
    with patch.object(coop,'client_patch_identity',return_value={'hash':'fixture'}),patch.object(coop,'launch') as launch:
        plan=coop.build_plan(config())
    assert plan['manual_robots']==['red_infantry'] and plan['robot_count']==6 and plan['timestep_s']==.002
    assert not plan['automatic_binding'] and not plan['automatic_goal']
    assert plan['phase']=='PLAN_ONLY_NOT_READY' and not plan['native_registered']
    assert plan['server_argv'][3]=='rm_match.deployment.coop_launcher'
    payload=dict(schema=coop.SCHEMA,core_argv=plan['core_server_argv'],url=plan['url'])
    assert plan['server_argv'][-1]==hashlib.sha256((json.dumps(payload,allow_nan=False)+'\n').encode()).hexdigest()
    launch.assert_not_called()


@pytest.mark.parametrize('change',[
    {'manual_robots':['red_sentry','red_infantry']},{'pb_wsl_navigation_manifest':'artifacts/local-pb.json'}])
def test_local_explicit_extension_does_not_send_goal_or_auto_control(change):
    with patch.object(coop,'client_patch_identity',return_value={}):plan=coop.build_plan(dict(config(),**change))
    assert not plan['automatic_goal'] and not plan['automatic_binding']
    if 'pb_wsl_navigation_manifest' in change:assert '--pb-wsl-navigation-manifest' in plan['core_server_argv']


@pytest.mark.parametrize('change',[{'manual_robots':[{}]},{'manual_robots':['red_infantry','red_infantry']},
    {'port':True},{'max_wall_seconds':float('nan')},{'script_argv':['bad']},{'raw_base64_codec':'unknown'}])
def test_invalid_local_config_is_rejected(change):
    with patch.object(coop,'client_patch_identity',return_value={}):
        with pytest.raises(ValueError):coop.build_plan(dict(config(),**change))


def test_readiness_is_exact_expected_url_transport_and_real_opt_in_camera():
    event=threading.Event();stream=io.StringIO();tap=coop._ReadyTap(stream,event,'http://127.0.0.1:8766')
    correct=dict(url='http://127.0.0.1:8766',transport='loopback_only',camera='real_opt_in')
    for change in ({'url':'http://127.0.0.1:9999'},{'transport':'lan'},{'camera':'factory_imported'}):
        tap.write(json.dumps(dict(correct,**change))+'\n');assert not event.is_set()
    tap.write(json.dumps(correct)+'\n');assert event.is_set()


@pytest.mark.parametrize('raw',[b'{"op":"stop","op":"stop"}',b'{"op":"stop","extra":1}',b'{"op":NaN}'])
def test_stop_duplicate_and_nonfinite_are_rejected(raw):
    with pytest.raises(ValueError):
        if coop.strict_json(raw)!={'op':'stop'}:raise ValueError('invalid op')


def worker_plan(tmp_path):
    value=dict(schema=coop.SCHEMA,core_argv=[str(Path(coop.sys.executable).absolute()),'-u','-m','rm_match.platform_v2'],url='http://127.0.0.1:8766')
    path=tmp_path/'plan.json';raw=json.dumps(value).encode();path.write_bytes(raw)
    return path,hashlib.sha256(raw).hexdigest()


def test_worker_ack_only_after_main_normal_return_and_thread_finished(tmp_path,capsys):
    path,sha=worker_plan(tmp_path);events=[]
    with patch.object(coop.sys,'platform','win32'),patch.object(coop,'read_stop',side_effect=lambda done:done.wait(.2) and False),\
            patch('rm_match.platform_v2.__main__.main',side_effect=lambda args:events.append('main_returned')):
        assert coop.worker(path,sha)==0
    rows=[json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events==['main_returned'] and rows[-1]['event']=='coop_server_finished' and rows[-1]['clean']


def test_worker_failed_main_has_no_cleanup_ack(tmp_path,capsys):
    path,sha=worker_plan(tmp_path)
    with patch.object(coop.sys,'platform','win32'),patch.object(coop,'read_stop',side_effect=lambda done:done.wait(.2) and False),\
            patch('rm_match.platform_v2.__main__.main',side_effect=RuntimeError('cleanup failed')):
        with pytest.raises(RuntimeError):coop.worker(path,sha)
    assert 'coop_server_finished' not in capsys.readouterr().out


def fake_launch(tmp_path,*,ack=True,reader_failure=False,client_code=0,nonobjects=False):
    out=coop.ROOT/'artifacts'/('coop-unit-'+tmp_path.name)
    p=coop.build_plan(config(),out=out);instances=[];envs=[]
    ready=dict(url=p['url'],transport='loopback_only',camera='real_opt_in')
    rows=[ready]+([dict(event='coop_server_finished',url=p['url'],clean=True)] if ack else [])
    if nonobjects:rows=['noise',None,12]+rows+[[]]
    class Sink(io.BytesIO):
        def __init__(self,owner):super().__init__();self.owner=owner
        def write(self,value):self.owner.code=0;return super().write(value)
    class Child:
        def __init__(self,argv,**kwargs):
            self.is_server=len(instances)==0;self.code=None if self.is_server else client_code
            self.stdout=io.BytesIO((''.join(json.dumps(row)+'\n' for row in rows)).encode() if self.is_server else b'')
            self.stdin=Sink(self);self.cleaned=False;self.released=False
            instances.append(self);envs.append(kwargs['env'])
        def poll(self):return self.code
        def cleanup(self,deadline):self.cleaned=True;return dict(clean=True,reaped=True,group_empty=True)
        def release_handles(self):self.released=True
    patches=[patch.object(coop.sys,'platform','win32'),patch.object(coop,'check_client',return_value={'client_patch':p['client_patch']}),
        patch.object(coop,'executable'),patch('rm_match.deployment.windows_owned_job.WindowsOwnedJobProcess',Child)]
    if reader_failure:patches.append(patch.object(coop,'ReadyLines',side_effect=RuntimeError('reader failed')))
    return p,out,instances,envs,patches


@pytest.mark.parametrize('ack,reader_failure',[(True,False),(False,False),(False,True)])
def test_launch_ownership_env_credential_missing_ack_and_reader_failure(tmp_path,ack,reader_failure):
    import contextlib,shutil
    p,out,children,envs,patches=fake_launch(tmp_path,ack=ack,reader_failure=reader_failure)
    try:
        with contextlib.ExitStack() as stack:
            for item in patches:stack.enter_context(item)
            code=coop.launch(p)
        result=json.loads((out/'RESULT.json').read_bytes())
        assert result['game_ready'] is False and result['clean']==(ack and not reader_failure)
        assert code==(0 if ack and not reader_failure else 2)
        assert all(child.cleaned and child.released for child in children)
        assert 'POLAR_SIM_ADMISSION_CREDENTIAL' not in envs[0]
        if len(envs)>1:
            secret=envs[1]['POLAR_SIM_ADMISSION_CREDENTIAL']
            assert secret not in (out/'plan.json').read_text() and secret not in (out/'RESULT.json').read_text()
        grant=json.loads((out/'admission.json').read_bytes())['grants'][0]
        assert grant['allowed_robots']==['red_infantry'] and not grant['audit_authorized']
    finally:
        # Only this freshly generated unit-owned output is removed.
        assert out.resolve().is_relative_to((coop.ROOT/'artifacts').resolve())
        shutil.rmtree(out)


def test_nonobject_logs_do_not_break_cleanup_and_nonzero_client_is_failure(tmp_path):
    import contextlib,shutil
    p,out,children,envs,patches=fake_launch(tmp_path,client_code=7,nonobjects=True)
    try:
        with contextlib.ExitStack() as stack:
            for item in patches:stack.enter_context(item)
            assert coop.launch(p)==2
        result=json.loads((out/'RESULT.json').read_bytes())
        assert not result['clean'] and result['client_returncode_before_cleanup']==7
        assert result['server_clean_ack'] and all(child.released for child in children)
        assert (out/'READY.json').exists() and (out/'SERVER_FINISHED.json').exists()
    finally:
        assert out.resolve().is_relative_to((coop.ROOT/'artifacts').resolve());shutil.rmtree(out)


def test_stderr_file_open_failure_closes_both_created_pipe_ends(tmp_path):
    actual=coop.os.fdopen;opened=[]
    def track(*args,**kwargs):
        stream=actual(*args,**kwargs);opened.append(stream);return stream
    with patch.object(coop.os,'fdopen',side_effect=track),patch.object(Path,'open',side_effect=OSError('fixture')):
        with pytest.raises(OSError):coop.CappedStderr(tmp_path/'failed.log')
    assert len(opened)==2 and all(stream.closed for stream in opened)


def test_stderr_has_actual_bounded_store_and_reports_overflow(tmp_path):
    cap=coop.CappedStderr(tmp_path/'stderr.log');cap.limit=32
    cap.writer.write(b'x'*64);cap.writer.close()
    with pytest.raises(RuntimeError):cap.close_until(coop.time.perf_counter()+1.)
    assert (tmp_path/'stderr.log').read_bytes()==b'x'*32 and not cap.thread.is_alive()
