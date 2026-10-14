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


def fake_launch(tmp_path,*,ack=True,reader_failure=False,client_code=0,nonobjects=False,plan_config=None,startup_mutation=None):
    out=coop.ROOT/'artifacts'/('coop-unit-'+tmp_path.name)
    p=coop.build_plan(config() if plan_config is None else plan_config,out=out);instances=[];envs=[]
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
            if self.is_server and startup_mutation is not None:startup_mutation()
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


def graph_files(tmp_path):
    from rm_match.deployment.navigation_plugin import CAPABILITIES as nav_caps, MANIFEST_SCHEMA as nav_schema
    from rm_match.deployment.decision_plugin import CAPABILITIES as dec_caps, MANIFEST_SCHEMA as dec_schema
    paths={}
    for name,caps,schema in [('navigation',nav_caps,nav_schema),('decision',dec_caps,dec_schema)]:
        value=dict(schema=schema,adapters=[dict(adapter_id='custom_fixture_'+name,label='Readonly manifest fixture',
            command=[coop.sys.executable,'-u','reviewed_wrapper.py'],cwd=str(tmp_path),supported_robots=['red_infantry'],
            transport='jsonl_v1',capabilities=copy.deepcopy(caps))])
        path=tmp_path/(name+'.json');path.write_text(json.dumps(value),encoding='utf8');paths[name]=path
    graph=tmp_path/'robotio.json'
    graph.write_text(json.dumps(dict(schema='polar.sim.robotio-plugins.v1',
        manifests={name:path.name for name,path in paths.items()}|{'aim':None},pipelines=[])),encoding='utf8')
    return graph,paths


def test_generic_graph_argv_snapshots_without_extra_pb_robot_or_implicit_authority(tmp_path):
    graph,components=graph_files(tmp_path)
    with patch.object(coop,'client_patch_identity',return_value={}),\
            patch('rm_match.deployment.robotio_plugin.load_robotio_plugins') as loader,\
            patch.object(coop,'launch') as launch:
        plan=coop.build_plan(dict(config(),robotio_plugins_json=str(graph),prepare_robotio_plugins=True))
    core=plan['core_server_argv']
    assert core[core.index('--robotio-plugins-json')+1]==str(graph)
    assert '--prepare-robotio-plugins' in core and '--pb-wsl-navigation-manifest' not in core
    assert plan['manual_robots']==['red_infantry'] and plan['robotio_plugins_registered']
    assert not plan['automatic_binding'] and not plan['automatic_goal']
    assert plan['fire_authority']=='existing_manual_only'
    assert set(plan['local_file_sha256'])=={str(graph),*(str(path) for path in components.values())}
    assert plan['server_argv'][-1]==hashlib.sha256((json.dumps(coop.server_plan_data(plan),allow_nan=False)+'\n').encode()).hexdigest()
    coop.validate_worker_argv(core,plan['url']);coop.verify_local_files(plan['local_file_sha256'])
    loader.assert_not_called();launch.assert_not_called()


@pytest.mark.parametrize('change',[
    {'prepare_robotio_plugins':True},{'prepare_robotio_plugins':1},{'prepare_robotio_plugins':'true'},
    {'robotio_plugins_json':'https://example.invalid/graph.json'},
    {'client_patch_manifest':'file:///C:/reviewed/patch.json'},
    {'client_root':'\\\\server\\share\\client'},
    {'client_python':'--sim-endpoint'},{'client_root':'C:relative_client'},
    {'robotio_plugins_json':'--pb-wsl-navigation-manifest'},
    {'client_patch_manifest':False},{'robotio_plugins_json':''}])
def test_generic_options_reject_nonlocal_paths_bool_coercion_and_missing_graph(change):
    with patch.object(coop,'client_patch_identity',return_value={}):
        with pytest.raises(ValueError):coop.build_plan(dict(config(),**change))


def test_combined_client_patch_manifest_identity_is_frozen_and_mismatch_fails_before_launch(tmp_path):
    manifest=tmp_path/'patch.json';manifest.write_text('{"schema":"fixture"}',encoding='utf8')
    sha=hashlib.sha256(manifest.read_bytes()).hexdigest()
    with patch.object(coop,'client_patch_identity',return_value={'manifest_sha256':sha}) as identity:
        plan=coop.build_plan(dict(config(),client_patch_manifest=str(manifest)))
    identity.assert_called_once_with(manifest_path=str(manifest))
    assert plan['client_patch_manifest']==str(manifest)
    assert plan['local_file_sha256'][str(manifest)]==sha
    with patch.object(coop,'client_patch_identity',return_value={'manifest_sha256':'0'*64}),patch.object(coop,'launch') as launch:
        with pytest.raises(ValueError,match='snapshot mismatch'):
            coop.build_plan(dict(config(),client_patch_manifest=str(manifest)))
        launch.assert_not_called()


