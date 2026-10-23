# 通用自瞄插件与原 Qt 客户端

2026-10-23：修复入口校验后、实际mj_step前到期的输入未撤销问题。运行时对当前活动通道提取原lease/input/action/activation/sensor期限，私有提示仅触发原完整权限守卫再次检查；原实际Command/ctrl写入器撤销到期通道。每次撤销后重新采样调用时刻，最多3×机器人数量轮，无等待、不采用新输入、不增加开火。仍有效的其他通道保留。
原六车2ms/NVIDIA1440×1080/15总fps、自有CPU4 T2/ONNX与原SDK手控移动场景，10秒/20秒两次无包装真实T2均通过既有有界场景门禁：RTF0.999675/0.999298、及时结果137/248、严格物理帧84/133、晚活动调用0/0；实际到期撤销3/2次，clean/errors[]/fire0。原80ms图像/150ms控制/RTF0.98未放宽，原失败不重写。
这只关闭本次物理调用到期缺口并证明当前有界实时传感器→真实T2→云台链；目标关联/跟踪保持率/预测弹道/命中精度/射击、移动本车、多车算法、可见Qt、第二实现、导航决策完整树、完整比赛与换机仍未验收，M0–M5不关闭。未输入敌方真值/刷新旧时间戳/使用替代算法，未调用子代理/恢复定时任务/训练/硬件。证据见[调用前过期撤销](validation/integration_expiry_20261023/README.md)。

2026-10-23：补齐WSL异步自瞄输入的有界连续readv接收，每批最多16次非阻塞读取或1ms即交还外层；原资源看门狗、完整SHA、额外字节/EOF拒绝、原80ms图像/150ms控制/RTF0.98和源身份保持。新增INPUT_IO本地统计及故障时仍回收owned child的保护，不增加图像缓存/队列、不压缩/降采样或更换算法。
48次同一真实BGR的Windows→WSL ABBA微基准全部SHA相同，外层select总次数3136/1260/1305/4132；耗时12.21/6.31/6.53/6.88ms。首组有预热差异，不声称整链稳定加速；readv调用反而增加。1MiB管道容量实验无稳定收益，未进入生产，也未修改全局WSL配置。
同日旧接收器对照RTF0.989471、138及时结果/81严格物理帧/2晚活动调用；新接收器RTF0.998485、120及时结果/69严格物理帧/3晚活动调用。两轮均clean/errors[]/禁射，全部原始判定FAIL；未挑较好结果签收，未将images_verified当作NN成功。剩余P0是entry→实际mj_step间过期撤销缺口，晚调用仍阻止整体验收。
保持六车2ms/NVIDIA1440×1080/15总fps、原自有CPU4 ELF/ONNX/客户端身份、静止red_infantry scope、对方SDK手控vy.08、gravity/yawgain4。未调用子代理/恢复定时任务/训练/硬件/完整比赛；通用接入/导航决策及M0–M5未据此关闭。证据见[有界接收修复](validation/payload_drain_20261023/README.md)。

移除真实MuJoCo renderer在原浮点畸变映射输出后的多余RGB.copy；保留原float32 map、INTER_LINEAR、分辨率、颜色、曝光身份、原native/public编码及80ms图像/150ms控制/RTF0.98门限。
实际NVIDIA六车/步进/物理弹丸/重置8曝光：与同一次readback的原复制路径逐字节相同，后续曝光不覆盖旧帧；这是GL帧所有权与像素检查，不是NN/精度或实时验收。
固定点映射候选出现约288万通道差异/最大7级，初次严格断言失败及后续对照均保留，该候选未进入生产；packed float映射虽相同但微基准无稳定收益，也未采用。
两次真实T2仍FAIL：01 RTF0.943211/79及时结果/32预写入/30物理帧，出现1次entry及时但真实mj_step调用超期，已排除有效帧；新增严格no_late_physical_active_calls门禁防止好帧掩盖该问题。最终同源02 RTF0.865401/8及时结果/5预写入/4物理帧，晚调用0，仍不满足RTF/数量/运动证据。原01结果不重写，另存只读新门禁复核亦FAIL；波动未隔离，不能把局部复制移除宣称稳定整链提速。
保持六车2ms、NVIDIA1440×1080/15总fps、自有CPU4 ELF/ONNX、red_infantry静止scope、原SDK手控对方vy.08、gravity/yawgain4及OpenCV JPEG85；火控始终false。未调用子代理，未改模型/NN/Command/物理、未刷新旧时间戳、未输入目标真值，未训练/硬件/整场比赛。证据见[曝光所有权与物理调用门禁](validation/exposure_ownership_20261017/README.md)。

