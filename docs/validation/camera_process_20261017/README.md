# 相机进程隔离与WSL清理证明共享锁

2026-10-17（UTC+8），父提交39257f73b2f10dc53379a649c01d1f5821c5da52，work/plan-t01-t03。未调用子代理。

## 修改与边界

显式`--camera-renderer-mode owned_process_v1`把同一MuJoCo模型/SourceLensWarp渲染放入owned本地子进程，默认thread不变。
固定Python模块argv、无shell/任意可执行路径；MJB SHA握手、原capture积分状态、独立MjData、逐请求/帧身份与RGB长度检查；单请求在途、有界header16KiB/payload64MiB。
初始化最多15秒、单次IPC最多0.5秒是资源响应上限，绝不是算法图像有效期；原80ms曝光/150ms控制窗口、队列、权限/过期/撤权守卫均继续检查原捕获戳。
CameraProvider仍由authority复制真实数据；渲染进程是仿真内部受信组件，其世界快照不暴露给算法；只有真实RGB进入原有seal与RGB→BGR链。
进程使用原OwnedJsonProcess/Windows Job或Linux owned group，故障/取消终止本进程组、解除阻塞管道、join I/O线程并保存回收证明；不能证明就报错，不杀其他进程或整个WSL发行版。
新模式仅本机role_v23的六车样本有证据，未经验证的新模型、插件/回调、设备/跨机不能自动称兼容；它不是已证实的性能修复。

