"""Explicit docs-only change after frozen QA; save exact before/after and scope."""
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'artifacts/prepared-bgr-postcheck-docs-20261014'
manifest=json.loads((ROOT/'artifacts/quality-20261014-prepared-bgr-frozen-02/manifest.json').read_bytes())
assert manifest['source_unchanged_during_checks'] is True
checked=manifest['source_files_sha256']
def sha(raw):return hashlib.sha256(raw).hexdigest()
names=('docs/IMPLEMENTATION_PROGRESS.md','docs/WSL_NATIVE_TRANSPORT.md')
before={name:(ROOT/name).read_bytes() for name in names}
assert all(sha(raw)==checked[name] for name,raw in before.items())
OUT.mkdir(exist_ok=False)
for name,raw in before.items():(OUT/(Path(name).stem+'.before.md')).write_bytes(raw)
text=before[names[0]].decode('utf8');nl='\r\n' if '\r\n' in text else '\n'
rows=text.splitlines(keepends=True)
for i,line in enumerate(rows):
    if line.startswith('| T03 |'):
        rows[i]='| T03 | 局部修复验证：sealed私有像素、BGR/SHA配对复用、启动/退出证明和分母分离；最新prepared第3轮5000实际步/物理RTF.999953、148raw | 原ELF完整输入1732/1732，等待47.379ms仍超时，0返回/0消费；后继启动guard只有专测/资源probe，默认live、GUI/完整比赛仍未验收 |'+nl
    if line.startswith('| T17 |'):
        rows[i]='| T17 | 进行中：最新冻结质量1286passed/33明确skip/876subtests；原QA01旧spec门禁失败保留，显式42spec选择与源/修改归属分开 | 质量不替live/许可/发布门禁；QA后仅文档与永久证据增补，M0–M5仍未签收 |'+nl