本轮修复实时诊断的执行帧误计：过去first actuator receipt包含仅预写入、随后在积分前撤销的帧，不能证明物理执行。上一检查点03唯一计数帧14仅有actuator记录，没有integration_entry，旧报告1帧不作为有效物理积分证据；历史文件/原判不覆盖，其他历史数量也未经此次新审计。
现仅计原integration_entry与同一步最终target/budget、实际mj_step调用时刻和本车真实ctrl/Command一致的帧；入口与实际调用都须在原80ms预算内。新增结果接收处置日志保留原collect wall sample及当时sim time，与较晚日志发布时间分开，不刷新身份/期限、不重复检查选取有利时间。
本轮同配置真实T2 10秒复验RTF0.7384549158、147 raw、103次真实完成均late_discard、及时native_result 0、预写入0、物理执行0；clean/errors[]/fire0，全部实时验收仍FAIL。35次collector late_result中5次在壁钟尚余2.20–8.48ms时仿真预算已超4–8ms，另1次wall/sim均超；这些包括pending状态，不声称是有效目标输出。未归因为单一CPU/GIL或本次日志开销，未盲目重复取最好结果。
六车2ms、真实NVIDIA1440×1080/15总fps、自有CPU4 ELF/ONNX、原red_infantry静止scope、手控对方vy.08、gravity/yawgain4和OpenCV JPEG85保持。原80ms图像、150ms控制、RTF0.98均不变。没有修改算法/模型/Command/物理，没有调用子代理/训练/硬件/整场比赛。证据见[物理积分证据修复](validation/native_integration_20261017/README.md)。

2026-10-17本轮：非阻塞外部采样获得551条GIL样本/79次采样错误，Pillow显示编码为可行动热点之一；该诊断RTF0.919355仍FAIL，采样不是精确CPU占用或等待时间证明。
新增显式display-jpeg-codec=opencv_jpeg85_v1，只改显示JPEG85；Pillow默认不变，原RGB/BGR、1440×1080/15总fps、80ms图像/150ms控制/RTF0.98保持。初步及最终实际保存帧对照的JPEG字节均与原Pillow一致；不泛化到未经验证的库版本。
当前无额外包装的OpenCV/Pillow/OpenCV三次真实T2 RTF0.960193/0.862132/0.965395，及时结果48/20/14、独立执行帧16/8/1，全FAIL且clean。显示JPEG均值7.10/11.73/8.17ms、P95 11.74/16.43/12.54ms；复测及时动作反而不足，不能把显示编码局部改善当作自瞄闭环修复。
未减少安全检查或证据写盘，未改Command/物理/模型/NN，不使用真值、补帧、刷新旧曝光或旧自瞄代替；未调用子代理，未启动训练/硬件/整场比赛。证据见[显示JPEG优化与外部采样](validation/display_jpeg_20261017/README.md)。

2026-10-17本轮：新增显式owned_process_v1相机渲染隔离，默认thread保持；同一MJB模型/原捕获状态在独立owned进程渲染，仅返回真实RGB，原曝光身份、80ms图像/150ms控制和RTF0.98门限保持。
8个真实NVIDIA样本覆盖六车、步进、弹丸与重置，渲染几何逐SHA相同；7个RGB逐字节相同，另1个至多少量通道差1级，原渲染器重复同输入也存在1级变化。初始严格字节对照失败原包保留；该画面保真检查不是视觉精度/全模型或实时验收，实际native每帧仍绑定自身精确原像素。
当前真实T2的独立进程01/原thread02/独立进程03 RTF0.651521/0.785445/0.768728，及时结果13/17/16、独立执行帧5/5/4，全部FAIL；无统计上提速结论，没有切换默认模式。
首轮同时暴露清理JSON短暂PermissionError，新增仅在原1.3秒退出预算内重读的修复；非法JSON、身份不符、永久不可读仍失败，后两次实际native均clean。初次失败不回写，不能把资源清理成功当作实时通过。
未调用子代理；未改模型/NN/分辨率/15fps上限/物理步长/传感器或输入算法真值，未启动训练、硬件或整场比赛。证据见[独立相机进程与退出竞态](validation/camera_process_20261017/README.md)。

2026-10-17最新：基础64线range传感器改为一次mj_multiRay，保留原64方向、group0/static、自车body排除和最终8m饱和，查询cutoff为无限；未改变物理步、相机/原生算法或80/150ms/0.98门限。
实际场景36组原型逐值相同，新增46项真实测距/重置/移动/观测回归；65项初步检查通过，最终专项689pass/131subtests。
受控竞争微基准30次采样旧单射线耗时1.464–2.502秒，批量0.0510–0.0521秒；无竞争约21.0–21.2ms对8.0–8.7ms。仅为range路径，不是闭环提速证明。
当前无额外包装原T2移动场景RTF0.611237423、52及时结果/19独立执行帧，仍因RTF失败。
实际T2 ABBA旧/新/新/旧RTF0.631651/0.618794/0.781420/0.572116，全部FAIL；后三轮不足10帧执行/目标运动期间执行证明，未继承旧资格。
完整流水线退化仍未解决，不能把传感器微基准或老/新实现波动当作整套实时通过。证据见[批量range与流水线隔离](validation/batch_scan_20261017/README.md)。

