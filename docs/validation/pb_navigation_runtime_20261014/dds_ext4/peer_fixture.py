"""Actual fixed DDS fixture; no physics, algorithm or synthetic localization."""
import json,os,sys
from pathlib import Path
root=Path('/mnt/c/Users/lulu/Desktop/claude/polarsimulation/polar-rm-simulator');sys.path.insert(0,str(root))
out=Path(__file__).absolute().parent
from rclpy.node import Node
original=Node.create_subscription;records={};errors=[]
def subscription(self,message_type,topic,callback,*args,**kwargs):
 kind='tf' if message_type.__name__=='TFMessage' else 'request' if message_type.__name__=='String' and topic.endswith('/polar/pb/request') else None
 if kind is not None:
  original_callback=callback
  def recorded(message,original_callback=original_callback):
   original_callback(message)
   if kind not in records:
    try:
     rows=[]
     for row in self.get_publishers_info_by_topic(topic):
      q=row.qos_profile
      rows.append(dict(topic=topic,node_name=row.node_name,node_namespace=row.node_namespace,
       reliability=q.reliability.name,durability=q.durability.name,history=q.history.name,depth=q.depth))
     if rows:records[kind]=rows
    except Exception as exc:errors.append(type(exc).__name__)
  callback=recorded
 return original(self,message_type,topic,callback,*args,**kwargs)
Node.create_subscription=subscription
from tools.diagnose_pb_humble_sensors import main
# Import the peer's bridge helpers with diagnostics disabled. Only the fresh
# JSONL child owns the O_EXCL phase file, never this DDS fixture parent.
os.environ['POLAR_PB_BRIDGE_PHASE_FILE']=str(out/'bridge_phase.jsonl')
code=main(['--out',str(out/'dds'),'--domain-id','82','--namespace','/polar_tfmessage_ext4/red_sentry'])
expected={'tf':('TRANSIENT_LOCAL',1),'request':('VOLATILE',8)}
passed=not errors and set(records)==set(expected) and all(len(records[k])==1 and records[k][0]['reliability']=='RELIABLE' and records[k][0]['history']=='KEEP_LAST' and (records[k][0]['durability'],records[k][0]['depth'])==v for k,v in expected.items())
(out/'ACTUAL_QOS.json').write_text(json.dumps(dict(records=records,errors=errors,tf_matches_original_broadcaster=True if passed else None,request_bounded_depth_8=passed,passed=passed),indent=2)+'\n')
print(json.dumps(dict(diagnostic_exit=code,qos_passed=passed)))
raise SystemExit(code if passed else 2)
