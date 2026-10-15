import hashlib, json, pathlib, subprocess, time
root=pathlib.Path(__file__).resolve().parents[2]
out=pathlib.Path(__file__).resolve().parent
owned=['rm_match/integrations/pb_goal_plugin_source.py','rm_match/integrations/pb_goal_plugin_peer.py','tests/test_pb_goal_plugin_source.py','tests/test_pb_goal_plugin_peer.py']
def hashes():return {p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in owned}
def save(name,value):
 with (out/name).open('x',encoding='utf-8') as f:json.dump(value,f,indent=2)
before=hashes();save('source_before.json',before)
cmd=[str(root/'.venv-sim/Scripts/python.exe'),'-m','pytest','-q',*owned[2:],'--junitxml='+str(out/'pytest.xml')]
save('COMMAND.json',dict(argv=cmd,cwd=str(root),scope='controlled unit fixtures; no ROS/GL/physics'))
start=time.perf_counter()
with (out/'stdout.txt').open('xb') as stdout,(out/'stderr.txt').open('xb') as stderr:
 child=subprocess.Popen(cmd,cwd=root,stdout=stdout,stderr=stderr)
 code=child.wait(timeout=60)
after=hashes();save('source_after.json',after)
save('RESULT.json',dict(exit_code=code,reaped=child.poll() is not None,pid=child.pid,elapsed_s=time.perf_counter()-start,source_unchanged=before==after))
print((out/'stdout.txt').read_text());print((out/'stderr.txt').read_text());print(json.dumps(json.loads((out/'RESULT.json').read_text())))
raise SystemExit(code)
