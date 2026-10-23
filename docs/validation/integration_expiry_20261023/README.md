# 实际积分调用前的过期撤销

2026-10-23 UTC+8，父提交4a6ea9bc2de0f5ad8791bd5c372e610a4fa0ca48，work/plan-t01-t03。

2026-10-23：修复入口校验后、实际mj_step前到期的输入未撤销问题。运行时对当前活动通道提取原lease/input/action/activation/sensor期限，私有提示仅触发原完整权限守卫再次检查；原实际Command/ctrl写入器撤销到期通道。每次撤销后重新采样调用时刻，最多3×机器人数量轮，无等待、不采用新输入、不增加开火。仍有效的其他通道保留。
原六车2ms/NVIDIA1440×1080/15总fps、自有CPU4 T2/ONNX与原SDK手控移动场景，10秒/20秒两次无包装真实T2均通过既有有界场景门禁：RTF0.999675/0.999298、及时结果137/248、严格物理帧84/133、晚活动调用0/0；实际到期撤销3/2次，clean/errors[]/fire0。原80ms图像/150ms控制/RTF0.98未放宽，原失败不重写。
这只关闭本次物理调用到期缺口并证明当前有界实时传感器→真实T2→云台链；目标关联/跟踪保持率/预测弹道/命中精度/射击、移动本车、多车算法、可见Qt、第二实现、导航决策完整树、完整比赛与换机仍未验收，M0–M5不关闭。未输入敌方真值/刷新旧时间戳/使用替代算法，未调用子代理/恢复定时任务/训练/硬件。证据见[调用前过期撤销](validation/integration_expiry_20261023/README.md)。

## 实现

原integration_entry为统一逻辑latch，之后仍有多车检查、证据准备和Python调度。仅保持当时合法的Command会让部分指令在实际call时已过原期限；前检查点的RTF虽然达标，晚调用2/3次，仍FAIL。
现在PlatformRuntime在原entry检查完成后对当前实际活动通道计算原期限最小值：lease.expires、手控input_expires，或算法原action.wall_deadline/activation_expires/sensor.wall_deadline。提示在本次控制锁保护下仅为私有映射，不进入算法/JSONL/HTTP，不赋予任何权限，也没有新取样/新预测或续期。
MuJoCoBackend将映射引用传入原Command守卫包装；MatchSimulation在实际调用前读原clock。如任何提示到期（包括恰好相等），对该车调用原完整守卫integration_expired，重新检查当前lease/epoch/window/source/budget，原实际Command写入路径及gravity/yaw servo撤销到期通道；gimbal回到本车当前测量保持值及原重力补偿，motion力/扭矩归零，其他有效通道保留。下一次循环重新采样实际调用时刻；只做撤销，不额外_fire，不等待算法或改sim time。
在控制锁内每个机器人最多三个活动通道可因过期被移除，循环最多3N轮；失效的受信任回调若不推进，明确抛错并在mj_step前停止，而非无限循环。已有无提示的直接engine/backends调用保留原路径。Python/OS调度仍不是硬实时保证；门禁仍独立记录原entry/真实call/post时间并拒绝任一晚活动调用。
完整阶段日志保留，新增integration_expired消费收据与计数；原18次基础guard/步保持，历史显示采样的完整性检查精确要求18×steps+实际撤销收据数量（禁射场景），未减少原守卫/日志。执行帧仍需原entry、最终target/budget、实际call和ctrl/Command共同匹配，撤销的entry不能冒充执行。

## 检查与原生证据

27项新默认测试：实际MuJoCo中source/action/activation/lease分别早于/恰好/晚于期限，原position与gravity servo两模式；同车motion到期但gimbal仍有效；错误受信任提示在3N界内失败且物理不前进；撤销过程不能额外生成弹丸。测试注入wallclock用于精确复现，没有以该时钟作为真实native验收。最终专项651 passed/13 skipped/4既有warnings/61 subtests，36.06s，driver36.5641658s/exit0/reaped。

| 原生 | 时长 | RTF | 及时结果 | 严格物理帧 | 晚活动调用 | 到期撤销 | 结果 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 01 | 10s | 0.9996750506 | 137 | 84 | 0 | 3 | 本有界场景PASS |
| 02 | 20s | 0.9992980514 | 248 | 133 | 0 | 2 | 本有界场景PASS |

实际NVIDIA/1440×1080/15总fps、六车2ms、CPU4自有ELF/ONNX、stationary red_infantry scope、对方原SDK lease手控vy.08、gravity/yawgain4、OpenCV JPEG85/raw pybase641.5.1、原SDK admission/window ACK及80ms图像/150ms控制/RTF0.98保持。两次clean/errors[]/fire0，无包装/离线停表/真值输入；原native NN与原始BGR逐SHA绑定。01在追加精确边界测试前运行，生产源码与最终02相同；02/专项02/QA全部程序输入需逐SHA一致，01完整源另存，不偷换记录。
ELF SHA67819b6812c2c4a87e2b411eed49c1e01cfb67212efdd2f2e0abd2aa3a963dec；ONNX b53470b42a5778aca8f3382ebe3c623482599cbf8ebad2e9a0dcc0c7f42c9255；客户端patch SHAf3d83e4d4584c7910958fda19f46dc310a310b8fb89376ebf5229a31b69bdf30。未重新构建/替换算法。

## 资格与复现边界

classification.live_moving_scene_chain_qualified=true仅指原手控移动场景的输入/计算/动作/时间/资源链；native_target_association_verified、moving_target_tracking_qualified、full_match_qualified、visible_qt_qualified及hardware_qualified均未据此成为true。没有用敌方真值验证当前算法确实选择/预测了正确装甲，未做目标精度/遮挡/重捕获/命中/自动射击，更未把手控场景运动称为PB导航决策。
本次交付通用运行时的真实过期撤销和两次有界实时通过；完整M1–M5、第二完整自瞄/导航策略、多车真实算法、真实车辆资产、可见客户端、两机LAN、完整3v3/7v7/回放与换机仍按总计划推进，不虚构完成或截止时间。
复现用归档driver及COMMAND.json：准备公开部署要求的原spec/ELF/模型/客户端，`.venv-sim/Scripts/python.exe -X utf8 artifacts/run_integration_expiry_20261023.py --mode native --attempt <fresh>`为10秒；long版本为20秒；focus/quality模式跑检查。全部串行，选新目录，QA冻结Git已知输入；保持失败原包不覆盖。完整实际BGR和私有ledger本地保留，包内取真实样本与脱敏事件/哈希，禁止把未知本机路径当作可移植部署保证。

最终QA01四阶段退出0：3716 passed, 47 skipped, 6 warnings, 1024 subtests passed in 193.31s (0:03:13)。driver 263.39399880000565秒/exit0/reaped；511项程序/测试/补丁输入与17959项Git已知全树输入在QA期间前后逐SHA相同。专项02、真实native02与QA的程序输入完全相同；native01保留追加精确边界测试前的源，生产程序相同。新增测试不代表native/比赛验收通过。
QA后仅补记文档与永久归档/索引，四份pre-QA文档原字节另存归档；结果增补本身未参加先前QA。本次原生有界场景通过，目标关联/精度/射击/比赛未验收，M0–M5未关闭；未调用子代理。
永久归档2679记录/607唯一payload，4936884字节；428个实际BGR留本地，Git取2个真实样本；私有账本仅SHA。records.tar.gz SHA256：`6e90de0d78e6c4327d5937f92cd07329a0101203b921e3fdeab797fb63a18d18`。
