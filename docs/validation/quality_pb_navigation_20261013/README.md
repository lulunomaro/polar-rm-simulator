# 点云 / Humble 开发检查点质量记录

attempt1 保留完整失败：1117 passed / 1 failed / 10 skipped / 574 subtests。
唯一失败为 WSL 实际初始化测试引用历史 spec，当前 builder SHA 已变化，门禁正确拒绝。
历史 spec 与 ELF 未修改。实测入口新增显式 POLAR_WSL_TEST_SPEC 选择本次真实默认构建。

attempt2：1118 passed / 10 skipped / 574 subtests，preset、source provenance、静态接口、
实际相机 35 checks 全部退出 0；871 项 source 在检查期间不变。
无推理、帧或物理步的默认 ELF 实际初始化/回收测试通过，不是实时自瞄通过。
相机 QA 与 ROS / 物理 / 合成测试按 manifest 中的 evidence_level 分开解释。

```powershell
$env:POLAR_TEST_WSL='1'
$env:POLAR_WSL_TEST_SPEC=(Resolve-Path 'artifacts/native-original-nav-checkpoint-build-20261013/operator_source.local.json').Path
.venv-sim/Scripts/python.exe tools/check_project.py --out artifacts/quality-new --camera
```

spec 是当前机器构建结果，换机需从固定源码重新构建，不可从此记录恢复 ELF。
PRESERVATION_MANIFEST.json 保存逐文件原路径、长度、字节 SHA。检查结束后新增此 README、
归档目录和进度说明；业务代码未改。M0–M5 尚未完整签收。