@pytest.mark.parametrize('which',['graph','navigation','decision'])
def test_changed_graph_or_component_is_rejected_before_owned_launch(tmp_path,which):
    graph,components=graph_files(tmp_path)
    with patch.object(coop,'client_patch_identity',return_value={}):
        plan=coop.build_plan(dict(config(),robotio_plugins_json=str(graph)))
    changed=graph if which=='graph' else components[which]
    changed.write_bytes(changed.read_bytes()+b' ')
    with patch.object(coop.sys,'platform','win32'),patch.dict(coop.os.environ,{'QT_QPA_PLATFORM':''}),\
            patch('rm_match.deployment.windows_owned_job.WindowsOwnedJobProcess') as spawn:
        with pytest.raises(ValueError,match='changed after plan'):coop.launch(plan)
        spawn.assert_not_called()


def test_main_keeps_config_snapshot_and_rejects_change_before_launch(tmp_path):
    path=tmp_path/'config.json';path.write_text(json.dumps(config()),encoding='utf8')
    actual_launch=coop.launch
    def invoke(plan):
        assert plan['local_file_sha256'][str(path)]==hashlib.sha256(path.read_bytes()).hexdigest()
        path.write_bytes(path.read_bytes()+b' ')
        return actual_launch(plan)
    with patch.object(coop,'client_patch_identity',return_value={}),patch.object(coop,'launch',side_effect=invoke),\
            patch.object(coop.sys,'platform','win32'),patch.dict(coop.os.environ,{'QT_QPA_PLATFORM':''}),\
            patch('rm_match.deployment.windows_owned_job.WindowsOwnedJobProcess') as spawn:
        with pytest.raises(ValueError,match='changed after plan'):
            coop.main(['--config',str(path),'--run'])
        spawn.assert_not_called()


@pytest.mark.parametrize('tail',[
    ['--robotio-plugins-json','https://example.invalid/graph.json'],
    ['--admission-manifest','\\\\server\\share\\grants.json'],
    ['--prepare-robotio-plugins'],['--sim-endpoint','http://example.invalid:8766'],
    ['--robotio-plugins-json','--port'],['--port','8766','--port','8766'],
    ['--max-wall-seconds','NaN'],['--raw-base64-codec','fallback']])
def test_worker_rejects_unknown_network_injected_or_duplicate_argv_before_main(tmp_path,tail):
    value=dict(schema=coop.SCHEMA,core_argv=[str(Path(coop.sys.executable).absolute()),'-u','-m','rm_match.platform_v2',*tail],
               url='http://127.0.0.1:8766')
    path=tmp_path/'worker.json';raw=json.dumps(value).encode();path.write_bytes(raw)
    with patch.object(coop.sys,'platform','win32'),patch('rm_match.platform_v2.__main__.main') as main:
        with pytest.raises(ValueError):coop.worker(path,hashlib.sha256(raw).hexdigest())
        main.assert_not_called()


def test_worker_rechecks_local_file_snapshots_before_startup(tmp_path):
    graph,components=graph_files(tmp_path)
    with patch.object(coop,'client_patch_identity',return_value={}):
        plan=coop.build_plan(dict(config(),robotio_plugins_json=str(graph)))
    raw=(json.dumps(coop.server_plan_data(plan),allow_nan=False)+'\n').encode()
    worker=tmp_path/'worker.json';worker.write_bytes(raw)
    components['navigation'].write_bytes(components['navigation'].read_bytes()+b' ')
    with patch.object(coop.sys,'platform','win32'),patch('rm_match.platform_v2.__main__.main') as main:
        with pytest.raises(ValueError,match='changed after plan'):
            coop.worker(worker,hashlib.sha256(raw).hexdigest())
        main.assert_not_called()


