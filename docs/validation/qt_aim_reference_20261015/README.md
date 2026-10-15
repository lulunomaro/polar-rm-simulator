# 第六 Qt 客户端、自瞄 v2 与显式部署选择

本轮完成严格 aim v2 的客户端选择/原授权绑定和部署版本配对。v2 是自瞄协议版本，客户端仍使用 Qt 6。
真实 Qt 回归使用合成 SDK/图像夹具，不能证明真实算法实时闭环、移动命中、可见桌面或完整 3v3。
本轮没有重跑 NN，没有放宽图像 80 ms 或控制窗口 150 ms，M0–M5 未完整签收。

父提交 `aa0991aa23a8622f005c007f932b7305fd30e687`，开发分支 `work/plan-t01-t03`。
用户指定父目录 PROJECT_PLAN.md SHA-256 为
`299b58e785778ae143ff86808f333d2c6ff4e470a00d4dd9138ee1c7380a21fd`。

## 实际结果与范围

| 检查 | 实际结果 | 范围 |
| --- | --- | --- |
| 原 Qt 专项 | 56 passed / 64 subtests / 0 skip | 严格 v1/v2 解析、传感器/身份负例与原选择/claim/HUD/arm/空config绑定，合成 SDK/图像 |
| 原 Qt 继承平台32模块 | 513 passed / 395 subtests / 0 skip，42.900717s，exit0/reaped | 256客户端源前后相同，真实 offscreen Qt；不是可见桌面、真实HTTP到物理或NN |
| 完整项目质量四阶段 | 3332 passed / 45 skipped / 6 warnings / 1024 subtests | 计划配置、来源、接口静态、单位/合成/物理测试；不替比赛验收 |
| 质量执行身份 | pytest227.07s，driver329.413784s，exit0/reaped | 484程序/测试/补丁输入前后逐SHA相同 |
| 第六补丁安装/还原 | 固定BASE上33文件apply、逐SHA、reverse与raw-clean通过 | 原五份patch/MF及138个旧checkout成员原字节不变 |
| 独立实际客户端检查 | check_client exit0/reaped，2.592044s，33文件 | 真实inspect_client/Git路径；独立审查未重跑Qt/NN/GL/物理 |
| 真实dry CLI | deploy、co-op、native diagnostic三次exit0 | 同一第六root/manifest/hash；没有启动算法或客户端 |
| active-v1性能诊断 | 四次ABBA加独立profile，五进程exit0/reaped | 实际六车MuJoCo、合成相机/方向策略、真实绑定/消费；无GL/NN/HTTP/SDK |

第六完整补丁以原客户端 `0cedf99b70b1beec99865b9980af6789e6c53d99` 为基线，包含第五版全部改动。
相对第五仅变更适配器解析器并增加两个测试模块。它严格匹配完整类型化 capabilities.v2、
camera_gimbal_v2/version2.0.0、camera+odometry、本地注册/真实prepare/reset协商声明和原source-base惯性yaw参考。
未知/混搭/额外能力、错误参考和未协商的旧ROS v2保持不可选；原v1和权限/时限语义保留。

- [第六manifest](../../../client_patches/CLIENT_AIM_REFERENCE_PATCH_MANIFEST.json) SHA-256：`f3d83e4d4584c7910958fda19f46dc310a310b8fb89376ebf5229a31b69bdf30`
- [完整补丁](../../../client_patches/robotio_aim_reference_v2.patch) SHA-256：`d7b3b828e3217f5fab460646f6ba2bf4c839a406e36a183756031596ce8e61c5`

## 失败与性能解释

第一次完整Qt调用因清理PYTHONPATH后旧夹具无法导入父仓rm_match而有3个collection错误；保留原pytest-all。
只修运行环境后另存pytest-all02，客户端源码未为该失败更改。首roundtrip在checkout/apply/reverse混用
Git CRLF配置，实际forward和33源检查成功，raw-clean断言失败；保存原命令、dirty输出和复现脚本。
后续逐调用匹配LF配置获得完整干净往返，原mixed-CRLF review按匹配配置通过只读reverse-check；没有改全局Git设置。

active-v1对照中，actor-active目标路径p50均值parent/current为18.75/21.00微秒；
1000步均值4.269783/4.348828ms，样本波动约9–10%，不能用它解释或否认真实链退化。
该诊断使用公开base64/JPEG路径，与T2私有像素路径不同。独立profile不混入吞吐对照，累计耗时不可相加。
某次终点已安全失活，最终ctrl为机械hold；不宣称每次终点均消费合成角度。
原RESULT末尾误写idle的范围说明按原字节保留，实际2770–2831次active phase及REVIEW纠正该描述。

已有native01/02/03的render p50为16.04/16.65/18.27ms，host输入ACK延迟p50为19.62/20.79/20.51ms；
这些是不同时期源码的已存运行，不能作为受控性能因果对照。没有thread-CPU或GIL等待证据。
下一步先复用profile-authority并补同源、有界队列/写入wall与thread-CPU内存采样，停止后落盘。
旧实际T2实时三次失败、最新RTF0.821310保持原分类，见[上一检查点](../aim_reference_20261015/README.md)。

## 复现与归档

从固定原BASE的全新干净client checkout安装完整第六补丁，不能叠加或重置已有修改。
以下从仿真仓根目录执行，省略run的命令仅生成计划：

```powershell
.venv-sim/Scripts/python.exe tools/apply_client_patch.py --client-root external/polar-rm-client-aim-reference-review --manifest client_patches/CLIENT_AIM_REFERENCE_PATCH_MANIFEST.json --run
.venv-sim/Scripts/python.exe tools/deploy.py plan --client-root external/polar-rm-client-aim-reference-review --client-patch-manifest client_patches/CLIENT_AIM_REFERENCE_PATCH_MANIFEST.json
.venv-sim/Scripts/python.exe -m rm_match.deployment.coop_launcher --config examples/coop_aim_reference_manual.json
.venv-sim/Scripts/python.exe tools/check_project.py --out artifacts/YOUR_FRESH_QUALITY_DIRECTORY
```

本轮完整质量调用另显式设置POLAR_TEST_WSL=1与本机已核验POLAR_WSL_TEST_SPEC；该local spec、模型与ELF不随仓库发布。
实际全部argv、环境、32个Qt模块列表、诊断driver及source roster在records中；重跑须使用新输出目录。
Qt调用的QT_QPA_PLATFORM=offscreen、PYTHONPATH为父仿真仓；没有启动硬件。
Linux setup-client/doctor/launch也必须使用同一显式client-patch-manifest与client-root；省略manifest仍为原第一版。

[MANIFEST.json](MANIFEST.json) 将原路径映射到 [records.tar.gz](records.tar.gz) 中按内容SHA命名的payload。
951条记录、864份唯一payload，归档4,220,278 bytes，SHA-256为
`5b363afd5a0353232b500b4973f832c19d5f0ce3da5ea7e47ad57db58b657654`，已逐payload顺序解压核验。
首次归档后独立审查修正了两份报告中的测试hash沿革说明，程序、补丁和实际结果均未变；
原报告原样保留，最终文字及前后SHA单独保存于[SUPPLEMENT.json](SUPPLEMENT.json)和[review-final.tar.gz](review-final.tar.gz)。
客户端256源字节是在测试后按测试前/后相同SHA复核补存，未伪称运行前已复制；质量driver的源在运行前直接复制。
不含模型、ELF、Git clone、admission或SDK明文凭证。本README、进度结果段及归档在最终质量检查后补写。
[FILES.json](FILES.json) 固定本包各文件的大小与SHA，不自引用。
