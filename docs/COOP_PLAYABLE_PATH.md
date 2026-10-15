# 3v3 验证场景：当前入口与缺口

用户最新要求以 **通用导航、决策、自瞄协议及可配置适配** 为主目标。不同队伍的程序通过开放组件接口接入；
北极熊、T2、同济是接入示例，不构成允许队伍或实现的名单。接口、能力协商与当前限制见
[通用插件接口](UNIVERSAL_PLUGIN_INTERFACES.md)。

本页的“手控步兵 + 北极熊哨兵 + 传统决策树 3v3”是验证该通用能力的具体场景。
当前交付是 **Windows 本机手动入口基础**，完整对战尚未跑通。显式组合补丁已支持 Qt 通用导航/决策目录选择，
安装与本地 graph 启动配置见[客户端通用接口](CLIENT_ROBOTIO_INTERFACE.md)；旧默认补丁保持原范围。
下述场景缺口用于安排验证，不能将单个队伍的专用实现或协议 fixture 宣称为通用目标已完成。

## 手控步兵与真实导航哨兵同场验证（2026-10-15）

新独立探针 `tools/qa_qt_pb_coop_sil.py` 已通过 5 秒与修复后的 30 秒联合 SIL。
原第五版 Qt 窗口经真实 HTTP 相机、两次 F2、W/S 和鼠标控制 `red_infantry`；独立 credential、motion lease 和 SDK
授权 `red_sentry` 的真实 WSL Point-LIO / SLAM / Nav2 / PB PID。只有原 Qt arm 阶段后才授权导航，
准备阶段 physics/sensor 为 0，没有预喂图像/点云或伪造目标。相机只用于步兵显示，导航是实际 200000 points/s ray/IMU。

| 运行 | 手动批量全部消费 | 原导航非零消费步 | 同一物理步两车非零 | 真实估计位置相对1米目标 |
| --- | --- | --- | --- | --- |
| joint01，5秒，原descriptor | 82/82 | 426 | 314 | Nav2完成 |
| joint03，30秒，reset策略修复 | 486/486 | 476 | 410 | Nav2完成 |

两条独立消费审计均无错误；03还有198实际传感器请求、196原LIO来源、28控制器结果，全部25根检查通过。
原参数 CV4 / CPython1ms 实读并还原，Linux仍各1.3秒、同一host1.5秒；所有owned Job/ROS群组/IO/HTTP/相机回收。
不把Linux时钟与Windows时钟相减；重叠使用同一host GO/F12区间和原2ms物理步。
30秒包含导航目标完成后的合法无动作状态，不能解释为两车30秒始终运动。

中间 joint02 请求30秒但启动阶段失败：reset消耗134ms，首个原采样余期不足50ms，响应超过原期限而拒绝，0导航消费。
启用现有通用 `discard_reset_observation_v1` 元数据策略，成功context-only reset后丢弃旧及初始化期间采样，
等新实际capture；没有改变runtime、自瞄、原50ms导航等待、80ms图像或150ms窗口。旧失败和所有原源保留。
并行清理 helper 的夹具负例不能代替 Linux 回收；实际回收以原 run/spec/boot/PID出生身份和空群组证明为准。

需同一已准备本机环境、第五 review 客户端及上述本地 ENV/stack 文件；复现要求全新输出目录与显式 `--run`：

```powershell
.venv-sim/Scripts/python.exe tools/qa_qt_pb_coop_sil.py --environment artifacts/pb-humble-ext4-runtime-20261014/ENVIRONMENT_COMPAT_FINAL.json --stack-config artifacts/pb-navigation-sil-config-20261014-04.json --out artifacts/qt-pb-coop-fresh --seconds 30 --max-wall-seconds 45 --host-opencv-threads 4 --host-python-switch-interval-ms 1 --run
```

