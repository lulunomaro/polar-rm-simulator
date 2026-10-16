# 批量基础range与完整流水线隔离

2026-10-17（UTC+8），父提交19b29aa962a2871885c08f7a979e322d79317106，分支work/plan-t01-t03；未调用子代理。

## 修复与证据范围

MatchSimulation.scan原每次64次mj_ray，现64个原标量cos/sin方向用一次mj_multiRay；保留group0、静态几何、自车body排除与原8m饱和。cutoff无限，避免提前几何裁剪改变最近交点；没有降低射线数、移除传感器、缓存旧采样或输入真值。
qpos/qvel/ctrl、2ms物理步、相机分辨率/K/D、15fps上限、80ms图像/150ms输入/0.98RTF均保持，原T2/ONNX不变。
此为基础64线range优化，不等同MID360点云优化、导航完成、视觉精度或整套实时修复。

官方[批量射线API](https://mujoco.readthedocs.io/en/stable/APIreference/APIfunctions.html#mj-multiray)声明同源多射线与nearest-hit语义；
[Python绑定](https://mujoco.readthedocs.io/en/stable/python.html#functions)说明每次C调用期间释放GIL。
本机pinned MuJoCo3.15.0绑定签名与实际调用均验证；受控竞争结果是该路径墙钟测量，不是对整套GIL等待的推定。

36组原型6车/6yaw与旧单射线逐值相等（max_abs=0）；受控ABBA 30次：
无竞争旧21.0200/21.1832ms，新8.7136/7.9508ms；有竞争旧2.5023003/1.4640481秒，新0.0520843/0.0510279秒。
新增46项实际ray回归，包含原API逐射线独立参考、7个平移点、64方向/过滤/自车排除/无限cutoff、无命中/8m饱和、真实运动/重置、不改状态与观测来源。
初步65pass/9subtests；最终专项689pass/131subtests/2既有warnings，pytest28.58秒、driver29.2386000秒/exit0/reaped，503项程序/测试/补丁输入前后相同。

## 无推理隔离与额外计时

在修改前19b29aa源使用与native相同公开初始场景，关闭NN但保留NVIDIA相机/六车2ms/gravity/gain4/手控SDK：
目标静止/运动/运动/静止的RTF0.999869/0.999967/0.998435/0.999929，均clean/errors[]，ncon最大4、solver迭代最大1。
不能把此结果算作原生自瞄、目标跟踪、导航/决策、GUI或完整比赛。

旧源上每31步同线程QPC采样实际T2的SPARSE_DIAGNOSTIC：RTF0.807584，146raw/37及时结果/18执行、fire0/clean；唯一整体失败RTF。
131采样步中backend/engine平均包含耗时1.797/1.651ms、mj_step/mj_forward为0.381/0.219ms；记录含包装与其他线程竞争，嵌套span重叠，不能相加或推算独占CPU/GIL等待。
同线程CPU总量5.1875秒为整段run（含cleanup），短span的Windows线程CPU量化不能用来精确定位等待。
scalar/fancy actuator写入的有/无竞争ABBA没有稳定收益，未据此修改执行器路径。

## 原T2实际结果全部失败

无额外包装native01：RTF0.6112374231，145raw/52及时结果/19独立执行，fire0、errors[]、clean；原像素/80/150ms/请求归账与原motion证明通过，唯一失败physics_rtf。

实际T2传感器ABBA为诊断wrapper：仅将scan实现切换为父源原函数或当前批量函数，原函数及整份父源、当前源、wrapper完整保存。
旧/新/新/旧RTF为0.6316510693/0.6187944309/0.7814196162/0.5721164367，全部FAIL；第1次仅RTF，后三次还不足10执行帧/对应motion证明。
标准化wrapper的新实现轮也不当作无包装生产资格；旧实现轮EXECUTED_SOURCE记录当前文件但实际scan被覆盖，必须结合SENSOR_IMPLEMENTATION.json/old_scalar_function.py核验，不能仅看文件SHA或classify字段。
这些整体结果不能证明微基准速度收益已扩展到整套管线，也不能将首轮0.611回归单独归因批量射线。当前性能退化未解决，原失败不回写。

固定CPU4 T2 ELF SHA256 67819b6812c2c4a87e2b411eed49c1e01cfb67212efdd2f2e0abd2aa3a963dec，ONNX b53470b42a5778aca8f3382ebe3c623482599cbf8ebad2e9a0dcc0c7f42c9255。
客户端第六patched source/manifest身份、pybase64_1_5_1、CV4、Python1ms、authority0x10和stationary red_infantry原scope保持。
对方vy.08为原150ms ControlPlane手控fixture，仅评测使用其真实位姿；没有向算法传目标真值，不算自主导航/决策。
当前Windows记录LastBootUpTime为2026-10-17 02:48:56，晚于此前部分历史记录；只作环境背景，不据此推断因果或继承历史通过。

## 复现

```powershell
.venv-sim/Scripts/python.exe -X utf8 -m pytest -q tests/test_batched_range_scan.py tests/test_core.py tests/test_navigation_sensors.py
.venv-sim/Scripts/python.exe -X utf8 tools/smoke_wsl_native_live.py --run --native-transport wsl_async_bgr_v3 --private-native-pixels --raw-base64-codec pybase64_1_5_1 --linux-native-spec artifacts/native-production-cpu4-build-20261014/operator_source.local.json --client-root external/polar-rm-client-aim-reference-review --client-patch-manifest client_patches/CLIENT_AIM_REFERENCE_PATCH_MANIFEST.json --out artifacts/FRESH_BATCH_SCAN_NATIVE --host-opencv-threads 4 --host-python-switch-interval-ms 1 --authority-affinity-mask 0x10 --seconds 10 --native-robot-scope examples/native_robot_scope.json --robot-id red_infantry --camera-capture-policy latest_pending --telemetry-publish-interval-ms 20 --gimbal-servo position_gravity_v1 --gimbal-yaw-gain 4 --moving-target-vy-mps 0.08
```

ABBA完整driver在归档run_ray_abba_20261017.py中，使用新输出目录；原/新函数只作受控传感器对照，绝不替换自瞄算法或修饰生产通过。
实际BGR全帧与私有账本留本地，永久包每个有native帧运行选一份实际BGR，SDK/admission/owner账本只列SHA；模型/ELF/clear credentials不发布。
本轮全量QA和归档已完成，具体数字及SHA见下方最终补记；M0–M5未关闭，完整跟踪/射击/GUI/多车/3v3及7v7均未验收。

最终QA01四阶段退出0：3575 passed, 45 skipped, 6 warnings, 1024 subtests passed in 166.41s (0:02:46)。driver244.4020972秒/exit0/reaped。
503项程序/测试/补丁输入及17927项Git已知输入在QA期间前后逐SHA相同；专项689pass/131subtests/2既有warnings、driver29.2386000秒，源与无包装native01完全相同。
QA结束后串行运行最终实际scan/独立原射线ABBA，4份程序输入前后SHA不变并与QA一致；36组逐值相同；Python1ms与单线程mask均成功恢复。无竞争旧[0.025352900000143563, 0.026895599999988917]秒、新[0.009682299999894894, 0.00944149999986621]秒；有竞争旧[2.5442957999998725, 1.8151100999998562]秒、新[0.05093620000025112, 0.0520833999999013]秒。
这些为range路径合成竞争结果，所有当前原生实时记录仍FAIL；不因此关闭跟踪/精度/射击、GUI、多车或M0–M5。
QA后仅补记结果文档、归档及索引；四份冻结文档原字节亦归档，最后的结果/归档增补未参加此前QA。
永久归档2302条记录、690份唯一payload、6,307,338字节；783份完整实际BGR留本地，Git取6份实际样本，22项私有账本只记SHA。
records.tar.gz SHA256：`ed60d665d55992a9758e8ed9a00fbe1efbf988344e4bf29b0cc7135a98cb2ea0`。
