import hashlib,json,os,signal,subprocess,time
from pathlib import Path
root=Path('/mnt/c/Users/lulu/Desktop/claude/polarsimulation/polar-rm-simulator');out=root/'artifacts/pb-humble-tfmessage-evidence-20261014'
environment=root/'artifacts/pb2025-humble-environment-20261013/ENVIRONMENT_COMPAT.json'
settings=json.loads(environment.read_text());env=dict(os.environ);env.update(settings['process_environment'])
for key in ('PYTHONPATH','PYTHONHOME','POLAR_PB_BRIDGE_PHASE_FILE'):env.pop(key,None)
cmd=[settings['venv_python'],str(out/'peer_fixture.py')];started=time.perf_counter()
proc=subprocess.Popen(cmd,env=env,cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
timed_out=False
try:stdout,stderr=proc.communicate(timeout=30)
except subprocess.TimeoutExpired:
 timed_out=True;os.killpg(proc.pid,signal.SIGKILL);stdout,stderr=proc.communicate(timeout=1)
(out/'stdout.log').write_text(stdout);(out/'stderr.log').write_text(stderr)
(out/'PROCESS_RESULT.json').write_text(json.dumps(dict(command=cmd,exit_code=proc.returncode,elapsed_seconds=time.perf_counter()-started,
 timed_out=timed_out,process_reaped=proc.poll() is not None,environment_sha256=hashlib.sha256(environment.read_bytes()).hexdigest(),
 qualification='actual DDS explicit sensor fixture, not 9 node SIL or physics or navigation'),indent=2)+'\n')
print(stdout);print('exit',proc.returncode)
