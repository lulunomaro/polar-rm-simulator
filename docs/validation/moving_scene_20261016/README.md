# T02/T03/T06 移动场景诊断夹具与真实 T2 证据

2026-10-16，父提交6f3cbeb12e2576880c0171addf25bab02f3dcb1b，开发分支work/plan-t01-t03。未调用子代理。

新增可选`tools/smoke_wsl_native_live.py --moving-target-vy-mps 0.08`。
默认不运动，原静态计划保持相同；显式开启时由场景操作者仅申请对方步兵motion租约，
每40ms使用原ControlPlane新window和新seq发送本体横向速度，TTL150ms，每250ms续租。
仅允许有限且绝对值0.03..0.15m/s；不自动夺回失效控制权或跨episode重用输入。
既有初始场景设置完成后，只通过控制通道驱动实际物理，不再写qpos、ctrl或时间戳；结束释放会话。

TARGET_MOTION.json记录原window/ACK期限与每个2ms积分入口的motion消费回执、原sim_time、目标位置和速度。
这些真值只在隔离评测中使用，不新增到算法DTO、相机图像或原生输入。
按原capture_sim_time逐项连接真实图像和T2实际执行回执，要求物理移动至少0.15m、至少100个有效积分消费、
至少10个运动期间的独立原生执行帧，完整无丢样/错误消费且会话关闭。

**该连接只证明物理运动与原生执行在时间上重合，不能识别T2实际跟踪哪辆车。**
当前原生输出没有可核对的目标身份；对方确在移动，也不能据此保证其在图像中被正确持续跟踪。
分类使用`live_moving_scene_chain_qualified`，强制`moving_target_tracking_qualified=false`；
开启运动时不授予`live_static_chain_qualified`。目标关联、跟踪误差、遮挡/丢失重捕获、射击、
运动射手、多车算法、可见Qt、导航/决策和完整比赛均未验收；M0–M5不关闭。
该脚本手控夹具不替北极熊导航或比赛决策树。

## 四组真实10秒结果

| 本轮native | 场景 | 可选phase/authority计时 | physics RTF | raw/及时结果/独立执行帧 | 对方位移m | 最大执行wall age ms | 结果 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 01 | 移动场景 | 关闭 | 0.949280825 | 147/110/60 | 0.723964 | 79.1263 | 失败：RTF低于0.98 |
| 02 | 移动场景 | 开启 | 0.999954752 | 148/136/85 | 0.763964 | 78.8289 | 局部链路PASS |
| 03 | 移动场景 | 关闭 | 0.999037776 | 147/133/72 | 0.763324 | 77.3833 | 局部链路PASS |
| 04 | 静态对照 | 关闭 | 0.999630533 | 148/126/121 | — | 79.3425 | 局部链路PASS |

四组均为实际六车2ms物理、NVIDIA GL 1440×1080/15fps上限、原T2真实图像推理，原80ms图像/150ms控制窗口，
stationary red_infantry scope，CPU4 ELF/同一ONNX、CV4、CPython1ms、authority mask0x10，
latest_pending、显式20ms历史显示；无离线时钟、真值/PnP/像素/算法替换，无开火。
每轮原SDK授权、像素反查、原异步请求归账、source不变与owned清理通过，错误为空，fire_true=0。
从首曝光开始计数。02的phase/authority包装有诊断开销；03/04关闭额外包装，仍保留基础trace和运动审计。
02/03的目标积分回执5000/4996条全部原授权有效、丢样0、bad消费0；240/238个原window，
85/72个独立执行帧精确连接到原捕获时的实际运动样本。

01使用加入目标运动但尚未细分“场景/目标跟踪”标签的源快照，失败原记录不重写。
02–04使用相同最终程序集。01的RTF0.949281失败保留；02脚本控制夹具before_step中位0.0109ms、P95 0.0575ms，
backend_step中位0.62005ms、P95 3.121225ms。后续局部通过没有定位首轮波动根因，也不保证长期稳定。
这些源、ELF/模型、配置和时钟身份分别保留，不能把历史成功直接当作当前整场验收。

