"""Capture host profile/stack/worker regression; no ROS or GL."""
from pathlib import Path
import hashlib,json,os,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'artifacts/goal-uuid-stack-focused-20261015-01';OUT.mkdir()
names=['tools/pb_navigation_stack.py','rm_match/integrations/pb_wsl_navigation_worker.py',
 'tools/qa_pb_navigation_sil.py','tests/test_pb_goal_stack_profile.py','tests/test_pb_navigation_stack.py',
 'tests/test_pb_wsl_navigation_worker.py','tests/test_pb_wsl_navigation_stdio.py']
before={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}
for n in names:
    p=OUT/'source'/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/n).read_bytes())
argv=[sys.executable,'-B','-m','pytest','-q',*names[3:],'-p','no:cacheprovider','--junitxml='+str(OUT/'pytest.xml')]
(OUT/'driver.py').write_bytes(Path(__file__).read_bytes());(OUT/'COMMAND.json').write_bytes((json.dumps(argv,indent=2)+'\n').encode())
started=time.perf_counter()
with (OUT/'stdout.log').open('xb') as stdout,(OUT/'stderr.log').open('xb') as stderr:
    child=subprocess.Popen(argv,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,shell=False,creationflags=subprocess.CREATE_NO_WINDOW)
    code=child.wait()
after={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}
result=dict(exit_code=code,reaped=child.poll() is not None,elapsed_s=time.perf_counter()-started,source_before=before,
 source_after=after,source_unchanged=before==after,scope='host unit/controlled worker process tests; skips explicit, no native ROS/GL')
(OUT/'RESULT.json').write_bytes((json.dumps(result,indent=2)+'\n').encode());print(json.dumps({k:v for k,v in result.items() if k not in ('source_before','source_after')}));sys.exit(code)
