"""Create final candidate-04 generation references, without executing launch."""
import ast
import copy
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
OLD=HERE.parent/'pb2025-lio-tf-source-20261013-02'
WORK=Path('/root/polar-navigation-humble-e05eb08e/lio_tf_build_20261014_05_02')
OLD_WORK=Path('/root/polar-navigation-humble-e05eb08e/lio_tf_build_20261013_02')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    out=HERE/'GENERATION_CONFIG.json'
    if out.exists():raise RuntimeError('generation output must be fresh')
    if not json.loads((HERE/'BUILD_RESULT.json').read_text())['passed']:raise RuntimeError('actual build required')
    if not json.loads((HERE/'POST_BUILD_AUDIT.json').read_text())['passed']:raise RuntimeError('actual post-build audit required')
    prior=json.loads((OLD/'GENERATION_CONFIG.json').read_text())
    keys=('package','executable','namespace','parameters')
    nodes=[]
    for call in ast.walk(ast.parse((HERE/'owned_lio.launch.py').read_text())):
        if isinstance(call,ast.Call) and isinstance(call.func,ast.Name) and call.func.id=='Node':
            nodes.append({kw.arg:ast.literal_eval(kw.value) for kw in call.keywords if kw.arg in keys})
    if nodes!=prior['nodes']:raise RuntimeError('actual launch parameters differ from reviewed original config')
    result=copy.deepcopy(prior)
    result.update(nodes=nodes,build_workspace=str(WORK),
                  install_prefixes=[str(WORK/'install/point_lio'),str(OLD_WORK/'install/loam_interface'),str(OLD_WORK/'install/sensor_scan_generation')],
                  source_overlay=str(HERE),source_manifest_path=str(HERE/'OVERLAY_MANIFEST.json'),
                  source_manifest_sha256=sha(HERE/'OVERLAY_MANIFEST.json'),
                  launch_path=str(HERE/'owned_lio.launch.py'),launch_sha256=sha(HERE/'owned_lio.launch.py'),
                  build_result_sha256=sha(HERE/'BUILD_RESULT.json'),
                  binary_audit_sha256=sha(HERE/'BINARY_AUDIT.json'),
                  post_build_audit_sha256=sha(HERE/'POST_BUILD_AUDIT.json'),
                  reused_tf_source_proof_sha256=sha(HERE/'REUSED_TF_SOURCE_PROOF.json'),
                  original_config_sha256=sha(OLD/'GENERATION_CONFIG.json'),
                  node_build_workspaces=dict(point_lio=str(WORK),loam_interface=str(OLD_WORK),sensor_scan_generation=str(OLD_WORK)))
    out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(config=str(out),sha256=sha(out),install_prefixes=result['install_prefixes'])))
if __name__=='__main__':main()
