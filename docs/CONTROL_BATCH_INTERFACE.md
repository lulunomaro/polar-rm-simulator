# 同一窗口中的原子控制提交

显式 `control_batch_version: 1` 用一次 HTTP 请求提交导航/自瞄授权和其余手动输入，减少同一窗口中的往返。
原 `/v2/control_window`、`/v2/adapter_input`、`/v2/control` 接口保持可用。
批量接口不创建新窗口，不续租，也不授权算法开火；图像80ms、窗口150ms、reset2s和清理预算保持原值。

`POST /v2/sessions` 请求 `server_window_v1` 时，服务器在响应中明确声明 `control_batch_version: 1`。
SDK只接受整数1；没有声明时保持原单请求路径，非法声明拒绝连接，不能靠试发或自动回退判断支持。

## 请求与响应

`POST /v2/control_batch` 仍使用当前内存会话 Bearer 和原平台16KiB请求上限。
请求只能包含以下字段：

| 字段 | 约束 |
| --- | --- |
| `robot_id` | 当前会话授权且实际存在的本车 |
| `lease_epochs` | 完整 `motion`、`gimbal`、`fire` 三个整数epoch；与原窗口及当前租约类型和值完全一致 |
| `window_id` | 已取得的当前原窗口整数ID |
| `valid_for_s` | 正有限有效期，受原命令/窗口期限限制 |
| `adapter_inputs` | 最多两个 `{kind, binding_epoch, seq}`；`navigation`对应motion、`aim`对应gimbal |
| `controls` | 剩余通道的 `{channel, lease_epoch, seq, value}`；必须包含独立手动fire，保留原单位/坐标/限位/spin校验 |

所有通道必须恰好覆盖一次。拒绝重复kind/channel、缺失、额外字段、混合身份、bool/float整数、无效数值和绑定通道的手动代打。
服务端先解析成独立有界值，再在原控制锁内重检当前会话、scope、租约、窗口、绑定和全部序号。
完整验证后再次采样原服务器时钟，一次提交全部成员；任何成员失败不会推进其它序号、输入或激活。
已有过期清理和motion模式冲突只能移除权力，不能部分接受其它成员。
每个截止时间受真实租约与原窗口限制，同一窗口的adapter激活不延长原激活期限。

响应包含原 `schema`、`accepted: true`、`robot_id`、完整 `lease_epochs`、`window_id`、`batch_version: 1`，
以及同顺序的 `adapter_inputs`、`controls` ACK数组。每个ACK保留原单条响应的完整字段：

```json
{
  "adapter_inputs": [{"accepted": true, "robot_id": "YOUR_ROBOT", "kind": "navigation", "binding_epoch": 1, "seq": 0, "window_id": 1, "activation_expires": 100.15}],
  "controls": [{"accepted": true, "robot_id": "YOUR_ROBOT", "channel": "fire", "lease_epoch": 1, "seq": 0, "window_id": 1, "input_expires": 100.15}]
}
```

上面只是两类ACK字段示意，不是完整请求或可用服务器时间。
客户端必须校验完整外层/数组/每个typed身份及期限；不得接受部分ACK、额外字段、重复JSON键或未知版本。

## SDK和客户端

```python
window = client.control_window(robot_id, ["motion", "gimbal", "fire"])
# Qt控制路径还必须等窗口ACK之后由正常事件循环产生的新输入采样。
ack = client.control_batch(
    robot_id,
    {"navigation": binding_epoch},
    {"gimbal": {"frame": "base_link", "yaw_rad": yaw, "pitch_rad": pitch},
     "fire": {"fire": manual_fire}},
    window_id=window["window_id"], valid_for_s=0.15,
)
```

仿真SDK和[第四客户端组合补丁](CLIENT_ROBOTIO_INTERFACE.md)使用相同API。
调用前一次预留全部序号，只发送一次；网络/ACK不确定或过期后不重放，需要显式撤权/重连。
SDK记录原window请求开始的本地时刻；只用同一server window内的expiry-issued相对差计算每个成员的本地上限。
ACK返回时再次采样本地时钟，任何成员迟到即失败，不把服务器绝对时钟当成本地时钟。

原Qt仍要求watch、真实新画面、own HUD、两次F2、焦点/输入及绑定护栏。
只在明确batch能力下，Handoff使用实测batch RTT会话上界，而不是逐请求RTT之和；
原window RTT、20ms采样、5ms唤醒、5ms余量与maintenance成本保留。旧single公式不变，不清零实测峰值。

## 当前证据边界

服务端36项专项、SDK53项含实际loopback HTTP的回归，以及第四客户端29模块484项/347subtests通过。
这些分别是合成时钟/HTTP和Qt后端夹具，不能代表队伍算法、物理命中或完整比赛。
原窗口真实相机、两F2、SDK授权与MuJoCo低点频协议运行另记于[实施进度](IMPLEMENTATION_PROGRESS.md)。
Qt offscreen不是可见桌面；合成导航/决策不是北极熊/其它队伍算法。完整对战、跨机LAN和M0–M5仍需独立验收。