def test_combined_patch_identity_mismatch_blocks_job_and_admission_creation(tmp_path):
    manifest=tmp_path/'patch.json';manifest.write_text('{"schema":"fixture"}',encoding='utf8')
    sha=hashlib.sha256(manifest.read_bytes()).hexdigest()
    out=coop.ROOT/'artifacts'/('coop-unit-'+tmp_path.name)
    with patch.object(coop,'client_patch_identity',return_value={'manifest_sha256':sha}):
        plan=coop.build_plan(dict(config(),client_patch_manifest=str(manifest)),out=out)
    with patch.object(coop.sys,'platform','win32'),patch.dict(coop.os.environ,{'QT_QPA_PLATFORM':''}),\
            patch.object(coop,'executable'),patch.object(coop,'check_client',return_value={'client_patch':{'wrong':'identity'}}) as checked,\
            patch('rm_match.deployment.windows_owned_job.WindowsOwnedJobProcess') as spawn:
        with pytest.raises(ValueError,match='patch changed'):coop.launch(plan)
    checked.assert_called_once_with(plan['client_root'],patch_manifest=str(manifest))
    spawn.assert_not_called();assert not out.exists()


@pytest.mark.parametrize('which',['navigation','patch'])
def test_snapshot_changed_during_server_start_blocks_client_and_keeps_owned_cleanup(tmp_path,which):
    import contextlib,shutil
    graph,components=graph_files(tmp_path)
    manifest=tmp_path/'patch.json';manifest.write_text('{"schema":"fixture"}',encoding='utf8')
    sha=hashlib.sha256(manifest.read_bytes()).hexdigest()
    changed=manifest if which=='patch' else components['navigation']
    def mutate():changed.write_bytes(changed.read_bytes()+b' ')
    with patch.object(coop,'client_patch_identity',return_value={'manifest_sha256':sha}):
        plan,out,children,envs,patches=fake_launch(tmp_path,
            plan_config=dict(config(),robotio_plugins_json=str(graph),client_patch_manifest=str(manifest)),
            startup_mutation=mutate)
    try:
        with contextlib.ExitStack() as stack:
            for item in patches:stack.enter_context(item)
            assert coop.launch(plan)==2
        result=json.loads((out/'RESULT.json').read_bytes())
        assert result['reason']=='launch_failed' and result['error_type']=='ValueError'
        assert len(children)==1 and all(child.cleaned and child.released for child in children)
        assert result['clean'] and result['server_clean_ack']
        assert result['game_ready'] is False
        assert 'POLAR_SIM_ADMISSION_CREDENTIAL' not in envs[0]
        assert json.loads((out/'admission.json').read_bytes())['grants'][0]['allowed_robots']==['red_infantry']
    finally:
        assert out.resolve().is_relative_to((coop.ROOT/'artifacts').resolve());shutil.rmtree(out)


def test_worker_accepts_new_generic_flags_and_original_hashes_without_registering_peers(tmp_path,capsys):
    graph,components=graph_files(tmp_path)
    with patch.object(coop,'client_patch_identity',return_value={}):
        plan=coop.build_plan(dict(config(),robotio_plugins_json=str(graph),prepare_robotio_plugins=True))
    raw=(json.dumps(coop.server_plan_data(plan),allow_nan=False)+'\n').encode()
    worker=tmp_path/'worker.json';worker.write_bytes(raw)
    with patch.object(coop.sys,'platform','win32'),\
            patch.object(coop,'read_stop',side_effect=lambda done:done.wait(.2) and False),\
            patch('rm_match.platform_v2.__main__.main') as main:
        assert coop.worker(worker,hashlib.sha256(raw).hexdigest())==0
    main.assert_called_once_with(plan['core_server_argv'][4:])
    assert json.loads(capsys.readouterr().out.splitlines()[-1])['event']=='coop_server_finished'


@pytest.mark.parametrize('path',['https://example.invalid/config.json','\\\\server\\share\\config.json'])
def test_configuration_network_paths_rejected_before_filesystem_access(path):
    with patch.object(Path,'is_symlink') as inspect:
        with pytest.raises(ValueError):coop.read_local(path)
        inspect.assert_not_called()


def test_main_freezes_canonical_config_path_with_parent_segments(tmp_path, monkeypatch):
    path=tmp_path/'config.json';path.write_text(json.dumps(config()),encoding='utf8')
    nested=tmp_path/'nested';nested.mkdir();monkeypatch.chdir(nested)
    with patch.object(coop,'client_patch_identity',return_value={}),patch.object(coop,'launch',return_value=0) as launch:
        assert coop.main(['--config','../config.json','--run'])==0
    plan=launch.call_args.args[0]
    assert plan['local_file_sha256']=={str(path):hashlib.sha256(path.read_bytes()).hexdigest()}
    coop.verify_local_files(plan['local_file_sha256'])
