# T03 Windows 实际相机管线对照

2026-10-13，Windows 同一主机，真实 MuJoCo OpenGL 相机和 PlatformRuntime。
原始 RGB 发布提前约 6 ms（稳态 P50），JPEG 显示 P50 略增约 2.2 ms。
本次只有相机和物理运行，没有绑定 native 算法，没有 native 请求、推理、gimbal 消费或 fire。
因此这些结果不能作为 native 闭环验收或完整比赛通过证据。

## 可复现配置与证据

```powershell
.\.venv-sim\Scripts\python.exe tools/profile_camera.py --seconds 10
```

工具允许 5–15 秒总运行时长；默认前 2 秒属于总时长内的 warmup，稳态统计排除这些曝光。
默认每次新建带 UTC 时间和随机后缀的 artifacts 目录；指定已有 `--out` 会直接失败，保留原证据。
每个 provider 在独立全新进程内运行，顺序 baseline → current；可用 `--order current,baseline` 反转顺序。
两边保持原始 1440×1080 RGB、总采集上限 15 FPS、6 个机器人、1 个 red_sentry watch、目标 RTF 1。
provider display/cache TTL 为原来的 2.5 秒；80 ms 为独立的 native 新鲜度参考，未放宽。
GPU 通过当前真实 GL context 的 GL_RENDERER / GL_VENDOR / GL_VERSION 查询，未依赖设备名称猜测。

正式高精度证据：

- `artifacts/camera_profile_20261013T042132Z_a28a9893/COMPARISON.json`
- 每边的 `RESULT.json`、`frames.json`（所有曝光，未发布为 null）、`stages.json`、`physics_steps.json`。
- 每边的 `current_camera.py` 保存了测量时实际使用的当前 renderer 源文件。
- 父目录 `baseline_camera.py` 是固定 git commit `1fdcd249be761100076670bb863c14357e8c62ed` 的原始 camera 文件，通过 `rm_match.platform_v2._baseline_camera` 动态加载。
- baseline 源码 SHA256：`bb76a168136a39c9c55b7a642c70a9ea68f46ef6b049ef4aee3e8f6e89a76ad4`。
- 两边当前 camera 源码 SHA256：`d99cfa60e3b90f03d9ecf1b3c1f1b47442c1f8770b11fdda691a3fac401e6548`。

原始 baseline provider 使用当前 MuJoCoCameraRenderer，以保持相同渲染、镜头 warp 和 GPU 路径；
这次对照测量 provider 发布/编码调度差别，没有声称重现整份旧仓库。
正式轮双侧向 provider 和 runtime 注入 `time.perf_counter`，即 Windows QueryPerformanceCounter，分辨率 100 ns。
这是 profiler 配置，未修改生产默认 `time.monotonic` 或系统计时器。
这一时钟也参与 Runtime 的 pacing，不能把本轮 RTF 与默认时钟首轮 RTF 的差异归因于相机改动。

## 同主机身份

| 项目 | 实际身份 |
|---|---|
| OS | Windows 11，10.0.26200 |
| CPU | 13th Gen Intel Core i9-13900HX，32 logical CPUs |
| GL renderer | NVIDIA GeForce RTX 5070 Ti Laptop GPU/PCIe/SSE2 |
| GL version | 4.6.0 NVIDIA 596.21 |
| Python | 3.12.14，`.venv-sim/Scripts/python.exe` |
| MuJoCo / NumPy / Pillow | 3.15.0 / 2.5.4 / 12.3.0 |

父代理的 native 编译在这两轮测量期间停止，减少 CPU 竞争。仍然只是每个版本一次 10 秒的有界观察，未消除所有操作系统调度噪声。

## 高精度稳态结果（后 8 秒曝光）

