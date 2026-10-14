# Qt 客户端通用组件接入

新的显式组合补丁支持按能力合同选择通用导航、决策/导航 pipeline，以及已有通用自瞄。
注册和显示不按队名分派。队伍仍需提供匹配协议的本地 wrapper；目录可选不代表算法或整场比赛已经通过。

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
