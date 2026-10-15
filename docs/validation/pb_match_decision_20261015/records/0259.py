"""Captured, owned real native BT/PB build; never starts decision or physics."""
from pathlib import Path
import argparse,hashlib,json,os,shutil,sys,threading,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from rm_match.deployment.windows_owned_job import WindowsOwnedJobProcess
p=argparse.ArgumentParser();p.add_argument('--attempt',type=int,required=True);a=p.parse_args();assert 1<=a.attempt<=20
out=ROOT/'artifacts'/f'pb-match-native-build-20261015-{a.attempt:02}';out.mkdir()
write=lambda p,v:p.write_bytes((json.dumps(v,indent=2)+'\n').encode())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
names=['operator_native/pb_match_decision/CMakeLists.txt','operator_native/pb_match_decision/runner.cpp',
    'tools/prepare_pb_match_decision.py','artifacts/run_pb_match_native_build_20261015.py']
before={n:sha(ROOT/n) for n in names};write(out/'SOURCE_BEFORE.json',before)
for name in names:
    target=out/'executed-source'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((ROOT/name).read_bytes())
mounted='/mnt/c/Users/lulu/Desktop/claude/polarsimulation/polar-rm-simulator'
argv=['wsl.exe','-d','Ubuntu-22.04','--','/root/polar-humble-ext4-20261014-01/venv/bin/python',
    mounted+'/tools/prepare_pb_match_decision.py','--out',f'/root/polar-pb-match-decision-build-20261015-{a.attempt:02}',
    '--btcpp-prefix','/root/polar-pb-match-bt4-20261015-01/install',
    '--interface-prefix','/root/polar-pb-match-interfaces-20261015-02/install',
    '--environment',mounted+'/artifacts/pb-humble-ext4-runtime-20261014/ENVIRONMENT_COMPAT_FINAL.json','--build']
write(out/'COMMAND.json',dict(argv=argv,timeout_s=240,nodes_started=False));start=time.perf_counter()
with (out/'stdout.log').open('xb') as sink,(out/'stderr.log').open('xb') as stderr:
    owner=WindowsOwnedJobProcess(argv,cwd=str(ROOT),env=dict(os.environ),stderr=stderr)
    owner.stdin.close()
    reader=threading.Thread(target=lambda:shutil.copyfileobj(owner.stdout,sink),daemon=True);reader.start()
    try:code=owner.wait(timeout=240)
    except BaseException:
        write(out/'FORCED_CLEANUP.json',owner.cleanup(time.perf_counter()+1.5));raise
    end=time.perf_counter()+1.5
    while owner.active_processes() and time.perf_counter()<end:time.sleep(.005)
    reader.join(max(0,end-time.perf_counter()));empty=owner.active_processes()==0
    stopped=not reader.is_alive();assert empty and stopped and time.perf_counter()<end
    owner.stdout.close();owner.release_handles()
after={n:sha(ROOT/n) for n in names};write(out/'SOURCE_AFTER.json',after)
import subprocess
copy_argv=['wsl.exe','-d','Ubuntu-22.04','--','/usr/bin/python3',mounted+'/artifacts/copy_pb_match_build_evidence_20261015.py','--attempt',str(a.attempt)]
copy_result=subprocess.run(copy_argv,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
(out/'mirror.stdout').write_bytes(copy_result.stdout);(out/'mirror.stderr').write_bytes(copy_result.stderr)
write(out/'MIRROR_COMMAND.json',dict(argv=copy_argv,exit_code=copy_result.returncode,reaped=True))
build=json.loads((out/'BUILD_RESULT.json').read_bytes()) if (out/'BUILD_RESULT.json').exists() else None
result=dict(passed=bool(code==0 and before==after and empty and stopped and copy_result.returncode==0 and build and build['passed']),
    returncode=code,reaped=True,job_empty=empty,reader_stopped=stopped,handles_released=True,source_unchanged=before==after,
    elapsed_s=time.perf_counter()-start,nodes_started=False,scope='actual native build only, no decision tick/SIL')
write(out/'RESULT.json',result);print(json.dumps(result));raise SystemExit(0 if result['passed'] else 2)
