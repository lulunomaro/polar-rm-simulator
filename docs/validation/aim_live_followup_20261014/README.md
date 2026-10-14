# 自瞄实时链路后续检查点（2026-10-14）

本包独立保存本轮失败、修复回归、只读诊断及实际运行原件。旧 `universal_aim_20261014` 不变。原件路径在 [INDEX.tsv](INDEX.tsv)，原始与存储字节数/SHA、共享 blob 编码及逐路径排除项在 [PRESERVATION_MANIFEST.json](PRESERVATION_MANIFEST.json)。每条路径独立保留；相同原字节共用内容寻址 blob。BGR/RGB、原 NN stdout/events、源码快照和日志都按原字节保存，gzip 使用 mtime=0，解压不改内容。

最终46组、3921条原路径，原字节合计3,749,847,441 bytes，共2222个唯一 blob / 81,513,687 stored bytes；20条逐路径排除记录。最终 preservation manifest SHA为 `5b41823a9114fd597883a14168caffc5c8e5523d401d6df44c37b17200714158`。初始生成3915条路径的 receipt/验证仍作为历史保留；`append_pb_fast_audit/` 明确追加六份审计原件，旧 blob 全部原字节不变。最终 `verification03/` 两模式实际 exit0/reaped、manifest/verifier源不变，包内重建9.544s，本机3921原件逐字节比较14.464s、missing=[]。

## 实际结果及边界

- T2 正式 CLI 调度实测 `formal_live`：RTF **0.9971029121**、**107 个及时结果 / 97 个独立物理消费帧**、0 fault，全部 `live_static_chain` 检查通过，source unchanged、资源清理通过。与 `gil_live7`（lean06）、`gil_live8`（lean07）合计三次本机静态场景通过；各次使用自己的原源码/配置和实际证据。
- 此结论只适用于显式生产 CPU4、host OpenCV线程数4（本机实际版本5.0.0）、`pybase64_1_5_1`、Python switch interval 1ms、Windows authority mask `0x10`、`wsl_async_bgr_v3`、private native pixels，且额外 authority 分段诊断 timers 关闭。仍保留每步耗时/像素/权限/消费审计。没有改 80ms 相机期限、150ms SDK 窗口或 reset 门限；switch 和线程亲和性实际读回与退出恢复见正式 run 的 `HOST_SCHEDULING.json`。
- 其它 GIL/亲和性/诊断 timers 运行中的低 RTF、早停、失锁与迟结果按实际失败保存；不能直接拿不同负载或不同配置作性能因果结论。异步模式允许明确迟结果丢弃，通过只表示其及时接受/消费样本，不表示全部推理都在 80ms 内。
- PB 原首图、controlled 及 fast 首图均未实时通过。fast driver 注册 exit0，host exit2；prepare 4.0485s、reset 0.0558s、capture→public 约16.4ms，act 约30.49ms 后原80ms期限 `queue.Empty`。累计 input 2,334,917 bytes / 43 chunks 含 prepare/reset 的197 bytes / 2 chunks；act 仅部分2,334,720 bytes / 41 chunks，没有完整图像 line，`complete_requests=2` 是 prepare/reset，不能称 NN、检测、MLP 或动作通过。三个节点清理记录保留。Linux/Windows 原始时刻各自记录，不跨时钟相减。独立 `pb_fast_audit` 核验原RGB、输入/源身份和回收；重建的完整wire长度/SHA不是实际OS完整递交证明，STOP lifetime统计不归因单帧。
- 通用 WSL 两项无害 nested-session / leader-exit 实测只证明进程所有权与回收，不计为自瞄、ROS算法或物理闭环。缓存方案只读反例 `cache_review_unimplemented` 未实施；离线 JSON 序列化测量 `json_saved_input_only` 不计实时性能。
- QA01 因新增原 `test_native_timing.py` 未声明来源归属失败，原日志保留；amendment04 明确 old/new SHA 与原因，原 EXTRACTION 未改。QA02 四步骤实际 exit0，`source_unchanged_during_checks=true`，**1745 passed / 40 explicit skips / 1008 subtests / 6 warnings**。这些质量检查不签收 M0–M5，不把 skip 计为通过。
- 本包、主文档 prose/LF 更新均是 QA02 后的证据/文档增补，不能称整个最终仓库所有文件等于 QA02 的文件表。执行程序字节保持原 QA SHA；主文档 before/after 和 Git LF 转换原件在 `postqa_docs_only`。

