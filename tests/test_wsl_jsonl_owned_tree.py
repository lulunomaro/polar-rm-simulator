"""Pure lineage/phase checks and opt-in harmless Linux process fixtures."""
from unittest.mock import patch
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import pytest
from rm_match.deployment.wsl_jsonl_owned_tree import WslJsonPeerTree
KILL=getattr(signal,'SIGKILL',9)

class ProcPath:
    def __init__(self,value):self.value=str(value);self.name=self.value.rsplit('/',1)[-1]
    def read_text(self):return 'boot'
    def iterdir(self):return [ProcPath('/proc/'+str(pid)) for pid in (10,20,30,40)]

def owner():
    result=WslJsonPeerTree.__new__(WslJsonPeerTree)
    result.pid=10;result.boot_id='boot';result.child=type('Child',(),dict(pid=20))()
    result.identity=dict(leader_start_ticks=100);result.births={}
    return result

def row(pid,ppid,sid,birth):return dict(pid=pid,ppid=ppid,pgid=sid,sid=sid,start_ticks=birth,state='S')

def test_nested_session_and_subreaper_adoption_remain_owned_by_birth():
    r=owner();rows={10:row(10,1,10,50),20:row(20,10,20,100),
        30:row(30,20,30,110),40:row(40,30,40,120)}
    with patch('rm_match.deployment.wsl_jsonl_owned_tree.Path',ProcPath),patch('rm_match.deployment.wsl_jsonl_owned_tree._stat',lambda pid:rows.get(pid)):
        assert {x['pid'] for x in r._verified_members()}=={20,30,40}
        rows.pop(20);rows[30]['ppid']=10
        assert {x['pid'] for x in r._verified_members()}=={30,40}
        assert r.births=={20:100,30:110,40:120}

def test_pid_reuse_or_live_lineage_escape_is_unclean_never_reauthorized():
    r=owner();rows={20:row(20,10,20,100),30:row(30,20,30,110)}
    with patch('rm_match.deployment.wsl_jsonl_owned_tree.Path',ProcPath),patch('rm_match.deployment.wsl_jsonl_owned_tree._stat',lambda pid:rows.get(pid)):
        r._verified_members();rows[30]['start_ticks']=111
        with pytest.raises(RuntimeError,match='birth changed'):r._verified_members()
        rows[30]['start_ticks']=110;rows[30]['ppid']=1
        with pytest.raises(RuntimeError,match='lineage changed'):r._verified_members()

def test_signal_uses_owned_pidfd_and_rejects_changed_birth_without_numeric_kill():
    r=owner();target=row(30,20,30,110)
    with patch('rm_match.deployment.wsl_jsonl_owned_tree.os.pidfd_open',return_value=91,create=True),\
         patch('rm_match.deployment.wsl_jsonl_owned_tree.signal.pidfd_send_signal',create=True) as send,\
         patch('rm_match.deployment.wsl_jsonl_owned_tree.os.close') as close,\
         patch('rm_match.deployment.wsl_jsonl_owned_tree.os.kill') as numeric,\
         patch('rm_match.deployment.wsl_jsonl_owned_tree._stat',return_value=target):
        assert r._signal_row(target,signal.SIGTERM)
        send.assert_called_once_with(91,signal.SIGTERM,None,0);close.assert_called_once_with(91)
        numeric.assert_not_called()
    with patch('rm_match.deployment.wsl_jsonl_owned_tree.os.pidfd_open',return_value=91,create=True),\
         patch('rm_match.deployment.wsl_jsonl_owned_tree.signal.pidfd_send_signal',create=True) as send,\
         patch('rm_match.deployment.wsl_jsonl_owned_tree.os.close') as close,\
         patch('rm_match.deployment.wsl_jsonl_owned_tree._stat',return_value=dict(target,start_ticks=111)):
        with pytest.raises(RuntimeError,match='birth changed'):r._signal_row(target,signal.SIGTERM)
        send.assert_not_called();close.assert_called_once_with(91)


