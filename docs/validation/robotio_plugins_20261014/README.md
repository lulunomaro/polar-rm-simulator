# 通用 RobotIO 接口检查点：2026-10-14

父提交 `d4a41b010de700e65768650a273c447e67940315`，开发分支 `work/plan-t01-t03`。
导航、决策、自瞄是独立配置组件；北极熊、T2、同济不构成队伍白名单。
接口说明见 [UNIVERSAL_PLUGIN_INTERFACES.md](../../UNIVERSAL_PLUGIN_INTERFACES.md)。
本包保存 328 项原始文件，原始 6,537,571 字节、存储 2,602,127 字节；SHA 和 literal/gzip 映射见
[PRESERVATION_MANIFEST.json](PRESERVATION_MANIFEST.json)。原始路径是映射键，不要求本机仍存在旧 artifacts。

## 已验证的范围

| 记录 | 实际结果 | 资格边界 |
| --- | --- | --- |
| aim-command-mapping-focused01 | 58 passed | 单元/codec；单位、符号、偏置、曝光/惯性角和严格 source；无新 NN/ROS |
| navigation-plugin-focused01 / decision-plugin-focused03 | 27 / 37 passed | 初始组件冻结源码、真实 stdlib JSONL 回执；不是队伍算法 |
| robotio-wsl-focused01 | 41 passed | WSL wrapper 生命周期 mock + nav，非实际 WSL |
| robotio-composition-focused04 | 34 passed、exit0/reaped/source unchanged | 双独立策略组合、身份/权限/原期限、实际 loopback HTTP；ROS 是假传输 |
| robotio-stop-intent-focused01 | 60 passed | host/peer 拒绝 hold/cancel 后非零速度；两个实际违规子进程回收；无 physics/ROS |
| platform-robotio-cli-focused02 | 18 passed / 10 subtests、exit0/reaped/source unchanged | CLI scope/共享清理 mock，非算法或物理运行 |
| ros2-jsonl-startup-focused02 | 4 passed | 真实 owned stdlib child、启动开销从总2秒扣除、非空进程回收证明；无 ROS |
| robotio-ros2-actual03 | exit0、五项检查全通过、source unchanged | 实际 Windows→WSL→Humble DDS；输入为合成 codec fixture，无物理传感器/队伍算法/NN |
| robotio-protocol-sil03 | exit0、14 checks全通过、source unchanged | 两车真实 MuJoCo 低点频协议消费；独立合成策略/恒速 fixture，非 SLAM/导航/自瞄/比赛 |
| quality-aim-followup05 | 四步骤exit0/source unchanged；1991 passed / 40 skipped / 1010 subtests / 6既有warnings | 配置、来源、接口静态和全量测试；不签收里程碑 |

最终 QA pytest 137.04 秒；外层 driver 175.6930609 秒且已回收。程序/测试/DEVELOPMENT_CHANGES
在 QA 后维持相同 SHA；之后新增本包和文档结果说明。没有把新增归档写成参与此前 QA 的源码。
初始组件专项的 source snapshot 与最终导航停止语义源码分别保存，不能将旧专项重标为最终字节已测。

## 实际通信与物理记录

[DDS03 RESULT](records/artifacts/robotio-ros2-actual-20261014-03/RESULT.json) 保存真实两类 prepare、原2秒 reset 与原 source echo。
内部驱动 7.906444 秒、外层 8.0219407 秒；原1秒图/能力协商、50ms导航回复、150ms宿主时窗不变。
真实 Linux owned tree、Windows Job 与 IO 线程清理证明分别保留；不能将异地 monotonic 时钟相减或刷新旧时刻。

[SIL03 RESULT](records/artifacts/robotio-protocol-sil-20261014-03/RESULT.json) 保存1771步/3.542秒仿真、原2ms步长、
显式1000点/秒实际 ray/gyro/accelerometer。四个 peer 在物理前真实资源准备0.6567465秒，不供应观测或虚假推理；
真正 binding 仍取得原2秒能力 reset ACK。此 prepare handover 是专用测试 harness，未验收默认服务器 JSONL 启动。

供给决策 v1/热量决策 v2 独立运行，goal-aware导航 fixture 只按实际意图返回恒速/零速，并非规划器。
两车各26个独立原 source action：红步兵2799条receipt/935非零消费步骤，蓝哨兵2940条receipt/980零速步骤。
AUDIT 独立核对原 typed6、决策→导航、SDK原window/lease/activation、原wall/sim150ms和实际执行器消费，errors=[]。
内部驱动5.8676381秒、外层6.1212747秒；runtime join .0387555秒，四子进程/HTTP/SDK均clean。
EVAL世界位置只用于隔离评测，不给peer；本记录不验收RTF、MID360、SLAM、目标到达、移动自瞄、开火或完整比赛。

## 保留的失败

- 初始 decision/组合专项失败 XML、修复前后 source、各次成功日志均保存；没有覆盖首次失败。
- DDS01 使用的 supervisor Python 缺 NumPy，尚无 Linux HELLO/CLEANUP，Linux group回收未证明。
  Windows Job 已清空不能替代 Linux 证明；无算法输入。DDS02 显式使用已有核验的 ext4 Python后通过，
  DDS03 在最终停止语义源码下再通过；原ENV SHA和旧失败保持，没有安装替代依赖或合成回收证明。
- SIL01 两车原动作与时限审计通过，但 actor退出与authority关闭竞争，整体失败。
  SIL02 提前actor释放后clean，但红车act越过原deadline后被拒绝并fault，整体失败。
  SIL03 先完成真实零输入资源准备再开始物理，保留原期限后通过。
- QA04 前三步通过，pytest14failed/1976passed/40skipped/1002subtests，原源码期间不变。
  旧 Sensors mock无robot_ids参数、旧diagnostic硬断言内部exchange恒为2秒。
  新断言保留全部旧负例，增加通用scope和真实总预算/非空Windows child清理；核心未为测试改限或回退scope。

当前 decision v1 的 navigation/perception明确unavailable；真实队伍反馈协议/包装、Qt通用导航选择、自动火、
第二套完整自瞄、移动/多车真实算法、两机LAN、3v3/7v7和M0–M5签收仍需独立工作。
此前T2三次静态live、PB单目标导航与PB图像80ms失败范围保持；本包没有重新运行它们。

## 校验与复跑

`FILES.json` 绑定本包其他所有文件，`verify_archives.py` 只做完整性校验，不执行算法。

```powershell
.venv-sim/Scripts/python.exe docs/validation/robotio_plugins_20261014/verify_archives.py
```

解压任意gzip记录后必须核对original_bytes/original_sha256；不要改写此包或覆盖旧artifacts。
通用协议演示可从仓库根目录显式复跑，输出必须全新：

```powershell
.venv-sim/Scripts/python.exe tools/qa_robotio_protocol_sil.py --out artifacts/robotio-protocol-fresh --duration 4 --run
```

实际 DDS 驱动/固定本机ext4环境信息按原字节保存，需先取得并核对该真实环境；不会自动下载ROS或启动硬件。
生产接入须替换fixture为实际审核wrapper，并保存原图/传感器→队伍算法→执行器的独立证据。
