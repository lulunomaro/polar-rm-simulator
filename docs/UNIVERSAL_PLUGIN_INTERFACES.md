# 通用导航、决策与自瞄插件接口

目标是让不同队伍的导航、比赛决策和自瞄程序通过可配置 wrapper 接入同一仿真客户端。
北极熊、T2、同济用于具体接入验证；注册规则以协议版本、能力、机器人范围和来源身份为依据，没有队伍白名单。
3v3 是验证场景。接口声明通过、协议 fixture 通过、某个队伍算法通过、完整比赛通过分别记账。

当前开放边界已包含组件 manifest、显式决策/导航组合、SDK 目录、JSONL、ROS 2 envelope 和显式 WSL 资源准备。
它不自动理解任意 ROS 消息或串口包。队伍应提供保持真实数据来源的 wrapper；算法本身、标定、耗时和输出含义仍需验证。
自动开火尚未开放；Qt 的通用导航/决策选择器尚未完成，当前通用入口使用 v2 SDK。

## 组件与数据边界

| 组件 | Manifest schema | 输入与能力 | 输出 |
| --- | --- | --- | --- |
| navigation | `polar.sim.navigation-plugins.v1` | `polar.sim.navigation-observation.v1`；`pointcloud_imu_v1` 点云/IMU、本车状态、裁判数据；不含理想位姿/里程计 | `polar.sim.action.v2` 的 `velocity_body`，或有原身份的 `pending_localization` / `no_associated_command` 状态 |
| decision | `polar.sim.decision-plugins.v1` | `polar.sim.decision-observation.v1`；`own_referee_v1` 本车 team/role/hp/ammo/heat/alive 和 phase/remaining_seconds/emergency_stop | `polar.sim.decision-intent.v1` 的 `navigation_intent`；没有执行器权限 |
| aim | `polar.sim.aim-plugins.v1` | `polar.sim.observation.v2`；`calibrated_camera_capture_own_v1` 工业相机原始 RGB/BGR 图像、标定和曝光时本车云台状态 | `gimbal_target` yaw/pitch，或 `no_target` / `pending_result`；`fire_authority=manual_only` |

决策 v1 的 `navigation` 与 `perception` 都必须为：

```json
{"available": false, "reason": "not_provided_in_own_referee_v1"}
```

此版本没有导航定位结果或视觉目标输入。不能填入理想 odometry、场上机器人列表、敌方位置、模拟器真值 Target。
后续增加估计结果需要新的明确协议版本和实际来源验证，不能在现有字段里藏数据。

决策 command 是严格联合类型：

```json
{"behavior": "hold", "reason": "explicit reason"}
```

```json
{"behavior": "cancel", "reason": "explicit reason"}
```

```json
{
  "behavior": "navigate_to_pose",
  "reason": "configured map waypoint",
  "goal": {"frame": "map", "position_m": [2.0, -1.0], "yaw_rad": 0.0}
}
```

决策不得输出 Twist、云台角或火控。`map` 目标表示意图，接口接受它不证明地图已标定；
场地图标定、真实定位、目标执行和取消由所选导航 wrapper 负责，不能注入理想 map→odom 或敌方世界坐标。
目标感知为空时应保持未检测状态。裸 Twist、Pose、Target 没有本次请求的来源身份，不能在订阅端补新身份后作为闭环输出。

## 本地注册与显式组合

三个组件 manifest 都使用 `adapters` 数组，每项具有：

```text
adapter_id / label / command / cwd / supported_robots / transport / capabilities
```

`adapter_id` 使用 `custom_*`。`supported_robots` 声明当前 wrapper 支持的机器人范围，不得扩大服务器 admission 授权。
命令和 cwd 来自本机可信文件；`{python}` 表示当前解释器。文件的原始字节 SHA 在注册时冻结，启动/绑定前变化会拒绝。
HTTP 只能选择已经注册的 ID，绑定 config 为 `{}`；不能提交 executable、模型路径、cwd 或新的授权范围。
本地进程隔离用于资源归属与回收，不是运行不可信代码的安全沙箱。

