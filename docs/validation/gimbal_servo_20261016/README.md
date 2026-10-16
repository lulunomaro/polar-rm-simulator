# T03/T04/T06 本车 pitch 重力补偿与实际关节跟随

2026-10-16，父提交2efc1793d639284e3f2f4fb527110b30631c81ea，work/plan-t01-t03。未调用子代理。

## 问题与修复

前一检查点的原静态T2链路虽然通过时限/像素/指令执行检查，末帧pitch原参考约−0.136rad、实际约−0.230rad。
这证明“已消费指令”不能替代关节到达或瞄准验收。源码检查发现旧source路径已有OwnGravityCompensator，
v2 MuJoCoBackend没有使用；当前0.4kg偏心枪管在有限刚度位置环下受重力，反复过期切为当前关节保持会持续下坠。

新增显式`--gimbal-servo position_gravity_v1`，供真实服务器和原生诊断使用；对应Python构造参数
`MuJoCoBackend(gimbal_servo='position_gravity_v1')`。**默认position不变，需显式启用才能获得本轮补偿。**
此选项属于本车底层控制，与队伍/算法无关，不改自瞄RobotIO角度、原始指令、80ms图像/150ms控制门限或租约。
使用本车实测pitch及本车模型质量/重心，tau=m*g*(cx*cos(q)-cz*sin(q))，ctrl=clip(raw_ref+tau/kp,原ctrlrange)。
不改MJCF质量/惯量、重力、kp/kv、阻尼、关节/执行器限位，不读取敌方状态、命中反馈或全系统qfrc_bias。

模型只接受已验证的pitch轴/枢轴、位置执行器/gear/限幅、单一pitch质量，以及无倾斜的平面祖先关节。
非平面、固定倾角、额外pitch后代质量等明确拒绝，无静默近似；这不是任意MJCF的重力控制器。
每个原actuator/integration/integration_entry/fire守卫前恢复原参考再检查授权，避免在多个边界重复加补偿。
失效指令仍撤销为当前实测关节位置保持，再计算该保持位置的本车前馈；不继续使用旧自瞄角度，也不授予开火。
未守卫的本地backend.step也只补偿一次；原默认position路径保持原数值行为。

## 分层证据

实际六车MuJoCo、注入Clock、每150ms发送新零角度输入且TTL40ms的3秒/1500步受控复现：
原position最终pitch−0.0731909172rad；补偿模式约−1.83e−16rad。全序列、源SHA和重放驱动已保存。
这是实际物理/合成时钟证据，不算实时RTF或真实推理验收。

新增22项回归覆盖六车、各执行阶段撤权/禁射、原window过期、模型参数不变、不可验证模型拒绝、限幅、默认计划不变及服务器参数传递。
最初相关51pass；冻结程序集专项510pass/98subtests/2既有warnings，driver12.3866343秒/exit0/reaped，499程序输入前后相同。

| 本轮native | 场景 | 显式servo | physics RTF | raw/及时原生结果/独立执行帧 | 最大执行wall age ms | 末2秒pitch参考误差P95 rad |
| --- | --- | --- | --- | --- | --- | --- |
| 01 | 静态 | position | 0.999536170 | 148/139/138 | 70.2598 | 0.072477198 |
| 02 | 静态 | position_gravity_v1 | 0.999081269 | 148/139/139 | 76.2513 | 0.000175827 |
| 03 | 移动场景 | position_gravity_v1 | 0.999714564 | 148/139/93 | 70.0378 | 0.001207455 |

三组均实际10秒，六车2ms、NVIDIA GL 1440×1080/15fps上限，原CPU4 T2/ONNX、CV4、CPython1ms、mask0x10，
latest_pending、20ms历史显示、stationary red_infantry scope；关闭额外phase/authority计时，保留原trace和03运动审计。
均保持原80/150ms与RTF0.98，首曝光纳入，像素反查/原请求归账/SDK授权/owned清理通过，无错误、fire0。
01为当前相同程序集默认position基线，并未因机械误差而改写其原“链路通过”结果。
02补偿静态末2秒pitch P95从0.072477198rad（4.153°）降至0.000175827rad（0.0101°），各30个原独立帧。
03对方原motion租约驱动实际移动0.763804m，4999个原有效积分消费、241个window、93个独立帧精确连接到运动样本。
03末2秒pitch P95约0.001207455rad，yaw P95约0.020040500rad（1.148°）；水平动态滞后仍需处理。

参考误差按原回执中**写当前控制前的关节实测值**与该帧原生角度指令计算，不是目标LOS误差或命中精度。
末2秒仅用于稳态统计，完整启动样本仍保存且纳入原实时分类；未用末段统计删掉实时失败。
本轮短测支持该已验证平面模型的pitch跟随修复，不替目标身份/连续跟踪、重捕获、PnP精度、弹道/射击、可见Qt、多车或完整比赛。
03仍强制moving_target_tracking_qualified=false；M0–M5不关闭，旧实时/binding_mismatch失败根因未宣告修复。

ELF SHA256 `67819b6812c2c4a87e2b411eed49c1e01cfb67212efdd2f2e0abd2aa3a963dec`，
ONNX SHA256 `b53470b42a5778aca8f3382ebe3c623482599cbf8ebad2e9a0dcc0c7f42c9255`，本轮未重建/替换T2。
原生robot_center是以本车yaw枢轴为原点、世界轴方向的预测位置，并非场地绝对坐标；
早期geometry inspection只作探索，预测时刻与曝光时刻不相同，静态对方位置有初始值假设，不将其数值作为PnP或目标关联验收。

## 复现

在[上一移动场景的完整命令](../moving_scene_20261016/README.md)追加
`--gimbal-servo position_gravity_v1`并选新的--out目录，即为03条件；移除--moving-target-vy-mps为02，
改用--gimbal-servo position为01。所有本地依赖、原spec/模型与客户端身份仍须准备并重新核验。
真实服务器`python -m rm_match.platform_v2`在现有启动参数上追加同一servo选项，启动JSON报告所选mode。
自定义模型不满足验证时必须提供自己的底层控制适配器，不能靠此选项绕过模型校验。
EXECUTED_SOURCE现也显式包含运动夹具源码；程序快照、GIMBAL_SERVO身份、原场景、原像素审计、原生输出和机械误差全序列保留。

最终QA01四阶段退出0：3476pass/45skip/6既有warnings/1024subtests；pytest153.90秒，driver206.5288316秒/exit0/reaped。
499个程序/测试/补丁输入及17911项Git已知输入在QA期间前后逐SHA相同，真实native01–03与该程序集相同。
QA后仅补记结果文档、永久归档与索引；程序及DEVELOPMENT维持已检验字节，冻结期间三份文档原字节亦归档；最后的结果/归档增补未参加此前QA。模型/ELF和凭据不随证据发布；完整BGR留本地，每轮取一个真实样本进Git。

永久归档2640条记录、612份唯一payload、4,307,103字节；422份完整实际BGR留本地，Git取3份真实样本，9项私有账本只列SHA。
records.tar.gz SHA256：`fbe7efcd31ac257771627362ff3dfd14b39b09014b898c8675be94cf94cb4bce`。
[MANIFEST.json](MANIFEST.json)映射原路径/SHA到[records.tar.gz](records.tar.gz)内容寻址payload，逐项解包核验；[FILES.json](FILES.json)固定包内文件SHA（不自引用）。
