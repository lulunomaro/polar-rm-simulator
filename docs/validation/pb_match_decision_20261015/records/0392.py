
import signal,sys,time
print('service_ready',flush=True)
for request in sys.stdin:
    if request.strip()=='cleanup':
        time.sleep(.04)
        print('cleanup_ack',flush=True)
