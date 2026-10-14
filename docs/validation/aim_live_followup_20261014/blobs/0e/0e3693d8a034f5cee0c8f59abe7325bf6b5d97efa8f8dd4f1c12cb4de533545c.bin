# 按计划实施的进度与证据

更新至 2026-10-14（UTC+8）。按用户指定的父目录 PROJECT_PLAN.md 推进，源码工作分支为
work/plan-t01-t03，开发起点 1fdcd249be761100076670bb863c14357e8c62ed。
历史 cf6a6e4 证据、原帧、原模型及失败实验均保留。当前无 M0–M5 完整签收。

| 任务 | 当前状态与实际进展 | 尚待完成 |
| --- | --- | --- |
| T01 | 进行中：RobotIO 草案、R01–R12/A01–A15 追踪、live/offline 独立预设及可执行校验 | 最终目标机、负责人、标定、规则和指标冻结；预设仍 draft |
| T02 | 进行中：原失败保留；contour-v3修复，完整T2新构建与静态OFFLINE24/三次live链通过 | 模型漏检、PnP精度矩阵、移动/丢失重捕获仍待完整验收 |
| T03 | 显式CPU4/CV4/pybase64/1ms/authority mask0x10配置三次静态live通过；正式入口RTF.9971029、107及时/97新帧物理消费、0fault/clean | 旧async02/stage/调度失败全部保留；默认profile、移动/多车、完整性能矩阵未验收；原80/150ms不变 |
| T04 | 进行中：固定原客户端加显式哈希补丁；282 项实际 Qt 回归；HTTP/相机/人工控制与实际 offscreen Qt 已过 | 新自有 T2 完整链、可见桌面交互、云台/实体弹丸全链 |
| T05 | 待推进：已有 scoped roster，native 支持仍限 stationary red_sentry | 角色/队伍/状态硬编码、移动与多车 native |
| T06 | 部分基础：独立正/负图像、故障安全与期限测试；保留全部失败和来源 | 系统运动/遮挡/丢失/射击/断线闭环矩阵与冻结验收 |
| T07 | 通用camera_gimbal_v1/原源关联/JSONL/ROS/WSL/Qt发现；T2静态live通过；同济原模型prepare/reset；PB七包build与三节点资源graph/reset/clean | PB首帧host序列化或部分WSL请求未完成，尚无图像计算；同济无图像；第二完整live、C板feedforward/固件、移动/多车/两机等未验收 |
| T08 | 未完整实现：当前解析式简化车辆 | 真实车辆资产/动力学/轮腿策略；来源许可与策略复现 |
| T09 | 局部SIL通过：导航profile实际3D ray/gyro/accelerometer、四线逐点ns且无ideal pose；Linux及Windows→WSL均有Point-LIO/Nav2真实消费；默认ideal odom/64rays限制仍保留 | MID360真实光学/动力学标定、编码器、定位精度/漂移/恢复、多场景与完整任务未验收 |
| T10 | 已有版本化 2026 RMUL 子集，未完整验收 | 官方规则逐条测试、资产许可和适用性 |
| T11 | 图像修复局部证据，已有源尺寸装甲和弹丸实现 | 真实装甲光学/物理标定、实体弹丸命中/热量/伤害完整证据 |
| T12 | 未验收 | 六车自有算法完整 3v3；旧算法/像素代打不计通过 |
| T13 | 本地局部修复：显式 role/robot/audit admission、state/frame 白名单、撤权和跨 scope 拒绝、客户端兼容；Operator与v2平台 HTTP拒绝响应/有界正文收尾修复 | 两物理电脑 LAN、多人冲突/断线及完整可见 GUI 验收 |
| T14 | 未验收 | 14 车完整 7v7、资源与实时性能 |
| T15 | 已有局部事件账本、哈希和帧证据 | 整场日志/复演/视频与关键事件、终局一致性 |
| T16 | 本机 Windows 仿真/Qt 与 WSL Linux 两次 clean native build；LF/UTF-8/socket/路径修复 | Windows native、干净第二电脑和可复现发布包 |
| T17 | followup02四步骤0/source unchanged：1745pass/40明确skip/1008subtests；修复前失败、源码归因、三次静态live/资源/构建独立归档 | 质量不替live/许可/发布；PB/Tongji图像链与移动/多车/比赛未过，M0–M5仍未签收 |
| T18 | 未启动真实硬件 | 先完成 SIL 与 HIL 安全方案；真实车辆专项授权仍需要 |

| 里程碑 | 状态 | 原因 |
| --- | --- | --- |
| M0 冻结基线 | 未完成 | T01 draft 和未决指标尚未冻结 |
| M1 自有真实闭环 | 进行中 | 自家T2显式配置静态实时链已通过；移动/重捕获/实体射击/可见客户端与完整回归未验收 |
| M2 通用可替换 | 未完成 | T07–T11 与两机 LAN/第二实现仍缺完整证据 |
| M3 完整 3v3 | 未完成 | 六车自有完整比赛、整场复演与换机未验收 |
| M4 完整 7v7 发布 | 未完成 | 14 车、Windows native、发布许可/包未验收 |
| M5 真实车辆 HIL | 未启动 | 依赖前置 SIL 及专项硬件授权 |

## 最新静态实时自瞄与通用层复测

新[逐次验证包](validation/aim_live_followup_20261014/README.md)保留所有原失败、修复前后、真实原图和完整来源。
自家T2完整原生检测/PnP/跟踪/控制链在本机静态场景连续三次通过 `live_static_chain`：

| 尝试 | 物理RTF | 及时结果 | 独立新帧实际关节消费 | 资格 |
| --- | --- | --- | --- | --- |
| lean-before06 | 0.9984405490 | 112 | 103 | 静态实时链通过 |
| lean-repeat07 | 0.9976797995 | 114 | 100 | 静态实时链通过 |
| formal-scheduling01 | 0.9971029121 | 107 | 97 | 正式参数入口静态实时链通过 |

六车场景、2ms物理步、1440×1080/15fps单相机、静止red_sentry单算法、原模型/CPU4 ELF与80/150ms保持。
它们显式使用host CV4、pybase64 1.5.1、CPython切换间隔1ms及Windows authority线程group0/mask0x10，
未加额外authority计时探针。正式入口实读生效值并finally恢复switch5ms和原mask4294967295；
没有证明该CPU是P核，没有改变系统电源、优先级或计时器。0adapterfault/0fire/全部owned资源clean。
迟到NN仍留在原帧并拒绝，pending不计及时推理/动作；这些结果不表示全部NN小于80ms、命中精度、
可见Qt桌面、移动/多车自瞄、实体射击、整场比赛或硬件通过。默认调度配置仍未取得相同资格。

