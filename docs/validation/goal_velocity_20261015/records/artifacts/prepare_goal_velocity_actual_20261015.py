"""Pin a fresh v2 stack without rewriting any previous config/build evidence."""
from pathlib import Path
import copy,hashlib,json
ROOT=Path(__file__).resolve().parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
linux=lambda p:'/mnt/c/'+p.resolve().relative_to(Path('C:/')).as_posix()
out=ROOT/'artifacts/goal-velocity-config-20261015-01';out.mkdir()
old=ROOT/'artifacts/pb-navigation-sil-config-20261014-04.json'
assert sha(old)=='affba380753b6b8eac9505098fd0bf9d8a4457a4ec2892c09c80fb3da62d5c26'
build_dir=ROOT/'artifacts/nav2-goal-controller-build-20261015-01'
build=json.loads((build_dir/'BUILD_RESULT.json').read_bytes())
source=build_dir/'src/SOURCE_IDENTITY.json';identity=json.loads(source.read_bytes())
assert build['passed'] and build['source_manifest_sha256']==sha(source)
assert identity['generator_sha256']==sha(ROOT/'tools/prepare_nav2_goal_controller_overlay.py')
assert identity['overlay_header_sha256']==sha(ROOT/'rm_match/integrations/pb_goal_controller_context.hpp')
assert identity['request_header_sha256']==sha(ROOT/'rm_match/integrations/pb_request_context.hpp')
value=json.loads(old.read_bytes());before=copy.deepcopy(value)
value.update(schema='polar.pb-stack-config.v2',controller_result_profile='follow_path_uuid_v2')
value['assets']['controller_server']=copy.deepcopy(build['executable'])
for name,p in [('goal_controller_source',source),('goal_controller_build',build_dir/'BUILD_RESULT.json')]:
    value['provenance'][name]=dict(path=linux(p),sha256=sha(p))
for group in ('assets','libraries'):
    for name,ref in before[group].items():
        if name!='controller_server':assert value[group][name]==ref
target=out/'STACK_CONFIG.json';target.write_bytes((json.dumps(value,indent=2)+'\n').encode())
(out/'CONFIG_PROOF.json').write_bytes((json.dumps(dict(original_path=str(old),original_sha256=sha(old),
 original_unchanged=True,new_path=str(target),new_sha256=sha(target),changed_asset='controller_server',
 remaining_ten_original_assets_unchanged=True,build_report_sha256=sha(build_dir/'BUILD_RESULT.json'),
 physical_or_ros_started=False),indent=2)+'\n').encode())
driver=(ROOT/'artifacts/run_goal_uuid_focus_20261015.py').read_text(encoding='utf8')
driver=driver.replace('goal-uuid-stack-focused-20261015-01','goal-uuid-stack-focused-20261015-02')
p=ROOT/'artifacts/run_goal_uuid_focus_20261015_02.py';assert not p.exists();p.write_bytes(driver.encode())
print(json.dumps(dict(config=str(target),sha256=sha(target))))
