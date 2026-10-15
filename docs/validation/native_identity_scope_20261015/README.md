# 静止 T2 自瞄的显式机器人身份

父提交 `209d8378da46f3cf4fbb4f4c80f669ee833c48c5`，开发分支 `work/plan-t01-t03`。
本轮消除包装层固定红方哨兵身份，增加按原字节 SHA 固定的本地 robot/team/role/referee ID scope，
并修复部署 launcher 的 doctor→启动→ready scope 替换竞态。
默认仍只允许原红哨兵；新声明不扩大 admission，不修改原 ELF、模型、标定、静止门或人工火控。
机械 helper 的曝光 `pitch_link` 转换另有纯几何回归，不充当原生移动支持。

## 实际通过范围

Windows RTX 5070 Ti Laptop MuJoCo 实际渲染，经原客户端 SDK 授权、WSL CPU4 T2 原生 ELF、
原检测/PnP/跟踪/控制输出和 MuJoCo 云台 actuator，两次**顺序单车静止**10墙钟秒实测通过。

| 原始结果 | 红步兵01 | 蓝步兵01 |
| --- | --- | --- |
| 2ms物理步 / 仿真秒 | 4945 / 9.89 | 4991 / 9.982 |
| 物理实时系数 | 0.9889068252 | 0.9981690168 |
| 原始相机帧 | 148 | 148 |
| 及时原生结果 / 独立源帧物理消费 | 135 / 135 | 124 / 121 |
| 最大消费原capture wall/sim age | 77.5396/78ms | 79.1358/78ms |
| 原生实际BGR归档文件 | 140 | 137 |
| fault / fire / 清理 | 0 / 0 / clean | 0 / 0 / clean |

显式配置为CPU4、host OpenCV4、pybase64 1.5.1、CPython switch 1ms、authority mask0x10、
六车场景/2ms、单相机1440×1080@15FPS、物理速率1.0。实读并finally恢复调度；原图像80ms/SDK150ms不变。
driver分别24.6974323/21.4255280s，exit0、reaped、各自执行源码前后不变。
Linux owned cleanup11.306/16.597ms、host runtime共享收尾76.937/88.666ms，原1.3/1.5s预算未改。
pending、late/discard、关闭时取消单列，没有计成及时推理或机械消费。

独立复核277个实际BGR及反通道RGB SHA、259条及时结果的原字段/类型、原capture身份、
授权窗口与实际消费，并区分Linux本地时钟与Windows QPC。host只添加原episode及由tracking导出的should_control。
原native stdin的team/referee没有独立echo记录；这里只以scope、严格输入匹配和执行源码证明构造路径。
没有移动、两车同时自瞄、精度/命中、实体弹丸、可见Qt、完整3v3/7v7、两机LAN、发布或HIL资格。
原默认profile和其他队伍自瞄也未因这两个静态样本自动获得实时资格。

scope示例原SHA为 `26428d8a33a9cff19f471f23ae21c53787c347e52de5f3309462634da7ff03f7`。
原CPU4 ELF为 `67819b6812c2c4a87e2b411eed49c1e01cfb67212efdd2f2e0abd2aa3a963dec`；
原ONNX为 `b53470b42a5778aca8f3382ebe3c623482599cbf8ebad2e9a0dcc0c7f42c9255`。
本轮没有重新构建或替换这些二进制。

## 回归、失败与保存范围

QA03四步骤通过：3123pass、45明确skip、1024subtests、6既有collection warnings。
pytest165.15s；driver219.2396239s、exit0/reaped。
466个程序/测试/来源输入、17846个Git已知检查输入在检查期间前后不变。
QA01缺helper变更归属说明，未进入pytest；QA02为3个旧夹具/可选参数断言失败（3120pass/45skip）。
修正明确初始化scope的测试夹具及新增参数断言后通过，没有给生产路径加默认回退或放宽校验。
独立review01错误比较原native与host附加字段、bootstrap与owned run ID；原文件保留，
review02严格逐原字段及正确身份链复核通过，没有修改原始运行结果。

两次live后另外修复launcher scope pin并更新一个绕过构造的测试夹具，未改两次实测所用的native执行链。
各阶段真实源码快照分别保留，未把后续字节回填旧结果；进度/兼容文档的结果说明在QA03结束后补写。

[PRESERVATION_MANIFEST.json](PRESERVATION_MANIFEST.json) 将2434个原文件记录映射到
[records.tar.gz](records.tar.gz) 的553个去重原字节payload，逐文件SHA/长度和tar内容已复核。
archive SHA：`fe704c4d59324b46e3d8d9efa4606f1686858ddd2e67ee2dbd504717658b5eee`。
归档含执行源码、原结果/账本/时限/清理/图像哈希、QA各次失败与最终日志、独立审查及下一步移动设计。
Git内另保留每色一个实际BGR样本；全部277个原图在本机artifacts中，另外275个未打包入Git。
不包含admission、SDK_EVENTS、clear credential、ELF/动态库、ONNX/模型或第三方完整checkout。
元数据中的本机路径是原运行记录；可按manifest读取archive_member并复算sha256，不应假设路径在另一台电脑存在。

本机完整原始目录：

- `artifacts/aim-live-native-scope-20261015-{red_infantry,blue_infantry}-01`
- `artifacts/native-scope-driver-20261015-{red_infantry-01,blue_infantry-01,quality-01,quality-02,quality-03}`
- `artifacts/quality-native-scope-20261015-{01,02,03}`
- `artifacts/native-scope-independent-review-20261015-{01,02}`
- `artifacts/native-moving-design-20261015-01`：只读设计，不是移动实现或测试通过。

## 本机复现

先按[原生构建记录](../native_runtime_threads_json_20261014/README.md)准备实际CPU4 spec、模型与原客户端。
这些本机依赖未随证据包携带。使用新输出目录，重复原窗口与参数：

```powershell
.venv-sim/Scripts/python.exe -X utf8 tools/smoke_wsl_native_live.py --run --native-transport wsl_async_bgr_v3 --private-native-pixels --linux-native-spec artifacts/native-production-cpu4-build-20261014/operator_source.local.json --client-root external/polar-rm-client-state-review --out artifacts/aim-scope-local-red01 --host-opencv-threads 4 --raw-base64-codec pybase64_1_5_1 --host-python-switch-interval-ms 1 --authority-affinity-mask 0x10 --seconds 10 --native-robot-scope examples/native_robot_scope.json --robot-id red_infantry
```

蓝方改 `--robot-id blue_infantry` 并选择另一个新输出目录。普通服务入口、独立admission和限制见
[兼容说明](../../AIM_PLUGIN_COMPATIBILITY.md)。两次独立运行不能作为多实例并行或移动闭环通过。