def phase_case(*,leader_exit_delay=None,child_ignores_term=False,deadline=1.3):
    value=owner();value.closed=False
    clock=[0.];signals=[];leader_exit=[None];members={20:row(20,10,20,100),30:row(30,20,30,110)}
    class Child:
        pid=20;returncode=None
        def poll(self):
            if self.returncode is None and leader_exit[0] is not None and clock[0]>=leader_exit[0]:
                self.returncode=0;members.pop(20,None)
                if 30 in members:members[30]['ppid']=10
            return self.returncode
    value.child=Child()
    def sent(target,sig):
        signals.append((target['pid'],sig,clock[0]))
        if target['pid']==20:
            if sig==KILL:leader_exit[0]=clock[0]
            elif leader_exit_delay is not None:leader_exit[0]=clock[0]+leader_exit_delay
        elif sig==KILL or not child_ignores_term:
            members[30]['state']='Z'
        return True
    def waited(pid,_):
        if pid in members and members[pid]['state']=='Z':members.pop(pid);return pid,0
        return 0,0
    with patch.object(value,'_verified_members',lambda:list(members.values())),\
         patch.object(value,'_signal_row',sent),\
         patch('rm_match.deployment.wsl_jsonl_owned_tree.signal.SIGKILL',KILL,create=True),\
         patch('rm_match.deployment.wsl_jsonl_owned_tree.os.WNOHANG',1,create=True),\
         patch('rm_match.deployment.wsl_jsonl_owned_tree.os.waitpid',waited),\
         patch('rm_match.deployment.wsl_jsonl_owned_tree.time.perf_counter',lambda:clock[0]),\
         patch('rm_match.deployment.wsl_jsonl_owned_tree.time.sleep',lambda delay:clock.__setitem__(0,clock[0]+delay)):
        proof=value.cleanup_until(deadline)
    return proof,signals


def test_cooperative_term_only_signals_leader_until_it_exits_then_remaining_descendants():
    proof,sent=phase_case(leader_exit_delay=.04)
    assert proof['clean'] and proof['reaped'] and proof['group_empty'] and not proof['killed']
    assert sent[0]==(20,signal.SIGTERM,0.)
    assert all(stamp>=.04 for pid,sig,stamp in sent if pid==30)
    assert proof['leader_exit_before_descendant_term'] is True
    assert proof['cleanup_elapsed_s']<.8


def test_stubborn_leader_preserves_original_point8_term_escalation_and_1point17_kill_gate():
    proof,sent=phase_case(child_ignores_term=True)
    assert proof['clean'] and proof['killed'] and proof['cleanup_elapsed_s']<=1.3
    assert all(.8<=stamp<1.17 for pid,sig,stamp in sent if pid==30 and sig==signal.SIGTERM)
    assert all(1.17<=stamp<=1.3 for pid,sig,stamp in sent if sig==KILL)
    assert proof['leader_exit_before_descendant_term'] is False


def test_leader_exit_does_not_give_term_ignoring_orphan_another_grace_or_deadline():
    proof,sent=phase_case(leader_exit_delay=.01,child_ignores_term=True)
    assert proof['clean'] and proof['killed'] and proof['cleanup_elapsed_s']<=1.3
    assert all(.01<=stamp<.8 for pid,sig,stamp in sent if pid==30 and sig==signal.SIGTERM)
    assert all(1.17<=stamp<=1.3 for pid,sig,stamp in sent if sig==KILL)


def test_short_original_deadline_is_not_replaced_by_independent_cooperative_or_kill_budget():
    proof,sent=phase_case(child_ignores_term=True,deadline=.03)
    assert not proof['clean'] and proof['cleanup_elapsed_s']<=.03
    assert all(stamp<.03 for _,_,stamp in sent)


