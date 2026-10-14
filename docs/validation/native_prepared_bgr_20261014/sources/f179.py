#!/usr/bin/env python3
"""Linux-local saved real sensor-frame compute diagnostic, never live evidence."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import time
import traceback
import math
import tempfile
from contextlib import contextmanager
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

PHASE_PREFIX='[RMCS-FIRST-FRAME] '
PHASE_SCHEMA='rmcs.first-frame-trace.v1'
PHASE_PROFILES=('first-frame-trace','request-preallocate-trace')
PHASE_NAMES=frozenset(('model_compile','request_preallocate','first_tick','actual_bgr_read',
    'generate_request','tensor_create','request_create','input_attach','resize','infer','post_nms','detector',
    'pose_estimation','tracker','control','stdout_serialize'))
STARTUP_PHASE_NAMES=frozenset(('model_compile','request_preallocate','tensor_create','request_create'))
CORE_FRAME_PHASES=frozenset(('first_tick','actual_bgr_read','generate_request','resize','input_attach','infer','post_nms',
    'detector','pose_estimation','tracker','control','stdout_serialize'))


def saved_request_identity(request):
    """Original sensor/control clock identity, never host/QPC-derived stamps."""
    if type(request.get('frame_id')) is not int or request['frame_id']<0:raise ValueError('Invalid saved frame identity')
    values=[]
    for name in ('capture_sim_time','observation_sim_time'):
        value=request.get(name)
        if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1e9:
            raise ValueError('Invalid saved '+name)
        values.append(round(value*1e9))
    if values[1]<values[0]:raise ValueError('Saved control precedes exposure')
    return dict(frame_id=request['frame_id'],exposure_timestamp_ns=values[0],control_time_ns=values[1])


def parse_native_phase_stderr(text,request,*,expected_profile=None,eof_complete=True):
    """Strict, bounded, Linux-local diagnostic protocol; no native execution.

    Ordinary original ELF stderr remains compatible: absent diagnostic records
    are reported unavailable, and become an error only when explicitly required.
    EOF/partial phases and malformed or mismatched records never count as success.
    """
    if expected_profile is not None and expected_profile not in PHASE_PROFILES:raise ValueError('Unknown phase profile')
    if type(text) is not str or len(text)>16*1024*1024:raise ValueError('Unbounded native stderr')
    if type(eof_complete) is not bool:raise ValueError('Invalid phase EOF state')
    identity=saved_request_identity(request)
    records=[];completed=[];stack=[];errors=[];profile=None;last_ns=None
    def error(code,line=None,phase=None):
        row=dict(code=code)
        if line is not None:row['line']=line
        if phase is not None:row['phase']=phase
        errors.append(row)
    fields={'schema','profile','phase','event','frame_id','exposure_timestamp_ns','control_time_ns',
        'linux_steady_ns','clock_domain','startup'}
    for line_no,line in enumerate(text.splitlines(keepends=True),1):
        if not line.startswith('[RMCS-FIRST-FRAME]'):continue
        if len(records)>=4096:error('too_many_phase_records',line_no);break
        if not line.startswith(PHASE_PREFIX):error('malformed_phase_prefix',line_no);continue
        if not line.endswith('\n'):error('partial_phase_line_at_eof',line_no);continue
        try:
            row=_saved_json(line[len(PHASE_PREFIX):])
            if type(row) is not dict:raise ValueError('phase object required')
            event=row.get('event')
            allowed=fields|({'elapsed_ns','exception_unwinding'} if event=='end' else set())
            if set(row)!=allowed or event not in ('begin','end'):raise ValueError('phase fields')
            if row['schema']!=PHASE_SCHEMA or type(row['schema']) is not str:raise ValueError('phase schema')
            if type(row['profile']) is not str or row['profile'] not in PHASE_PROFILES:raise ValueError('phase profile')
            if type(row['phase']) is not str or row['phase'] not in PHASE_NAMES:raise ValueError('phase name')
            if type(row['startup']) is not bool or row['clock_domain']!='linux_steady_diagnostic_only':raise ValueError('phase clock/startup')
            for key in ('frame_id','exposure_timestamp_ns','control_time_ns','linux_steady_ns'):
                if type(row[key]) is not int or not (-1 if key!='linux_steady_ns' else 0)<=row[key]<=2**63-1:
                    raise ValueError('phase integer')
            if event=='end' and (type(row['elapsed_ns']) is not int or not 0<=row['elapsed_ns']<=2**63-1
                or type(row['exception_unwinding']) is not bool):raise ValueError('phase end values')
        except (ValueError,TypeError,OverflowError):error('invalid_phase_record',line_no);continue
        records.append(row)
        if profile is None:profile=row['profile']
        if row['profile']!=profile or (expected_profile is not None and row['profile']!=expected_profile):error('phase_profile_mismatch',line_no,row['phase'])
        if row['startup'] and row['phase'] not in STARTUP_PHASE_NAMES:error('invalid_startup_phase',line_no,row['phase'])
        if not row['startup'] and row['phase'] in ('model_compile','request_preallocate'):error('startup_phase_marked_as_frame',line_no,row['phase'])
        if (row['profile']=='request-preallocate-trace' and not row['startup']
            and row['phase'] in ('tensor_create','request_create')):error('preallocated_request_created_inside_frame',line_no,row['phase'])
        if row['profile']=='first-frame-trace' and row['startup'] and row['phase']!='model_compile':error('lazy_profile_preallocated_at_startup',line_no,row['phase'])
        expected={k:-1 for k in identity} if row['startup'] else identity
        if any(row[k]!=v for k,v in expected.items()):error('phase_original_identity_mismatch',line_no,row['phase'])
        stamp=row['linux_steady_ns']
        if last_ns is not None and stamp<last_ns:error('phase_clock_reversed',line_no,row['phase'])
        last_ns=stamp
        key=(row['startup'],row['phase'])
        if row['event']=='begin':
            if any((r['startup'],r['phase'])==key for r in stack):error('phase_duplicate_active_begin',line_no,row['phase'])
            stack.append(row)
        elif not stack or (stack[-1]['startup'],stack[-1]['phase'])!=key:
            error('phase_end_without_matching_nested_begin',line_no,row['phase'])
        else:
            begin=stack.pop();elapsed=stamp-begin['linux_steady_ns']
            if row['elapsed_ns']!=elapsed:error('phase_elapsed_mismatch',line_no,row['phase'])
            if row['exception_unwinding']:error('phase_exception_unwinding',line_no,row['phase'])
            completed.append(dict(phase=row['phase'],startup=row['startup'],begin_linux_steady_ns=begin['linux_steady_ns'],
                end_linux_steady_ns=stamp,elapsed_ns=row['elapsed_ns'],exception_unwinding=row['exception_unwinding']))
    if stack:
        for row in stack:error('phase_begin_without_end_at_eof',phase=row['phase'])
    if not eof_complete:error('phase_stream_eof_not_confirmed')
    if not records and expected_profile is not None:error('required_phase_stream_missing')
    counts={}
    for row in completed:
        key=(row['startup'],row['phase']);counts[key]=counts.get(key,0)+1
    for (startup,phase),count in counts.items():
        if count>1:error('phase_completed_more_than_once',phase=phase)
    stream_valid=bool(records) and not errors
    required=CORE_FRAME_PHASES
    if profile=='first-frame-trace':required=required|{'tensor_create','request_create'}
    elif profile=='request-preallocate-trace':required=required|{'input_attach'}
    missing=sorted(phase for phase in required if counts.get((False,phase),0)!=1)
    required_startup=({'model_compile','request_preallocate','tensor_create','request_create'}
        if profile=='request-preallocate-trace' else {'model_compile'})
    missing_startup=sorted(phase for phase in required_startup if counts.get((True,phase),0)!=1)
    if records:
        for phase in missing:error('required_first_frame_phase_missing',phase=phase)
        for phase in missing_startup:error('required_startup_phase_missing',phase=phase)
    first_frame_complete=stream_valid and not missing and not missing_startup
    return dict(schema='polar.saved-native-phase-report.v1',available=bool(records),required=expected_profile is not None,
        expected_profile=expected_profile,profile=profile,original_identity=identity,
        clock_domain='linux_steady_diagnostic_only',eof_complete=eof_complete,
        valid=bool(records) and not errors,stream_valid=stream_valid,first_frame_complete=first_frame_complete,
        required_first_frame_phases=sorted(required),missing_first_frame_phases=missing,
        required_startup_phases=sorted(required_startup),missing_startup_phases=missing_startup,
        completed_phases=completed,incomplete_phases=[r['phase'] for r in stack],
        events=records,errors=errors,
        qualification='Linux-local scoped phase wall durations; startup is zero-frame, not per-inference lifetime CPU')


def _saved_json(text):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('Duplicate saved JSON field')
            result[key]=value
        return result
    def nonfinite(value):raise ValueError('Nonfinite saved JSON value')
    return json.loads(text,object_pairs_hook=pairs,parse_constant=nonfinite)


def _saved_checked_path(path,root):
    path=Path(os.path.abspath(path))
    if not path.is_relative_to(root):raise ValueError('Saved input outside run root')
    for part in (path,*path.parents):
        info=part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
            raise ValueError('Saved input reparse/symlink path')
    return path


def _saved_read(path,root,max_bytes):
    path=_saved_checked_path(path,root);before=path.lstat()
    if not stat.S_ISREG(before.st_mode):raise ValueError('Saved input must be a regular file')
    if before.st_size>max_bytes:raise ValueError('Saved input exceeds bounded size')
    descriptor=os.open(path,os.O_RDONLY|getattr(os,'O_BINARY',0)|getattr(os,'O_NOFOLLOW',0))
    with os.fdopen(descriptor,'rb') as stream:
        opened=os.fstat(stream.fileno());content=stream.read(max_bytes+1)
    after=_saved_checked_path(path,root).lstat()
    identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)
    if len(content)>max_bytes or identity(before)!=identity(opened) or identity(opened)!=identity(after):
        raise ValueError('Saved input changed while reading')
    return content


def select_saved_native_input(run_root):
    """Select exactly one archived real frame; portable, with no native imports."""
    root=Path(os.path.abspath(run_root));_saved_checked_path(root,root)
    requests=[]
    for line in _saved_read(root/'ledger.jsonl',root,16*1024*1024).decode('utf-8').splitlines():
        row=_saved_json(line)
        if type(row) is not dict:raise ValueError('Saved ledger row must be an object')
        if row.get('event')=='native_request':requests.append(row)
    if len(requests)!=1:raise ValueError('Exactly one preserved native request required')
    request=requests[0];frame_id=request.get('frame_id');expected_sha=request.get('raw_bgr_sha256')
    if type(frame_id) is not int or frame_id<0:raise ValueError('Invalid saved request frame_id')
    if type(expected_sha) is not str or not re.fullmatch('[0-9a-f]{64}',expected_sha):
        raise ValueError('Invalid saved request pixel SHA')
    candidates=[]
    for directory,dirs,files in os.walk(root,followlinks=False):
        for name in dirs:_saved_checked_path(Path(directory)/name,root)
        for name in files:
            path=Path(directory)/name
            if name=='sensor_input.bgr':candidates.append(('legacy_sensor_input_bgr',path,None,None))
            elif name==f'sensor_{frame_id}.json':
                if path.parent.name!='actual_frames':raise ValueError('Saved manifest outside actual_frames')
                manifest_bytes=_saved_read(path,root,4096)
                manifest=_saved_json(manifest_bytes.decode('utf-8'))
                fields={'schema','frame_id','width','height','stride_bytes','bytes','encoding','file','sha256'}
                if type(manifest) is not dict or set(manifest)!=fields:raise ValueError('Invalid saved manifest fields')
                for key,value in [('frame_id',frame_id),('width',1440),('height',1080),('stride_bytes',4320),('bytes',4665600)]:
                    if type(manifest[key]) is not int or manifest[key]!=value:raise ValueError('Invalid saved manifest '+key)
                expected_file=f'sensor_{frame_id}.bgr'
                if (manifest['schema']!='polar.sim.actual_native_frame_evidence.v1'
                    or manifest['encoding']!='bgr8' or manifest['file']!=expected_file
                    or manifest['sha256']!=expected_sha):raise ValueError('Invalid saved manifest identity')
                candidates.append(('v2_actual_frame_manifest',path.parent/expected_file,path,hashlib.sha256(manifest_bytes).hexdigest()))
    if len(candidates)!=1:raise ValueError('Saved input missing or ambiguous candidates')
    kind,source,manifest,manifest_sha=candidates[0];content=_saved_read(source,root,4665600)
    if len(content)!=4665600 or hashlib.sha256(content).hexdigest()!=expected_sha:
        raise ValueError('Saved actual pixel identity mismatch')
    return dict(request=request,content=content,source=source,manifest=manifest,
        input_format=kind,sha256=expected_sha,
        provenance=dict(format=kind,frame_id=frame_id,source=source.relative_to(root).as_posix(),
            manifest=None if manifest is None else manifest.relative_to(root).as_posix(),manifest_sha256=manifest_sha,
            image_sha256=expected_sha))


def distribution(values):
    values=sorted(values)
    def p(q):
        if not values:return None
        x=q*(len(values)-1);i=int(x);j=min(i+1,len(values)-1)
        return (values[i]+(values[j]-values[i])*(x-i))*1000
    return dict(samples=len(values),p50_ms=p(.5),p95_ms=p(.95),p99_ms=p(.99),max_ms=max(values)*1000 if values else None)


@contextmanager
def saved_storage_workspace(out,content,storage,*,tmpfs_parent=Path('/dev/shm')):
    """Preserve pixels in out; optionally use one owned, always removed workspace."""
    if storage not in ('drvfs','tmpfs'):raise ValueError('Unknown saved-input storage')
    retained=out/'saved_input.bgr';retained.write_bytes(content)
    temporary=None
    state=dict(storage=storage,retained_image=str(retained),image_sha256=hashlib.sha256(content).hexdigest(),
        cleanup=None)
    try:
        if storage=='tmpfs':
            temporary=tempfile.TemporaryDirectory(prefix='polar-saved-native-',dir=tmpfs_parent)
            workspace=Path(temporary.name);workspace.chmod(0o700)
            image=workspace/'saved_input.bgr';image.write_bytes(content)
        else:workspace=out;image=retained
        if image.read_bytes()!=content or retained.read_bytes()!=content:raise ValueError('Storage changed saved pixels')
        state.update(workspace=workspace,image=image,workspace_mode=oct(workspace.stat().st_mode&0o777))
        yield state
    finally:
        path=None if temporary is None else Path(temporary.name)
        if temporary is not None:temporary.cleanup()
        state['cleanup']=dict(tmpfs_created=path is not None,tmpfs_path=None if path is None else str(path),
            tmpfs_removed=path is None or not path.exists())
        (out/'STORAGE_CLEANUP.json').write_text(json.dumps(state['cleanup'],indent=2)+'\n',encoding='utf-8')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-root',required=True,type=Path)
    p.add_argument('--native-spec',required=True,type=Path)
    p.add_argument('--out',required=True,type=Path)
    p.add_argument('--storage',choices=('drvfs','tmpfs'),default='drvfs')
    p.add_argument('--phase-profile',choices=('none',*PHASE_PROFILES),default='none',
        help='Require strict STDERR phase evidence only for an explicit diagnostic overlay; original ELF default remains compatible')
    a=p.parse_args()
    if sys.platform!='linux':raise RuntimeError('Run only in Linux, no Windows/host clock inference')
    phase_profile=None if a.phase_profile=='none' else a.phase_profile
    if phase_profile is None:
        from rm_match.deployment.profile import validate_t2_spec
        spec,spec_sha=validate_t2_spec(a.native_spec)
    else:
        from tools.validate_native_performance_profile import validate_performance_spec
        spec,spec_sha=validate_performance_spec(a.native_spec,expected_profile=phase_profile)
    root=Path(os.path.abspath(a.run_root));out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    def write(name,value):
        (out/name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    saved=select_saved_native_input(root)
    request=saved['request'];content=saved['content'];image_sha=saved['sha256']
    write('SAVED_INPUT_PROVENANCE.json',saved['provenance'])
    write('NATIVE_SPEC.json',spec)
    diagnostic_sources=['tools/diagnose_native_saved_compute.py','rm_match/operator/source_aim.py',
        'rm_match/integrations/rmcs_process.py']
    if phase_profile is not None:diagnostic_sources.append('tools/validate_native_performance_profile.py')
    write('DIAGNOSTIC_SOURCE.json',{rel:hashlib.sha256((ROOT/rel).read_bytes()).hexdigest() for rel in diagnostic_sources})
    with saved_storage_workspace(out,content,a.storage) as workspace:
        try:report=run_saved_compute(spec,spec_sha,out,saved,workspace,
            phase_profile=phase_profile)
        except BaseException:
            (out/'exception.txt').write_text(traceback.format_exc(),encoding='utf-8')
            raise
    report['storage_cleanup']=workspace['cleanup']
    write('RESULT.json',report)
    write('EVIDENCE_MANIFEST.json',{str(x.relative_to(out)):hashlib.sha256(x.read_bytes()).hexdigest()
        for x in out.rglob('*') if x.is_file() and x.name!='EVIDENCE_MANIFEST.json'})
    print(json.dumps({k:report[k] for k in ('fresh_valid_first_inference','duplicate_noninference_responses','filesystem_stages','errors')},indent=2))
    return 0 if not report['errors'] and report['storage_cleanup']['tmpfs_removed'] and all(c['cleanup']['proc_absent'] for c in report['cases']) else 2


def run_saved_compute(spec,spec_sha,out,saved,workspace,*,phase_profile=None):
    import resource
    from rm_match.camera_profile import SourceCameraProfile
    from rm_match.integrations.rmcs_contract import own_state
    from rm_match.integrations.wsl_operator_worker import _stdin_wait,validate_sensor_frame
    from rm_match.operator.source_aim import OperatorFovProcess
    def write(name,value):
        (out/name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    request=saved['request'];image_sha=saved['sha256'];image=workspace['image']
    saved_request_identity(request)
    captured=request['own_at_capture'];profile=SourceCameraProfile()
    own=own_state(SimpleNamespace(own_qpos=captured['own_qpos_at_capture'],own_qvel=captured['own_qvel_at_capture'],
        odom_xyyaw=captured['own_odom_at_capture'],odom_vxyw=captured['own_odom_velocity_at_capture'],
        own_hp=0,ammo=0,own_heat=0))
    # These optional fields were not archived in the trace; they are not used by
    # the original native Runner. Omit them rather than fabricate measurements.
    for name in ('hp','ammo','heat'):own.pop(name)
    frame=dict(schema='rmcs-mujoco-actor-frame-v1',episode=request['episode'],frame_id=request['frame_id'],
        exposure_timestamp_ns=round(request['capture_sim_time']*1e9),capture_time_s=request['capture_sim_time'],
        own_referee_id=7,own_team='red',image=dict(encoding='bgr8',width=1440,height=1080,stride_bytes=4320,
            bytes=4665600,sha256=image_sha,path=str(image)),camera=dict(fx=profile.fx,fy=profile.fy,cx=profile.cx,
            cy=profile.cy,distortion=list(profile.distortion)),own=own)
    packet=dict(episode=request['episode'],control_time_ns=round(request['observation_sim_time']*1e9),frame=frame)
    validate_sensor_frame(frame);write('ORIGINAL_RECONSTRUCTED_PACKET.json',packet)
    fs=[]
    for i in range(15):
        start=time.perf_counter();raw=image.read_bytes();read=time.perf_counter()
        sha=hashlib.sha256(raw).hexdigest();hashed=time.perf_counter()
        json.dumps(packet,allow_nan=False);encoded=time.perf_counter()
        assert sha==image_sha
        fs.append(dict(sample=i,read_s=read-start,sha256_s=hashed-read,json_encode_s=encoded-hashed))
    env=os.environ.copy();env.update(spec.get('environment',{}))
    env.update(AUTOAIM_CONFIG=spec['autoaim_config'],RMCS_HEADLESS_SHARE=spec['model_share'],ORT_DISABLE_TELEMETRY='1')
    cases=[];errors=[]
    # Same packet fifteen times in one process, plus three independent fresh
    # first-inference cases. Duplicate exposure is rejected by original gates.
    for name,count in [('same_packet_15',15),('fresh_first_1',1),('fresh_first_2',1),('fresh_first_3',1)]:
        case_out=out/name;case_cwd=workspace['workspace']/name
        process=OperatorFovProcess(spec['binary'],spec['executor_yaml'],case_cwd,env,
            fov=dict(fov_degrees=180.,circle_radius_x_norm=1.,circle_radius_y_norm=1.),timeout=2.)
        rows=[];child=None;readiness=None;start=time.perf_counter();error=None;cleanup=None
        usage_before=resource.getrusage(resource.RUSAGE_CHILDREN);cpu=None;peak_rss_kib=None
        try:
            case_cwd.mkdir(parents=True,exist_ok=False)
            (case_cwd/'tracking_mode').write_bytes(spec['runtime_mode_contents'].encode('utf-8'))
            process.reset(dict(episode=request['episode']));child=process.process
            deadline=time.perf_counter()+15
            while time.perf_counter()<deadline:
                readiness=_stdin_wait(child.pid)
                if readiness:break
                if child.poll() is not None:raise RuntimeError('Native exited before ready')
                time.sleep(.005)
            if readiness is None:raise TimeoutError('Original ELF read(0) readiness exceeded 15s')
            startup=time.perf_counter()-start
            for i in range(count):
                begin=time.perf_counter();response=process.control(packet);end=time.perf_counter()
                row=dict(sample=i,linux_local_request_perf=begin,linux_local_response_perf=end,
                    response_s=end-begin,response=response)
                rows.append(row)
                # Persist each real response before computing aggregate reports.
                write(name+'_responses.json',rows)
        except BaseException as exc:
            error=type(exc).__name__+':'+str(exc);errors.append(dict(case=name,error=error))
            (out/(name+'_exception.txt')).write_text(traceback.format_exc(),encoding='utf-8')
            startup=time.perf_counter()-start
        finally:
            try:
                if child is not None:
                    for line in Path('/proc/'+str(child.pid)+'/status').read_text().splitlines():
                        if line.startswith('VmHWM:'):peak_rss_kib=int(line.split()[1])
            except OSError:
                # An exited process can vanish here; resource audit must never
                # prevent the lifecycle owner from closing/reaping its child.
                pass
            close_start=time.perf_counter()
            try:process.close()
            except BaseException as exc:
                errors.append(dict(case=name,error='close:'+type(exc).__name__+':'+str(exc)))
            cleanup=dict(close_s=time.perf_counter()-close_start,pid=None if child is None else child.pid,
                returncode=None if child is None else child.poll(),
                proc_absent=child is not None and not Path('/proc/'+str(child.pid)).exists(),
                stdin_closed=child is not None and child.stdin.closed,stdout_closed=child is not None and child.stdout.closed)
            usage_after=resource.getrusage(resource.RUSAGE_CHILDREN)
            cpu=dict(user_s=usage_after.ru_utime-usage_before.ru_utime,system_s=usage_after.ru_stime-usage_before.ru_stime,
                peak_rss_kib_preclose=peak_rss_kib,qualification='Owned-child lifetime CPU including model startup and reap; preclose Linux VmHWM, not per-inference timing')
            if case_cwd!=case_out and case_cwd.exists():
                try:shutil.copytree(case_cwd,case_out)
                except OSError as exc:errors.append(dict(case=name,error='retain_case:'+type(exc).__name__+':'+str(exc)))
        try:
            stderr_bytes=_saved_read(case_out/'rmcs_stderr.log',out,16*1024*1024)
            phases=parse_native_phase_stderr(stderr_bytes.decode('utf-8'),request,expected_profile=phase_profile,
                eof_complete=cleanup['proc_absent'])
            phases['stderr_sha256']=hashlib.sha256(stderr_bytes).hexdigest()
            phases['correlated_response_sample']=0 if rows else None
            if phases['available'] or phase_profile is not None:
                if not phases['valid']:errors.append(dict(case=name,error='native_phase_diagnostic_failed',phase_errors=phases['errors']))
        except (ValueError,OSError,UnicodeError) as exc:
            phases=dict(available=False,valid=False,required=phase_profile is not None,
                errors=[dict(code='phase_stderr_read_failed',error_type=type(exc).__name__)])
            # An actual stderr evidence failure must remain visible even when
            # original execution already failed; never synthesize absent stages.
            errors.append(dict(case=name,error='native_phase_stderr_unavailable',phase_errors=phases['errors']))
        write(name+'_phase_report.json',phases)
        cases.append(dict(case=name,startup_s=startup,zero_tick_readiness=readiness,error=error,cleanup=cleanup,
            child_cwd=str(case_cwd),cpu=cpu,tracking_mode_sha256=hashlib.sha256(spec['runtime_mode_contents'].encode('utf-8')).hexdigest(),
            responses=rows,phase_diagnostic=phases,
            actual_detector_samples=sum(x['response']['detector_executed'] is True for x in rows)))
        write('CASES_PARTIAL.json',cases)
    first=[x['responses'][0]['response_s'] for x in cases if x['responses'] and x['responses'][0]['response']['detector_executed']]
    duplicates=[x['response_s'] for x in cases[0]['responses'][1:] if not x['response']['detector_executed']]
    phase_samples={};startup_phase_samples={}
    for case in cases:
        phases=case['phase_diagnostic']
        if not phases.get('valid'):continue
        for stage in phases['completed_phases']:
            target=startup_phase_samples if stage['startup'] else phase_samples
            target.setdefault(stage['phase'],[]).append(stage['elapsed_ns']/1e9)
    report=dict(schema='polar.linux.saved-native-compute.v1',scope='Offline Linux-local compute/FS diagnostic only; cannot supplement failed live control',
        clock_domain='Linux time.perf_counter only, never subtract Windows/QPC time',
        spec_sha256=spec_sha,binary_sha256=spec['sha256']['binary'],model_sha256=spec['model_sha256'],
        source_identity=spec['source_identity'],actual_image_sha256=image_sha,saved_input=saved['provenance'],
        storage=dict(mode=workspace['storage'],native_image=str(image),retained_image=workspace['retained_image'],
            workspace=str(workspace['workspace']),workspace_mode=workspace['workspace_mode'],
            identical_retained_and_native_pixels=True),
        preserved_capture_ns=packet['frame']['exposure_timestamp_ns'],preserved_control_ns=packet['control_time_ns'],
        timestamp_or_pixel_changes=False,own_fields_omitted_not_archived=['hp','ammo','heat'],
        ready_before_capture_or_inference=True,live_80ms_budget_changed=False,
        diagnostic_response_timeout_s=2.,cases=cases,errors=errors,
        phase_profile=phase_profile,
        first_frame_phase_timings={k:distribution(v) for k,v in phase_samples.items()},
        startup_phase_timings={k:distribution(v) for k,v in startup_phase_samples.items()},
        phase_timing_qualification='Four independent processes, first original exposure only; scoped wall timings are inclusive/nested, not additive or child-lifetime CPU; duplicate requests contribute no phase/inference samples',
        fresh_valid_first_inference=distribution(first),duplicate_noninference_responses=distribution(duplicates),
        filesystem_stages={k:distribution([x[k] for x in fs]) for k in ('read_s','sha256_s','json_encode_s')},
        filesystem_samples=fs)
    return report


if __name__=='__main__':
    raise SystemExit(main())
