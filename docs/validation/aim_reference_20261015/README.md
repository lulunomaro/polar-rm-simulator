# 通用自瞄源方向与最终执行器修复

父提交 `4908d19b5a1239cb1c235259a8779db595e82831`，分支 `work/plan-t01-t03`。
用户指定总计划 `PROJECT_PLAN.md` SHA为 `299b58e785778ae143ff86808f333d2c6ff4e470a00d4dd9138ee1c7380a21fd`。
本轮修复了宿主最终检查的新角度未进入真实Command的问题，新增显式通用aim v2源方向协议，
并修复暂停后在途旧源复活、取消缺证和停止后管道关闭误标。**最新原生实时回归仍FAIL，移动T2及完整3v3尚未通过。**

## 实现与有限通过范围

`polar.sim.aim-plugin.capabilities.v2` 显式增加 `inertial_from_source_base_v1`，要求camera+odometry。
旧v1的相对关节角和wire ACK保留；JSONL/owned WSL的prepare/reset必须精确协商完整能力。
v2锁定原source observation的本车yaw、六身份、原动作与camera预算，消费时换算当前机械yaw；
不刷新80ms图像/150ms SDK窗口，不补平移、目标运动、弹道或三维IMU。未知合同不得推断接受。
固定第五Qt和旧ROS envelope仍拒绝v2，协议SDK路径可绑定；示例是需部署真实wrapper的模板。
接口实现不表示大部分外部自瞄已实际通过，也没有放开T2 stationary门或自动火控。

真实MuJoCo机械正/负对照各1000个2ms步、两车三phase共6000行，输入是合成指令/guard/clock。
旧backend最大实际Command/ctrl聚合偏差0.07002480126182786rad，新版为0；两车旋转且合成预算失效后撤权。
helper夹具可用budget=None，生产collector另强制校验原非空camera预算。
逐步raw ctrl没有保存，0/旧偏差是工具当次读取真实data.ctrl后的聚合断言；保存target独立重算残差约1.22e-15。
这些是0图像/0NN/0SDK的离线机械证据，不能称移动自瞄闭环或实时性能通过。

真实AdapterSlot阻塞线程证明pause→resume旧在途结果复活：修前1失败，按同绑定observed_seq水位修后83pass/20subtests。
新源恢复用collector夹具，不冒称完整相机scheduler恢复或实际双任务排队实验。v1恢复行为、换代及原期限另有回归。

WSL v2协商02使用真实无害peer，实际prepare/reset/完整capabilities ACK与原出生身份进程回收通过，0act/图像/NN/物理。
01误选Ubuntu下不存在的解释器，无HELLO/CLEANUP，原cleanup unproved保留；02不能补证01。
取消专测有157pass，包装过期/绝对期限修复196pass，最后STOP管道专测205pass；各自范围及源SHA分别保存。
真实partial输入取消02实收1024/4665600bytes后STOP，未宣称完整SHA/NN，约68.8ms回收。
最后真实Windows原write/read/close+Ubuntu监督器的gated部分接收验证02，STOP后原FileIO产生EPIPE，
仅记source-bound interrupted候选；原Linux input_cancelled和owned清理独立证明闭合，0NN，约49.6ms回收。
候选本身不提供terminal，never-attempted+0bytes证明与attempted但返回字节未知严格分开；既有fault不能洗白。
各actual01的夹具导入/过短冷启动失败均保留原driver，不回写通过。

## 实际原生回归与尚存性能问题

同原CPU4 ELF/ONNX、CV4、pybase641.5.1、CPython1ms、authority mask0x10、六车2ms、
1440×1080单视角15FPS和原80/150ms，三次单车静止10墙钟秒实测如下。没有用旧算法或像素替代。

| 原记录 | 物理RTF | raw帧 | 原生结果 / 独立源帧消费 | 未归账请求 | 原classification |
| --- | ---: | ---: | ---: | ---: | --- |
| native01 | 0.976948387 | 148 | 95 / 85 | 1 | FAIL：physics_rtf, all_native_requests_completed, original_async_transactions_accounted |
| native02 | 0.933982086 | 147 | 75 / 36 | 0 | FAIL：physics_rtf, runtime_error_free, original_async_transactions_accounted |
| native03 | 0.821309897 | 146 | 49 / 32 | 0 | FAIL：physics_rtf, original_async_transactions_accounted |

