import copy,hashlib,json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
linux='/mnt/c/Users/lulu/Desktop/claude/polarsimulation/polar-rm-simulator/'
sha=lambda path:hashlib.sha256(Path(path).read_bytes()).hexdigest()
cfg=copy.deepcopy(json.loads((root/'artifacts/pb-navigation-sil-config-20261014-02.json').read_bytes()))
def ref(relative):return dict(path=linux+relative,sha256=sha(root/relative))
cfg['environment']=ref('artifacts/pb-humble-ext4-runtime-20261014/ENVIRONMENT_COMPAT_FINAL.json')
cfg['generation_config']=ref('artifacts/pb2025-lio-tf-source-20261014-04/GENERATION_CONFIG.json')
cfg['install_prefixes']=[p.replace('lio_tf_build_20261013_02/install/point_lio','lio_tf_build_20261014_04/install/point_lio') for p in cfg['install_prefixes']]
cfg['assets']['point_lio']=dict(path='/root/polar-navigation-humble-e05eb08e/lio_tf_build_20261014_04/install/point_lio/lib/point_lio/pointlio_mapping',
    sha256='ff6e3bde78b74edde2875984a3dc8687a6b8a65bfc172e52dbbb74630794005b')
old=linux+'artifacts/pb2025-humble-environment-20261013/prefix'
new='/root/polar-humble-ext4-20261014-01/prefix'
for label in ('slam_toolbox','planner_server','controller_server'):
    cfg['assets'][label]['path']=cfg['assets'][label]['path'].replace(old,new)
for label,name in [('lio_source','OVERLAY_MANIFEST.json'),('lio_elf','BINARY_AUDIT.json'),
                   ('lio_build','BUILD_RESULT.json'),('lio_post_build','POST_BUILD_AUDIT.json'),
                   ('tf_reuse','REUSED_TF_SOURCE_PROOF.json')]:
    cfg['provenance'][label]=ref('artifacts/pb2025-lio-tf-source-20261014-04/'+name)
for label,name in [('ext4_copy','MIGRATION_RESULT.json'),('ext4_finalization','FINALIZATION_RESULT.json'),
                   ('ext4_original_provenance','ORIGINAL_PROVENANCE_REFERENCE.json')]:
    cfg['provenance'][label]=ref('artifacts/pb-humble-ext4-runtime-20261014/'+name)
out=root/'artifacts/pb-navigation-sil-config-20261014-03.json'
with out.open('x',encoding='utf-8',newline='\n') as f:json.dump(cfg,f,indent=2);f.write('\n')
print(out.name,sha(out))
