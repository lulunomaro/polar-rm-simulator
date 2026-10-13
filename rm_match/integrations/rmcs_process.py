"""Copied local JSONL transport. Starts only an explicitly supplied local binary."""
import json,subprocess,select
from pathlib import Path

class RMCSProcess:
 def __init__(self,binary,executor_yaml,out,env,timeout=60.):
  self.binary=Path(binary).resolve();self.executor=Path(executor_yaml).resolve();self.out=Path(out).resolve()
  self.env=env;self.timeout=timeout;self.process=None;self.stderr=None
 def reset(self,message):
  self.close();self.out.mkdir(parents=True,exist_ok=True)
  self.stderr=(self.out/'rmcs_stderr.log').open('w')
  self.process=subprocess.Popen([str(self.binary),str(self.executor)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                stderr=self.stderr,text=True,bufsize=1,env=self.env,cwd=self.out)
 def control(self,packet):
  request={'time_s':packet['control_time_ns']/1e9,'frame':packet['frame']}
  if self.process.poll() is not None:raise RuntimeError(f'RMCS process exited {self.process.returncode}; inspect stderr')
  self.process.stdin.write(json.dumps(request,allow_nan=False)+'\n');self.process.stdin.flush()
  ready,_,_=select.select([self.process.stdout],[],[],self.timeout)
  if not ready:raise TimeoutError('Actual RMCS response timed out; no synthetic replacement')
  line=self.process.stdout.readline()
  if not line:raise RuntimeError('RMCS closed stdout; no output to apply')
  result=json.loads(line)
  if result.get('status')!='ok' or abs(result['time_s']-request['time_s'])>1e-9:raise ValueError('RMCS invalid status/time')
  # headless source adapter's tracking must denote actual should_track (verified by source owner).
  return {**result,'episode':packet['episode'],'control_time_ns':packet['control_time_ns'],
          'direction_frame':'world','should_control':bool(result['tracking'])}
 def close(self):
  if self.process is not None:
   if self.process.poll() is None:
    self.process.stdin.close()
    try:self.process.wait(timeout=5)
    except subprocess.TimeoutExpired:self.process.terminate();self.process.wait(timeout=5)
   self.process=None
  if self.stderr:self.stderr.close();self.stderr=None
