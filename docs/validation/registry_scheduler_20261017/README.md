# 注册调度元数据与实际流水线诊断

2026-10-17（UTC+8），父提交e34fa5774ee39859719c88878dfbf2786bfade1f，开发分支work/plan-t01-t03。没有调用子代理。

只读缓存仅包含注册时确定的required_sensors tuple、observation_profile、schedule_on_camera_frame及原max_camera_age_sim_s/max_camera_age_wall_s。
固定字段与原descriptor同一份注册输入，存于同一AdapterSpec；跨插件的注册事务仍原子发布既有spec/capabilities。
完整公共get/descriptors仍detach，业务能力与协议不扩展；覆写get的Registry子类、duck registry和非常规元数据继续原live get路径。
本车传感器、帧身份、租约/activation、当前源角度与原截止均不缓存、不延期，逐次原执行守卫保留。

## 微基准与测试

实际注册T2描述为2839 JSON字节；无GL/物理/NN，仅重复同帧调度检查。6000次ABBA：public_copy161.0095ms、frozen13.0227ms、frozen11.9594ms、public_copy160.5232ms。
只是该路径开销下降，不能作为物理RTF或原生实时通过，更不能证明性能退化根因。
新增16项测试；首轮48pass/1fail（fixture相机缺max_views），修正fixture后49pass/21subtests。
专项最终609pass/119subtests/2既有warnings，31.16秒pytest，driver31.7472472秒，exit0/reaped、502项程序/测试/补丁输入前后相同。
覆盖公共可变数据隔离、只读元数据、缺省/非常规值、动态get与duck兼容、staged spec发布、同帧去重、原150ms失效换代与未激活重绑。

## 真实诊断与失败

| 运行 | 配置与结果 | 边界 |
| --- | --- | --- |
| manual01–04 | 六车dt.002，gravity servo/gain4，手控SDK；相机关/开/开/关RTF0.999802/0.999909/0.999184/0.999940，均clean无错误 | 无adapter/NN/Qt，仅物理与相机隔离；两组实际NVIDIA GL |
| cProfile01 | 实际原T2/GL准备，额外cProfile包装；RTF0.596253，物理约.815秒后binding_mismatch，native结果0，clean | 存在额外开销及其他线程帧，不能当作独占authority分析或实时资格；未使用其数据认定瓶颈根因 |
| native01 | 原1ms switch、mask0x10、无可选计时，RTF0.8947118172，147raw/99及时结果/46独立执行，fire0、clean、errors[] | 唯一失败physics_rtf；原像素绑定、80/150ms、请求归账与目标物理运动证明通过 |
| native02 | 同程序，仅显式switch0.1ms，RTF0.6554832437，33raw/2及时结果/0执行，约2.215秒后binding_mismatch退出，fire0、clean | 多项失败，全部原判保留；原设置成功恢复，没有将0.1ms设为默认或放宽期限 |

无包装native01/02与专项focus01使用相同502项程序/测试/补丁输入。最终测试fixture修正另记。cProfile包装及手控脚本另保存完整原/执行字节，不混为生产源码资格。
native两次均FAIL；手控正常不能替代完整自瞄实时通过。native01证明目标运动时间内原指令执行，仍不证明T2识别/跟踪特定对象。
控制方向/目标关联、PnP精度、遮挡重捕获、射击、可见Qt、多车、完整3v3、7v7、Windows native/换机/LAN均不因此验收。

原T2 CPU4 ELF SHA256：67819b6812c2c4a87e2b411eed49c1e01cfb67212efdd2f2e0abd2aa3a963dec。
ONNX SHA256：b53470b42a5778aca8f3382ebe3c623482599cbf8ebad2e9a0dcc0c7f42c9255。没有重建/替换/训练。
实际1440×1080/15总fps/1view、原相机K/D与光学、六车dt.002、stationary red_infantry scope、对方vy.08手控fixture。
private像素为真实RGB→BGR，pybase64_1_5_1，80ms图像/150ms控制/0.98RTF均保持。对方手控运动不计自主导航或决策。

## 复现

微基准完整driver与输入快照在归档原artifacts/registry-scheduler-benchmark-20261017-01目录映射下；不启动原生进程或渲染器。
回归：python -m pytest -q tests/test_registry_scheduling_metadata.py rm_match/platform_v2/test_registry_hotpath.py tests/test_robotio_registration_races.py tests/test_navigation_runtime.py。
真实native完整命令在每轮driver的COMMAND.json；本机原spec/原客户端准备完成后，可使用：

```powershell
.venv-sim/Scripts/python.exe -X utf8 tools/smoke_wsl_native_live.py --run --native-transport wsl_async_bgr_v3 --private-native-pixels --raw-base64-codec pybase64_1_5_1 --linux-native-spec artifacts/native-production-cpu4-build-20261014/operator_source.local.json --client-root external/polar-rm-client-aim-reference-review --client-patch-manifest client_patches/CLIENT_AIM_REFERENCE_PATCH_MANIFEST.json --out artifacts/FRESH_NATIVE_OUT --host-opencv-threads 4 --host-python-switch-interval-ms 1 --authority-affinity-mask 0x10 --seconds 10 --native-robot-scope examples/native_robot_scope.json --robot-id red_infantry --camera-capture-policy latest_pending --telemetry-publish-interval-ms 20 --gimbal-servo position_gravity_v1 --gimbal-yaw-gain 4 --moving-target-vy-mps 0.08
```

02仅将显式switch改为0.1并使用新out；它是失败对照，不是推荐配置。所有输出新建，不覆盖原失败，不刷新旧时间戳。
完整BGR与私有账本留本地；永久包将记录代码、实际结果、失败和每个有帧运行的一份实际BGR。模型/ELF、私有credential不随证据发布。
全量QA结果与归档SHA待执行后补记；不以此前测试或历史pass代替本轮。

全量QA01在静态接口阶段出现1个旧测试失败（161项中1个subtest）；旧fixture直接修改已注册内部descriptor，与只读元数据不一致。
现改为按每个变体通过公开Registry.register注册相机/自定义传感器profile，原采样与期限断言不变；针对性31项/3subtests通过。
QA01及首次49项的fixture失败原日志均保留。生产adapters.py/runtime.py自native01/02后未改；仅该测试fixture和DEVELOPMENT归因记录增补，不能称全部502项输入与native完全相同。
手控与cProfile诊断使用修改前e34fa57生产源，源快照分开保留；无包装native使用本轮调度优化源；后续全量QA02待执行。

最终QA02四阶段退出0：3529 passed, 45 skipped, 6 warnings, 1024 subtests passed in 167.70s (0:02:47)。driver212.8633324秒/exit0/reaped。
502项程序/测试/补丁输入及17922项Git已知输入在QA02期间前后逐SHA相同；最终专项624pass/122subtests/2既有warnings，driver23.9851011秒。
native01/02的生产runtime/adapters及其他程序与最终QA逐SHA相同，仅测试fixture test_observation_refresh.py和DEVELOPMENT归因记录两项不同；不把整个输入集合说成相同。
QA01静态接口161项中的camera subtest失败原记录保留；最终fixture用公开注册声明，不降低原采样/期限断言。
QA后仅补记结果文档、归档及索引；冻结期间四份文档原字节归档，最后的结果/归档增补未参加此前QA。
永久归档3691条记录、648份唯一payload、4,846,821字节；160份完整实际BGR留本地，Git取2份样本，13项私有账本只列SHA。
records.tar.gz SHA256：`d0fea92d39667d1654615d5eddb44e9a4dfae02f33c45ddc84c7b9b9c193830a`。
