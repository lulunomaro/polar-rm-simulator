
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
