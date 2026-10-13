# 可选 ROS 2 JSON 信封桥（T07 基础）

入口：`python -u -m rm_match.integrations.ros2_bridge`。生产入口必须有真实 `rclpy`、`std_msgs` 和 DDS；缺依赖直接失败，绝不返回零动作冒充算法。桥本身不包含 Nav2、定位、自家导航或检测算法，也不发布伪造 IMU/LiDAR/TF。现有理想里程计、理想 ranges 的导航边界仍待 T09 补齐。

## 本地预注册

[`examples/ros2_adapters.json`](../examples/ros2_adapters.json) 复用 `polar.sim.adapter.jsonl.v1` 注册格式，明确新增 `custom_ros2_navigation`、`custom_ros2_aim` 两个 ID；不修改默认 native 注册。管理员审核本地 manifest 的 argv，固定节点名、收发 topic、kind、adapter_id、domain 和本地等待上限。绑定 config 只能是 `{}`；HTTP 客户端不能选择执行命令、ROS topic 或节点。

`{python}` 是服务选定解释器。必须在同一受控 ROS Python 环境启动服务和桥：source 已核验的 ROS 环境，确认该解释器可 `import rclpy; from std_msgs.msg import String`。Windows 服务到 WSL ROS 的专用跨系统监督器尚未提供；不要把 Linux 路径塞进 Windows 注册 argv。

用已有部署入口显式加入：

```sh
python tools/deploy.py plan --adapters-json examples/ros2_adapters.json
# 实际 launch 还须满足原部署/native/client/admission 的全部检查。
# --sim-python 必须指向经过核验且已加载真实 rclpy 的解释器。
```

SDK 选择示例（已启动服务、真实算法 ROS 节点已连接）：

```python
import os
from rm_match.platform_v2.client import PlatformClient
client = PlatformClient('http://127.0.0.1:18765', control_profile='server_window_v1',
        admission_credential=os.environ['POLAR_SIM_ADMISSION_CREDENTIAL'])
try:
    client.open('operator')
    client.claim('red_sentry', ['motion'])
    binding = client.bind('red_sentry', 'navigation', 'custom_ros2_navigation', {})
    window = client.control_window('red_sentry', ['motion'])
    client.adapter_input('red_sentry', 'navigation', binding['binding_epoch'],
        window_id=window['window_id'])
    # 继续按 SDK 的输入窗口/keepalive/renew 契约操作；阅读状态不续期。
finally:
    client.close()
```

当前 Qt 未实现任意 `custom_` ID 的配置 UI；本例使用 SDK。aim 须另行领取 gimbal，navigation 不能领取 fire 来扩大算法权限。ROS 同一 domain/topic 的本地发布者必须可信；此桥没有 SROS2 peer 身份授权，也不是恶意 Python/DDS 沙箱或硬件接口。

## 数据与期限

两个 topic 使用 `std_msgs/msg/String`，`data` 是一个 UTF-8 JSON 信封：

| topic | 信封精确字段 | 内层对象 |
| --- | --- | --- |
| observation | `schema / type / adapter_id / observation`；type 为 `observation` | 完整 `polar.sim.observation.v2` 对象 |
| action | `schema / type / adapter_id / action`；type 为 `action` | 完整 `polar.sim.action.v2` 对象 |

schema 均为 `polar.sim.ros2.envelope.v1`。例如收到身份为下面六项的真实观测后，外部算法可以返回如下合法零速度动作（这是消息格式示例，不是导航算法）：

```json
{"schema":"polar.sim.ros2.envelope.v1","type":"action","adapter_id":"custom_ros2_navigation","action":{"schema":"polar.sim.action.v2","robot_id":"red_sentry","episode":2,"binding_epoch":3,"observed_seq":1,"sim_time":1.0,"wall_deadline":987654321.0,"kind":"navigation","mode":"velocity_body","command":{"frame":"base_link","vx_mps":0.0,"vy_mps":0.0,"wz_rps":0.0}}}
```

算法必须从刚收到的 observation 原样复制六项：`robot_id / episode / binding_epoch / observed_seq / sim_time / wall_deadline`。不能把旧 Twist 的速度复制进动作，再贴上当前帧身份；无 Header 或缺原始六项关联的控制不会被这个桥转换。已有 command 坐标、角度、范围和标量类型校验照常执行。

单个桥进程只 reset 一次，只持有一个 pending observation 和一个响应槽。序号严格递增；旧绑定/episode、身份值或类型不匹配、错误路由、未知字段、重复 JSON key、非有限数、过大消息都拒绝。observation/JSONL 请求上限 12 MiB，action 信封/JSONL 响应上限 64 KiB。拒绝响应不会消费当前合法 pending；超期不会刷新等待预算或产生替代动作。aim 的 `fire_permission=true` 明确拒绝，桥不合成任何开火输入。

`wall_deadline` 是服务器的绝对单调时钟值，只能 echo。桥用自己的单调时钟限制从收到观测起的处理时间（示例 80ms，上限 250ms），不把服务器绝对值减 Linux 本地时钟。跨进程传输和排队已消耗的时间仍由 host `JsonLineAdapter` 与物理消费门禁拒绝；本地 80ms 等待不代表服务器额外赠予 80ms。

