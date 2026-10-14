"""Capture independent package and original-file verification as owned processes."""
import hashlib,json,os,subprocess,time
from pathlib import Path
root=Path(__file__).resolve().parents[1]
out=root/'docs/validation/git_prepared_bgr_20261014';out.mkdir()
verifier=root/'docs/validation/native_prepared_bgr_20261014/verify_archives.py'
archive=verifier.parent
(out/'driver.py').write_bytes(Path(__file__).read_bytes())
(out/'STAGED_PROGRAM_QA_PROOF.json').write_bytes((root/'artifacts/prepared-bgr-qa-index-proof-20261014/RESULT.json').read_bytes())
(out/'check_staged_programs.py').write_bytes((root/'artifacts/prepared-bgr-qa-index-proof-20261014/driver.py').read_bytes())
rows=[]
for name,extra in [('package',[]),('originals',['--check-originals'])]:
 command=[str(root/'.venv-sim/Scripts/python.exe'),str(verifier),'--archive',str(archive),*extra]
 before=hashlib.sha256(verifier.read_bytes()).hexdigest();started=time.perf_counter()
 with (out/(name+'.stdout.bin')).open('xb') as stdout,(out/(name+'.stderr.bin')).open('xb') as stderr:
  child=subprocess.Popen(command,cwd=root,stdout=stdout,stderr=stderr,stdin=subprocess.DEVNULL,shell=False,creationflags=subprocess.CREATE_NO_WINDOW)
  code=child.wait()
 result=dict(command=command,pid=child.pid,driver_pid=os.getpid(),returncode=code,reaped=child.poll() is not None,
  elapsed_s=time.perf_counter()-started,verifier_sha256_before=before,verifier_sha256_after=hashlib.sha256(verifier.read_bytes()).hexdigest())
 (out/(name+'.json')).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
 assert code==0 and result['verifier_sha256_before']==result['verifier_sha256_after'],result
 rows.append(result)
print(json.dumps(dict(passed=True,processes=len(rows))))
