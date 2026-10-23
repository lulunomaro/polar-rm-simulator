# T03 Windows 实时调度修复与验证

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

2026-10-16最新：新增显式本车yaw位置反馈增益（默认1不变）和接收判定/日志时钟分离。
本轮真实T2四次RTF0.942783/0.965446/0.814787(额外计时)/0.643594(不绑单核)，均低于0.98，全部FAIL。
03/04原请求归账通过，原80/150ms和像素/清理保持；旧记录不重判。无渲染物理对照数值相同不等于整套实时等价。
当前不继承下文历史局部实时资格，退化根因仍需隔离。完整失败和复现见[yaw反馈证据](validation/gimbal_yaw_20261016/README.md)。

最终QA01四阶段退出0：3513pass/45skip/6既有warnings/1024subtests；pytest173.28秒，driver242.4219978秒/exit0/reaped。
501个程序/测试/补丁输入及17917项Git已知输入在QA期间前后逐SHA相同，真实native03/04与该程序集相同；01/02是接收审计修复前源，全四次FAIL保留原判。
QA后仅补记结果文档、永久归档与索引；程序及DEVELOPMENT维持已检验字节，冻结期间四份文档原字节亦归档；最后的结果/归档增补未参加此前QA。

2026-10-16最新：v2新增显式--gimbal-servo position_gravity_v1，默认position不变。
实际T2静态末2秒关节对原pitch参考P95从0.072477198降至0.000175827rad；补偿静态/移动RTF0.999081/0.999715，
139/139及时结果与139/93帧执行，原80/150ms、像素/请求归账与清理均通过。
这里只是已验证本车平面模型的机械跟随修复；移动yaw参考滞后P95仍1.148°，目标身份/瞄准精度/射击/整场未验收。
代码、默认模式失败机械表现、真实结果和合成时钟复现见[重力前馈证据](validation/gimbal_servo_20261016/README.md)。

最终QA01四阶段退出0：3476pass/45skip/6既有warnings/1024subtests；pytest153.90秒，driver206.5288316秒/exit0/reaped。
499个程序/测试/补丁输入及17911项Git已知输入在QA期间前后逐SHA相同，真实native01–03与该程序集相同。
QA后仅补记结果文档、永久归档与索引；程序及DEVELOPMENT维持已检验字节，冻结期间三份文档原字节亦归档；最后的结果/归档增补未参加此前QA。

2026-10-16最新移动场景：原T2、对方原租约物理运动，首轮RTF0.949281失败保留；
额外阶段计时02为0.999955，关闭额外计时03为0.999038、133及时结果/72帧执行，最大执行wall age77.3833ms；
静态对照04为0.999631、126/121，均保持原80ms图像/150ms控制、0.98RTF门限。
只验收运动场景链路，特定目标关联/跟踪资格保持false；首轮波动根因未定、没有长期性能保证。
源、原始失败、可选计时及复现见[移动场景证据](validation/moving_scene_20261016/README.md)。

最终QA01四阶段退出0：3454pass/45skip/6既有warnings/1024subtests；pytest159.12秒，driver218.4420192秒/exit0/reaped。
497个程序/测试/补丁输入及17905项Git已知输入在QA期间前后逐SHA相同；真实native02–04与该程序集相同，01较早源/失败原记录分别保留。
QA后仅补记结果文档、永久归档和索引；程序及DEVELOPMENT维持已检验字节。冻结期间三份文档原字节归档，最后的结果/归档增补未参加此前QA，不把文档更新称为新一轮全树验收。

2026-10-16增补：真实服务器入口支持显式`--telemetry-publish-interval-ms 20`，范围0..100ms有限数；
默认0继续每个物理步发布显示。无效参数在admission/模型准备前拒绝，启动JSON报告
`telemetry_publish_interval_s`。它只减少历史HUD/receipt缓存的整理，全部物理步、相机采样安排、
原控制期限检查和执行trace保持；首帧、revision/episode/时钟回退、最终停止独立发布，缓存不重戳。
暂停/裁判HUD可延后至下一次显示发布，物理急停/过期归零仍逐步检查，周期不构成硬实时保证。

本轮原T2单车静止、六车2ms/15fps上限/原80ms图像和150ms控制的两次10秒无额外包装复测：
20ms与每步显示RTF分别0.999975/0.999185，及时结果126/133，独立帧执行115/117，像素核对、请求归账和清理通过。
每步显示也通过；Windows记录两轮之间重启，不能宣称恢复由分频或某个CPU参数单独造成。
这只是当前静态局部通过；移动、丢失重捕获、射击、可见Qt、多车、完整比赛和长期稳定未验收。
参数、原失败、诊断包装与无包装样本分别保存在[控制期限证据](validation/control_deadline_20261016/README.md)。

最终QA01四阶段退出0：3431pass/45skip/6既有warnings/1024subtests；pytest152.54秒，driver211.9689139秒/exit0/reaped。
495个程序/测试/补丁输入和17899项Git已知输入前后逐SHA相同；native02/03使用同一最终程序集，01额外诊断包装/父源另存。
QA后仅补记结果文档、进度表与新永久归档/索引；执行程序与DEVELOPMENT保持原已检验字节。
不声称这些最后的文档/归档增补参加此前QA，冻结期间三份文档原字节亦已归档。

2026-10-13（UTC+8），阶段实测。机器为 i9-13900HX、RTX 5070 Ti Laptop、Windows 11、NVIDIA 596.21；Python 3.12.14、MuJoCo 3.15.0。此机器是当前开发测量环境，不代表用户已经冻结最终验收目标机。

