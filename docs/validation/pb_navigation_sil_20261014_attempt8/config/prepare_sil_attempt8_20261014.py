from pathlib import Path
import hashlib,json
root=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ref(p):return dict(path=str(p),sha256=sha(p))
cfg=json.loads((root/'artifacts/pb-navigation-sil-config-20261014-03.json').read_bytes())
lio=root/'artifacts/pb2025-lio-tf-source-20261014-05-02'
post=json.loads((lio/'POST_BUILD_AUDIT.json').read_bytes())
build=json.loads((lio/'BUILD_RESULT.json').read_bytes())
assert post['passed'] and post['compiler_group_reaped'] and not post['remaining_build_members']
assert post['only_main_source_changed'] and post['source_unchanged'] and post['original_04_binary_unchanged']
assert build['returncode']==0 and build['passed'] and build['compiler_driver_reaped']
controller=root/'artifacts/pb-controller-diag-build-20261014-01'
ctrl=json.loads((controller/'BINARY_AUDIT.json').read_bytes())
assert ctrl['record']['load']['exit_code']==0 and ctrl['record']['ldd']['exit_code']==0
assert all(ctrl['old_reports_unchanged'].values())
new_lio=post['new_binary_path'];new_lio_prefix=str(Path(new_lio).parents[2])
new_ctrl=ctrl['record']['path'];new_ctrl_prefix=ctrl['record']['prefix']
old_lio_prefix=str(Path(cfg['assets']['point_lio']['path']).parents[2])
old_ctrl_prefix=str(Path(cfg['libraries']['pb_controller']['path']).parents[1])
cfg['install_prefixes']=[{old_lio_prefix:new_lio_prefix,old_ctrl_prefix:new_ctrl_prefix}.get(p,p) for p in cfg['install_prefixes']]
cfg['assets']['point_lio']=dict(path=new_lio,sha256=sha(new_lio))
assert cfg['assets']['point_lio']['sha256']==post['new_binary_sha256']
cfg['libraries']['pb_controller']=dict(path=new_ctrl,sha256=sha(new_ctrl))
assert cfg['libraries']['pb_controller']['sha256']==ctrl['record']['sha256']
cfg['generation_config']=ref(lio/'GENERATION_CONFIG.json')
for key,name in [('lio_source','OVERLAY_MANIFEST.json'),('lio_elf','BINARY_AUDIT.json'),('lio_build','BUILD_RESULT.json'),('lio_post_build','POST_BUILD_AUDIT.json'),('tf_reuse','REUSED_TF_SOURCE_PROOF.json'),('lio_build_compat','DERIVED_BUILD_COMPAT.json')]:cfg['provenance'][key]=ref(lio/name)
cfg['provenance']['lio_dispatch_symbols']=ref(lio/'DISPATCH_SYMBOL_AUDIT.json')
cfg['provenance'].pop('controller_resume')
cfg['provenance']['controller_source']=ref(root/'artifacts/pb-controller-diag-source-20261014-01/SOURCE_IDENTITY.json')
cfg['provenance']['controller_build']=ref(controller/'RESULT.json')
cfg['provenance']['controller_elf']=ref(controller/'BINARY_AUDIT.json')
for record in [cfg['generation_config'],cfg['environment'],*cfg['assets'].values(),*cfg['libraries'].values(),*cfg['provenance'].values()]:assert sha(record['path'])==record['sha256']
out=root/'artifacts/pb-navigation-sil-config-20261014-04.json'
assert not out.exists()
out.write_text(json.dumps(cfg,indent=2)+'\n',encoding='utf8')
print(json.dumps(dict(config=ref(out),new_lio=cfg['assets']['point_lio'],new_controller=cfg['libraries']['pb_controller'])))
