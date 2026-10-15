# FollowPath UUID 到真实导航消费

本页记录显式 `follow_path_uuid_v2` profile：将实际 Nav2 FollowPath goal UUID、原扫描/控制器来源和 MuJoCo 消费回执逐条关联。
这是 [goal-only 生命周期库](NAVIGATION_GOAL_LIFECYCLE.md) 的实际后端验证；尚未注册成通用 goal-aware 速度插件，
也未接 PB 比赛树或决策定位反馈。旧默认 `scan_v1` 及其历史结果保持原样。

## UUID 来自实际目标句柄

[prepare_nav2_goal_controller_overlay.py](../tools/prepare_nav2_goal_controller_overlay.py) 从固定 Nav2 1.1.20 源构建独立 server：
upstream revision `a097086719c88f781aa59788eca29ac6ca5e56db`。原 PB PID 插件 ELF、Point-LIO 和其它已建算法保持原字节，
只在新配置替换 controller_server executable；旧11项资产原件保留，没有覆盖系统 server 或旧构建。

server 的 GOAL_GUARD 在这次原 `computeVelocityCommands` 前取得实际 accepted handle/UUID。
算法计算期间不持 server 锁；发布来源回执前在原目标锁下重检 server active、accepted cancel、pending/preempt、
同一个 handle 和同一个 UUID。请求/原 LIO stamp 与计算期间 pending context 也必须匹配。
不是在 Twist 订阅端读取 latest UUID，不修改原 PID 的速度结果，也不拿目标角/真值代替算法。
实现见 [pb_goal_controller_context.hpp](../rm_match/integrations/pb_goal_controller_context.hpp)。

实际独立构建用时116.924752116秒，编译/链接及loader检查通过；新server SHA为
`09e70405510db579cacbf00d456391d89fdf6ce041fbc860fbc04f562993e53f`。
source/build manifest 与原server身份由启动配置绑定检查，包含同份原字节读取的SHA，不只凭profile名选择。

## 显式版本，动作不扩字段

桥的本地设置为：

```python
NavigationSettings(
    result_profile="follow_path_uuid_v2",
    controller_id="nav2_server_pb_pid_goal_v1",
    # 机器人/generation/topic仍由可信本地配置指定。
)
```

结果 envelope schema 为 `polar.sim.pb-navigation-result.v2`，顶层仍恰好 schema/adapter_id/action/source。
`source` 恰好含：

```text
cloud_frame_id, localization_stamp_ns, controller_stamp_ns, controller_id, goal_uuid
```

goal_uuid 必须为32位小写十六进制普通字符串；action 仍是原六身份的 `polar.sim.action.v2/velocity_body`，不添加 UUID 或重贴时钟。
v1/v2不能互收。桥继续检查原扫描、LIO/计算stamp、controller、generation、动作和原本地回复期限。
`sourced_goal_result()` 只是包装已审核调用者的元数据，不能自证 UUID 的实际来源。
桥本身也不判断该目标是否为“本应用授权的目标”；这需要目标生命周期记录与独立消费审计，不能把格式校验说成授权证明。

[audit_navigation_goals.py](../tools/audit_navigation_goals.py) 先运行原扫描/LIO/SDK期限审计，再验证 lifecycle 的完整 origin_intent、
唯一 operation/goal UUID 和原 context。每条原 ROS v2 result 按 UUID 对应真实接受的 navigation handle；
每条真正消费按完整 typed 六身份及动作值对应原结果。同源可对应多个 UUID 时拒绝歧义，不选最新目标。
origin_source 与后续授权分别保留；合法旧来源消费不因后来的 hold/终态被重标或伪改为零速。
没有跨 Linux/Windows 时钟相减，也不把 cancel ACK、terminal 或 stop_confirmed 当作编码器零速。
未运动目标可计0；本次探针额外要求两个目标都存在实际非零消费。

## 静止扫描建图配置与失败保留

