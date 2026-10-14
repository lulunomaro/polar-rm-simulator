# Windows GPU 相机与 WSL 原生传输

这是本地显式实验入口，使用 Windows 的真实 NVIDIA/MuJoCo 原尺寸相机和 Ubuntu
内的自有 T2/contour-v3 Linux ELF。它没有提供 Windows 原生算法构建，也没有完成
M1、可见 Qt、LAN 或完整比赛验收。原模型、94 个恢复源码、PnP 门限与历史证据保持原字节。

## 身份与生命周期

`own_wsl_registry()` 校验同一份 spec 原始 SHA、完整 ELF/构建/生成源码/配置/模型、
原 T2 与新图像 frontend 的复合身份，严格映射 `/mnt/c` 与 `C:`，拒绝越界与 reparse。
分发固定为 Ubuntu；网络绑定仍仅允许 FOV 配置。预加载在本地 setup 完成，原 ELF
实际进入 `read(0)` 等待才声明 ready；没有提前拍帧、推理或推进物理。

预加载模型只被第一个相同配置的绑定接管。首次 reset 保留该进程，换代会关闭并
重建；取消是持久状态。关闭或启动失败时回收 owned Linux 子进程，保存 `/proc`、
wait/reap 和 pipe 关闭证明；v2 同时清理专属 0700 `/dev/shm` 目录。全量资产检查在
注册和每次启动边界执行，运行中已加载进程不每帧重算模型与 94 个源码的 SHA。

## 两种显式传输

`wsl_stdio_v1` 保留共享盘文件入口。独立离线实验中，4,665,600 字节的 DrvFs
读取中位数约 58 ms；supervisor 和原 ELF 会重复读取。这份结果是文件系统诊断，
不能视为实时模型耗时或闭环通过。

`wsl_stdio_bgr_v2` 使用有界头部和恰好 4,665,600 字节的真实 BGR 负载。
同一次严格验证产生的 RGB 私有字节用于确切通道交换；不可变 BGR 快照只传给
可信本地桥，不进入 JSON observation、HTTP session 或控制配置。Windows 与 Linux
各核验大小和 SHA，Linux 写专属内存文件，然后只替换原 frame 的 `image.path`。
相机标定、本车曝光状态、图像内容、曝光时间及控制时间均不变。v2 的原始 BGR
输入由独立有界写入线程保存为 `actual_frames/sensor_<frame_id>.bgr` 与 SHA manifest；
提交只接收同一份不可变 bytes，工作线程必须写入并读回核验。队列满、重放帧号、
SHA 或 IO 失败明确报错，停止后排空已接受帧；关闭时缺帧或线程仍存活不能声明 clean。
v1 继续同步共享盘文件。v2 的 Linux 本地计时与 Windows QPC 计时分别报告。

相机发布后通过同一身份/消费者/时效检查唤醒算法调度，不等待下一个 50 ms 周期。
排队标记绑定实际原子 sensor packet 的帧号，避免发布竞态造成重复输入。
观测先复制快照再验证并解码，同一份元数据与像素配对；JSON 类型和未知字段严格拒绝。
本机相机在编码时封装与原始 bytes、编码字符串、机器人、episode、帧号、曝光时间及
图像形状绑定的私有凭据。只有注册的相机凭据且字符串对象完全相同时可复用该 bytes；
普通 JSON、同值新字符串、伪造对象或元数据变化仍走完整严格解码。凭据不进入 HTTP、
公共 observation、日志或第三方 adapter。它不能跳过标定、权限、期限和后续 SHA 检查。
每次原生观测同时保留曝光起算的 80 ms 壁钟期限及 80 ms 仿真时间期限。
手动操作仍走真实 SDK 的 150 ms server window，native 没有自动开火授权。

## 测量与复现

真实测试包含首帧，并单独统计 raw、准备、传输、原生结果、物理消费、超时、丢帧
和清理；空结果不能用零延迟替代。setup 和报告失败保留原文件及异常栈；原始
ledger、SDK、帧绑定和 runtime 观测在派生统计之前落盘。

固定六车、2 ms 物理步、1440×1080、15 总 FPS、一视角、RTF 1、10 秒壁钟：

```powershell
.venv-sim/Scripts/python.exe tools/smoke_wsl_native_live.py --run --native-transport wsl_stdio_bgr_v2 --linux-native-spec artifacts/native-contour-v3-final-default-build/operator_source.local.json --client-root external/polar-rm-client-state-review --out artifacts/wsl-native-live-fresh --seconds 10
$env:POLAR_TEST_WSL='1'
.venv-sim/Scripts/python.exe -m pytest rm_match/integrations/test_wsl_operator.py rm_match/integrations/test_wsl_operator_pipe.py -q
```

输出必须选新目录。固定环境与原始失败在
[实际测试证据](validation/wsl_native_live_20261013/ATTEMPT3.md) 及同目录的后续尝试中保存。
单位、无算法子进程传输、保存图像离线计算、实时链与完整比赛的资格分别记录。

截至第七轮，实时闭环仍失败。第六轮首次收到完整真实图像，但 Linux 接收/核验/写入
已超过剩余期限，没有交付 ELF；第七轮取消同步图像写入后完整图像接收约 16.75 ms，
仍为原生超时、0 返回、0 有效执行，RTF 0.840。该旧报告未记录实际 ELF stdin 写入字节，
不能据此确定是否开始 NN。新 worker 累计实际 `os.write` 返回并单独报告
`native_stdin_bytes_written` / `native_stdin_complete`，只证明输入交付，不能单独证明推理完成。
旧报告中 `native_identity` 的 v1 标签有误，原 STARTUP 与请求日志均为 v2；新 v2 对象
显式登记两个 pipe 模块的 SHA，旧失败报告保持原字节。
