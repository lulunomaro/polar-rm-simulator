
import json,signal,subprocess,sys,time
child=subprocess.Popen([sys.executable,'-c','import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print("ready",flush=True);time.sleep(120)'],stdout=subprocess.PIPE,text=True,start_new_session=True)
assert child.stdout.readline().strip()=='ready'
print(json.dumps({'nested_pid':child.pid}),flush=True)
time.sleep(120)
