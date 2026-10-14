from types import SimpleNamespace
import json
from rm_match.recording_health import RecordingHealth,FRAGMENTED_MP4_ARGS,memory_snapshot

def test_disabled_does_not_create_files(tmp_path):
    x=RecordingHealth(tmp_path,False);x.tick(None,None,0);x.close();assert not list(tmp_path.iterdir())

def test_records_without_changing_simulation(tmp_path):
    judge=SimpleNamespace(events=[{'type':'fixture'}],snapshot=lambda:{'phase':'running'})
    sim=SimpleNamespace(time=1.5,judge=judge)
    x=RecordingHealth(tmp_path,True);x.tick(sim,{'t':1.5,'qpos':[1,2]},16);x.close()
    assert sim.time==1.5 and judge.events==[{'type':'fixture'}]
    checkpoint=json.loads((tmp_path/'checkpoint.json').read_text())
    assert checkpoint['status']=='checkpoint_not_a_complete_episode'
    assert checkpoint['sim_time_s']==1.5 and checkpoint['recorded_frames']==16
    assert json.loads((tmp_path/'durable_physics_replay.jsonl').read_text())=={'t':1.5,'qpos':[1,2]}
    assert 'host_memory_kb' in json.loads((tmp_path/'resource_health.jsonl').read_text())

def test_fragment_options_only_change_container_encoding():
    assert FRAGMENTED_MP4_ARGS==['-movflags','+frag_keyframe+empty_moov+default_base_moof','-g','10','-flush_packets','1']
    assert isinstance(memory_snapshot()['processes'],list)
