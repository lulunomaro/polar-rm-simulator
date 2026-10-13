# RobotIO v1 逻辑契约草案

状态：draft，2026-10-13（UTC+8），对应 T01/T07。本文约束后续接入与验收，不能作为新 wire schema 已实现或 T01 已冻结的证据。当前可执行格式仍是 `polar.sim.observation.v2`、`polar.sim.action.v2`、`rm.sim.platform.v2` 与 `polar.sim.adapter.jsonl.v1`；不得把它们改名为 RobotIO v1 后直接发送。字段以 [contracts.py](../rm_match/platform_v2/contracts.py)、[server.py](../rm_match/platform_v2/server.py)、[control.py](../rm_match/platform_v2/control.py) 为准。现有范围见 [CONTRACT.md](../rm_match/platform_v2/CONTRACT.md) 与 [CUSTOM_INTERFACES.md](CUSTOM_INTERFACES.md)。

## 三个数据平面

| 平面 | 目标边界 | 当前实现与缺口 |
| --- | --- | --- |
| 选手/算法 | 本车传感器、标定、合法裁判字段和授权控制；禁止敌方真值、理想定位及命中预知 | 默认算法 DTO 不含敌方坐标、目标 ID、分割标签、全车名单或 simulator/judge 对象；默认仍有理想本车关节、`odom_xyyaw`/`odom_vxyw` 和 64 条匿名理想射线。显式 navigation_sensor_v1/PB桥使用独立真实ray/gyro/accelerometer，不传ideal pose，详见下述局部接入边界 |
| 仿真/裁判 | 完整世界状态、碰撞与规则内部状态仅在权威线程使用 | 物理推进、控制仲裁、碰撞与裁判由服务权威线程管理；当前规则仅已验证的 3v3 子集 |
| 观战/评测 | 真值、俯视与评分单独权限/通道，不回流算法 | 显式 audit grant 的 spectator 保留完整审计；operator state 是 `operator_limited_display`，frame 是 `operator_camera_display_v1`，不含世界 xy/odom 或他人动态/指令。本地 grant 限定 robot scope，watch/claim/control 不得越范围。跨机权限、TLS 与多人实测仍待 T13 |

因此不能以 DTO 字段审核或局部 state 投影通过宣称 A09/A10 已通过。同进程 Python 和可信 JSONL 子进程均不构成恶意插件安全沙箱；第三方部署还需访问与资源隔离。

## 版本、声明与映射

| RobotIO v1 逻辑项 | 当前映射 | 状态 |
| --- | --- | --- |
| 机器人与运行身份 | DTO `robot_id`、`episode`；`own.team/role`；HTTP 从 backend 枚举 robot IDs | 已有，默认 native 仍限静止 `red_sentry` |
| 插件能力与发现 | `/v2/adapters` descriptor 含 `adapter_id/version/kind/required_sensors/output_modes/available/reason`；`/v2/capabilities` 提供部分控制能力 | 已有声明与拒绝路径；不是完整通用版本协商或运行质量证明 |
| 模型/配置身份 | 默认 `own-rmcs-t2-v1` 校验 source/build/spec/binary/config/model 哈希；JSONL 固定本地 manifest 哈希 | 部分已有，通用车辆包、所有插件的统一哈希声明与模型映射待 T07/T08 |
| 会话/代际 | HTTP 内存 session 与 bearer；每车每通道 lease epoch；算法 `episode/binding_epoch` | 已有，但算法 DTO 不携带 session ID；关联由服务内部 binding owner 完成 |
| 输入与输出 | own-sensor observation → navigation `velocity_body` 或 aim `gimbal_target` | 已有；关节/扭矩、轨迹、动态目标流及 RL 模式待扩展，未知模式拒绝 |
| 进程生命周期 | `reset({episode,robot_id,binding_epoch})` → `act(observation)` → `close()` | 已有；异常需显式 rebind；一个 slot 最多一个运行任务加一个可替换待处理观测 |
| 桥接 | 可信本地 native、JSONL；HTTP Python SDK | 已有；ROS 2 与串口桥待 T07/T18，不是当前依赖 |

默认部署缺模型、算法或身份不匹配时失败，不静默切换像素基线。默认 registry 与 opt-in 示例 registry 的能力不能混写。HTTP 配置只选择预注册 ID，不选择 import、可执行文件或模型路径。

## 坐标、单位与标定

当前 `frames` 必须严格等于 validator 中的四项声明：

