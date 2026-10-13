import hashlib,json,os,pathlib,signal,subprocess,time
repo=pathlib.Path('/mnt/c/Users/lulu/Desktop/claude/polarsimulation/polar-rm-simulator')
old=repo/'artifacts/pb2025-nav2-plugins-actual-build-20261013-02'
out=pathlib.Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
source=old/'src/pb_omni_pid_pursuit_controller'
identity_path=source/'SOURCE_IDENTITY.json';identity=json.loads(identity_path.read_text())
for name,metadata in identity['files'].items():
    if sha(source/name)!=metadata['sha256']:raise ValueError('resume_source_changed')
before={str(p):sha(p) for p in (identity_path,old/'BUILD_RESULT.json',old/'build.log')}
envpath=repo/'artifacts/pb2025-humble-environment-20261013/ENVIRONMENT_COMPAT.json'
envraw=envpath.read_bytes();env=dict(os.environ);env.update(json.loads(envraw)['process_environment']);env['MAKEFLAGS']='-j2'
cmd=['colcon','--log-base',str(out/'logs'),'build','--base-paths',str(source),'--packages-select','pb_omni_pid_pursuit_controller',
     '--build-base',str(old/'build'),'--install-base',str(old/'install'),'--executor','sequential','--cmake-args',
     '-DBUILD_TESTING=OFF','-DPython3_EXECUTABLE=/usr/bin/python3','-DPYTHON_EXECUTABLE=/usr/bin/python3']
start=time.perf_counter();timeout=False
with (out/'resume_build.log').open('xb') as log:
    proc=subprocess.Popen(cmd,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    try:proc.wait(timeout=600)
    except subprocess.TimeoutExpired:
        timeout=True
        try:os.killpg(proc.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        try:proc.wait(timeout=.5)
        except subprocess.TimeoutExpired:pass
        try:os.killpg(proc.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        proc.wait(timeout=1.)
after={name:sha(pathlib.Path(name)) for name in before}
result=dict(schema='polar.sim.pb-controller-resume.v1',command=cmd,exit_code=proc.returncode,
            timeout=timeout,elapsed_seconds=time.perf_counter()-start,original_evidence_before_sha256=before,
            original_evidence_after_sha256=after,original_reports_unchanged=before==after,
            reuse_verified_source=True,reuse_build=str(old/'build'),install=str(old/'install'),
            environment_sha256=hashlib.sha256(envraw).hexdigest(),environment=json.loads(envraw)['process_environment'],
            MAKEFLAGS='-j2',SDK_reset_timeout_unchanged=2.,navigation_nodes_started=False)
(out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
raise SystemExit(0 if proc.returncode==0 and not timeout and before==after else 2)