2026-10-17最新：消除500Hz调度对完整插件描述的重复deepcopy，只读缓存仅含注册时传感器要求与固定策略；原帧、当前授权、期限和执行守卫仍实时检查。
四组手控六车/相机关开开关RTF0.999802/0.999909/0.999184/0.999940；没有adapter或NN，不能替代自瞄。
实际T2描述的ABBA调度微基准6000次为161.0095/13.0227/11.9594/160.5232ms，只证明该路径开销下降。
原T2移动场景native01保持1ms配置：RTF0.8947118、99及时结果/46独立执行帧，仍因RTF<0.98失败。
native02仅改显式CPython切换间隔0.1ms：RTF0.6554832，约2.215秒后binding_mismatch退出、2结果/0执行；失败保留，设置均恢复，未更改默认值。
不以该微基准声称已修复整套实时性能；80ms图像/150ms控制/0.98RTF不变，根因仍待进一步隔离。
永久证据与复现见[注册元数据调度证据](validation/registry_scheduler_20261017/README.md)。

通用层按公开输入/输出契约适配算法，不按队伍名称判断兼容。当前入口接受完整云台控制链 `direct_gimbal_v1`；只有检测/跟踪状态的 `detector_tracker_target_v1` 需要显式接上原控制器/弹道模块，不能把目标 yaw、裸 Target 或串口字段当成云台目标。未知能力、版本、输出模式及任意执行路径都不会由 HTTP 自动适配。

## 实机链路与当前仿真链路