固定配置：六车、物理 dt=0.002 s、1440×1080 原始相机、15 总 FPS、一激活视角、10 秒壁钟、前 2 秒作为相机分布 warmup。保留 native 图像 80 ms、input window 150 ms 语义。本次不绑定 native、不打开 GUI、不射击，不证明 A02–A05/A12 完整验收。

## 发现与修复

- 原 `run()` 每次慢步把下次 deadline 重置到当前壁钟，永久丢弃该次欠下的物理步。即使其余时间有 CPU 余量也无法补回，真实 RTF 约 0.71。
- 固定壁钟起点，按原 dt 逐步累加 deadline。落后时执行实际 `mj_step` 补欠步，追平后继续等待；不改采样时间戳，不等待算法，不跨过真实墙钟授权期限。短期 catch-up 的每步仍执行全部 actuator、integration、integration_entry 与 fire 检查。
- 控制锁覆盖一整个物理步，guard 每次先执行 expiry，再检查控制 revision；只有未变更的已分离元数据在本步内复用。撤权、换代、绑定或指令变更使缓存失效；期限、camera budget 与物理可执行性仍在每次 guard 重新判定。此优化没有缓存传感器值或当前姿态。
- receipt 先建立 entry/final 索引，再统一序列化，避免每步约 20 次 JSON 往返与重复扫描；完整各 phase trace 保留。backend 缓存的仅是 immutable model 关节索引与转矩限位，姿态和力仍从当步数据读取。无弹丸时跳过无效 swept collision AABB 计算，有弹丸路径不变。
- raw base64 采用固定 192 KiB、3 字节倍数的小块，并在块间 `sleep(0)` 让出 GIL。输出预分配为 `4*ceil(raw_bytes/3)`，临时块有界；像素、padding、DTO、队列、JPEG 与原 post-encode 身份/停止/过期拒绝机制保持原语义。

## 可核对的局部结果

运行日志、逐步耗时、配置、源文件与哈希在本地 `artifacts` 下保存，旧证据不覆盖。

| 证据目录 | 实际物理 RTF | 结果范围 |
| --- | --- | --- |
| `runtime-profile-before-unprofiled` | 0.70962，3553 步 | 修复前同配置，步耗时 P50 1.531 ms/P99 16.662 ms |
| `runtime-profile-cache-unprofiled` | 0.78664，3934 步 | 只做运行时缓存/receipt/backend 优化，尚未修固定起点 |
| `runtime-profile-chunk-unprofiled` | 0.76530，3827 步 | 期间另一子代理 WSL 编译，受干扰诊断包；不能作为正式 A/B 结论 |
| `runtime-profile-anchored-clean` | 0.99847，4999 步/10.01334 s | 无额外重任务；步 P50 0.911 ms/P99 16.264 ms；raw 131 帧 P95 28.380 ms、最大 63.626 ms |
| `runtime-profile-real-pixel/current` | 0.99846，4996 步/10.00739 s | 独立真实 GL/物理复测与像素审计；warmup 后 raw 118 帧 P95 25.287 ms/P99 26.449 ms/最大 27.662 ms，全部小于 80 ms |

第二次测量实际 renderer raw 与协议解码后的 4,665,600 字节完全相同，SHA-256 均为 `518f975bf2e608e913e649836d1dff9b4f4e4f5f6d75b0a8544694b4cad2ac69`，相机字段 allowlist 审计通过。warmup 后 display 117 帧，P95 32.201 ms，14.61 FPS；第一份 clean 全分布有 display 启动最大值 181.63 ms，保留该异常，不声称全部显示时延达标。15 总 FPS 并不满足候选操作手 25 FPS 指标。

独立 `cProfile` 诊断包在 `runtime-profile-before-cprofile`；其吞吐受 profiler 开销影响，不能与 unprofiled RTF 相比较。短测量满足当前 ≥0.95 候选 RTF，但 native 推理、GUI、完整对局时长、多视角、7v7、跨机和最终质量阈值仍需单独测试。

## 复现与安全回归

使用已安装仿真依赖的 Python，输出目录必须是新目录：

```sh
python tools/profile_runtime.py --out artifacts/runtime-profile-new --seconds 10
python tools/profile_runtime.py --cprofile --out artifacts/runtime-profile-diagnostic-new --seconds 10
python -m unittest rm_match.platform_v2.test_runtime_pacing rm_match.platform_v2.test_window_consumption rm_match.platform_v2.test_native_timing rm_match.platform_v2.test_spin_feedback rm_match.platform_v2.test_observation_refresh rm_match.platform_v2.test_raw_encoding rm_match.platform_v2.test_camera rm_match.platform_v2.test_state_projection
```

上述 65 项实际通过，覆盖 expiry 在各消费阶段穿越、release/epoch 变更、物理数值等价、刷新 own sample、raw 分块全部 padding 余数与真实尺寸 byte equality、renderer 阻塞/停止/身份/队列，以及 operator state 防泄漏。调度测试模拟实际壁钟 stall，验证仍执行原步长并追平墙钟预算，降低 RTF 配置仍按原起点限速。

T13 投影禁止 operator 读取 truth receipts/feedback。原两项 spin receipt 测试与一项 blocking camera 测试改用明确 spectator 审计读取实际消费，控制/claim 仍来自 operator；blocking camera 同时断言 release 后 operator 不再收到该车 applied target。测试语义更新没有放开 operator 权限。

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