尚未资格化：完整比赛、多场景定位/射击准确率、可见 Qt GUI 的这次实时运行、C板/电机硬件 HIL、Tongji/PB 完整实时自瞄、不同机器无准备即可运行。旧导航 seq67 timeout 原因仍开放；本包不以 T2 静态通过关闭它。

## 修复证据与缺失记录

`consume_before/after1/after2` 保存消费边界 fresh sampling、精确80ms拒绝和 receipt 元数据脱离的失败/通过回归；不把注入时钟单元测试当真实物理时效证明。`losttarget` 保存全 null 方向三元组、安全无目标语义、过期与取消相关原失败/通过。gil1ms01 当时被拒绝 stdout 未保存，不能称本轮追回该原件；fixed02 的83个实际 stdout 中7个失锁全 null 三元组是后续真实 NN 原件，独立 before/after 三项失败复现属于单元证据。

`stop_before/after` 是 Linux本地5ms最佳努力STOP轮询计划（文件调用/调度耗时无硬实时保证）与有界标量 IO 计量修复；内存 stop 即时检查、spawn前强制身份检查和原清理预算保留。实际两项 harmless proof 原目录由 followup RESULT 指定，未拿上一轮 fixture 代替。`scheduling_before/after` 保存正式 helper/入口修复及94项 focused/13 subtests、真实无害 Windows 线程 mask/group 读回与恢复；这项测试不运行 NN/物理。

admission grant 和原 SDK_EVENTS 作为凭据面排除，逐路径原因列入 manifest；这不表示 SDK 没运行，RESULT、authority ledger 与消费记录仍保留其授权/执行证据。模型、ELF、依赖/克隆源码与构建对象不打包，已有原 spec/build/model/config/SHA 引用按实际可用原件保存；本包不会代替本机重建。公开 launcher 凭据语义标签和公开 `synthetic-token` 测试常量仅按精确文件 SHA/键/值白名单通过；其它凭据值不放行。

生成器首次预检的编码/公开常量误报原驱动记录逐字节保存在 `archive_driver/`（并有 ignored 原件），不改任何输入日志。初次包 verifier 因生成 INDEX 使用 Windows CRLF 而失败，原 INDEX/recipe/失败 stdout/stderr 在 `verification/`；仅新 INDEX 元数据规范为显式 LF，原 payload blob 和 preservation manifest 完全不变。后续独立验证记录另存，不改首失败。

## 复现和验证

实际命令原件在 `formal_driver` 的 COMMAND。新机器先按公开脚本构建、选择身份匹配的 CPU4 Linux spec，准备固定客户端补丁、WSL/渲染及可选 codec。不得改旧 spec hash 或自动换模型。运行参数为：

```powershell
.venv-sim/Scripts/python.exe tools/smoke_wsl_native_live.py --run `
  --linux-native-spec <本机已核验CPU4-spec> --client-root <本机固定补丁客户端> `
  --out <全新输出目录> --native-transport wsl_async_bgr_v3 `
  --private-native-pixels --raw-base64-codec pybase64_1_5_1 `
  --host-opencv-threads 4 --host-python-switch-interval-ms 1 `
  --authority-affinity-mask 0x10 --seconds 10
```

`--profile-authority` 默认关闭。CPU mask 必须在本机当前 Windows CPU group 可用；失败明确拒绝，不自动选另一个核。调度默认不设置，只作用于当前拥有进程/authority线程，不改 OS timer/power/priority 或 Linux模型线程。

包内重建验证（克隆后不要求 ignored artifacts）：

```powershell
python docs/validation/aim_live_followup_20261014/verify_archive.py
```

本机全部原件逐字节比较：

```powershell
python docs/validation/aim_live_followup_20261014/verify_archive.py --check-originals --repo-root <本机仓库根>
```

两个模式分别核验，保留实际 command/stdout/stderr/process result；默认包内 SHA/解压检查不冒称原工作区比对。`FILES.json` 最终记录包中实际文件库存，排除 FILES 自身以避免递归。这里只解压/核验原件，不启动模型、ROS、WSL、GL 或物理。
