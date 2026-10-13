from pathlib import Path
import hashlib,json,os,signal,subprocess,sys,time
root=Path(__file__).resolve().parents[1]
out=root/'artifacts/pb-navigation-sil-actual-20261014-attempt8'
driver=root/'artifacts/pb-navigation-sil-driver-20261014-attempt8'
assert not out.exists() and not driver.exists()
driver.mkdir()
envpath=root/'artifacts/pb-humble-ext4-runtime-20261014/ENVIRONMENT_COMPAT_FINAL.json'
cfgpath=root/'artifacts/pb-navigation-sil-config-20261014-04.json'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
source_names=['tools/pb_navigation_stack.py','tools/qa_pb_navigation_sil.py','rm_match/integrations/pb_controller_context.hpp','tools/pb2025_overlay/pb_scan_source.hpp']
before={n:sha(root/n) for n in source_names}
command=[sys.executable,'-m','tools.qa_pb_navigation_sil','--environment',str(envpath),'--stack-config',str(cfgpath),'--out',str(out),'--seconds','30','--run','--diagnostics']
record=dict(schema='polar.pb-sil-owned-driver.v1',command=command,driver_sha256=sha(__file__),source_sha256=before,
    environment_sha256=sha(envpath),stack_config_sha256=sha(cfgpath),resource_timeout_seconds=180,
    timeout_is_not_sdk_deadline=True,hardware=False,training=False)
(driver/'COMMAND.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf8')
started=time.perf_counter();timed_out=False
with (driver/'stdout.log').open('wb') as stdout,(driver/'stderr.log').open('wb') as stderr:
    proc=subprocess.Popen(command,cwd=root,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,start_new_session=True)
    (driver/'PID.json').write_text(json.dumps(dict(pid=proc.pid,pgid=os.getpgid(proc.pid)))+'\n',encoding='utf8')
    try:proc.wait(timeout=180)
    except subprocess.TimeoutExpired:
        timed_out=True;os.killpg(proc.pid,signal.SIGINT)
        try:proc.wait(timeout=10)
        except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=2)
result=dict(record,elapsed_seconds=time.perf_counter()-started,exit_code=proc.returncode,timed_out=timed_out,
    process_reaped=proc.poll() is not None,source_unchanged=before=={n:sha(root/n) for n in source_names},
    actual_result_path=str(out/'RESULT.json'),actual_result_sha256=sha(out/'RESULT.json') if (out/'RESULT.json').is_file() else None)
(driver/'PROCESS_RESULT.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
print(json.dumps({k:result[k] for k in ('elapsed_seconds','exit_code','timed_out','process_reaped','source_unchanged','actual_result_path')}))
raise SystemExit(0 if proc.returncode==0 and not timed_out else 2)
