"""Explicit second docs-only clarification; preserve first revision originals."""
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'artifacts/prepared-bgr-postcheck-docs-20261014-02'
PREVIOUS=ROOT/'artifacts/prepared-bgr-postcheck-docs-20261014'
qa=ROOT/'artifacts/quality-20261014-prepared-bgr-frozen-02/manifest.json'
checked=json.loads(qa.read_bytes())['source_files_sha256']
def sha(raw):return hashlib.sha256(raw).hexdigest()
names=('docs/IMPLEMENTATION_PROGRESS.md','docs/WSL_NATIVE_TRANSPORT.md')
current={name:(ROOT/name).read_bytes() for name in names}
transport=current[names[1]].decode('utf8')
old='Windows私有工厂只对同一份不可变BGR计算一次SHA；审核的私有配对receipt绑定same bytes对象、image字段、robot/episode/frame、曝光/control/deadline、校准与capture-own，符合才免重复host SHA。错配/普通输入fallback仍完整hash；Linux SHA始终保留。receipt只认证该配对，不封印全部sensor或control authority，后续lease/epoch/原80ms wall+sim预算和150ms SDK各消费阶段仍重检。'
new='Windows私有工厂只对同一份不可变BGR计算一次SHA；审核的私有配对receipt绑定same bytes对象、image字段、episode/frame、曝光/control/deadline、校准与capture-own四vectors（joint_positions/joint_velocities/base_odom_xyyaw/base_odom_vxyw），符合才免重复host SHA。robot/消费者/generation/binding由上游snapshot ingress和owned out path负责，不是receipt自身字段。有receipt却错配直接reject/STOP；无receipt的legacy/普通入口才完整host hash，不fallback接受错误proof。Linux SHA始终保留。receipt只认证该配对，不封印全部sensor或control authority，后续lease/epoch/原80ms wall+sim预算和150ms SDK各消费阶段仍重检。'
assert old in transport;transport=transport.replace(old,new)
progress=current[names[0]].decode('utf8')
old='actual3之后补启动前validation/慢file-open后的共享cancel、STOP和原deadline重检；此后到达的取消交owned cleanup处理，不声称消除所有原子竞态。'
new='actual3已有validation前/后guard与WORKER phase；其后仅补最终Popen前慢file-open后的共享cancel、STOP和原deadline重检，以及更严格tmpfs proof。此后到达的取消交owned cleanup处理，不声称消除所有原子竞态；新最后guard未重跑live。'
assert old in progress;progress=progress.replace(old,new)
progress=progress.replace('后继启动guard只有专测/资源probe','后继最终Popen guard只有专测/资源probe')
OUT.mkdir(exist_ok=False)
rows=[]
for name,text in zip(names,(progress,transport)):
    original=(PREVIOUS/(Path(name).stem+'.before.md')).read_bytes();assert sha(original)==checked[name]
    (OUT/(Path(name).stem+'.before.md')).write_bytes(original)
    raw=text.encode('utf8');(ROOT/name).write_bytes(raw);(OUT/(Path(name).stem+'.after.md')).write_bytes(raw)
    rows.append({'path':name,'checked_before_sha256':checked[name],
        'revised_from_first_after_sha256':sha(current[name]),'final_after_sha256':sha(raw)})
assert all(sha((ROOT/name).read_bytes())==digest for name,digest in checked.items() if name not in names)
(OUT/'RESULT.json').write_text(json.dumps({'schema':'polar.evidence.postcheck-docs-only.v1','revision':2,
 'postcheck_changed_files':rows,'all_other_checked_files_unchanged':True,'checked_map_sha256':sha(qa.read_bytes()),
 'scope':'Only exact receipt/guard wording in two docs; first revision originals retained; no execution changes or retest',
 'final_whole_repository_equals_QA_map':False,'low_impact_docs_not_retested':True},indent=2)+'\n',encoding='utf8')
print(json.dumps({'revision':2,'changed_docs':names,'other_checked_files_unchanged':True}))
