# Qt 客户端通用组件接入

新的显式组合补丁支持按能力合同选择通用导航、决策/导航 pipeline，以及已有通用自瞄。
注册和显示不按队名分派。队伍仍需提供匹配协议的本地 wrapper；目录可选不代表算法或整场比赛已经通过。

## 第六份 aim v2 组合补丁（2026-10-15）

新安装推荐 [CLIENT_AIM_REFERENCE_PATCH_MANIFEST.json](../client_patches/CLIENT_AIM_REFERENCE_PATCH_MANIFEST.json)
对应的完整第六补丁。它包含第五版全部改动，另支持完整声明的 `camera_gimbal_v2` 与 source-base 惯性 yaw 参考；
这是自瞄接口版本，客户端仍用 Qt 6。原第五版及其真实手控/导航证据保持原身份。
严格能力选择、安装、显式 `--client-patch-manifest`、版本错配拒绝和范围见[自瞄兼容文档](AIM_PLUGIN_COMPATIBILITY.md#第六-qt-客户端显式选择-v2)。
`examples/coop_aim_reference_manual.json` 提供对应 root/manifest 的手控配置；算法 spec 仍须单独准备。
UI 能选择和绑定不表示第三方算法、移动云台或整场比赛已通过。

## 第五份相机顺序组合补丁（2026-10-15）

[CLIENT_CAMERA_ORDER_PATCH_MANIFEST.json](../client_patches/CLIENT_CAMERA_ORDER_PATCH_MANIFEST.json) 与
[robotio_camera_order_v1.patch](../client_patches/robotio_camera_order_v1.patch) 是从固定 `0cedf99b70b1beec99865b9980af6789e6c53d99`
完整安装的第五份补丁，SHA `fc0ce37f9ca30f8542da3a315e67db2d855df227c10746a637fba6cc2f20e4f1`。
包含先前通用组件、租约和 batch 修复，必须选全新干净基线 checkout；旧四份补丁、manifest 和副本保持原字节。

真实手控第二次失败记录显示：合法相机帧 4.064 秒，异步 HUD 状态 4.010 秒，相差 54 ms，
原 50 ms 对齐检查抛错并撤权。新补丁完整验证元数据、JPEG 和原 TTL 后，在最终锁内重检身份与顺序；
合法超前帧暂不安装，等待后续原状态。丢弃不刷新视频、序号、HUD、时间锚或有效期。
原 50 ms 对齐界、显示 TTL、算法图像 80 ms 和 SDK 150 ms 均不变；损坏、过期、倒序或身份错误仍拒绝。
解码期间的 watch/会话/episode 变更不能安装旧帧。

```powershell
.venv-sim/Scripts/python.exe tools/apply_client_patch.py --manifest client_patches/CLIENT_CAMERA_ORDER_PATCH_MANIFEST.json --client-root YOUR_FRESH_CLIENT_PATH --run
.venv-sim/Scripts/python.exe -m rm_match.deployment.coop_launcher --config examples/coop_camera_order_manual.json
```

第二条默认只生成本机手动启动计划；示例需要本机第五 review 副本，人工选择步兵、claim 和两次 F2。
30 模块实际 Qt offscreen 回归 496 passed / 363 subtests / 0 skipped，源不变且 owned tree/reader 回收。
实际原窗口手控 5 秒和 30 秒均通过：真实 HTTP 相机、Jello Manual、两 F2、普通 W/S 与鼠标事件、SDK 和 MuJoCo。
独立原窗口/租约/序号/值/expiry 回执审计无错误，86 / 479 批原指令全部消费；前进、后退和非零云台均生效。
显式 host/Qt CV4、CPython 1 ms 实读后还原，原清理预算内资源退出。
这些是离屏手控 SIL；没有队伍导航/决策/自瞄、ROS/NN、可见桌面、RTF、射击命中或完整比赛验收。
失败及通过原记录见[永久证据](validation/manual_camera_order_20261015/README.md)。

后继[同场导航验证](COOP_PLAYABLE_PATH.md)保持同一第五客户端字节：5秒及修复后的30秒，原手动步兵与
真实北极熊 Point-LIO/Nav2 哨兵同时物理消费，原窗口/SDK和原LIO来源审计均通过。
新增探针与并行owned退出用于验证，未改变原客户端补丁；中间reset期限失败单独保留。
这是离屏单目标协同SIL，没有比赛决策树、移动自瞄、自动火、可见桌面或完整3v3签收。

原窗口实际复现需全新输出目录与显式 `--run`，探针不会替换普通客户端输入或放宽护栏：

```powershell
.venv-sim/Scripts/python.exe tools/qa_qt_manual_sil.py --client-root external/polar-rm-client-camera-order-review --patch-manifest client_patches/CLIENT_CAMERA_ORDER_PATCH_MANIFEST.json --out artifacts/qt-manual-fresh --seconds 30 --max-wall-seconds 45 --host-opencv-threads 4 --host-python-switch-interval-ms 1 --run
```

## 第四份批量控制组合补丁（2026-10-15）

[CLIENT_ROBOTIO_BATCH_PATCH_MANIFEST.json](../client_patches/CLIENT_ROBOTIO_BATCH_PATCH_MANIFEST.json) 与
[robotio_control_batch_v1.patch](../client_patches/robotio_control_batch_v1.patch) 从相同固定基线完整应用，
patch SHA `bda801aeec7e0f1e6f34bc96708285eb90350880d1602df15a1f365d70a9e0f7`。
必须使用新的干净基线checkout，不能叠加到先前三个补丁；原三个checkout/patch/manifest逐字节保持。

新服务器明确协商版本1时，导航/自瞄授权与剩余手动云台/开火按[原子控制协议](CONTROL_BATCH_INTERFACE.md)一次发送。
缺少能力仍走原single路径，非法能力/部分ACK/迟到成员/重复JSON字段均拒绝，不重试或放宽150ms。
原window ACK后新采样、F2/own HUD/焦点、租约竞态修复和真正撤权均保持；测量batch实际RTT上界而不是削减旧预测。
29模块完整实际Qt offscreen回归484passed/347subtests/0skip，pytest21.72秒，owned child/reader全部退出且源不变；
另21项专项及17模块351passed/141subtests原记录保留。物理协议结果与算法/比赛资格另记进度。

```powershell
.venv-sim/Scripts/python.exe tools/apply_client_patch.py --manifest client_patches/CLIENT_ROBOTIO_BATCH_PATCH_MANIFEST.json --client-root YOUR_FRESH_CLIENT_PATH --run
.venv-sim/Scripts/python.exe -m rm_match.deployment.coop_launcher --config examples/coop_robotio_batch_protocol.json
```

第二条默认仅生成合成协议示例的启动计划，不证明实际队伍算法或比赛；本地示例选择独立batch review目录。

## 后继租约状态顺序补丁（2026-10-15）

[CLIENT_ROBOTIO_STATE_PATCH_MANIFEST.json](../client_patches/CLIENT_ROBOTIO_STATE_PATCH_MANIFEST.json) 与
[robotio_state_order_v1.patch](../client_patches/robotio_state_order_v1.patch) 是第三份独立组合补丁，
SHA `a5f3fccfeb7afd50807e464ca39e5c00f49c77648213872b909f54c6d085ee93`，仍从相同固定基线完整应用。
前两份补丁、manifest 与 checkout 保持原字节；安装时必须选全新基线 checkout，不能叠加。

该版本修复已确定复现的异步状态竞态：claim ACK 后，之前请求的完整旧 lease epoch 快照不能释放新租约，
且丢弃时不刷新任何 state/HUD/lease/window 时间锚。同 episode 的三个 channel epoch 必须完整、类型正确且全部低于 ACK；
混合、缺失、bool、当前 epoch 的 owner 不符及更高 epoch 真正撤权仍停止控制，原 session/watch/episode 护栏保留。
SDK claim 仍保持 disarmed，实际新 own HUD 和第二次 F2 才可激活。

```powershell
.venv-sim/Scripts/python.exe tools/apply_client_patch.py --manifest client_patches/CLIENT_ROBOTIO_STATE_PATCH_MANIFEST.json --client-root YOUR_FRESH_CLIENT_PATH --run
.venv-sim/Scripts/python.exe -m rm_match.deployment.coop_launcher --config examples/coop_robotio_state_protocol.json
```

第二条只是合成协议演示的启动计划；配置使用本机 `external/polar-rm-client-robotio-state-review`。
完整16模块实际 Qt offscreen 回归为330passed/103subtests/0skip，pytest11.94秒、owned driver12.4185秒，源不变且进程回收。
这仍是后端夹具回归；不能据此关闭物理、可见 GUI、队伍算法或完整比赛。
原窗口实际尝试另使用 `tools/qa_qt_platform_robotio.py`，默认 dry plan，必须指定新输出目录和 `--run`。
显式 `--host-opencv-threads 4 --host-python-switch-interval-ms 1` 只改变当前进程调度并核验/还原，不扩大80/150ms门限。
当前三次原窗口尝试均整体失败：第一次F2后撤权，原原因码不足以归因；第二次已过两F2、绑定和27非零物理步，
随后真实请求预算压力撤权，后续probe等待错误又导致晚清理/Job回收缺证。两次原文件和各自源码均保持，后继实验单独记账。
该并发补丁的纯 transport 复现不是第一次实际窗口失败的根因证明。
第三次使用上述新补丁与显式CV4/1ms，真实HTTP画面、原窗口watch/Jello选择、两次F2、绑定和全部原护栏就绪；
38次SDK激活、11个独立动作、477条receipt和159个非零物理消费步，原typed6/SDK150ms审计无错误。
GO后约2.424秒，原Handoff预测成本157ms超过150ms预算而撤权：实测最大window31ms、pulse32ms、control32ms，
仍严格保留预测与取消。这次护栏失效立即收尾，原1.5秒清理预算内所有owned Job、SDK/HTTP/相机线程退出；
整体exit2/source unchanged，不能报告原窗口全链通过。截图仅为原Qt offscreen内部画面，不是可见桌面验收。

## 安装固定客户端补丁

客户端固定基线是 `0cedf99b70b1beec99865b9980af6789e6c53d99`。
新 [CLIENT_ROBOTIO_PATCH_MANIFEST.json](../client_patches/CLIENT_ROBOTIO_PATCH_MANIFEST.json) 对应
[robotio_navigation_v1.patch](../client_patches/robotio_navigation_v1.patch)，SHA256 为
`594b8562ba88dadf2facb59a1bdaa3517c4be22bf7397b4512d97b07c942e9e3`。
它包含原 operator_state_v1 的全部修改，必须应用在该固定基线的全新、干净 checkout。
不要叠加到旧补丁目录；工具会拒绝 partial/混合状态。旧补丁、manifest 和旧客户端副本保留原字节。

从仿真仓库根目录执行，替换本机客户端路径：

```powershell
.venv-sim/Scripts/python.exe tools/apply_client_patch.py --manifest client_patches/CLIENT_ROBOTIO_PATCH_MANIFEST.json --client-root YOUR_FRESH_CLIENT_PATH
.venv-sim/Scripts/python.exe tools/apply_client_patch.py --manifest client_patches/CLIENT_ROBOTIO_PATCH_MANIFEST.json --client-root YOUR_FRESH_CLIENT_PATH --run
```

第一条检查，第二条显式应用；固定 HEAD、patch/source hash、tracked/staged 改动与新文件均严格验证。
本机验证副本位于 `external/polar-rm-client-robotio-review`，没有向客户端仓库提交；可交付修改是上述组合补丁。

## 目录与启动配置

独立导航必须完整声明 `pointcloud_imu_v1`、`velocity_body`、导航能力合同、本地注册、机器人/传感器范围和空 binding config。
pipeline 还需精确声明两组件 ID 和 `decision_intent_v1` 输入模式。未知能力、队伍自带可执行路径和非空 binding config 不进入 HTTP 控制请求。
pipeline 在客户端仍是 navigation motion 通道；自瞄独立使用 gimbal 通道。原 claim、人工 F2 激活、watch/focus、租约和 fire 护栏保留。
无 goal config 的通用导航隐藏旧 world-goal 输入；实际目标由已审核 wrapper 或 decision intent 提供。

`coop-launch.v1` 增加三个可选本地字段：

| 字段 | 用途 |
| --- | --- |
| `robotio_plugins_json` | 可信本地组件 graph；各组件 manifest 也在启动计划中冻结原字节 SHA |
| `prepare_robotio_plugins` | 严格布尔值；需要 graph，显式准备 owned WSL 资源 |
| `client_patch_manifest` | 选择已核验的组合补丁，缺省继续使用旧 operator_state_v1 |

配置、graph、组件和所选 manifest 在 launch、server worker 和实际 ready 后启动客户端前重检。
变更被拒绝，不通过读取新文件自动替换算法或扩大 admission。默认人工授权仍仅 red_infantry；
不自动绑定、发目标或开火。启动器只支持原 loopback 范围。

[coop_robotio_protocol.json](../examples/coop_robotio_protocol.json) 是低点频合成策略的协议演示配置，
需要上面的本机 review checkout 和 `.venv-client`。默认仅输出计划：

```powershell
.venv-sim/Scripts/python.exe -m rm_match.deployment.coop_launcher --config examples/coop_robotio_protocol.json
```

真实队伍接入须复制配置、替换 graph 为实际 wrapper 并核验环境，参考 [通用插件接口](UNIVERSAL_PLUGIN_INTERFACES.md)。
本轮没有实际启动该配置的完整可见 PlatformWindow，不能将 dry plan 写成可见客户端操作通过。

## 实际验证范围

[本轮永久证据](validation/client_robotio_20261015/README.md) 区分以下记录：

- 原 Qt 客户端真实 PySide6 offscreen 回归 286 passed、91 subtests、0 skipped，包括原 Jello 选择和 F2/租约护栏。
  后端为测试夹具，没有实际物理导航或工业相机。
- 新实际 offscreen QWidget/QComboBox/QPushButton，经客户端解析/计划、HTTP、原 v2 SDK 控制窗口和真实 MuJoCo：
  1750 物理步、26 个独立原 source action、3736 条 receipt、1247 个非零消费步骤，typed6/SDK150ms 审计 errors=[]。
  两个独立 stdlib decision/navigation 进程使用合成策略，点云为实际 ray/IMU、显式 1000 points/s；
  完整资源准备、reset、动作、取消和 owned tree/IO 回收分别保存。
- 首次物理尝试因 reset 开销消耗首帧原期限，整体失败并保持零运动。修复为成功 reset 后丢弃旧/排队采样，等待原身份的新采样；
  未延长门限、重标旧时刻或填入假动作。首次失败和后续通过均保存，不拼接。
- 新 launcher 选项专项为 mock 启动/身份/变更拒绝；实际物理 harness 不替它的完整可见启动验收。

实际协议物理复跑要求新输出目录、显式 `--run`：

```powershell
.venv-sim/Scripts/python.exe tools/qa_qt_robotio_protocol.py --out artifacts/qt-robotio-fresh --duration 3.5 --run
```

此 harness 使用实际 Qt 控件，但未运行原 PlatformWindow、工业相机、GL、原 F2/watch 全链、ROS/WSL 或队伍算法。
它不验收 RTF、SLAM、目标到达、NN、可见 GUI、自动火或 3v3。自动火仍为人工通道；决策 v1 定位/感知反馈仍 unavailable。
自家 T2 三次静态实时链和 PB 单目标导航的历史范围保持；PB/同济完整自瞄、移动/多车/整场比赛仍待独立验证。