| 帧/字段 | 约定 |
| --- | --- |
| `world` | 右手系，米，+Z 向上；从上方看正 yaw 逆时针；当前地图原点由场景定义 |
| `base_link` | +X 前、+Y 左、+Z 上；底盘速度为 m/s，yaw rate 为 rad/s |
| `gimbal_link` | yaw 相对底盘；正 pitch 向上；yaw/pitch 均为弧度 |
| `camera_optical` | +X 右、+Y 下、+Z 前 |
| `own.qpos`/`qvel` | 当前五维顺序 `[base_x,base_y,base_yaw,gimbal_yaw,gimbal_pitch]` 及其导数；不是任意车辆关节数组；前两项是模型关节坐标，不可一概当作地图绝对位置 |
| `odom_xyyaw`/`odom_vxyw` | `[world_x,world_y,yaw]` / `[world_vx,world_vy,yaw_rate]`，当前来自理想仿真本车状态 |
| `sensors.ranges` | `frame=base_link`，距离 m、角度 rad、匿名射线；`provenance=ideal_simulated_range` |

相机 `extrinsics.parent_frame=gimbal_link`；`translation_m` 与 `rotation_xyzw` 将 camera optical 坐标变到 parent，即 `p_parent=R(q_xyzw)*p_optical+t`。四元数顺序 x,y,z,w，单位范数误差不得超过 1e-6。MuJoCo 的内部 wxyz 顺序由相机适配器显式转换，不能直接复制。当前没有独立 `map`/`lidar` 帧契约或统一变换树；其原点、外参版本、标定有效期与任意车辆轴映射需在 T07–T09 冻结。

图像是实际渲染 packed rgb8/bgr8，`stride_bytes=width*3`，base64，raw 最大 8 MiB；内参 fx/fy/cx/cy 以像素为单位，畸变为 `brown_conrady_5` 五系数与 `calibration_id`。相机曝光时的本车 pose/velocity 与 `capture_sim_time` 同包传递，不能用到达时位姿替换。无传感器时只返回 `available=false` 与 reason；不伪造 IMU、深度或 MID360 点云。

## 时钟、序列与期限

`sim_time` 是本 episode 的仿真秒；传感器 `capture_sim_time` 是采样仿真时间。`wall_deadline`、HTTP `server_monotonic_s`、session/lease/input/window 到期时间均是服务端单调秒，不是 UTC，也不可与另一台电脑的 monotonic 时间相减。现有算法 action 必须精确回显 `robot_id/episode/binding_epoch/observed_seq/sim_time/wall_deadline`，不得刷新时间戳延命。

HTTP 每通道控制 `seq`、adapter activation `seq` 各自在当前代际内严格递增，观测有 `observed_seq`。session、lease epoch、binding epoch、episode、watch epoch、window ID 用途不同，不能互换。重启失效 bearer；新 episode 撤销租约；重绑使旧算法结果失效。

`legacy_v2` 从服务器接收时计算短 TTL；默认控制平面 session TTL 60 s、lease TTL 1 s、command 上限 250 ms（可由服务配置调整）。`server_window_v1` 必须先申请 `/v2/control_window`，窗口至多 150 ms；指令有效期取接收时 TTL 与窗口剩余期限的较小者，重复使用同窗口不得延长旧授权。绑定后的算法还须用 `/v2/adapter_input` 维持独立 activation，续 session 或 lease 不替代它。权威线程在结果消费与实际执行器写入处重查权限、代际、物理状态与期限；accepted 仅表示请求被接纳，不证明执行器已到位。

自有 native 保留 80 ms 图像预算及 150 ms 输入窗口。live 按服务端壁钟期限执行；offline 可等待算法并采用独立 modeled-latency 配置，离线通过不等于实时通过。[验收预设](../config/acceptance/m1-v1.json) 保留两套时钟模式。现有 runtime trace 有 enqueue/result/apply 等时间；统一每段采样、发送、接收、排队、实际生效时间及跨机测时误差账本仍待 T03/T15。采样仿真时间不能冒充采样壁钟时间。

## 控制权与安全

每车 `motion/gimbal/fire` 独立租约，claim 不抢占；spectator 不可 claim、renew、bind 或 control。navigation 只输出底盘速度，aim 只输出云台目标；`fire_permission` 仅信息，不生成弹丸。当前火力仍是独立、当前、显式人工/测试通道，自动射击闭环待 T04。