通常工业相机直接连接上位机，图像交给自瞄算法；下位机 C 板通过串口/CAN 等提供姿态、编码器或其他本体反馈，接收云台控制命令并驱动电机。具体反馈和控制字段由各队固件决定，不要求图像先经过 C 板。例如同济公开环境使用海康工业相机、RoboMaster C 板/BMI088 和虚拟串口，其公开 [Gimbal 协议](https://github.com/TongjiSuperPower/sp_vision_25/blob/bd9f5e798fa3c6dd3b483ae6627796afb41c608d/io/gimbal/gimbal.hpp) 分别声明反馈四元数、yaw/pitch、角速度和控制角度/角速度/角加速度；可核对 [官方项目说明](https://github.com/TongjiSuperPower/sp_vision_25)。

当前仿真接口链路是：**MuJoCo 场景实际渲染 RGB/BGR → 原 CameraInfo/K/D/标定和曝光源上下文 + 同次物理快照的本车姿态反馈 → 上位机完整自瞄算法（检测、跟踪及其控制/弹道链）→ 规范 yaw/pitch action → runtime 重查原 80/150 ms 门限及租约 → MuJoCo 云台关节 actuator → 下一次曝光和关节反馈**。适配程序把原图与本车测量交给算法，不从仿真器喂敌方位置、Target 角度或目标身份真值。yaw/pitch 是算法计算后的控制输出，不是替代图像的输入。相机像素由模拟相机产生，不是物理工业相机采集；qpos/qvel 来自模拟关节，不是实物 IMU/编码器采样。[camera.py](../rm_match/platform_v2/camera.py) 在曝光时复制实际 MuJoCo data；[backend.py](../rm_match/platform_v2/backend.py) 执行经过重检的目标并推进物理。仿真 adapter/runtime/actuator 在这里替代 C 板控制与电机执行，没有连接或验证物理 C 板/电机，也尚未复现特定固件的 CAN、电流环、滤波或硬件延迟。

2026-10-16最新检查点：此前静态/移动场景局部链与pitch重力修复已有证据，但本轮四次原T2移动场景实时复验全部FAIL，RTF0.942783/0.965446/0.814787(额外计时)/0.643594(不绑单核)，不继承历史实时资格。新增本车yaw反馈选项不改变算法角度/RobotIO，接收审计修复不延长原截止；当前目标关联、动态跟踪、射击/完整比赛仍未验。见[本轮原始失败与复现](validation/gimbal_yaw_20261016/README.md)。

历史记录：自家 T2 的历史显式配置曾连续三次通过本机静态实时链，正式入口一次物理RTF0.9971029、107个及时结果/97个独立新帧实际关节消费、0fault/0fire/clean；原80/150ms保持，late/pending不计及时推理或动作。后续源检查点的三次静态实时回归仍FAIL，最新RTF0.821310，当前不继承历史实时资格，见[原始失败记录](validation/aim_reference_20261015/README.md)。旧async02的RTF0.5475和额外计时/调度失败保留。同济source04实际原模型prepare/reset/清理通过，仍无真实图像计算。PB source03七包build/三真实节点graph/reset/clean已过；实际首帧在host序列化或跨WSL请求部分传输时超原80ms，尚无该帧MLP/PnP或控制结果。接口合同不表示三套实时自瞄都通过，也不保证未经适配的程序零修改接入。见[历史逐次验证](validation/aim_live_followup_20261014/README.md)与[此前构建/准备记录](validation/universal_aim_20261014/README.md)。

导航已有 Windows→WSL、实际 LiDAR/IMU→Point-LIO→Nav2→SDK→MuJoCo 的单目标生产 SIL 闭环证据，见 [导航生产验证](validation/pb_wsl_production_20261014/README.md)。这是导航的局部结果，不替代自瞄实时门禁、定位精度、完整比赛或实机 C 板验收。

## 注册与选择

管理员在本机准备 `polar.sim.aim-plugins.v1` manifest，固定 executable/argv/cwd、可用机器人和完整 capabilities。模板见 [aim_plugins.json](../examples/aim_plugins.json)，分别演示本地 JSONL、ROS envelope、Windows→WSL JSONL transport。`reviewed_aim_wrapper.py`、Linux `/opt/polar-reviewed/...` 都是需替换的本机真实程序/路径，模板不能直接作为已部署算法。`supported_robots` 是本地安装范围，可按实际标定与机器人能力配置，不是团队白名单；新队伍不需要改通用协议或硬编码 ID。能力声明只表示接口支持，不代表检测质量、实时性或实车验收。

服务入口：`python -m rm_match.platform_v2 --camera --admission-manifest LOCAL_GRANTS --aim-plugins-json LOCAL_AIM_MANIFEST`；自家 T2 Linux 部署入口 `python -m rm_match.deployment.server` 也支持 `--aim-plugins-json`。自家 launcher 可显式传同一选项；它仍保留自家原生默认配置。其余入口参数按对应帮助设置，不在 HTTP 请求里传模型、import、命令或 topic。

Windows 的 WSL 插件另显式加 `--prepare-aim-plugins`，在 backend/physics 前真实准备；Linux-only 的自家部署 server 不启动 WSL 准备池。模型、binary、source、标定与 dependency prefix 应由对应适配器生成并核验自己的本地注册文件，不能把 T2 spec 换个 binary 路径冒充另一套算法。

原 Qt 客户端固定基线为 `0cedf99b70b1beec99865b9980af6789e6c53d99`，用 [固定补丁](../client_patches/README.md) 校验/安装。`V2 Aim` 通过服务 catalog 中的公开 capability 合同发现 `custom_*` 插件，可用机器人和相机声明匹配时才可选择；绑定 config 精确为 `{}`。选择不自动 claim、arm 或开火。未适配的客户端/算法不能仅加一个 ID 就获得支持。

### 显式 v2 惯性 yaw 参考与能力协商

[aim_plugins_inertial_v2.json](../examples/aim_plugins_inertial_v2.json) 是本地 JSONL / Windows→WSL 的**接口模板，未提供可运行算法或实测资格**。其中 `reviewed_inertial_aim_wrapper.py`、模块名和 `/opt/polar-reviewed/...` 路径必须替换为实际审核过的 wrapper 与环境；不是测试 fixture 或第二套自瞄的部署成果。`supported_robots` 仍由本地安装、标定与实际输入范围决定，不按队名分派，也不授予控制权。

manifest 顶层仍为 `polar.sim.aim-plugins.v1`；其 `capabilities` 显式选择 `polar.sim.aim-plugin.capabilities.v2`，保留 v1 的全部能力字段和值，另增加精确字段 `gimbal_reference='inertial_from_source_base_v1'`。服务 descriptor 对应 `aim_plugin_contract='camera_gimbal_v2'`、`version='2.0.0'`、`required_sensors=['camera','odometry']`。旧 v1 继续使用原 base-relative 关节目标语义；不能把缺少该字段的旧声明推断为惯性参考，或把未知能力当 v1 接受。

wrapper 必须独立声明其真实支持的版本，例如在原真实算法工厂入口使用：

```python
from rm_match.deployment.aim_plugin import CAPABILITIES_V2
from rm_match.integrations.aim_jsonl_peer import run_aim_plugin

# factory 由审核过的算法 wrapper 实现，返回实际 compute；不供应假图像或假目标。
raise SystemExit(run_aim_plugin(factory, capabilities=CAPABILITIES_V2))
```

JSONL 与 WSL peer 的 v2 `prepare` / `reset` 请求均携带完整 capabilities，ACK 必须精确回显同一完整能力对象；不接受缺项、额外字段、错误版本或将任意请求能力原样回声冒充支持。`prepare` 只确认真实资源初始化完成，不调用推理、不代替当前 context 的真实 reset；reset 保持原 2 秒门限。未准备的本地直接 JSONL 仍需真实 reset 协商；WSL 仍需显式 `--prepare-aim-plugins` 和完整 owned-process 清理证明。旧 `ros2_envelope_v1` 没有该 v2 协商，v2 配此 transport 必须拒绝，不能沿旧 ROS bridge 自动降级。

v2 输出仍是原 `polar.sim.action.v2` / `aim/gimbal_target`：`command.frame='base_link'`，yaw/pitch 表达**该动作原 source observation 的 base 坐标系**中的方向角，六身份不变。宿主用同一原观测的 `own.odom_xyyaw[2]` 锁定 source yaw，恢复惯性 yaw；消费边界再以本车新 yaw 转回当前云台相对关节角。平面 yaw 示意为 `inertial_yaw = source_yaw + action_yaw`、`joint_yaw = inertial_yaw - consume_yaw`，实际还需原角度归一化及关节限制。宿主不会以插件另填的姿态或新时间替换该 source。这里的“惯性”是本次源方向的 yaw 保持，不补底盘平移、目标位移、弹道、前馈或完整三维 IMU 稳定。

曝光时的 `camera.own_*_at_capture` 与 source observation 的 own 姿态属于不同采样点。算法若由曝光的相机 / `pitch_link` 方向计算输出，须显式利用该曝光的捕获姿态和标定，再正确转换到原 source base；不能把曝光姿态和当前观测姿态混用，也不能对已是 source-base 的角度重复补偿。每次消费仍重查原 capture 80 ms、SDK 150 ms、epoch、租约、activation 与 fault；yaw 补偿不刷新身份、时间戳或授权寿命。`no_target` / `pending_result` 继续是无角度状态，不用零角动作伪装等待。

固定第五 Qt 客户端的 `custom_*` 解析精确接受 v1 capabilities 和 `['camera']`，因此会安全拒绝 v2，不会在原下拉列表中获得可选资格。保持该客户端和补丁身份时，v2 可经服务 catalog 与具备对应协议的 SDK 显式选择、绑定和授权；不能把 v2 伪标 v1、删字段或借原 native ID 绕过 UI 检查。需要 Qt 直接选择 v2 时，应另做独立客户端兼容版本。本节的分层证据见[本轮固定记录](validation/aim_reference_20261015/README.md)：真实MuJoCo合成指令机械正/负对照、真实无害WSL能力协商与取消回收通过，最终QA为3322pass/45skip/1024subtests；三次实际T2静态实时回归仍FAIL，最新RTF0.821310。最终STOP管道窄修后未重跑NN。协议与宿主关节语义扩展不等于T2移动底盘、移动命中、多车同时自瞄或完整比赛通过。

### 第六 Qt 客户端：显式选择 v2

这里的“v2”是自瞄接口版本；客户端仍使用 PySide6 / Qt 6。
新 [CLIENT_AIM_REFERENCE_PATCH_MANIFEST.json](../client_patches/CLIENT_AIM_REFERENCE_PATCH_MANIFEST.json)
与 [robotio_aim_reference_v2.patch](../client_patches/robotio_aim_reference_v2.patch)
是从原固定 BASE 出发的第六份**完整组合补丁**，包含第五版所有修复，不叠加在旧 checkout 上。
它另接受上述完整 v2 capabilities、`camera_gimbal_v2`、`2.0.0`、`camera+odometry` 和惯性参考组合；
缺字段、额外能力、版本混搭、未知参考、没有协商能力的旧 ROS envelope 均拒绝。
合法 v1 保持原语义。可选项仍经原 Qt 选择、租约、fresh own HUD、手动 arm 和空 `{}` binding config；
选中协议不会自动绑定、续期、取得控制或开火。

新 checkout 使用 `external/polar-rm-client-aim-reference-review`，安装命令见[客户端补丁](../client_patches/README.md)。
Linux 部署的 `setup-client/plan/doctor/launch` 均需携带
`--client-root external/polar-rm-client-aim-reference-review --client-patch-manifest client_patches/CLIENT_AIM_REFERENCE_PATCH_MANIFEST.json`。
部署计划固定同一 manifest/patch hash，doctor、服务启动前和客户端进程取得凭证前重新核验对应源码；
期间改文件必须拒绝。省略该参数仍是原第一份补丁，没有版本自动猜测或回退。
真实 WSL native diagnostic 也接受同一个显式参数，并在收尾复核客户端身份；它的历史默认未变。
旧五份补丁和所有既有证据均保留自己的原字节及资格。

[coop_aim_reference_manual.json](../examples/coop_aim_reference_manual.json) 仅提供第六 Qt 的手控入口配置，
外部导航/自瞄 spec 仍为 null；它不随模板安装模型或运行算法。要接入第三方算法，仍需实际 wrapper、
严格能力协商、相机标定与原时限验证；该 UI 扩展不能使尚未通过的实时/移动/比赛自动获得资格。

第六实际离屏专项56pass/64subtests、继承平台32模块513pass/395subtests/0skip，
使用原Qt窗口与合成SDK/图像夹具，未运行真实HTTP到物理、自瞄NN或可见桌面。
33文件补丁往返、独立check_client和三个实际dry CLI已通过；原五版字节保留。
最终项目QA3332pass/45skip/1024subtests，484程序/测试/补丁输入不变。
原collection环境失败和CRLF探针失败、active-v1性能诊断及复现见[本轮固定证据](validation/qt_aim_reference_20261015/README.md)。

### T2 显式静止身份 scope

[native_robot_scope.json](../examples/native_robot_scope.json) 是**显式本地身份范围示例，不授予算法资格**：仅声明 `red_infantry/red/infantry/3` 和 `blue_infantry/blue/infantry/103`。这些值分别为 robot ID、team、role、referee ID；示例不是通用插件队伍白名单，也不是移动或两车同时运行的验收记录。

平台入口可把该文件与已核验的 native spec 一起显式指定。例如 Windows→WSL：

```powershell
.venv-sim/Scripts/python.exe -m rm_match.platform_v2 --camera --admission-manifest LOCAL_GRANTS --wsl-native-spec LOCAL_VERIFIED_LINUX_SPEC --native-out artifacts/native-scope-local01 --wsl-native-transport wsl_async_bgr_v3 --private-native-pixels --native-robot-scope examples/native_robot_scope.json
```

`LOCAL_GRANTS` 和 `LOCAL_VERIFIED_LINUX_SPEC` 需替换为本机准备的实际文件；Linux 本地原生入口改用 `--native-spec LOCAL_VERIFIED_NATIVE_SPEC`，不带 WSL transport/private-pixels 选项。上面的命令只展示身份 scope 接线，没有替代前述显式调度、codec 和各机实际依赖配置，也不声明达到实时门禁。未提供 `--native-robot-scope` 时仍仅为原默认 `red_sentry/red/sentry/7`。

scope 原始文件按 SHA-256 固定，并在适配器创建、准备/交接等边界重检；运行期间不要修改后沿用旧注册。服务 catalog 的 `supported_robots` 来自该本地声明，输入本车 `team/role` 必须与同一 robot ID 的声明一致；adapter 将对应身份送入原生帧。该声明不授予 HTTP 控制权限，客户端仍需独立 admission grant、租约、绑定和原窗口授权，不能通过 binding config 改身份或扩大范围。

身份扩展仍保留 `stationary_only=True`、速度/稳定等待和每次消费门禁，以及原模型、图像尺寸、K/D、相机安装位姿的严格校验。更换模型或车辆相机安装需要另行适配与验证，不能靠改 scope 绕过。该文件列出两车只表示允许选择这两个身份；既有静止红哨兵 ELF/实时证据不会自动扩展资格。新增两次顺序单车静止实测已通过：红步兵135及时结果/135独立帧物理消费、RTF0.988907；蓝步兵124及时结果/121消费帧、RTF0.998169，均0fault/0fire/clean。原80/150ms保持；不是移动或两车同时运行通过，详见[本轮证据](validation/native_identity_scope_20261015/README.md)。

Linux部署 launcher 对显式scope核对 doctor 的完整类型化声明，在创建服务进程前复核原文件，并检查 ready 回执的同一声明；服务读取另一份合法scope也会被拒绝。scope不会扩大原自动生成的红哨兵 admission，步兵操作仍需匹配的独立本地grant。

方向转换 helper 若显式处理 `pitch_link`，必须另传属于原曝光的 `capture_observation`，用同次捕获姿态转换，不能以当前送达姿态冒充曝光姿态。生产原生输出仍使用显式 `world` 方向；此 helper 边界不改变现有 `base_link` 关节目标语义，也不新增惯性稳定或移动补偿资格。

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

v1 动作是 `polar.sim.action.v2` 的 `aim/gimbal_target`：base-relative yaw、pitch 为 rad，正 pitch 向上，`active`、算法真实 confidence 或 null，以及仅信息性的 fire permission。v2 保留动作形状，但按上文显式源参考在消费时转换 yaw。实际火控保持人工独立授权。

当前通用输出是关节角目标，不含 yaw/pitch 角速度或角加速度前馈；上游协议若依赖这些字段或板端控制器，须声明并实现对应适配/控制链，不能把位置 servo 的结果称成原 C 板控制器效果。通用输入的五维向量也不等于完整 IMU 四元数、加速度或真实编码器协议；机器人运动学映射、时间同步和闭环表现仍需逐适配器验证。

无目标/尚无关联结果使用 `polar.sim.aim-status.v1`，精确原六身份 + `kind=aim` + `status=no_target|pending_result`，没有角度、command 或假置信度。服务仅对显式支持的 `camera_gimbal_v1` / `camera_gimbal_v2` 合同接收这类状态，清掉旧输出并保持同代实例；它不计为推理成功或物理消费。过期、旧代、未知合同或 status 仍拒绝。

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

最终QA02四阶段退出0：3529 passed, 45 skipped, 6 warnings, 1024 subtests passed in 167.70s (0:02:47)。driver212.8633324秒/exit0/reaped。
502项程序/测试/补丁输入及17922项Git已知输入在QA02期间前后逐SHA相同；最终专项624pass/122subtests/2既有warnings，driver23.9851011秒。
native01/02的生产runtime/adapters及其他程序与最终QA逐SHA相同，仅测试fixture test_observation_refresh.py和DEVELOPMENT归因记录两项不同；不把整个输入集合说成相同。
QA01静态接口161项中的camera subtest失败原记录保留；最终fixture用公开注册声明，不降低原采样/期限断言。
QA后仅补记结果文档、归档及索引；冻结期间四份文档原字节归档，最后的结果/归档增补未参加此前QA。
永久归档3691条记录、648份唯一payload、4,846,821字节；160份完整实际BGR留本地，Git取2份样本，13项私有账本只列SHA。
records.tar.gz SHA256：`d0fea92d39667d1654615d5eddb44e9a4dfae02f33c45ddc84c7b9b9c193830a`。

最终QA01四阶段退出0：3575 passed, 45 skipped, 6 warnings, 1024 subtests passed in 166.41s (0:02:46)。driver244.4020972秒/exit0/reaped。
503项程序/测试/补丁输入及17927项Git已知输入在QA期间前后逐SHA相同；专项689pass/131subtests/2既有warnings、driver29.2386000秒，源与无包装native01完全相同。
QA结束后串行运行最终实际scan/独立原射线ABBA，4份程序输入前后SHA不变并与QA一致；36组逐值相同；Python1ms与单线程mask均成功恢复。无竞争旧[0.025352900000143563, 0.026895599999988917]秒、新[0.009682299999894894, 0.00944149999986621]秒；有竞争旧[2.5442957999998725, 1.8151100999998562]秒、新[0.05093620000025112, 0.0520833999999013]秒。
这些为range路径合成竞争结果，所有当前原生实时记录仍FAIL；不因此关闭跟踪/精度/射击、GUI、多车或M0–M5。
QA后仅补记结果文档、归档及索引；四份冻结文档原字节亦归档，最后的结果/归档增补未参加此前QA。
永久归档2302条记录、690份唯一payload、6,307,338字节；783份完整实际BGR留本地，Git取6份实际样本，22项私有账本只记SHA。
records.tar.gz SHA256：`ed60d665d55992a9758e8ed9a00fbe1efbf988344e4bf29b0cc7135a98cb2ea0`。

最终QA01四阶段退出0：3608 passed, 46 skipped, 6 warnings, 1024 subtests passed in 163.55s (0:02:43)。driver 220.70395029999963秒/exit0/reaped；506项程序/测试/补丁输入与17934项Git已知全树输入在QA期间前后逐SHA相同。
最终专项focus03与QA的完整程序集相同：385pass/3skip/1既有warning/51subtests，driver 21.89011859999846秒/exit0/reaped。native02/03与QA仅测试分类负例字节不同，生产代码相同；两次原生均FAIL，未继承资格。
最终equivalence04：8个样本几何逐SHA相同，RGB不同通道数[0, 0, 0, 1, 0, 0, 0, 0]，每个样本最大通道误差[0, 0, 0, 1, 0, 0, 0, 0]；该源与QA只差其后新增分类负例，不冒充逐RGB字节全部相同。
QA后仅补记结果文档/永久归档/索引；四份pre-QA文档原字节保留在归档；最终结果增补未参加此前QA。所有M0–M5未关闭，独立渲染未证实实时收益、目标精度/关联/射击/可见Qt/多车和比赛仍未验。
永久归档5742条记录/650份唯一payload，4874300字节；372份完整实际BGR留本地，Git取3个真实样本，9项私有账本仅记SHA。
records.tar.gz SHA256：`8d45151f160a51df6fa11c5c472f48962c9a08444ce9a105465b7c101ed0892c`。

最终QA01四阶段退出0：3631 passed, 46 skipped, 6 warnings, 1024 subtests passed in 162.20s (0:02:42)。driver 215.64897719999863秒/exit0/reaped；507项程序/测试/补丁输入与17939项Git已知全树输入在QA期间前后逐SHA相同。
最终专项420pass/10skip/1既有warning/57subtests，driver 25.060204100000192秒/exit0/reaped；专项、三次无包装native与QA的完整程序集逐SHA相同。最终实际JPEG-helper验证5个输入SHA与QA对应项相同，原线程数恢复；codec微基准不替实时资格。
QA后原事件聚合：03的14条native_result为tracking=true5条/false9条，另有114条async_pending、99条async_late_discard，最终1独立执行帧。聚合不是逐身份的因果解释；下一步应按原request/frame/deadline区分未跟踪、到期丢弃及最终守卫撤销，不能靠保持旧输出或刷新时间戳补足执行。该离线只读分析helper初次目录定位错误亦保留，修正后未改仿真/测试源码。
QA后仅增补结果文档/永久归档/索引；四份pre-QA文档原字节亦归档；最终结果增补未参加此前QA。三次实际T2与外部采样全部仍FAIL，及时执行复测退化，M0–M5、完整目标精度/关联/射击、GUI、多车与比赛未关闭。
永久归档3243条记录/649份唯一payload，5087177字节；523份完整实际BGR留本地，Git取4个真实样本，12项私有账本只记SHA。
records.tar.gz SHA256：`a91d6dda7fe06e3553193d22bcf12a8e3c8de3b4943972895ef8a9f5a7e96b0f`。

最终QA01四阶段退出0：3665 passed, 46 skipped, 6 warnings, 1024 subtests passed in 166.94s (0:02:46)。driver 228.75098830000206秒/exit0/reaped；508项程序/测试/补丁输入与17944项Git已知全树输入在QA期间前后逐SHA相同。专项、一次真实native与QA的程序输入完全相同；新增测试不代表native/比赛验收通过。
QA后仅补记文档与永久归档/索引，四份pre-QA文档原字节另存归档；结果增补本身未参加先前QA。当前T2仍FAIL，M0–M5未关闭；未调用子代理。
永久归档1600记录/574唯一payload，3182406字节；108个实际BGR留本地，Git取1个真实样本；私有账本仅SHA。records.tar.gz SHA256：`9b4ce894f3fb606506bc5a2448b515ab56138edcbe12f6011dd7db1dc67ec35e`。

最终QA01四阶段退出0：3677 passed, 47 skipped, 6 warnings, 1024 subtests passed in 172.84s (0:02:52)。driver 223.32034099999873秒/exit0/reaped；509项程序/测试/补丁输入与17949项Git已知全树输入在QA期间前后逐SHA相同。最终GL02、专项02、真实native02与QA的程序输入完全相同；各01保留此前原源，不继承新门禁。新增测试不代表native/比赛验收通过。
QA后仅补记文档与永久归档/索引，四份pre-QA文档原字节另存归档；结果增补本身未参加先前QA。当前T2仍FAIL，M0–M5未关闭；未调用子代理。
永久归档3708记录/625唯一payload，4251989字节；257个实际BGR留本地，Git取2个真实样本；私有账本仅SHA。records.tar.gz SHA256：`a5bf4bc357b9e8011d50774325734df688d193749b816012a36e1e7cfe94f6f6`。

最终QA01四阶段退出0：3689 passed, 47 skipped, 6 warnings, 1024 subtests passed in 172.76s (0:02:52)。driver 234.44433290000597秒/exit0/reaped；510项程序/测试/补丁输入与17954项Git已知全树输入在QA期间前后逐SHA相同。专项01、真实native01与QA的程序输入完全相同；旧接收器00保留原源，两个实际原生运行均FAIL。新增测试不代表native/比赛验收通过。
QA后仅补记文档与永久归档/索引，四份pre-QA文档原字节另存归档；结果增补本身未参加先前QA。当前T2仍FAIL，M0–M5未关闭；未调用子代理。
最终COMPARE.json逐SHA核对510项程序输入，对照00与候选01实际仅wsl_aim_async_worker.py不同，测试文件也相同；不据此推断输入轨迹/系统负载相同。初始恢复candidate.py是后续溢出诊断补记前的中间快照，最终运行source快照保留最终源。
永久归档2172记录/609唯一payload，4305906字节；276个实际BGR留本地，Git取2个真实样本；私有账本仅SHA。records.tar.gz SHA256：`553d940176c8da026caf7cbd99d756296d79e84ea3460de4acaa02d434be9354`。

最终QA01四阶段退出0：3716 passed, 47 skipped, 6 warnings, 1024 subtests passed in 193.31s (0:03:13)。driver 263.39399880000565秒/exit0/reaped；511项程序/测试/补丁输入与17959项Git已知全树输入在QA期间前后逐SHA相同。专项02、真实native02与QA的程序输入完全相同；native01保留追加精确边界测试前的源，生产程序相同。新增测试不代表native/比赛验收通过。
QA后仅补记文档与永久归档/索引，四份pre-QA文档原字节另存归档；结果增补本身未参加先前QA。本次原生有界场景通过，目标关联/精度/射击/比赛未验收，M0–M5未关闭；未调用子代理。
永久归档2679记录/607唯一payload，4936884字节；428个实际BGR留本地，Git取2个真实样本；私有账本仅SHA。records.tar.gz SHA256：`6e90de0d78e6c4327d5937f92cd07329a0101203b921e3fdeab797fb63a18d18`。
