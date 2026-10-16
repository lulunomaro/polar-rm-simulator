# 原生自瞄的有界分段诊断

计时默认关闭，不进入HTTP配置。`tools/smoke_wsl_native_live.py --profile-phases` 仅接受
`wsl_async_bgr_v3`，使用本机显式准备的同一个NumericPhaseProbe贯穿注册、准备、物理线程、
异步传输与实际图像存证。它不是新算法，不提供假图像、敌方位置或控制授权。

```powershell
.venv-sim/Scripts/python.exe tools/smoke_wsl_native_live.py --native-transport wsl_async_bgr_v3 --profile-phases
```

上面仅生成计划，不启动资源。实际运行仍需原本完整的本地spec、客户端root/manifest、场景/相机/codec、
调度配置、新输出目录及显式run。诊断不改变80ms图像门、150ms控制窗口、原source或Linux/host清理预算。
如果SDK因原窗口过期拒绝binding，不重试、延长期限或重绑来清洗该失败。

`PHASE_TIMING.json` 在线程清理后保存固定标量：原六身份、request/frame/pixel SHA、原deadline、
线程号、墙钟ns、当前线程CPU ns、字节数和队列占用。没有图片拷贝、额外图像校验或热路径JSON/文件写入。
容量262144，溢出显式计数并拒绝完整取证资格。`complete`首先表示保留未溢出，另有clean-shutdown与匹配完整性检查，
不能把它当成算法、RTF或比赛通过。源码/输入hash与真实清理证据仍须独立核验。

whole authority step每步记录；详细authority阶段固定每50个step采样，现有profile-authority墙钟统计仍独立保留。
原请求的传输和存证阶段全部采样。该取样规则写入计划和原始快照，未采样的详细阶段不能算零耗时。
首次全阶段诊断产生约14万条采样并失败，原记录保留；减少详细采样后另存新运行，不回写旧报告。
即使采样变少，诊断仍有成本，不能把不同源码、开关或负载的结果当作受控因果对照。

`PHASE_SUMMARY.json` 只在同线程、同类型原source/request/frame/SHA下相减CPU；跨线程队列只比较同进程墙钟。
reader entry/validated按同一种回复事件匹配，validated-result到accepted-caller单列；缺样或歧义单列，不造零值。
inclusive阶段会重叠，不能相加。wall减thread CPU保留负数，不能叫作GIL等待、锁等待或Linux原生计算。
本机两次实测CPU记账正增量为15.625ms，短阶段CPU为0不表示没有计算；报告同时保留API宣称分辨率和实际观测增量。
host/Linux绝对时钟不互减，原Linux本地时长保持原域。

本轮还将实际BGR文件读回SHA的固定分块从64KiB改为1MiB，完整文件、大小、实际磁盘读回和两次SHA均保留。
只减少每帧Python read/update循环（4,665,600字节时72次降至5次），临时块上界1MiB，原帧队列/输出字节不变。
同一真实文件的离线暖缓存ABBA加一个明确合成Python争用线程显示约8.8倍墙钟改善，全部12个校验和相同；
这不等于生产RTF改善、GIL因果结论或真实闭环签收。优化前后实际运行资格分别保存。

原始失败、独立CPU量化/绑定撤权审查、离线分块对照、最终测试与复现入口见
[固定证据](validation/native_phase_20261016/README.md)。

## 显式按渲染就绪拍摄

`CameraProvider(..., capture_policy='render_ready')` 仅在相机工作线程空闲时拍摄新的物理快照。
本地诊断可用 `--camera-capture-policy render_ready` 选择；默认仍是 `latest_pending`。
工作线程忙时不复制新快照，不推进拍摄间隔或轮询车辆位置；本车订阅撤销和跨回合清理仍先执行。
新拍摄使用当时真实的 wall/sim 时间和本车姿态，已有图像不改时间、不改变原 80ms/150ms 门限。
它可能降低实际帧率，不保证渲染、推理或物理 RTF 达标。计划与报告分别记录选择和实际相机状态。
该选项适用于相机调度，不依赖队名、自瞄算法或真实目标位置。

相机源码变更后，旧 PB 模拟安装位姿文件会按其原源码 SHA 被拒绝，不能覆盖旧文件或跳过检查。
可用 `python tools/capture_aim_mounts.py --out artifacts/YOUR_FRESH_MOUNT_DIRECTORY` 从当前编译模型
重新导出六车静态云台/炮口设计。该步骤零物理步、零渲染、零推理，不是硬件标定，也不会自动重新绑定
旧 PB 插件 spec；新文件及其 SHA 仍须通过原 `checked_mount`，并为后续算法运行显式准备新的配置和证据。