逻辑生命周期应为 claim → arm/持续授权 → command → release。当前没有独立 `/v2/arm`；strict profile 的有效窗口与 activation 是已实现的持续授权机制，不能称为完整 RobotIO arm 状态机。HTTP 断连不会即时通知物理服务，停止依赖已有 command/activation/lease 到期；失焦需客户端停止发送输入，服务端无法直接感知 UI 焦点。

过期、NaN/无穷、错误身份、插件退出/异常、停赛/急停/死亡均拒绝结果或禁用受影响通道。底盘撤销作用力/转矩，云台保持当前角，fire=false；这不证明惯性速度瞬间为零。stationary-only native 在当前请求/实测运动下另有抑制。SDK 丢响应、畸形响应、重定向或超大响应标记 uncertain，禁止盲重试控制/续约/绑定；显式重连后重新 claim/bind，不重放旧射击。HIL 独立急停、限幅、看门狗尚待专项授权与 T18，不将 SIL 护栏写成真实硬件安全验收。

## HTTP 与 JSONL 示例

HTTP 成功响应带 `schema=rm.sim.platform.v2`。会话 bearer 只在内存和 Authorization 头使用，以下不包含凭证。服务仅 loopback，默认 127.0.0.1:8766，body 最大 16 KiB；当前无跨机 LAN、TLS 或远程准入。可用端点有 health/sessions/keepalive/close、robots/adapters/capabilities/state、watch/frame、claim/renew/release、bind/unbind、control_window/adapter_input/control，见 server 的精确字段。

`/v2/state` 对 operator 返回 `source=data_plane=operator_limited_display`、`algorithm_input=false`、`state_projection_version=1`。`robots` 保留 `robot_id/team/role` 供选择；仅本会话当前至少持有一项有效 lease 的车附 hp/max_hp/ammo/heat/heat_max/alive/相对云台角。watch 不授予动态 HUD。公开顶层仅 episode/sim_time/sample_sim_time、phase、remaining_seconds/duration_seconds、winner、runtime_state 等已声明子集；不发未核验的 VP/金币/伤害图。own HUD 的 freshness 来自历史 sample_sim_time，权限由当前 `control.server_monotonic_s` 与 lease 判定，不能将历史画面/状态当作新采样。

`control.leases` 中自己有效通道 owner 为 session ID，可读该通道 input 与期限；其他占用统一 owner=`occupied`，空闲为 null，不发他人的 session ID、input 或绑定配置。自己的有效对应 binding 仅返回身份/activation metadata/lease_epochs，所有 config 都省略。历史 `applied_targets` 还需 consumption receipt 的 owner/epoch 与当前租约一致才返回对应自己通道，receipt 本身不外发。未知未来字段默认丢弃，已知标量键中的嵌套对象也不透传。spectator 完整审计需要显式 audit grant，不能由 body role 升级。

HTTP `/v2/sessions` 必须使用 server-owned local manifest 的 credential，角色与 robot scope 由服务端确定；无 policy/credential 拒绝。operator watch 与写端点均 hard-check scope，roster/capabilities/catalog 同步限制。`/frame` 只发实际 JPEG、静态 K/D/外参与原帧身份/时钟，不含 capture own pose/odom；内部算法 sensor packet 保持原捕获本车传感器。OfflineRuntime 继承投影，只额外允许 scheduler/lifecycle 白名单，不发 native 私有异常路径。SDK 与字段说明见 [ADMISSION.md](ADMISSION.md)。

固定原 Qt 提交 `0cedf99` 的 v2 parser 强制全车 xy/动态字段与旧 truth source，未经适配会明确失败；不得填虚构 xy=0 或假 HUD 来兼容。客户端需应用显式版本/哈希记录的 operator state 补丁：未 claim 只用静态 roster 和实际相机完成选择/claim，lease 有效后才消费本车 HUD，缺失分数显示 unknown。补丁构建与 GUI 可见交互需另行实测，本文件不宣称旧 Qt 无改动兼容或 GUI 已通过。

strict profile 下 `/v2/control` 的示例请求（epoch/window 必须取当前服务回复，不可照抄）：

```json
{"robot_id":"red_sentry","channel":"motion","lease_epoch":3,"seq":0,"window_id":7,"valid_for_s":0.1,"value":{"frame":"base_link","vx_mps":0.25,"vy_mps":0.0,"wz_rps":0.0}}
```

