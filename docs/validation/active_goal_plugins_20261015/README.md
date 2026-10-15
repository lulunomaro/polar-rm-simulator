# 通用当前目标授权插件证据（2026-10-15）

本包保存新增active-goal能力版本、原执行源、受控回归及真实低率MuJoCo协议路由，
父提交为24ead6483ddac99f313535ad433abdbbcdfe8ea1。完整3v3、真实PB新注册组合、
新profile真实DDS、自瞄/定位反馈/RTF/LAN均未验收。此前真实PB native UUID的独立SIL归属旧包，不挪用。

## 结果与失败

- 最初插件/传输专项133通过；其执行源独立保存。
- 最后新profile、ROS包络、契约/历史、compute、PB raw UUID来源与独立审计190通过，
  exit0/reaped/source unchanged。另保存contracts历次59/66/67、compute29与PB source26的原命令/源/原日志。
- actual01内部20检查通过，但外层在leader退出时Job非空、forced清理，整轮严格失败。
  不依据后续结果重判这次，初始源219份前后一致。
- actual02内部20检查通过，外层在原1.5秒清理期限内实测Job1→0/5.1622ms，
  无信号或强制终止，exit0/reaped，220份执行源前后一致。
  4秒/2000物理步，56个决策与56个导航结果。红方28action中27有实际消费，
  2371消费回执/792非零物理步；蓝方28status、0action/0motion消费。
  四个独立peer的归属/IO/SDK/HTTP全部clean，runtime join .0546202s。
- 后续审查发现02的外层reader join有独立1.5秒，新03将所有外层Job/reap/reader/handle共用一个1.5秒deadline。
  原02脚本/记录不改、不重标。actual03仍20检查通过、2000步，28action全部消费/2473回执/828非零步，
  蓝28status/0action/0motion消费。runtime join .0541796s，外层总清理.005654s，Job1→0→final0，
  reader停、handle释放、exit0/reaped，无forced，220执行源不变。
- 最终全量QA13四步骤0、2550pass/41skip/1024subtests/6既有warning；pytest141.63s，
  driver182.6746119s、exit0/reaped，435份程序/测试/来源前后相同。准确结果以本包
  `quality-aim-followup-20261014-13`和`aim-followup-quality-driver-20261014-13`原manifest/RESULT为准；
  检查不等于里程碑签收。

UUID与常速度由明确标记的synthetic后端产生，本包不证明任何原生controller实际产生了这些UUID。
受控ROS包络检查不是DDS；PBGoalControllerSource单元组合也不是实际ROS/PB注册运行。
导航/相机/SDK的原50ms/80ms/150ms和资源清理门限未扩大。

## 复现

使用相同已准备本机依赖，实际低率协议路由入口要求全新目录和显式运行：

```powershell
.venv-sim/Scripts/python.exe tools/qa_active_goal_protocol_sil.py --out artifacts/active-goal-protocol-fresh --duration 4 --run
```

该命令只运行synthetic队伍组件、真实MuJoCo点云/IMU/SDK，不包含相机、模型、ROS或GUI。
两份本地examples清单显式选capabilities.v2和导航结果v1，HTTP不能选择程序路径。
外层强归属检查的实际driver01/02位于各自`source/artifacts/`，原Windows Job身份与逐次计数都保留。
生命周期cancel ACK不等于terminal stop，status不伪造成零action。

## 字节与归档

`PRESERVATION_MANIFEST.json`记录每个原路径、SHA256/字节数与literal/gzip映射，gzip mtime=0。
原失败、实际执行源快照及后来源码分别保存，不改旧检查点或回填旧qualification。
`FILES.json`覆盖包内所有交付文件（自身除外）。运行`verify_archives.py`检查覆盖、原件散列及解压散列。
SDK原始私密事件、admission凭据及本地私密设置不纳入包；无模型、ELF或第三方可执行资产。
后续进度文字仅报告完成的QA结果，不声称QA测试了结果填入后的文案。