生产模板为 [navigation_plugins.json](../examples/navigation_plugins.json)、
[decision_plugins.json](../examples/decision_plugins.json)、[aim_plugins.json](../examples/aim_plugins.json)。
模板中的 reviewed wrapper 文件必须替换为实际本地程序，它们不是已经安装好的队伍算法。

统一 graph schema 为 `polar.sim.robotio-plugins.v1`。例如可信本地 `config/robotio_plugins.local.json`：

```json
{
  "schema": "polar.sim.robotio-plugins.v1",
  "manifests": {
    "navigation": "navigation_plugins.local.json",
    "decision": "decision_plugins.local.json",
    "aim": "aim_plugins.local.json"
  },
  "pipelines": [
    {
      "adapter_id": "custom_team_decision_navigation",
      "label": "Reviewed team decision and navigation",
      "decision_plugin_id": "custom_reviewed_team_decision",
      "navigation_plugin_id": "custom_reviewed_navigation",
      "supported_robots": ["red_sentry"]
    }
  ]
}
```

不需要的组件 manifest 可以为 `null`。引用路径相对 graph 文件；组件 cwd 相对组件 manifest。
pipeline 的机器人范围必须是两组件范围的子集，ID 不得碰撞。
要接收决策意图，navigation capabilities 必须显式声明 `goal_input_modes: ["decision_intent_v1"]`；
生产 navigation 模板默认是 `[]`，需要真实 wrapper 支持后才能修改声明。

组合每次以同一份原观测运行 decision，然后将本次完整 intent 交给 navigation。
没有新意图时，goal-aware navigation 不自动编默认目标。`hold` / `cancel` 也传给 navigation 执行。
停止意图要求 navigation 真正保持/取消，并返回同来源的零速度或无动作状态；非零速度必须拒绝。
composer 不得把原非零输出改写为零后冒充算法已停止。最新停止语义专项包含两个实际违规子进程的拒绝与回收；
完整原记录见[永久验证包](validation/robotio_plugins_20261014/README.md)。
pipeline 仍是现有 `navigation` motion 通道的一个 adapter；decision 不增加第三个物理执行器通道。

## 身份、协商与期限

所有 observation、intent、action/status 保留六项原身份：

```text
robot_id, episode, binding_epoch, observed_seq, sim_time, wall_deadline
```

必须连 JSON 标量类型一起回显。跨机器人、旧 episode/epoch、重放 observed_seq、重贴 sim_time/deadline 均不能授权新控制。
SDK 控制窗口还关联 session、motion/gimbal lease epoch、window_id 和 activation；算法 DTO 不替代这些权限。
`wall_deadline` 属于原宿主时钟。Linux/ROS peer 保留它并回显，不能用自己的 monotonic 时钟重写或与跨域时钟直接相减。

navigation 和 decision 的实际 reset ACK 包含完整 `capabilities`，宿主逐字段与 manifest 比较；
ROS 路由先发送 `capabilities_request` 并检查实际 peer 的 context/capabilities，才返回 reset ACK。
本地声明不等于已协商。现有 aim 路由仍按声明的 camera/gimbal 合同验证输入输出，不能将其注册声明称为同样的 reset 能力协商已完成。

| 门限 | 当前含义 |
| --- | --- |
| 80 ms | 相机图像原 capture 的 sim/wall 年龄门限；不能借传输或推理完成时刻重置 |
| 150 ms | SDK 活输入/控制窗口；组合两组件共享原 wall_deadline，decision 用时不会给 navigation 重新发完整窗口 |
| 2 s | binding reset；decision+navigation 共用一个 reset deadline，不是各拿 2 s |
| 50 ms | 通用 navigation ROS envelope 的最大本地回复窗口；decision 最大 150 ms，原宿主期限仍独立生效 |
| 1 s | ROS graph 与实际 capability 协商的本地总预算 |
| 1.3 s / 1.5 s | owned WSL Linux 清理 / 宿主资源清理；组合 peer 共享原宿主 1.5 s 资源预算 |

