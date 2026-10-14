# 自有 Qt 客户端 operator_state_v1 补丁

2026-10-15 第五份完整组合补丁为 [CLIENT_CAMERA_ORDER_PATCH_MANIFEST.json](CLIENT_CAMERA_ORDER_PATCH_MANIFEST.json)
与 [robotio_camera_order_v1.patch](robotio_camera_order_v1.patch)。从下述同一固定基线安装在全新干净 checkout，不能叠加旧四版。
包含之前通用组件和 batch 修复；合法相机帧暂时超前 HUD 时验证后丢弃，不刷新原时间锚或有效期，
仍保持原对齐、身份、损坏/倒序/过期护栏。旧四个 checkout/patch/manifest 原字节保持。
第五 review 为 `external/polar-rm-client-camera-order-review`；完整496项/363subtests Qt 回归和真实5秒/30秒手控 SIL 通过。
安装、原失败和范围见[客户端接口](../docs/CLIENT_ROBOTIO_INTERFACE.md)。未向客户端仓库提交或推送。

2026-10-15 后继租约状态顺序版为 [CLIENT_ROBOTIO_STATE_PATCH_MANIFEST.json](CLIENT_ROBOTIO_STATE_PATCH_MANIFEST.json)
与 [robotio_state_order_v1.patch](robotio_state_order_v1.patch)，仍从固定原基线完整应用，不能叠加前两版。
修复 claim ACK 后迟到旧状态误释放新租约，保留真实更高 epoch 撤权与原时间锚；全330/103subtests/0skip离屏回归。
新 review 目录为 `external/polar-rm-client-robotio-state-review`，旧两份 manifest/patch/checkouts 原字节保持。
安装与验证范围见[客户端通用接口](../docs/CLIENT_ROBOTIO_INTERFACE.md)。

2026-10-15 新增可选的 [CLIENT_ROBOTIO_PATCH_MANIFEST.json](CLIENT_ROBOTIO_PATCH_MANIFEST.json)
与 [robotio_navigation_v1.patch](robotio_navigation_v1.patch)。这是从同一固定基线出发、包含原全部修改的组合补丁，
用于通用导航/决策组合的 Qt 目录选择；安装在全新基线 checkout，不叠加旧补丁。
原默认 `CLIENT_PATCH_MANIFEST.json` 和 `operator_state_v1.patch` 保持不变。
新安装命令、启动器选择字段、真实 Qt 与协议物理证据范围见 [客户端通用接口](../docs/CLIENT_ROBOTIO_INTERFACE.md)。
以下原版本记录保持各自原资格，不能重标为新组合补丁已验证。

固定基线：`0cedf99b70b1beec99865b9980af6789e6c53d99`。补丁 SHA256 和每个文件的原/新 hash 在 `CLIENT_PATCH_MANIFEST.json`。
此版本是固定原客户端加审阅补丁，不是原始 byte-exact 客户端。external 副本未提交、未 push。

```powershell
.\.venv-sim\Scripts\python.exe tools/apply_client_patch.py --client-root YOUR_CLIENT_PATH
.\.venv-sim\Scripts\python.exe tools/apply_client_patch.py --client-root YOUR_CLIENT_PATH --run
```

第一条只验证。第二条显式应用；再次运行只验证已应用状态，不重复应用。
工具拒绝不同 HEAD、staged 改动、任何非预期 tracked 改动、partial patch、错误新文件、patch/source hash 不匹配和路径越界。
源文件内容 hash 将 CRLF 归一为 LF，manifest 另记录原/新 checkout 字节 hash，适配 Windows Git autocrlf。

Operator 单独解析 `operator_limited_display` 版本 1；拒绝 legacy 真值、世界坐标和未授权动态机器人 HUD。
Spectator 保留原 full-state provenance 和 xy/alive/hp 等严校验。
未 claim 时只用静态 roster 与实际 JPEG 相机选择和请求 lease；claim ACK 不自动 arm，须再等新鲜、同 session/epoch 的实际 own gimbal HUD。
80/150 ms 控制窗口、fire/focus/watch generation/late ACK 护栏保留。
HUD 使用请求开始时间保守计算 lease 有效期；重复 sample_sim_time 不刷新 own HUD 年龄。
显式 release 立即清除 own 和 robot rows 的动态 HUD 缓存，server release 后必须仍为空。
Map 不绘制隐藏位置；世界方向、分数和敌方动态 HUD 标明 unavailable / unknown，不补 xy=0 或敌 HP。

历史 `91e3653d...` 补丁对应客户端与实际 Qt 回归 282 passed、67 subtests passed、0 skipped，Qt 6.12.0、`QT_QPA_PLATFORM=offscreen`。apply 工具 10 passed。这些实际证据不自动给后续新增能力签收。
历史首轮 `.venv-sim` 的 193 CPU passed / 7 Qt skipped 证据保留；后来在 `.venv-client` 的真实 Qt 环境补齐了这些窗口事件测试，没有模拟 Qt 来宣称通过。
client 的共享 synthetic fixtures 从 Qt 测试模块拆出，claim 后显式提供新 own HUD 样本。原对应 input/fire/focus/window 与 routed ControlPlane 回归已保留。
原完整 requirements 下载在 WebEngine wheel 遇到 ReadTimeout，日志保留。已恢复同版 Essentials/Addons/shiboken 及所有被实际测试使用的核心库；源码没有 WebEngine/Pdf 引用。本轮不声称完整 PySide6 meta-package 安装已完成。

