# 第9轮：显式私有真实像素早发布，仍失败

本机 Windows NVIDIA 相机 + WSL Ubuntu 原 ELF/模型，10.0346 秒实际运行。
六车、2ms、1440×1080、15总FPS、1视角、RTF目标1、曝光起算80ms、控制窗口150ms均保留。
只显式开启独立 private_native_pixels.v1 输入；公开 observation.v2 仍须完整 base64。

```powershell
.venv-sim/Scripts/python.exe tools/smoke_wsl_native_live.py --run --native-transport wsl_stdio_bgr_v2 --private-native-pixels --linux-native-spec artifacts/native-contour-v3-final-default-build/operator_source.local.json --client-root external/polar-rm-client-state-review --out artifacts/wsl-native-live-fresh --seconds 10
```

本轮148帧实际私有发布，148帧公开raw，全部80ms内。曝光→私有发布P50 15.713ms、P95 18.558ms、最大33.521ms；公开编码完成P50 30.447ms、最大48.316ms。
首slot任务在交接后返回 ValueError，零native_request、零native_result、零云台消费、fire0。
首次任务started_wall 33999.5550619、completed_wall 33999.6505244，耗95.463ms，原frame1截止33999.5815709未变。
本轮诊断只记录异常类型，不能凭此断言内部异常位置；后续交接/过期修复须另测。
RTF **0.6712768652**，相较第8轮0.961608明显退化，根因未充分解释。
**live_static_chain_qualified=false**，未提交图像给native，不能据像素hash和空请求集合声称native绑定通过。

原ELF/model已startup-ready但零推理。owned native退出、监督器/pipe/evidence writer回收、tmpfs移除、运行时clean；所有源hash运行前后一致。
本目录保留原 RESULT、ledger、SDK/帧/启动/清理证据；PRESERVATION_MANIFEST绑定20个文件。
EXECUTED_SOURCE_BYTES.json.gz 保存162项原运行源码的base64字节映射，用 EXECUTED_SOURCE.json 逐项SHA验证后可恢复旧失败代码。
派生修复不会覆盖这份实际失败记录。此实测没有Qt可见交互、完整比赛、第二电脑LAN或硬件。
