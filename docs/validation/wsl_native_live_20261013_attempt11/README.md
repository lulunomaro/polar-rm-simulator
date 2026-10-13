# 第11轮：显式C编码恢复RTF，原native仍超时

同六车/2ms/1440×1080/15总FPS/1视角，80ms曝光门限与150ms控制窗口不变。
新增显式 `--raw-base64-codec pybase64_1_5_1`，默认仍旧stdlib_chunked；缺1.5.1真实C扩展则setup失败，不降级冒充。
Windows官方wheel SHA `0cfa495858ee229bac9d6dadaaef3d666ccb40de0ad8e04487079f960b33ee90`，
实际C扩展 SHA `2b9cfb88f2a2318a6e6d021dc78d86fa6e472e7d988e4ab9525796c4c65b712d`，运行结束复核不变。

10.04985秒，4998实际步，RTF **0.9946415032**。148实际私有/raw帧，公开raw全部80ms内；P50 15.530ms、最大30.763ms。
private→enqueue2.354ms，相比第10轮提交帧16.488ms降低；这不是受控单因素A/B，也不能把全部旧回退单独归因于GIL。
step wall P50 1.707ms/P99 7.559ms。标准序列化独立同字节短测P50 15.340→1.279ms；JSON序列化仍约8.8ms，不是算法推理性能。

只有1次native_request、零返回/零消费、fire0，**live_static_chain_qualified=false**。
准备图像耗19.931ms，其中诊断RGB SHA **13.597ms**；到bridge前原预算只剩41.569ms。
Linux接收18.743ms、hash1.936ms、tmpfs写1.726ms，stdin完整1727/1727；等待18.860ms后control_timeout。
完整BGR保存、像素绑定、源/DLL身份、owned native清理均通过；不能据组件RTF通过声称实时自瞄通过。

原结果/ledger与165项源码原字节保留于本目录，PRESERVATION_MANIFEST绑定23项实际文件。后续延后RGB诊断另算版本，不覆盖本次失败。
