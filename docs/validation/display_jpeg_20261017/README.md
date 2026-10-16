# 显示JPEG85编码与外部线程采样

2026-10-17（UTC+8），父提交e63ed3b108415f5aa6e9f066da783f096b51f9b1，work/plan-t01-t03。未调用子代理。

## 证据驱动的修改

外部py-spy 0.4.2对本聊天独自启动的真实T2宿主进程采样8秒，100Hz/threads/gil/nonblocking，不取locals、不挂起进程或改算法。551条GIL样本/79次栈采样错误；291条物理authority、66条显示编码、59条证据写盘、48条相机、29条适配线程等。
这是有丢样的诊断提示，不能解释为精确CPU时长、GIL等待比例或完整根因。wrapper只记录本机实际PID再runpy执行原smoke，执行源、argv和包装完整保存；附加采样运行不当作无包装生产验收。
该真实T2采样运行RTF0.9193551814、147raw/53及时结果/21独立执行、clean/errors[]，仍因RTF失败；没有因局部动作而关闭完整自瞄。
控制对象重建、证据写盘与各原安全边界未改，本轮仅对显示编码这个热点做限定改动。

新增显式`--display-jpeg-codec opencv_jpeg85_v1`，`pillow_jpeg85`仍是默认。cv2.cvtColor把同一显示RGB副本转换为BGR，cv2.imencode质量保持85，返回仍是原base64 JPEG DTO和原capture身份，2MiB上限不变。
没有resize/降质量/降fps；原生算法始终获得原封存RGB→BGR，与JPEG显示编码分离。失败只设置display_error，不清除/替换原native/raw缓存；编码期间停止/撤权仍拒绝旧显示帧，不重盖捕获戳。
新codec初始化显式加载OpenCV，不自动回退；源/版本/成功显示帧及配置匹配由诊断报告记录。CLI非默认选项必须同时启用camera。

