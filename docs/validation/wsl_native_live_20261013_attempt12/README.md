# 第12轮：退出后实际RGB审计，实时native仍未通过

```powershell
.venv-sim/Scripts/python.exe tools/smoke_wsl_native_live.py --run --native-transport wsl_stdio_bgr_v2 --private-native-pixels --raw-base64-codec pybase64_1_5_1 --linux-native-spec artifacts/native-contour-v3-final-default-build/operator_source.local.json --client-root external/polar-rm-client-state-review --out artifacts/wsl-native-live-fresh --seconds 10
```

同六车、2ms、1440×1080、15总FPS、1视角；实际曝光起算80ms、150ms控制窗口保持。
仅有逐帧BGR存档的私有WSLv2路径把诊断RGB SHA移到退出后；BGR转换、host/Linux传输SHA仍同步验证。
公开/v1/无逐帧存档路径继续原RGB校验。任意缺失或损坏存档都不能通过新增postclose_actual_pixel_audit门禁。

10.022708秒、5000真实步，RTF **0.9977343448**。
148次raw编码全部80ms内，P50 14.258ms、P95 16.576ms、最大22.080ms；147实际私有发布，1个终止期间未发布帧有原时刻/明确拒绝原因。
step wall P50 1.058ms、P99 3.567ms、最大12.375ms。
首真正native帧为 **frame7 / observed_seq8**，曝光410ms、控制422ms，private→enqueue .913ms，enqueue→request7.933ms。
bridge准备2.830ms后原预算剩 **54.128ms**。
Linux收到4,665,600字节耗7.892ms、SHA2.024ms、tmpfs写2.447ms；向原ELF完整写1733/1733字节，native等待 **41.232ms** 后仍control_timeout。
零native_result、零物理云台消费、fire0，**live_static_chain_qualified=false**。

退出后读取同一actual_frames清单和真实BGR并SHA验证，精确BGR→RGB换通道得到原FRAME_BINDINGS RGB SHA：

- BGR `3bb32201aa3bf37b603c03962a84cb53b70ceb6dcde0e3b394324553939e9422`
- RGB `fdbd9b0a2a0c116dad80e39e3a909b13db50f0d72a27c3ec54136c8464ed7261`

像素审计clean=true，capwall/capsim/control_ns及原request身份严格匹配；未补写原ledger中的延期RGB字段。
原ELF/model/spec不变，运行源码和C扩展结束复核不变；PID698退出-15并reap、tmpfs移除、writer/thread全部退出，errors=[]。
168项本次源码原字节、RESULT/ledger/SDK/actualBGR与清理证据冻结；新增POST_CLOSE_PIXEL_AUDIT和RAW_CODEC_IDENTITY另存。
原模型独立首次离线推理34.7–57.6ms，不能据其回复补本次实时缺失。后续须继续定位实际native首推理/调度延迟；不要反复启动相同配置或放宽期限。