依据MuJoCo[状态与积分](https://mujoco.readthedocs.io/en/stable/computation/index.html#the-state)和[保存模型/状态API](https://mujoco.readthedocs.io/en/stable/APIreference/APIfunctions.html#mj-savemodel)，使用同一MJB和mjSTATE_INTEGRATION恢复后mj_forward；实际几何SHA用于核对当前场景，不能用文档代替实测。

## 原失败和图像保真

equivalence01/02严格RGB逐字节检查在第4样本失败（1个通道/1级）；第二轮重复同输入的原renderer本身也变化1个通道/1级。没有删除或改判原失败。
equivalence03/04改为明确的保真诊断：几何数组SHA严格相等，RGB最多1级/32个通道变化上界；03实测第4样本4通道/1级，其余7个样本逐字节相同。最终04实际值保存在原stdout。
该检查覆盖6车相机、真实物理步进、物理弹丸图元与reset；qpos/qvel/ctrl不被渲染器修改。实际native仍逐帧使用精确原像素SHA，不放宽原图像/请求审计或视觉得分门限。
focus01暴露旧__new__测试fixture缺renderer_mode，_loop用兼容的默认thread读取后原断言通过，原8个失败保留。

## 实际T2全部失败

保持原CPU4 T2 ELF/ONNX、同一公开近距离诊断场景、六车2ms、NVIDIA1440×1080/15总fps、CV4/Python1ms/authority0x10、pybase641.5.1、原第六客户端patch身份、stationary red_infantry scope、gravity/yawgain4和对方原SDK手控vy.08。
对方手控移动不是队伍导航/决策；fire始终0。没有新旧瞄准算法混用、真值输入或补帧/改曝光戳。

| native | 相机 | RTF | 及时native结果 | 独立执行帧 | clean | 整体 |
| --- | --- | --- | --- | --- | --- | --- |
| 01 | 独立进程 | 0.6515205954 | 13 | 5 | false | FAIL |
| 02 | 原thread | 0.7854452615 | 17 | 5 | true | FAIL |
| 03 | 独立进程 | 0.7687280009 | 16 | 4 | true | FAIL |

01 raw145、02/03 raw146。01同时失败请求完整归账/清理及运动期间执行证明；02/03仅RTF、至少10执行帧和对应运动证明失败，原80/150ms/精确像素、请求归账及禁射等守卫保持。
01是WSL退出竞态修复前；02/03的生产程序相同，之后仅补充test_camera_process.py中的分类负例。没有因源测试补充继承旧通过或宣称第二模式提速。
固定ELF SHA256 `67819b6812c2c4a87e2b411eed49c1e01cfb67212efdd2f2e0abd2aa3a963dec`；ONNX `b53470b42a5778aca8f3382ebe3c623482599cbf8ebad2e9a0dcc0c7f42c9255`。

## 清理证明修复

native01原closed事件记录CLEANUP.json PermissionError，随后磁盘原Linux证明显示reaped/group_empty/tmpfs_removed；旧host失败仍保留，未事后改判clean。
原close逻辑在文件出现后立即读取，异常会跳过child.wait并提前杀host launcher。现在仅针对PermissionError在原1.3秒总预算/原最后0.1秒资源保留内重试；不捕获非法JSON/身份错误，永久拒绝仍失败且sticky。
测试覆盖真实Windows CreateFileW独占共享锁释放、3次模拟短锁、非法JSON、错误owner、永久拒绝与原owned管道回收；这不更改任何推理接受时钟或租约。
修复后两次actual native严格清理均通过，进程模式另有自己的Job回收/IO线程退出证明。

## 复现

```powershell
$env:POLAR_TEST_CAMERA_PROCESS='1'
.venv-sim/Scripts/python.exe -X utf8 -m pytest -q -s tests/test_camera_process.py tests/test_wsl_cleanup_read_race.py
Remove-Item Env:POLAR_TEST_CAMERA_PROCESS
.venv-sim/Scripts/python.exe -X utf8 tools/smoke_wsl_native_live.py --run --native-transport wsl_async_bgr_v3 --private-native-pixels --raw-base64-codec pybase64_1_5_1 --linux-native-spec artifacts/native-production-cpu4-build-20261014/operator_source.local.json --client-root external/polar-rm-client-aim-reference-review --client-patch-manifest client_patches/CLIENT_AIM_REFERENCE_PATCH_MANIFEST.json --out artifacts/FRESH_CAMERA_PROCESS --host-opencv-threads 4 --host-python-switch-interval-ms 1 --authority-affinity-mask 0x10 --seconds 10 --native-robot-scope examples/native_robot_scope.json --robot-id red_infantry --camera-capture-policy latest_pending --telemetry-publish-interval-ms 20 --gimbal-servo position_gravity_v1 --gimbal-yaw-gain 4 --moving-target-vy-mps .08 --camera-renderer-mode owned_process_v1
```

若需对照仅把renderer-mode显式选thread；使用新输出目录，串行运行，保留每次原始失败。
本轮完整QA与归档结果随后补记；单元/合成/真实渲染/真实短时native分开列证，所有M0–M5仍开放，目标关联/精度/重捕获/射击、可见Qt、多实现、多车/3v3/7v7未验。

最终QA01四阶段退出0：3608 passed, 46 skipped, 6 warnings, 1024 subtests passed in 163.55s (0:02:43)。driver 220.70395029999963秒/exit0/reaped；506项程序/测试/补丁输入与17934项Git已知全树输入在QA期间前后逐SHA相同。
最终专项focus03与QA的完整程序集相同：385pass/3skip/1既有warning/51subtests，driver 21.89011859999846秒/exit0/reaped。native02/03与QA仅测试分类负例字节不同，生产代码相同；两次原生均FAIL，未继承资格。
最终equivalence04：8个样本几何逐SHA相同，RGB不同通道数[0, 0, 0, 1, 0, 0, 0, 0]，每个样本最大通道误差[0, 0, 0, 1, 0, 0, 0, 0]；该源与QA只差其后新增分类负例，不冒充逐RGB字节全部相同。
QA后仅补记结果文档/永久归档/索引；四份pre-QA文档原字节保留在归档；最终结果增补未参加此前QA。所有M0–M5未关闭，独立渲染未证实实时收益、目标精度/关联/射击/可见Qt/多车和比赛仍未验。
永久归档5742条记录/650份唯一payload，4874300字节；372份完整实际BGR留本地，Git取3个真实样本，9项私有账本仅记SHA。
records.tar.gz SHA256：`8d45151f160a51df6fa11c5c472f48962c9a08444ce9a105465b7c101ed0892c`。
