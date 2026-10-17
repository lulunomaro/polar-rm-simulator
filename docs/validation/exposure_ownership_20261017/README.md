# 曝光所有权与晚物理调用门禁

2026-10-17 UTC+8，父提交14e12d25050ad3285ca86be697fc342b906a43e5，work/plan-t01-t03。

移除真实MuJoCo renderer在原浮点畸变映射输出后的多余RGB.copy；保留原float32 map、INTER_LINEAR、分辨率、颜色、曝光身份、原native/public编码及80ms图像/150ms控制/RTF0.98门限。
实际NVIDIA六车/步进/物理弹丸/重置8曝光：与同一次readback的原复制路径逐字节相同，后续曝光不覆盖旧帧；这是GL帧所有权与像素检查，不是NN/精度或实时验收。
固定点映射候选出现约288万通道差异/最大7级，初次严格断言失败及后续对照均保留，该候选未进入生产；packed float映射虽相同但微基准无稳定收益，也未采用。
两次真实T2仍FAIL：01 RTF0.943211/79及时结果/32预写入/30物理帧，出现1次entry及时但真实mj_step调用超期，已排除有效帧；新增严格no_late_physical_active_calls门禁防止好帧掩盖该问题。最终同源02 RTF0.865401/8及时结果/5预写入/4物理帧，晚调用0，仍不满足RTF/数量/运动证据。原01结果不重写，另存只读新门禁复核亦FAIL；波动未隔离，不能把局部复制移除宣称稳定整链提速。
保持六车2ms、NVIDIA1440×1080/15总fps、自有CPU4 ELF/ONNX、red_infantry静止scope、原SDK手控对方vy.08、gravity/yawgain4及OpenCV JPEG85；火控始终false。未调用子代理，未改模型/NN/Command/物理、未刷新旧时间戳、未输入目标真值，未训练/硬件/整场比赛。证据见[曝光所有权与物理调用门禁](validation/exposure_ownership_20261017/README.md)。

## 有限改动与拒绝的实验

原`SourceLensWarp.apply`每次调用实际cv2.remap得到独立拥有的连续RGB数组；renderer随后再次.copy一份同尺寸RGB，15fps下有重复分配/复制。生产只移除后一次copy，不改remap输入/映射/插值/边界/畸变或任何模型几何，不复用输出缓冲，原像素不可变snapshot仍单独创建。
12项新默认测试含四种stride/转置输入的源与前后输出不别名、真实renderer方法接复用readback数组验证旧曝光不变，及7种缺失/非法/非零late计数即拒绝分类。实际GL测试显式启用，最终13pass：8曝光覆盖六车、原步进、物理弹丸及episode重置，同一次GL读回分别取原复制参考与新输出，SHA逐字节相同；保留所有此前曝光，每次后续渲染检查不被覆盖，qpos/qvel/ctrl不变。它没有复跑两个GL画面再用容差掩盖差异，也没有把原参考copy加入无包装native。

本轮另试cv2.convertMaps CV_16SC2定点表示：实际OpenCV5.0.0对3个全分辨率噪声输入每个约288万通道不同，最大差6–7，原严格断言失败保留。候选从未写入rm_match源码。packed float map三图相同，但40帧ABBA约2.76/2.67/2.99/3.07ms，波动重叠，无稳定收益，亦未采用。原SourceCameraProfile/float maps文件保持逐字节原SHA。

## 真实T2与更严格的调用门禁

| 次数 | 源 | RTF | 及时native | 预写入 | 严格物理帧 | 晚活动调用 | 结论 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 01 | copy移除，追加调用门禁前 | 0.9432114252 | 79 | 32 | 30 | 1，事后原证据复核 | FAIL |
| 02 | 最终完整源 | 0.8654010876 | 8 | 5 | 4 | 0 | FAIL |

