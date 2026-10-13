"""Generate a local runtime spec from an existing frozen 40f7 timing-v4 build.

No network, model download, or build is performed. Local paths stay out of Git.
"""
import argparse,hashlib,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--source-spec',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
s=json.loads(a.source_spec.read_text());root=a.source_spec.resolve().parent
if s.get('id')!='user_07pitch_rebuilt' or s.get('protocol_id')!='portable-rmcs-distance-dr-timing-v4':raise ValueError('Expected frozen candidate v4 spec')
for k in ('binary','executor_yaml','autoaim_config','model_share'):
 q=Path(s[k]);s[k]=str(q.resolve() if q.is_absolute() else (root/q).resolve())
for k in ('binary','executor_yaml','autoaim_config'):
 if hashlib.sha256(Path(s[k]).read_bytes()).hexdigest()!=s['sha256'][k]:raise ValueError('Hash mismatch: '+k)
if s['sha256']['binary']!='70ad294ff8be702804ebd1e3f98048d0a13b9e74894d8b28615886a83eda0fcb':raise ValueError('This match freezes the 40f7 actor binary')
s['source_spec_id']=s['id'];s['id']='repaired_observation_intercept_m038';s['frozen_build']={'binary_sha256':s['sha256']['binary']};s['source_commit']='40f7af130d076bcabab98613bd66745f81c7f643'
a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(s,indent=2)+'\n');print(a.out)
