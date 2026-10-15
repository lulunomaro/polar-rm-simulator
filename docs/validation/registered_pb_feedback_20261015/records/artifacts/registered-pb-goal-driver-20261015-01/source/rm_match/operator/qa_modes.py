"""Bounded real MuJoCo spin/feedback HTTP smoke; default no GL, no hardware."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=Path('artifacts/operator_modes_smoke'))
    parser.add_argument('--render',action='store_true')
    args=parser.parse_args()
    output=args.out.resolve();output.mkdir(parents=True,exist_ok=True)
    cwd=Path(__file__).resolve().parents[2]
    env=os.environ.copy();env['PYTHONPATH']=str(cwd)
    log=(output/'bridge.jsonl').open('w')
    command=[sys.executable,'-m','rm_match.operator','--port','0','--max-wall-seconds','15','--camera-fps','2']
    if not args.render:command+=['--no-render']
    child=subprocess.Popen(command,cwd=cwd,env=env,stdout=subprocess.PIPE,stderr=log,text=True)
    result={'simulation_only':True,'render_requested':args.render};seq=0
    try:
        ready=child.stdout.readline();log.write(ready);log.flush()
        start=json.loads(ready);url=start['url']
        def get(path):
            with urllib.request.urlopen(url+path,timeout=2) as response:return response.read()
        session=json.loads(get('/session'));assert session['capabilities']['operator_modes_version']==1
        def send(enabled=True,direction='ccw',speed=120.):
            nonlocal seq
            seq+=1
            body=dict(session_id=session['session_id'],epoch=session['epoch'],robot_id=session['robot_id'],
                seq=seq,sent_at_ms=time.time()*1000,focus=True,deadman=True,
                vx_mps=0.,vy_mps=0.,yaw_rate_rps=0.,pitch_rate_rps=0.,fire=False,
                mode_request=dict(spin_enabled=enabled,spin_direction=direction,spin_speed_dps=speed,chassis_follow='free'))
            req=urllib.request.Request(url+'/control',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(req,timeout=1) as response:ack=json.load(response)
            assert ack['accepted'] and ack['seq']==seq
        def run_phase(name,seconds,**settings):
            until=time.monotonic()+seconds
            while time.monotonic()<until:
                send(**settings);time.sleep(.025)
            t=json.loads(get('/telemetry'));result[name]=t
            return t
        def rate(t):return t['operator_modes']['measured']['chassis_yaw_rate_rps']
        ccw=run_phase('ccw_120',.75)
        assert rate(ccw)>.8,ccw['operator_modes']
        fast=run_phase('ccw_420',.75,speed=420.)
        assert rate(fast)>rate(ccw)+1.,fast['operator_modes']
        off=run_phase('spin_off',.65,enabled=False)
        assert abs(rate(off))<abs(rate(fast))*.4,off['operator_modes']
        assert not off['operator_modes']['effective']['spin_enabled']
        cw=run_phase('cw_120',.65,direction='cw')
        assert rate(cw)<-.8,cw['operator_modes']
        if args.render:
            (output/'cw_first_person.jpg').write_bytes(get('/frame.jpg'))
        time.sleep(.4)
        expired=json.loads(get('/telemetry'));result['timeout']=expired
        assert expired['control']['reason']=='control_timeout'
        assert expired['operator_modes']['measured']['yaw_torque']==0.
        assert not expired['operator_modes']['effective']['spin_enabled']
        assert not expired['applied_operator_command']['fire']
        result['checks']=dict(ccw_physical=True,cw_physical=True,speed_changes_physics=True,
                              spin_off_brakes=True,timeout_zero_torque=True,manual_fire_stays_off=True)
        result['success']=True
    finally:
        child.terminate()
        try:child.wait(timeout=5)
        except subprocess.TimeoutExpired:child.kill();child.wait()
        log.write(child.stdout.read());log.close()
        (output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({key:result[key] for key in ('success','checks')}))


if __name__=='__main__':main()
