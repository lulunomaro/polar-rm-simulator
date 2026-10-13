# 北极熊哨兵导航固定源码审计

审计日期：2026-10-13。当前优先接入 [pb2025_sentry_nav](https://gitee.com/SMBU-POLARBEAR/pb2025_sentry_nav)，目标平台为 Ubuntu 22.04 / ROS 2 Humble。旧 [pb_rm_simulation](https://gitee.com/SMBU-POLARBEAR/pb_rm_simulation) 页面已标 Paused；2024 源码保留用于接口与扫描模式比较，不作为默认导航实现。本报告为源码审计与构建方案；尚未构建或运行导航，不代表定位、控制或实时闭环通过。

全部新克隆位于 `artifacts/polarbear-navigation-source-e05eb08e/`，固定身份、实际 checkout 状态及逐源码文件 SHA-256 在同目录 `SOURCE_MANIFEST.json`。均为 shallow/sparse clone；未执行上游安装脚本、硬件驱动或 Gazebo，未改用户旧目录。

## 固定身份

| 源码 | 固定提交 | 本地目录 |
|---|---|---|
| Gitee pb2025_sentry_nav main | `cb97fb07ace54fcc617ddb884227ef85fe4b8f85` | `pb2025_sentry_nav` |
| 2025 Point-LIO gitlink | `641424bf9d924f5ba0bd87ca9d91a4f148384925` | `point_lio2025` |
| 2025 Livox driver gitlink | `524e14a1ec714e427bde729a8f869bb7acd8507d` | `livox_ros_driver2_2025` |
| Omni PID pursuit controller gitlink | `0b95c800e61f8abbdddfcf6b07f8838b842724c3` | `pb_omni_pid_pursuit_controller` |
| pb_nav2_plugins gitlink | `d70977132936da4d758bd6e8c0771a8cf4861ad9` | `pb_nav2_plugins` |
| Gitee RM2024_SMBU_auto_sentry_ws | `07335f942ad37f0b55bbdde3186ed26993abe90f` | `RM2024_SMBU_auto_sentry_ws` |
| 上述总仓导航 gitlink | `c194997cb1ffb41ada91bba4002c3ba09d0e4cfd` | `pb_rm_simulation_sentry_branch` |
| 旧 PB master | `c6443f2d7969ba0f1d284536b4ef4bca8a773345` | `pb_rm_simulation` |
| 旧 PB Livox gitlink | `8cb0fa51e336bf8d89648a81ff1f54b98c625d28` | `livox_ros_driver2_humble` |
| 旧 PB FAST-LIO gitlink | `d43ba685e88e6da05178bdafde8d959cf00e0fad` | `FAST_LIO` |

2025 的依赖 gitlink 均来自总仓 `.gitmodules` 所指的官方 `SMBU-PolarBear-Robotics-Team` GitHub 仓库。尚未克隆、需要后续按功能选择的 gitlink：small_gicp_relocalization `d54b951a88df3642d53f795829a77878196007ae`、pointcloud_to_laserscan `5efaa8ba391bf4450a02cc5bb794b586c9f7d267`、pb_teleop_twist_joy `0335d20ccdff3411843a92f3fd17c6c5003e2144`。导航最小验证不需要遥控手柄。

2024 哨兵分支最新头为 `2803cd7a323c0d157828bede4d33b94e9f13baae`；这里实际 checkout 的是总仓指定 `c194...`，没有用最新头替换其身份。FAST-LIO 的 ikd-Tree 子模块未初始化，旧仓不能据此称为完整可构建源码。

## 传感器接口与实际时间

2025 实车配置的 Point-LIO 使用相对 topic `livox/lidar` (`livox_ros_driver2/msg/CustomMsg`) 与 `livox/imu` (`sensor_msgs/msg/Imu`)，`lidar_type=1`、`scan_line=4`。可按运行命名空间成为 `/red_sentry/livox/lidar` 等；ROS namespace 不会自动修改 TF frame 名称。Point-LIO `src/laserMapping.cpp:372` 使用 SensorDataQoS 订阅。实际 IMU 无方向解算值时必须声明 orientation unavailable；不能填仿真世界姿态。

两代锁定 Livox 消息定义相同，2025 `msg/CustomMsg.msg` 是：

```text
std_msgs/Header header
uint64 timebase
uint32 point_num
uint8 lidar_id
uint8[3] rsvd
CustomPoint[] points
```

`CustomPoint.msg` 是 `uint32 offset_time`、`float32 x/y/z`、`uint8 reflectivity/tag/line`。坐标米；offset_time 相对 timebase 的纳秒。Point-LIO `src/preprocess.cpp:348` 将 offset_time / 1e6 存为毫秒 curvature，随后扫描时间由 header 开始时间加实际点 offset 计算。必须保留真实扫描窗口与逐点采样时间，不能以发布时刻回填。

仿真应直接发布这套 CustomMsg，并可并行发布带明确字段定义的 PointCloud2 给其他消费者。Point-LIO 实车配置 `imu_time_inte=0.005`、`acc_norm=1.0` 面向原 200 Hz / g 单位硬件；本仿真 2 ms IMU / m/s² 需要独立配置 `imu_time_inte=0.002`、`acc_norm=9.81`、实际外参及 `use_sim_time=true`，不能照搬实车外参 `[-0.011,-0.02329,0.04412]`。关闭自动 extrinsic estimation 和任何自动时间偏移调整，初次实验不装载 prior PCD。

`preprocess.cpp:341` 和切帧路径 103 行的原筛选是 `line < N_SCANS` 且 `(tag & 0x30)` 为 `0x10` 或 `0x00`；`N_SCANS` 直接取 `preprocess.scan_line`。真实接入的 line 必须为 0–3，tag=0x10 合法；原 line=i%6 的六线诊断 profile 在 scan_line=4 下会被丢弃约三分之一，需改变传感器 profile 的线编号，不修改导航 filter。循环从索引 1 开始，并保留点抽样、blind/range 与重复点筛选。

2025 原 simulation 配置用 `velodyne_points` / lidar_type=2。`ign_sim_pointcloud_tool` 将 PC2 转成 XYZIRT，按 `point_id % horizon_scan * 0.1 / horizon_scan` 合成时间；ring 也按垂直角推算。该转换器不能放在真实 MuJoCo CustomMsg 前面。

## 定位、TF 与控制链

Point-LIO 发布 `aft_mapped_to_init` (Odometry)、`cloud_registered`、`cloud_registered_body`、`path` 等相对 topic。`src/laserMapping.cpp:265` 的 odometry frame 为 `camera_init`、child 为 `body`，其独立 TF 为 `camera_init -> aft_mapped`。Cloud 注册结果用 `camera_init`，stamp 为 `lidar_end_time`；body cloud 用 `body`。`publish_odometry_without_downsample=true` 时 odometry stamp 为逐点 `time_current`，否则为 `lidar_end_time`。

`loam_interface` 订阅上述 odom/cloud，使用已知 base-to-lidar 静态外参转换为 `odom` 系，输出 `lidar_odometry` / `registered_scan`；odometry 保留原 header.stamp。它不需要世界真实位姿。`sensor_scan_generation` 再同步 lidar odom/cloud，输出 `sensor_scan`、`odometry` 与动态 `odom -> base_frame`。默认配置使用 `base_footprint / front_mid360 / gimbal_yaw`；MuJoCo 接入需提供真实固定 mount，并选择实际 chassis 控制 frame。不能发布理想 world-to-robot TF。

以下原源码行为是接入时必须处理的关联缺口：

- `sensor_scan_generation.cpp:50` 使用队列 100 的 ApproximateTime，再以 cloud stamp 发布 odometry/TF；不能由这个复制后的 stamp 推断原 odometry 来自相同扫描。
- `getTransform()` 在 TF lookup 异常时返回单位变换（92–99）；接入应返回未定位并拒绝控制。
- `publishOdometry()` 用 steady-clock 回调到达间隔求速度（130–152），与模拟时间不一致；需使用同一有效 sim stamp 的差分，episode/reset 时清空历史。
- 原高频逐点 odometry 与 scan-end cloud 时间不同。首轮建议 `publish_odometry_without_downsample=false`，使用精确 scan-end 关联，并在 Point-LIO 输出处保留原 cloud_frame_id/episode/请求身份，不能仅在 downstream 把最新身份贴到旧 pose 上。

Nav2 中的真实全向控制器是固定仓 `pb_omni_pid_pursuit_controller/src/omni_pid_pursuit_controller.cpp:219`：`computeVelocityCommands(const PoseStamped &pose, const Twist &velocity, GoalChecker*)`。268 行将 `cmd_vel.header=pose.header`；270–272 行形成实际 body 速度 xy 和 angular.z；277 返回 TwistStamped。碰撞分支抛 PlannerException。原接口没有仿真的 lease/activation/episode/cloud 身份，因此只读 Twist 订阅无法安全获得这些信息。

可信 overlay 应在实际 compute 入口及返回处关联有界 original request context 与定位输出，证明 pose 的扫描来源；拒绝缺关联、错 episode、过期输入及 TF 缺失，结果携原六项控制身份、cloud_frame_id、定位 stamp、实际 compute stamp、body 速度。Nav2 获取 pose 的 TF 过程也需要验证其 stamp 的来源；`cmd.header=pose.header` 本身不足以证明。这是源码支持的插入点，尚未声称该 overlay 已实现或闭环通过。

`pb2025_nav_bringup/launch/navigation_launch.py` 的 actual remap：controller `cmd_vel -> cmd_vel_controller`；velocity_smoother 从 `cmd_vel_controller` 到 `cmd_vel_nav2_result`；原 `fake_vel_transform` 再输出 `cmd_vel`。原 fakeVel 读取 Float32 `cmd_spin`，默认 spin 为 3.14 rad/s，叠加角速度，并使用 ApproxTime local_plan/odom 和无 stamp 的 Twist 缓存；其激活时限还使用默认 `rclcpp::Clock().now()`。仿真安全动作接口不直接消费这条无身份链，也不启用原默认自旋。可保留 topic 供诊断，但控制应采用可信 compute 返回结果并通过原 authority 门禁。

## 扫描模式与旧仓比较

2024 Livox Gazebo 插件附 `scan_mode/mid360.csv`，按 azimuth / zenith 转射线方向；time 列虽读入，后续未用。插件 CustomMsg offset_time 是 CPU 生成过程中 high_resolution_clock 的经过时间，并非真实逐点曝光；timebase/tag/line 未填。旧 URDF 为 10 Hz、30000 samples、100 Hz IMU；这些不能用于证明当前真实采样时序。

旧 PB 根 LICENSE 为 MIT，Livox 模拟插件 LICENSE 为 MIT（Ricardo Casimiro, 2023）。CSV 没有独立来源/许可说明：可以在保留仓库许可的前提下作为仓内方向模板评估，不称为厂商硬件扫描时间规范。2025 总仓、控制器、插件声明 Apache-2.0；Point-LIO package 声明 BSD；Livox driver 独立保留其 LICENSE。移植的 owned workspace 必须保存每个仓库许可证及 NOTICE。

旧 2024 `/cmd_vel` 是文档入口，Gazebo planar_move 实际 remap 到 `/cmd_vel_chassis`；旧 fake_vel_transform 会将非零 angular.z 改成配置自旋（哨兵 launch 为 5 rad/s）。2025 是添加 spin_speed，不应混淆两版接口。

## 新 owned Humble workspace 准备方案

已验证 Ubuntu-22.04 有 Humble setup、colcon、g++ 11.2、CMake 3.22、PCL 1.12、Eigen 3.4、python3-dev、rosidl_default_generators、ament_cmake_auto、tf2_ros。dpkg 审计明确尚无 navigation2/nav2-bringup/nav2-core、pcl_ros、slam_toolbox、glog dev；ninja-build 仅 un 状态，不能把 dpkg-query exit0 当已安装。详细版本/原始命令在 SOURCE_MANIFEST。

隔离 workspace 计划用 Linux 自有目录 `/root/polar-navigation-humble-e05eb08e/`，避免在 DrvFs 编译，也不修复用户原 workspace。构建按三个阶段：

1. owned `livox_ros_driver2` **interfaces-only** 包：原固定 CustomMsg/CustomPoint 原字节，保留相同 ROS 包名与类型支持；独立小 CMake 只执行 rosidl_generate_interfaces，不链接 SDK/不构建或启动硬件 driver。原 driver CMake 会无条件加入驱动并链接 SDK，因此不能称原 driver 已实现纯消息构建开关。
2. 固定 Point-LIO、loam_interface、sensor_scan_generation、terrain_analysis/ext：依赖 rclcpp/rclpy、geometry/nav/sensor/visualization_msgs、pcl_ros/pcl_conversions、tf2_ros/tf2_geometry_msgs、message_filters、Eigen、glog/Python/OpenMP。Point-LIO 此版本内置 ivox，没有旧 FAST-LIO 的 ikd-Tree gitlink依赖。构建时还需 checkout 它的安装目录 rviz_cfg（即使不启动 RViz），避免 sparse 缺安装路径。先只收真实传感器，验证 LIO 与 epoch 重置，不发命令。
3. 固定 Omni controller、pb_nav2_plugins 与 Humble Nav2 必要节点：controller/planner/costmaps/behavior/lifecycle/BT/mapserver 等。原配置指定 intensity voxel layer、BackUpFreeSpace 插件，需固定 pb_nav2_plugins，不能悄悄替换算法。mapping 模式增加 slam_toolbox + 锁定 pointcloud_to_laserscan；已有地图定位才选择锁定 small_gicp_relocalization 及其独立依赖。初次不运行原 bringup 全链，不启动 Gazebo、硬件驱动、遥控或默认 fakeVel 自旋。

本次仅准备依赖/锁定计划，未安装系统依赖或实际 build。实际构建与 CPU/GPU 测量必须按父任务协调窗口进行。需要另行保存 owned 源 overlay diff、基线/新 SHA、实际 colcon 日志与运行证据，才能将此源审计转为接入验证。

## Owned 时间、TF 与定位来源修复

新增 `tools/prepare_pb2025_lio_tf_overlay.py`，在固定 HEAD、pristine 工作树、edited Git blob SHA 和唯一源码锚点全部匹配时生成独立源码；输出目录必须新建。上游 checkout 保持未修改；每个新/原文件 hash 写入 `OVERLAY_MANIFEST.json`。C++ 私有辅助实现位于 `tools/pb2025_overlay/`，并逐原字节复用共享 `rm_match/integrations/pb_request_context.hpp` 的严格请求解析器。

生成版使用 ExactTime 有界队列 8，callback 再比较 cloud/odom 的 exact stamp 与 frame。TF mount 必须通过 latest lookup 证明是静态变换（返回 stamp=0）且有限、单位 quaternion；缺失或动态 mount 拒绝，不回退单位变换。odom-to-base 仅来自算法估计与该静态 mount。body 速度按实际 ROS sim stamp 差分，再从估计 odom 方向旋转到 body；重复、回退时间拒绝。节点属于单 episode/binding，reset 必须创建 fresh stack，不复用上一次速度或 TF 缓存。

Point-LIO 在真实 CustomMsg 入口要求 `header.stamp == timebase == request.acquisition_start_ns`，一次性捕获严格校验的请求 Json 副本，随实际 lidar/time 缓存进入 `MeasureGroup.pb_context`。新请求替换 pending 不改变已入队扫描的 context。实际估计发布时使用该扫描 context 和原 `odomAftMapped.header.stamp`，输出 `/polar/pb/localization` 的 `polar.sim.pb-localization-result.v1`：请求原 11 字段加实际 `localization_stamp_ns`，schema 替换；不读 latest request，不填理想 pose，不改 filtered scan-end 时间。来源窗口或关联不符时不发布估计结果。错 episode/binding 在 ScanSource 中产生不可恢复的 GenerationFault、撤销 pending 并从 ROS callback 抛出，owned node 停止，不能随后恢复旧 generation。输入 scan 缓存最多 8 帧。IMU ROS subscriber 的有界 depth 调为 1024，以接收每扫描窗口 51 条真实 2 ms 样本 burst；内部 IMU 缓存达到 4096 后明确报错停止，不静默丢旧数据。原 IMU header.stamp 逐整数复制，去掉零偏移 double 往返，传感采样率和滤波算法未变。

owned launch 仅启用 Point-LIO、loam_interface、sensor_scan_generation。固定 base=base_link、lidar=livox_frame；默认 namespace=red_sentry，原请求 episode/binding 可在生成命令显式设置。实际 cloud/IMU同位置、同 frame，因此 IMU-to-lidar 外参为零平移/单位旋转，base-to-sensor 实际安装外参仍由 bridge 的静态 TF 提供。传感 topics 为 namespaced `livox/lidar` / `livox/imu`，算法 odometry 为 namespaced `odometry`；桥接配置必须显式对齐。高频逐点 odometry、cut/con_frame、时间偏移与非 CustomMsg 输入在这条 owned 可信路径启动时拒绝。

源码级与实际轻量 C++ 回归已检查 SHA/锚点、fresh target、unknown HEAD、原仓 clean、exact 配对、missing TF、body sim dt、原扫描 context 的不可变身份/窗口/只绑定一次、新 pending 不改变旧扫描、正确 owned launch。轻量 helper 编译运行使用 Ubuntu-22.04 g++ 与隔离依赖前缀中的 nlohmann 3.10.5；这不是完整 ROS 节点构建或 DDS/SIL 闭环。完整节点 build 与 TF/DDS 实际回归须等待依赖前缀就绪并保存独立构建/运行日志。

## 用户既有目录

Windows 相邻 `哨兵导航llm控制计划/pb_rm_simulation` 和 WSL `/root/pb_ws/src/pb_rm_simulation` 的旧 parent HEAD 均为 `457cae56c33e2eb407ad412608b02e2c2c716286`，origin 是旧 GitHub LihanChen2004 仓。WSL 的 Livox/FAST-LIO/Point-LIO 三个子模块处于 changed HEAD 且工作树 tracked 文件全部删除（分别 90/73/55 项，只有 .git 文件）；另外两个导航 gitlink 未初始化，没有 install 目录。它不是当前固定 Gitee / 2025 的完整构建基线。未执行 reset/checkout/清理或改系统配置；新源码与后续工作必须隔离。