WSL resource preparation 在物理运行前显式执行，当前最多 15 s 初始化预算。
它不提供图像、点云或虚假推理预热，也不代替 binding 的实际 reset ACK/2 s 门限。
资源是一个 prepared instance 对一个 binding，换代/rebind 需要新资源；缺失回收证明仍报告不干净。

## Wrapper 与传输

| 传输声明 | 当前入口 |
| --- | --- |
| `jsonl_v1` | navigation `run_navigation_plugin(factory, goal_input_modes=...)`；decision `run_decision_plugin(factory)`；aim `run_aim_plugin(factory)` |
| `ros2_navigation_envelope_v1` / `ros2_decision_envelope_v1` | `python -m rm_match.integrations.robotio_ros2_bridge`，ROS 2 String 中承载有原身份的 envelope；外部算法节点必须实现 capability 握手和完整响应 |
| aim `ros2_envelope_v1` | `python -m rm_match.integrations.ros2_bridge --kind aim ...`，既有 calibrated camera/action envelope |
| `wsl_jsonl_v1` | 本地 manifest 额外声明 `wsl: {distribution, python, process_env}`，command/cwd 为实际 Linux 路径，使用 owned Windows/Linux supervisor |

navigation callback 为 `compute(detached_navigation_observation, detached_intent_or_none)`；
decision 为 `compute(detached_decision_observation)`；aim 为 `compute(camera_bundle, detached_observation)`。
应返回完整有源 DTO，缺失结果会失败，框架不以零速度、hold 或 no-target 代替算法结果。
工厂/库 stdout 被导向 stderr，stdout 保留给 bounded JSONL。wrapper 可以桥接 ROS 2、原生程序或队伍串口协议，
但不能以旧算法、像素代打、真值或新时间戳代替原图→真实自瞄→yaw/pitch 链路。

ROS 2 接入时，真实算法节点先启动在匹配的本机 DDS domain/topic 上。bridge 示例参数形状如下：

```powershell
.venv-sim/Scripts/python.exe -m rm_match.integrations.robotio_ros2_bridge --adapter-id custom_team_navigation --kind navigation --node-name team_navigation_bridge --observation-topic /team/navigation/observation --action-topic /team/navigation/response --domain-id 80 --response-timeout 0.05 --goal-input
```

此命令需要当前解释器中实际可用的 ROS 2/rclpy；Windows 未安装时应配置真正的 Humble Linux/WSL wrapper。
它不会自动启动队伍算法，也不会退回假 transport。decision 使用 `--kind decision`，不加 `--goal-input`；
navigation 是否加该开关必须与 manifest 的 goal_input_modes 一致。
多车实例必须使用独立 ROS node/topic/namespace 或 DDS domain；可为每车配置不同 component 行。
把 supported_robots 写成多车不自动改写固定主题，wrapper 须证明本车数据和 context 独立。

## 服务器与 SDK

从仓库根目录启动已经提供真实 wrapper 和 admission 的本地配置：

```powershell
.venv-sim/Scripts/python.exe -m rm_match.platform_v2 --admission-manifest config/robotio_admission.local.json --robotio-plugins-json config/robotio_plugins.local.json --camera --camera-total-fps 15 --port 8766
```

只有 navigation/decision、没有 aim 的 graph 可以去掉 camera 参数。
Windows graph 包含 WSL peer 时额外传 `--prepare-robotio-plugins`；不显式准备的 WSL adapter 会显示 unavailable。
参数只选择可信本地文件，admission 仍要求原有 `polar.sim.admission.v1` grants。不要把 credential 写入公共 manifest 或命令行。

`GET /v2/plugins` 需要有效会话。返回 `polar.sim.robotio-plugin-catalog.v1` 的组件/组合目录与授权机器人范围，
不返回 command、cwd、credential 或隐藏仿真状态。仅接口 readiness 元数据不能作为实际算法通过证据。
`GET /v2/adapters` 保持现有 navigation/aim 执行器列表；独立 decision 只在 plugin catalog 中出现。