两轮均10秒/147原raw/clean/errors[]/fire0，原SDK admission/window原期限；01 136requests/135started，02 121requests/120started。无目标关联/跟踪保持率/命中精度证明；运动来自原lease手控fixture，不是自主导航/决策。浮点复制移除没有隔离系统负载/GIL/WSL/实际画面轨迹，不能将数值波动当作稳定提升或完成自瞄。

01的122个entry候选中1次真实call已过原wall期限，原统计正确排除该次，剩121次有效积分分属30frame；但原整体验收仅因RTF失败，未另将任一晚活动调用设为独立失败。现在增加`late_physical_active_calls`计数及`no_late_physical_active_calls`严格非bool整数0门禁：最终target仍有gimbal且真实call不在原原始曝光期限内时计数；不得用其他及时帧覆盖。字段缺失也拒绝。不修改物理Command或把逻辑entry样本冒称真实call；Python调度仍有entry→call空隙，未承诺硬实时保证。
01原RESULT保持原字节；`GATE_REVIEW.json`是原ledger证据在新分类器下的只读复核（RTF和晚调用双失败），不是再执行/过关。02为补充该门禁后的一次新真实运行，最终GL02/专项02/native02/QA逐SHA同源；第一轮GL/专项/native保留各自之前源码。没有反复跑到最好一次签收。

原ELF SHA67819b6812c2c4a87e2b411eed49c1e01cfb67212efdd2f2e0abd2aa3a963dec；ONNX b53470b42a5778aca8f3382ebe3c623482599cbf8ebad2e9a0dcc0c7f42c9255；客户端patch SHAf3d83e4d4584c7910958fda19f46dc310a310b8fb89376ebf5229a31b69bdf30。未构建替换算法。

最终专项503 passed/13 skipped/4既有warnings/57 subtests，27.32s；GL02 13pass/8曝光；退出0/reaped。两轮native exit2/reaped；失败和原输入保留。公开事件只选源身份/原时刻/预算/target及检查/本车ctrl；私有session/ledger不上传，仅SHA。完整真实BGR留本地并取真实样本到永久包；没有替代像素。

## 复现与尚未完成

归档driver COMMAND.json记录实际argv/环境和source快照；准备原本地spec/ELF/模型/审查客户端后，以`.venv-sim/Scripts/python.exe -X utf8 artifacts/run_exposure_ownership_20261017.py --mode equivalence --attempt <fresh>`跑显式NVIDIA检查，`--mode focus`跑专项，`--mode native`跑真实10秒，`--mode quality`跑四阶段全量。必须串行，选择新目录，QA期间冻结Git已知输入。没有依赖则按公开部署文档构建，本机私有路径不是换机交付承诺。
本轮关闭局部冗余copy/证据分类问题，未关闭完整M1。真实动态目标关联/精度/遮挡/重捕获/射击、第二自瞄完整接入、导航决策全树、GUI、多机LAN、真实资产、3v3/7v7/整场回放与换机/Windows native仍按总进度表分别未验收；M0–M5无完整签收，HIL未启动。

最终QA01四阶段退出0：3677 passed, 47 skipped, 6 warnings, 1024 subtests passed in 172.84s (0:02:52)。driver 223.32034099999873秒/exit0/reaped；509项程序/测试/补丁输入与17949项Git已知全树输入在QA期间前后逐SHA相同。最终GL02、专项02、真实native02与QA的程序输入完全相同；各01保留此前原源，不继承新门禁。新增测试不代表native/比赛验收通过。
QA后仅补记文档与永久归档/索引，四份pre-QA文档原字节另存归档；结果增补本身未参加先前QA。当前T2仍FAIL，M0–M5未关闭；未调用子代理。
永久归档3708记录/625唯一payload，4251989字节；257个实际BGR留本地，Git取2个真实样本；私有账本仅SHA。records.tar.gz SHA256：`a5bf4bc357b9e8011d50774325734df688d193749b816012a36e1e7cfe94f6f6`。
