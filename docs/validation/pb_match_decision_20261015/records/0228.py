"""Build the fixed protocol-v1.7.0 messages in a fresh owned ext4 prefix, no ROS nodes."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys,time,traceback
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from rm_match.integrations.owned_linux_group import LinuxOwnedProcessGroup
OUT=ROOT/'artifacts/pb-match-interfaces-build-20261015-01'
WORK=Path('/root/polar-pb-match-interfaces-20261015-01')
assert not OUT.exists() and not WORK.exists()
OUT.mkdir();WORK.mkdir()
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
write=lambda p,v:p.write_bytes((json.dumps(v,indent=2)+'\n').encode())
(OUT/'driver.py').write_bytes(Path(__file__).read_bytes())
audit=ROOT/'artifacts/pb-match-behavior-audit-20261014-01'
source=audit/'pb_rm_interfaces_protocol_v1_7_0';manifest=json.loads((audit/'pb_rm_interfaces_protocol.FILES.json').read_bytes())
before={n:sha(source/n) for n in manifest};assert before==manifest
shutil.copytree(source,WORK/'source',ignore=shutil.ignore_patterns('.git'))
assert {n:sha(WORK/'source'/n) for n in manifest}==manifest
write(OUT/'SOURCE_BEFORE.json',before)
settings=json.loads((ROOT/'artifacts/pb-humble-ext4-runtime-20261014/ENVIRONMENT_COMPAT_FINAL.json').read_bytes())
env=dict(os.environ,**settings['process_environment'])
commands=[['cmake','-S',str(WORK/'source'),'-B',str(WORK/'build'),
    '-DCMAKE_BUILD_TYPE=Release','-DCMAKE_EXPORT_COMPILE_COMMANDS=ON','-DBUILD_TESTING=OFF',
    '-DCMAKE_INSTALL_PREFIX='+str(WORK/'install'),
    '-DPython3_EXECUTABLE='+settings['venv_python'],'-DPYTHON_EXECUTABLE='+settings['venv_python']],
    ['cmake','--build',str(WORK/'build'),'--parallel','2'],
    ['cmake','--install',str(WORK/'build')]]
steps=[];error=None;started=time.perf_counter()
try:
    for index,argv in enumerate(commands,1):
        owner=LinuxOwnedProcessGroup();child=None;begin=time.perf_counter()
        with (OUT/f'step{index}.log').open('xb') as sink:
            try:
                child=subprocess.Popen(argv,cwd=WORK,env=env,stdin=subprocess.DEVNULL,
                    stdout=sink,stderr=subprocess.STDOUT,start_new_session=True)
                identity=owner.attach(child)
                write(OUT/f'step{index}.COMMAND.json',dict(argv=argv,identity=identity,timeout_s=900))
                code=child.wait(timeout=900)
            finally:
                cleanup=owner.cleanup();write(OUT/f'step{index}.CLEANUP.json',cleanup)
        row=dict(argv=argv,exit_code=code,elapsed_s=time.perf_counter()-begin,cleanup=cleanup)
        steps.append(row);write(OUT/'STEPS.json',steps)
        if code or not cleanup['clean']:raise RuntimeError('build_step_failed:'+str(index))
    lib=WORK/'install/lib/libpb_rm_interfaces__rosidl_typesupport_cpp.so'
    assert lib.is_file()
    child=subprocess.run(['ldd',str(lib)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=10,env=env)
    (OUT/'LDD.log').write_bytes(child.stdout)
    assert child.returncode==0 and b'not found' not in child.stdout
    for name in ('CMakeCache.txt','compile_commands.json'):
        shutil.copyfile(WORK/'build'/name,OUT/name)
except BaseException as exc:
    error=type(exc).__name__+':'+str(exc);(OUT/'FAILURE.log').write_text(traceback.format_exc())
after={n:sha(source/n) for n in manifest};write(OUT/'SOURCE_AFTER.json',after)
lib=WORK/'install/lib/libpb_rm_interfaces__rosidl_typesupport_cpp.so'
result=dict(schema='polar.pb-match-interfaces-build.v1',passed=error is None and before==after,
    fixed_revision='8912fa565a7ac57ef070df218957379123d238ee',version='protocol-v1.7.0',
    source_files=len(manifest),source_unchanged=before==after,work=str(WORK),install=str(WORK/'install'),
    library=str(lib),library_sha256=sha(lib) if lib.is_file() else None,steps=steps,error=error,
    elapsed_s=time.perf_counter()-started,nodes_started=False,scope='actual clean protocol message build only; no decision tick or SIL')
write(OUT/'RESULT.json',result);print(json.dumps({k:v for k,v in result.items() if k!='steps'}))
raise SystemExit(0 if result['passed'] else 2)
