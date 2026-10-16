# 历史显示采样与真实启动失败

父提交3718807e1b66d8d76ba006d6d1da9886c1ddf119，分支work/plan-t01-t03。本轮未调用子代理。
原80ms图像、150ms控制、0.98 RTF、2ms物理步与六车场景均保留，M0–M5未签收。

PlatformRuntime可显式设置telemetry_publish_interval_s（0..0.1秒），默认0继续每步发布。
只有display_snapshot、camera.status与历史receipt显示索引/JSON拷贝受该频率影响。
曝光安排、算法采样/收集、锁内原期限检查、所有执行边界守卫、MuJoCo和全部trace每步执行。
首帧、revision/episode变化、时钟回退强制采样；close独立发布停止/归零状态。
延期缓存保留原sim_time/sample_sim_time/steps/receipt时间；公开快照保持historical标志和当前租约投影。
暂停/裁判HUD可延至下一发布，物理急停立即检查；不保证发生操作系统停顿时仍能按周期发布。

专项394pass/88subtests、2既有warnings，driver31.8252986秒/exit0/reaped，494执行输入前后相同。
13项新回归使用真实MuJoCo与合成时钟（无GL/native/实时性能资格）：逐步qpos/ctrl、完整receipt、相机调用，
两次显示间的原指令到期归零、历史样本不重戳、release/reset/clock回退/close与非法本地设置。

ABBA各1000实际六车2ms物理步，明确合成调度时钟、无GL/NN/ROS：

| 顺序 | 默认A1 | 20ms B1 | 20ms B2 | 默认A2 |
| --- | --- | --- | --- | --- |
| 实际循环wall秒 | 1.6762485 | 2.6660001 | 3.8221278 | 5.1894252 |
| 显示发布/延后 | 1000/0 | 91/909 | 91/909 | 1000/0 |

四组最终qpos/ctrl字节哈希与18000次执行边界记录计数相同；条件未隔离、时长漂移，不宣称性能因果收益。

| 实际静态启动 | 01无可选计时 | 02阶段诊断计时 |
| --- | --- | --- |
| 原计划/实际physics wall秒 | 10 /0.8970823 | 10 /0.5943057 |
| 早停physics RTF | 0.2831401311 | 0.2422995438 |
| raw/及时结果/独立帧执行 | 13/0/0 | 7/0/0 |
| steps/发布/延后 | 127/37/90 | 72/23/49 |
| 执行边界/physics trace | 2286/127 | 1296/72 |
| 错误/判定 | binding_mismatch /FAIL | binding_mismatch /FAIL |

保持原ELF/ONNX、CV4、CPython1ms、mask0x10、15fps上限、latest_pending与原静止red_infantry显式scope。
二者均0开火、原源不变、owned资源clean；readiness是零图像/零推理准备，实际没有preserved native request，
POST_CLOSE_PIXEL_AUDIT明确false/No preserved native requests。不能说本轮完成了NN或真实像素绑定。
早停RTF不是10秒完整测量，诊断计时的额外开销也不能与无计时run视为受控性能对照。
02阶段计时250项完整/无丢弃，仅2个backend/schedule详细样本；最长step53.8615ms。
CPU时间原15.625ms量化保留，不能据短CPU零值或wall差值定GIL/CPU根因。

复现专项与检查：

```powershell
.venv-sim/Scripts/python.exe -m pytest -q tests/test_telemetry_cadence.py
.venv-sim/Scripts/python.exe tools/check_project.py --out artifacts/YOUR_FRESH_QUALITY
```

实际启动argv、driver、输入原字节、阶段原记录和失败结果随归档保存。
同一诊断入口tools/smoke_wsl_native_live.py增加显式--telemetry-publish-interval-ms 20；
无--run仅打印计划，需要本地原spec/ELF/模型和客户端目录才能运行，归档不发布这些二进制或私有SDK账本。
最终QA01四阶段退出0：3422pass/45skip/6既有warnings/1024subtests；pytest285.33秒，driver445.6073199秒/exit0/reaped。
494个程序/测试/补丁输入与17894项Git已知输入前后逐SHA相同；两次实际启动使用同一最终程序输入。
QA后仅补记本README、进度表和永久归档/索引，执行程序与DEVELOPMENT原已检验字节保持；
不声称新增结果文档/归档参加此前QA。冻结期间的两份文档原字节也已归档。

本次归档2072条原路径记录、570份唯一payload，2,722,200字节。
[MANIFEST.json](MANIFEST.json)映射原路径/SHA与[records.tar.gz](records.tar.gz)内容寻址payload，逐项解压核验。
本轮完整BGR归档与Git样本均为0；两个实际pixel audit失败原件保留。私有SDK/admission/owner账本6项留本地，以SHA列出。
records.tar.gz SHA256：`bad6d70fa06dd86f7c52b4568045454021a534ffd8c036ff84f9f10a6fcb622c`。
[FILES.json](FILES.json)固定包内文件SHA，不自引用。
