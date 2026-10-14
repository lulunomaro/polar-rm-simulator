"""Deterministic fake-clock/runtime experiment, no actual physics or algorithm."""
import argparse,copy,json,sys
from pathlib import Path
if not __debug__:raise SystemExit('Qualification requires normal Python')
p=argparse.ArgumentParser();p.add_argument('--nav-root',required=True,type=Path);p.add_argument('--out',required=True,type=Path);p.add_argument('--expect',choices=['baseline_gap','fresh_output'],required=True);a=p.parse_args()
if a.out.exists():raise SystemExit('Use a new output file')
sys.path.insert(0,str(a.nav_root.absolute()))
from rm_match.platform_v2.runtime import PlatformRuntime
from rm_match.platform_v2.test_runtime import FakeBackend
from rm_match.platform_v2.contracts import action_for
class Slot:
    dropped=0;lifecycle_error=None
    def __init__(self):self.jobs=[];self.result=None
    def submit(self,job):self.jobs.append(copy.deepcopy(job))
    def poll(self):r=self.result;self.result=None;return r
    def close(self):pass
now=[10.];events=[];backend=FakeBackend(('r',));r=PlatformRuntime(backend,clock=lambda:now[0],trace=events.append);r._episode=0
c=r.control;t=c.open_session('operator','server_window_v1')['token'];e=c.claim(t,'r',['motion'])['lease_epochs'];b=r.bind(t,'r','navigation',e,'nav_rule_v1',{'goal_world_m':[.75,0.]});slot=Slot();r.slots['r','navigation']=slot

def pulse(seq):
 w=c.control_window(t,'r',e);ack=c.adapter_input(t,'r','navigation',e,b['binding_epoch'],seq,w['window_id'],.15)
 events.append(dict(event='fake_activation',wall=now[0],sim=backend.sim_time,ack=ack));return ack

def deliver(job):
 slot.result=dict(job=job,error=None,completed=now[0],value=action_for(job['observation'],'navigation','velocity_body',dict(frame='base_link',vx_mps=0.,vy_mps=0.,wz_rps=0.)))
 r._collect(c.snapshot(),backend.sim_time)
old=pulse(0);r._schedule(c.snapshot(),0.);first=slot.jobs[-1];deliver(first)
now[0]=10.1;backend.sim_time=.02;new=pulse(1);r._schedule(c.snapshot(),.02)
fresh_count=len(slot.jobs)
if fresh_count>1:
 now[0]=10.101;deliver(slot.jobs[-1])
now[0]=old['activation_expires'];backend.sim_time=.03;r._collect(c.snapshot(),.03)
snapshot=c.snapshot();target=r._targets(snapshot,.03)['r']['motion'];r.close()
result=dict(scope='real PlatformRuntime and ControlPlane with fake clocks/backend and explicit synthetic adapter output; no MuJoCo/native/GL',old_expiry=old['activation_expires'],new_expiry=new['activation_expires'],scheduled_jobs=fresh_count,current_binding_live=snapshot['bindings']['r']['navigation']['owner'] is not None,old_job_deadline_unchanged=first['observation']['wall_deadline']==old['activation_expires'],target_at_old_expiry=target,events=events)
result['passed']=bool(result['current_binding_live'] and result['old_job_deadline_unchanged'] and ((a.expect=='baseline_gap' and fresh_count==1 and target is None) or (a.expect=='fresh_output' and fresh_count==2 and target is not None)))
a.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='events'}))
if not result['passed']:raise SystemExit(1)
