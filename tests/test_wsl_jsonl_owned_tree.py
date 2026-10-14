"""Pure lineage tests; actual nested-session fixture is a separate opt-in."""
from unittest.mock import patch
import signal
import pytest
from rm_match.deployment.wsl_jsonl_owned_tree import WslJsonPeerTree

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