ELF SHA256 `67819b6812c2c4a87e2b411eed49c1e01cfb67212efdd2f2e0abd2aa3a963dec`；
ONNX SHA256 `b53470b42a5778aca8f3382ebe3c623482599cbf8ebad2e9a0dcc0c7f42c9255`。
模型/ELF不随证据归档发布。

## 复现与失败记录

需已有本地CPU4构建/spec、依赖、NVIDIA GL和第六客户端身份清单。默认调用仅打印计划，不启动GL/推理。
以下命令启动明确10秒、不开火的实时诊断，输出目录必须新建；用`--profile-authority --profile-phases`复现02额外计时条件。
移除`--moving-target-vy-mps 0.08`复现04的静态对照。使用用户自己的路径应重新记录身份与实际条件。

```powershell
.venv-sim/Scripts/python.exe -X utf8 tools/smoke_wsl_native_live.py `
  --run --native-transport wsl_async_bgr_v3 --private-native-pixels `
  --raw-base64-codec pybase64_1_5_1 `
  --linux-native-spec artifacts/native-production-cpu4-build-20261014/operator_source.local.json `
  --client-root external/polar-rm-client-aim-reference-review `
  --client-patch-manifest client_patches/CLIENT_AIM_REFERENCE_PATCH_MANIFEST.json `
  --host-opencv-threads 4 --host-python-switch-interval-ms 1 --authority-affinity-mask 0x10 `
  --seconds 10 --native-robot-scope examples/native_robot_scope.json --robot-id red_infantry `
  --camera-capture-policy latest_pending --telemetry-publish-interval-ms 20 `
  --moving-target-vy-mps 0.08 --out artifacts/my-fresh-moving-scene
```

新增23项回归覆盖实际MuJoCo物理、motion scope、原window/输入过期归零、错owner/epoch/seq/时间、
episode reset、释放、无效CLI提前拒绝及保守分类。测试中的原生回执头是合成的，只测试评测连接，不冒充真实推理。
初步139项有1失败/138通过：2.4秒实际位移0.143521643m不足0.15m；将测试运行改为3秒/1500步，保持阈值，
后续139项通过。完整专项488pass/98subtests、2既有warnings，driver13.5086853秒/exit0/reaped，497程序输入前后相同。
完整失败JUnit、通过日志、各轮原始计划/结果/全像素审计/源快照及驱动脚本均保留；01从未改写成PASS。
最终QA01四阶段退出0：3454pass/45skip/6既有warnings/1024subtests；pytest159.12秒，driver218.4420192秒/exit0/reaped。
497个程序/测试/补丁输入及17905项Git已知输入在QA期间前后逐SHA相同；真实native02–04与该程序集相同，01较早源/失败原记录分别保留。
QA后仅补记结果文档、永久归档和索引；程序及DEVELOPMENT维持已检验字节。冻结期间三份文档原字节归档，最后的结果/归档增补未参加此前QA，不把文档更新称为新一轮全树验收。

永久归档在本目录生成：内容寻址payload与原路径/SHA清单，完整BGR留本地、每轮取一个真实样本；
清晰credential及完整SDK/owner账本只在本地保留，清单记录其SHA。归档不是发布模型/程序包或完整比赛视频。

归档3152条记录、626份唯一payload、5,264,355字节；556份完整实际BGR留本地，Git取4份真实样本，12项私有账本只记录SHA。
records.tar.gz SHA256：`2c437b871a01163b73b4dab93c1adc714a1607f842a0b971f8609925554bc546`。
[MANIFEST.json](MANIFEST.json)映射原路径/SHA到[records.tar.gz](records.tar.gz)内容寻址payload，逐项解包核验；[FILES.json](FILES.json)固定包内文件SHA（不自引用）。