新 stack config v2 显式选择 `controller_result_profile=follow_path_uuid_v2`，并使用
`mapping_profile=stationary_scan_accumulation_v1`。后者只把原 SLAM Toolbox 2.6.10 的
minimum_travel_distance/heading 从0.1改为0，使静止时新的真实非重复扫描可继续参与积分；
原时间间隔0.2秒、map update 0.5秒、use_scan_matching=false、滤波和 PID 保持。
这是显式场景配置，不是默认参数优化或通用 SLAM 精度结论；没有填地图像素、夹紧 start cell、改 TF 或喂真值。

原 movement gate 可能在初始地图窄时抑制继续积分，是源码与日志支持的推断；没有直接记录 accepted-scan 总数，
不能声称测得“只接受一帧”。本系列02真实55请求/53 LIO、0目标，出现一次resize与41次outside，最终原TimeoutError；
此前 goal-only 04 有6次resize与2次outside，运行条件不同，不据此做单因素性能归因。
本系列01因v2配置exact字段ROSTER遗漏在数据启动前失败；两次原失败均保留，未用03重判。

03 的 `peer/GOAL_REPORT.json/last_map_attempt` 保存实际raw costmap receipt、原TF和目标：
192×167、约0.05m/cell，start cell `[20,154]`、goal cell `[40,154]` 均在半开边界内，goal cost为255。
该边界判定不宣称规划可行；实际 Smac/FollowPath 的真实结果另行验证。
`session/stack/planner_server.log` 保存实际StaticLayer resize，包括146×154、190×165、192×167及后续更新，
不是从最终地图倒推启动时地图大小。

## 实际03结果（2026-10-15）

`artifacts/goal-velocity-coop-actual-20261015-03/RESULT.json` 的26检查全部通过。
原 Qt 人工步兵与真实 PB 导航哨兵同场，GO区间15.0010015秒；238/238手动批全部匹配、4473消费步，
90原传感器请求、88原LIO来源、27真实控制器v2结果、463非零导航步，其中387个同一物理步两车同时非零。

| FollowPath UUID | 原目标来源 | 原控制器结果 | 非零导航消费步 | 目标结局 |
| --- | --- | --- | --- | --- |
| `32b1248f593b45f88f6fcf1c3f37ed79` | origin seq15 | 2 | 25 | 实际hold后cancel ACK、terminal、stop成立 |
| `4d4b00dd4aa94040a9b9367488979a98` | origin seq18 | 25 | 438 | 第二目标实际succeeded |

runtime join为0.5917298秒、external owner关闭为0.3981158秒，在同一host1.5秒及原Linux1.3秒预算内完成。
内部35.2830733秒、driver37.4271006秒，exit0/reaped、source unchanged、全部clean、没有强制终止。
12项原生C++ guard测试、桥57测试/23子测试、审计92测试/35子测试另有focused证据；不把单元计作实际算法运行。
本轮全量QA12结果另由进度记录发布，不在这里预填通过数字。

高层目标/hold策略是synthetic探针；目标取实际估计map TF沿map-x偏移1米，不是PB比赛树或定位精度验收。
原80ms相机、150ms SDK、50ms导航等待、2s reset及资源预算保持；没有新自瞄、自动火、完整3v3或M0–M5签收。
decision v1的 navigation/perception仍unavailable，后续需真正的版本化估计反馈和通用插件连接。

## 复现入口

需本机已核验Humble环境、新独立server构建、新stack配置与第五客户端。公开读者须先准备自己的已核验依赖；
这些本机artifact路径不是自动安装接口。全新输出目录、显式运行：

```powershell
.venv-sim/Scripts/python.exe tools/qa_goal_velocity_coop_sil.py --environment artifacts/pb-humble-ext4-runtime-20261014/ENVIRONMENT_COMPAT_FINAL.json --stack-config artifacts/goal-velocity-config-20261015-02/STACK_CONFIG.json --out artifacts/goal-velocity-coop-fresh --seconds 15 --max-wall-seconds 30 --host-opencv-threads 4 --host-python-switch-interval-ms 1 --run
```

环境原SHA为`d60183ebf62d520c72eb20b84207fa4344d8f17183bb0df8eee92f97b7f981ee`。去掉`--run`只输出计划。
旧默认profile、旧probe和历史证据保持原字节；新通过只适用于上述显式配置。
