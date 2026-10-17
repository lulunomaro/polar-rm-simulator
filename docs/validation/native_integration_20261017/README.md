# 物理积分证据与结果处置修复

2026-10-17 UTC+8，父提交030590eecbe891f4787299d3002943432140cb85，work/plan-t01-t03。

## 修复与历史边界

本轮修复实时诊断的执行帧误计：过去first actuator receipt包含仅预写入、随后在积分前撤销的帧，不能证明物理执行。上一检查点03唯一计数帧14仅有actuator记录，没有integration_entry，旧报告1帧不作为有效物理积分证据；历史文件/原判不覆盖，其他历史数量也未经此次新审计。
现仅计原integration_entry与同一步最终target/budget、实际mj_step调用时刻和本车真实ctrl/Command一致的帧；入口与实际调用都须在原80ms预算内。新增结果接收处置日志保留原collect wall sample及当时sim time，与较晚日志发布时间分开，不刷新身份/期限、不重复检查选取有利时间。
本轮同配置真实T2 10秒复验RTF0.7384549158、147 raw、103次真实完成均late_discard、及时native_result 0、预写入0、物理执行0；clean/errors[]/fire0，全部实时验收仍FAIL。35次collector late_result中5次在壁钟尚余2.20–8.48ms时仿真预算已超4–8ms，另1次wall/sim均超；这些包括pending状态，不声称是有效目标输出。未归因为单一CPU/GIL或本次日志开销，未盲目重复取最好结果。
六车2ms、真实NVIDIA1440×1080/15总fps、自有CPU4 ELF/ONNX、原red_infantry静止scope、手控对方vy.08、gravity/yawgain4和OpenCV JPEG85保持。原80ms图像、150ms控制、RTF0.98均不变。没有修改算法/模型/Command/物理，没有调用子代理/训练/硬件/整场比赛。证据见[物理积分证据修复](validation/native_integration_20261017/README.md)。

原始旧ledger本地只读诊断位于artifacts/native-consumption-diagnosis-20261017-03；脚本首次命令引号错误已纠正，未改旧记录。这是探索性普通相等join，不能当作严格跨身份验收；新代码使用递归类型和值精确比较，拒绝bool冒充epoch/frame。新物理检查仅为诊断资格，不更改执行授权。

`tools/smoke_wsl_native_live.py`保留每阶段完整计数与所有stale记录；独立保留distinct_native_prepared_frames。每个integration_entry候选在同一真实物理步结束后，核对原episode/rid/frame预算、原入口wall/sim、最终target/budget、start≤call≤post、原wall独占/sim包含截止、五个真实ctrl和backend最终Command与禁射。允许mj_step完成/日志发布较晚，但实际调用必须在原期限内。不仅将旧字段改名，旧人工计数字段也不能单独使classify通过，缺少physical_integration_evidence严格true即拒绝。

原targets与budget保持，pose/ctrl只用于本车隔离评测，绝不反馈给算法。后续另一次fire guard若撤销target，该候选不合格。仅预写入、后续撤销和实际调用过期都不累计独立执行帧。可继续记录及时native_result，但其本身不是物理执行。

`PlatformRuntime._collect`每个polled result只增加一个处置事件，覆盖binding_changed/sample_discarded/private_source_rejected/sticky_fault/adapter_error/late_result/source_invalidated_after_submit/navigation_status/aim_status/accepted/invalid_result；沿用原接受/拒绝分支及short-circuit检查。记录既有now和当前sim_time、原观测身份/预算，日志wall_time仍取实际发布时间。未复制凭据/异常参数/命令到新事件，未追加一次授权检查或延长结果有效期。

## 验证层级

新增34项单元/合成与实际MuJoCo测试：入口与真实调用分开、截止精确边界、最终撤销、不同source/budget/episode、bool/NaN、ctrl/Command不符及禁射；两项actual MuJoCo在原步长真实mj_step下验证先写入再撤销和有效入口；7项collector接受/拒绝与延迟日志场景。它们不代表真实NN/目标跟踪通过。
专项488 passed/10 skipped/4既有collection warnings/57 subtests，31.27s，driver32.8178763s/exit0/reaped，程序源不变。

实际native为原无包装smoke，10秒，六车2ms/1440×1080/15总fps。ELF SHA67819b6812c2c4a87e2b411eed49c1e01cfb67212efdd2f2e0abd2aa3a963dec，ONNX b53470b42a5778aca8f3382ebe3c623482599cbf8ebad2e9a0dcc0c7f42c9255，客户端patch SHAf3d83e4d4584c7910958fda19f46dc310a310b8fb89376ebf5229a31b69bdf30。未构建/替换另一算法。
RTF0.7384549157625799、raw147、108request、103实际started/late_discard、5discarded_before_native、0 timely native_result、0 prepared/physical；clean/errors[]，exit2/reaped，原源不变。此轮没有真实有效entry可用于正向native执行验证，actual MuJoCo合成正向检查不可填补该缺口。

146个collector结果逐个有处置：110 aim_status、35 late_result、1 sample_discarded。35中的5个是原wall尚未到但sim已超，1个wall/sim均超；其余wall超。读取原日志只解释记录字段，不把pending当作成功推理/有效输出，也不把原生晚到tracking=true当作及时目标。CPU/GPU/系统负载未做受控因果隔离，不能断言本次RTF下降的单一原因。

`artifacts/native-integration-analysis-20261017-01/PUBLIC_EVIDENCE.json`保留不含会话/lease凭据的原时刻、原预算和处置；原私有ledger仅本地保留并记SHA，不重写旧记录。完整实际BGR本地留存，永久包取真实样本，未取替代像素。当前无射击、GUI、目标精度/目标关联、第二完整自瞄、完整导航决策协同或完整3v3通过，T01–T18与M0–M5以总进度表保留边界。

## 复现

按归档driver COMMAND.json及source snapshot准备原本地spec、ELF/ONNX和已审查客户端，再以`.venv-sim/Scripts/python.exe -X utf8 artifacts/run_native_integration_20261017.py --mode native --attempt <fresh-number>`运行。需支持真实NVIDIA/WSL；选新目录，不覆盖失败，不与构建/pytest/GL竞争启动。无本地native依赖时先按公开部署说明构建，不把原私有本机路径作为可移植部署承诺。
专项用同driver `--mode focus`，全量用`--mode quality`；运行期间冻结全部Git已知输入。脚本/实际argv/源码/日志/原始失败/后续QA与保留清单另存本证据目录。

最终QA01四阶段退出0：3665 passed, 46 skipped, 6 warnings, 1024 subtests passed in 166.94s (0:02:46)。driver 228.75098830000206秒/exit0/reaped；508项程序/测试/补丁输入与17944项Git已知全树输入在QA期间前后逐SHA相同。专项、一次真实native与QA的程序输入完全相同；新增测试不代表native/比赛验收通过。
QA后仅补记文档与永久归档/索引，四份pre-QA文档原字节另存归档；结果增补本身未参加先前QA。当前T2仍FAIL，M0–M5未关闭；未调用子代理。
永久归档1600记录/574唯一payload，3182406字节；108个实际BGR留本地，Git取1个真实样本；私有账本仅SHA。records.tar.gz SHA256：`9b4ce894f3fb606506bc5a2448b515ab56138edcbe12f6011dd7db1dc67ec35e`。
