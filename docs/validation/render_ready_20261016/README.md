# 显式按渲染就绪拍摄与静态及时链恢复

本轮最终默认运行恢复138个及时T2结果、134个独立帧的实际云台消费，最长wall age78.1184ms。
**整轮仍FAIL**：10秒physics RTF0.961707低于原0.98。没有移动自瞄、自动开火、实体命中或完整3v3验收。
父提交82195be3156272495d55aa2b73b441375ecadeb9，分支work/plan-t01-t03。全轮未调用子代理。

新增CameraProvider显式render_ready策略，GL/编码忙时才延后新的物理快照，先处理撤权与回合变化。
不修改旧图时间或像素，默认latest_pending和原标定/80ms图像/150ms控制不变，实际FPS可能降低。
本轮ready01忙时延后计数0，默认02/03也恢复及时链，故不能把改善归因于新策略。
保持六车/2ms/1440×1080/15fps上限、原CPU4 ELF与ONNX、显式CV4/CPython1ms/authority mask0x10。

| 实际静态运行 | ready01 | default02 | 最终default03 |
| --- | --- | --- | --- |
| scalar Command快照 | 优化前 | 优化前 | 优化后 |
| run+cleanup wall秒 | 10.0890160 | 10.0957523 | 10.0896508 |
| driver秒/exit/reaped | 25.2343708/2/是 | 22.7413714/2/是 | 24.3827509/2/是 |
| physics RTF | 0.964237 | 0.964767 | 0.961707 |
| raw/及时结果/独立帧执行 | 148/138/137 | 148/136/136 | 148/138/134 |
| 最大执行wall age毫秒 | 78.5482 | 75.6497 | 78.1184 |
| 唯一未过判据 | physics_rtf | physics_rtf | physics_rtf |

三次原输入预算/像素反查/请求归账/owned清理/执行源码逐SHA均通过，SDK/runtime无错误、fire0。
最终03的141笔原请求=138 stdout+1 late+1 after-pending discard+1 owned unwritten cancel，未把它们都算及时结果。
原binding期限撤权不改。旧零及时结果、binding_mismatch与其它失败全部保留，不因本轮恢复回写旧状态。
当前GPU读回约8ms，而旧记录40–50ms；未隔离硬件负载/功耗/系统调度，不宣称性能因果或跨机器稳定性。

Command快照仅将六个不可变字段直接放入新dict，保留值/类型/分离性，替代每2ms递归asdict。
离线六Command/10000轮ABBA：asdict0.0745421/0.0760521s，scalars0.0121251/0.0125949s。
这不等于生产RTF改善，实际default03仍未达0.98。保留了原执行器守卫、每消费边界和完整显示字段。
OpenCV浮点/定点镜头映射ABBA出现像素SHA差异且无明显收益，放弃改动，原镜头映射源码不变。

相机源码修改使旧PB静态mount source pin正确拒绝，首个全量1fail/3403pass，未绕过校验。
新增`tools/capture_aim_mounts.py`按当前编译模型重新导出六车设计，0物理步/0NN/0GL，与旧robots数据逐值相同；
新SHA e77f3c1c785d4791761e1a095129198c4d5dd154730f069118213a796a27acd6。
原PB校验器、旧mount和旧spec不变；使用新文件仍须显式准备新配置和重新验证，不能继承旧PB完整运行资格。
测试现在提取当前实际模型，通过原checked_mount并测试错误SHA/robot/source；单列旧mount必须拒绝的负例。

早期相机JUnit两失败源于测试误认已完成MjData池不能复用、plan字段名，修正后156pass/40subtests。
mount+camera专项30pass；最终原运行时/消费期限/guard等64pass。初次全量期间文档曾编辑，该轮不作为最终冻结通过。
专项初次JUnit无完整运行前源码快照，不将后补的最终源冒充其原始执行源；真正native与全量driver保留各自原输入快照。

复现入口（需本机已核验的原spec、ELF/模型与第六client，二进制与私有配置不在包中）：

```powershell
.venv-sim/Scripts/python.exe tools/capture_aim_mounts.py --out artifacts/YOUR_FRESH_MOUNTS
.venv-sim/Scripts/python.exe tools/smoke_wsl_native_live.py --native-transport wsl_async_bgr_v3 --camera-capture-policy render_ready
.venv-sim/Scripts/python.exe tools/check_project.py --out artifacts/YOUR_FRESH_QUALITY
```

第二条仅打印计划。实际argv、环境与原始失败/结果见归档；native最终03不带可选计时，完整QA显式启用POLAR_TEST_WSL及本机原spec。
[MANIFEST.json](MANIFEST.json)把原路径/SHA映射到[records.tar.gz](records.tar.gz)的内容寻址payload，逐payload解压核验。
每次真实BGR仅入Git一份，全部本地帧保留完整pixel audit；私有admission、SDK/owner账本、无关进程清单仅本地保留SHA排除记录。
[FILES.json](FILES.json)固定包文件字节，不自引用。最终结果说明与归档在QA后补写，不称为参与此前检查。

最终QA02四阶段通过：3405pass/45skip/6既有warnings/1024subtests，pytest142.63s、driver185.3665567s、exit0/reaped。
492个程序/测试/补丁输入前后逐SHA相同，17884项全树输入在该轮前后相同；native03使用同一最终492项输入。
本段与进度任务表结果在QA结束后补写；质量通过不改变三次实际live均因RTF判FAIL。

归档2595条原路径记录、593份唯一payload，4,585,203字节；423份完整实际BGR保留本地，Git取其中3份。
records.tar.gz SHA256：`da0d58197f746f084eec5405c5ddeca72e1860c7b21efdf46d2a94141d4f8c7a`。
