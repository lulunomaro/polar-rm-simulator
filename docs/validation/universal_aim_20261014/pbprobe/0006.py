"""Root-executed Windows actual prepare/reset probe, no act/image/NN."""
import argparse,hashlib,json,sys,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
def write(path,value):Path(path).write_bytes((json.dumps(value,indent=2,sort_keys=True)+'\n').encode())
def main():
 p=argparse.ArgumentParser();p.add_argument('--label',required=True);p.add_argument('--manifest',type=Path,required=True)
 p.add_argument('--robot-id',required=True);p.add_argument('--episode',type=int,required=True);p.add_argument('--binding-epoch',type=int,required=True)
 a=p.parse_args();assert __import__('re').fullmatch('[a-z0-9_-]{1,60}',a.label)
 out=Path(__file__).parent/('host_'+a.label)
 if out.exists():raise ValueError('fresh host probe label required')
 out.mkdir();prepared=adapter=None;result=dict(success=False,act_calls=0,image_captures=0,inference_calls=0,
  context=dict(robot_id=a.robot_id,episode=a.episode,binding_epoch=a.binding_epoch),qualification='Actual resource/reset only, no SDK lease or realtime acceptance')
 try:
  from rm_match.deployment.wsl_jsonl import PreparedWslAimPlugins
  prepared=PreparedWslAimPlugins.__new__(PreparedWslAimPlugins)
  start=time.perf_counter();prepared.__init__(a.manifest,repo_root=ROOT,shared_root=out/'owned',clock=time.perf_counter,startup_timeout=15.)
  result['prepare_seconds']=time.perf_counter()-start
  adapter=prepared.take('custom_pb_aim',prepared.sha)
  start=time.perf_counter();adapter.reset(result['context']);result['reset_seconds']=time.perf_counter()-start
  result['prepared']=adapter.prepared;result['claimed']=adapter.claimed;result['manifest_sha256']=prepared.sha
  result['success']=adapter.prepared and adapter.claimed and result['reset_seconds']<=2.
 except BaseException as exc:
  result['error']=type(exc).__name__+':'+str(exc);(out/'FAILED_TRACEBACK.txt').write_text(traceback.format_exc())
  if hasattr(exc,'cleanup_status'):result['failure_cleanup_status']=exc.cleanup_status
 finally:
  if adapter is not None:
   try:adapter.close()
   except BaseException:
    result['success']=False;(out/'CLOSE_TRACEBACK.txt').write_text(traceback.format_exc())
   result['cleanup']=adapter.shutdown_status
   if not result['cleanup'] or result['cleanup'].get('clean') is not True:result['success']=False
  if prepared is not None and hasattr(prepared,'instances'):
   instances=dict(prepared.instances)
   try:prepared.close_unclaimed()
   except BaseException:result['success']=False;(out/'UNCLAIMED_TRACEBACK.txt').write_text(traceback.format_exc())
   result['unclaimed_cleanup']={k:v.shutdown_status for k,v in instances.items()}
  write(out/'PROBE_RESULT.json',result);print(json.dumps(result),flush=True)
 return 0 if result['success'] else 2
if __name__=='__main__':raise SystemExit(main())
