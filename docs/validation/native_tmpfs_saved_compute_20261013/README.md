# 原实际第8帧数据：Linux tmpfs离线计算诊断

这是保存图像重放的离线耗时，不是实时闭环通过。原曝光410ms、控制428ms、实际BGR、原模型和完整T2/contour-v3保持不变。
实际像素SHA256 `3bb32201aa3bf37b603c03962a84cb53b70ceb6dcde0e3b394324553939e9422`，ELF `4d357067…`，spec `a808f11e…`。

```sh
.venv-linux/bin/python tools/diagnose_native_saved_compute.py --run-root artifacts/wsl-native-live-20261013-attempt8-stdin-scalar-caps --native-spec artifacts/native-contour-v3-final-default-build/operator_source.local.json --storage tmpfs --out artifacts/native-saved-fresh
```

四个新native进程每个先零tick/model-ready，再首次真正检测/PnP/跟踪/控制；耗时 **57.612 / 35.272 / 37.867 / 34.712ms**，P50 36.569ms、P95 54.650ms。
每个首次响应 detector_executed=true、inference_calls=1、pose=1、tracking/should_control=true。
其余14个同packet重复响应 detector_executed=false，不纳入新图推理速度；P50 .604ms不能冒充NN性能。
tmpfs图像读取P50 .509ms、最大1.808ms，四个child工作目录及tracking_mode均在同一owned0700 tmpfs。
CPU为owned child整个生命周期含startup/reap，不能当作逐帧推理CPU。

四个PID761/798/835/872已reap，/proc消失，stdin/stdout关闭，tmpfs工作目录已移除，errors=[]。
PRESERVATION_MANIFEST绑定21项实际结果、请求/响应、stderr、tracking_mode和原图压缩字节；saved_input.bgr.gz解压后必须验证上述原SHA。
运行前后未放宽live80ms门限；本诊断2s等待上限不能补充第8轮超时动作或改变其失败分类。