本轮修复原tracker失锁时的 `[null,null,null]` 向量：仅tracking=false允许完整空三元组，active/partial-null仍拒绝；
保留真实无目标状态，不补角度。runtime先完成分离的消费metadata，再取实际消费时刻重查门限，receipt不再共享可变字典。
源槽收到已过原deadline的返回只保存原响应并返回无动作pending，不再记及时native_result；owned stop取消不再冒充算法fault。
WSL JSONL的STOP检查按本地5ms最佳努力调度，原Event取消即时检查，完整身份/有界清理不变；新增固定scalar IO清理证据。
实际两项无害Win→WSL进程树生命周期复测8.9329773s/exit0/reaped/原source不变，不是NN或实时控制验收。

PB三真实节点资源已启动，但首帧未通过。controlled尝试在host序列化时过期，完整请求只有prepare/reset；
新fast受控尝试显式CV4/pybase64/1ms后capture→public16.3977ms、act入口30.4881ms，原80ms仍queue.Empty。
Linux只收部分act字节：43chunks/2334917bytes（含prepare/reset）、complete_requests=2，无完整act、无SourceArmors/Target/compute。
故未取得该图像的MLP/PnP结果或云台动作；prepare4.0485265s/reset55.7953ms、原模型/source03保持、相机/全部节点clean、设置恢复。
离线保存DTO编码对照只证明相同wire/像素，不作为推理或实时改善因果证据。同济仍仅实际模型prepare/reset，无真实图像闭环。

最终QA followup02四步exit0/source unchanged，1745passed/40明确skip/1008subtests/6既有warnings；
driver159.0866653s/reaped，pytest129.71s。首轮QA因新增原提取测试未归因失败也保留，补显式源码变更记录后再运行；
原EXTRACTION基线不改。质量检查不替代上述live、第二实现、完整比赛、发布或M0–M5签收。

## 最新代码与证据：ROS2及实时入口修复

