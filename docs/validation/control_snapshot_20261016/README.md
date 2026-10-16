# 控制快照复制减负与实际失败

本轮实时仍FAIL且相对旧静态恢复记录退化。没有移动、自动开火、完整3v3或M0–M5签收。
父提交4ddeb55e1c515f038b0c20c28ec68c8e9e827c49，开发分支work/plan-t01-t03。本轮未调用子代理。

ControlPlane的binding快照原先整图deepcopy；现在仅直接复用None/bool/int/float/str精确类型，
所有非标量仍deepcopy，共享memo保留嵌套共享/循环引用。公开全局与单车snapshot两处使用同一helper。
未缓存授权；原session/lease/activation到期、锁、revision、80ms图像/150ms控制与每个消费边界检查保留。
插件边界的JSON序列化校验没有改变，未知可变字段仍分离。

1000个实际六车2ms步的离线cProfile无GL/NN/ROS；snapshot累计0.660→0.245s只用于定位，含剖析器开销。
无剖析器、明确合成固定时钟、原同值公开snapshot的ABBA，每组4000次：

| 场景 | 原helper A1/A2秒 | candidate B1/B2秒 |
| --- | --- | --- |
| 六车idle | 0.3601857 /0.3336793 | 0.1817983 /0.1843007 |
| 单车激活窗口与嵌套配置 | 0.3437710 /0.3967282 | 0.2328574 /0.2257156 |

两种实现都带同一额外helper调用，退出后恢复；不是生产RTF、GL、NN或实际授权验收。

| 真实原T2单车静止、六车场景 | candidate01 | parent02 | candidate03 |
| --- | --- | --- | --- |
| control / mask | 新copy /0x10 | 实际父源码 /0x10 | 新copy /0x100 |
| run+cleanup wall秒 | 10.0913964 | 10.0878651 | 10.1297212 |
| driver秒/exit/reaped | 22.3051271 /2 /是 | parent outer28.4621659 /inner2 /是 | 26.1924251 /2 /是 |
| physics RTF | 0.673369 | 0.432765 | 0.542763 |
| raw/及时结果/独立帧执行 | 146/46/19 | 145/1/0 | 146/4/3 |
| SDK/runtime错误 | 无 | 无 | 无 |
| 判定 | FAIL，RTF | FAIL，RTF/样本/动作 | FAIL，RTF/样本/动作 |

所有原capture预算、真实像素反查、请求归账、owned清理、各自执行源码核对通过，fire0。
保持原CPU4 ELF/ONNX、1440×1080/15fps上限、2ms/六车、原CV4/CPython1ms；无可选phase/authority计时。
parent02只为显式对照恢复实际父提交control.py与DEVELOPMENT_CHANGES，运行期间固定，结束还原候选原字节。
它使用父实现而非最终实现；不套用最终candidate的源身份或单元验收，T2算法本身没有回退。
01与03候选程序相同，但mask不同；没有控制系统负载等条件，不能从这些run定因、排除回退或宣称生产收益。
真实运行低于原0.98，不改时间、门限、物理目标速率或验收标准。旧138/134及0.961707记录仍按旧源保留。

专项65pass，覆盖原精确截止、sticky撤权、嵌套/共享/循环结构与双向隔离。
初次两测试误用SDK调用形参，直接API返回invalid_lease_epochs；修改的是测试，产品校验不变。
含完整临时会话表示的初次失败JUnit仅本地保留，包内记录SHA与简化失败说明，避免发布原会话标记。
离线profile首次按文件执行因模块路径失败；之后按-m执行，原错误保留，不声称已启动物理/推理。

复现入口：

```powershell
.venv-sim/Scripts/python.exe -m pytest -q tests/test_control_snapshot_copy.py
.venv-sim/Scripts/python.exe tools/check_project.py --out artifacts/YOUR_FRESH_QUALITY
```

实际native argv、局部显式参数、各driver源码和原结果在归档。ELF/ONNX、私有本地spec和完整SDK/owner账本不发布。
[MANIFEST.json](MANIFEST.json)映射原路径/SHA与[records.tar.gz](records.tar.gz)内容寻址payload，逐项解压核验；
每次取一份真实BGR，全部本地帧保留完整pixel audit。[FILES.json](FILES.json)固定包文件SHA且不自引用。
本README的最终结果与归档在QA结束后补记，不声称参加此前检查。

最终QA01四阶段通过：3409pass/45skip/6既有warnings/1024subtests；pytest155.88s，driver232.3592175s、exit0/reaped。
493个程序/测试/补丁输入前后逐SHA相同，17889项Git已知输入前后相同；native03与此最终程序集相同，parent02原源另存。
这些测试结果不覆盖或取代三次实际失败，未声称实时、移动自瞄、完整比赛或发布验收。

本次归档2110条原路径记录、599份唯一payload，3,569,063字节；357份完整实际BGR留本地，Git取3份。
records.tar.gz SHA256：`66b3e87a2eaf1b86178b6d3931a234ff462724ecdfd0da50f59735909552c213`。