| 指标 | 固定 baseline provider | 当前 provider |
|---|---:|---:|
| 曝光帧数 | 117 | 118 |
| raw 已发布帧数 | 117 | 118 |
| capture → raw P50 / P95 / P99 / max，ms | 33.933 / 37.787 / 39.826 / 41.445 | 27.992 / 31.259 / 32.372 / 33.014 |
| raw FPS | 14.624 | 14.748 |
| raw 80 ms 内 / 已发布 raw | 117 / 117，100% | 118 / 118，100% |
| raw 80 ms 内 / 所有曝光 | 117 / 117，100% | 118 / 118，100% |
| display 已发布帧数 | 117 | 117 |
| capture → display P50 / P95 / P99 / max，ms | 33.933 / 37.787 / 39.826 / 41.445 | 36.136 / 40.296 / 41.664 / 45.745 |
| display FPS | 14.624 | 14.623 |
| display 80 ms 内 / 已发布 display | 117 / 117，100% | 117 / 117，100% |
| display 80 ms 内 / 所有曝光 | 117 / 117，100% | 117 / 118，99.153% |
| 全段物理 steps | 3194 | 3205 |
| 全段物理 RTF | 0.6388 | 0.6409 |
| physics tick P50 / P95 / P99 / max，ms | 2.364 / 6.352 / 16.587 / 18.908 | 2.350 / 5.379 / 16.811 / 25.172 |
| 进程 CPU 秒，10 秒 run | 15.391 | 15.594 |
| 平均 CPU cores | 1.539 | 1.559 |
| 全机 32 logical CPUs 的进程平均占比 | 4.809% | 4.872% |
| clean shutdown / errors | true / [] | true / [] |

当前 raw P50 降低 17.51%，P95 降低 17.27%。JPEG 线程隔离使算法 RGB 先发布，display P50 增加 6.52%。
当前最后一曝光的 RGB 已发布，JPEG 在有界停机前未发布；其 `capture_to_display_s` 为 null，保留在曝光分母内。
表中 80 ms 比例仅指曝光到管线发布的墙钟延迟，并未测量随后消费者排队、native 推理或模拟时间新鲜度。
这里没有产生 native 新鲜度拒绝计数，不能把这些比例当成 native 请求成功率。
RTF 仍明显低于目标 1，不能声称已达到实时物理或完整控制闭环。

稳态的每帧发布时刻由短小的 cache `__setitem__` hook 记录，不在物理 tick 内排序分位数。
原生 renderer 内部分段使用其现有 monotonic 时钟，Windows 下有量化；外层 render_total / encode 使用 QPC。
正式轮 renderer 包装器未转发 `last_timings`，因此 `provider_timings` 的 scene_update / render_readback / lens_warp 为 0 个样本；
实际 renderer 返回的原始分段值保存在 `stages.json`。工具已补上包装器透传，后续运行可从 ledger 取得这些分段，
本报告没有回填或编造历史 ledger 数值。

## 默认时钟首轮（保留）

`artifacts/camera_profile_20261013T042020Z_eb7a000a/COMPARISON.json` 使用原始生产 `time.monotonic`，没有 QPC 注入。
两侧稳态各 102 曝光和 102 raw 发布，raw FPS 均为 12.75。
baseline raw P50/P95/P99/max 为 31/32/109.68/156 ms，80 ms 内 100/102（98.039%）；
当前为 16/31.95/32/32 ms，80 ms 内 102/102（100%）。两侧 RTF 分别 0.2258 / 0.2224。
这些时间戳表现为 15–16 ms 的量化，故用于保留默认配置行为证据；不能与 QPC 轮混合计算加速比例。
首轮没有进程 CPU 统计，报告没有补造该数据。

## Raw 像素与算法边界核对

两边都保留第一张已发布 raw 对应的真实 renderer RGB 引用，停机后再解码 base64 并计算 SHA256，
避免每帧 hash 增加测量延迟。每边 4,665,600 字节，逐字节相同：

| 版本 | 同一帧 renderer RGB 与 raw DTO 的 SHA256 |
|---|---|
| baseline | `a07a5cc91bccf5bba02bb3e6e3b6e8ca3fb3affca643930c4f5079c989f7fa2c` |
| current | `6b1962e697bc3120db2587bb45fc958aaee726fa0d825625b5f28a3ffd646f67` |

不同进程的曝光模拟时间可能不同，因此不要求两个版本之间 hash 相同；核对的是每条管线渲染 RGB → raw DTO 没有改写像素。
两边 sensor DTO 严格匹配 camera 字段白名单和 image 字段白名单，provenance 为 `simulated_raw_camera`；
没有额外敌方真值、目标标签、检测框或算法目标字段。
这里没有绑定算法，也未声称逐帧 native 消费的数据已独立审计。

工具验证：`python -m pytest tests/test_profile_camera_tool.py -q`，3 passed。
覆盖空样本不宣称 freshness、80 ms 边界与过期样本保留、已有失败证据目录禁止覆盖。