SDK 的一次发现、绑定和活输入请求示例，credential 由本机进程环境提供：

```python
import os
from rm_match.platform_v2.client import PlatformClient

client = PlatformClient(
    "http://127.0.0.1:8766",
    control_profile="server_window_v1",
    admission_credential=os.environ["POLAR_OPERATOR_CREDENTIAL"],
)
try:
    client.open("operator")
    catalog = client.plugins()
    robot_id = "red_sentry"  # 必须属于 admission 和所选 pipeline 的范围
    client.claim(robot_id, ["motion"])
    binding = client.bind_pipeline(robot_id, "custom_team_decision_navigation")
    window = client.control_window(robot_id, ["motion"])
    client.adapter_input(
        robot_id, "navigation", binding["binding_epoch"],
        window_id=window["window_id"], valid_for_s=0.15,
    )
finally:
    client.close()
```

这是一次协议请求，不承诺绑定后台初始化已完成或产生运动。实际客户端应在本轮绑定 ready 后，
由当前活输入刷新 lease 和新的 server window/adapter_input；释放按键、暂停、断连或权限撤销后停止刷新。
不能靠自动重贴旧 window、旧 intent/action 延续控制。自瞄单独 claim gimbal 并绑定 aim；fire 仍由独立人工通道控制。
当前 SDK/server 仅支持 loopback，不宣称另一台电脑 LAN 已验收。

## 当前证据与显式协议演示

独立 supply v1 与 heat v2 决策 fixture 的 JSONL 组合、hold/cancel、身份/期限、清理和 loopback catalog 已有 focused 证据。
它们是两份不同源码策略加 synthetic goal velocity fixture，不是队伍决策、SLAM、路径规划或自瞄模型。

[实际 DDS03 RESULT](validation/robotio_plugins_20261014/records/artifacts/robotio-ros2-actual-20261014-03/RESULT.json) 的 exit_code=0、source_unchanged=true，
检查两次真实 prepare ACK、navigation/decision 在原 2 s 内 reset，以及两类原 source echo；内部驱动用时 7.906444 s。
其明确 scope 是 **synthetic protocol DDS**。这证明该次真实 ROS 2 通信协议 fixture，不证明任何队伍算法、神经网络、物理导航或完整比赛。
首次 supervisor 缺 NumPy 的失败、DDS02 通过与最终停止语义源码下 DDS03 通过分别保留，没有拼接或重判。

仓库还提供 [robotio_protocol_plugins.json](../examples/robotio_protocol_plugins.json)，
关联两份独立 decision fixture 和 goal-aware navigation fixture。
以下命令是显式低速协议 SIL 演示：新输出目录、3–5 s 时长、`--run` 都由工具要求。

```powershell
.venv-sim/Scripts/python.exe tools/qa_robotio_protocol_sil.py --out artifacts/robotio-protocol-demo-fresh --duration 4 --run
```

工具先显式完成四个实际 JSONL peer 的资源 prepare，再由本轮 binding 执行真实 reset/能力 ACK。
它运行真实 MuJoCo 的本车点云/IMU、v2 SDK 与独立 synthetic 子进程，保存实际控制消费与清理证据；
只在隔离评价端读取世界位置，不送给 peer。点云为 1000 points/s 的演示配置，没有相机/NN/ROS/WSL/GUI。
第三轮已经通过：1771 物理步、两车各 26 个独立原 source action，红步兵 935 个非零消费步骤、蓝哨兵 980 个零速度消费步骤，
原 SDK/传感器时限审计无错误，四个子进程/HTTP/SDK 全部回收。前两轮退出竞争与原期限超时失败原样保留；
这个通过使用专用资源准备 harness，不证明服务器默认 JSONL 启动或实时性能已通过。复跑应读取新 RESULT/AUDIT/CLEANUP。
它不验收 MID360/SLAM、目标到达、RTF、移动自瞄、开火或 3v3；生产接入仍须换成实际 wrapper 并分别验证。
