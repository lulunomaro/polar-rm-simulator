"""Observer-only recording health. Never changes control or simulation time."""
import json,os,time
from pathlib import Path

FRAGMENTED_MP4_ARGS=['-movflags','+frag_keyframe+empty_moov+default_base_moof','-g','10','-flush_packets','1']

def memory_snapshot():
    result={'processes':[],'host_memory_kb':{}}
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            k,rest=line.split(':',1)
            if k in ('MemTotal','MemAvailable','SwapTotal','SwapFree'):
                result['host_memory_kb'][k]=int(rest.split()[0])
        for p in Path('/proc').iterdir():
            if not p.name.isdigit():continue
            try:
                values={k:v.strip() for k,v in (line.split(':',1) for line in (p/'status').read_text().splitlines() if ':' in line)}
                result['processes'].append({'pid':int(p.name),'name':values.get('Name'),'rss_kb':int(values.get('VmRSS','0 kB').split()[0])})
            except (OSError,ValueError):continue
    except OSError as exc:result['read_error']=type(exc).__name__
    return result

class RecordingHealth:
    def __init__(self,out,enabled):
        self.out=Path(out);self.enabled=enabled;self.last_wall=-float('inf');self.last_checkpoint=-float('inf')
        self.file=(self.out/'resource_health.jsonl').open('w') if enabled else None
        self.frames=(self.out/'durable_physics_replay.jsonl').open('w') if enabled else None
    def tick(self,sim,physics_frame,recorded_frames):
        if not self.enabled:return
        self.frames.write(json.dumps(physics_frame,separators=(',',':'))+'\n')
        now=time.monotonic()
        if now-self.last_wall>=30:
            self.last_wall=now
            self.file.write(json.dumps({'wall_unix_s':time.time(),'sim_time_s':sim.time,'recorded_frames':recorded_frames,**memory_snapshot()})+'\n');self.file.flush()
        if sim.time-self.last_checkpoint>=5:
            self.last_checkpoint=sim.time;self.frames.flush()
            data={'status':'checkpoint_not_a_complete_episode','sim_time_s':sim.time,'recorded_frames':recorded_frames,'judge':sim.judge.snapshot(),'referee_events':sim.judge.events}
            tmp=self.out/'checkpoint.tmp';tmp.write_text(json.dumps(data,separators=(',',':')));os.replace(tmp,self.out/'checkpoint.json')
    def close(self):
        if self.file:self.file.close()
        if self.frames:self.frames.close()