这是实际原窗口的离屏事件验证，尚非可见桌面人工开局入口、比赛树、自瞄/自动火、LAN或六车完整3v3。
该次PB目标源为独立单目标wrapper；新增通用goal-only生命周期及取消/重开验证见下节，决策估计/裁判反馈仍待实现。
代码、失败、原采样/回执、画面和退出证明见[永久证据](validation/qt_pb_coop_20261015/README.md)。

## 新增目标取消、重开与同场手控验证

[通用目标生命周期 v1](NAVIGATION_GOAL_LIFECYCLE.md) 现为独立可复用库，尚未注册为通用速度插件。
新实际第04轮在真实 PB `compute_path_then_follow` 路径运行 synthetic 高层 goal/hold 策略，
原 Qt 手动步兵与导航哨兵的 GO 区间为15.0248667秒：239/239手动批全部匹配、4779消费步，
95实际传感器请求、93原LIO来源、26控制器结果、448导航非零步，376个同一物理步两车同时非零。
第一目标收到hold后实际cancel ACK、terminal和stop均成立，才开启第二目标并真实成功；25项检查全部通过，原资源预算内全部回收。
origin seq16/19分别保留，后续seq17/42只是续授权，不重标旧目标终态。第01导入、第02无目标、第03 NumPy UUID失败均保留。

这里验证异步目标生命周期，不等于比赛决策。`NavigateToPose`后端目前仅单元测试，未启动完整比赛BT；
PB速度仍未带goal UUID，因此没有逐条“某goal→某cmd_vel”的归属证明。decision v1导航/视觉反馈仍为unavailable，
没有理想位姿或敌方位置输入；目标为实际估计map TF沿map-x方向偏移1米，未验收定位精度、多目标比赛策略或六车3v3。
具体API、两种后端配置和显式复现命令见[生命周期文档](NAVIGATION_GOAL_LIFECYCLE.md)。

## 启动手动入口

第五份相机顺序补丁已通过原 PlatformWindow 的实际离屏手控 5 秒与 30 秒验证：原 HTTP 相机、Jello 手动选择、
两 F2、W/S 和鼠标事件经 SDK 进入真实 MuJoCo，86 / 479 批指令全部匹配原窗口/租约/序号/expiry 的消费回执。
前进、后退、非零云台和原护栏、清理均通过；不是可见桌面或完整比赛。
本机新示例为 [coop_camera_order_manual.json](../examples/coop_camera_order_manual.json)，
安装第五补丁及验证细节见[客户端接口](CLIENT_ROBOTIO_INTERFACE.md)。默认 dry plan；显式 `--run` 才启动普通人工窗口：

```powershell
.venv-sim/Scripts/python.exe -m rm_match.deployment.coop_launcher --config examples/coop_camera_order_manual.json --out artifacts/coop-camera-manual-fresh --run
```

这份配置只授权步兵手动操控；不会自动启用哨兵、导航目标、自瞄或比赛树。
此前手控两次失败及第五补丁的后续通过在[独立永久包](validation/manual_camera_order_20261015/README.md)，没有覆盖旧记录。

复用已经准备好的本机环境、固定客户端及其审核补丁：仿真使用 `.venv-sim`，Qt 使用 `.venv-client`。
示例配置为 [coop_manual.json](../examples/coop_manual.json)，默认仅授权 `red_infantry`，没有观战审计权限。

```powershell
# 查看配置对应的启动计划；此命令不启动程序。
.venv-sim/Scripts/python.exe -m rm_match.deployment.coop_launcher --config examples/coop_manual.json

# out 必须为全新目录。启动后在客户端选择获授权的步兵，显式 claim/arm。
.venv-sim/Scripts/python.exe -m rm_match.deployment.coop_launcher --config examples/coop_manual.json --out artifacts/coop-manual-fresh --run
```

