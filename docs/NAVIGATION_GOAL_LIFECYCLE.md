# 有来源的异步导航目标生命周期 v1

`NavigationGoalLifecycle` 是可复用的 **goal-only 库**：接收原 `decision-intent.v1`，跟踪异步目标、取消和真实终态。
它不读取传感器、不输出速度、不提供定位反馈，也尚未注册为通用 `velocity_body` 插件。
现有 decision v1 的 navigation/perception 仍为 unavailable。旧PB默认scan_v1不带goal UUID；
新增显式follow_path_uuid_v2已完成[真实goal→速度消费关联](NAV2_GOAL_VELOCITY.md)，但不改变本库的goal-only权限。

实现为 [navigation_goal_lifecycle.py](../rm_match/integrations/navigation_goal_lifecycle.py) 和可选
[nav2_goal_backend.py](../rm_match/integrations/nav2_goal_backend.py)。仅导入不创建 ROS context、线程或 executor。
调用者必须拥有真实 node/executor、串行调用该库并负责调度和资源收尾；本库没有跨线程锁。

## 调用与来源

```python
from rm_match.integrations.navigation_goal_lifecycle import NavigationGoalLifecycle

# backend 是下面配置的真实 Nav2GoalBackend，或实现同一严格接口的已审核后端。
engine = NavigationGoalLifecycle(backend, deadline_mode="host")
engine.reset({"robot_id": robot_id, "episode": episode, "binding_epoch": binding_epoch})
receipt = engine.submit(original_intent, expected_source=original_six_identity)
receipt = engine.poll()  # 非阻塞；由调用者持续驱动，不能据一次 pending 假报成功。
```

`reset` 只允许一次，换机器人/episode/binding 必须建立新实例。`submit` 校验完整 intent 形状、严格标量类型、
当前 generation 和单调 observed_seq；`expected_source` 可额外核对原六身份：

```text
robot_id, episode, binding_epoch, observed_seq, sim_time, wall_deadline
```

每个目标保存不可回流修改的 `origin_intent`，后续同几何目标只更新 `latest_authorization` 原六身份，不重发目标。
终态同几何目标也去重，包括失败，不能自动重试；显式 hold/cancel、授权过期会清除去重屏障，随后新授权可重开。
不同目标先取消旧目标，只有旧操作通过停止屏障后才发送；等待中的新 intent 过期即丢弃，不重贴时间。
有限历史默认 64 项，耗尽报告 fault，不覆盖原来源。后端状态只通过对应 operation 的 `poll` 更新，旧操作回调不能写入新操作。

## 取消、终态与清理

`cancel_acknowledged` 仅表示实际取消请求获得匹配 UUID 的确认，**不等于 terminal**。
停止屏障要求 send 已解析、所有可能已接收目标均取得真实终态，并有 `terminal=true` 和 `stop_confirmed=true`；
`canceled` 还要求实际 cancel ACK。迟到的 goal acceptance 仍属于原操作，必须取消并等待其结果。
这里证明目标操作结束，不单凭 Nav2 action 终态声称底盘编码器零速。

`succeeded` 必须有真实 navigation UUID；终态/UUID不能回退或替换。缺失、矛盾或伪造后端状态进入 sticky fault 并请求取消，
不以零速度、假 hold 或成功回执代替停止。未知 start/cancel 失败也不能报告 clean。

`request_stop()` 禁止以后 submit、丢弃 pending 并请求取消；它立即返回，调用者仍需 `poll()` 到实际停止证明。
Nav2 backend 的 `destroy()` 在未证明停止时拒绝销毁。node/executor/进程的关闭与 owned group 回收仍由调用者负责；
生命周期 `clean=true` 不能代替这些资源证明。

顶层快照 schema 为 `polar.sim.navigation-goal-lifecycle.v1`，包含 current_source、active operation ID、pending_intent、
fault、stop_requested、clean 和 goals 历史；顶层不把旧目标成功写成“当前观测成功”。
每个历史记录分别保存 origin_intent、latest_authorization、goal UUID、terminal、stop_confirmed、stop_intent/stop_reason。
快照明确 `actuator_authority=none`、`localization_feedback=unavailable`，没有 pose、velocity 或自动 fire 权限。

## 两类时钟

| 模式 | 期限处理 |
| --- | --- |
| `host` | 仅在调用者与原 wall_deadline 同一时钟域时使用；过期 submit 拒绝，poll 在原授权过期时请求取消 |
| `opaque` | 跨 Windows/Linux 时原 wall_deadline 仅保存/回显，不减本地 monotonic；原宿主仍负责 SDK/执行权限的 150 ms 检查 |

`send_timeout_s` 默认 1 s、`cancel_timeout_s` 默认 1.3 s，是本地异步资源观察上限，不能扩大原控制授权。
它们不是为一个旧观测重新发放 1 s/1.3 s 控制期限。原相机 80 ms、SDK 150 ms、binding reset 2 s 以及外层资源预算不变。