实际本机 HTTP + MuJoCo GL 验证：`artifacts/operator_client_http_gl_20261013_02/RESULT.json`，9 项检查全部 true。
5 秒内 1964 个物理 steps、61 个 JPEG、9 个 manual control HTTP 请求；实际消费 motion 66 steps、gimbal 63 steps，fire 始终为 0。
保存 static / leased / immediate release / server released states 与 HUD、诊断和真实相机 PNG；未运行 native，也未创建 Qt GUI。
可复现命令（新输出目录，不覆盖既有证据）：

```powershell
.\.venv-sim\Scripts\python.exe tools/smoke_client_operator_state.py --run --out artifacts/YOUR_FRESH_DIRECTORY
```

当前 server admission 联调已补齐：SDK `admission_credential` 存内存，`open` body 字段为 `credential`（32–256 字符）。
Qt Transport 从 `POLAR_SIM_ADMISSION_CREDENTIAL` 读取；凭证不进命令行、配置文件、诊断或 patch。
Operator 相机只接受 `source=operator_camera_display_v1`、`camera_display_version=1`、`data_plane=operator_limited_display`，仅 JPEG、帧时间/身份、K/D 和静态 extrinsics；任何 own q/odom/pose、profile 或未来字段均拒绝。
Spectator 仍校验完整旧相机元数据，但服务端必须显式授予 audit 角色，operator credential 不能借为 audit。

新实际权限与 Qt 证据：`artifacts/operator_admission_http_gl_qt_20261013_01`，16 项检查全部 true。
仅 red_sentry scope、跨 scope watch 拒绝、operator credential 不能获取 audit、匿名 operator 拒绝；所有 operator 数据 endpoint 样本保留。
5 秒内 2501 物理 steps，manual motion / gimbal 分别消费 108 / 106 steps，fire 为 0。
`qt/ACTUAL_QT_OFFSCREEN.png` 来自真实 QApplication `app.exec()` 与原 PlatformWindow 的 Qt QPainter/QImage 渲染，使用真实 HTTP 解码的 1440×1080 相机像素；不是 visible desktop screenshot，没有创建可见窗口。
历史该 run 的外层 legacy qualification 仍写着 no Qt GUI，不能据此推翻其 `qt` 内层真实事件循环/renderer 证据；工具后续输出已准确区分 offscreen Qt / visible / native 三种范围，不回写历史结果。

```powershell
.\.venv-sim\Scripts\python.exe tools/smoke_client_operator_state.py --run --qt-python .venv-client/Scripts/python.exe --out artifacts/YOUR_FRESH_QT_DIRECTORY
```

原客户端的独立 `tools/verify_offline_platform.py` audit 入口需 `--admission-manifest`（只有哈希的配置路径）及分别的 `POLAR_SIM_OPERATOR_ADMISSION_CREDENTIAL`、`POLAR_SIM_AUDIT_ADMISSION_CREDENTIAL`。
当前父仓 OFFLINE24 driver 只用 scoped operator 观看，不需要 audit。两条路径不会自动跨角色借用凭证。

OFFLINE24 attempt3 握手后揭示的新协议字段已独立修复：operator 允许经过严格验证的 `clock_profile`、`offline_final_state`、`completed_captures`、`offline_halt_code`。
调度器 kind、七个整数 delay、工程配置标记、终态和有限 halt-code 均有白名单；80 ms max-age 保持不变。嵌套私有字段、非有限数、bool 冒充整数、错误时钟组合或原始异常文本均拒绝。
历史 offline clock 补丁 SHA256 为 `91e3653df439289e25d64eb334f9c6f6a73e0c4aa8e3615ce968010e3b1860ee`；先前 `52fe289e...` 记录及实际 HTTP/Qt 证据保留，对应回归日志在 `artifacts/plan-start/client-qt-offline-clock-regressions.log`。
Git 检查逐调用启用 `core.autocrlf=true`、`core.filemode=false` 并尊重 attributes，不持久修改 Git 配置；canonical hash 仍拒绝真实未知改动，允许同一 Windows checkout 经 WSL 检查。

2026-10-14 通用自瞄接口扩展：当前补丁 SHA 为 `a889f79c20ff850c2531ed52f0bb3b8b55facf4f201efa5ccf45149bb7b1a331`。`custom_*` 只有完整匹配 `camera_gimbal_v1` 能力合同才成为 `V2 Aim` 选项，HTTP binding config 精确为空；未知版本/能力/执行模式及仅 detector/tracker 输出均不当作直接云台控制。详见 [AIM_PLUGIN_COMPATIBILITY](../docs/AIM_PLUGIN_COMPATIBILITY.md)。旧 patch/manifest 原字节另存，未重标旧 HTTP/Qt 报告。

客户端对 `algorithm_status_context` 只接受原 episode/绑定 epoch/adapter 身份一致、当前本会话 gimbal lease 下的有限状态和七个标量字段。原 result deadline 从服务端时钟通过请求开始时间保守映射为本地显示期限；过期、他人车辆、旧代、坐标及异常文本被拒绝。`no_target/pending_result` 表示无动作，`result_available` 不等于机械应用。该显示字段不更新 SDK 控制窗口或 fire 权限。

本次新增客户端纯解析/计划/状态测试 9 项通过；不是 GUI/第二检测器/ROS DDS/物理自瞄闭环证据。后续真实 Qt/算法验收须按当前补丁和算法/source 模型身份另存新报告。

## 第四份显式原子控制补丁

`CLIENT_ROBOTIO_BATCH_PATCH_MANIFEST.json` / `robotio_control_batch_v1.patch` 必须从同一固定BASE完整安装在新checkout。
它包含前三份修复，只在服务器明确协商batch版本1时合并同一原窗口的授权与手动输入。
旧三版本原字节保持，不能叠加；完整协议和资格见[接口说明](../docs/CONTROL_BATCH_INTERFACE.md)。
