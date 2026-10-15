import hashlib,json,pathlib,subprocess,time
root=pathlib.Path.cwd(); out=root/'artifacts/navigation-goal-lifecycle-focused-20261015-01'
paths=['tests/test_navigation_goal_lifecycle.py','rm_match/integrations/navigation_goal_lifecycle.py','rm_match/platform_v2/decision_contracts.py']
before={p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths}
cmd=[str(root/'.venv-sim/Scripts/python.exe'),'-m','pytest',paths[0],'-q','--junitxml='+str(out/'junit02.xml')]
(out/'COMMAND02.json').write_text(json.dumps(cmd,indent=2),encoding='utf-8')
start=time.perf_counter()
with (out/'stdout02.log').open('wb') as stdout,(out/'stderr02.log').open('wb') as stderr:
 p=subprocess.Popen(cmd,cwd=root,stdout=stdout,stderr=stderr); rc=p.wait(timeout=60)
after={p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths}
(out/'PROCESS_RESULT02.json').write_text(json.dumps(dict(exit_code=rc,reaped=p.poll() is not None,elapsed=time.perf_counter()-start,before=before,after=after,source_unchanged=before==after),indent=2),encoding='utf-8')
print((out/'stdout02.log').read_text());print((out/'stderr02.log').read_text());print('exit',rc)