01的108号缺少source-specific pre-native终态，精确停止phase未知；后来的证明不能补旧日志。
02真实input取消已闭合，但一条桥接及时结果到包装时已过期并正确拒绝；QA原来漏列此分支。
02另有同一frame22三phase的sim_time恰等原sim_deadline，减法得0.08000000000000007而误报；
原wall尚余4.75ms以上。修复只比较原绝对边界：wall严格小于deadline、sim保持原inclusive上界，
不加epsilon、不四舍五入，原差值/分布保留，原02 RESULT仍FAIL。
03中101号先owned_stop，再约65ms后因正在写的大pipe关闭出现EPIPE，旧host无差别标fault；
Linux已保存同原源112516/4665600bytes部分输入取消。QA拒绝fault是正确保守行为；最终仅窄修STOP后的明确关闭异常。
最后host修复后没有再跑T2 NN，不能把03重标最终源码通过。

所有原实际输入/像素审计、拒绝及清理原件保存。三次RTF均未达0.98，本轮没有新的静态实时资格。
无相机/绑定/NN的真实六车1000步fresh-process ABBA，parent均值0.838887ms/step、current0.815237ms/step；
仅说明此空闲公共路径未显示退化，不能解释绑定、图像和线程交互中的实际下降，不能因而断定外部负载是根因。
一次cProfile单列，不纳入吞吐对照。下一步应继续定位实际绑定/图像链的GIL、渲染、IO和原生时序，保持原门限。

## 最终质量与证据保存

最终四阶段质量检查通过：`3322 passed, 45 skipped, 6 warnings, 1024 subtests passed in 154.50s (0:02:34)`。
driver 217.932701s、exit0/reaped，472个程序/测试/来源输入前后逐SHA不变。
QA01保留3217pass/1旧WSL GIL压力测试原期限失败/45skip/1024subtests；该旧压力源独立诊断1pass不回填QA01。
独立审查发现的host fault取消缺口先有4失败负例，修后通过；审查早稿在并发修补期间SHA归属错误有AFTER更正，原件保留。
部分旧before源码未直接捕获：派生恢复副本逐SHA命中当时执行map，明确标记direct_original_byte_capture=false，未冒称直接捕获。
本README、进度结果段和归档在最终QA之后补写，不声称参与此前检查；执行程序/测试保持最终QA字节。
单位、合成、离线机械、实际无害进程和实际T2静态失败各自分类，不以质量通过关闭M0–M5。

[PRESERVATION_MANIFEST.json](PRESERVATION_MANIFEST.json)将2733条原文件记录映射到
[records.tar.gz](records.tar.gz)的759个去重原字节payload，逐member已验证。
archive SHA：`12fa2955d20189c498f5d17dbab545ba095fc4e06fff0c7bc464b2d75f692200`。
三轮完整原图共313份留在本机artifacts，Git内每轮保留一个实际BGR样本，完整逐帧hash审计保留。
不含admission、SDK_EVENTS、clear credential、ELF/动态库、ONNX模型、第三方完整checkout或字节码缓存。

本机复现（使用fresh输出目录；WSL解释器需已安装且实际存在）：

```powershell
.venv-sim/Scripts/python.exe -X utf8 tools/qa_aim_reference_mechanics.py --out artifacts/local-aim-reference-mechanics01
.venv-sim/Scripts/python.exe -X utf8 tools/qa_aim_reference_wsl.py --out artifacts/local-aim-reference-wsl01 --distribution Ubuntu-22.04 --linux-python /root/polar-humble-ext4-20261014-01/venv/bin/python
```

真实T2复现命令在各driver的COMMAND.json中，必须先按原构建记录准备实际spec/ELF/模型/原客户端；此包不携带这些依赖。
下一原生移动profile仍需fixed-own-odom、tracker原点和pivot-relative FireController链、新源身份与29TU clean build，
再做正常速度移动/重捕获/实体弹丸；第二实现、Qt v2、两机LAN、3v3/7v7、换机发布与HIL均未完成。
