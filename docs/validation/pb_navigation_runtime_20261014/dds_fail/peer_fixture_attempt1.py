import json,sys
from pathlib import Path
root=Path('/mnt/c/Users/lulu/Desktop/claude/polarsimulation/polar-rm-simulator');sys.path.insert(0,str(root))
out=root/'artifacts/pb-humble-tfmessage-evidence-20261014'
from rclpy.node import Node
original=Node.create_subscription;records=[];errors=[]
def subscription(self,message_type,topic,callback,*args,**kwargs):
 if message_type.__name__=='TFMessage':
  def recorded(message):
   callback(message)
   if not records:
    try:
     for row in self.get_publishers_info_by_topic(topic):
      q=row.qos_profile
      records.append(dict(topic=topic,node_name=row.node_name,node_namespace=row.node_namespace,
       reliability=q.reliability.name,durability=q.durability.name,history=q.history.name,depth=q.depth))
    except Exception as exc:errors.append(type(exc).__name__)
  callback=recorded
 return original(self,message_type,topic,callback,*args,**kwargs)
Node.create_subscription=subscription
from tools.diagnose_pb_humble_sensors import main
code=main(['--out',str(out/'dds'),'--domain-id','82','--namespace','/polar_tfmessage_probe/red_sentry'])
passed=len(records)==1 and not errors and all(r['reliability']=='RELIABLE' and r['durability']=='TRANSIENT_LOCAL' and r['history']=='KEEP_LAST' and r['depth']==1 for r in records)
(out/'STATIC_TF_QOS.json').write_text(json.dumps(dict(records=records,errors=errors,matched_original_broadcaster_qos=passed),indent=2)+'\n')
print(json.dumps(dict(diagnostic_exit=code,qos_passed=passed)))
raise SystemExit(code if passed else 2)
