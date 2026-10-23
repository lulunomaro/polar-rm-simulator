# 有界WSL输入接收

2026-10-23 UTC+8，父提交22653fe12abe5fe62e0a61f778955f0090dd3c28，work/plan-t01-t03。

2026-10-23：补齐WSL异步自瞄输入的有界连续readv接收，每批最多16次非阻塞读取或1ms即交还外层；原资源看门狗、完整SHA、额外字节/EOF拒绝、原80ms图像/150ms控制/RTF0.98和源身份保持。新增INPUT_IO本地统计及故障时仍回收owned child的保护，不增加图像缓存/队列、不压缩/降采样或更换算法。
48次同一真实BGR的Windows→WSL ABBA微基准全部SHA相同，外层select总次数3136/1260/1305/4132；耗时12.21/6.31/6.53/6.88ms。首组有预热差异，不声称整链稳定加速；readv调用反而增加。1MiB管道容量实验无稳定收益，未进入生产，也未修改全局WSL配置。
同日旧接收器对照RTF0.989471、138及时结果/81严格物理帧/2晚活动调用；新接收器RTF0.998485、120及时结果/69严格物理帧/3晚活动调用。两轮均clean/errors[]/禁射，全部原始判定FAIL；未挑较好结果签收，未将images_verified当作NN成功。剩余P0是entry→实际mj_step间过期撤销缺口，晚调用仍阻止整体验收。
保持六车2ms/NVIDIA1440×1080/15总fps、原自有CPU4 ELF/ONNX/客户端身份、静止red_infantry scope、对方SDK手控vy.08、gravity/yawgain4。未调用子代理/恢复定时任务/训练/硬件/完整比赛；通用接入/导航决策及M0–M5未据此关闭。证据见[有界接收修复](validation/payload_drain_20261023/README.md)。

## 行为与回归

原异步supervisor每个可读分片只readv一次，然后回到完整外层select/child.poll/stop/watchdog。现在只在fd0已非阻塞时连续接收当前可用数据，最多16次或1ms，EAGAIN立即交回，不等待新数据；每次读前检查同一个header_started+1s资源看门狗，原80ms行动期限仍由host与原Linux完整输入期限检查约束，两个时钟不跨域相减。partial进度保留在持有的同一bytearray上；额外一个字节原readv溢出检测保留，坏SHA不进入native。不增加并发推理/输入队列。

批次上限是本地公平性目标，Python被调度挂起时不构成硬实时保证。INPUT_IO只记录有效payload readv字节、header携带payload字节、被拒绝read字节、EAGAIN/批次数以及原SHA验证图像数量，不是算法执行或及时动作证明。统计写盘在原owned清理finally内捕获异常，失败必须使clean=false，不能跳过child/tmpfs回收。

12个新默认测试：多片同缓冲正确拼接；初次/中途EAGAIN不自旋；持续可读时16调用/1ms公平退出；watchdog精确到期及批次中到期；EOF/overflow/IO故障不当作完整帧且保留进度；INPUT_IO写盘故障仍回收owned child并报告清理不完整。专项624pass/13skip/4既有warning/61subtests，34.37s，driver34.990561s/exit0/reaped。

真实BGR微基准为同一个历史实际捕获帧，12帧×参考/候选/候选/参考，以逐帧ack保持一笔在途，完全相同bytes/SHA；候选用生产_drain_payload，参考每次外层select只调用原_read_payload_into一次。它不运行NN/物理，不是实时资格。另一个1MiB容量实验有48张同SHA输入，但收益波动，未改生产/系统配置。Linux探针每帧2秒仅是无NN微基准资源上限，不用于真实native或80ms资格。

## 原生结果与不足

旧实现通过git show取父提交worker原字节，仅在自有串行对照运行期间替换这一文件，候选字节保存并在finally恢复；00 driver退出并验证source_unchanged后恢复，无运行中混源。baseline.py/candidate.py/RESTORE.json保留原SHA与过程。新01、专项01、最终QA必须逐SHA同程序源；00保留自己的原源，只有worker和测试源存在差异，具体清单另存。

| 真实运行 | RTF | 及时结果 | 严格物理帧 | 晚活动调用 | clean | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| 00 旧接收器 | 0.9894705278 | 138 | 81 | 2 | true | FAIL |
| 01 新接收器 | 0.9984851343 | 120 | 69 | 3 | true | FAIL |

均10秒/原六车2ms/NVIDIA1440×1080/15总fps，原图像80ms/控制150ms，RTF门禁0.98不变。新01 INPUT_IO：135次完整SHA验证，15672批/76729read调用/14294EAGAIN；622586673有效readv字节+7269327 header图像字节=135×4665600，拒绝read字节0。此处不代表135个成功NN/动作。及时结果120、严格物理帧69另由原源身份/入口/实际call/ctrl/Command核对；3晚调用未被好的帧掩盖。

两轮输入轨迹/负载不是确定性同帧回放；不把RTF数值变化归因于单一优化，及时结果/有效帧数反而下降。当前阻塞已明确为最后entry检查到真实call之间的时间缺口，不能延长deadline/保持过期输出/改时间戳来过关；下一步须修复实际过期撤销并继续按同一门禁验，不将接收器优化写成自瞄已修好。

原ELF SHA67819b6812c2c4a87e2b411eed49c1e01cfb67212efdd2f2e0abd2aa3a963dec；ONNX b53470b42a5778aca8f3382ebe3c623482599cbf8ebad2e9a0dcc0c7f42c9255；客户端patch SHAf3d83e4d4584c7910958fda19f46dc310a310b8fb89376ebf5229a31b69bdf30。未替换算法或喂入目标真值，火控false；运动是SDK手控fixture，导航/决策/跟踪/射击/完整比赛均不得据此签收。

复现：归档driver/COMMAND.json及源快照对应实际argv；准备公开部署所需原ELF/本地spec/模型/客户端后，`.venv-sim/Scripts/python.exe -X utf8 artifacts/run_payload_drain_20261023.py --mode native --attempt <fresh>`运行真实链，focus/quality模式运行对应检查。选择新目录，不覆盖旧失败；构建/GL/测试/native串行，QA期间冻结Git已知输入。原私有ledger与完整实际BGR本地留存，公开事件只留源身份、时间/预算、target、ctrl/Command与检查；取真实帧样本进入永久包，私有账本只记SHA。

最终QA01四阶段退出0：3689 passed, 47 skipped, 6 warnings, 1024 subtests passed in 172.76s (0:02:52)。driver 234.44433290000597秒/exit0/reaped；510项程序/测试/补丁输入与17954项Git已知全树输入在QA期间前后逐SHA相同。专项01、真实native01与QA的程序输入完全相同；旧接收器00保留原源，两个实际原生运行均FAIL。新增测试不代表native/比赛验收通过。
QA后仅补记文档与永久归档/索引，四份pre-QA文档原字节另存归档；结果增补本身未参加先前QA。当前T2仍FAIL，M0–M5未关闭；未调用子代理。
最终COMPARE.json逐SHA核对510项程序输入，对照00与候选01实际仅wsl_aim_async_worker.py不同，测试文件也相同；不据此推断输入轨迹/系统负载相同。初始恢复candidate.py是后续溢出诊断补记前的中间快照，最终运行source快照保留最终源。
永久归档2172记录/609唯一payload，4305906字节；276个实际BGR留本地，Git取2个真实样本；私有账本仅SHA。records.tar.gz SHA256：`553d940176c8da026caf7cbd99d756296d79e84ea3460de4acaa02d434be9354`。
