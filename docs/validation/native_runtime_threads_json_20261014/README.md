# Native runtime thread properties 与通用 JSON 进程收尾证据

本包独立保存 2026-10-14 的原始构建、compiled-model 属性/零 tick 检查、stdout 观测、八个离线 OpenCV 环境对照、通用 JSON owned-process 修复和最终统一 QA。它不覆盖旧包，不把机械微诊断、模型启动累计 CPU、离线响应或通用进程修复写成 live80 或哨兵生产导航重新验证。

`PRESERVATION_MANIFEST.json` 和 `INDEX.tsv` 每条列出原路径、原字节 SHA/大小、短文件名和存储 SHA/大小。较大新 payload 使用 gzip mtime=0；已经压缩的原件、混合 UTF16/UTF8 的日志、失败/errata 和 STOP 身份原件均保持原字节。构建分组名是 `bld`，避免 `build` 被 Git 忽略。ELF、模型权重、objects、venv、依赖和缓存不发布；原 C++/Python 配置与构建元数据可保存。私有凭据值严格拒绝，不重编码或删改原日志绕过边界。

## 证据组及资格

| 分组 | 保存的原件 | 可以支持的范围 |
|---|---|---|
| bld / blddrv | compiled-properties trace build 与实际独立构建 driver | 固定生成源码、原配置/模式/spec/build manifest、语法/构建日志及退出过程；不是原 ELF 字节等价或实时资格 |
| zero / zerodrv / propf | 零 tick 属性 probe、driver 和 properties 专测 | 实际编译后的模型/执行设备属性与原控制前准备；零输入、零推理，不冒称改变运行线程已经有效 |
| stdout / firstread | stdout telemetry before/after、纯专测及首请求只读报告 | Supervisor 实际观察和严格截止保护；0 read bytes 不证明 ELF 没写，旧 actual3 缺字段仍 unknown |
| cvf / cv8 / cvdrv / cvreview | 对照专测、八个真实离线 fresh case、driver 与 agent 只读报告 | 只读实际属性与环境是否生效；未生效 cv1 严格拒绝、0 NN，default 四份离线回复不称 live80 |
| jsonbefore / json1 / json2 | 通用 JSON owned-tree before、第一修复/errata、最终 after02 | 原资源缺口、故障与修复/测试源码分别保留；不删除首错、不把 generic 资源修复当自家哨兵 production 再测 |
| linux1 / linux2 / pipe | 实际 Linux 前后检查及实际无害 pipe 检查 | 原来源与源换行规范化后的独立结果，29 项 pipe 检查保留各自 scope；不是 NN、ROS 或比赛闭环 |
| qa / qadrv | 冻结完整 QA 和实际 driver | 四阶段 exit0、源码在检查中不变；1324 passed / 35 明确 skip / 930 subtests / 6 已有 warnings，原 pytest 108.77s，driver 128.635s 且已回收 |
| refs | 源码、测试及 runtime-source-line-ending 原记录 | CRLF→LF 的 before/after SHA 和实际 normalized Linux 来源；不给原测试日志赋最终新源身份 |

cv1 请求与实际 applied 属性严格分开。未生效请求提前终止，不靠默认行为产生推理后再声称线程设置成功。default 回复来自保存图像的独立离线进程，既没有 live 80 ms 原 authority 的动作消费，也不能把两个未配对样本相减称纯 NN 性能收益。compiled-model 实际属性日志与 requested 配置分开，NN/进程 lifetime CPU 分开。

stdout 新字段只记录每事务累计读取字节、可读观察数、stdin 完成后的 Linux 本地相对时间、retained buffer 长度及最多 4 KiB 前缀 SHA，不保存原文、不在原 deadline 后读取或接受结果、不放宽 80/150 ms。首请求旧档的 47.378868 ms 是完整 stdin 之后到失败的截断等待，包含输入/计算/输出/调度，不能称纯推理或反向补旧缺字段。

通用 JSON 资源树的原失败、首错修订、最终 after02 与 CRLF→LF 规范化记录一并保留。Windows after02 专测执行的是原 CRLF 版本；Linux02 与统一 QA 执行的是仅规范成 LF 的同逻辑版。它们的不同原字节/源码 SHA 都按各次实际记录保存，不能相互冒名。旧源码/故障记录不覆盖，也不声称它们逐字节等于新 LF 文件。

根代理 QA 后只新增/修订说明文档和此 package；本轮十二个执行程序（四项修改、八个新模块/测试）仍与确切 QA hash 相同。根代理 post-QA 证明核对 3,075 个既有 checked 文件，只有 IMPLEMENTATION_PROGRESS/WSL_NATIVE_TRANSPORT 两份文档更新说明。新 archive/verifier/README 在 QA 完成后加入，未参与此前 1324 项测试。这次只执行独立字节验证，不把归档检查称为此前 QA，也不为低影响证据文档再跑模拟/NN/ROS 或全测试。Git staging/push 证明另存 ignored artifacts，不放本包制造自引用。

## 独立核验

新 clone 无 ignored artifacts 也能只校验包内 payload、恢复后的原 SHA、INDEX 和保存工具哈希，不导入模拟器，不搜索原工作区，不启动进程：

```powershell
python docs/validation/native_runtime_threads_json_20261014/verify_archive.py --archive docs/validation/native_runtime_threads_json_20261014
```

该模式输出 `originals_checked=false`，不称作当前 ignored 原件比对。要严格核对本机每条原字节，显式选择：

```powershell
python docs/validation/native_runtime_threads_json_20261014/verify_archive.py --archive docs/validation/native_runtime_threads_json_20261014 --check-originals --repo-root .
```

原件缺失、不同、路径别名/越界或存储损坏均失败。标准库独立 verifier 不导入 archive 脚本/SDK/模拟器。验证原输出和退出过程由单独保存操作记录，不把包内哈希检查当功能测试或实时通过。

这是新的独立证据包。完整 M0–M5、实时原 native 链、移动/开火、多车比赛、LAN/新机器/Windows-native/HIL 仍需各自真实验收。以前成功的哨兵生产导航范围沿用原单独包，本轮 generic 修复没有重跑或重新签发该资格。
