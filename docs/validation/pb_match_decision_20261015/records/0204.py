import hashlib,json,pathlib,subprocess,time
out=pathlib.Path(__file__).resolve().parent;root=out.parents[1]
files=['tools/prepare_pb_match_decision.py','operator_native/pb_match_decision/CMakeLists.txt','operator_native/pb_match_decision/runner.cpp','operator_native/pb_match_decision/README.md','tests/test_pb_match_decision_prepare.py']
def snapshot():return {p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in files}
def save(name,value):
 with (out/name).open('x',encoding='utf-8') as f:json.dump(value,f,indent=2)
before=snapshot();save('source_before.json',before)
argv=[str(root/'.venv-sim/Scripts/python.exe'),'-m','pytest','-q','tests/test_pb_match_decision_prepare.py','--junitxml='+str(out/'pytest.xml')]
save('COMMAND.json',dict(argv=argv,cwd=str(root),scope='pure source/overlay preparation; no native build/ROS/BT execution'))
start=time.perf_counter()
with (out/'stdout.txt').open('xb') as stdout,(out/'stderr.txt').open('xb') as stderr:
 child=subprocess.Popen(argv,cwd=root,stdout=stdout,stderr=stderr);code=child.wait(timeout=60)
after=snapshot();save('source_after.json',after)
save('RESULT.json',dict(exit_code=code,reaped=child.poll() is not None,pid=child.pid,elapsed_s=time.perf_counter()-start,source_unchanged=before==after))
print((out/'stdout.txt').read_text());print((out/'stderr.txt').read_text());print((out/'RESULT.json').read_text())
raise SystemExit(code)
