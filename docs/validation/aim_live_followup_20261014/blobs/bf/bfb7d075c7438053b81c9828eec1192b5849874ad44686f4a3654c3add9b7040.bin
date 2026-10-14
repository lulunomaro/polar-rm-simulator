# 通用自瞄插件与原 Qt 客户端

通用层按公开输入/输出契约适配算法，不按队伍名称判断兼容。当前入口接受完整云台控制链 `direct_gimbal_v1`；只有检测/跟踪状态的 `detector_tracker_target_v1` 需要显式接上原控制器/弹道模块，不能把目标 yaw、裸 Target 或串口字段当成云台目标。未知能力、版本、输出模式及任意执行路径都不会由 HTTP 自动适配。

## 实机链路与当前仿真链路

通常工业相机直接连接上位机，图像交给自瞄算法；下位机 C 板通过串口/CAN 等提供姿态、编码器或其他本体反馈，接收云台控制命令并驱动电机。具体反馈和控制字段由各队固件决定，不要求图像先经过 C 板。例如同济公开环境使用海康工业相机、RoboMaster C 板/BMI088 和虚拟串口，其公开 [Gimbal 协议](https://github.com/TongjiSuperPower/sp_vision_25/blob/bd9f5e798fa3c6dd3b483ae6627796afb41c608d/io/gimbal/gimbal.hpp) 分别声明反馈四元数、yaw/pitch、角速度和控制角度/角速度/角加速度；可核对 [官方项目说明](https://github.com/TongjiSuperPower/sp_vision_25)。

当前仿真接口链路是：**MuJoCo 场景实际渲染 RGB/BGR → 原 CameraInfo/K/D/标定和曝光源上下文 + 同次物理快照的本车姿态反馈 → 上位机完整自瞄算法（检测、跟踪及其控制/弹道链）→ 规范 yaw/pitch action → runtime 重查原 80/150 ms 门限及租约 → MuJoCo 云台关节 actuator → 下一次曝光和关节反馈**。适配程序把原图与本车测量交给算法，不从仿真器喂敌方位置、Target 角度或目标身份真值。yaw/pitch 是算法计算后的控制输出，不是替代图像的输入。相机像素由模拟相机产生，不是物理工业相机采集；qpos/qvel 来自模拟关节，不是实物 IMU/编码器采样。[camera.py](../rm_match/platform_v2/camera.py) 在曝光时复制实际 MuJoCo data；[backend.py](../rm_match/platform_v2/backend.py) 执行经过重检的目标并推进物理。仿真 adapter/runtime/actuator 在这里替代 C 板控制与电机执行，没有连接或验证物理 C 板/电机，也尚未复现特定固件的 CAN、电流环、滤波或硬件延迟。

自家 T2 的显式配置已连续三次通过本机静态实时链，正式入口一次物理RTF0.9971029、107个及时结果/97个独立新帧实际关节消费、0fault/0fire/clean；原80/150ms保持，late/pending不计及时推理或动作。旧async02的RTF0.5475和额外计时/调度失败保留。同济source04实际原模型prepare/reset/清理通过，仍无真实图像计算。PB source03七包build/三真实节点graph/reset/clean已过；实际首帧在host序列化或跨WSL请求部分传输时超原80ms，尚无该帧MLP/PnP或控制结果。接口合同不表示三套实时自瞄都通过，也不保证未经适配的程序零修改接入。见[最新逐次验证](validation/aim_live_followup_20261014/README.md)与[此前构建/准备记录](validation/universal_aim_20261014/README.md)。

导航已有 Windows→WSL、实际 LiDAR/IMU→Point-LIO→Nav2→SDK→MuJoCo 的单目标生产 SIL 闭环证据，见 [导航生产验证](validation/pb_wsl_production_20261014/README.md)。这是导航的局部结果，不替代自瞄实时门禁、定位精度、完整比赛或实机 C 板验收。

## 注册与选择

管理员在本机准备 `polar.sim.aim-plugins.v1` manifest，固定 executable/argv/cwd、可用机器人和完整 capabilities。模板见 [aim_plugins.json](../examples/aim_plugins.json)，分别演示本地 JSONL、ROS envelope、Windows→WSL JSONL transport。`reviewed_aim_wrapper.py`、Linux `/opt/polar-reviewed/...` 都是需替换的本机真实程序/路径，模板不能直接作为已部署算法。`supported_robots` 是本地安装范围，可按实际标定与机器人能力配置，不是团队白名单；新队伍不需要改通用协议或硬编码 ID。能力声明只表示接口支持，不代表检测质量、实时性或实车验收。

服务入口：`python -m rm_match.platform_v2 --camera --admission-manifest LOCAL_GRANTS --aim-plugins-json LOCAL_AIM_MANIFEST`；自家 T2 Linux 部署入口 `python -m rm_match.deployment.server` 也支持 `--aim-plugins-json`。自家 launcher 可显式传同一选项；它仍保留自家原生默认配置。其余入口参数按对应帮助设置，不在 HTTP 请求里传模型、import、命令或 topic。

Windows 的 WSL 插件另显式加 `--prepare-aim-plugins`，在 backend/physics 前真实准备；Linux-only 的自家部署 server 不启动 WSL 准备池。模型、binary、source、标定与 dependency prefix 应由对应适配器生成并核验自己的本地注册文件，不能把 T2 spec 换个 binary 路径冒充另一套算法。

原 Qt 客户端固定基线为 `0cedf99b70b1beec99865b9980af6789e6c53d99`，用 [固定补丁](../client_patches/README.md) 校验/安装。`V2 Aim` 通过服务 catalog 中的公开 capability 合同发现 `custom_*` 插件，可用机器人和相机声明匹配时才可选择；绑定 config 精确为 `{}`。选择不自动 claim、arm 或开火。未适配的客户端/算法不能仅加一个 ID 就获得支持。

## 相机、反馈与期限

- 输入仍为 `polar.sim.observation.v2`，六身份字段是 robot/episode/binding_epoch/observed_seq/sim_time/wall_deadline。
- 图像为 packed `rgb8`/`bgr8`，原像素、尺寸、stride、K、Brown–Conrady 五项 D、`gimbal_link` 到 `camera_optical` 静态标定与 calibration ID 随原曝光一起传输。
- 使用 `camera.own_*_at_capture` 处理该曝光，不能把 delivery 时刻的 own 状态替换进去。普通 DTO 仍有已声明的模拟本车 odometry；这不改变 T09 最终导航输入边界。
- 当前 `own_qpos_at_capture` 顺序为 `[base_x_joint_m, base_y_joint_m, chassis_yaw_rad, gimbal_yaw_rad, gimbal_pitch_rad]`；`own_qvel_at_capture` 对应 `[base_x_rate_mps, base_y_rate_mps, chassis_wz_rps, gimbal_yaw_rate_rps, gimbal_pitch_rate_rps]`。前两项是模型 slide joint 的位移，不能不计模型出生位置就当世界 xy；单独的 `own_odom_at_capture` 使用 body xpos。yaw/pitch 与角速度来自同次 MuJoCo 关节快照，不能把它们标成实物 IMU/编码器读数。
- 坐标为右手系；base 为前/左/上，光学相机为右/下/前，yaw 为绕竖直轴逆时针正，云台 pitch 向上正。外参 xyzw 四元数表达 optical→gimbal 变换；例如上游串口 wxyz 必须显式换序，不直接复制。仿真时间是 episode 内秒，ROS 曝光 stamp 由原浮点仿真秒量化为 ns；静态标定 TF 用时间 0。ROS `/clock` 和所需动态 TF 由具体 reviewed adapter 提供，通用 codec 不替它们填值。
- `wall_deadline` 是服务端时钟的绝对值；外部 Linux/ROS 进程只能原样 echo，不能减本地 monotonic 后重新授权。服务端保留原相机 80 ms、SDK 150 ms、租约/epoch/每消费阶段检查；JSONL reset 仍为 2 s。
- 客户端展示的 JPEG/受限 HUD 属于显示平面，不作为算法输入。没有敌方真值、分割/目标 ID、模拟器对象或像素凭据进入插件消息。

[aim_camera_codec.py](../rm_match/integrations/aim_camera_codec.py) 将校验后的曝光转成不可变像素与源上下文；可选 ROS 对象为实际 `sensor_msgs/Image`、`CameraInfo`、静态光学标定 `TransformStamped`。ROS 类型缺失明确失败。它不生成 world/odom TF 或 IMU；完整机器人运动学/所需 TF 必须来自显式真实标定与本车测量，不能补 identity TF。

## 输出与无目标

动作是 `polar.sim.action.v2` 的 `aim/gimbal_target`：base-relative yaw、pitch 为 rad，正 pitch 向上，`active`、算法真实 confidence 或 null，以及仅信息性的 fire permission。实际火控保持人工独立授权。

当前通用输出是关节角目标，不含 yaw/pitch 角速度或角加速度前馈；上游协议若依赖这些字段或板端控制器，须声明并实现对应适配/控制链，不能把位置 servo 的结果称成原 C 板控制器效果。通用输入的五维向量也不等于完整 IMU 四元数、加速度或真实编码器协议；机器人运动学映射、时间同步和闭环表现仍需逐适配器验证。

无目标/尚无关联结果使用 `polar.sim.aim-status.v1`，精确原六身份 + `kind=aim` + `status=no_target|pending_result`，没有角度、command 或假置信度。服务只对已声明 `camera_gimbal_v1` 的插件接收这类状态，清掉旧输出并保持同代实例；它不计为推理成功或物理消费。过期、旧代、未知 status 仍拒绝。

Qt 的受限状态可显示带 episode/绑定/adapter/source frame/原 deadline 的 `algorithm_status_context`。只显示有效本会话绑定；过期样本不显示，无目标不会继续显示旧机械成功。`result_available` 仅表示结果可用，机械消费必须另有隔离评测证据。

## Native、ROS 和串口适配点

[aim_jsonl_peer.py](../rm_match/integrations/aim_jsonl_peer.py) 提供 `run_aim_plugin(compute_factory)` / `serve_aim_plugin(compute, ...)`。本地 wrapper 延迟加载真实算法，再调用 `compute(bundle, observation)`，返回真实 action 或显式 status。`None`、错误或未知输出会失败，不补 hold/no-target。stdout 只承载有界 JSONL，库日志转到 stderr；进程树由宿主拥有并回收。

[ros2_bridge.py](../rm_match/integrations/ros2_bridge.py) 保留有界 `std_msgs/String` 原 observation/action envelope，aim 可返回 `type=status`。node/topic/domain 只在本地 argv 固定。标准 ROS Image/Target 管线须把不可变 `aim-source-context.v1` 随实际曝光贯穿处理；仅一个 bare Header 或 latest Target 不能证明 episode/绑定/请求来源。`validate_source_echo()` 不做最近时间匹配或贴新身份。

串口/私有 native API 需自己的 reviewed wrapper 明确编码、单位、反馈来源和输出关联。不直接连接硬件端口，不根据收到的最新串口消息猜测它属于哪张新曝光。

### 显式 Windows→WSL JSONL 生命周期

`wsl_jsonl_v1` 是可选本地 transport；没有准备资源时注册项为 unavailable，不直接把裸 `wsl.exe` 当普通 JSONL 插件。manifest 固定 Linux 绝对 argv/cwd、distribution、监督器 Python 与有界 process_env，HTTP 仍只能选预注册 ID 和空 config，不能传命令、topic 或文件路径。

`PreparedWslAimPlugins(path, repo_root=ROOT, shared_root=ROOT/'artifacts/aim-wsl', startup_timeout=15.)` 必须在 backend/physics 前显式创建；`register_aim_plugins(..., wsl_prepared=pool)` 交接资源，服务 finally 调用 `pool.close_unclaimed()`。独立 `op=prepare` 仅在真实 compute factory 初始化完成后回执，不供应图像、不预猜 epoch、不替代 reset ACK。实际绑定仍发送当前 context 的 `op=reset`，等待原 2 秒回执并执行可选 engine.reset；未 prepare 的原直接 JSONL reset 模式保持。当前池每插件只交接一次，重绑需新准备/服务重启，不能宣称通用自动重启已完成。

关闭使用同一 1.5 秒资源预算：STOP 保留原 run/spec 身份，Linux 监督器按出生身份核验唯一 peer 的祖先链及 subreaper 接收的后代，包括新 SID 子进程；Windows 侧由执行前建立的 Job 拥有 wsl.exe。双方清理、leader reap、组为空和 IO 线程结束均须有证明，缺证明直接 unclean；Windows 已 reap 不代表 Linux 已清理。此机制不能沙箱隔离恶意插件把任务交给外部服务。

该层已在 Windows→WSL 运行两项无害实际进程测试：正常真实 prepare/reset，以及 leader 提前退出、独立 SID 后代忽略 TERM 并持 pipe；两项通过，driver 8.978 s、exit0/reaped，所核验源码未变。原始日志与清理证明在 `artifacts/wsl-jsonl-actual-20261014-01`。它证明这两种进程生命周期，不是检测器、ROS graph、NN 或实时自瞄闭环资格。PB 节点的 immutable generation 与真实模型/graph 初始化仍须按其独立适配器验证，不能预造 generation/假 ready。

## 三个例子的当前实际范围

| 实现 | 已核对接口 | 尚需验证 |
|---|---|---|
| 自家 RMCS T2 | 固定完整原生spec/model/CPU4；显式host配置三次静态live通过，正式入口107及时/97新帧消费/RTF.9971 | 默认profile、命中精度、移动/多车/火控/可见Qt及整场未验收 |
| TongjiSuperPower/sp_vision_25 | 固定 `bd9f5e7...` 原检测/跟踪/MPC源；source04 clean19构建与实际原模型prepare/当前context reset/clean已过 | 零图像/零NN阶段，尚未实际图像控制和原80ms live；不用像素baseline充当同济 |
| PB Gitee PB_RM_Vision | `ab0c83b...` 的 Image/CameraInfo→Armors/Target；Target.yaw 是目标姿态，旧仓发 MCU 目标状态 | 控制链及原曝光关联，不能裸 atan2 替换原控制器 |
| PB 官方 GitHub pb2025_rm_vision | `df1892c...` 原完整节点；source03/七包build/真实graph/reset/清理已过；首帧失败已定位并保存 | 图像请求host过期或WSL未完整输入，无实际MLP/PnP/图像控制，80ms live未验收 |

本轮已有纯契约与真实客户端解析/计划代码测试；它们不等于第二套自瞄检测器、ROS DDS 或 GUI/物理闭环通过。实际验收应逐插件保留源码/模型/构建、原图 SHA/标定、源关联、SDK ACK、真实消费和全 owned-process 清理，并继续核对原时限与人工火控。

## 可选工具依赖

自家 T2 Windows入口可显式用 `--wsl-native-spec LOCAL_LINUX_SPEC --native-out LOCAL_SHARED_OUT --wsl-native-transport wsl_async_bgr_v3 --private-native-pixels`，配合原 `--camera --admission-manifest`。实际零NN模型准备在physics前，绑定仍reset当前context。v3仅有一个原compute，迟到stdout只归原帧；忙或证据背压返回无角度进度，原80/150ms不变。默认同步transport及其严格超时判定保留。该入口在下述显式本机配置取得静态实时资格，完整部署范围仍未验收。

`pip install -e ".[aim-tools]"` 仅增加准备工具所需 PyYAML：同济生成器用 `yaml.safe_load` 读取原 YAML 参数，PB owned launch 同样读取原配置。C++ `yaml-cpp`、OpenVINO、ROS Humble、消息/TF包及 `image_transport_plugins` 是各算法自己的依赖，应按其有来源/hash 的安装前缀准备；Python optional extra 不会替它们安装 ROS 或宣布 preflight 通过。通用 JSONL 合同本身不需要 PyYAML。

显式本机运行设置为 `--host-opencv-threads 4 --raw-base64-codec pybase64_1_5_1 --host-python-switch-interval-ms 1 --authority-affinity-mask 0x10`。
这些参数只允许本地启动指定，HTTP不能选择；codec需要实际固定1.5.1依赖，CLI报告实际模块和extension SHA。
切换间隔在准备前生效、全部资源清理后恢复；亲和性仅Windows当前authority线程的runtime.run区间，同CPU group实读并finally恢复。
默认不修改调度或调用WinAPI；Linux显式线程亲和性请求失败。mask0x10是本机实测配置，没有证明其CPU类别或跨机性能。
它保持原模型、像素、80/150ms及fire权限，不改变系统优先级、电源或计时器，也不提供Python硬实时保证。

用同一真实Linux CPU4 spec、原客户端checkout和新输出目录复测：

```powershell
.venv-sim/Scripts/python.exe tools/smoke_wsl_native_live.py --run --native-transport wsl_async_bgr_v3 --private-native-pixels --linux-native-spec artifacts/native-production-cpu4-build-20261014/operator_source.local.json --client-root external/polar-rm-client-state-review --out artifacts/aim-live-local-reproduction01 --host-opencv-threads 4 --raw-base64-codec pybase64_1_5_1 --host-python-switch-interval-ms 1 --authority-affinity-mask 0x10 --seconds 10
```

该本机spec含哈希固定的实际Linux构建路径，需先按构建证据准备；克隆仓库中的验证包不携带模型/ELF。
额外authority计时探针默认关闭，旧加探针诊断未达RTF的失败保留。验收仍逐帧检查原capture、SDK ACK、实际消费和清理；
静态链资格不代表所有NN都在80ms内、精度、第二套算法、移动/多车、整场或硬件通过。
