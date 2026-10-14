"""Actual offscreen Qt selector->SDK->MuJoCo protocol SIL; not team navigation.

Default is a dry plan. Actual execution requires --run and a pinned local client
patch. No F2/camera/visible window, GL renderer, NN, ROS or WSL is exercised.
"""
from __future__ import annotations
import argparse
import copy
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import sys
import threading
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
RID='red_infantry';AID='custom_protocol_pipeline_supply'


def write(path,value):path.write_text(json.dumps(value,allow_nan=False,indent=2)+'\n',encoding='utf8')


def plain(path,directory=False):
    path=Path(path).absolute()
    if path.resolve()!=path or path.is_symlink() or (not path.is_dir() if directory else not path.is_file()):
        raise ValueError('plain_existing_local_path_required')
    if path.drive.startswith('\\\\'):raise ValueError('local_drive_required')
    return path


def run(out,a,identity):
    from qa_robotio_protocol_sil import audit
    from rm_match.deployment.launcher import check_client
    from rm_match.deployment.coop_launcher import CappedStderr
    from rm_match.deployment.robotio_plugin import register_robotio_plugins
    from rm_match.deployment.json_adapter import SharedCleanupBudget
    from rm_match.deployment.profile import digest
    from rm_match.deployment.windows_owned_job import WindowsOwnedJobProcess
    from rm_match.platform_v2.adapters import Registry
    from rm_match.platform_v2.backend import MuJoCoBackend
    from rm_match.platform_v2.runtime import PlatformRuntime
    from rm_match.platform_v2.server import PlatformHTTPServer,TransportConfig
    from rm_match.platform_v2.admission import AdmissionPolicy
    from rm_match.navigation_sensors import NavigationSensorConfig
    rows=[];lock=threading.Lock();failures=[];ready=threading.Event();finished=threading.Event()
    qt_ready=None;qt_finished=None;reader=None;child=None;stderr=None;qt_proof=None;runtime=None
    server=None;http=None;backend=None;instance=None;handed=False
    budget=SharedCleanupBudget();prepare_rows=[];prepare_start=time.perf_counter();prepare_limit=prepare_start+15.
    def retain(row):
        with lock:
            if len(rows)>=30000:raise RuntimeError('bounded_protocol_rows_full')
            rows.append(copy.deepcopy(row))
    def close_unclaimed():
        if instance is None or handed:return
        try:instance.close()
        finally:write(out/'UNCLAIMED_CLEANUP.json',instance.shutdown_status)
        if not instance.shutdown_status or not instance.shutdown_status['clean']:raise RuntimeError('unclaimed_cleanup_unproved')
    try:
        registry=Registry();register_robotio_plugins(registry,ROOT/'examples/robotio_protocol_plugins.json')
        spec=registry.get(AID);instance=spec.factory({});instance._budget=budget
        for name in ('decision','navigation'):
            peer=getattr(instance,name);peer._resource_budget=budget;exchange=peer._exchange
            def recorded(packet, peer_name=name, exchange=exchange, **kwargs):
                if packet['op']=='prepare':kwargs['timeout']=min(kwargs['timeout'],prepare_limit-time.perf_counter())
                value=exchange(packet,**kwargs)
                retain(dict(event='peer_exchange',robot_id=RID,peer=peer_name,packet=packet,response=value))
                return value
            peer._exchange=recorded
        for name in ('decision','navigation'):
            if time.perf_counter()>=prepare_limit:raise TimeoutError('prepare_15s_expired')
            peer=getattr(instance,name);start=time.perf_counter()
            if name=='decision':peer.prepare()
            else:
                peer._open_owned_process();original_process=peer.process;original_owner=peer._owned_process
                peer._exchange(dict(op='prepare',config={}),timeout=min(2.,prepare_limit-time.perf_counter()))
                def prepared_open(peer=peer,process=original_process,owner=original_owner):
                    if (peer.failed or peer._cancelled.is_set() or peer.process is not process
                        or peer._owned_process is not owner or process.poll() is not None):raise RuntimeError('prepared_navigation_unavailable')
                    if digest(peer.manifest)!=peer.manifest_sha:raise RuntimeError('prepared_manifest_changed')
                peer._open_owned_process=prepared_open
            end=time.perf_counter();prepare_rows.append(dict(peer=name,started_wall=start,ack_wall=end,elapsed_s=end-start))
            if end>=prepare_limit:raise TimeoutError('prepare_15s_expired')
        write(out/'PREPARE.json',dict(completed=True,rows=prepare_rows,budget_s=15.,elapsed_s=time.perf_counter()-prepare_start,
            scope='two real resource prepare ACKs; zero observations/policy calls/inference'))
        def take(config):
            nonlocal handed
            if type(config) is not dict or config or handed:raise RuntimeError('prepared_handover_once_empty_config')
            for peer in (instance.decision,instance.navigation):
                if peer.failed or peer._cancelled.is_set() or peer.process is None or peer.process.poll() is not None:raise RuntimeError('prepared_peer_unavailable')
                if digest(peer.manifest)!=peer.manifest_sha:raise RuntimeError('prepared_manifest_changed')
            handed=True;return instance
        registry._specs[AID]=type(spec)(spec.descriptor,take)
        sensor_config=NavigationSensorConfig(robot_ids=(RID,),point_rate_hz=1000)
        backend=MuJoCoBackend(navigation_sensors=sensor_config);initial=backend.display_snapshot()
        def trace(row):
            if row.get('robot_id')!=RID:return
            if row['event']=='actuator_consumed' and row['target']['motion'] is not None:
                retain(dict(row,source_action=copy.deepcopy(runtime.outputs.get((RID,'navigation')))))
            elif row['event'] in ('adapter_enqueue','adapter_result'):retain(row)
        runtime=PlatformRuntime(backend,registry=registry,trace=trace,action_ttl=.15)
        credential=secrets.token_urlsafe(32)
        policy=AdmissionPolicy([dict(credential_sha256=hashlib.sha256(credential.encode()).hexdigest(),
            role='operator',allowed_robots=[RID],audit_authorized=False)])
        server=PlatformHTTPServer(TransportConfig(port=0,admission_policy=policy),runtime)
        http=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.05},daemon=True,name='qt-robotio-http');http.start()
        url='http://127.0.0.1:'+str(server.server_address[1])
        if check_client(a.client_root,patch_manifest=a.patch_manifest)!=identity:raise RuntimeError('client_identity_changed_before_launch')
        env=dict(os.environ)
        for key in tuple(env):
            if any(word in key.upper() for word in ('CREDENTIAL','SECRET','TOKEN','PASSWORD')) or key in ('PYTHONPATH','PYTHONHOME'):
                env.pop(key,None)
        env.update(QT_QPA_PLATFORM='offscreen',POLAR_SIM_ADMISSION_CREDENTIAL=credential)
        command=[str(a.client_python),'-u',str(ROOT/'tools/qa_qt_robotio_peer.py'),'--client-root',str(a.client_root),
            '--url',url,'--adapter-id',AID,'--duration',str(a.duration)]
        write(out/'CHILD_COMMAND.json',dict(argv=command,cwd=str(ROOT),credential_transport='memory/environment_only'))
        stderr=CappedStderr(out/'qt.stderr.log')
        child=WindowsOwnedJobProcess(command,cwd=str(ROOT),env=env,stderr=stderr.writer);stderr.writer.close()
        def collect():
            nonlocal qt_ready,qt_finished
            try:
                count=0
                while True:
                    raw=child.stdout.readline(16385)
                    if not raw:break
                    count+=1
                    if count>512 or len(raw)>16384 or not raw.endswith(b'\n'):raise RuntimeError('qt_stdout_bounded_limit')
                    from rm_match.integrations.ros2_bridge import parse_json
                    row=parse_json(raw,16384)
                    if type(row) is not dict:raise RuntimeError('qt_stdout_object_required')
                    event=row.get('event')
                    if event=='qt_ready':
                        if qt_ready is not None or set(row)!={'event','robot_id','selected','plan','binding','actual_widgets','camera','visible_gui','f2'}:
                            raise RuntimeError('qt_ready_shape')
                        if row['robot_id']!=RID or row['selected']!=[AID] or row['plan']!={'navigation':{'adapter_id':AID,'config':{}}}:
                            raise RuntimeError('qt_selected_plan_mismatch')
                        qt_ready=row;ready.set()
                    elif event=='sdk_activation':
                        if set(row)!={'event','robot_id','window','activation'} or row['robot_id']!=RID:raise RuntimeError('qt_sdk_event_shape')
                        retain(row)
                    elif event=='qt_finished':
                        if set(row)!={'event','clean','errors','exit_code'} or qt_finished is not None:raise RuntimeError('qt_finished_shape')
                        qt_finished=row;finished.set()
                    else:raise RuntimeError('unknown_qt_stdout_event')
            except BaseException as exc:failures.append('qt_reader:'+type(exc).__name__);ready.set();finished.set()
        reader=threading.Thread(target=collect,daemon=True,name='qt-robotio-reader');reader.start()
        if not ready.wait(15.) or qt_ready is None or failures:raise RuntimeError('actual_qt_selection_ready_failed')
        write(out/'QT_SELECTED.json',qt_ready)
        child.stdin.write(b'{"op":"go"}\n');child.stdin.flush()
        runtime.run(max_wall_seconds=a.duration,real_time_factor=1.)
    except BaseException as exc:
        failures.append(type(exc).__name__);(out/'failure.log').write_text(traceback.format_exc(),encoding='utf8')
        if getattr(exc,'cleanup_status',None) is not None:write(out/'LAUNCH_FAILURE_CLEANUP.json',exc.cleanup_status)
    finally:
        deadline=budget.claim()
        if child is not None:
            if child.poll() is None:
                try:child.stdin.write(b'{"op":"stop"}\n');child.stdin.flush()
                except Exception as exc:failures.append('qt_stop:'+type(exc).__name__)
            try:child.wait(timeout=max(0.,deadline-time.perf_counter()-.2))
            except Exception as exc:failures.append('qt_wait:'+type(exc).__name__)
            try:qt_proof=child.cleanup(deadline)
            except Exception as exc:failures.append('qt_job_cleanup:'+type(exc).__name__)
            try:
                if reader is not None:reader.join(max(0.,deadline-time.perf_counter()))
                child.stdin.close();child.stdout.close();child.release_handles()
            except Exception as exc:failures.append('qt_handles:'+type(exc).__name__)
        if stderr is not None:
            try:stderr.close_until(deadline)
            except Exception as exc:failures.append('qt_stderr:'+type(exc).__name__)
        if runtime is not None and not runtime._closed:
            try:runtime.close()
            except Exception as exc:failures.append('runtime_close:'+type(exc).__name__)
        elif runtime is None and backend is not None:
            try:backend.close()
            except Exception as exc:failures.append('backend_close:'+type(exc).__name__)
        try:close_unclaimed()
        except Exception as exc:failures.append('unclaimed_close:'+type(exc).__name__)
        if server is not None:
            try:
                if http is not None and http.is_alive():server.shutdown()
                server.server_close()
                if http is not None:http.join(max(0.,deadline-time.perf_counter()))
            except Exception as exc:failures.append('http_cleanup:'+type(exc).__name__)
        cleanup=dict(qt_job=qt_proof,qt_finished=qt_finished,reader_stopped=reader is None or not reader.is_alive(),
            http_stopped=http is None or not http.is_alive(),http_workers_idle=server is None or server._slots._value==server.config.max_http_workers,
            runtime=None if runtime is None else runtime.shutdown_status,pipeline=None if instance is None else instance.shutdown_status)
        write(out/'CLEANUP.json',cleanup)
    if not (out/'PREPARE.json').exists():write(out/'PREPARE.json',dict(completed=False,rows=prepare_rows,budget_s=15.))
    with (out/'PROTOCOL_TRACE.jsonl.gz').open('wb') as stream:
        with gzip.GzipFile(filename='',mode='wb',fileobj=stream,mtime=0) as gz:
            for row in rows:gz.write(json.dumps(row,allow_nan=False,separators=(',',':')).encode()+b'\n')
    independent=audit(rows);write(out/'AUDIT.json',independent)
    if runtime is not None and initial is not None and runtime.cached.get('robots'):
        xy0=next(r['xy'] for r in initial['robots'] if r['robot_id']==RID)
        xy1=next(r['xy'] for r in runtime.cached['robots'] if r['robot_id']==RID)
        write(out/'EVAL.json',dict(source='isolated_world_evaluation_never_peer_input',initial_xy=xy0,final_xy=xy1,displacement_m=math.dist(xy0,xy1)))
    physical=independent['physical'][RID]
    checks=dict(two_actual_resource_prepare_acks=len(prepare_rows)==2,actual_qt_widgets_selected=qt_ready is not None,
        actual_sdk_clean_ack=qt_finished is not None and qt_finished['clean'] is True and qt_finished['exit_code']==0,
        actual_physical_motion=physical['nonzero_sim_steps']>0,typed_source_sdk150_receipt_join=not independent['errors'],
        no_adapter_fault=not any(row['event']=='adapter_result' and row.get('error') for row in rows),
        original_dt_2ms=backend is not None and backend.timestep==.002,
        runtime_clean=bool(runtime and runtime.shutdown_status and runtime.shutdown_status['clean']),
        pipeline_clean=bool(instance and instance.shutdown_status and instance.shutdown_status['clean']),
        qt_job_clean=bool(qt_proof and qt_proof['clean'] and qt_proof['group_empty'] and qt_proof['returncode']==0),
        io_http_threads_stopped=cleanup['reader_stopped'] and cleanup['http_stopped'] and cleanup['http_workers_idle'],errors_empty=not failures)
    return dict(passed=all(checks.values()),checks=checks,errors=failures,physical=physical,
        steps=None if runtime is None else runtime.steps,qualification='actual_offscreen_widgets_clientSDK_low_rate_protocol_SIL_only',
        limitations=['not original Jello/F2/camera/visible GUI','synthetic fixtures, not team decision/navigation',
            '1000 points/s, not MID360/SLAM/RTF/match qualification','no NN/ROS/WSL/GL renderer'])


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument('--client-root',type=Path,default=ROOT/'external/polar-rm-client-robotio-review')
    p.add_argument('--patch-manifest',type=Path,default=ROOT/'client_patches/CLIENT_ROBOTIO_PATCH_MANIFEST.json')
    p.add_argument('--client-python',type=Path,default=ROOT/'.venv-client/Scripts/python.exe')
    p.add_argument('--out',type=Path);p.add_argument('--duration',type=float,default=3.5);p.add_argument('--run',action='store_true')
    a=p.parse_args(argv)
    if not math.isfinite(a.duration) or not 3<=a.duration<=4:raise ValueError('duration_3_to_4_seconds_required')
    a.client_root=plain(a.client_root,True);a.patch_manifest=plain(a.patch_manifest);a.client_python=plain(a.client_python)
    from rm_match.deployment.launcher import check_client
    identity=check_client(a.client_root,patch_manifest=a.patch_manifest)
    plan=dict(phase='DRY_PLAN_NOT_READY',robot_id=RID,adapter_id=AID,duration=a.duration,
        client_identity=identity,physics_timestep_s=.002,point_rate_hz=1000,credential_transport='memory/environment_only',
        explicit_run_required=True,scope='offscreen selector+client SDK only; no F2/camera/visible GUI/real navigation')
    if not a.run:print(json.dumps(plan,allow_nan=False,indent=2));return 0
    if sys.platform!='win32' or a.out is None:raise RuntimeError('Windows_and_fresh_output_required')
    out=a.out.absolute()
    if out.exists() or not out.is_relative_to(ROOT/'artifacts') or out.resolve()!=out:raise ValueError('fresh_owned_artifacts_output_required')
    out.mkdir(parents=True);records=[];started=time.perf_counter();result=None
    try:
        import qa_robotio_protocol_sil as protocol
        files=set(protocol.SOURCE_FILES)|{'tools/qa_qt_robotio_protocol.py','tools/qa_qt_robotio_peer.py',
            'rm_match/deployment/launcher.py','rm_match/deployment/coop_launcher.py'}
        for rel in sorted(files):
            raw=(ROOT/rel).read_bytes();target=out/'source'/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
            records.append(dict(path=str(ROOT/rel),snapshot='source/'+rel,size=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
        for rel in ('rm_client/sim_platform_adapters.py','rm_client/sim_platform_client.py'):
            source=a.client_root/rel;raw=source.read_bytes();target=out/'client_source'/rel
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
            records.append(dict(path=str(source),snapshot='client_source/'+rel,size=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
        raw=a.patch_manifest.read_bytes();(out/'CLIENT_PATCH_MANIFEST.json').write_bytes(raw)
        records.append(dict(path=str(a.patch_manifest),snapshot='CLIENT_PATCH_MANIFEST.json',size=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
        write(out/'SOURCE_MANIFEST.json',dict(files=records));write(out/'COMMAND.json',dict(argv=sys.argv,plan=plan))
        result=run(out,a,identity)
    except BaseException as exc:
        result=dict(passed=False,error_type=type(exc).__name__);(out/'driver_failure.log').write_text(traceback.format_exc(),encoding='utf8')
    unchanged=all(hashlib.sha256(Path(row['path']).read_bytes()).hexdigest()==row['sha256'] for row in records)
    result.update(source_unchanged=unchanged,elapsed_seconds=time.perf_counter()-started)
    code=0 if result['passed'] and unchanged else 2;result['exit_code']=code;write(out/'RESULT.json',result)
    print(json.dumps(dict(passed=code==0,exit_code=code,out=str(out)),allow_nan=False));return code


if __name__=='__main__':raise SystemExit(main())