手动 motion 现有上限为各轴 ±3 m/s、yaw ±4 rad/s；JSONL navigation action 上限不同：各轴 ±1 m/s、速度范数 ≤1 m/s、yaw ±2 rad/s。手动 gimbal 为 yaw [-3.14,3.14]、pitch [-0.4,0.5] rad；算法 gimbal validator 范围更宽，但 backend 再查物理限位。它们不可作为通用车辆的冻结限位；车辆映射需单独声明。

JSONL 一行一个 UTF-8 JSON，stdout 只用于协议并及时 flush；本地 manifest 固定命令/cwd/能力。reset 示例：

```json
{"schema":"polar.sim.adapter.jsonl.v1","op":"reset","context":{"episode":1,"robot_id":"red_sentry","binding_epoch":2},"config":{}}
```

act 请求包为 `{schema,op:"act",observation:OBSERVATION}`。以下是无目标真值的完整 action 回复示例，六项身份必须回显当前 observation，不能发送示例里的虚拟期限：

```json
{"schema":"polar.sim.adapter.jsonl.v1","op":"act","ok":true,"action":{"schema":"polar.sim.action.v2","robot_id":"red_sentry","episode":1,"binding_epoch":2,"observed_seq":9,"sim_time":0.2,"wall_deadline":123.45,"kind":"aim","mode":"gimbal_target","command":{"frame":"base_link","yaw_rad":0.0,"pitch_rad":0.0,"active":false,"confidence":null,"fire_permission":false}}}
```

JSONL 请求最大 12 MiB、回复 64 KiB、最多一笔事务；reset 最长 2 s，act 不晚于 250 ms 或既有 server deadline 中较早者。故障杀掉自有子进程，显式 rebind 才恢复，无静默代打。退出由 wrapper `close()` 管理，当前不定义 JSONL `op=close`。

## 错误与待冻结项

HTTP 拒绝格式是 `{"accepted":false,"error":"原因码"}`，当前拒绝响应不带成功 schema。400 用于结构/数值错误，401 会话失效，403 只读/来源权限，404 未知机器人/插件/端点，409 为租约冲突与状态/期限冲突，413 超限，429 容量不足。示例码：`lease_occupied`、`lease_mismatch`、`stale_seq`、`expired_control_window`、`binding_mismatch`。算法 validator 用 `ContractError`，JSONL 异常由 wrapper fail closed；尚无统一跨 HTTP/JSONL/硬件错误码表与可重试分类。

运行时 stop 先撤销控制权限。reviewed native lifecycle 通过持久取消事件停止 owned process，迟到的 reset/Popen 不能恢复推理；worker 单独拥有 wait/pipe close。live slots 与 offline worker 共用一次 1.5 s shutdown join 预算，等待发生在关闭阶段。可信审计的 `shutdown_status` 记录 `clean/unfinished_slots/lifecycle_errors/join_budget_s/join_elapsed_s`；任何未退出线程或关闭异常将 runtime 标为 `adapter_shutdown_incomplete`，离线终态改 HALTED。未知 Python 插件无法强行终止时必须记录关闭失败；这不构成恶意插件沙箱。80 ms 相机与 150 ms 授权期限未改变。

T01 退出前需确认实际负责人、目标机、规则/传感器配置与质量阈值，并解决或列为有负责人的接口决策；T07/T09/T13 的能力缺口须按各自测试实现。显式[PB导航桥](PB_NAVIGATION_BRIDGE.md)及[Windows→WSL入口](PB_WSL_NAVIGATION.md)已有真实仿真点云/IMU→自家Point-LIO/SLAM/Smac/PID、生产Gate和独立外部动作客户端的单哨兵/单代/单目标局部SIL证据；这未改变默认DTO，也未完成通用ROS接口或传感器标定。未完成：完整版本协商、通用map/lidar/关节规范、独立arm、真实车辆IMU/编码器/点云标定、默认理想里程计移除、完整任务/多实现、跨机时钟/TLS/多人实测、视频/HUD/裁判/输入频率与压缩/排序/背压/掉包规范、统一比赛证据清单、通用ROS 2/串口桥和硬件监督器。

局部验证命令：`python -m unittest rm_match.platform_v2.test_state_projection`。9 项 CPU/实际 loopback HTTP 测试覆盖本车/敌车真值哨兵、未知未来字段、嵌套透传、他人输入/绑定配置、release/expired lease 立即撤销 HUD、新 owner 不继承历史命令、spectator 快照不变。这是响应边界验证，不含渲染、GUI、native 推理、跨机或完整比赛。
