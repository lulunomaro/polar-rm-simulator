
import json,os,select,signal,subprocess,sys,time
from pathlib import Path
out=Path(sys.argv[1]);case=sys.argv[2]
if case=='cooperative':
    stopping=False
    def stop(*_):
        global stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop)
    child=subprocess.Popen([sys.executable,str(out/'service.py')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,start_new_session=True)
    assert child.stdout.readline().strip()=='service_ready'
    metadata={'service_pid':child.pid}
elif case=='nested_orphan':
    child=subprocess.Popen([sys.executable,str(out/'nested.py')],stdout=subprocess.PIPE,text=True,start_new_session=True)
    metadata={'service_pid':child.pid,**json.loads(child.stdout.readline())}
else:
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    child=subprocess.Popen([sys.executable,'-c','import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print("ready",flush=True);time.sleep(120)'],stdout=subprocess.PIPE,text=True,start_new_session=True)
    assert child.stdout.readline().strip()=='ready'
    metadata={'service_pid':child.pid}
print(json.dumps(metadata),flush=True)
assert sys.stdin.readline().strip()=='run'
if case=='nested_orphan':os._exit(0)
if case=='cooperative':
    while not stopping:time.sleep(.002)
    time.sleep(.03)
    child.stdin.write('cleanup\n');child.stdin.flush()
    ready=select.select([child.stdout],[],[],.3)[0]
    answer=child.stdout.readline().strip() if ready else None
    proof=dict(answer=answer,service_alive=child.poll() is None,leader_pid=os.getpid(),service_pid=child.pid)
    (out/'LEADER_CLEANUP.json').write_text(json.dumps(proof))
    assert answer=='cleanup_ack' and proof['service_alive']
else:time.sleep(120)
