# Polar RM Simulator

独立的 RoboMaster MuJoCo 仿真仓库。默认部署组合是**本仓库 + 自己的 [Polar RM Client](https://github.com/lulunomaro/polar-rm-client) + 自己的 RMCS T2 源码**，无需克隆历史导航仓库。客户端保持独立组件，不复制进仿真源码。

## 换一台电脑，从这里开始

当前 native 部署目标是 **Linux x86-64**。先看 [部署指南](docs/DEPLOYMENT.md)，再运行默认的无副作用计划：

```sh
python3 tools/deploy.py plan
```

完整路径是：获取固定客户端 → 建立独立 Python 环境 → 构建自有 RMCS → doctor 检查 → 显式启动。

```sh
# 下载固定版本客户端到 external/polar-rm-client；不安装依赖、不启动程序
python3 tools/deploy.py setup-client --run
# 依赖准备与 native 构建见部署指南，然后：
python3 tools/deploy.py doctor --sim-python .venv-sim/bin/python --client-python .venv-client/bin/python
python3 tools/deploy.py launch --sim-python .venv-sim/bin/python --client-python .venv-client/bin/python --run
```

默认 profile `own-rmcs-t2-v1` 只注册自有 T2 native 自瞄。它核对 T2 源码身份、模型、构建记录、二进制和配置哈希；缺少或不匹配就报错，不会换成像素识别、旧 `40f7` 或测试算法。窗口内仍需明确选择红哨兵和 native 自瞄，再 claim/arm；启动不会抢占车辆或自动开火。

**部署入口已整理，不代表整场对局已跑通。** 当前 native adapter 仍仅支持静止 `red_sentry`，开火保持人工独立控制。相机/native 实时路径尚未通过既定壁钟验收；不放宽时间窗来掩盖这一点。完整自动对局、多车 native、移动自瞄、Windows native、跨机 LAN、真实硬件与完整官方规则均未完成验证。

## 仓库包含什么

- MuJoCo 世界、相机、裁判子集、SIM v2 服务、Python SDK 与测试
- 自有 RMCS `079a7fe + T2 tracker` 源码和 portable 构建入口：`operator_native/runtime/`；不冒充旧 `40f7` 或未修改上游
- `models/shenzhen-0526.onnx`；模型来源与授权见模型旁的说明和 [第三方声明](THIRD_PARTY_NOTICES.md)
- 不包含已编译 native 二进制、系统依赖、Python 解释器、私人场景/标定或真实轮腿 CAD/RL 资产

native 源码、模型存在，编译成功和闭环运行是不同层级。已完成一次 Linux 干净构建及五项有限软件协议检查，见 [构建验证](docs/NATIVE_BUILD_VALIDATION.json)。当前主机的真实 MuJoCo/相机/live 测试未通过闭环条件，见 [部署验证](docs/DEPLOYMENT_VALIDATION.md)。构建细节见 [Native RMCS](docs/NATIVE_RUNTIME.md)。

## 接入自己的算法或客户端

- 导航、自瞄：本地 JSONL 子进程接口，输入仅自己的传感器观测，输出明确的速度或云台目标；[接口与可运行示例](docs/CUSTOM_INTERFACES.md)
- 其他客户端：同机 `http://127.0.0.1:8766` 的 SIM v2 HTTP/JSON 协议；无需使用 Qt
- 当前固定 Qt 客户端认识 native RMCS ID。新自定义 ID 可通过 SDK/自定义客户端绑定；尚未宣称 Qt 已支持任意插件配置界面

## 历史与诊断入口

手动 SIM v2、固定单车静止不开火的 24 次曝光 OFFLINE SIL、旧 timing-v5 全场记录保留供明确选择。它们不是默认部署路径，验收结论不能互换。旧 Windows `.bat` 也不代表当前 native 部署经过 Windows 验证。见 [历史独立仓库指南](docs/STANDALONE_REPOSITORY.md) 与 [timing-v5](docs/MATCH_TIMING_V5.md)。

## 轻量验证与来源

```sh
python tools/verify_standalone.py
python tools/check_standalone_contracts.py
python -m unittest discover -s tests -p test_deployment.py -v
```

初始提取的 190 个源文件和一个精确函数夹具记录在历史清单；后续有明确任务归属的改动记录在 [DEVELOPMENT_CHANGES.json](DEVELOPMENT_CHANGES.json)，验证工具分别核对未改原字节和已登记的新字节，不覆盖历史身份。提取来源为 [7663ae7](https://github.com/lulunomaro/llm-RM-navigation/tree/7663ae744d69b27813abaefeaa9ae3e73be46a9f/simulation/mujoco_match)，详情见 [EXTRACTION_MANIFEST.json](EXTRACTION_MANIFEST.json)、[SOURCE_PROVENANCE.md](SOURCE_PROVENANCE.md)、[部署变更验证](docs/DEPLOYMENT_VALIDATION.md)。这些轻量检查不运行 MuJoCo 物理、渲染或 native 推理，不等于全量测试或完整对局通过。

自有实现按 [MIT](LICENSE) 开源；保留所有第三方许可。外部依赖和第三方资产的授权不会被本仓库许可证覆盖。

新增 [OFFLINE24 复现工具与记录](docs/OFFLINE_DEPLOYMENT_VALIDATION.md)：本次原客户端离屏会话解码了 24 帧，触发 13 次自有 native 推理；PnP 接受位姿和进入物理的有效云台命令均为 0，静态跟踪/控制链仍未通过。这不代表默认实时路径、完整对局或换机部署通过。保留失败结果、原始合成画面、单帧角点/PnP 诊断与独立复现入口，见 [单帧诊断](docs/validation/pnp_saved_frame_20261013/README.md)。

## 按项目计划继续开发

[实施进度](docs/IMPLEMENTATION_PROGRESS.md) 记录 T01–T03 的当前代码、实测、失败和下一步。
[RobotIO 工作稿](docs/ROBOT_IO_V1.md) 与 [验收追踪表](docs/ACCEPTANCE_TRACEABILITY.md) 映射现有协议与缺口；验收配置仍为 draft，未确认条件不记为通过。
本地统一质量入口（每次使用新输出目录）：

```sh
python tools/check_project.py --out artifacts/quality-001
# 可选额外运行实际相机/HTTP检查；不含 native 闭环或完整比赛：
python tools/check_project.py --out artifacts/quality-camera-001 --camera
```


## 当前计划实施

新构建默认使用修复后的自有 T2 + contour-v3；独立渲染正/负例与24帧完整静态离线链已通过。
实际 Qt、服务端 role/robot/audit 准入与故障清理有单独证据；实时 native、完整3v3/7v7和Windows
native尚未验收。各阶段及失败记录见 [实现进度](docs/IMPLEMENTATION_PROGRESS.md) 与
[最终静态链](docs/validation/pnp_contour_v3_aftercleanup_chain_20261013/README.md)。