首次 reset ACK 前最多等待 1 秒发现已存在的 observation 消费者和 action 发布者；没有算法 graph 则失败。此等待不发送观测、不计入帧预算，也不能替代原 host reset 超时。stdout 只输出 JSONL：桥将 ROS/Python/C 的控制台输出重定向到 stderr（现有 host 丢弃此 stderr）。失败无成功动作回复，需显式重新绑定。

## ROS 设置与验证边界

两端须采用相容 QoS：`KEEP_LAST / depth=1 / BEST_EFFORT / VOLATILE`。depth 限制排队历史，volatile 不给迟到订阅者回放旧控制；消息丢失会触发原 host 超时。String 类型在 DDS wire 上没有固定长度，应用入口会拒绝超大 JSON，不能据此声称具有恶意发送者的内存隔离。

桥只在自己的进程环境设置 `ROS_DOMAIN_ID`（本地 argv 明确指定）、`ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`、空 `ROS_STATIC_PEERS`，并兼容设置 `ROS_LOCALHOST_ONLY=1`；不修改系统、shell 配置或防火墙。外部算法进程也要使用相同 domain（示例 78）和本地发现设置。只接受 `rmw_fastrtps_cpp` / `rmw_cyclonedds_cpp`，不以不支持这些发现参数的 Zenoh 伪装本地限制。它约束自动发现，不是 ROS peer 认证，也不是两电脑 LAN 验收。

```sh
python -m pytest tests/test_ros2_bridge.py tests/test_ros2_bridge_transport.py
# 明确启用后必须使用真实 ROS Python；依赖缺失将失败，不能 skip/fallback。
POLAR_RUN_ACTUAL_ROS2_BRIDGE=1 python -m unittest discover -s tests -p test_ros2_bridge_actual.py -v
```

第一组只验证显式 FakeTransport/FakeRos 契约和生命周期，不能当作 ROS 验收。第二组用真实 rclpy/DDS peer 与桥子进程，传的是标明 test fixture 的 DTO，断言完整身份、stdout 与正常退出；不运行物理、导航或检测，不证明 SIL/HIL、实际传感器闭环或比赛性能。未启用 actual flag 时仅该专项测试明确 skipped。当前 Windows 环境缺 ROS 的实际 CLI 检查结果是退出 2、stdout 0 字节。

### 本轮真实 DDS 证据

2026-10-13 在 Ubuntu WSL Python 3.14.4 中，官方 ROS 2 Lyrical `rclpy 10.0.11` + `rmw_fastrtps_cpp` 实测 1 项通过，采用原示例 80ms 本地响应等待上限。domain 为 79、自动发现仅 LOCALHOST、无静态 peers。桥子进程退出 0，收到 1 个完整 DTO、输出 reset/action 两条合法 JSONL；六身份原样 echo；测试 peer 线程已结束、ROS context 已关闭。

冻结证据位于 [`actual_attempt3/ACTUAL_ROS_RESULT.json`](validation/ros2_dds_bridge_20261013/actual_attempt3/ACTUAL_ROS_RESULT.json)、同目录的 probe 与 actual_dds 日志。`PACKAGES_MANIFEST.json` 记录 97 个经官方 ROS InRelease 签名与 SHA 核验的 deb；`EXTRACTION.json` 记录 owned-prefix 解压与链接检查。7 个 Ubuntu C 依赖和 4 个 Python 依赖分别有官方 apt/GPG/SHA 记录；不执行安装钩子、不写 `/etc`、不修改全局环境。前两次缺库/缺 Python 依赖的失败证据保持原样。

全部 ROS 库位于 `artifacts/ros2-local-lyrical-20261013/prefix`，运行器[原文](validation/ros2_dds_bridge_20261013/run_actual_ros.py.txt)只给子进程设置 Python/动态库/AMENT/ROS 变量，ROS 日志亦留在该次 attempt 目录。该专项证明 DDS/JSONL 基础桥接与清理，尚未证明原 host `JsonLineAdapter` 2s 启动限制、80ms 物理消费门禁下的 ROS 算法运行，或真实导航/自瞄闭环；较慢的 prefix 导入不能被记成满足实时指标。

## 官方接口依据

实现核对了 ROS 2 官方 Jazzy 源码；docs.ros.org 页面本次读取被 Anubis 拒绝，使用官方 GitHub 镜像内容。安装分发和运行版本仍须记录并实际核验。

- [Python publisher / subscriber 示例](https://github.com/ros2/examples/tree/jazzy/rclpy/topics)：String、create_publisher/create_subscription、节点初始化与关闭。
- [QoS](https://github.com/ros2/ros2_documentation/blob/jazzy/source/Concepts/Intermediate/About-Quality-of-Service-Settings.rst)：keep-last/depth、best-effort、volatile 及兼容性。
- [发现范围](https://github.com/ros2/ros2_documentation/blob/jazzy/source/Tutorials/Advanced/Improved-Dynamic-Discovery.rst)：LOCALHOST、STATIC_PEERS 和 Zenoh 例外。
- [rclpy executor](https://github.com/ros2/rclpy/blob/jazzy/rclpy/rclpy/executors.py)、[node](https://github.com/ros2/rclpy/blob/jazzy/rclpy/rclpy/node.py)：单线程 spin_once、graph 查询与关闭。
- [String 定义](https://github.com/ros2/common_interfaces/blob/jazzy/std_msgs/msg/String.msg)：本阶段显式 JSON 信封的兼容载体；后续强类型 RobotIO ROS 消息尚未实现。
