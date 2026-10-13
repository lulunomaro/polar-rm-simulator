"""Actual Windows loopback HTTP rejection; no simulator or external transport."""
import hashlib,http.client,json,socket,threading,time
from pathlib import Path
from rm_match.operator.server import BridgeState,start_server

OUT=Path(__file__).parent
state=BridgeState();server,thread=start_server(state,0);port=server.server_address[1]
rows=[]
try:
    for mode in ('http_client','split_body'):
        for i in range(20):
            connection=None;raw=None
            try:
                if mode=='http_client':
                    connection=http.client.HTTPConnection('127.0.0.1',port,timeout=2.)
                    connection.request('POST','/control','x'*4097,{'Content-Type':'application/json'})
                    response=connection.getresponse()
                else:
                    raw=socket.create_connection(('127.0.0.1',port),timeout=2.)
                    raw.sendall(('POST /control HTTP/1.0\r\nHost: 127.0.0.1:'+str(port)+'\r\nContent-Type: application/json\r\nContent-Length: 4097\r\n\r\n').encode())
                    time.sleep(.02);raw.sendall(b'x'*4097)
                    response=http.client.HTTPResponse(raw);response.begin()
                body=response.read();rows.append(dict(mode=mode,trial=i,status=response.status,body=body.decode(),error=None))
            except Exception as error:rows.append(dict(mode=mode,trial=i,error=type(error).__name__,message=str(error)))
            finally:
                if connection is not None:connection.close()
                if raw is not None:raw.close()
finally:
    state.stop();server.shutdown();server.server_close();thread.join(2.)
root=Path(__file__).resolve().parents[2]
report=dict(scope='actual loopback Windows HTTP transport only',source_sha256={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'rm_match/operator/server.py',Path(__file__))},rows=rows,
    failures=sum(r.get('error') is not None for r in rows),server_reaped=not thread.is_alive())
(OUT/'RESULT.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
print(json.dumps(dict(failures=report['failures'],trials=len(rows),server_reaped=report['server_reaped'])))
