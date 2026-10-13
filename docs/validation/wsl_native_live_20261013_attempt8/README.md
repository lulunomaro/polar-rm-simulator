# 第八轮真实 Windows GPU / WSL v2 测量

结论：FAIL。原 80ms 图像期限、150ms SDK 窗口、六车、2ms、1440×1080、
15总FPS、一视角保持。未得到原生结果或有效物理云台消费，不是 M1、完整比赛、
可见 Qt 或 Windows 原生构建验收。

实际命令：

```powershell
.venv-sim/Scripts/python.exe tools/smoke_wsl_native_live.py --run --native-transport wsl_stdio_bgr_v2 --linux-native-spec artifacts/native-contour-v3-final-default-build/operator_source.local.json --client-root external/polar-rm-client-state-review --out artifacts/wsl-native-live-20261013-attempt8-stdin-scalar-caps --seconds 10
```

| 测量 | 真实结果 |
| --- | --- |
| 壁钟 / 物理 RTF | 10.0498323s / 0.9616081，低于本机诊断门槛0.98 |
| 原始相机 | 149帧，P50 28.861ms、P95 32.819ms、最大37.661ms，全部≤80ms |
| 首个原生请求的 host 准备 | raw→enqueue7.990ms，enqueue→native_request20.195ms，bridge准备3.863ms |
| host bridge 剩余期限 | 21.199ms；Windows QPC，原曝光起算，没有刷新 |
| Linux 图像阶段 | 完整4,665,600 bytes，接收12.462ms、SHA2.032ms、tmpfs写4.045ms |
| 原 ELF stdin pipe | 实际os.write累计1733/1733 bytes，完整JSON+LF，0.028ms |
| Linux 后续等待 | 5.584ms后control_timeout；0原生返回、0有效执行 |
| 原始图像证据 | 接受并写完1帧，失败0，线程退出；SHA一致 |
| 生命周期 | 原PID698退出-15并reap；专属tmpfs已删除；runtime/error[]与clean shutdown通过 |
| Windows CPU | timed runtime.run含收尾/all threads共16.0 CPU s；不含setup或WSL子进程 |
| Linux CPU/RSS | 原ELF完整生命周期含模型启动：user0.395443s/system0.423032s/maxRSS142884KiB；不能作为单次NN时延 |

只有管道写入完整可证实，不能据此证明 ELF 已读完、NN 已执行或推理完成。
Linux 阶段计时仅在 Linux 本地相加；不得与 Windows QPC 绝对时间相减。
`RESULT.json` 收录原 `SUPERVISOR_ERROR.json` 的精确输入字节与清理记录，身份标签
已正确声明 `wsl_stdio_bgr_v2` 并校验两个 pipe 模块。spec、原模型、94个恢复源和
contour-v3/ELF身份与前几轮保持一致。

本轮减少了每个物理步对静态 descriptor 的重复深拷贝。独立 FakeBackend 配对短测
复制250→0，step+demand P50 .4919→.4026ms；单独保留活跃故障绑定及 SDK 的真实
Windows GPU 实验为RTF0.9983966。这些证据不能证明第七轮RTF0.840的根因已解释。
第八轮恢复到0.962仍未关闭实时性能缺口，不再以相同配置盲目重测。

第八轮后发现并修复 Linux select 返回后的期限缺口：等待长度限制为实际剩余预算，
返回后再次核验，过期的可读结果或stdin都不能继续处理。两个实际无害子进程回归
验证过期可读回复仍被拒、期限内回复保持原时戳；这些测试没有原ELF/NN/GL资格。
本目录保留的是第八轮实际执行版本，后续修改不回写报告。

`SOURCE_SNAPSHOT_MANIFEST.json` 保存16个关键执行模块/工具的确切字节与执行时SHA，
包含更新前 worker；只逆向恢复此后的select检查差异且必须吻合已存SHA。
不是全仓库快照。`sensor_9.bgr.gz` 是实际保存图像的无损gzip，解压后必须恰好
4,665,600 bytes、SHA256 `3bb32201aa3bf37b603c03962a84cb53b70ceb6dcde0e3b394324553939e9422`。
`sensor_9.json` 与 `SOURCE_FRAME.json` 绑定原始来源；没有修改像素或添加标签。
公开包不含 admission credential、原 ELF 或本机依赖。旧第一至七轮报告保持原字节。

从本目录恢复保存帧输入（在仓库根目录运行 Python，输出须是新目录）：

```python
from pathlib import Path
import gzip, shutil
source = Path('docs/validation/wsl_native_live_20261013_attempt8')
replay = Path('artifacts/attempt8-saved-replay')
frames = replay / 'actual_frames'
frames.mkdir(parents=True, exist_ok=False)
shutil.copyfile(source / 'ledger.jsonl', replay / 'ledger.jsonl')
shutil.copyfile(source / 'sensor_9.json', frames / 'sensor_9.json')
(frames / 'sensor_9.bgr').write_bytes(gzip.decompress((source / 'sensor_9.bgr.gz').read_bytes()))
```

`tools/diagnose_native_saved_compute.py` 现在按唯一请求帧号和 SHA 严格选择 v1 文件或
v2 manifest，拒绝歧义、越界、重解析和错图，记录实际输入来源。Linux 离线入口示例：

```bash
.venv-linux/bin/python tools/diagnose_native_saved_compute.py --run-root artifacts/attempt8-saved-replay --native-spec artifacts/native-contour-v3-final-default-build/operator_source.local.json --out artifacts/offline-attempt8-fresh
```

须先按构建文档获得同一身份的 ELF/spec。此工具的2s等待和保存帧请求始终是离线诊断，
不能补入第八轮实时结果；曝光及控制仿真时间取原ledger，没有生成新曝光。

后续优先削减实际图像编码/准备/跨系统传输成本，并对首个真实 NN 的剩余时间测量。
本机只读库存未在 PATH/VS注册/标准目录/两Python环境中找到 Windows 编译器或
OpenVINO，不是全盘搜索；Windows原生路线需要单独准备可追溯工具链。
所有全量检查以 `artifacts/quality-20261013-wsl-frozen-checkpoint/manifest.json` 为准，
本地质量通过也不能替代实时链验收。
