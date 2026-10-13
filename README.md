# Polar RM Simulator

独立的 RoboMaster MuJoCo 仿真源码仓库。物理世界、相机、裁判子集、SIM v2 协议和测试在这里维护；Qt 操作客户端继续留在 [polar-upper-computer-control](https://github.com/lulunomaro/polar-upper-computer-control)。

## 这次拆分

从 [llm-RM-navigation 固定提交 7663ae7](https://github.com/lulunomaro/llm-RM-navigation/tree/7663ae744d69b27813abaefeaa9ae3e73be46a9f/simulation/mujoco_match) 提取 `simulation/mujoco_match` 到本仓库根目录。

- 这是精选公开源码快照，不是整个子目录或完整 Git 历史迁移。原仓库、分支与历史提交不变。
- 精选 190 个源文件按远端 Git blob SHA-1 校验并保留原字节；仿真与算法实现不变。另有 1 个仅保留原始 rule_decide 函数的文本测试夹具，函数正文逐字不变。
- 首次源码拆分不复制历史运行日志、内部审阅记录、私人场景初值或模型/二进制；随后补入的原版检测模型单独记录于 [models/](models/)。首次拆分的路径和校验值见 [EXTRACTION_MANIFEST.json](EXTRACTION_MANIFEST.json)，排除边界见 [PUBLICATION_SCOPE.md](PUBLICATION_SCOPE.md)。原完整历史继续留在来源仓库。
- 自有实现按 [MIT License](LICENSE) 开源；第三方归属与适用范围见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。依赖和外部资产不因本仓库许可证自动改变授权。

## 三个入口

1. **手动 SIM v2**：`python -m rm_match.platform_v2 --camera --port 8766 --camera-total-fps 2`。客户端显式连接 `http://127.0.0.1:8766`，选车后 F2 claim、再 F2 arm，F12 release。仅限本机回环，不需要 native 自瞄资产。
2. **OFFLINE/native SIL**：已有客户端监督启动器的 `--mode offline`。原版检测模型已补入 [models/shenzhen-0526.onnx](models/shenzhen-0526.onnx)；仍需独立提供且哈希匹配的 Linux native 二进制、配置和场景初始化 JSON。范围仍为固定单车、静止、不开火的 24 次曝光场景；Qt 为观察入口。
3. **历史 timing-v5 全场记录**：`rm_match.opening_runner --mode match --aim rmcs-stop`，使用另外冻结的 timing-v4 actor 身份。准确入口与限制见 [MATCH_TIMING_V5.md](docs/MATCH_TIMING_V5.md)。

三者不能互换验收结论。历史 `launch_match_windows.bat` 是旧自动对局 viewer，不是当前手动 SIM v2。

## 独立目录怎么用

本仓库根目录直接包含 `rm_match/`、`tools/`、`tests/` 和依赖文件。旧文档中的 `NAV_ROOT` 或 `simulation/mujoco_match` 工作目录，现在对应本仓库根目录；不要再额外拼接子目录。

在自己的仿真 Python 环境安装 `requirements-camera.txt`；Qt 客户端使用独立环境和 `requirements-core.txt`。现有客户端启动器的参数名仍是 `--nav-root`，将它设为本仓库根目录即可。保留虚拟环境 Python 的原调用路径。完整命令见 [独立仓库指南](docs/STANDALONE_REPOSITORY.md)。

本仓库已包含历史 RMCS 检测模型 `models/shenzhen-0526.onnx`（4,359,932 字节），SHA-256 为 `b53470b42a5778aca8f3382ebe3c623482599cbf8ebad2e9a0dcc0c7f42c9255`。模型字节与固定上游及历史身份记录一致；原始 MIT 声明、输入输出接口和权利范围说明见 [模型来源与限制](models/README.md)。本次只做字节与来源核验，没有运行模型推理或物理仿真，不能据此认定 native 流程已就绪。

本仓库已补入 [operator_native/runtime/](operator_native/runtime/README_PORTABLE.md) 的 RMCS T2 原生源码与可移植构建入口：94 个恢复文件保持原字节，来源是 `079a7fe + T2 tracker`，不是历史 `40f7` 全场基线。外部 C++ 依赖仍需本机准备，源码存在不等于 native 运行已验收。最小步骤、依赖和当前验证边界见 [原生构建指南](docs/NATIVE_RUNTIME.md)。

本仓库仍不包含 native 二进制、外部 native 依赖库、策略权重、私有场景初值、真实轮腿 CAD/RL 资产或 Python 解释器。不要把示例配置当成可运行 native 配置。native 路径仅有 Linux ELF64/x86-64 源码约束；Windows 桌面、跨设备 LAN、完整官方规则与真实硬件动力学均未完成验证。实时 camera/native 路径也未达到原定壁钟验收标准。

## 不启动物理的拆分检查

```sh
python tools/verify_standalone.py
python tools/check_standalone_contracts.py
```

第一条使用标准库验证所列公开源文件、Python 语法、JSON 与 XML。第二条运行选定的合成合约及回环 HTTP 单测，需要现有 NumPy。不会启动 MuJoCo、渲染、native actor、付费 API 或硬件，也不会触发 CI。

本次结果与未执行项见 [EXTRACTION_VALIDATION.json](EXTRACTION_VALIDATION.json)。公开初版不携带历史对局/native 运行结果，也没有重新运行物理或 native 基准。轻量检查不代表全量 pytest 或完整物理验收通过。
