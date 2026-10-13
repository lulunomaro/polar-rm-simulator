"""Standard-library deployment planner/doctor. Installation is always explicit."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import platform
import queue
import shutil
import subprocess
import sys
import threading
import time
from .profile import (PROFILE, CLIENT_REPOSITORY, CLIENT_COMMIT, LIMITATIONS,
                      digest, read_json)

ROOT = Path(__file__).resolve().parents[2]


def client_patch_identity():
    manifest=read_json(ROOT/'client_patches/CLIENT_PATCH_MANIFEST.json')
    if manifest.get('base_commit')!=CLIENT_COMMIT:
        raise ValueError('Client patch base differs from the fixed own-client commit')
    path=ROOT/'client_patches'/manifest['patch_file']
    if path.parent!=ROOT/'client_patches' or digest(path)!=manifest['patch_sha256']:
        raise ValueError('Client patch bytes differ from their declared identity')
    return dict(base_commit=CLIENT_COMMIT,patch_sha256=manifest['patch_sha256'],
                manifest_sha256=digest(ROOT/'client_patches/CLIENT_PATCH_MANIFEST.json'),
                qualification='Fixed own client plus explicit reviewed operator-state patch')


def executable(path):
    # Preserve venv interpreter invocation identity, including symlinked parents.
    path = Path(path).expanduser().absolute()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError('Python executable missing: ' + str(path))
    return str(path)


def clean_environment():
    env = dict(os.environ)
    for name in ('PYTHONPATH', 'PYTHONHOME', 'POLAR_APP_ROOT','POLAR_SIM_ADMISSION_CREDENTIAL'):
        env.pop(name, None)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    return env


def plan(a):
    if not 1024 <= a.port <= 65535 or not 0 < a.max_wall_seconds <= 3600:
        raise ValueError('Invalid port or wall time')
    if not 0 < a.camera_fps <= 15 or not 0 < a.real_time_factor <= 1:
        raise ValueError('Invalid camera FPS or real-time factor')
    root = a.client_root.expanduser().absolute()
    out = a.out.expanduser().absolute()
    spec = a.native_spec.expanduser().absolute()
    # Plan is side-effect free, and can be printed before dependencies exist.
    sim_python = str(a.sim_python.expanduser().absolute())
    client_python = str(a.client_python.expanduser().absolute())
    supplied_admission = getattr(a,'admission_manifest',None)
    admission = supplied_admission.expanduser().absolute() if supplied_admission else out / 'admission.json'
    server = [sim_python, '-u', '-m', 'rm_match.deployment.server',
              '--native-spec', str(spec), '--native-out', str(out / 'native'),
              '--port', str(a.port), '--camera-total-fps', str(a.camera_fps),
              '--max-wall-seconds', str(a.max_wall_seconds),
              '--real-time-factor', str(a.real_time_factor),
              '--admission-manifest',str(admission)]
    if a.adapters_json:
        server += ['--adapters-json', str(a.adapters_json.expanduser().absolute())]
    return dict(schema='polar.sim.deployment.plan.v1', profile=PROFILE,
        server_argv=server,
        client_argv=[client_python, str(root / 'main.py'), '--sim-platform-v2',
                     '--sim-role', 'operator', '--sim-endpoint', f'http://127.0.0.1:{a.port}'],
        sim_root=str(ROOT), client_root=str(root), out=str(out), native_spec=str(spec),
        adapters_json=str(a.adapters_json.expanduser().absolute()) if a.adapters_json else None,
        admission_manifest=str(admission), provision_local_admission=supplied_admission is None,
        admission_scope=['red_sentry'] if supplied_admission is None else 'local_manifest',
        client_repository=CLIENT_REPOSITORY, client_commit=CLIENT_COMMIT,
        client_patch=client_patch_identity(),
        url=f'http://127.0.0.1:{a.port}', max_wall_seconds=a.max_wall_seconds,
        gl=a.gl, automatic_binding=False, fire_authority='manual_only',
        limitations=LIMITATIONS,
        qualification='Plan only; no dependency, inference, renderer or UI qualification')


def run_checked(argv, *, cwd=None, timeout=20):
    result = subprocess.run(argv, cwd=cwd, env=clean_environment(), stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
        check=False, text=True)
    if result.returncode:
        raise ValueError('Command failed (' + str(result.returncode) + '): ' +
                         (result.stderr or result.stdout)[-2000:].strip())
    return result.stdout.strip()


def python_probe(python, modules):
    code = '''import importlib,json,sys
result={'python':sys.version.split()[0], 'invoked_executable':sys.executable, 'prefix':sys.prefix, 'modules':{}}
for name in sys.argv[1:]:
 try:
  m=importlib.import_module(name); result['modules'][name]={'ok':True,'version':str(getattr(m,'__version__','imported'))}
 except Exception as e: result['modules'][name]={'ok':False,'error':type(e).__name__+': '+str(e)}
print(json.dumps(result))'''
    value = json.loads(run_checked([executable(python), '-I', '-c', code, *modules]))
    if not all(row['ok'] for row in value['modules'].values()):
        raise ValueError('Dependency import failed: ' + json.dumps(value['modules']))
    if tuple(int(x) for x in value['python'].split('.')[:2]) < (3, 10):
        raise ValueError('Python 3.10 or newer required')
    return value


def check_client(root):
    root = Path(root)
    actual = run_checked(['git', '-C', str(root), 'rev-parse', 'HEAD'])
    if actual != CLIENT_COMMIT:
        raise ValueError('Client must be at pinned commit ' + CLIENT_COMMIT)
    from tools.apply_client_patch import inspect_client
    identity=client_patch_identity()
    patched=inspect_client(root)
    if patched['apply_required']:
        raise ValueError('Pinned client requires the explicit operator-state patch; run tools/apply_client_patch.py --client-root PATH --run')
    for rel in ('main.py', 'rm_client/ui/sim_platform_window.py',
                'rm_client/sim_platform_adapters.py', 'requirements-core.txt'):
        if not (root / rel).is_file():
            raise ValueError('Pinned client file missing: ' + rel)
    return {'commit': actual, 'tracked_source_clean': False, 'patched_source_verified': True,
            'client_patch': identity}


def doctor(p):
    """Import dependencies / check assets; never start physics, renderer or actor."""
    checks = []
    def check(name, fn):
        try:
            detail = fn()
            checks.append(dict(name=name, ok=True, detail=detail))
            return detail
        except Exception as exc:
            checks.append(dict(name=name, ok=False, error=type(exc).__name__ + ': ' + str(exc)))
            return None
    def host():
        if sys.platform != 'linux' or platform.machine().lower() not in ('x86_64', 'amd64'):
            raise ValueError('Own native RMCS requires Linux x86-64; Windows is unvalidated')
        return {'system': sys.platform, 'machine': platform.machine()}
    check('native_host', host)
    check('sim_python_dependencies', lambda: python_probe(p['server_argv'][0], ['numpy', 'mujoco', 'PIL', 'cv2']))
    check('client_python_dependencies', lambda: python_probe(p['client_argv'][0], ['PySide6.QtCore', 'PySide6.QtWidgets', 'cv2', 'numpy', 'paho.mqtt.client', 'serial']))
    check('pinned_client', lambda: check_client(p['client_root']))
    def admission():
        if p['provision_local_admission']:
            return {'scope':['red_sentry'],'credential':'provisioned_in_memory_at_launch',
                    'audit_authorized':False}
        from ..platform_v2.admission import AdmissionPolicy
        policy=AdmissionPolicy.from_manifest(p['admission_manifest'])
        grant=policy.authenticate('operator',os.environ.get('POLAR_SIM_ADMISSION_CREDENTIAL'))
        policy.verify_manifest_unchanged(p['admission_manifest'])
        return {'scope':list(grant.allowed_robots),'audit_authorized':grant.audit_authorized,
                'manifest_sha256':policy.manifest_sha256}
    check('local_admission',admission)
    def native():
        code = ('import json; from rm_match.deployment.profile import validate_t2_spec; '
                's,h=validate_t2_spec(' + repr(p['native_spec']) + '); '
                'print(json.dumps({"spec_sha256":h,"binary":s["binary"],'
                '"source_identity":s["source_identity"]}))')
        return json.loads(run_checked([executable(p['server_argv'][0]), '-c', code], cwd=p['sim_root']))
    native_result = check('own_t2_native_assets', native)
    if native_result:
        def linkage():
            if sys.platform != 'linux' or shutil.which('ldd') is None:
                raise ValueError('Linux ldd is required to inspect this trusted local build')
            output = run_checked(['ldd', native_result['binary']])
            if 'not found' in output:
                raise ValueError('Native shared libraries missing: ' + output)
            return {'shared_libraries_resolved': True, 'scope': 'loader lookup only; not inference'}
        check('native_shared_libraries', linkage)
    def display():
        if os.environ.get('QT_QPA_PLATFORM', '').lower() in ('offscreen', 'minimal', 'minimalegl'):
            raise ValueError('Visible client rejects offscreen/minimal Qt; use separate CPU tests')
        if not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY'):
            raise ValueError('Visible Qt client needs an actual Linux desktop display')
        return 'Display variable present; actual Qt window and renderer remain untested'
    check('visible_desktop', display)
    def output():
        path = Path(p['out'])
        if path.exists() or path.is_symlink():
            raise ValueError('Output must be a fresh directory')
        return 'Fresh output path'
    check('output_directory', output)
    if p['adapters_json']:
        def extensions():
            code = ('from rm_match.deployment.json_adapter import load_registrations; '
                    'print(len(load_registrations(' + repr(p['adapters_json']) + ')))')
            return {'registered': int(run_checked([executable(p['server_argv'][0]), '-c', code], cwd=p['sim_root'])),
                    'scope': 'manifest validation only; custom code not started'}
        check('custom_adapter_manifest', extensions)
    return dict(schema='polar.sim.deployment.doctor.v1', profile=PROFILE,
        ready_to_attempt=all(c['ok'] for c in checks), checks=checks,
        limitations=LIMITATIONS,
        qualification='Preflight only; no physics, render, native inference or Qt window was started')


class ReadyLines:
    def __init__(self, stream):
        self.queue = queue.Queue(32)
        self.error = None
        def read():
            try:
                while True:
                    row = stream.readline(65537)
                    if not row:
                        break
                    if len(row) > 65536 or not row.endswith(b'\n'):
                        raise ValueError('Oversized or partial server startup output')
                    self.queue.put_nowait(row)
            except Exception as exc:
                self.error = str(exc)
        self.thread = threading.Thread(target=read, daemon=True, name='deployment-ready')
        self.thread.start()


def stop_child(child):
    if child is None:
        return None
    if child.poll() is None:
        try:
            child.terminate()
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                child.kill()
            except ProcessLookupError:
                pass
            child.wait(timeout=2)
    return child.returncode


def verify_ready(value, p, spec_sha):
    if (value.get('event') != 'ready' or value.get('profile') != PROFILE
            or value.get('url') != p['url'] or value.get('spec_sha256') != spec_sha
            or value.get('native_registered') is not True
            or value.get('transport') != 'loopback_only'
            or value.get('automatic_binding') is not False
            or not p.get('admission_policy_sha256')
            or value.get('admission_policy_sha256') != p.get('admission_policy_sha256')
            or value.get('fire_authority') != 'manual_only'
            or 'aim_native_rmcs_v1' not in value.get('adapter_ids', [])):
        raise ValueError('Server ready message does not match own-RMCS deployment')


def launch(p):
    report = doctor(p)
    if not report['ready_to_attempt']:
        print(json.dumps(report, indent=2)); return 2
    from ..platform_v2.admission import AdmissionPolicy
    if not p['provision_local_admission']:
        expected=next(c['detail'] for c in report['checks'] if c['name']=='local_admission')
        policy=AdmissionPolicy.from_manifest(p['admission_manifest'])
        if policy.manifest_sha256!=expected['manifest_sha256']:
            raise ValueError('admission_manifest_changed_after_doctor')
        credential=os.environ['POLAR_SIM_ADMISSION_CREDENTIAL']
        grant=policy.authenticate('operator',credential)
        if list(grant.allowed_robots)!=expected['scope'] or grant.audit_authorized!=expected['audit_authorized']:
            raise ValueError('admission_grant_changed_after_doctor')
    out = Path(p['out']); out.mkdir(parents=True, exist_ok=False)
    if p['provision_local_admission']:
        from .enrollment import provision_operator
        credential=provision_operator(p['admission_manifest'],p['admission_scope'])
        policy=AdmissionPolicy.from_manifest(p['admission_manifest'])
        policy.authenticate('operator',credential)
    policy.verify_manifest_unchanged(p['admission_manifest'])
    p=dict(p,admission_policy_sha256=policy.manifest_sha256)
    (out / 'plan.json').write_text(json.dumps(p, indent=2) + '\n')
    (out / 'doctor.json').write_text(json.dumps(report, indent=2) + '\n')
    spec_sha = next(c['detail']['spec_sha256'] for c in report['checks'] if c['name'] == 'own_t2_native_assets')
    result = {'profile': PROFILE, 'qualification': 'Launch only, not full-match acceptance', 'reason': 'starting'}
    server = client = None
    try:
        with (out / 'server.stderr.log').open('wb') as serr, (out / 'client.log').open('wb') as clog:
            env = clean_environment(); env['POLAR_USER_DATA_ROOT'] = str(out / 'client_user_data')
            senv = dict(env, MUJOCO_GL=p['gl'], OMP_NUM_THREADS='1')
            policy.verify_manifest_unchanged(p['admission_manifest'])
            server = subprocess.Popen(p['server_argv'], cwd=p['sim_root'], env=senv,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=serr, bufsize=0)
            reader = ReadyLines(server.stdout)
            deadline = time.monotonic() + min(20., p['max_wall_seconds'])
            while True:
                if reader.error:
                    raise ValueError(reader.error)
                if server.poll() is not None:
                    raise ValueError('Server exited before ready; see server.stderr.log')
                try:
                    raw = reader.queue.get(timeout=.05)
                    ready = json.loads(raw)
                    verify_ready(ready, p, spec_sha)
                    break
                except queue.Empty:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Server readiness timeout')
            (out / 'server_ready.json').write_text(json.dumps(ready, indent=2) + '\n')
            policy.verify_manifest_unchanged(p['admission_manifest'])
            # Ready may take seconds. Do not grant the credential to a client
            # whose tracked source/patch identity changed during server startup.
            current_client=check_client(p['client_root'])
            if current_client['client_patch']!=p['client_patch']:
                raise ValueError('client_patch_changed_after_plan')
            env['POLAR_SIM_ADMISSION_CREDENTIAL']=credential
            client = subprocess.Popen(p['client_argv'], cwd=p['client_root'], env=env,
                stdin=subprocess.DEVNULL, stdout=clog, stderr=subprocess.STDOUT)
            print(json.dumps({'profile': PROFILE, 'event': 'client_started', 'out': str(out),
                              'note': 'Select red_sentry and V2 Aim native, then explicitly claim/arm; no automatic fire'}), flush=True)
            deadline = time.monotonic() + p['max_wall_seconds']
            while server.poll() is None and client.poll() is None and time.monotonic() < deadline:
                if reader.error:
                    raise ValueError(reader.error)
                time.sleep(.1)
            result['reason'] = ('server_exited' if server.poll() is not None else
                                'client_exited' if client.poll() is not None else 'wall_limit')
            result['server_exit_before_cleanup'] = server.poll()
            result['client_exit_before_cleanup'] = client.poll()
    except KeyboardInterrupt:
        result['reason'] = 'user_interrupt'
    except Exception as exc:
        result.update(reason='launch_error', error=type(exc).__name__ + ': ' + str(exc))
    finally:
        result['client_exit'] = stop_child(client)
        result['server_exit'] = stop_child(server)
        if server and server.stdout:
            server.stdout.close()
        (out / 'launch_result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 2 if result['reason'] == 'launch_error' or any(
        result.get(k) not in (None, 0) for k in ('server_exit_before_cleanup', 'client_exit_before_cleanup')) else 0


def setup_client(root, run=False):
    root = Path(root).expanduser().absolute()
    if root.exists() or root.is_symlink():
        raise ValueError('Client destination exists; use a new directory or pass existing --client-root')
    commands = [['git', 'init', str(root)],
                ['git', '-C', str(root), 'remote', 'add', 'origin', CLIENT_REPOSITORY],
                ['git', '-C', str(root), 'fetch', '--depth=1', 'origin', CLIENT_COMMIT],
                ['git', '-C', str(root), 'checkout', '--detach', 'FETCH_HEAD'],
                [sys.executable,str(ROOT/'tools/apply_client_patch.py'),'--client-root',str(root),'--run']]
    if run:
        for cmd in commands:
            run_checked(cmd, timeout=180)
        check_client(root)
    return {'repository': CLIENT_REPOSITORY, 'commit': CLIENT_COMMIT,
            'client_patch': client_patch_identity(),
            'commands': commands, 'executed': run, 'submodules': 'not initialized',
            'scope': 'External client only; no dependency installation or application startup'}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    p.add_argument('command', nargs='?', choices=('plan', 'doctor', 'launch', 'setup-client'), default='plan')
    p.add_argument('--client-root', type=Path, default=ROOT / 'external/polar-rm-client')
    p.add_argument('--sim-python', type=Path, default=Path(sys.executable))
    p.add_argument('--client-python', type=Path, default=ROOT / '.venv-client/bin/python')
    p.add_argument('--native-spec', type=Path, default=ROOT / 'operator_native/runtime/local_build/operator_source.local.json')
    p.add_argument('--out', type=Path, default=ROOT / 'artifacts/deployment')
    p.add_argument('--adapters-json', type=Path)
    p.add_argument('--admission-manifest',type=Path,
        help='Existing local grants; supply the operator credential via POLAR_SIM_ADMISSION_CREDENTIAL')
    p.add_argument('--port', type=int, default=8766)
    p.add_argument('--max-wall-seconds', type=float, default=300.)
    p.add_argument('--camera-fps', type=float, default=15.)
    p.add_argument('--real-time-factor', type=float, default=1.)
    p.add_argument('--gl', choices=('egl', 'glfw', 'osmesa'), default='egl')
    p.add_argument('--run', action='store_true', help='Explicitly execute setup-client or launch; otherwise print a plan')
    a = p.parse_args(argv)
    try:
        if a.command == 'setup-client':
            value = setup_client(a.client_root, run=a.run)
        else:
            value = plan(a)
            if a.command == 'launch' and a.run:
                return launch(value)
            if a.command == 'doctor':
                value = doctor(value)
                print(json.dumps(value, indent=2)); return 0 if value['ready_to_attempt'] else 2
        print(json.dumps(value, indent=2)); return 0
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({'error': str(exc), 'profile': PROFILE}), file=sys.stderr); return 2


if __name__ == '__main__':
    raise SystemExit(main())
