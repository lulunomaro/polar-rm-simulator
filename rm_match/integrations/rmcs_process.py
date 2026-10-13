"""Copied local JSONL transport. Starts only an explicitly supplied local binary."""
import json,subprocess,select,threading
from pathlib import Path

class RMCSProcess:
 def __init__(self,binary,executor_yaml,out,env,timeout=60.):
  self.binary=Path(binary).resolve();self.executor=Path(executor_yaml).resolve();self.out=Path(out).resolve()
  self.env=env;self.timeout=timeout;self.process=None;self.stderr=None
  self._stop_requested=threading.Event()
 def reset(self,message):
  if self._stop_requested.is_set():raise RuntimeError('RMCS transport stopped; create a new instance')
  self.close();self.out.mkdir(parents=True,exist_ok=True)
  self.stderr=(self.out/'rmcs_stderr.log').open('w')
  self.process=subprocess.Popen([str(self.binary),str(self.executor)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                stderr=self.stderr,text=True,bufsize=1,env=self.env,cwd=self.out)
  if self._stop_requested.is_set():
   self.request_stop();self.close()
   raise RuntimeError('RMCS transport cancelled during startup')
 def request_stop(self):
  """Nonblocking durable cancellation; lifecycle owner later closes/reaps."""
  self._stop_requested.set();child=self.process
  if child is not None and child.poll() is None:
   try:child.terminate()
   except ProcessLookupError:pass
   # No grace wait on the authority: a child ignoring SIGTERM must also unblock
   # its owner's readline. The owner still exclusively waits/reaps/closes pipes.
   if child.poll() is None:
    try:child.kill()
    except ProcessLookupError:pass
 def control(self,packet):
  if self._stop_requested.is_set():raise RuntimeError('RMCS transport stopped')
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
  # Stop the owned process before closing buffered pipes: closing stdin first
  # can flush into a child that stopped reading and block without a deadline.
  # SIGTERM is bounded; an unresponsive child is killed and reaped explicitly.
  child=self.process;stderr=self.stderr
  try:
   if child is not None:
    if child.poll() is None:
     try:child.terminate()
     except ProcessLookupError:pass
     try:child.wait(timeout=.5)
     except subprocess.TimeoutExpired:
      try:child.kill()
      except ProcessLookupError:pass
      child.wait(timeout=.5)
    else:child.wait(timeout=.5)
  finally:
   self.process=None;self.stderr=None
   if child is not None:
    for stream in (child.stdin,child.stdout,getattr(child,'stderr',None)):
     if stream is not None:
      try:stream.close()
      except (OSError,ValueError):pass
   if stderr is not None:
    try:stderr.close()
    except (OSError,ValueError):pass
