# T03 Windows 实时调度修复与验证

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
