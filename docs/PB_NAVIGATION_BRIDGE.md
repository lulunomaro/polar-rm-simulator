# 北极熊导航传感器桥（可选，未通过导航验收）

目标是 [SMBU-POLARBEAR/pb2025_sentry_nav](https://gitee.com/SMBU-POLARBEAR/pb2025_sentry_nav)。较旧 `pb_rm_simulation` 的 Humble/Livox 接口仅作对照，不将现有 WSL 克隆和已偏离的子模块版本视为已冻结上游。新版控制器和完整定位/导航链的接口、构建与真实运行仍需核验。

`pb_navigation_adapter.register_pb_navigation(registry, manifest)` 是可信本地注册入口；示例在 `examples/pb_navigation_adapters.json`。HTTP 只能选择已注册 ID 和空 config，不能指定进程命令、ROS 话题或文件路径。注册描述声明 `observation_profile=pointcloud_imu_v1`、`required_sensors=[pointcloud,imu]`。它复用 JsonLineAdapter 的原始主机时钟、2 秒 reset 门限、响应期限与进程清理；新 hook 只允许显式 action/status 二选一。

示例命令要求子进程自己能导入 ROS 和 Livox 已生成消息。主机继续清除 PYTHONPATH/PYTHONHOME，不能靠父进程已导入 rclpy 冒充新子进程启动通过。已在 owned Humble venv 通过固定 .pth 做真实新子进程验证；Windows→WSL 的可靠进程托管和实际 PB 全链尚未验证。缺依赖时明确失败，无替代 ROS 实现。

## 传感器与时钟

- 输入是 `polar.sim.navigation-observation.v1`，原六身份字段完全保留。没有 ideal odometry、世界坐标、敌方状态或地图真值。
- `/livox/lidar` 为 Livox `CustomMsg`：header/timebase 是实际 scan 开始仿真纳秒，逐点 offset_time 是相对开始的真实采样纳秒；tag/line/reflectivity 原样传递。不会复制旧模拟插件以 CPU 墙钟生成 offset 的做法。
- `/livox/lidar/pointcloud` 是明确自定义的 PointCloud2 布局：20 字节、小端，x/y/z FLOAT32 位于 0/4/8，offset_time UINT32 位于 12，reflectivity/tag/line UINT8 位于 16/17/18，最后一字节零。它不是上游 driver 的 FLOAT64 timestamp 布局；当前适配 CustomMsg，不能声称任意 PointCloud2 消费者兼容。
- `/livox/imu` 为实际 gyro/accelerometer，每个原始样本使用自己的仿真 stamp，单位 rad/s、m/s²。orientation_covariance[0] = -1 表示没有 orientation estimate；不填入仿真真值姿态。相邻扫描共用的边界 IMU 样本只发布一次。
- `/clock` 使用扫描结束仿真时间；仅发布输入校准对应的静态 `base_link→livox_frame`。map/odom 到 base 的动态 TF 必须来自真实 LIO/SLAM。
- IMU depth 1024、点云 depth 1，均有界；控制身份话题 reliable depth 1。仅本地 ROS domain 81（可由本地 manifest 固定修改），进程级 LOCALHOST，不改变全局设置。这不提供 SROS2 或恶意本地进程隔离。

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

`pb_navigation_workspace.prepare_controller()` 已提供固定 `0b95c800e61f8abbdddfcf6b07f8838b842724c3` 控制器的 owned 源 overlay：在原 `computeVelocityCommands()` 入口保存 context，并在实际速度计算完成、碰撞检查通过后的返回点发结果；保留原 PID/路径/碰撞算法。`pb_controller_context.hpp` 只接受已审 Point-LIO raw-input→MeasGroup→实际估计输出传播的 `/polar/pb/localization` 事件（原六身份、cloud_frame_id、原窗口、实际定位 stamp），要求它与实际 compute pose.header.stamp 匹配。普通 Odometry 或“最新定位”不能授权动作。当前 overlay 尚未编译或实际闭环验证。

桥和控制器必须显式冻结 expected_robot_id/episode/binding_epoch。示例仅 red_sentry、episode 0、binding epoch 1。控制器 overlay 默认 disabled；开启需要 `polar_sourced.enabled=true`、对应固定 robot/episode/epoch、use_sim_time=true 和实际 body 控制 frame base_link。可信 supervisor 必须为一次 generation 启动全新的 LIO/controller/bridge 与隔离 namespace/进程，结束回收整棵 owned 栈。变代必须整体重启；没有自动重启实现时不能沿用旧 ROS 栈。仿真时间回零会复用旧 stamp，仅清 pending 不足以证明旧定位不存在。

桥不订阅裸 `/cmd_vel`。收到裸 Twist 后取“最新请求”重贴身份不能证明因果关联。当前目标 2025 的 fake_vel_transform 会叠加默认 3.14 rad/s 自旋；首个 SIL 不接入它或 velocity_smoother，显式禁用默认 spin（设 0），只读取可信 controller compute 返回结果。旧 2024 的角速度替换行为属于历史对照，不能混入 2025 接入说明。超过 SDK 速度范围的动作拒绝，不偷偷截断。

每次仅一个 pending 观测/一个结果；未知字段、旧序号、旧 epoch、旧点云、未来定位/计算 stamp、超期和重复结果拒绝。ROS 等待预算默认 50 ms；如果没有实际结果，返回原六身份的 `polar.sim.navigation-status.v1`，状态为 `pending_localization` 或 `no_associated_command`，不包含 command。Runtime 对已声明导航 profile 的等待状态清除旧输出并保留实例，让 LIO 获得后续扫描；真实子进程超时/异常仍失败，不延长主机期限。

当前测试：显式 Fake transport 的传感器字节/时间/身份/过期拒绝；真实 JSONL fixture 子进程的等待与资源清理。这些不是实际 DDS、PointLIO、Nav2 或哨兵运动验收。

`tools/prepare_pb_humble_interfaces.py` 从固定 Git 对象生成新的 owned workspace，拒绝版本/hash/patch anchor 不匹配及 link/路径越界。默认锁定 2025 Livox driver `524e14a1ec714e427bde729a8f869bb7acd8507d`，仅原 CustomMsg/CustomPoint 的 rosidl 接口包，不构建硬件 SDK/driver。首个真实接口构建 `artifacts/pb-humble-interfaces-actual-20261013` 成功（46.84 秒），来自对照 driver `8cb0fa5...`；`TARGET2025_MESSAGE_EQUIVALENCE.json` 独立证明两版原消息字节相同，不改旧构建来源或报告。

`tools/diagnose_pb_humble_sensors.py` 有两个独立验证范围：默认 explicit fixture 使用实际 DDS 和原 JsonLineAdapter 2 秒 reset；`--archived-observation` 仅检查实际 DDS/codec，原 gzip DTO 的 capture/六身份/wall_deadline 完全保留，不调用 host act authority，不允许产生动作。两者均没有 LIO/Nav2 算法，不能作为哨兵导航验收。

真实 Humble/Fast DDS 结果已保存（rclpy 3.3.21、Python 3.10.12、当时系统 NumPy 1.21.5，尚未证明 NumPy 2 环境 ABI）：

- `artifacts/pb-humble-dds-fixture-actual-20261013/RESULT.json`：原 JsonLineAdapter 新子进程 reset 0.806705 秒，50 ms ROS 等待后返回 pending_localization；9 项字节/时间/身份/无虚构动作检查通过，child reaped、管道/IO线程/DDS peer/context 全部关闭。
- `artifacts/pb-humble-dds-archived-actual-20261013/RESULT.json`：真实 MuJoCo 归档首帧 584 点和 51 IMU 样本通过 actual DDS，CustomMsg/PointCloud2 的重建字节 SHA 一致，原 capture .1 和 wall_deadline 43088.3520294 保留；9 项检查和资源清理通过。它是 archived codec 验证，未执行 host deadline authority，不代表当时实时导航可控制。
