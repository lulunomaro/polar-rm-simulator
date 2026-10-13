"""Linux owner of one native child for the opt-in wsl_stdio_v1 bridge.

All wall timestamps here are Linux-local diagnostics. Host authority never
subtracts these from Windows QPC. No synthetic camera or native tick at startup.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import select
import signal
import subprocess
import time
from .owned_linux_group import LinuxOwnedProcessGroup

MAX_LINE = 65536
MAX_IMAGE = 4665600


def validate_sensor_frame(frame):
    """Only the existing native own-sensor envelope; no world/target objects."""
    allowed={'schema','episode','frame_id','exposure_timestamp_ns','capture_time_s','own_referee_id','own_team','image','camera','own'}
    if type(frame) is not dict or set(frame)-allowed or frame.get('schema')!='rmcs-mujoco-actor-frame-v1':
        raise ValueError('unexpected native sensor frame fields')
    image=frame.get('image')
    if type(image) is not dict or set(image)!={'encoding','width','height','stride_bytes','bytes','sha256','path'}:
        raise ValueError('unexpected native image fields')
    def scalar(value):
        if type(value) not in (int,float) or not math.isfinite(value): raise ValueError('invalid sensor scalar')
    camera=frame.get('camera',{})
    if type(camera) is not dict or set(camera)-{'fx','fy','cx','cy','distortion'}: raise ValueError('unexpected camera fields')
    for key,value in camera.items():
        if key=='distortion':
            if type(value) is not list or len(value)!=5: raise ValueError('invalid sensor distortion')
            for item in value: scalar(item)
        else: scalar(value)
    lengths=dict(joint_positions=5,joint_velocities=5,base_odom_xyyaw=3,base_odom_vxyw=3,
        pitchlink_to_world_quaternion_wxyz=4,pitchlink_angular_velocity_world_rad_s=3,
        pitchlink_angular_velocity_local_rad_s=3,yaw_origin_world_m=3,camera_position_pitchlink_m=3,muzzle_position_pitchlink_m=3)
    own=frame.get('own',{})
    if type(own) is not dict or set(own)-set(lengths)-{'camera_optical_from_pitchlink_rotation','hp','ammo','heat'}:
        raise ValueError('unexpected own sensor fields')
    for key,value in own.items():
        if key in lengths:
            if type(value) is not list or len(value)!=lengths[key]: raise ValueError('invalid own vector')
            for item in value: scalar(item)
        elif key=='camera_optical_from_pitchlink_rotation':
            if type(value) is not list or len(value)!=3 or any(type(row) is not list or len(row)!=3 for row in value): raise ValueError('invalid optical transform')
            for row in value:
                for item in row: scalar(item)
        else: scalar(value)


def _record(out, name, data):
    temporary=out/(name+'.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n', encoding='utf8')
    os.replace(temporary,out/name)


def _emit(data):
    raw = json.dumps(data, allow_nan=False, separators=(',', ':')).encode() + b'\n'
    if len(raw) > MAX_LINE:
        raise ValueError('oversize supervisor output')
    os.write(1, raw)


def _stdin_wait(pid):
    """Linux x86_64 read syscall on fd0, after Runner initialization."""
    try:
        syscall = Path(f'/proc/{pid}/syscall').read_text().strip()
        wchan = Path(f'/proc/{pid}/wchan').read_text().strip()
        fields = syscall.split()
        if len(fields) >= 2 and fields[0] == '0' and int(fields[1], 0) == 0 and wchan == 'pipe_read':
            return dict(abi='Linux x86_64 read(0)', syscall=syscall, wchan=wchan)
    except (OSError, ValueError):
        pass
    return None


def supervise(command, out, fov, *, env=None, spec_sha=None, startup_timeout=15., control_timeout=.08):
    """Internal process owner; tests use harmless children, production main verifies spec."""
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    stopped = False
    def stop_signal(*_):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)
    child = None; errorlog = None; reason = 'startup_failure'; killed = False
    startup = time.monotonic(); reads = {}; pending = None; writebuf = b''
    try:
        owner=LinuxOwnedProcessGroup()
        errorlog = (out / 'native_stderr.log').open('wb')
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=errorlog, cwd=out.parent, env=env, bufsize=0, start_new_session=True)
        owned=owner.attach(child)
        _record(out, 'OWNED_CHILD.json', dict(owned,spec_sha256=spec_sha,transport='wsl_stdio_v1'))
        os.set_blocking(0, False)
        os.set_blocking(child.stdin.fileno(), False); os.set_blocking(child.stdout.fileno(), False)
        ready = False; readiness = None; active_deadline = startup + startup_timeout
        while True:
            now = time.monotonic()
            if stopped or (out / 'STOP').exists():
                reason = 'host_cancel'; break
            if child.poll() is not None:
                reason = 'native_exit'; raise RuntimeError('owned native process exited')
            if not ready:
                readiness = _stdin_wait(child.pid)
                if readiness:
                    ready = True; active_deadline = None
                    data = dict(event='ready', transport='wsl_stdio_v1', native_pid=child.pid,run_id=owned['run_id'],supervisor_pid=owned['supervisor_pid'],
                        spec_sha256=spec_sha, readiness=readiness, startup_elapsed_linux_s=now-startup,
                        native_ticks=0, inference_calls=0, camera_captures=0, physics_steps=0)
                    _record(out, 'STARTUP.json', data); _emit(data)
            if active_deadline is not None and now >= active_deadline:
                reason = 'startup_timeout' if not ready else 'control_timeout'
                raise TimeoutError(reason)
            watch = [0, child.stdout.fileno()]
            readable, writable, _ = select.select(watch, [child.stdin.fileno()] if writebuf else [], [], .01)
            if child.stdin.fileno() in writable:
                sent = os.write(child.stdin.fileno(), writebuf); writebuf = writebuf[sent:]
            for fd in readable:
                chunk = os.read(fd, 8192)
                if not chunk:
                    if fd == 0:
                        reason = 'host_eof'; return 0
                    reason = 'native_eof'; raise RuntimeError('owned native stdout closed')
                reads[fd] = reads.get(fd, b'') + chunk
                if len(reads[fd]) > MAX_LINE:
                    raise ValueError('oversize stdio message')
                while b'\n' in reads[fd]:
                    line, reads[fd] = reads[fd].split(b'\n', 1)
                    message = json.loads(line)
                    if fd != 0:
                        if pending is None or writebuf:
                            raise ValueError('unsolicited native result')
                        _emit(dict(event='result', id=pending, response=message))
                        pending = None; active_deadline = None
                        continue
                    if not ready or pending is not None or message.get('event') != 'control':
                        raise ValueError('invalid concurrent bridge request')
                    packet = message['packet']
                    if set(packet) != {'control_time_ns', 'time_s', 'frame', 'operator_fov'} or packet['operator_fov'] != fov:
                        raise ValueError('invalid native packet')
                    if type(packet['control_time_ns']) is not int or packet['control_time_ns'] < 0 or packet['time_s'] != packet['control_time_ns']/1e9:
                        raise ValueError('native clock mismatch')
                    validate_sensor_frame(packet['frame'])
                    image = packet['frame']['image']; path = Path(image['path'])
                    if not path.is_absolute() or not path.resolve().is_relative_to(out.parent.resolve()) or path.is_symlink():
                        raise ValueError('image outside owned binding directory')
                    if any(parent.is_symlink() for parent in path.parents): raise ValueError('image parent symlink rejected')
                    with path.open('rb') as stream: raw=stream.read(MAX_IMAGE+1)
                    if len(raw) != MAX_IMAGE or image.get('bytes') != MAX_IMAGE or image.get('encoding') != 'bgr8' or (image.get('width'),image.get('height'),image.get('stride_bytes')) != (1440,1080,4320):
                        raise ValueError('invalid real BGR image size')
                    if hashlib.sha256(raw).hexdigest() != image['sha256']:
                        raise ValueError('real BGR image hash mismatch')
                    pending = message['id']
                    budget = message.get('timeout_s', control_timeout)
                    if type(budget) not in (int,float) or not 0 < budget <= control_timeout:
                        raise ValueError('invalid local control budget')
                    active_deadline = now + budget
                    writebuf = json.dumps(packet, allow_nan=False, separators=(',', ':')).encode() + b'\n'
                    if len(writebuf) > MAX_LINE:
                        raise ValueError('oversize native request')
    except Exception as exc:
        _record(out, 'SUPERVISOR_ERROR.json', dict(reason=reason, error_type=type(exc).__name__, error=str(exc)))
        try: _emit(dict(event='error', reason=reason, error_type=type(exc).__name__))
        except (BrokenPipeError,OSError): pass
        return 2
    finally:
        if child is not None:
            result=owner.cleanup()
            for stream in (child.stdin, child.stdout): stream.close()
            _record(out, 'CLEANUP.json', dict(result,transport='wsl_stdio_v1',spec_sha256=spec_sha,
                reason=reason,
                cleanup_linux_monotonic=time.monotonic(), clock_domain='linux_local_diagnostic_only'))
        if errorlog is not None: errorlog.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', type=Path, required=True); parser.add_argument('--spec-sha256', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--fov-degrees',type=float,required=True); parser.add_argument('--radius-x',type=float,required=True); parser.add_argument('--radius-y',type=float,required=True)
    parser.add_argument('--startup-timeout', type=float, default=15.); parser.add_argument('--control-timeout', type=float, default=.08)
    args = parser.parse_args()
    spec, sha = validate_linux_spec(args.spec, args.spec_sha256)
    fov = dict(fov_degrees=args.fov_degrees,circle_radius_x_norm=args.radius_x,circle_radius_y_norm=args.radius_y)
    env = os.environ.copy(); env.update(spec.get('environment', {}))
    env.update(AUTOAIM_CONFIG=spec['autoaim_config'],RMCS_HEADLESS_SHARE=spec['model_share'],ORT_DISABLE_TELEMETRY='1')
    return supervise([spec['binary'], spec['executor_yaml']], args.out, fov, env=env, spec_sha=sha,
        startup_timeout=args.startup_timeout, control_timeout=args.control_timeout)


def validate_linux_spec(path, expected_sha):
    """Second boundary, standard library only; Windows has mapped/full-source checks."""
    from rm_match.deployment import profile
    spec, sha=profile.read_json_snapshot(path)
    if sha!=expected_sha or spec.get('operator_identity')!='rmcs-sim-operator-fov-v1':
        raise ValueError('Linux spec identity mismatch')
    revision, extra=profile.validate_source_identity(spec.get('source_identity',{}))
    if revision!='contour-v3': raise ValueError('Linux bridge requires contour-v3')
    environment=spec.get('environment',{})
    if type(environment) is not dict or any(k not in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS') or v!='1' for k,v in environment.items()):
        raise ValueError('Linux native environment mismatch')
    expected=spec['sha256']; frozen=spec['frozen_build']
    if expected['binary']!=frozen['binary_sha256']: raise ValueError('Linux binary declaration mismatch')
    for key in ('binary','executor_yaml','autoaim_config'):
        selected=Path(spec[key])
        if not selected.is_absolute() or selected.is_symlink() or profile.digest(selected)!=expected[key]:
            raise ValueError('Linux native asset mismatch: '+key)
    model=Path(spec['model_share'])/'shenzhen-0526.onnx'
    if spec['model_sha256']!=profile.MODEL_SHA256 or profile.digest(model)!=profile.MODEL_SHA256:
        raise ValueError('Linux model mismatch')
    mode=hashlib.sha256(b'multi_ekf\n').hexdigest()
    if spec.get('runtime_mode_contents')!='multi_ekf\n' or spec.get('runtime_mode_sha256')!=mode or expected.get('runtime_mode')!=mode:
        raise ValueError('Linux runtime mode mismatch')
    root=Path(path).parent; build, build_sha=profile.read_json_snapshot(root/'BUILD_MANIFEST.json',4*1024*1024)
    if build_sha!=frozen['manifest_sha256'] or build.get('status')!='native_build_succeeded' or build.get('full_clean_compile') is not True or build.get('binary_sha256')!=expected['binary']:
        raise ValueError('Linux frozen build mismatch')
    inputs=build['input_identity']
    if inputs.get('algorithm_identity')!=spec['source_identity'] or inputs.get('corner_refinement')!=revision or inputs.get('additional_source_files')!=extra:
        raise ValueError('Linux source lineage mismatch')
    for rel,digest in inputs['source_files'].items():
        if profile.digest(profile.RUNTIME_ROOT/rel)!=digest: raise ValueError('Linux recovered source mismatch')
    for rel,digest in inputs['generated_sha256'].items():
        if profile.digest(root/rel)!=digest: raise ValueError('Linux generated source mismatch')
    for rel,digest in extra.items():
        if profile.digest(profile.RUNTIME_ROOT/rel)!=digest: raise ValueError('Linux frontend source mismatch')
    return spec,sha


if __name__ == '__main__':
    raise SystemExit(main())
