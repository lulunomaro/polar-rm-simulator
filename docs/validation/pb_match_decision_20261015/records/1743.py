"""Bounded same-process-tree HTTP/physics/render QA. Synthetic operator input."""
import argparse,json,os,subprocess,sys,time,urllib.request
from pathlib import Path

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out',type=Path,default=Path('artifacts/operator_smoke'))
args=parser.parse_args()
runtime=Path(__file__).resolve().parents[2]
output=args.out.resolve();output.mkdir(parents=True,exist_ok=True)
log=(output/'bridge.jsonl').open('w')
env=os.environ.copy();env['PYTHONPATH']=str(runtime)
child=subprocess.Popen([sys.executable,'-m','rm_match.operator','--port','0','--camera-fps','2','--max-wall-seconds','18'],cwd=runtime,env=env,stdout=subprocess.PIPE,stderr=log,text=True)
ready=child.stdout.readline()
log.write(ready);log.flush()
base=json.loads(ready)['url'];seq=0

def get(path):
 with urllib.request.urlopen(base+path,timeout=2) as response:
  data=response.read();return data,dict(response.headers)
def telemetry():return json.loads(get('/telemetry')[0])
def send(**updates):
 global seq
 seq+=1
 m=dict(session_id=session['session_id'],epoch=session['epoch'],robot_id=session['robot_id'],seq=seq,
  sent_at_ms=time.time()*1000,focus=True,deadman=True,vx_mps=0.,vy_mps=0.,yaw_rate_rps=0.,pitch_rate_rps=0.,fire=False)
 m.update(updates)
 request=urllib.request.Request(base+'/control',data=json.dumps(m).encode(),headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(request,timeout=1) as response:
  ack=json.load(response)
 assert ack['accepted'] and ack['seq']==seq
 return ack

result={}
try:
 deadline=time.monotonic()+5
 while True:
  try:session=json.loads(get('/session')[0]);break
  except Exception:
   if time.monotonic()>deadline:raise
   time.sleep(.05)
 assert session['robot_id']=='red_infantry'
 deadline=time.monotonic()+5
 while True:
  before=telemetry()
  if before.get('own',{}).get('ammo',0)>0 and before.get('camera',{}).get('available'):break
  if time.monotonic()>deadline:raise RuntimeError('Camera or legal virtual supply not ready: '+str(before))
  time.sleep(.05)
 result['before']=before
 getframe,headers=get('/frame.jpg');(output/'before.jpg').write_bytes(getframe)
 assert headers['X-Camera-Name']=='red_infantry__aim'
 assert headers['X-Camera-Overlays']=='false'
 assert headers['X-Sim-Session-Id']==session['session_id']
 result['frame_headers']=headers
 deadline=time.monotonic()+1.3
 while time.monotonic()<deadline:
  send(vx_mps=.5,yaw_rate_rps=-.35,pitch_rate_rps=.15,fire=True)
  time.sleep(.04)
 during=telemetry();result['during']=during
 assert during['own']['xy'][0]>before['own']['xy'][0]+.01,(before['own'],during['own'])
 assert during['own']['gimbal_yaw']<before['own']['gimbal_yaw']-.05
 assert during['own']['ammo']<before['own']['ammo']
 # Heartbeat loss needs no renderer progress to expire the input lease.
 time.sleep(.4)
 after=telemetry();result['after_timeout']=after
 assert after['control']['reason']=='control_timeout',after['control']
 applied=after['applied_operator_command']
 assert applied['force_x']==0 and applied['force_y']==0 and not applied['fire'],applied
 send(vx_mps=.5,fire=True,focus=False)
 time.sleep(.1)
 blur=telemetry();result['after_blur']=blur
 assert blur['control']['reason']=='focus_lost'
 assert not blur['applied_operator_command']['fire']
 frame,headers=get('/frame.jpg');(output/'after.jpg').write_bytes(frame)
 from PIL import Image
 im=Image.open(output/'after.jpg');assert im.size==(320,240)
 result['checks']={'human_motion':True,'human_aim':True,'virtual_judge_shot':True,'raw_first_person_jpeg':True,
  'heartbeat_timeout_neutral':True,'focus_loss_neutral':True,'frozen_match_untouched':True}
 result['measured_interval']={'wall_seconds':1.3,'sim_seconds':during['sim_time']-before['sim_time']}
 result['success']=True
finally:
 child.terminate()
 try:child.wait(timeout=5)
 except subprocess.TimeoutExpired:child.kill();child.wait()
 log.write(child.stdout.read());log.close()
 (output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:result[k] for k in ('success','checks','measured_interval')}))