SERVICE = r'''
import signal,sys,time
print('service_ready',flush=True)
for request in sys.stdin:
    if request.strip()=='cleanup':
        time.sleep(.04)
        print('cleanup_ack',flush=True)
'''
NESTED = r'''
import json,signal,subprocess,sys,time
child=subprocess.Popen([sys.executable,'-c','import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print("ready",flush=True);time.sleep(120)'],stdout=subprocess.PIPE,text=True,start_new_session=True)
assert child.stdout.readline().strip()=='ready'
print(json.dumps({'nested_pid':child.pid}),flush=True)
time.sleep(120)
'''
LEADER = r'''
import json,os,select,signal,subprocess,sys,time
from pathlib import Path
out=Path(sys.argv[1]);case=sys.argv[2]
if case=='cooperative':
    stopping=False
    def stop(*_):
        global stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop)
    child=subprocess.Popen([sys.executable,str(out/'service.py')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,start_new_session=True)
    assert child.stdout.readline().strip()=='service_ready'
    metadata={'service_pid':child.pid}
elif case=='nested_orphan':
    child=subprocess.Popen([sys.executable,str(out/'nested.py')],stdout=subprocess.PIPE,text=True,start_new_session=True)
    metadata={'service_pid':child.pid,**json.loads(child.stdout.readline())}
else:
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    child=subprocess.Popen([sys.executable,'-c','import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print("ready",flush=True);time.sleep(120)'],stdout=subprocess.PIPE,text=True,start_new_session=True)
    assert child.stdout.readline().strip()=='ready'
    metadata={'service_pid':child.pid}
print(json.dumps(metadata),flush=True)
assert sys.stdin.readline().strip()=='run'
if case=='nested_orphan':os._exit(0)
if case=='cooperative':
    while not stopping:time.sleep(.002)
    time.sleep(.03)
    child.stdin.write('cleanup\n');child.stdin.flush()
    ready=select.select([child.stdout],[],[],.3)[0]
    answer=child.stdout.readline().strip() if ready else None
    proof=dict(answer=answer,service_alive=child.poll() is None,leader_pid=os.getpid(),service_pid=child.pid)
    (out/'LEADER_CLEANUP.json').write_text(json.dumps(proof))
    assert answer=='cleanup_ack' and proof['service_alive']
else:time.sleep(120)
'''
SUPERVISOR = r'''
import json,select,subprocess,sys,time
from pathlib import Path
from rm_match.deployment.wsl_jsonl_owned_tree import WslJsonPeerTree
out=Path(sys.argv[1]);case=sys.argv[2]
owner=WslJsonPeerTree();child=None;proof=None
try:
    child=subprocess.Popen([sys.executable,str(out/'leader.py'),str(out),case],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,start_new_session=True)
    owner.attach(child)
    assert select.select([child.stdout],[],[],1.)[0], 'leader_ready_timeout'
    metadata=json.loads(child.stdout.readline())
    births=owner._verified_members()
    (out/'READY.json').write_text(json.dumps(dict(metadata=metadata,births=births)))
    child.stdin.write('run\n');child.stdin.flush()
    if case=='nested_orphan':
        end=time.perf_counter()+.3
        while child.poll() is None and time.perf_counter()<end:time.sleep(.002)
        assert child.returncode==0
finally:
    deadline=time.perf_counter()+1.3
    proof=owner.cleanup_until(deadline)
    (out/'OWNERSHIP.json').write_text(json.dumps(proof))
    if child is not None:
        child.stdin.close();child.stdout.close()
assert proof['clean'] and proof['reaped'] and proof['group_empty'] and not proof['remaining_members'], proof
assert proof['cleanup_elapsed_s']<=1.3
ready=json.loads((out/'READY.json').read_text())
assert all(str(pid) in {str(p) for p in proof['observed_births']} for pid in ready['metadata'].values())
if case=='cooperative':
    journal=json.loads((out/'LEADER_CLEANUP.json').read_text())
    assert journal['answer']=='cleanup_ack' and journal['service_alive'] and not proof['killed']
elif case=='stubborn':assert proof['killed'] and proof['leader_exit_before_descendant_term'] is False
else:assert proof['killed'] and proof['leader_exit_before_descendant_term'] is True
print(json.dumps(dict(case=case,passed=True,ownership=proof)),flush=True)
'''


@pytest.mark.skipif(sys.platform!='linux' or os.environ.get('POLAR_RUN_OWNED_TREE_ACTUAL')!='1',
    reason='explicit coordinated harmless Linux ownership fixture required')
@pytest.mark.parametrize('case',['cooperative','nested_orphan','stubborn'])
def test_real_linux_leader_cleanup_service_nested_orphan_and_stubborn_reaping(tmp_path,case):
    base=Path(os.environ.get('POLAR_OWNED_TREE_PROOF_DIR',str(tmp_path)))
    out=base/case;out.mkdir(parents=True,exist_ok=False)
    for name,source in (('service.py',SERVICE),('nested.py',NESTED),('leader.py',LEADER),('supervisor.py',SUPERVISOR)):
        (out/name).write_text(source,encoding='utf8')
    root=Path(__file__).resolve().parents[1]
    env=dict(os.environ,PYTHONPATH=str(root))
    started=__import__('time').perf_counter()
    result=subprocess.run([sys.executable,str(out/'supervisor.py'),str(out),case],cwd=root,env=env,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=7.)
    (out/'STDOUT.txt').write_bytes(result.stdout);(out/'STDERR.txt').write_bytes(result.stderr)
    (out/'EXECUTION.json').write_text(json.dumps(dict(exit_code=result.returncode,reaped=True,
        elapsed_s=__import__('time').perf_counter()-started,scope='harmless Linux processes only; no ROS or physics')))
    assert result.returncode==0,result.stderr.decode(errors='replace')
