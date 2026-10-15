# Registered PB attempt03 只读独立复核

结论：原始证据足以支持本配置下，一车、一个真实 PB 导航目标、synthetic 估计反馈策略的通用注册链路与物理消费；新增编码后、write 前的原 50 ms action 门有独立证据。未发现推翻该窄范围结论的问题。

复核只读取 frozen attempt03 输入和执行时源码快照，未调用原审计函数、未启动 ROS／模拟器／测试／构建、未修改程序。`INPUT_HASHES.json` 保存 503 份输入的 SHA/大小；`EXECUTION.json` 确认读取前后均未变。`RAW_CHECKS.json` 为独立 PowerShell/.NET 原始交叉计算，`raw_join_problems=[]`。

- 149 次 observe、149 份原 decision v2、148 份实际 act 回应。149 份 decision 均精确投影原 own/referee 与原 feedback；138 份 available 估计逐一对应同源、同 stamp 的真实 LIO 与唯一 raw TF lookup。
- 14 份公开 action 各有唯一 final gate。全部 gate 的原 source6、scan、原 deadline、完整 result/UUID 精确匹配实际公开回应；从 host trace 提取原 response JSON 片段加 LF 的 UTF-8 SHA，与 14 个 gate 的实际 encoded SHA 全部相同。
- final gate 最大原 stage 年龄 **41.657967 ms**，最小余量 **8.342033 ms**；原 source gate 最大 **38.688298 ms**。执行时 `navigation_jsonl_peer.py` 的 hook 确在验证/history/编码完成之后、write 之前；peer 在 gate 记录深拷贝之后再采样并检查原 deadline。没有重开 50 ms 或换算 host/Linux 时钟。
- 580 条非零物理消费全部匹配这 14 份实际公开 action，并回溯到原 native ROS result、FollowPath UUID `c3fd85680bf54d459868d1c6ede6c6ff`、原 SDK 窗口及源 capture。零条 status／关闭中断 source 被计作物理动作。最大 capture wall/sim 年龄 **145.487500/138.000000 ms**，均未超过 150 ms；最小 wall 授权余量约 **1.6 μs**，不据此推断更多负载下的时延保证。
- seq13/sim1.3 的目标来自原实际估计 map-x +1 m、y 不变及原四元数 yaw。seq36/sim3.6 已在原 feedback 中观察到该真实目标的 succeeded/terminal/stop_confirmed，并由同次 decision 返回 hold。stop 为实际 action-server 生命周期确认，不是编码器或物理速度归零认证。
- 最后一份 seq150、`hold/synthetic_estimated_goal_completed` 在 host 开始关闭后被中断：无实际回应、无 final gate、无物理消费。本次有 **1 次显式 shutdown-aborted transaction**，不能写成 149 次完整成功 act。它未被用于补齐动作或终态。

7522 个 2 ms 物理步，SDK 受控跨度 15.0054443 s。peer cleanup 0.428731 s、host 共享 1.5 s 内 0.789177 s；WSL birth-bound nested-session scope 空组且 reaped，SDK/HTTP/IO 停止，outer Job 实测 1→0、约 5.2197 ms、无 outer 强制回收。229 份 literal source 快照及 23 份 peer evidence SHA 全匹配；driver before/after 源清单相同。

执行时源码仍是物理 ray/gyro/acceleration → Point-LIO/SLAM/Nav2/PB → 原 TFBuffer exact-stamp estimate；没有世界位姿进入 peer/decision，也没有假 TF/地图、真值输入、旧估计重戳或另一个算法代打。名义 200k rays/s profile 中，每包有效命中点实测 561–807，不能宣称已校准 MID360 密度。

final gate 是 **before-write**，未提供 pipe-write-completion 时戳；host 实际回应与物理消费另由原 150 ms 门证明。取消／替换／第二目标、PB 比赛决策树、自瞄、射击、Qt、定位精度、RTF、完整比赛和跨机 DDS 均不在此验收范围。旧 attempt02 及 review01 原样保留，未用新门追认旧程序。
