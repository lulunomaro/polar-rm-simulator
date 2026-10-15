"""Capture synthetic history/JSONL regressions; no ROS or real-time claim."""
from pathlib import Path
import hashlib,json,os,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/final-withholding-focused-20261015-01'
OUT.mkdir()
names=['rm_match/platform_v2/goal_navigation_contracts.py','rm_match/integrations/navigation_jsonl_peer.py',
       'tests/test_goal_navigation_contracts.py','tests/test_staged_navigation_plugin.py','tests/test_active_goal_navigation_plugin.py']
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
before={n:sha(ROOT/n) for n in names}
write=lambda n,v:(OUT/n).write_bytes((json.dumps(v,indent=2)+'\n').encode())
write('SOURCE_BEFORE.json',before)
for n in names:
    target=OUT/'source'/n;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((ROOT/n).read_bytes())
command=[sys.executable,'-m','pytest',*names[2:],'-q','--tb=short','--junitxml='+str(OUT/'pytest.xml')]
write('COMMAND.json',dict(argv=command,scope=__doc__))
write('PRELIMINARY_FAILURE.json',dict(kind='transcribed_terminal_result_not_raw_log',passed=120,failed=1,
    reason='Test fixture supplied identity-only source to navigation_status_for, which correctly requires original observation; fixture corrected, no production relaxation.',
    test='test_final_expiry_withholds_once_then_next_capture_can_control_same_goal'))
start=time.perf_counter()
with (OUT/'stdout.log').open('xb') as stdout,(OUT/'stderr.log').open('xb') as stderr:
    child=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,
        shell=False,creationflags=subprocess.CREATE_NO_WINDOW)
    code=child.wait()
after={n:sha(ROOT/n) for n in names};write('SOURCE_AFTER.json',after)
result=dict(passed=code==0 and before==after,returncode=code,reaped=child.poll() is not None,
    source_unchanged=before==after,source_files=len(names),elapsed_s=time.perf_counter()-start)
write('RESULT.json',result);print(json.dumps(result));raise SystemExit(0 if result['passed'] else 2)
