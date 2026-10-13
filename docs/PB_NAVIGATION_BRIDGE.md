# 北极熊导航传感器桥（可选，单次 SIL 局部通过）

目标是 [SMBU-POLARBEAR/pb2025_sentry_nav](https://gitee.com/SMBU-POLARBEAR/pb2025_sentry_nav)，固定源与 gitlink 见 [来源审计](POLARBEAR_NAVIGATION_SOURCE.md)。较旧 `pb_rm_simulation` 的 Humble/Livox 接口仅作对照，不将现有 WSL 克隆和已偏离的子模块版本视为已冻结上游。第八轮在 Linux 单车/单代/30 秒范围内，真实点云和 IMU 经定位、地图、规划与原控制器，产生 SDK 授权的非零物理运动消费。完整任务、定位精度与跨平台部署仍未验收。

`pb_navigation_adapter.register_pb_navigation(registry, manifest)` 是可信本地注册入口；示例在 `examples/pb_navigation_adapters.json`。HTTP 只能选择已注册 ID 和空 config，不能指定进程命令、ROS 话题或文件路径。注册描述声明 `observation_profile=pointcloud_imu_v1`、`required_sensors=[pointcloud,imu]`。它复用 JsonLineAdapter 的原始主机时钟、2 秒 reset 门限、响应期限与进程清理；新 hook 只允许显式 action/status 二选一。

示例命令要求子进程自己能导入 ROS 和 Livox 已生成消息。主机继续清除 PYTHONPATH/PYTHONHOME，不能靠父进程已导入 rclpy 冒充新子进程启动通过。已在 owned Humble venv 通过固定 .pth 做真实新子进程验证；后述 Linux bounded SIL 已局部通过，Windows→WSL 的可靠进程托管和完整 PB 导航任务仍未验收。缺依赖时明确失败，无替代 ROS 实现。

## 传感器与时钟

- 输入是 `polar.sim.navigation-observation.v1`，原六身份字段完全保留。没有 ideal odometry、世界坐标、敌方状态或地图真值。
- `/livox/lidar` 为 Livox `CustomMsg`：header/timebase 是实际 scan 开始仿真纳秒，逐点 offset_time 是相对开始的真实采样纳秒；tag/line/reflectivity 原样传递。不会复制旧模拟插件以 CPU 墙钟生成 offset 的做法。
- `/livox/lidar/pointcloud` 是明确自定义的 PointCloud2 布局：20 字节、小端，x/y/z FLOAT32 位于 0/4/8，offset_time UINT32 位于 12，reflectivity/tag/line UINT8 位于 16/17/18，最后一字节零。它不是上游 driver 的 FLOAT64 timestamp 布局；当前适配 CustomMsg，不能声称任意 PointCloud2 消费者兼容。
- `/livox/imu` 为实际 gyro/accelerometer，每个原始样本使用自己的仿真 stamp，单位 rad/s、m/s²。orientation_covariance[0] = -1 表示没有 orientation estimate；不填入仿真真值姿态。相邻扫描共用的边界 IMU 样本只发布一次。
- `/clock` 使用扫描结束仿真时间；仅发布输入校准对应的静态 `base_link→livox_frame`。map/odom 到 base 的动态 TF 必须来自真实 LIO/SLAM。
- IMU depth 1024、点云 depth 1，均有界；请求身份 reliable depth 8 对齐 source 订阅，结果 reliable depth 1。桥仍只接受一个 pending 的原六身份结果，不用排队身份授权新动作。仅本地 ROS domain 81（可由本地 manifest 固定修改），进程级 LOCALHOST，不改变全局设置。这不提供 SROS2 或恶意本地进程隔离。

[ROS 官方 Imu 定义](https://github.com/ros2/common_interfaces/blob/humble/sensor_msgs/msg/Imu.msg)规定未知姿态使用 covariance[0]=-1；[PointCloud2 定义](https://github.com/ros2/common_interfaces/blob/humble/sensor_msgs/msg/PointCloud2.msg)要求显式字段和字节布局。[Livox 官方消息](https://github.com/Livox-SDK/livox_ros_driver2/tree/master/msg)定义 timebase 与逐点 offset_time；最终上游固定版本需另行记录。

## 控制关联，不能重贴旧速度

桥发布 `/polar/pb/request`（String JSON），schema 为 `polar.sim.pb-navigation-request.v1`：adapter_id、原六身份、cloud_frame_id、acquisition_start_ns/end_ns。`wall_deadline` 是主机绝对时钟值，仅原样回显，ROS 进程不拿它减自己的 monotonic。

桥只接收 `/polar/pb/result` 的 `polar.sim.pb-navigation-result.v1`：

```text
{schema, adapter_id,
 action: 完整原 action.v2（velocity_body/base_link，原六身份），
 source: {cloud_frame_id, localization_stamp_ns,
          controller_stamp_ns, controller_id}}
```

必须在真实控制器计算点传播同一请求身份和对应点云帧；source 的定位 stamp 必须处于该扫描的采样窗口，计算 stamp 不能超出观测 sim_time。`sourced_result()` 只是受审控制器调用的封装函数，不能证明外部消息确实执行了算法。

`pb_navigation_workspace.prepare_controller()` 已提供固定 `0b95c800e61f8abbdddfcf6b07f8838b842724c3` 控制器的 owned 源 overlay：在原 `computeVelocityCommands()` 入口保存 context，并在实际速度计算完成、碰撞检查通过后的返回点发结果；保留原 PID/路径/碰撞算法。`pb_controller_context.hpp` 只接受已审 Point-LIO raw-input→MeasGroup→实际估计输出传播的 `/polar/pb/localization` 事件（原六身份、cloud_frame_id、原窗口、实际定位 stamp），要求它与实际 compute pose.header.stamp 匹配。普通 Odometry 或“最新定位”不能授权动作。该 overlay 已实际编译，第八轮已验证一条真实定位→规划→动作→物理消费链；旧失败和安全拒绝保持。

桥和控制器必须显式冻结 expected_robot_id/episode/binding_epoch。示例仅 red_sentry、episode 0、binding epoch 1。控制器 overlay 默认 disabled；开启需要 `polar_sourced.enabled=true`、对应固定 robot/episode/epoch、use_sim_time=true 和实际 body 控制 frame base_link。可信 supervisor 必须为一次 generation 启动全新的 LIO/controller/bridge 与隔离 namespace/进程，结束回收整棵 owned 栈。变代必须整体重启；没有自动重启实现时不能沿用旧 ROS 栈。仿真时间回零会复用旧 stamp，仅清 pending 不足以证明旧定位不存在。

桥不订阅裸 `/cmd_vel`。收到裸 Twist 后取“最新请求”重贴身份不能证明因果关联。当前目标 2025 的 fake_vel_transform 会叠加默认 3.14 rad/s 自旋；首个 SIL 不接入它或 velocity_smoother，显式禁用默认 spin（设 0），只读取可信 controller compute 返回结果。旧 2024 的角速度替换行为属于历史对照，不能混入 2025 接入说明。超过 SDK 速度范围的动作拒绝，不偷偷截断。

每次仅一个 pending 观测/一个结果；未知字段、旧序号、旧 epoch、旧点云、未来定位/计算 stamp、超期和重复结果拒绝。ROS 等待预算默认 50 ms；如果没有实际结果，返回原六身份的 `polar.sim.navigation-status.v1`，状态为 `pending_localization` 或 `no_associated_command`，不包含 command。Runtime 对已声明导航 profile 的等待状态清除旧输出并保留实例，让 LIO 获得后续扫描；真实子进程超时/异常仍失败，不延长主机期限。

单位测试使用显式 Fake transport 检查传感器字节/时间/身份/过期拒绝，另有真实 JSONL fixture 子进程的等待与资源清理。下述 actual DDS 和整栈实测分别保存，不能将单位 fixture 计作 Point-LIO/Nav2 或哨兵运动验收。

`tools/prepare_pb_humble_interfaces.py` 从固定 Git 对象生成新的 owned workspace，拒绝版本/hash/patch anchor 不匹配及 link/路径越界。默认锁定 2025 Livox driver `524e14a1ec714e427bde729a8f869bb7acd8507d`，仅原 CustomMsg/CustomPoint 的 rosidl 接口包，不构建硬件 SDK/driver。首个真实接口构建 `artifacts/pb-humble-interfaces-actual-20261013` 成功（46.84 秒），来自对照 driver `8cb0fa5...`；`TARGET2025_MESSAGE_EQUIVALENCE.json` 独立证明两版原消息字节相同，不改旧构建来源或报告。

`tools/diagnose_pb_humble_sensors.py` 有两个独立验证范围：默认 explicit fixture 使用实际 DDS 和原 JsonLineAdapter 2 秒 reset；`--archived-observation` 仅检查实际 DDS/codec，原 gzip DTO 的 capture/六身份/wall_deadline 完全保留，不调用 host act authority，不允许产生动作。两者均没有 LIO/Nav2 算法，不能作为哨兵导航验收。

真实 Humble/Fast DDS 结果已保存（rclpy 3.3.21、Python 3.10.12；前两轮为历史 NumPy 1.21.5 环境）：

- `artifacts/pb-humble-dds-fixture-actual-20261013/RESULT.json`：原 JsonLineAdapter 新子进程 reset 0.806705 秒，50 ms ROS 等待后返回 pending_localization；9 项字节/时间/身份/无虚构动作检查通过，child reaped、管道/IO线程/DDS peer/context 全部关闭。
- `artifacts/pb-humble-dds-archived-actual-20261013/RESULT.json`：真实 MuJoCo 归档首帧 584 点和 51 IMU 样本通过 actual DDS，CustomMsg/PointCloud2 的重建字节 SHA 一致，原 capture .1 和 wall_deadline 43088.3520294 保留；9 项检查和资源清理通过。它是 archived codec 验证，未执行 host deadline authority，不代表当时实时导航可控制。
- `artifacts/pb-humble-dds-numpy2-actual-20261013/RESULT.json`：owned venv 的 NumPy 2.2.6 环境，独立 namespace 的实际 DDS fixture 9 项检查与清理通过，新子进程原 2 秒 reset 实测 1.298072 秒。真实生成消息 ABI 另通过序列化/反序列化检查，不能由此推出 native cv2 或导航闭环兼容。

## 真实构建与单代 SIL：2026-10-14

实际源码来自当前 Windows 工作区的固定对象与 reviewed overlay；运行环境是 WSL Ubuntu 22.04 / ROS2 Humble。本节早期 SIL 的 MuJoCo、SDK、桥与 ROS 栈均在 Linux 环境运行；后续另提供[Windows专用入口及实际3/4轮验证](PB_WSL_NAVIGATION.md)，不能混用两个环境的记录。每轮使用 DOMAIN 84、新 namespace、新 generation 和全新 owned 进程；不喂假传感器、不预热算法、不刷新原时刻。

Point-LIO、loam_interface、sensor_scan_generation、terrain 以及 PB 控制器/插件已经真实编译。PB 原 `liblayers.so` 与 Nav2 基类库同 SONAME，实际加载出现 `ObstacleLayer::deactivate` 未解析；仅将 owned 输出库与 XML 绑定改为 `libpb_intensity_layers.so`，原类与算法源字节保持。独立 03 插件构建 412.657 秒成功；02 控制器复用同 SHA 的已编译对象，独立 resume 23.838 秒成功，旧 combined 600 秒超时报告保留。构建工具默认资源预算改为 1800 秒，可选 60–3600 秒；这不改变 SDK 的 2 秒 reset / 150 ms 控制期限。

Point-LIO 04 在新的 owned workspace 完成真实构建（约 25.6 分钟），ELF `ff6e3bde78b74edde2875984a3dc8687a6b8a65bfc172e52dbbb74630794005b`；其他已核验 TF 包明确复用旧 ELF。新 source join 将 raw/context 分开有界等待，只配 exact 原 stamp/timebase/窗口；过界清理未配对输入，不重贴身份、不延长 host 控制期限。旧 02/03 构建与失败保留，不能将 04 编译成功记为 LIO 定位成功。

三个原算法 ELF 的实际 `ldd` 与 `RTLD_NOW` 加载通过。单独插件类探针编译超过 180 秒的失败保留；后续真实 Nav2 栈已成功配置 Smac、`pb_nav2_costmap_2d::IntensityVoxelLayer` 和 `pb_omni_pid_pursuit_controller::OmniPidPursuitController`，提供了实际插件实例化证据，但不是算法控制成功。

[单代 SIL 冻结证据](validation/pb_navigation_sil_20261014/README.md)保存 attempts 1–6 的失败、源快照和清理；六轮均未通过闭环：

| 实验 | 实际结果与边界 |
| --- | --- |
| attempts 1–4 | 入口/栈启动等失败保留；无导航物理消费通过结论 |
| attempt5 | 30 秒、15000 物理步、RTF 0.999315；543 次 SDK 原 150 ms 激活正常。PB reset 2.0448 秒超过原 2 秒，queue.Empty 后持续故障；0 ROS 请求/定位/动作 |
| attempt6 | 子进程实际 reset ACK 成功；module→ACK 1.370686 秒，ROS types import 1.099678 秒、node 构造 0.131157 秒、图发现约 0.000986 秒，订阅计数 [1,1,2,1]。后续 SDK lease_mismatch，运行 3.472802 秒/1016 步，0 定位/地图/动作消费 |

attempt6 的物理最大停顿为 40.717807→41.820299，即 1.102492 秒；定位到导航 worker 误导入 native 图像模块与 NumPy2/cv2 ABI 警告。修复已通过独立隔离回归，后述 SIL7 真实定位成功不重判旧失败，也不等于导航动作通过。原 2 秒/1 秒图等待/150 ms 门禁仍保持，每轮使用新目录保存真实结果。

可选环境变量 `POLAR_PB_BRIDGE_PHASE_FILE` 仅用于启动诊断：指向仓库 `artifacts` 内已有父目录下的绝对新文件，拒绝路径逃逸、链接及重复文件；最多 64 条固定阶段、PID、本机时钟和有限订阅计数，无凭据、环境或传感器正文。记录 ROS import/init、graph ready、reset ACK 与正常 cleanup；被 host 强制终止时缺少末尾 cleanup 不能证明资源已回收，仍以实际进程/线程清理记录为准。Linux phase clock 不用于改写 host deadline。

静态 TF 改为直接发布 `TFMessage`，保留 Humble 官方 broadcaster 的 KEEP_LAST/depth1、TRANSIENT_LOCAL、RELIABLE 和同一实测 `TransformStamped`，避免无用 buffer/client/listener 整包导入。fresh 子进程纯导入对照显示该额外阶段约 70–150 ms，直接消息约 1 ms；公共 ROS 类型冷导入仍可能超过 2 秒。首轮实际 DDS 原 2 秒 reset 2.036241 秒失败，尚未到数据/QoS检查；失败与完整清理保留于 `artifacts/pb-humble-tfmessage-evidence-20261014`。

owned ext4 环境逐文件核验并复制 venv、受信前缀、compat 与 Livox 接口；14,899 个文件、1,621 个目录、186 个链接及 mode 均有身份账本。仅派生 .pth 修改为明确的新路径，原环境/报告/算法 ELF 保留。FINAL ENV SHA `d60183ebf62d520c72eb20b84207fa4344d8f17183bb0df8eee92f97b7f981ee`，三次 fresh 进程导入、八种实际 ROS 消息序列化和六车模型零物理步探针均通过；未初始化 DDS、未预热 NN，postprobe 未发现输入变化或残留进程。

`artifacts/pb-humble-tfmessage-ext4-20261014-attempt2/dds/RESULT.json` 的真实 DDS fixture 九项全部通过：原 JsonLineAdapter fresh-child reset 0.454714 秒、act 0.051592 秒，51 个 IMU 样本、原字节/时钟/身份/静态实测 TF 一致，没有虚构动作；child/IO/peer/context 全部关闭。phase 内 ROS imports 0.158634 秒、node 构造 0.040355 秒、graph 约 0.000865 秒。它没有 physics/LIO/Nav2，不代表导航控制闭环。

额外 QoS wrapper 退出 2 的原报告单独保留：本轮 Fast DDS endpoint 图信息确实显示 TF RELIABLE/TRANSIENT_LOCAL、request RELIABLE/VOLATILE，但 history 为 UNKNOWN、depth 为 0，不能测得队列深度。代码与单位回归配置的 KEEP_LAST、TF depth1/request depth8，与图中实际观察到的可靠性/持久性分开记录；不将 UNKNOWN 改写为 1/8，也不因此覆盖已通过的九项 DDS 结果。这项 DDS 验证不签收后述 SIL7。

## 第七轮实际链与后续诊断

[永久 runtime 证据](validation/pb_navigation_runtime_20261014/README.md)包含 89 个逐字节记录，分别保存 Point-LIO04、ext4、导入、DDS 与实际 SIL7，不能合并成一次运行。SIL7 使用 04 与冻结 ext4 ENV：15000 步/30 秒仿真、RTF 0.999506，293 个原身份请求、290 个真实 LIO 定位事件、58 个地图消息；Smac 成功返回 14-pose 路径（status4），FollowPath 接受后因 FailedProgress 终止（status6）。控制器 source result、有效运动消费均为 0，整体 SIL 失败；源与资产 SHA 未变、九组算法进程与 runtime 全部回收。输入未包含 ideal pose。

请求与定位的原六身份及窗口一致；observer 显示 287/290 个定位到达时已有后续请求，延迟约 96–148 ms。它不证明 C++ callback 顺序，也不能用于把旧定位贴给新请求。当前 ControllerContext 的单 pending/清定位缓存、pose stamp exact匹配、compute sim_window 上限均保留，未放宽 bridge 50 ms 或 SDK 150 ms。

`polar_sourced.diagnostics` 默认 false，开启后固定最多 256 条元数据日志，记录真实 callback 的 pending/source seq、拒绝字段、pose/computed ns、原 sim window、定位戳数量/边界与速度 norm；不记录传感器正文或凭据。FakeROS 类型下实际编译原头文件验证了开关前后相同输出/安全拒绝与日志上限；新控制器独立 fresh 构建 driver 195.130948 秒成功，ELF `d4539050e0959270080044ace965a525f7653b0ef0a1715b031a06d91e156dbd`，`ldd` 与 `RTLD_NOW` 通过。旧 02 ELF/日志/报告和上游算法源保持字节一致；此构建没有执行控制器计算或导航。

真实 rclcpp DDS 微夹具显示同一 51 个原 stamp 的 IMU burst，非 exhaustive `spin_some` 消费耗时 100.102 ms；有界 1 ms `spin_all` 为 188.399 µs。该夹具使用显式 synthetic消息，不是物理传感器或 SIL；Point-LIO05 已完成独立构建与依赖/源审计，ELF `fd2b50c7a2d1993c80fc251f201126af6d3775a813851102108dfb65e521471f`，原 500 Hz、样本、滤波和时窗保持。后述第八轮独立验证新链，不用微夹具时延重判 SIL7。

[dispatch 质量记录](validation/quality_navigation_dispatch_20261014/README.md)：1144 passed、37 明确 skip、685 subtests，preset/source/interface 通过且检查期间 source 未变；前轮真实 camera35 checks 独立保留，本轮不重复。它不替代实际导航、Windows↔WSL入口或完整比赛验收。

## 第八轮：单次 Linux SIL 局部通过

[第八轮冻结证据](validation/pb_navigation_sil_20261014_attempt8/README.md)：实际退出 0，30 秒/15000 步，RTF 0.9995295364；294 原身份请求、292 定位事件、59 地图消息，Smac 返回 14-pose 路径（status4），FollowPath 成功（status4）。18 个原控制器 source result 对应 779 个非零物理运动消费步，原 sensor/SDK 权限、wall/sim期限与原身份审计 errors=[]；fire_permission=false。source 不变、runtime clean join 0.013611 秒，九个 owned 算法组全部回收且资产身份不变。七轮旧失败保持原结果。

目标由实际算法 `map→base_link` 估计 pose 沿 map 的 x 方向偏移 1 m、y 保持不变生成；它不是基于仿真真值的目标。退出后的真实 qpos `[1.434108,-0.0204169,0.0000558]` 仅用于隔离评测，没有进入算法输入，也不能据此声称定位精度、所有导航目标或障碍场景通过。本次证据限 red_sentry、单 episode/binding、单目标与本机 Linux/Humble；完整任务、动态障碍/恢复/漂移、多车比赛、第二机器和硬件仍待验证。Windows专用入口的后续局部验证见[独立记录](PB_WSL_NAVIGATION.md)。

`stack/controller_server.log` 前 256 条诊断已达到上限：request_installed42，localization_accepted28，localization_context_mismatch13，localization_no_pending15，begin_accepted18，begin_no_pending35，begin_pose_not_localized26，finish_no_request61，finish_published18。18 发布与实际 source result 数一致；该有界前缀未出现 velocity/clock/pending_changed 的 finish 拒绝，不代表日志停止后的所有回调均已统计。pose不匹配和旧 context 仍安全拒绝。

独立复核将全部 779 条消费关联到原 source result 和 SDK ACK，0 adapter fault，消费时 capture age 27.298–148.928 ms 保持原 150 ms 门限。292 个定位事件逐字段/类型匹配原请求；observer 请求→定位到达延迟 P50 5.532 ms、P95 6.913 ms、最大 10.614 ms，属于接收代理测量。实际 C++ 的 186 个采样报告记录批量 callback 最大数 25–50、已报告区间最大 dispatch 1.206 ms；1 ms 是非抢占执行预算，不是 CPU 硬上限，10 Hz 采样也不能覆盖所有区间。原 ROS 日志有 Reached the goal 旁证，但没有完整记录 path/goal TF；14-pose 与目标来源按已冻结工具结果记录，不声称由 raw ROS 独立重算。

Linux 复现入口如下，环境与 stack-config 必须由本机的已核验依赖、固定源和 owned 构建生成；先核对全部源/ELF/配置 SHA，再选择新的输出目录。归档不附带可直接在第二机器运行的私有 `/root` 工作区。

```sh
cd /path/to/polar-rm-simulator
/path/to/verified-humble-venv/bin/python tools/qa_pb_navigation_sil.py \
  --environment /path/to/generated/ENVIRONMENT_COMPAT_FINAL.json \
  --stack-config /path/to/generated/pb-navigation-sil-config.json \
  --out artifacts/pb-navigation-sil-fresh --seconds 30 --diagnostics --run
```

实际本轮 config04 SHA `affba380753b6b8eac9505098fd0bf9d8a4457a4ec2892c09c80fb3da62d5c26`，FINAL ENV SHA `d60183ebf62d520c72eb20b84207fa4344d8f17183bb0df8eee92f97b7f981ee`；其中绑定 Point-LIO05 `fd2b50c7...`、诊断控制器 `d4539050...`、原算法 source/build/ELF 审计及插件03。完整路径与字节身份以本轮 RESULT/PLAN/config 构建引用为准，不能只改路径复用旧身份。`--diagnostics` 仅打开有界元数据记录，不改变 2 秒 reset、1 秒图等待、50 ms ROS 等待或 150 ms 控制门限。
