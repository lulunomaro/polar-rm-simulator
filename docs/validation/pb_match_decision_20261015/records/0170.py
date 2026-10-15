import ast,hashlib,json,pathlib,subprocess,sys,time
root=pathlib.Path(__file__).resolve().parents[2]
out=pathlib.Path(__file__).resolve().parent
files=['rm_match/integrations/pb_match_decision_peer.py','tests/test_pb_match_decision_peer.py','rm_match/platform_v2/decision_contracts.py','rm_match/platform_v2/navigation_feedback_contracts.py','rm_match/deployment/decision_plugin.py','rm_match/deployment/profile.py']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
before={n:sha(root/n) for n in files}
for n in files:
 p=out/'source02'/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((root/n).read_bytes())
for n in files[:2]:ast.parse((root/n).read_text(encoding='utf8'),filename=n)
command=[sys.executable,'-m','pytest','tests/test_pb_match_decision_peer.py','tests/test_decision_navigation_v2.py','tests/test_decision_plugin.py','-q','--junitxml='+str(out/'junit02.xml')]
(out/'COMMAND02.json').write_text(json.dumps({'argv':command,'scope':'pure exec/pin negative units and harmless stdlib decision peer regression; no nativeBT build/tick/ROS/WSL/NN/physics'},indent=2),encoding='utf8')
start=time.perf_counter()
with (out/'stdout02.log').open('wb') as stdout,(out/'stderr02.log').open('wb') as stderr:
 child=subprocess.Popen(command,cwd=root,stdout=stdout,stderr=stderr,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
 try:rc=child.wait(timeout=60)
 except subprocess.TimeoutExpired:child.kill();rc=child.wait();raise
elapsed=time.perf_counter()-start
after={n:sha(root/n) for n in files}
result={'exit_code':rc,'reaped':child.poll() is not None,'elapsed_s':elapsed,'source_unchanged':before==after,'before':before,'after':after}
(out/'PROCESS_RESULT02.json').write_text(json.dumps(result,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in result.items() if k not in ('before','after')}));print((out/'stdout02.log').read_text());sys.exit(rc)