## 显式 Nav2 后端配置

调用者先建立实际 ROS node/executor，并验证所选服务器、地图/TF和本机命名空间。配置来自可信本机程序，不能由 HTTP 指定执行命令。

```python
from rm_match.integrations.nav2_goal_backend import Nav2GoalBackend, Nav2GoalSettings

# 模式一：需要已实际运行的 bt_navigator；当前只有单元测试，未实际验收此路径。
settings = Nav2GoalSettings(
    "navigate_to_pose",
    navigation_action=namespace + "/navigate_to_pose",
    behavior_tree="",  # 服务器默认树；不自动安装/启动比赛树。
)

# 模式二：现 PB 实际验证路径，使用原 planner/controller，不依赖 bt_navigator。
settings = Nav2GoalSettings(
    "compute_path_then_follow",
    planner_action=namespace + "/compute_path_to_pose",
    controller_action=namespace + "/follow_path",
    planner_id="GridBased",
    controller_id="FollowPath",
    goal_checker_id="general_goal_checker",
)
backend = Nav2GoalBackend(node, settings)
```

选择其中一种配置。action 名必须为绝对 ROS 路径，未使用模式的字段不能混入。
ComputePathToPose 使用真实机器人起点，只有原规划成功且 path 为合法 map 帧才把完整 path 交给 FollowPath；不制造路径。
goal PoseStamped 使用原 intent sim_time，不能用接收 now 冒充原采样。UUID支持真实 Humble 的 uint8 NumPy 表示，严格检查尺寸和类型。
当前没有 `navigation_goal_backend_profiles.json` 的注册 loader；以上是库配置，不是可直接交给组件 manifest 的新 schema。

## 当前验证范围（2026-10-15）

受控 Future/Event 生命周期回归与原 decision/navigation/ROS envelope 回归合并 152 项通过；
Nav2 后端 UUID 修复后的 36 项 focused 通过。这些单元不代表实际 NavigateToPose、定位精度或比赛通过。

新联合实际第 04 轮 `artifacts/navigation-goal-coop-actual-20261015-04` 的 25 项检查全部通过：
原 Qt 手动步兵与真实 PB 导航哨兵共享 15.0248667 s GO 区间，239/239 手动批匹配、4779 消费步；
95 传感器请求、93 原 LIO 来源、26 控制器结果、448 导航非零步，其中 376 个物理步两车同时非零。
第一目标 origin seq16、后续授权 seq17，hold seq18 获实际 cancel ACK/terminal/stop；第二目标 origin seq19、后续授权 seq42，真实 succeeded/terminal/stop。
新旧 navigation UUID 分别为 `d3a3e7af4862404da3fb3e1d02b941c0` 与 `696517697e8b4bdb8c3c0dd189becbb3`，没有把历史终态改贴成 seq42 的算法结果。
内部 34.7467119 s、driver 37.0327612 s、exit 0、source unchanged，所有 owned 资源回收且未强制终止。

这是 **synthetic 高层 goal/hold 策略 + 原 PB ComputePath/FollowPath** 的有限联合 SIL，不是 PB 比赛树。
目标来自实际估计 map TF 的 map-x 方向相对 1 m 偏移，不用世界真值；这也不提供按原扫描六身份关联的定位反馈 v2。
第 01 轮导入失败、第 02 轮未取得目标、第 03 轮 NumPy UUID 失败分别保留，不能重判旧结果。
上述goal-only第04轮使用的旧PB速度回执没有goal UUID，因此该轮不能据同时运动逐条证明速度归属。
后续独立goal-velocity第03轮使用新server/v2显式profile，已按原UUID/六身份/动作/SDK消费证明两目标分别25/438个非零步；
26项检查通过，详情及两次此前失败见[goal到速度验证](NAV2_GOAL_VELOCITY.md)。它仍是synthetic高层策略，不是通用插件或比赛树。

复现需已有的已核验 Humble 环境、PB 构建/stack 配置和第五客户端补丁；公开读者须先在本机准备这些依赖。
不自动下载或回退到其他源。全新输出目录、显式运行：

```powershell
.venv-sim/Scripts/python.exe tools/qa_navigation_goal_coop_sil.py --environment artifacts/pb-humble-ext4-runtime-20261014/ENVIRONMENT_COMPAT_FINAL.json --stack-config artifacts/pb-navigation-sil-config-20261014-04.json --out artifacts/navigation-goal-coop-fresh --seconds 15 --max-wall-seconds 30 --host-opencv-threads 4 --host-python-switch-interval-ms 1 --run
```

去掉 `--run` 只输出计划。此工具不安装 bt_navigator、不接比赛树、不开放自动开火；完整决策反馈、多目标比赛策略、可见人工开局、六车3v3和 M0–M5 签收仍未完成。