text=''.join(rows)
addition='''
## prepared-BGR 本轮修复检查点（2026-10-14）

[独立永久记录](validation/native_prepared_bgr_20261014/README.md)保存三轮新失败、源码/构建/配置身份、专测与清理证明。原42ea570c…spec复用已有当前匹配的29TU clean checkpoint和同4d357…ELF/原模型，没有重新赋SHA或改旧manifest；旧a808…spec因portable/CMake输入漂移在第1轮startup前严格拒绝。

第2轮native启动失败，raw0/physics0/NNrequest0，没有Linux STARTUP/OWNED_CHILD/CLEANUP证明；本地Runtime clean不能当Linux整栈clean。另一6.352s资源-only startup probe与后续成功清理均不回填此旧缺口，启动失败根因仍开放。

第3轮actual3源/codec不变，5000steps/10sim：物理10.0004716s、RTF.999952842；run+cleanup10.0587424s、比率.994160065，分母独立。148raw在原80ms、1真实native请求/0响应/0消费、fire0；原ELF stdin1732/1732字节，等待47.378868ms后期限截断。单首请求factory5.2297ms、hostprep.1399ms（receipt.0184ms）不是纯NN或每帧统计，也不是同源配对改善。退出后实际像素审计、同run/boot/PID/PGID出生/回收、空组与tmpfs删除通过。

actual3之后补启动前validation/慢file-open后的共享cancel、STOP和原deadline重检；此后到达的取消交owned cleanup处理，不声称消除所有原子竞态。PRE_NATIVE_EXIT仅证明未尝试spawn且tmpfs_removed；与真正child reaped严格区分，缺证仍失败。原15s native setup/1.3s host资源收尾和80/150ms控制门限不扩大。harness未开始时duration=None，physics与run+cleanup分别记账。

后继focused06原日志95passed/21明确skip/76subtests；Linux14 tests/unit含STOP/SIGTERM/deadline file-setup；最终guard独立startup probe02准备4.315s、0NN/0physics且资源clean。它们不能给guard修补前actual3的179份执行源码重标最终SHA，也不证明最后版本实际live通过；未重复NN/GL。

统一QA01原件为1285passed/1failed/32skip/875subtests，默认旧a808初始化spec被严格builder门禁拒绝。QA02由显式POLAR_WSL_TEST_SPEC选择已有42spec，非自动fallback：1286passed/33明确skip/876subtests、6已有warnings，四阶段exit0、source_unchanged_during_checks=true；pytest118.64s，driver137.428s/reaped。QA后仅本进度说明、WSL传输说明和新永久证据增补，执行源码与DEVELOPMENT保持原已检验SHA；不声称新增文档/归档曾参与该QA。

已有生产导航单目标局部成功保持；旧导航seq67尾超时、原模型3.85m漏检、实时自瞄0响应/0消费、移动与开火、多车/完整比赛、两机LAN/第二实现、Windows native与HIL仍按T01–T18/M0–M5门禁未签收。保存帧2s等待或预加载模型不替实际live证据。
'''
(ROOT/names[0]).write_bytes((text+addition.replace('\n',nl)).encode('utf8'))
transport='''# Windows GPU 相机与 WSL 原生传输

本地显式实验入口使用Windows真实NVIDIA/MuJoCo原尺寸相机和Ubuntu中的完整自有T2/contour-v3 Linux ELF。最新[prepared-BGR检查点](validation/native_prepared_bgr_20261014/README.md)仍0实时native返回/0物理消费；Windows-native、可见Qt、LAN、M1及完整比赛均未验收。历史第1–12轮原包保持，原模型/94份恢复源码/PnP门限未改。

## 身份与两种传输

own_wsl_registry按同一份spec原SHA核验ELF/build/generated/config/model及原T2+contour复合身份，固定可信Ubuntu，严格/mnt/c↔C:映射/路径/reparse边界。全资产校验在注册/启动，不每control重算已加载模型。预加载只有原ELF实际read(0)等待才能ready，没有提前拍帧、推理或推进物理；首次同配置绑定接管，换代关闭重建，取消持久。

wsl_stdio_v1保留共享盘图像入口；58ms DrvFs读取中位数是独立离线文件系统诊断，不能与不同样本相减当纯NN。wsl_stdio_bgr_v2传有界头+恰好4,665,600真实BGR bytes，Linux再核验尺寸/SHA并写owned0700 tmpfs，只替原frame image.path，原标定/捕获own/曝光/control时间不变。有界actual_frames writer必须完整落盘并读回核验；队列满、SHA/IO错误、缺帧或存活线程均明确失败。

Windows私有工厂只对同一份不可变BGR计算一次SHA；审核的私有配对receipt绑定same bytes对象、image字段、robot/episode/frame、曝光/control/deadline、校准与capture-own，符合才免重复host SHA。错配/普通输入fallback仍完整hash；Linux SHA始终保留。receipt只认证该配对，不封印全部sensor或control authority，后续lease/epoch/原80ms wall+sim预算和150ms SDK各消费阶段仍重检。私有对象不进入JSON/HTTP/公共日志或未知adapter。普通JSON/旧frame/自定义行为仍走原严格校验。

取消在validation前/后、慢file-open后及Popen前重检共享flag/STOP/原deadline；之后到达cancel交owned cleanup，不绝对声称spawn竞态消失。WORKER/birth/run/spec身份与phase/启动失败原件保留。PRE_NATIVE_EXIT只能证明没有spawn尝试且tmpfs_removed，不把native_child_reaped=false改true；已spawn必须原PID/PGID/start/boot匹配、TERM/KILL/reap、空组与tmpfs删除，缺证明仍失败。杀wsl.exe不等于Linux回收；原15s setup/1.3s host资源预算与控制门限不扩大。

## 显式本地复现

本机匹配的已有clean checkpoint是42ea570c…spec，同4d357…ELF；目录名字original不替代其实际contour-v3身份。旧native-contour-v3-final-default-build/a808…记录仍原样保留，在当前portable/CMake输入下严格拒绝；不改旧hash、不自动fallback。公开读者须按当前构建脚本在自己的机器生成并核验本地spec，再显式选该路径，不能复制私有路径当发布包。

```powershell
.venv-sim/Scripts/python.exe tools/smoke_wsl_native_live.py --run --native-transport wsl_stdio_bgr_v2 --private-native-pixels --raw-base64-codec pybase64_1_5_1 --linux-native-spec artifacts/native-original-nav-checkpoint-build-20261013/operator_source.local.json --client-root external/polar-rm-client-state-review --out artifacts/wsl-native-live-fresh --seconds 10
$env:POLAR_TEST_WSL='1'
$env:POLAR_WSL_TEST_SPEC='C:/absolute/local/project/artifacts/native-original-nav-checkpoint-build-20261013/operator_source.local.json'
.venv-sim/Scripts/python.exe -m pytest rm_match/integrations/test_wsl_operator.py rm_match/integrations/test_wsl_operator_pipe.py -q
```

optional pybase64_1_5_1须预先安装并与已声明扩展身份匹配；不能缺失时静默替代。FOV/本地注册命令不由HTTP指定，out必须全新。六车、2ms、1440×1080、15总FPS、1view和原80/150ms保持。

## 原始测量范围

最新actual3源不变，5000steps/10sim；physics10.0004716s/RTF.999952842与run+cleanup10.0587424s/ratio.994160065分开。148raw、1请求、0结果/消费，原ELF完整stdin1732/1732字节和47.378868ms等待只证明交付/整包超时，不证明NN完成或纯NN时延。单首请求factory5.2297ms/hostprep.1399ms含receipt.0184ms不称每帧或配对性能改善；postclose实际BGR/RGB审计与本轮owned cleanup通过。

actual1是旧spec门禁拒绝；actual2启动失败/0physics/0NN且Linuxcleanup未证，后继probe/actual3不能补它。actual3之后的最终启动guard只有focused06/Linux14/资源probe02及QA02，不能重标旧actual3执行SHA或宣称final live已跑。没有开始时duration=None，setup/报告失败保存原异常与有限phase，不刷新旧时刻。历史[第12轮](validation/wsl_native_live_20261013_attempt12/README.md)及更早原件独立保留；离线保存帧、重复帧绕过NN、预加载和资源-only成功均非实时资格。M0–M5仍未完整签收。
'''
old_transport=before[names[1]].decode('utf8');transport_nl='\r\n' if '\r\n' in old_transport else '\n'
(ROOT/names[1]).write_bytes(transport.replace('\n',transport_nl).encode('utf8'))
rows=[]
for name in names:
    raw=(ROOT/name).read_bytes();(OUT/(Path(name).stem+'.after.md')).write_bytes(raw)
    rows.append({'path':name,'checked_before_sha256':checked[name],'current_after_sha256':sha(raw)})
unchanged={name:sha((ROOT/name).read_bytes()) for name in checked if name not in names}
differences={name:{'checked':checked[name],'current':digest} for name,digest in unchanged.items() if digest!=checked[name]}
assert not differences,'Unexpected checked file changed outside postcheck docs: '+str(list(differences))
(OUT/'RESULT.json').write_text(json.dumps({'schema':'polar.evidence.postcheck-docs-only.v1','postcheck_changed_files':rows,
 'all_other_checked_files_unchanged':True,'checked_map_sha256':sha((ROOT/'artifacts/quality-20261014-prepared-bgr-frozen-02/manifest.json').read_bytes()),
 'scope':'Only two docs after completed QA; new permanent archive untracked evidence is outside historical checked map; no execution source changes',
 'final_whole_repository_equals_QA_map':False,'low_impact_docs_not_retested':True},indent=2)+'\n',encoding='utf8')
print(json.dumps({'changed_docs':names,'other_checked_files_unchanged':True,'postQA_docs_only':True}))