参考[py-spy官方说明](https://github.com/benfred/py-spy)的外部采样及非阻塞风险；
[OpenCV Python绑定源](https://github.com/opencv/opencv/blob/5.x/modules/python/src2/cv2_util.hpp)展示PyAllowThreads/ERRWRAP2释放并恢复Python线程状态。
这些文档不能替代本地实测；不把JPEG局部耗时下降当作完整GIL问题已经解决。
py-spy工具只下载到ignored artifacts，未修改生产venv或依赖；PyPI wheel SHA256 `8b06a353c177677e4e1701b288d8c58e2f8d4208ee81a8048d9f72ba800918f8`，exe SHA `6e83ab095f40453742d01a2719a178f308534015da519ec0659d2584139dc995`；源码/公开URL/版本与原MIT元数据本地保留，Git不分发工具二进制。

## 有限画面/编码检查

初步probe选采样运行的3个实际BGR帧，独立Pillow参考与候选OpenCV得到完全相同JPEG字节/解码像素，尺寸1440×1080；无竞争20帧旧约73–77ms、新51–54ms，仅codec路径微基准。
最终verify直接调用本次生产encode_display_jpeg并用独立原Pillow参考，另选native03的首/中/末3实际BGR；JPEG原字节相同，RGB输入不变，20帧ABBA旧76.9–89.4ms、新53.8–61.2ms。源码前后SHA/原OpenCV线程数恢复保留，不含NN/GL/物理RTF验收。
新23项检查包括1440×1080红/蓝/梯度/噪声/反向stride、原JPEG85字节、颜色通道、容量、未知codec、cv2失败不回退、显示故障不污染raw/native、停止中发布拒绝、原帧身份及严格分类。专项420pass/10skip/1既有warning/57subtests。
这些相同字节结果限本机当前pinned OpenCV/Pillow库，不承诺所有JPEG库/硬件版本均字节相同。

## 原门限下的实际T2全部失败

三次无额外Python包装/外部采样的原smoke串行比较，只切换显示codec；其余CPU4自有T2 ELF/ONNX、原第六Qt源/patch身份、公开近距离场景、六车2ms、NVIDIA1440×1080/15总fps、CV4/Python1ms/authority0x10、raw pybase641.5.1、原stationary red_infantry scope、gravity/yawgain4和对方SDK手控vy.08保持。

| native | 显示codec | RTF | 及时结果 | 独立执行 | JPEG均值/P95 ms | clean | 整体 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 01 | OpenCV85 | 0.9601927986 | 48 | 16 | 7.10 / 11.74 | true | FAIL |
| 02 | Pillow85 | 0.8621322709 | 20 | 8 | 11.73 / 16.43 | true | FAIL |
| 03 | OpenCV85 | 0.9653951923 | 14 | 1 | 8.17 / 12.54 | true | FAIL |

raw148/147/148；01/03成功显示147帧，原像素/80ms/150ms/归账及禁射门保持。01仅physics_rtf失败；02/03还失败最低10执行帧与对应运动证明。全部errors[]/fire0/clean，旧失败原判保留。
本次两次OpenCV的物理RTF及显示局部计时较Pillow对照好，但及时动作在复测退化；该短序列没有隔离所有系统负载、实际云台/图像轨迹差异，不证明稳定因果或完整改善。默认不切换，也不通过重复跑取最好成绩来签收。
原80ms图像、150ms控制与RTF0.98不变；对方移动仍是原SDK手控fixture，不是自主导航/决策；没有目标真值、旧帧时间戳修饰或像素代打。
ELF SHA256 `67819b6812c2c4a87e2b411eed49c1e01cfb67212efdd2f2e0abd2aa3a963dec`，ONNX `b53470b42a5778aca8f3382ebe3c623482599cbf8ebad2e9a0dcc0c7f42c9255`。

## 复现

```powershell
.venv-sim/Scripts/python.exe -X utf8 -m pytest -q tests/test_display_jpeg_codec.py rm_match/platform_v2/test_camera.py rm_match/platform_v2/test_native_early_pixels.py
.venv-sim/Scripts/python.exe -X utf8 tools/smoke_wsl_native_live.py --run --native-transport wsl_async_bgr_v3 --private-native-pixels --raw-base64-codec pybase64_1_5_1 --linux-native-spec artifacts/native-production-cpu4-build-20261014/operator_source.local.json --client-root external/polar-rm-client-aim-reference-review --client-patch-manifest client_patches/CLIENT_AIM_REFERENCE_PATCH_MANIFEST.json --out artifacts/FRESH_DISPLAY_JPEG --host-opencv-threads 4 --host-python-switch-interval-ms 1 --authority-affinity-mask 0x10 --seconds 10 --native-robot-scope examples/native_robot_scope.json --robot-id red_infantry --camera-capture-policy latest_pending --telemetry-publish-interval-ms 20 --gimbal-servo position_gravity_v1 --gimbal-yaw-gain 4 --moving-target-vy-mps .08 --camera-renderer-mode thread --display-jpeg-codec opencv_jpeg85_v1
```

切换Pillow仅改显示codec，使用新输出目录并串行运行。外部采样wrapper、原始stacks、错误、source/argv/actual PID和工具来源在归档中；没有局部变量转储或他人进程采样。
实际完整BGR留本地，Git每个native运行选1个实际样本，私有admission/SDK/owner账本只记SHA。所有M0–M5开放，目标关联/精度/重捕获/射击、可见Qt、多实现/多车和3v3/7v7仍未验。
全量QA/归档结果见最终补记；没有模型训练、真实硬件、主分支合并或发布。

最终QA01四阶段退出0：3631 passed, 46 skipped, 6 warnings, 1024 subtests passed in 162.20s (0:02:42)。driver 215.64897719999863秒/exit0/reaped；507项程序/测试/补丁输入与17939项Git已知全树输入在QA期间前后逐SHA相同。
最终专项420pass/10skip/1既有warning/57subtests，driver 25.060204100000192秒/exit0/reaped；专项、三次无包装native与QA的完整程序集逐SHA相同。最终实际JPEG-helper验证5个输入SHA与QA对应项相同，原线程数恢复；codec微基准不替实时资格。
QA后原事件聚合：03的14条native_result为tracking=true5条/false9条，另有114条async_pending、99条async_late_discard，最终1独立执行帧。聚合不是逐身份的因果解释；下一步应按原request/frame/deadline区分未跟踪、到期丢弃及最终守卫撤销，不能靠保持旧输出或刷新时间戳补足执行。该离线只读分析helper初次目录定位错误亦保留，修正后未改仿真/测试源码。
QA后仅增补结果文档/永久归档/索引；四份pre-QA文档原字节亦归档；最终结果增补未参加此前QA。三次实际T2与外部采样全部仍FAIL，及时执行复测退化，M0–M5、完整目标精度/关联/射击、GUI、多车与比赛未关闭。
永久归档3243条记录/649份唯一payload，5087177字节；523份完整实际BGR留本地，Git取4个真实样本，12项私有账本只记SHA。
records.tar.gz SHA256：`a91d6dda7fe06e3553193d22bcf12a8e3c8de3b4943972895ef8a9f5a7e96b0f`。
