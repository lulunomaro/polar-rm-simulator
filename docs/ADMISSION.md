# T13 本地准入与显示数据权限

版本：`polar.sim.admission.v1`，2026-10-13。仅适用于当前 loopback 服务；不代表两台电脑 LAN、多用户账号系统或最终多人比赛验收。

## 服务端授权

HTTP `/v2/sessions` 必须提交服务端认可的 `credential`（32–256 字符）和匹配的 role。角色、车辆范围和审计权限来自本地 manifest，客户端不能提交 `allowed_robots`、`audit_authorized` 或 `trusted_admin`。缺 policy/凭据返回 401，角色升级返回 403，额外权限字段返回 400。

manifest 顶层严格为 `schema` 与 `grants`；每个 grant 严格包含：

| 字段 | 语义 |
| --- | --- |
| `credential_sha256` | 凭据 UTF-8 的 SHA-256，64 个小写十六进制字符；不保存明文凭据 |
| `role` | `operator` 或 `spectator` |
| `allowed_robots` | operator 必须是已加载 robot IDs 的非空、无重复列表；spectator 必须为空列表 |
| `audit_authorized` | operator 必须 false；spectator 必须 true，明确授权完整审计真值 |

manifest 最大 64 KiB、最多 64 grants；重复键、未知字段、未知机器人和不完整权限拒绝。同一 credential 可显式重连并取得新的短时 bearer；旧 bearer、租约、绑定和输入不恢复。policy 在启动时加载，撤销/轮换 manifest 需重启服务，旧 bearer 随重启失效。这是最小本地 grant 机制，不包含账户、密码恢复或权限管理 UI。

policy 的权限与 `manifest_sha256` 从同一份有界 raw bytes 生成。doctor、launcher 与 server ready 使用这份身份；启动前 manifest 改变、doctor 后范围替换、Qt 启动前源码/补丁身份变化都 fail closed。SHA 只标识文件内容，不是用户凭据。

服务使用 `AdmissionPolicy.from_manifest(path)` 与 `TransportConfig(admission_policy=policy)`。裸 TransportConfig 没有 policy 时 HTTP 招生关闭，health 仍可检查。`python -m rm_match.platform_v2 --admission-manifest <本地文件>` 和默认部署服务都要求 manifest。直接 `control.open_session()` 是可信管理员/本地测试上下文，网络请求无法选择这一路径。

默认 launcher 为当前默认组合生成只允许 `red_sentry`、无 audit 的 grant，凭据仅在进程内生成并交给 Qt 子进程环境 `POLAR_SIM_ADMISSION_CREDENTIAL`，manifest 只存 hash。自定义 `--admission-manifest` 时，launcher 从该环境变量获取 operator 凭据。凭据不进入命令参数、URL、plan、状态报告或 SDK repr；本地招生材料不提交到公共仓库。

独立 SDK 使用 `PlatformClient(url, admission_credential=credential)`，Qt transport 从同名环境变量读取。`open()` 返回 session ID、role、scope/审计状态和期限，隐去 bearer；随后使用内存 Authorization bearer。缺准入 ACK、ACK 中非法 scope/角色或丢失响应保持 uncertain；明确的 HTTP 拒绝是已知结果，不能盲重放控制。

## 车辆权限与数据平面

operator 的 robots/state/capabilities/catalog 只列授权 robot IDs。watch、claim、bind、control、renew、release、unbind、adapter activation 和 control window 均在服务端校验 scope；匹配 lease owner/epoch 也不能绕过范围检查。lease 有效性与 admission 是独立检查。

| 端点/角色 | 可见内容 |
| --- | --- |
| operator `/v2/state` | `operator_limited_display`；scope 内静态 roster、公开 phase/time/winner、仅有效本会话 lease 车的本车 HUD与自己控制元数据；无坐标/odom、敌方动态、他人配置/指令/receipt |
| operator `/v2/frame` | `operator_camera_display_v1`、`camera_display_version=1`；scope 内实际 JPEG、静态 K/D 与 camera-to-gimbal 外参、帧 identity、原 capture/encode/age 与尺寸；没有任何 own qpos/qvel/odom 或世界姿态，无 claim 也不能由视频元数据拿坐标 |
| 明确授权 audit 的 spectator | 完整审计 state/frame；只读，不得 claim/control |
| 算法内部 sensor packet | 保留真实像素、原采样时钟、K/D 与捕获时本车传感器；不由 display 反向构造；ideal odometry/ranges 的 T09 缺口仍存在 |

相机投影未知字段默认剔除，calibration 不返回可扩展的 `profile`；只允许 intrinsics 的 fx/fy/cx/cy/distortion_model/5 系数与 extrinsics 的 parent_frame/calibration_id/translation_m/xyzw。不填虚构 xy=0、假 HUD 或到达时位姿来兼容旧客户端。

OfflineRuntime 继承同一 scoped state/frame 投影。额外只公开白名单 clock profile 与 scheduler tick/ns、工程 delays、barrier_state、completed_captures、COMPLETED/HALTED 终态和去除私有异常内容的 `offline_halt_code`。renewal/cleanup 可读取自己的 binding epoch/owner/lease epochs；完整 native 错误与 trace 留在可信审计，不能借离线模式恢复 HTTP 全量真值。

## 已执行的局部验证

- 104 项 admission/HTTP/SDK/control/camera/state 检查通过；覆盖匿名招生、错误凭据、角色升级、越 scope 各写端点、scope/lease 独立、未 claim 视频元数据、未来 truth 字段、显式 audit。
- 62 项 offline/admission/camera/projection 检查通过；实际 HTTP OfflineRuntime 验证终态与 renewal 字段可用、异常路径不泄漏、release 撤销 HUD、operator frame 无 own pose；内部 capture own sensors 保留。
- 实际 MuJoCo QA 使用显式随机本地授权并通过：multiclient 20 checks、真实 GL camera 35 checks、resupply 15 checks。QA 管理者明确授予所测 operator scope 与 audit grant，凭据只在内存，不写证据；这些 QA 不替代两电脑 LAN。

对应测试入口：

```sh
python -m unittest rm_match.platform_v2.test_admission rm_match.platform_v2.test_offline_projection rm_match.platform_v2.test_server rm_match.platform_v2.test_client rm_match.platform_v2.test_camera rm_match.platform_v2.test_state_projection
```

剩余范围：LAN 仍关闭；TLS/远程身份、跨机丢包/重连/多人实测未验收。没有恶意同进程 Python 插件沙箱，没有真实 MID360/自主 SLAM 验收，也没有完整 3v3/7v7 结论。本地 grant 启用关闭的是已验证 HTTP 权限漏洞，不能关闭 A10 或发布多人比赛能力标签。
