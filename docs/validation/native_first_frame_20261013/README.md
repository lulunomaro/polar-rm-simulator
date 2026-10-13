# 首帧分段诊断：预分配没有显示可信改善

两个独立诊断 profile 都由 29 个 C++ 翻译单元干净构建。原 94 文件、contour-v3 与模型未改；默认 source composition 和生成 main 保持，诊断 ELF 使用新的复合身份。正式 registry 明确拒绝这些 spec，仅保存帧工具的显式 `--phase-profile` 专用验证入口接受。

| 实际保存帧测量 | 四个 fresh 首响应 ms | P50 ms | infer P50 ms |
| --- | --- | --- | --- |
| first-frame-trace | 53.336 / 29.982 / 38.488 / 32.814 | 35.651 | 24.009 |
| request-preallocate-trace | 55.725 / 31.241 / 35.504 / 33.862 | 34.683 | 23.088 |

每组另有 14 次重复同 packet 的非推理回复，它们不计入 NN 性能。请求创建 P50 约 0.051 ms、Tensor 约 0.006 ms；纯初始化分配约 0.057 ms，没有可信收益，未替换生产默认行为。未预热推理、未给假图或移动时间戳。嵌套阶段不能相加，独立 P50 不能相减。

8 个进程均首次执行检测、有效 PnP、跟踪，并保存完整合法阶段记录；全部 reap、关闭 pipes、移除 owned tmpfs。输入是第 12 轮实际 BGR SHA `3bb32201aa3bf37b603c03962a84cb53b70ceb6dcde0e3b394324553939e9422`，frame 7、曝光 410 ms、control 422 ms。等待上限为标明离线的 2 秒，不是 live 80 ms 通过；此前 live 的 41.232 ms 只是被期限截断的整包等待。

[COMPARISON.json](comparison/COMPARISON.json) 与两组 build/saved 下的原报告、stderr、逐阶段/响应与原包保持字节。BGR 仅无损 gzip；[保留清单](PRESERVATION_MANIFEST.json)同时记录压缩与原字节 SHA。ELF 未随归档发布，需要本地依赖与重新构建，旧 consumer-local 路径不是换机启动配置。

```sh
python operator_native/runtime/build_portable.py build --out artifacts/new-trace --corner-refinement contour-v3 --performance-profile first-frame-trace --prefix /path/to/openvino/runtime/cmake
python tools/diagnose_native_saved_compute.py --run-root artifacts/wsl-native-live-20261013-attempt12-postclose-rgb-audit --native-spec artifacts/new-trace/operator_source.local.json --out artifacts/new-trace-saved --storage tmpfs --phase-profile first-frame-trace
```

`request-preallocate-trace` 使用另一新目录。所有 profile 都仅是显式诊断；T03/M1 的 live 动作仍未通过。