用户最新明确要求接入 [北极熊 pb2025_sentry_nav](https://gitee.com/SMBU-POLARBEAR/pb2025_sentry_nav)
哨兵导航，源码已锁定 cb97fb07 及其 Point-LIO/Omni PID gitlink，见 [来源审计](POLARBEAR_NAVIGATION_SOURCE.md)。
Ubuntu22.04/Humble 环境与新 owned workspace 分开验证，不修改旧坏 checkout 或启硬件driver。
新 schema 只传 sensor-local点/真实offset、实际 gyro/accelerometer与合法裁判状态，无qpos/ideal odom。
等待定位是独立无动作状态，保留同代算法实例；异常/进程超时、旧帧、变代、越权仍拒绝。
服务入口 `--pb-navigation-manifest` 为显式本地注册，不给HTTP选择命令。

[实际传感器证据](validation/navigation_sensors_20261013/README.md)：四线10s/5000步/99cloud/RTF0.9999635，
原输入时刻、源码hash和无回波处理均保留。它使用物理脚本激励，尚不是自家导航算法闭环。
PB原路径的ApproxTime重贴pose时间、missingTF单位回退和wall-time速度差分必须修复；
owned overlay 已修复这些边界，实际controller入口/结果与LIO扫描绑定同一不可变上下文；
不接裸Twist后补当前identity。真实LIO/TF/terrain与PB控制器/插件已在独立workspace编译成功。

[Humble实际DDS与构建记录](validation/pb_humble_sensors_20261013/README.md)：原JsonLineAdapter新进程
reset 0.806705s、act 0.051286s，9项真实DDS/清理检查通过；后续实际归档584点、51IMU
及独立clock/tf_static主题搬运通过。后两项不是当前物理deadline authority验证，原时刻未刷新。
这些DDS早期记录不是导航闭环；后述SIL8另有真实定位/规划/物理消费证据。默认T2另有29TU新clean build，
ELF仍4d357067…，诊断profile未替换默认自瞄。

用户已明确授权把最新成果提交并推送当前开发分支；不合并main，不发布release。

本轮 [冻结质量记录](validation/quality_pb_navigation_20261013/README.md)：1118passed、10skipped、
574subtests，实际camera35checks与preset/source/interface全部通过；871项source检查期间不变。
第一轮1117passed/1failed完整保留：测试误引旧builder spec被哈希门禁拒绝；第二轮显式选择
真正新默认构建，未改旧spec或放宽门禁。Point-LIO/loam/sensor三包实际build已过；
此质量记录早于下述实际SIL，不等于导航执行通过。PB插件原layers重名已仅修owned输出库/XML绑定，
原算法/class字节不变；旧加载失败保留。

[单代 PB 导航 SIL 证据](validation/pb_navigation_sil_20261014/README.md)按轮保存当前Windows工作区
源快照与Ubuntu22.04/Humble真实Linux运行结果。固定PB插件独立构建412.657s成功，控制器
同SHA对象resume23.838s成功；三ELF真实依赖解析/加载通过。原combined600s超时保留，
构建资源预算默认1800s、可选60–3600s，不改变任何SDK时窗。真实Nav2已配置Smac、PB PID和
IntensityVoxelLayer类；独立类probe编译180s超时也保留，不覆盖为通过。

SIL attempts1–6均未形成定位→规划→控制→物理消费闭环。attempt5实际30s/15000步，
RTF0.999315、543次原150ms SDK激活；子进程reset2.0448s超原2s持续故障，0ROS请求/定位/动作。
attempt6阶段文件证明reset ACK已flush：module→ACK1.370686s，ROS imports1.099678s、
node0.131157s、图发现约.000986s（counts[1,1,2,1]），不是图等待耗尽1s。
随后SDK lease_mismatch停止，3.472802s/1016步、0定位/地图/动作消费；最大物理停顿
40.717807→41.820299约1.102492s，已定位导航worker误import native图像模块及NumPy2/cv2 ABI警告，
该导入修复的独立回归与后续SIL7结果另记，旧失败保持。启动诊断只写bounded本地phase，不改sourcewall/数据/期限。
本轮Linux全栈试验不等于Windows↔WSL桥入口、可见GUI、完整导航任务或M2通过。

导航误import native/cv2已修为仅真实 native 实例进入图像模块；独立 runtime 81passed/52subtests，
Humble fresh process 证明 navigation/JSON slot 不尝试 vision import。统一质量入口
`artifacts/quality-20261014-navigation-startup-checkpoint/manifest.json`：1139passed、36skipped、625subtests，
状态为 checks_passed_not_milestone_acceptance。它是质量检查，不替代实际导航或完整比赛。

Point-LIO 04 新 owned workspace 真实构建约25.6分钟，ELF ff6e3bde78b74edde2875984a3dc8687a6b8a65bfc172e52dbbb74630794005b；
raw/context有界exact join与未配对过界清理保留原时间/身份，旧02/03未覆盖。
新owned ext4环境保存14,899文件、1,621目录、186链接与mode核验，原前缀/环境不变；
仅受信派生pth映射新路径。三fresh导入/真实消息serialize/六车模型0step通过，未init DDS或预热NN。
FINAL ENV SHA d60183ebf62d520c72eb20b84207fa4344d8f17183bb0df8eee92f97b7f981ee。

ext4下独立DDS fixture `artifacts/pb-humble-tfmessage-ext4-20261014-attempt2/dds/RESULT.json` 九checks全通过，
原2s reset实际.454714s、act.051592s，51IMU及原bytes/time/identity/staticTF通过且clean。
额外QoS wrapper exit2如实保留：图能确认TF RELIABLE/TRANSIENT_LOCAL、request RELIABLE/VOLATILE，
但本次history UNKNOWN/depth0，不能据其测量队列深度；source/单位配置KEEP_LAST、TF1/request8另记。
首旧env2.036241s reset失败与独立类probe180s compile失败都保留，不拼接为新成功。
这些DDS检查均非physics/LIO/Nav2闭环；SIL第七轮结果见下文，仍未通过。

[新 runtime 永久记录](validation/pb_navigation_runtime_20261014/README.md)保存89项原字节/SHA，包含ext4与SIL7分开的来源。
SIL7已结束：15000步/30s，RTF0.999506，293原请求、290LIO定位事件、58map；
Smac status4成功返回14-pose路径，FollowPath接受后status6 FailedProgress，0controller result、0有效motion消费。
整体未通过，source/assets不变且九组算法进程/runtime全部clean。Windows当前源与Linux真实栈范围仍分开，
这些局部算法成功不是Win↔WSL部署、完整哨兵任务或M2验收。

原身份请求→loc一致，但287/290定位到observer时已经看到后续请求；96–148ms到达延迟是observer诊断，
不能据此推断CPP callback顺序/重贴identity。新ControllerContext default-off metadata日志限256条，
记录真实begin/finish拒绝，不改单pending、pose匹配、原sim_window或50/150ms门禁；
实际FakeROS C++对照guard/output相同。新controller-only fresh构建195.130948s通过，
ELF d4539050e0959270080044ace965a525f7653b0ef0a1715b031a06d91e156dbd实际ldd/RTLD_NOW通过，旧02原字节保持。

有界dispatch实际DDS微夹具将同51个原stamp消息消费从spin_some100.102ms降至spin_all188.399µs；
此为synthetic DDS调度证据，不是SIL/物理传感器。Point-LIO05已独立编译与依赖/源审计通过，
ELF fd2b50c7a2d1993c80fc251f201126af6d3775a813851102108dfb65e521471f；新一轮SIL8结果另存，不重判旧运行。
[最新dispatch质量记录](validation/quality_navigation_dispatch_20261014/README.md)：1144passed、37明确skip、685subtests，
preset/source/interface通过且source_unchanged=true；本轮未重复camera，前轮35checks另存。

[SIL8永久记录](validation/pb_navigation_sil_20261014_attempt8/README.md)实际退出0：30s/15000步，
RTF0.9995295364，294原请求、292真实定位、59map；Smac14-pose/status4与FollowPath/status4成功，
18controller result、779非零物理消费步，原身份/传感器/SDK150ms/wall-sim期限审计errors=[]。
source unchanged，runtime clean join .013611s，九个算法组allreap/assets unchanged；fire_permission=false。
这是本机Linux Ubuntu22.04/Humble、red_sentry单车/单代/单目标的一次局部SIL通过，不签收M1/M2或完整任务。

目标为实际算法估计map pose沿map的x方向偏移1m、y保持不变；postrun qpos[1.434108,-.0204169,.0000558]只用于隔离评测，
不进入算法、不能据此称定位精度或所有导航场景通过。旧SIL7失败仍保留。
控制器bounded前256条diag：beginaccepted18、finishpublished18，nopending35、posenotlocalized26、
finishnorequest61、requestinstalled42、locaccepted28、loccontextmismatch13、locnopending15；
它只是达到上限的日志前缀，不代表后续全部callback。安全拒绝仍工作。

独立复核779条均关联原source→SDK ACK→物理消费，0adapter fault，capture age27.298–148.928ms未超过原150ms。
292定位逐字段/类型匹配原请求；observer到达延迟P50 5.532ms/P95 6.913ms/max10.614ms是接收代理测量。
C++186个采样区间的批量callback最大数25–50、dispatch最大1.206ms；spin_all1ms为非抢占预算，非CPU硬上限，采样不等于全量统计。
raw ROS的Reached the goal为旁证；完整path/goal TF未记录，14-pose和目标来源引用冻结工具结果，未由raw ROS独立重算。

复现使用本机生成的已核验ENV/stack config与freshout，不声明归档私有路径可跨机运行：

```sh
/path/to/verified-humble-venv/bin/python tools/qa_pb_navigation_sil.py \
  --environment /path/to/generated/ENVIRONMENT_COMPAT_FINAL.json \
  --stack-config /path/to/generated/pb-navigation-sil-config.json \
  --out artifacts/pb-navigation-sil-fresh --seconds 30 --diagnostics --run
```

本轮config04 SHA affba380753b6b8eac9505098fd0bf9d8a4457a4ec2892c09c80fb3da62d5c26，
FINALd601...、Point-LIO05 fd2b50c7...、诊断controller d4539050...与build/source/ELF引用完整冻结于RESULT/PLAN。
入口/构建依据见[PB桥说明](PB_NAVIGATION_BRIDGE.md)；Windows专用入口与实际验证见下节，第二机器、更多目标/障碍/恢复与定位精度仍待验证。
fullQA1144/37skip/685subtests为独立质量证据，不能扩大本次SIL范围。

## Windows 物理仿真 → owned WSL 自家导航

[专用接入说明](PB_WSL_NAVIGATION.md)与[永久证据](validation/pb_wsl_navigation_20261014/README.md)
新增受信本地 `--pb-wsl-navigation-manifest`、持久有界管道、原主机期限校验和Linux整栈收尾。
HTTP只选择已注册ID，不选择命令；准备先于backend/physics且不预热传感器数据，原reset2s/graph1s/ROS50ms保持。
服务显示独立namespace/Domain84；生产入口没有自动测试目标。后续独立外部动作客户端的局部验证见下节，完整行为树/任务仍未验收。

| Windows→WSL实测 | 实际证据与结论 |
| --- | --- |
| attempt1 | prepare7.349s；880step/12request/10LIO/0command；真实Humble UUID ndarray(uint8,16)被旧记录校验误拒，整体失败，九组资源回收但业务CLEANUP=false；旧字节保留 |
| attempt2 | UUID修复后Smac14/status4、FollowPath/status4；3808step/20result/326非零消费；seq67主机接收超原activation deadline，SDK退出是STOP后继，30s验证失败；resource/runtime全部clean |
| attempt3 | 15000step/30simsec/299request/297LIO/42result/553非零消费；Smac14/status4与FollowPath/status4，原身份/SDK150ms/消费期限审计errors=[]；source/assets/runtime/session全部clean |
| attempt4 | 再次15000step/30simsec/299request/297LIO/55result/514非零消费；Smac14/status4与FollowPath/status4，原期限与全部收尾通过；source/assets unchanged |

第3轮原RTF .980798实际含runtime.run内部 .58698s close，不作为纯物理RTF。
第4轮分开保存实际最后physics step：29.9995142s物理区间、RTF约1.0000；
run+cleanup30.5623169s、比率.981601，join .561446s/1.5s。指标分母和源字节均保留。
新增完整raw目标TF、14pose路径/原stamp、两个action UUID/接受/状态以及退出后estimatedTF，
不使用truth、idealodom、旧cmd重贴、不同domain时钟相减或放宽80/150ms。
独立只读复核3/4全部553/514个非零消费分别关联21/20个实际消费命令及两端SDK原窗口，
host capture age分别53.988–120.290ms/51.226–140.888ms；raw目标/路径/action原时刻和UUID核验通过。
两个单车/单代/单相对目标成功短测不关闭attempt2间歇超时根因、完整哨兵任务、定位精度、第二机器或比赛验收。

新增 bounded host/Linux scalar RPC phase账本与STOP共享盘耗时元数据（只在内存记录、收尾写盘），
用于后续定位尾延迟。修复 native WSL leader先退出时可能留下孙进程的owned-group回收，
真实Linux9项清理、8项stdio夹具与Windows source/spec回归分别标明范围；它们没有NN/硬件闭环资格。
当前M0–M5完整状态保持未签收，默认T2实时仍0返回/0消费；下一步继续完整外部任务、
导航异常与恢复矩阵、自瞄首帧80ms链、长期负载，所有旧失败保留。

本轮首统一质量检查1208passed/1failed/48skip/768subtests，未标通过，见
[质量与HTTP修复记录](validation/quality_wsl_navigation_20261014/README.md)。
失败是原Operator HTTP超大正文拒绝时Windows偶发RST，40真实loopback对照中20个延迟正文全部复现；
修复先送拒绝响应/FIN，再最多64KiB/100ms总预算弃正文，accepted limit仍4096，拒绝仍先neutral。
合法正文保留原2s、改为总deadline避免逐字续时；40同脚本真实对照全部413，25focused/31subtests通过。
这与导航attempt2未关闭的跨WSL超时是两个不同故障，不能把HTTP修复计作导航尾延迟根因关闭。

最终第二轮统一质量记录 `artifacts/quality-20261014-wsl-navigation-frozen-02`：
1216passed、48明确skip、776subtests（6条已有fixture collection warnings），preset/source/interface/pytest全部退出0，
source_unchanged_during_checks=true、checks_passed_not_milestone_acceptance。
原161未改源/29归属修改/1派生fixture核验通过；本轮未重复camera，前轮35checks另存，
实际Linux清理/stdio与Windows导航3/4范围分别按上述原件记录，不以条件skip计通过。
归档只追加验证字节和此最终说明，执行源码保持质量检查时的身份；M0–M5仍未完整签收。

## 生产 Gate + 独立外部 ROS 目标客户端

新记录见[生产接入证据](validation/pb_wsl_production_20261014/README.md)，与旧内部QA3/4原字节分别保存。
内部相对目标关闭（relative_test_goal=false），生产Gate仅在实际map/LIO/估计TF出现后激活原服务器。
独立owned客户端只查询GetState与真实代价地图/TF，再向原ComputePathToPose和FollowPath发送一个估计相对目标；
它不切换生命周期、不发布sensor或cmd_vel，也不输入truth。完整自家决策/行为树尚未验证。

| 生产实测 | 原结果与限定范围 |
| --- | --- |
| attempt1 | 657step/1.314sim秒、9request/7定位/0controller/0消费；Gate ACTIVE但Smac报Start pose is out of costmap，status6/empty，失败保留；算法与外部进程组实际已reap，业务失败不标clean通过 |
| attempt2 | 实际15000step/30sim秒、物理29.999280400s/RTF1.000023987；299request/297定位/59map/19controller/708非零消费，Smac15pose/status4、FollowPath/status4；source不变，runtime/Nav九组/外部client与supervisor清理通过 |
| attempt3 | 平台HTTP修复后，28项前置源码快照含server/client/admission；15000step/30sim秒、物理30.000017600s/RTF0.999999413；299request/297定位/59map/19controller/412非零消费，Smac15pose/status4、FollowPath/status4；source与全部资源清理通过 |

首轮没有HostTimeout：13次act RPC均完整，host本域P50 52.424ms/max53.749ms；这不能关闭旧内部QA第2轮seq67故障。
修复客户端读取原global_costmap/costmap_raw：保留原网格geometry/stamp/接收clock/dataSHA、实际估计TF/目标与cell索引，
两点必须可定位到同一份有效网格的半开边界内才发唯一规划请求。cost值不决定ready、不重试planner、不替换原寻路。
未保存整个网格原字节，SHA/cell代价仅作原记录关联，不宣称独立重算；元数据bounds可独立重算。

另修复status查询busy误停act、注册准备失败吞清理错误、pre-ready清理身份核验、激活线程与栈的收尾顺序、
并发stack.stop共享原deadline及有界阶段账本的收尾写盘。host/Linux均显式记录total/dropped/capacity；
complete只表明未截尾，不表明每RPC成功。实际物理时长与run+cleanup分开，长清理不能使提前停步通过30秒验收。
导航冻结专项原日志为71passed/8明确skip/105subtests；HTTP另有37passed/21subtests/0skip。最终统一质量以新归档manifest为准。
统一质量第一轮preset/source通过但interface_static失败：v2平台MAX16384拒绝正文时Windows偶发10053，尚未执行pytest。
实际TCP对照36case中24个延迟正文均丢失413；修复flush/FIN后最多64KiB/100ms弃正文，同36case全部完整413。
合法正文沿用原1秒并限定为总读取期限，timeout/truncated返回400且不dispatch/renew；原源码与失败均保存。
修改归属保持原提取SHA，仅更新开发SHA和说明；第三轮导航使用该新HTTP源码，不以第二轮证据重标。
原80ms图像、150ms控制、reset2s/graph1s/ROS50ms均未放宽；本轮无相机/NN/射击/训练/硬件。
T07/T09/T13/T16只有上述局部增量，T01–T18其余缺口和M0–M5状态保持表中结果；默认T2实时仍0返回/0消费。

[原host2s实测](validation/ros2_startup_20261013/README.md)：Lyrical module因清理PYTHONPATH缺rclpy，
固定bootstrap仍未在原2s内完成rclpy初始化；两次0观测/0动作且清理完成，不能把先前DDS通过推成host通过。

[首帧实际分解](validation/native_first_frame_20261013/README.md)：两个诊断profile均29TU clean build，
8fresh完整检测/PnP/跟踪与清理，原actual12帧410/422ms未改。create_request仅约0.05ms，
pure preallocation没有可信改善，未生产采纳；主要infer约23–24ms，首响应最大53–56ms。
这些是独立overlay的离线记录，原default/live失败保持，未以重复同帧回复或阶段P50相减声称实时通过。

[ROS2基础桥](ROS2_BRIDGE.md) 已新增本地预注册的 navigation/aim ID和严格JSON信封；
官方Lyrical rclpy10.0.11/FastDDS在Ubuntu26.04 WSL实际通过，bridge退出0、peer/thread/context清理完成。
[永久证据](validation/ros2_dds_bridge_20261013/README.md)保留两个依赖失败和第三次实际成功，
97ROS deb+11Ubuntu依赖只解压到owned prefix并核验官方签名/SHA。它使用明确DTO/零速度fixture；
不证明host启动时窗、真实导航、自瞄、物理SIL、Nav2、TF、点云、LAN或硬件。
上述通用Lyrical桥没有Windows专用监督器；本轮另提供受审的PB/Humble Windows监督器，两个入口与证据不能混用。

JSONL修复了Windows Python3.12的monotonic/QPC origin差异；注册接口可注入与runtime相同clock，
默认统一perf_counter；实际child测试证明不误过期，排队恢复后超过原deadline会关闭child/IO并拒绝。
私有native路径默认关闭，仅两种经过review的精确native类可读sealed实际RGB，不向custom/JSON/ROS发送内部对象。
公开observation.v2仍完整base64；lease/epoch/当前activation、stationary与wall/sim80ms、150ms窗口不变。
初始化耗尽帧预算时丢弃旧帧，下一新帧可继续；算法真实异常仍持续故障直到新绑定。

[第9轮](validation/wsl_native_live_20261013_attempt9/README.md)入口ValueError/零请求/RTF0.671失败保留；
[第10轮](validation/wsl_native_live_20261013_attempt10/README.md)交接修复后有真实请求，但RTF0.735与native超时保留。
显式camera-fast/pybase641.5.1只编码原字节；缺版本/C扩展明确失败，默认stdlib不变。
[第11轮](validation/wsl_native_live_20261013_attempt11/README.md)RTF0.99464/raw148全80ms，
仍因native超时而失败，记录诊断RGB SHA耗13.597ms。
[第12轮](validation/wsl_native_live_20261013_attempt12/README.md)将诊断RGB审计移到退出后，
原BGR/传输SHA同步保留；RTF0.997734、5000步/raw148全80ms、精确存档像素审计clean。
bridge预算剩54.128ms，Linux收图7.892/hash2.024/tmpfs写2.447ms，原ELF stdin1733/1733完整，
native等待41.232ms后仍超时。零native返回、零物理云台消费、fire0，不能称实时闭环通过。
PID698已reap、tmpfs移除、所有writer/thread清理、源/扩展hash不变；168项运行源字节和实际BGR均冻结。

[原保存图tmpfs离线诊断](validation/native_tmpfs_saved_compute_20261013/README.md)四个新原ELF进程首次真实检测/PnP/跟踪/control
为34.712–57.612ms（P50 36.569）；重复同packet的.604ms不是真实新推理。
不能用离线结果填补live空响应。下一项继续原native首推理/调度与部署性能；禁止相同配置盲重跑、提高门限或预热首推理。

本轮统一质量入口 `artifacts/quality-20261013-ros2-private-native-checkpoint/manifest.json`：
1060passed、7skipped、436subtests，实际camera35checks、preset/source/interface全部通过，
723项source在检查期间不变；status仍为checks_passed_not_milestone_acceptance。
真实WSL DDS另有1项通过，未把默认ROS专项skip、单位fixture和实时native失败相加称完整接入。
测试完成后的仅文档/报告归档变更单独记录；已测业务代码不变。
本地3ecd226普通Windows clone发现随机UUID归档长路径检出失败；修复仅缩短归档目录/索引，
41项实际记录字节/SHA完全不变，原路径保存在original_path。冻结质量目录记录此失败与后续换目录复核；未启用系统长路径绕过或删去证据。

下一轮可执行诊断：在独立overlay构建中测first native read/create_request/resize/infer/post/PnP/tracker，
原41.232ms是被期限截断的整包等待，不是纯NN耗时；原common_model.hpp已LATENCY。
优先验证将Tensor/create_infer_request的纯分配移到模型setup（不set假图、不infer、不热首帧）；
必要时独立比较实际生效的inference_num_threads=1/2/4与CPU pinning，保留原ELF/spec和原模型/算法/门限。
ROS下一小验收应直接验证host原2s reset限制，不能从8s的DDS测试推出已满足。

## 实测与证据范围

T03 当前开发机 i9-13900HX/RTX 5070 Ti Laptop、Windows、Python3.12.14、MuJoCo3.15：
同六车、2ms 物理步、1440×1080、15 总 FPS、一视角、10s 无 native 测量，
RTF 0.70962 → 0.99847；独立复测 RTF 0.99846，raw P95 25.287ms、P99 26.449ms、
最大 27.662ms，118 帧全部在 80ms 内，真实像素字节一致。
Display P95 32.201ms/14.61FPS；另一次启动最大181.63ms保留。15总FPS不等于候选25FPS。
这只是实时物理/图像证据，不能替代 native、完整比赛或7v7。见 [性能报告](RUNTIME_PERFORMANCE.md)。
旧中间 RTF0.2649/0.7164 及 cProfile 干扰包均保留，未覆盖或冒充严格 A/B。

T02 contour-v3：11 张未见独立真实 MuJoCo 图像，原模型有检测的7正例全部有效pose，
角点RMSE .134–.405px、位置误差1.7–28.7mm；3负例pose0，包括原误接受的单灯条遮挡。
第8正例原模型无检测，候选也无检测。保持模型/genre/confidence及原PnP门限，
DARK仅在实际像素支持唯一完整同色双灯条时恢复颜色；目标真值仅在 native 退出后做离线评分。
见 [图像修复报告](validation/pnp_contour_v3_20261013/README.md)。v1/v2与相机fixture错误失败均保留。

完整 contour-v3 native clean build：29个翻译单元syntax/compile/link通过；
新binary SHA256 4d3570674a7a150da0e86f64bbbd25adcfa8bb9e2731672ac6aeaa296cf92b42，
spec SHA256 28d051057118c62e36fd6c7fb7adc924819168335a01e164fcea440fcaebad8b，
复合源身份绑定原T2 tracker与新frontend；94个恢复native源文件不变。
这是build证据，完整OFFLINE24跟踪/控制链另测。
原重建 artifacts/native-build-2 binary 797e6ba7...仍供历史重现；首次GCC15缺标准头失败保留。

T13/客户端：本地显式凭据禁止匿名招生、operator提权审计与跨授权车辆操作；
state无全局位姿/其他输入，frame仅JPEG+静态标定+真实时钟，无own_qpos/own_odom。
actualHTTP攻击/控制/离线生命周期回归、三项真实MuJoCo QA已过。
客户端282项实际PySide6/Qt offscreen回归、67subtests、0skip；
artifacts/operator_admission_http_gl_qt_20261013_01 的16项检查通过，
实际QApplication/app.exec/QTimer、原renderer/QImage输出PNG，motion消费108物理步、
gimbal106步、12HTTPcommands、fire0、Qt退出0。
这是实际offscreen Qt+HTTP+GL，既不是可见桌面验收，也没有native算法绑定。
完整meta requirements的WebEngine大包曾timeout；恢复实际需要的Essentials/Addons/shiboken，
未把部分安装称完整requirements安装。

本机仿真基线pytest为680passed/5failed/2skipped/187subtests；失败保留。
部署/源组合/招生边界局部回归44passed、1个Windows symlink privilege skip。
最终全量结果以 fresh quality manifest 和日志为准，不把局部项数相加为总数。

## 当前可执行后续与复现

继续OFFLINE24实际T2 tracker→有效云台→物理消费/释放链与实时 native 因果账本；
保持原80ms图像门限/150ms控制窗口，不更新时间戳、不输入目标真值、不旧算法或像素代打。
所有构建/测试先检查运行状态，输出用fresh目录。source质量入口同时绑定tracked与新模块SHA。

    python tools/validate_acceptance.py
    python tools/validate_acceptance.py --require-frozen
    python tools/check_project.py --out artifacts/quality-new --camera

第二条当前draft返回2是预期保护。Linux/WSL离线EGL当前llvmpipe，不能冒充NVIDIA实时性能。
聊天按用户最新要求每2小时自动检查并继续已授权开发；仅实质进展/失败/完成/需用户输入通知。
不合并主分支、不发布release、不训练模型、不启动真实硬件测试；当前开发分支推送已获用户授权。

## 后续发现与修复记录

初次统一质量检查 artifacts/quality-20261013-checkpoint-01：configuration/source/193项合成接口通过，
全量752passed、1failed、3skipped、216subtests；未标通过。
失败为Windows venv launcher退出后真实解释器仍持有cwd。保存process-PID实测证明，
JSONL关闭现回收owned Windows进程树并join IO线程；20次实际oversize退出和立即目录清理全过。
同时修同一次JSON快照/源hash绑定、变更policy/spec/client身份拒绝、quality自身output误算source问题。
第二轮全量785passed/4skipped/216subtests与真实camera检查通过，但检测到并发更新源码，严格门禁正确返回source_changed_during_checks；最终冻结质量报告另存。

OFFLINE24 attempt2/3均保留：startup耗尽父5s初始绑定窗口；新增独立15s实际QApplication/cv2/numpy
preload-ready握手，不提前physics/capture/native，保持父5s、子3.5s与原80/150门限。
attempt3实际握手和session通过，但原client严格拒新离线scheduler metadata；已补严格4字段解析、
未知字段/私有嵌套拒绝，282actualQt/67subtests/0skip与fresh固定base apply/幂等验证通过。
新patch SHA256 91e3653df439289e25d64eb334f9c6f6a73e0c4aa8e3615ce968010e3b1860ee。

WSL隐藏GLFW经仅进程环境D3D12/NVIDIA可实际渲染；小图能力probe不计性能通过。
原配置10s实际测量 artifacts/wsl_runtime_d3d12_20261013_01：5000真实物理步、RTF0.99995，
但renderer初始化7.119s，只有3raw/JPEG帧，render/readback P50 .740s，曝光到raw P50 .820s/最大1.148s，
135丢帧，全部发布raw超过80ms。保留完整命令/env/结果hash，不在此配置伪称native实时通过。
Windows本地GPU相机25ms证据与WSL原生链的期限缺口是两种不同证据；需继续解决跨平台完整链。

## 最终静态链与当前冻结检查点

最终默认新构建使用已通过独立图像与完整静态链的 contour-v3；显式
--corner-refinement original 保留原失败重现。再次从零构建29syntax/29compile/link通过，
ELF同4d357067...，新spec SHA256 a808f11e8f8088ba89c2cf2a8e94d4bf18c386dc69d3d4114b9b2b40e57a3cdd。

新代码的 [aftercleanup完整静态链报告](validation/pnp_contour_v3_aftercleanup_chain_20261013/README.md)
通过：24actual exposures、13/13 pose/tracking/should_control，241次真正gimbal actuator消费，fire0；
原fire controller should_shoot有7/13为true，adapter fire_permission保持false，不能把两者混写。
原native PID1216已reap、returncode -15、两pipeclosed，worker已退出且instance释放；
shared shutdown join .01395s/1.5s，unfinished/lifecycleerrors=[]，runtime.error None。
运行前后10项实际源码hash完全一致。父/子startup时窗、80/150门限及原model/94native source均保持。

owned RMCS terminate→kill→finally streams、live/offline可信native取消、迟到Popen/reset防复活，
未知Python插件只使用总1.5s等待并明确unclean，避免假clean或卡住物理authority。
Windows专用140passed/22subtests与WSL实际12lifecycle checks通过。
本轮字节规范保护已冻结overlay/patch/报告的literal SHA；常规源LF规范后更新26项提取修改归属。
本地分支检查点 1dc500d / 3160522 已保存，工作区干净；新本地clone源门禁通过，42项冻结报告/工具/源码hash与客户端patch全部一致。它不等于第二物理电脑或公开发布。


冻结的最终质量入口 artifacts/quality-20261013-frozen-checkpoint/manifest.json：
checks_passed_not_milestone_acceptance；preset、26项归属源变更/未改原字节、193项合成接口、
全量787passed/4skipped/216subtests、实际camera35checks全部通过，运行期间source_unchanged=true。
相应draft --require-frozen仍应拒绝。当前局部问题的代码/测试/失败与复现均保存；
新默认PnP修复和静态OFFLINE链已验证，M1实时/完整比赛、M2–M5仍按上表继续推进。


Windows条件跳过的2项原尺寸EGL/lens投影用WSL实际EGL另跑，2passed（6.40s），
日志 artifacts/checkpoint-clone-egl-projection.log；SIGTERM-ignore另有POSIX实际12项回归，
Windows symlink权限skip保持显式，不为测试改系统权限。最后没有遗留构建或native运行。
下一项可执行M1工作是显式Windows GPU/持久WSL native传输与真实80/150ms全链测量；
现WSL单独GLFW/D3D12原尺寸相机不满足80ms，不能直接启动该配置当实时通过。

## 显式 Windows GPU / WSL native 开发检查点

本轮新增 [WSL 传输说明](WSL_NATIVE_TRANSPORT.md)，注册和启动校验同一 raw spec、ELF、
模型、配置、生成 main、原 94 源文件及 contour-v3 复合身份。模型初始化完成后只使用
实际 Linux `read(0)` readiness；没有先拍帧、推理或推进物理。换代、取消、启动失败、
blocked pipe 和超时均回收 owned 子进程，v2 同时回收专属 0700 tmpfs。
Windows GPU 相机与 Linux ELF 组合不等于 Windows 原生构建或可见桌面验收。

v1 共享盘路径和 v2 真实 BGR pipe 明确区分、没有自动回退。v2 只传同一实际不可变
4,665,600-byte BGR，Linux 校验 SHA 后写 tmpfs，保留曝光状态、标定与时间。
Windows 端图像改由独立有界线程写入逐帧文件/manifest 并读回 SHA；收尾必须写完已接受
图像，队列满或 IO 错误不能吞掉。公共 JSON 与第三方 adapter 不获得该私有 byte 入口。

修复的边界包括：先快照再严格校验同一元数据/像素；枚举值和字段类型拒伪造 Python
等值对象；实际原子 sensor packet 帧号去重；新帧发布可及时唤醒原生调度；每个执行阶段
仍按原曝光检查 wall/sim 双 80ms；原生结果和请求统一 Windows QPC 时钟。
私有像素凭据只在相机编码工厂产生，与原始 bytes、编码字符串对象、完整帧身份、
尺寸及曝光配对；伪造、JSON 往返或错配仍严格解码，不能携带到 HTTP/公共日志。
原 150ms SDK server window、静止 red_sentry 限制和 fire_permission=false 保持。

实时实验全部保留原文件与失败结论，见 [第七轮](validation/wsl_native_live_20261013/ATTEMPT7_TOKEN_ASYNC.md)
及同目录第一至六轮。固定六车、2ms、1440×1080、15总FPS、一视角：

| 实验 | 实际边界与结果 |
| --- | --- |
| v1 第1轮 | RTF0.997893，147raw；准备已耗尽80ms，native0返回/0执行 |
| v1 第2轮 | 实际运行后统计对字符串求百分位异常；只恢复已保存的startup/请求/清理，不虚构丢失RTF/raw数据 |
| v1 第3轮 | RTF0.992233，148raw；host准备期限失败，未进入bridge native_request |
| v2 第4轮 | 1,835,008/4,665,600 bytes接收后期限耗尽，无完整ELF输入 |
| v2 第5轮 | 3,211,264 bytes接收后期限耗尽，无完整ELF输入 |
| v2 第6轮 | 首次接收完整图像；接收/核验/写tmpfs14.35ms超剩余12.56ms，在ELF stdin前拒绝 |
| v2 第7轮 | RTF0.840138，149raw均≤37.94ms；准备15.73ms，Linux完整图像阶段16.75ms，generic control_timeout；native1请求/0返回/0执行；原图保存与reap/tmpfs清理均过 |
| v2 第8轮 | RTF0.961608，149raw均≤37.661ms；实际BGR完整，原ELF stdin1733/1733字节，仍超时0返回/0执行；source unchanged与证据/清理通过 |

第七轮旧报告未记录真正写入 ELF 的字节数，不能判断开始 NN 与否；新 worker 累计
实际 os.write 返回、完整 JSON+LF 长度、输入完成标记及等待原生结果时长。完整输入不等于
推理完成或控制通过。旧报告 native_identity 中 v1 标签有误，STARTUP/请求实际均为 v2；
新 v2 checked metadata 绑定两个 pipe 程序 SHA，旧报告原字节保留。

Linux 保存实际失败帧离线诊断中，四个 fresh 模型的第一真实响应 P50 84.87ms，包含
DrvFs 文件读取；独立文件读取 P50 58.46ms 是未配对测量，不能相减宣称纯 NN 时延。
重复同帧请求约3ms绕过新帧NN，不计吞吐或实时资格。无 native、同源码相机独立实际
诊断 RTF0.998367；编码工厂仅约多0.26ms/帧，不能单凭这些数字断定第七轮退化原因。
所有诊断都是相应范围的证据，T03/M1 实时完整链仍未签收，M0–M5 状态保持上表。

新的 [第八轮实际报告](validation/wsl_native_live_20261013_attempt8/README.md) 同时保存
16个关键执行源码确切快照、实际 BGR 无损压缩、完整字节交付/CPU/清理证据。
活跃故障绑定+SDK150ms独立Windows GPU诊断RTF0.9983966，说明它们不能充分解释旧退化。
静态能力查询消除重复 descriptor 深拷贝，公开副本隔离和每阶段权限/80ms/速度/epoch
检查保留；短paired FakeBackend step+demand P50 .4919→.4026ms，不等于实际RTF。
后续补上select返回后原期限重检：过期的已可读结果不得接受。实际无害子进程验证
完整输入但回复超时、短写、跨事务计数清零、过期可读拒绝与期限内通过；不称原NN通过。
保存帧工具已兼容v2异步逐帧文件，按唯一原请求帧号/SHA及严格manifest选择，拒绝
错图、歧义和路径变化；Windows11单位通过/1symlink权限skip，Linux12单位通过。
第八轮包的解压输入与离线复现步骤已保存，离线2s等待不写成实时80ms通过。
只读 Windows 库存未在已查标准目录找到编译器/OpenVINO，未安装或下载，非全盘搜索。

本轮统一入口（需独占实际 GL/native 测试窗口，先更新修改归属 SHA）：

```powershell
$env:POLAR_TEST_WSL='1'
.venv-sim/Scripts/python.exe tools/check_project.py --out artifacts/quality-20261013-wsl-frozen-checkpoint --camera
```

唯一计数与当前代码 SHA 见该目录 manifest、pytest.xml/log 和 camera 记录。只允许
各检查退出0且 source_unchanged_during_checks=true 时声明本地质量通过，不能据此关闭
M1或发布。按计划优先继续修复实际跨平台期限；下一次实验使用新目录，保持全部旧失败。

## prepared-BGR 本轮修复检查点（2026-10-14）

[独立永久记录](validation/native_prepared_bgr_20261014/README.md)保存三轮新失败、源码/构建/配置身份、专测与清理证明。原42ea570c…spec复用已有当前匹配的29TU clean checkpoint和同4d357…ELF/原模型，没有重新赋SHA或改旧manifest；旧a808…spec因portable/CMake输入漂移在第1轮startup前严格拒绝。

第2轮native启动失败，raw0/physics0/NNrequest0，没有Linux STARTUP/OWNED_CHILD/CLEANUP证明；本地Runtime clean不能当Linux整栈clean。另一6.352s资源-only startup probe与后续成功清理均不回填此旧缺口，启动失败根因仍开放。

第3轮actual3源/codec不变，5000steps/10sim：物理10.0004716s、RTF.999952842；run+cleanup10.0587424s、比率.994160065，分母独立。148raw在原80ms、1真实native请求/0响应/0消费、fire0；原ELF stdin1732/1732字节，等待47.378868ms后期限截断。单首请求factory5.2297ms、hostprep.1399ms（receipt.0184ms）不是纯NN或每帧统计，也不是同源配对改善。退出后实际像素审计、同run/boot/PID/PGID出生/回收、空组与tmpfs删除通过。

actual3已有validation前/后guard与WORKER phase；其后仅补最终Popen前慢file-open后的共享cancel、STOP和原deadline重检，以及更严格tmpfs proof。此后到达的取消交owned cleanup处理，不声称消除所有原子竞态；新最后guard未重跑live。PRE_NATIVE_EXIT仅证明未尝试spawn且tmpfs_removed；与真正child reaped严格区分，缺证仍失败。原15s native setup/1.3s host资源收尾和80/150ms控制门限不扩大。harness未开始时duration=None，physics与run+cleanup分别记账。

后继focused06原日志95passed/21明确skip/76subtests；Linux14 tests/unit含STOP/SIGTERM/deadline file-setup；最终guard独立startup probe02准备4.315s、0NN/0physics且资源clean。它们不能给guard修补前actual3的179份执行源码重标最终SHA，也不证明最后版本实际live通过；未重复NN/GL。

统一QA01原件为1285passed/1failed/32skip/875subtests，默认旧a808初始化spec被严格builder门禁拒绝。QA02由显式POLAR_WSL_TEST_SPEC选择已有42spec，非自动fallback：1286passed/33明确skip/876subtests、6已有warnings，四阶段exit0、source_unchanged_during_checks=true；pytest118.64s，driver137.428s/reaped。QA后仅本进度说明、WSL传输说明和新永久证据增补，执行源码与DEVELOPMENT保持原已检验SHA；不声称新增文档/归档曾参与该QA。

已有生产导航单目标局部成功保持；旧导航seq67尾超时、原模型3.85m漏检、实时自瞄0响应/0消费、移动与开火、多车/完整比赛、两机LAN/第二实现、Windows native与HIL仍按T01–T18/M0–M5门禁未签收。保存帧2s等待或预加载模型不替实际live证据。

## 模型实际属性与 JSONL 进程树修复（2026-10-14）

本轮[独立证据](validation/native_runtime_threads_json_20261014/README.md)区分诊断构建、零帧资源检查、保存帧离线响应、无害进程夹具和统一QA。原生产导航已有 Windows→WSL 点云/IMU→自家Point-LIO/SLAM/Smac/PID→物理底盘的30秒单目标局部通过记录；本轮未重跑导航或完整哨兵任务。

仅 first-frame-trace 诊断 overlay 增加真实 CompiledModel 属性查询；没有 set_property、暖推理或改变原94源/模型/ROI/生产配置。新独立29syntax/29TU clean build通过，原42生产spec保持严格匹配。实际零帧read(0) readiness后记录 CPU、16推理线程、1 stream、LATENCY、f32、pinning=true、ANY_CORE，OpenCV getNumThreads=32；0图像/0NN/0physics，owned组回收与tmpfs删除通过。它不是实时性能验收。

固定原失败帧8、曝光476000000ns/control486000000ns、BGR3951a597…的8fresh ABBAABBA离线诊断保留失败：默认4进程完整提交各1700bytes、14phase完整，首次真实回复61.720/37.697/38.116/37.881ms；2秒离线等待不能替80ms live。cv1四进程仅改OPENCV_FOR_THREADS_NUM=1，实际属性仍32，均在发送首packet前严格拒绝，0stdin/0NN；comparison_complete=false，没有有效线程对照或因果改善结论。所有8组reaped/empty且tmpfs删除、源不变。下一可执行方案是在独立诊断构建中显式调用cv::setNumThreads(1)，先测实际属性再对照，不把环境变量未生效的原因写成已证。

新worker只增加每事务stdout已读字节、select可读次数、原stdin完成后首次可读/读取时长、有界前缀长度与SHA及保留buffer长度，不记录原stdout前缀文本。select、读取和解析后仍重检原deadline；0读取不证明ELF从未写出。旧actual3缺这些字段仍未知，不能补填。实际Windows→WSL无害pipe29项通过；不等于原NN实时通过。

通用JSONL插件原Windows实际复现：leader退出且close返回成功，孙进程仍存活。修复使用执行前归属的Windows Job和Linux owned session，leader先退出仍清理后代；共享1.5秒资源预算涵盖生命周期锁/回收/IO join，原reset2秒和action原deadline不扩大。取消/Job assignment/句柄关闭/IO thread启动/归属检查失败保留明确unclean proof，未spawn与reaped分开；无法验证group时只对直接Popen尝试回收，不声称未知后代已消失。Windows after02原专测29passed/2Linuxskip/2subtests；CRLF→LF仅字节规范记录另存，最终LF源实际Linux02为20passed/11Windowsskip/2subtests，包括TERM-ignore孤儿孙进程和blocked pipe实际回收。原before/after01与错误标签ERRATA全部保留。

最终统一 artifacts/quality-20261014-runtime-threads-frozen-01 四阶段退出0，1324passed/35明确skip/930subtests/6已有warnings，pytest108.77s、driver128.635s/reaped、source_unchanged_during_checks=true；显式POLAR_TEST_WSL=1/POLAR_WSL_TEST_SPEC=原42spec。QA后只有本文、WSL说明和新永久包增补，不称这些文档或归档参与此前QA。当前最新真实live自瞄仍1请求/0回复/0消费/fire0；导航与自瞄同时实时、自动开火、完整巡逻/比赛及M0–M5仍未签收。
