# 控制期限诊断、静态链恢复与服务器显示选项

父提交de37da74c3f47c70f18f9afb0db9e2ea2243eec5，分支work/plan-t01-t03。本轮未调用子代理。
此前0.897/0.594秒binding_mismatch早停与更早的实时退化证据保持，不覆盖原失败。
当前恢复的是固定公开场景下单车静止T2的10秒局部链，M0–M5仍未签收。

四组真实5秒手控对照使用实际六车2ms MuJoCo、核心SDK、原150ms窗口、固定本车小角度云台、零开火，
无adapter/NN/Qt：相机off/on/on/off的RTF为0.999897/0.999918/0.999917/0.999889，均无SDK错误、clean。
on使用实际NVIDIA GL、原相机尺寸与15fps上限。该对照只有手控/时延意义，不替真实自瞄或像素反查。

| 真实10秒原T2静态入口 | 01额外控制诊断包装 | 02无额外包装 | 03无额外包装 |
| --- | --- | --- | --- |
| 程序输入 | 父程序集，额外wrapper另存 | 最终程序集 | 同02 |
| 显示间隔 | 显式20ms | 显式20ms | 原默认0/每步 |
| physics RTF | 0.999917397 | 0.999974701 | 0.999184862 |
| raw/及时native/独立帧执行 | 148/134/130 | 148/126/115 | 147/133/117 |
| physics步/显示发布/延后 | 5000/544/4456 | 5000/544/4456 | 4996/4996/0 |
| 最大执行wall age ms | 79.2323 | 79.8317 | 79.6065 |
| 最大执行sim age ms | 约80，按原记录<= | 约80，按原记录<= | 约80，按原记录<= |
| 原像素反查/请求归账/清理 | 通过/通过/clean | 通过/通过/clean | 通过/通过/clean |
| SDK/runtime错误/开火 | 无/0 | 无/0 | 无/0 |
| 原判定/范围 | 局部PASS，额外诊断开销 | 静态局部PASS | 静态局部PASS |

原CPU4 ELF 67819b6812c2c4a87e2b411eed49c1e01cfb67212efdd2f2e0abd2aa3a963dec、
ONNX b53470b42a5778aca8f3382ebe3c623482599cbf8ebad2e9a0dcc0c7f42c9255保持。
均原CV4、CPython1ms、mask0x10、2ms/六车、1440×1080/15fps上限、latest_pending、静止red_infantry显式scope。
模型readiness前0相机/0推理/0物理，从首曝光计数，保持原80/150ms与0.98 RTF门限；不提供敌方真值或代打算法。
仅核对第六Qt客户端的固定源码/补丁和使用其SDK，未打开可见Qt，不继承旧五版客户端身份。

01仅以额外wrapper记录原SDK调用起止及有限数回复字段，并在原_clear_binding调用前记录caller与原期限。
不记录body/header/token，不改任何授权、帧、输出或期限；wrapper原字节与SHA另存，不能只凭原代码文件清单称为无包装。
165个激活ACK的剩余原期限最小111.1571ms；唯一binding清除位于结束阶段_clear_lease，激活尚未过期，
本次没有复现原期限撤权。02/03没有这些额外SDK/清除包装，也没有可选phase/authority计时。

Windows报告本轮16:03:30启动，上一提交记录15:32:35。两轮之间重启是环境变化，不能证明重启是根因，
也不能将恢复归因于显示分频：本轮每步显示同样通过。启动/提交时间只作环境背景，合格依据是本轮原帧、
原deadline、真实native结果与物理执行；不以旧时间戳、旧算法、真值或历史通过替代当前验收。
有样本接近80ms，无长期稳定性保证；移动目标、移动本车、重捕获、射击、导航比赛树、完整3v3及两机LAN尚未验收。

实际服务器现可在原启动命令追加`--telemetry-publish-interval-ms 20`。范围0..100ms有限数，默认0不变，
启动JSON给出`telemetry_publish_interval_s`；无效值在读取admission/加载模型前拒绝。
此参数只控制历史显示缓存整理，原物理/相机/guard/trace每步执行、延后缓存保留原sample/receipt时间、最终停止重新采样。
暂停/裁判HUD按显示周期更新，物理安全门逐步执行。它不配置场景距离/FOV，不保证默认任意场景模型都能检测。

新增9项CLI生命周期/无效参数回归，初步84pass/10subtests；最终程序集专项465pass/98subtests、2既有warnings，
driver10.6809109秒/exit0/reaped，495程序输入前后相同。

最终QA01四阶段退出0：3431pass/45skip/6既有warnings/1024subtests；pytest152.54秒，driver211.9689139秒/exit0/reaped。
495个程序/测试/补丁输入和17899项Git已知输入前后逐SHA相同；native02/03使用同一最终程序集，01额外诊断包装/父源另存。
QA后仅补记结果文档、进度表与新永久归档/索引；执行程序与DEVELOPMENT保持原已检验字节。
不声称这些最后的文档/归档增补参加此前QA，冻结期间三份文档原字节亦已归档。

复现专项：

```powershell
.venv-sim/Scripts/python.exe -m pytest -q tests/test_telemetry_cli.py tests/test_telemetry_cadence.py
.venv-sim/Scripts/python.exe -m rm_match.platform_v2 --help
```

各次实际argv、原源字节、额外包装、原输出与完整像素反查记录随归档保存；本地ELF/模型/私有spec与SDK/admission账本不公开。
新配置不改变通用RobotIO协议、控制权或任何队伍算法实现；未据此关闭完整平台/发布验收。

永久包3100条原路径记录、609份唯一payload，4,186,464字节。
[MANIFEST.json](MANIFEST.json)对应原路径/SHA与[records.tar.gz](records.tar.gz)内容寻址payload，逐项解压核验。
419份完整实际BGR与全量像素核验留本地，Git保留3份真实BGR样本。
13项私有admission/SDK/owner账本仅以路径/SHA列出，clear credential不公开。
records.tar.gz SHA256：`fa5358550519b96c697505ef57ffae5b96ff554207fe739701c5b6c8b931a7b0`。
[FILES.json](FILES.json)固定包内文件SHA，不自引用。
