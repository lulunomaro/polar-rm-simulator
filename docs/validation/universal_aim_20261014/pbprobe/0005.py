"""Checked local PB peer entry; full failures retained, canonical protocol unchanged."""
import argparse,hashlib,json,os,sys,traceback
from pathlib import Path
def checked(path,sha):
 path=Path(path)
 if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('bootstrap source link')
 raw=path.read_bytes()
 if hashlib.sha256(raw).hexdigest()!=sha:raise ValueError('bootstrap source changed')
 return raw
def main():
 p=argparse.ArgumentParser();p.add_argument('--bootstrap-ref',required=True);p.add_argument('--bootstrap-sha256',required=True);p.add_argument('--peer-sha256',required=True)
 a=p.parse_args();checked(__file__,a.peer_sha256)
 spec=json.loads(checked(a.bootstrap_ref,a.bootstrap_sha256));engine=None;code=0
 sys.stdout.flush();protocol=os.fdopen(os.dup(sys.stdout.fileno()),'wb',buffering=0);os.dup2(sys.stderr.fileno(),sys.stdout.fileno())
 try:
  if spec['schema']!='polar.pb-aim-local-bootstrap.v1':raise ValueError('bootstrap schema')
  for path,sha in spec['installed_module_sha256'].items():checked(path,sha)
  sys.path[:0]=[spec['repo_root'],*spec['module_paths']]
  from rm_match.integrations.pb_aim_engine import PBAimEngine
  from rm_match.integrations.pb_aim_stack import load_stack
  from rm_match.integrations.aim_jsonl_peer import serve_aim_plugin
  stack=load_stack(spec['stack_ref']['path'],spec['stack_ref']['sha256'])
  engine=PBAimEngine(stack);engine.prepare()
  # Exactly the frozen canonical implementation. Factory actually completed;
  # prepare ACK is not HELLO, and reset still awaits three original-context ACKs.
  serve_aim_plugin(engine,sys.stdin.buffer,protocol)
 except BaseException:
  traceback.print_exc(file=sys.stderr);sys.stderr.flush();code=2
 finally:
  if engine is not None:
   try:engine.close()
   except BaseException:traceback.print_exc(file=sys.stderr);sys.stderr.flush();code=2
  protocol.close()
 return code
if __name__=='__main__':raise SystemExit(main())
