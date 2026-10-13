import hashlib,json,os,signal,subprocess,sys,time
from pathlib import Path
root=Path('/mnt/c/Users/lulu/Desktop/claude/polarsimulation/polar-rm-simulator');out=Path(__file__).absolute().parent
environment=Path(sys.argv[1]);environment_raw=environment.read_bytes()
environment_sha=hashlib.sha256(environment_raw).hexdigest()
if environment_sha!='d60183ebf62d520c72eb20b84207fa4344d8f17183bb0df8eee92f97b7f981ee':raise ValueError('final_ext4_environment_identity_changed')
settings=json.loads(environment_raw)
if (out/'dds').exists() or (out/'bridge_phase.jsonl').exists():raise ValueError('requires_fresh_dds_and_phase_output')
env=dict(os.environ);env.update(settings['process_environment'])
for key in ('PYTHONPATH','PYTHONHOME','POLAR_PB_BRIDGE_PHASE_FILE'):env.pop(key,None)
cmd=[settings['venv_python'],str(out/'peer_fixture.py')];started=time.perf_counter()
proc=subprocess.Popen(cmd,env=env,cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
timed_out=False
try:stdout,stderr=proc.communicate(timeout=30)
except subprocess.TimeoutExpired:
 timed_out=True;os.killpg(proc.pid,signal.SIGKILL);stdout,stderr=proc.communicate(timeout=1)
(out/'stdout.log').write_text(stdout);(out/'stderr.log').write_text(stderr)
(out/'PROCESS_RESULT.json').write_text(json.dumps(dict(command=cmd,exit_code=proc.returncode,elapsed_seconds=time.perf_counter()-started,
 timed_out=timed_out,process_reaped=proc.poll() is not None,environment_path=str(environment),environment_sha256=environment_sha,
 wrapper_sha256=hashlib.sha256((out/'peer_fixture.py').read_bytes()).hexdigest(),
 qualification='actual DDS explicit sensor fixture, not 9 node SIL or physics or navigation'),indent=2)+'\n')
print(stdout);print('exit',proc.returncode)
