"""Actual Windows loopback rejection probe; no simulation or ROS runtime."""
import hashlib,http.client,json,subprocess,sys,threading,time
from pathlib import Path
from types import SimpleNamespace
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[1];sys.path.insert(0,str(ROOT))
from rm_match.platform_v2.server import PlatformHTTPServer,TransportConfig,MAX_BODY_BYTES

def main():
    label=sys.argv[1]
    source=ROOT/'rm_match/platform_v2/server.py';before=source.read_bytes()
    (OUT/('server.'+label+'.py')).write_bytes(before)
    if label=='before':
        blob=subprocess.check_output(['git','show','438ef2f:rm_match/platform_v2/server.py'],cwd=ROOT)
        (OUT/'HEAD438.server.py').write_bytes(blob)
        (OUT/'BASE_IDENTITY.json').write_text(json.dumps(dict(current_sha256=hashlib.sha256(before).hexdigest(),
            git_438_blob_sha256=hashlib.sha256(blob).hexdigest(),exact_bytes_equal=before==blob,
            canonical_lf_equal=before.replace(b'\r\n',b'\n')==blob.replace(b'\r\n',b'\n')),indent=2))
    runtime=SimpleNamespace(control=SimpleNamespace(robot_ids=['red_sentry']))
    server=PlatformHTTPServer(TransportConfig(port=0,max_http_workers=2),runtime)
    thread=threading.Thread(target=lambda:server.serve_forever(poll_interval=.01));thread.start();rows=[]
    started=time.perf_counter()
    try:
        for delay in (0.,.015,.05):
            for sample in range(12):
                conn=http.client.HTTPConnection('127.0.0.1',server.server_address[1],timeout=2.)
                then=time.perf_counter();row=dict(delay_s=delay,sample=sample)
                try:
                    if delay==0:conn.request('POST','/v2/sessions','x'*(MAX_BODY_BYTES+1),{'Content-Type':'application/json'})
                    else:
                        conn.putrequest('POST','/v2/sessions');conn.putheader('Content-Type','application/json')
                        conn.putheader('Content-Length',str(MAX_BODY_BYTES+1));conn.endheaders()
                        time.sleep(delay);conn.send(b'x'*(MAX_BODY_BYTES+1))
                    response=conn.getresponse();raw=response.read()
                    row.update(status=response.status,body=json.loads(raw),exact_response=response.status==413 and json.loads(raw)=={'accepted':False,'error':'body_too_large'})
                except Exception as error:row.update(error_type=type(error).__name__,error=str(error),exact_response=False)
                finally:conn.close()
                row['elapsed_s']=time.perf_counter()-then;rows.append(row)
                print(json.dumps(row),flush=True)
    finally:
        server.shutdown();server.server_close();thread.join(2.)
    result=dict(scope='actual loopback TCP with fake runtime; no simulation/ROS/authorization bypass',label=label,
        source_sha256=hashlib.sha256(before).hexdigest(),source_unchanged=source.read_bytes()==before,
        samples=rows,exact_responses=sum(r['exact_response'] for r in rows),all_responses_exact=all(r['exact_response'] for r in rows),
        serve_thread_reaped=not thread.is_alive(),elapsed_s=time.perf_counter()-started)
    (OUT/(label+'.json')).write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='samples'}))

if __name__=='__main__':main()