此入口启动真实 v2 六车场景服务和固定原 Qt 客户端；程序没有自动绑定算法、发导航目标或开火。
可在可信本地配置中指定已有 `pb_wsl_navigation_manifest` 或 `wsl_native_spec`，它们只注册/准备资源。
旧 native 默认仍限制静止 `red_sentry`。HTTP 请求不能选择可执行文件或扩大人工授权范围。
当前是 loopback 本机入口；没有第二台电脑 LAN 或干净机安装验收。

21 项启动/身份/缺失清理确认测试通过。实际短 smoke 使用全新输出与端口 18766，配置 8 秒；
driver 10.3184506 秒退出 0/reaped/source unchanged，服务正常退出 0，原 Qt 子进程在回收前仍运行，随后由 owned Job 结束。
服务正常资源关闭确认和两个空 Job/回收证明均保存。这个结果只证明启动/退出，不证明人工按键、画面、命中或整场比赛。
证据见[本轮永久包](validation/coop_stream_20261014/README.md)。

## 直接影响对战的工作

1. **移动真实自瞄。** T2 当前速度门和 runtime stationary 门会在底盘运动时撤销自瞄。
   已定位曝光姿态、原算法惯性方向与实际执行时本车角度的转换路径；移动 opt-in 仅有候选，尚未合入或实际验证。
   验证先做本车匀速横移、旋转、启停，保持原图、80 ms 图像门限与 150 ms SDK 窗口。
2. **原比赛决策与导航连接。** 官方独立仓库为
   [pb2025_sentry_behavior](https://github.com/SMBU-PolarBear-Robotics-Team/pb2025_sentry_behavior/tree/d111b635d326775c6c19aa12500a0bbd6a27a588)，
   workspace 固定于 `5faf964b121642d1c8d22dcabf683a13158c2351`。
   当前导航栈只有 planner/controller，未启动接收 `NavigateToPose`/`goal_pose` 的 `bt_navigator`。
   默认 `rmul_2025` 树发固定导航点与小陀螺，没有默认视觉攻击/射击分支；原 Nav2 恢复树不能代替它。
3. **合法状态、地图和取消。** 比赛树需要本车裁判反馈，补给 RFID/受击装甲事件尚未导出；
   固定场地点没有证明与当前 SLAM map 对齐。原树 7 rad/s 小陀螺超过自动接口 2 rad/s 范围，
   首场须显式配置关闭或新增适配，不能静默截断。比赛 BT.CPP 4.6.2 与 Nav2 v3 分进程；
   原取消可累计超过 1.3 秒且 client 会重发，须受原清理期限约束。视觉攻击还需 fresh Target 与失效目标取消。
4. **有来源的自动射击和其余四车。** 当前 fire 为人工通道。自动射击必须来自真实自瞄、经过控制权/期限/裁判仲裁；
   传统决策树机器人明确标注算法来源。随后实际运行整局、结束/reset/第二局及所有资源回收。

通用层 PB 图像请求已从部分传输改为全量抵达 Python peer，但仍超原 80 ms，未向 ROS 发布该图像，也没有检测/PnP/跟踪结果。

先前实际 Point-LIO/Nav2/PID 单目标验证使用实际 ray/IMU 200000 points/s，
与没有导航传感器的手动实验分开记账。既有 PB 速度 wrapper 本身尚未接入通用 `decision_intent_v1` 的 goal/hold/cancel，
也未导出完整估计定位反馈；新增目标库及独立客户端的实际验证不能替代这些接口或比赛树接入。
5秒及30秒人工步兵与真实导航哨兵同场验证见上文；新增goal-only取消/重开已有限验证，
后续继续将其接入通用速度wrapper、补有原采样身份的算法估计/裁判反馈和传统决策树。
禁止用世界真值、最新无来源 TF 或伪造 hold 来填反馈。

这个修复与已有 T2 静态实时、PB 单目标导航分别记账，均不能替代以上完整对战验证。
新电脑、移动精度、多车性能、完整官方规则及 M0–M5 签收仍按计划保留。
