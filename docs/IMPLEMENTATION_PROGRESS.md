# 按计划实施的进度与证据

2026-10-13（UTC+8）。按用户指定的父目录 PROJECT_PLAN.md 推进，源码工作分支为
work/plan-t01-t03，开发起点 1fdcd249be761100076670bb863c14357e8c62ed。
历史 cf6a6e4 证据、原帧、原模型及失败实验均保留。当前无 M0–M5 完整签收。

| 任务 | 当前状态与实际进展 | 尚待完成 |
| --- | --- | --- |
| T01 | 进行中：RobotIO 草案、R01–R12/A01–A15 追踪、live/offline 独立预设及可执行校验 | 最终目标机、负责人、标定、规则和指标冻结；预设仍 draft |
| T02 | 进行中：原失败复现；独立图像 contour-v3 修复，完整 T2 新构建成功 | 静态 OFFLINE24 跟踪/执行与实际清理已过；模型漏检、移动目标与 live 门禁仍未关闭 |
| T03 | 局部修复验证：raw/JPEG 分离、高精度时钟、原期限复查、显式sealed像素早发布、C编码及退出后独立像素审计；第12轮5000实际步/RTF0.9977、148raw全部80ms内 | 首native等41.232ms仍超时、0返回/0执行；完整默认部署/live+GUI、更多视角/完整比赛/长期负载仍缺，旧回退根因未完整关闭 |
| T04 | 进行中：固定原客户端加显式哈希补丁；282 项实际 Qt 回归；HTTP/相机/人工控制与实际 offscreen Qt 已过 | 新自有 T2 完整链、可见桌面交互、云台/实体弹丸全链 |
| T05 | 待推进：已有 scoped roster，native 支持仍限 stationary red_sentry | 角色/队伍/状态硬编码、移动与多车 native |
| T06 | 部分基础：独立正/负图像、故障安全与期限测试；保留全部失败和来源 | 系统运动/遮挡/丢失/射击/断线闭环矩阵与冻结验收 |
| T07 | 部分基础：RobotIO与JSON registry；可选ROS2信封桥，Lyrical/Fast DDS真实1项通过、身份echo与清理已测；JSONL同源QPC及排队后期限已修 | host2s startup/80ms物理ROS联调、标准ROS传感器消息、Nav2/自家节点适配、Windows↔WSL桥、两套完整独立实现 |
| T08 | 未完整实现：当前解析式简化车辆 | 真实车辆资产/动力学/轮腿策略；来源许可与策略复现 |
| T09 | 未完整实现：当前 ideal own odometry 与 64 rays 显式保留限制 | MID360/IMU/编码器包、自主定位建图、关闭理想定位审计 |
| T10 | 已有版本化 2026 RMUL 子集，未完整验收 | 官方规则逐条测试、资产许可和适用性 |
| T11 | 图像修复局部证据，已有源尺寸装甲和弹丸实现 | 真实装甲光学/物理标定、实体弹丸命中/热量/伤害完整证据 |
| T12 | 未验收 | 六车自有算法完整 3v3；旧算法/像素代打不计通过 |
| T13 | 本地局部修复：显式 role/robot/audit admission、state/frame 白名单、撤权和跨 scope 拒绝、客户端兼容 | 两物理电脑 LAN、多人冲突/断线及完整可见 GUI 验收 |
| T14 | 未验收 | 14 车完整 7v7、资源与实时性能 |
| T15 | 已有局部事件账本、哈希和帧证据 | 整场日志/复演/视频与关键事件、终局一致性 |
| T16 | 本机 Windows 仿真/Qt 与 WSL Linux 两次 clean native build；LF/UTF-8/socket/路径修复 | Windows native、干净第二电脑和可复现发布包 |
| T17 | 进行中：统一质量入口、明确测试范围、源提取/后续修改哈希分离；WSL 传输/私有像素/原始证据安全回归 | 本轮冻结质量记录见下文；许可/发布门禁尚未完成 |
| T18 | 未启动真实硬件 | 先完成 SIL 与 HIL 安全方案；真实车辆专项授权仍需要 |

| 里程碑 | 状态 | 原因 |
| --- | --- | --- |
| M0 冻结基线 | 未完成 | T01 draft 和未决指标尚未冻结 |
| M1 自有真实闭环 | 进行中 | 图像修复/物理性能/客户端权限已有局部实测，完整 realtime 链尚未验收 |
| M2 通用可替换 | 未完成 | T07–T11 与两机 LAN/第二实现仍缺完整证据 |
| M3 完整 3v3 | 未完成 | 六车自有完整比赛、整场复演与换机未验收 |
| M4 完整 7v7 发布 | 未完成 | 14 车、Windows native、发布许可/包未验收 |
| M5 真实车辆 HIL | 未启动 | 依赖前置 SIL 及专项硬件授权 |

## 最新代码与证据：ROS2及实时入口修复

[ROS2基础桥](ROS2_BRIDGE.md) 已新增本地预注册的 navigation/aim ID和严格JSON信封；
官方Lyrical rclpy10.0.11/FastDDS在Ubuntu26.04 WSL实际通过，bridge退出0、peer/thread/context清理完成。
[永久证据](validation/ros2_dds_bridge_20261013/README.md)保留两个依赖失败和第三次实际成功，
97ROS deb+11Ubuntu依赖只解压到owned prefix并核验官方签名/SHA。它使用明确DTO/零速度fixture；
不证明host启动时窗、真实导航、自瞄、物理SIL、Nav2、TF、点云、LAN或硬件。
Windows服务到WSL ROS的专用监督器尚未提供，不能把Linux注册路径直接视为Windows部署完成。

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
聊天每30分钟自动检查继续已授权开发；仅实质进展/失败/完成/需用户输入通知。
不合并主分支、不推送公开发布、不训练模型、不启动真实硬件测试。

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
