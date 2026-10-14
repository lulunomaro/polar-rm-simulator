# 3v3 验证场景：当前入口与缺口

用户最新要求以 **通用导航、决策、自瞄协议及可配置适配** 为主目标。不同队伍的程序通过开放组件接口接入；
北极熊、T2、同济是接入示例，不构成允许队伍或实现的名单。接口、能力协商与当前限制见
[通用插件接口](UNIVERSAL_PLUGIN_INTERFACES.md)。

本页的“手控步兵 + 北极熊哨兵 + 传统决策树 3v3”是验证该通用能力的具体场景。
当前交付是 **Windows 本机手动入口基础**，完整对战尚未跑通；Qt 通用导航/决策选择器也尚未完成。
下述场景缺口用于安排验证，不能将单个队伍的专用实现或协议 fixture 宣称为通用目标已完成。

## 启动手动入口

复用已经准备好的本机环境、固定客户端及其审核补丁：仿真使用 `.venv-sim`，Qt 使用 `.venv-client`。
示例配置为 [coop_manual.json](../examples/coop_manual.json)，默认仅授权 `red_infantry`，没有观战审计权限。

```powershell
# 查看配置对应的启动计划；此命令不启动程序。
.venv-sim/Scripts/python.exe -m rm_match.deployment.coop_launcher --config examples/coop_manual.json

# out 必须为全新目录。启动后在客户端选择获授权的步兵，显式 claim/arm。
.venv-sim/Scripts/python.exe -m rm_match.deployment.coop_launcher --config examples/coop_manual.json --out artifacts/coop-manual-fresh --run
```

此入口启动真实 v2 六车场景服务和固定原 Qt 客户端；程序没有自动绑定算法、发导航目标或开火。
可在可信本地配置中指定已有 `pb_wsl_navigation_manifest` 或 `wsl_native_spec`，它们只注册/准备资源。
旧 native 默认仍限制静止 `red_sentry`。HTTP 请求不能选择可执行文件或扩大人工授权范围。
当前是 loopback 本机入口；没有第二台电脑 LAN 或干净机安装验收。

21 项启动/身份/缺失清理确认测试通过。实际短 smoke 使用全新输出与端口 18766，配置 8 秒；
driver 10.3184506 秒退出 0/reaped/source unchanged，服务正常退出 0，原 Qt 子进程在回收前仍运行，随后由 owned Job 结束。
服务正常资源关闭确认和两个空 Job/回收证明均保存。这个结果只证明启动/退出，不证明人工按键、画面、命中或整场比赛。
证据见[本轮永久包](validation/coop_stream_20261014/README.md)。

## 直接影响对战的工作

1. **移动真实自瞄。** T2 当前速度门和 runtime stationary 门会在底盘运动时撤销自瞄。
   已定位曝光姿态、原算法惯性方向与实际执行时本车角度的转换路径；移动 opt-in 仅有候选，尚未合入或实际验证。
   验证先做本车匀速横移、旋转、启停，保持原图、80 ms 图像门限与 150 ms SDK 窗口。
2. **原比赛决策与导航连接。** 官方独立仓库为
   [pb2025_sentry_behavior](https://github.com/SMBU-PolarBear-Robotics-Team/pb2025_sentry_behavior/tree/d111b635d326775c6c19aa12500a0bbd6a27a588)，
   workspace 固定于 `5faf964b121642d1c8d22dcabf683a13158c2351`。
   当前导航栈只有 planner/controller，未启动接收 `NavigateToPose`/`goal_pose` 的 `bt_navigator`。
   默认 `rmul_2025` 树发固定导航点与小陀螺，没有默认视觉攻击/射击分支；原 Nav2 恢复树不能代替它。
3. **合法状态、地图和取消。** 比赛树需要本车裁判反馈，补给 RFID/受击装甲事件尚未导出；
   固定场地点没有证明与当前 SLAM map 对齐。原树 7 rad/s 小陀螺超过自动接口 2 rad/s 范围，
   首场须显式配置关闭或新增适配，不能静默截断。比赛 BT.CPP 4.6.2 与 Nav2 v3 分进程；
   原取消可累计超过 1.3 秒且 client 会重发，须受原清理期限约束。视觉攻击还需 fresh Target 与失效目标取消。
4. **有来源的自动射击和其余四车。** 当前 fire 为人工通道。自动射击必须来自真实自瞄、经过控制权/期限/裁判仲裁；
   传统决策树机器人明确标注算法来源。随后实际运行整局、结束/reset/第二局及所有资源回收。

通用层 PB 图像请求已从部分传输改为全量抵达 Python peer，但仍超原 80 ms，未向 ROS 发布该图像，也没有检测/PnP/跟踪结果。
这个修复与已有 T2 静态实时、PB 单目标导航分别记账，均不能替代以上完整对战验证。
新电脑、移动精度、多车性能、完整官方规则及 M0–M5 签收仍按计划保留。
