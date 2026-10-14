PB2025 自瞄源适配候选
=====================

本候选接入 PB2025 原 OpenCV 灯条检测、`mlp.onnx` 数字分类、PnP、EKF tracker 和 Gravity/Gaf 弹道节点；最终云台角度来自原 `publishGimbalCommand`。截至本轮，source03七包build/ldd、三真实节点graph/reset/全树清理通过；真实首帧试验仍在host序列化或跨WSL部分图像请求时超原80ms，无完整图像输入/MLP/PnP/控制结果。下述02准备阶段与失败历史保留，最新执行范围见末节。

固定来源是 [SMBU-PolarBear-Robotics-Team/pb2025_rm_vision](https://github.com/SMBU-PolarBear-Robotics-Team/pb2025_rm_vision)，commit `df1892c48f90093f86a2f7b02af6441a80aa2d97`。审计 checkout 位于 `external/pb2025-aim-interface-review`，当前生成源码在 `artifacts/pb2025-aim-source-20261014-03`；早期 01/02 保留。`tools/prepare_pb_aim_plugin.py` 核对固定 Git blobs、LFS OIDs、分类模型/标签 SHA 后复制快照；只生成独立目录，不修改 upstream。

原分类模型 SHA256 为 `b3250176ea8fdbe6d1585be954363757ff6a8245a81e8797f16cea601976d47a`，标签为 `8cc04e2a54c7ee1c39925c9ca8e6eebe2d1015ee9dab77ab3befd8095be74411`。本次不使用 bringup 中的 `opt-1208-001.onnx`：主仓包含默认 OpenCV detector，OpenVINO detector 是另一个实现的 bringup 选项，不能用配置中的名字宣称已接通 YOLO。

源码钩子只包裹消息和输出。`polar_pb_aim_interfaces` 的 `SourceImage` 同时携带原 Image、CameraInfo 和不可重贴的 source context；原 detector 发布 `SourceArmors`，原 tracker 发布 `SourceTarget`，原 projectile 回调把同一 context 与实际 GimbalCmd.position 配对。原图像 stamp、robot、episode、binding epoch、observed sequence、sim time、host wall deadline、frame ID 和 calibration ID 贯穿该路径。标准 GimbalCmd 中的 `header=this->now()` 保留原行为，但不用于曝光关联。

最终 `/namespace/polar/pb/aim_result` 是 `std_msgs/String`，schema `polar.sim.pb-aim-result.v1`，字段只有 `schema/source_context/capture_stamp_ns/status/output_frame/yaw/pitch`。`no_target` 来自原 tracker 的非 tracking 回调，角度为 null。有效角度由原弹道计算输出，适配只把 ROS 正 Y 俯仰转换为仿真正向上的 pitch，并规整 yaw 周期；没有新的 Target→atan2 求解器。confidence 为 null，fire_permission 永远 false，原 `cmd_shoot` 不连接平台开火权限。

局部 TF 为 `gimbal_aim_origin → gimbal_yaw → gimbal_link → camera_optical/shooter_link`。前两旋转使用原图像采集时的 own qpos，静态值使用实际编译模型标定 `artifacts/aim-mount-calibration-20261014-02/MOUNTS.json`，SHA `05ef42635d646c80dd0031092ddd9119ca1216f9996ab4c4d9dd58280e4622d7`。其 origin 明确是仿真模型设计标定，不是硬件测量。peer 核对 ref、模型来源 SHA、每辆车的 body/joint/site 和轴约定；没有隐式零位姿、map/world/odom TF 或敌方真值。当前候选声明 stationary-first，使用采集时自己的速度门禁；移动底盘的定位/惯导 TF 尚未加入。原相机 80 ms 和 SDK 150 ms 权限仍由 host 校验；ROS 本地等待最多 80 ms，原 host QPC deadline 只是原样往返字段，不与 Linux clock 比较。

Humble MessageFilter 读取通用 message header traits，因此自定义 carrier 的顶层 Header 保留原 TF 时间查询。此结论来自 [Humble MessageFilter 源码](https://github.com/ros2/geometry2/blob/humble/tf2_ros/include/tf2_ros/message_filter.hpp) 和 [Humble message traits](https://github.com/ros2/message_filters/blob/humble/include/message_filters/message_traits.h)；最终仍需实际编译/link 验证。

实际构建所需来源与依赖
----------------------

2026-10-14 `git ls-remote` 读到以下 refs，构建必须使用所列 commit 而非移动分支。02准备阶段只查询refs，随后03的实际clone/hash与七包构建见末节。

| 原依赖 | 仓库 | 固定 commit |
| --- | --- | --- |
| auto_aim_interfaces/main | https://github.com/SMBU-PolarBear-Robotics-Team/auto_aim_interfaces | `5eab0e0464b6cfae7cf8ae0599109b3f5b623e3d` |
| pb_rm_interfaces/main | https://github.com/SMBU-PolarBear-Robotics-Team/pb_rm_interfaces | `66c8bee0d389b0eed9e84157c26d026b95ebae4c` |
| rmoss_core/humble | https://github.com/SMBU-PolarBear-Robotics-Team/rmoss_core | `8209ec517dfbb7ecac613cf0c9534d67ff918b7d` |
| rmoss_interfaces/humble | https://github.com/SMBU-PolarBear-Robotics-Team/rmoss_interfaces | `424f50c831b3e74fa72446969362cdabb2e22cd1` |

至少构建 `auto_aim_interfaces`、`pb_rm_interfaces`、`rmoss_projectile_motion`、新 `polar_pb_aim_interfaces` 和三个 owned PB 节点；rmoss 包的递归依赖须按固定 checkout 的 package.xml 再审计。还需要 Humble rclcpp/rclpy、rclcpp_components、rosidl、sensor/geometry/std/tf2/rosgraph messages、cv_bridge、image_transport、message_filters、Eigen、OpenCV DNN、nlohmann_json 和 ROS launch 的 PyYAML。不要构建或启动 hik 相机硬件 driver。02阶段只有既有环境可用，03已有独立安装prefix、实际节点ELF及ldd核验。

源准备产物包括 `SOURCE_MANIFEST.json`（原始/生成源 SHA）、原参数 literal `PB_AIM_PARAMS.yaml` 和 `pb_aim_launch.py`。launch 只覆写 use_sim_time 与两个明确的局部 frame，原检测、分类、滤波、弹道阈值与 offset 保留。TF/clock topic 显式 remap 到独立 namespace，不启 hardware/Gazebo。原 simulation detect_color=0 保留；首次实际试验必须选择匹配原配置的目标颜色，不能把保留参数解释成所有阵营都已验收。

Linux JSONL peer 入口是 `python -m rm_match.integrations.pb_aim_ros_peer`，要求本地 adapter ID、robot/generation、独立 namespace/domain、mount ref/SHA。三节点须由拥有进程组的 supervisor 预先启动；peer reset 检查原图像/Target subscribers 和真实结果 publisher 已建立，不发送热身图像或假观测。完整 Windows session/owned-stack 启动、依赖实际构建、真实首帧分类推理次数、80 ms 内结果及 Qt 绑定验收仍须由后续独占实测完成，不能把本次源准备或纯 mock 回调记为 ROS/模型通过。

51 项纯回归通过，原日志位于 `artifacts/pb2025-aim-plugin-focused-20261014-01/focused.log`。覆盖六身份/曝光/标定错配、跨 clock-origin、迟到结果、状态与实际角度的不同形状、manual-only fire、采集时反馈、partial ROS setup cleanup，以及完整源准备后 upstream 字节保持不变。早期 source-preparation 分类错误保留在该证据目录的 failure observations，不作为成功结果。

PB03 的准备与真实绑定
--------------------

以上 02 记录与结果保持原字节。新候选 `artifacts/pb2025-aim-source-20261014-03` 使用独立 `PBAimEngine`，直接由通用 JSONL/WSL peer 持有，不再建立第二个 WSL 进程层。factory 在返回前启动三个真实模型节点并检查原图像/目标/结果图；此时 SourceGate 未配置，拒绝任何图像。prepare ACK 只说明实际资源图就绪，没有曝光、假 generation 或推理热身。reset 原 context 一次配置三个节点并等待同 run/robot/episode/epoch/calibration 的三条真实 ACK，限本地 1s 且仍受 host 原 2s reset 约束。重复 ACK 不清除已有序号或曝光；不允许下一 generation 复用实例。

PB03 采用标定 03：`artifacts/aim-mount-calibration-20261014-03/MOUNTS.json`，SHA `296aaa073da96fa0dcc0ecf473284e76eb94859dd53006457c9507cdda86bf62`。静态向量与 02 相同，来源绑定包含 camera 仅局部计时换成 QPC 的新源码。它仍是零物理步、零推理的仿真设计标定。

源码额外声明一个 `source_safety_hook`：原 `solver_->solve` 返回 false 时原程序可能读取未写入的 pitch。owned 回调现在检测原 bool，失败发送同一原 source context 的 `pending_result`、null yaw/pitch 并返回，不发布 GimbalCmd；成功时原距离、选板、预测、solver、符号和 offset 数学保持原样。manifest 记录唯一锚点及原/新 CPP SHA。此安全修复不代表求解成功率提高。

`tools/prepare_pb_aim_stack.py` 绑定实际 ELF、安装后的原模型/标签、环境、标定和 source manifest，并完整解析原 YAML。`SCOPED_PARAMS.yaml` 按 namespace/节点全名生成，逐完整字典核对，仅改变 use_sim_time 和前述两个 frame；裸节点参数文件在 namespace 内可能被 ROS 忽略，因此不直接传入。prepared stack 没有 argv/硬件/参数选项可来自 HTTP。

inner close 使用一个共享 1s 截止，实际子节点 TERM/KILL/reap 与最多一个 ROS close worker 共用剩余预算。线程或子进程残留保持 sticky cleanup failure；inner direct-child 清理不能替代通用 outer birth-bound owner 的全树证据。

四个表中固定依赖已实际 clone、detached checkout、逐原文件 hash 记录在 `artifacts/pb2025-aim-dependencies-20261014-01`；原库保持 pristine。最小 owned 兼容副本 `pb2025-aim-dependency-compat-20261014-03` 只修两接口包遗漏的 std_msgs find/rosidl DEPENDENCIES/package.xml 声明，消息与 rmoss solver 字节不变。`tools/prepare_pb_aim_dependencies.py` 可复现该步骤。实际构建只需要其三个包与 PB03 的四个包，共七包；rmoss_interfaces 作为来源审计保留，未被此闭包引用。Hik driver 不启动。依赖准备、纯测试与 scoped 文件验证均不能充作实际 Humble 编译、模型推理、实时 80ms 或 Qt 接入通过。

PB03 实际构建与零图像准备
------------------------

新独立signed依赖prefix02实际下载/解包成功，没有执行deb安装脚本。实际preflight03发现其OpenCV-dev导出指向未提取的库，旧失败保留。构建工具现要求显式核验完整系统OpenCV的config/header/library SHA与ldd，实际preflight04通过。七包独立colcon构建01实际325.824s、exit0/reaped/source unchanged；实际安装的三个节点ELF、MLP、labels及全部ldd检查通过。构建工具不改变原检测/分类阈值或模型。

实际Windows→Ubuntu-22.04注册/prepare/reset探针attempt1使用同一封存source03和build01，三个真实节点由通用owned supervisor启动：prepare 10.1790645s，当前robot/episode/binding_epoch reset 0.0526272s，三条源门ACK符合原本地1s/host2s预算，Windows/Linux全树clean。prepare/reset未发送任何图像或act，没有NN热身；探针context不是SDK租约，不能把本结果当原80ms实时控制通过。注册核验实际模型/标定/source/完整namespace配置，安装消息路径只加入该peer的内存sys.path，没有修改原venv.pth或设置manifest PYTHONPATH。

实际报告与失败原文保存在[本轮验证包](validation/universal_aim_20261014/README.md)，`pbprobe`组包含注册脚本、静态审查、原结果及owned清理日志。实际MLP/PnP、移动反馈、实时图像控制与Qt绑定继续验证。

PB03 真实首帧失败与传输分段
--------------------------

最新[逐次验证包](validation/aim_live_followup_20261014/README.md)保存default、controlled和controlled-fast独立尝试、真实RGB/PNG/DTO、phase与cleanup IO记录。
default尝试拍到场外墙面；controlled公开测试场景按本车相机实际前向放置原红装甲，场景真值仅存评测设置，不进算法DTO。
controlled首次capture→public约37.9ms、act入口约50.4ms，host序列化后原80ms过期，尚未提交act；只有prepare/reset两个完整请求。
controlled-fast显式CV4/pybase641.5.1/switch1ms，capture→public16.3977ms、act入口30.4881ms，仍在原80ms等返回时queue.Empty。
Linux实际IO43chunks/2334917bytes（含prepare/reset）、complete_requests=2；act只有部分输入，没有peer第三条完整line、compute或SourceArmors/Target。
因而该图像尚未到原分类/PnP链，不能把失败解释为模型推理时间或TF拒绝；零结果不证明分类器已推理。
prepare4.0485265s/reset55.7953ms、原source03和71生成文件/模型/标定保持、Windows/Linux全部节点和相机clean；CV32/switch5ms实际恢复。
总STOP检查551次/2.074553s是全生命周期累积成本，不能当该act耗时；5ms调度是最佳努力，不是硬实时响应保证。
下一步针对完整大图跨WSL传输和host校验/序列化分段改进，保持原80/150ms与完整原图，不通过重贴时刻、裁切/降分辨率或暖机帧过关。
离线保存DTO的ABBA编码对照只用于测量：相同wire/原身份/像素不变，样本少且有尾延迟，不证明1ms因果收益，也不算NN/ROS/实时闭环。
