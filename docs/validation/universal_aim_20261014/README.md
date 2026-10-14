# 通用自瞄、真实模型准备与首批实时返回证据

本包保留不同时间、源码和证据级别的独立实验。它不覆盖旧验证包，不把 prepare/单元/离线结果写成实时或完整比赛通过。`INDEX.tsv` 对应原路径；`PRESERVATION_MANIFEST.json` 对每份原件和存储件列 SHA/大小，大件 gzip mtime=0，可还原原字节。运行 `python verify_archive.py` 只校验字节，不启动算法。模型、ELF、依赖 prefix、私有凭据和 admission manifest 不发布。

| 证据组 | 实际范围 |
|---|---|
| peer / actual / stderr | 通用能力协议及进程生命周期；WSL 两项真实无害进程测试；stderr 修复80pass/4skip/2subs。没有 NN/ROS/物理资格。 |
| cpu4 / cpu4drv / threads | 原 T2 新 CPU4 构建29个TU与链接，实际589.292s；明确配置/实际属性、原模型和 source composition 身份。没有 NN 预热，不能把旧 spec 42 元数据重写为新构建。 |
| ov4 / ov4drv | 八份独立保存帧实际推理，CPU16四份总时延P50 41.145ms/max68.731，CPU4四份37.163/max40.608；这是离线诊断，不是实时或统计保证。 |
| hostcv / mount / status | 线程 API、源上下文/进度合同；静态仿真云台运动学标定。没有实物工业相机标定或 ROS 动态 TF 实测。 |
| tjbuild / tjerr / tjstart / tjreset / tjready | 同济原源 fresh04 的19步构建；首监督器Python缺NumPy无HELLO失败原样保留；fresh02显式venv后实际原模型prepare 4.033s、原2s reset实际12.039ms、清理clean。零图像/零NN，不称检测或闭环通过。 |
| pbsource / pbtool / pbretry / pbpre1 / pbdep1 / pbdep2 / pbbooterr | PB03 source carrier、原配置、失败弹道解安全边界；缺image_transport_plugins、下载HTTP超时与entry bootstrap首错保留。signed同资产HTTPS deps02实际成功，不表示整套prefix独立闭包或ROS节点已运行。 |
| asyncunit / asyncerr / async2 / asynctime | 单原T2 compute异步进度；旧cold结果只按原帧丢弃，pending无角度。async01证据队列满/清理失败；根修容量前检查和原1.5s收尾后async02无sticky fault、像素完整、清理clean。 |
| qa1 / qadrv1 | 本次冻结全量QA：1644pass、39明确skip、1008subtests、6已有warnings，四步骤0，source unchanged；其后工具bootstrap有独立21项验证，不把它赋为旧QA源码。 |
| qa2 / qadrv2 | 最终代码全量QA：1648pass、39明确skip、1008subtests、6已有warnings，四步骤0/source unchanged；pytest128.12s、driver155.198s且reaped。之后只更新文档、证据与ignored本机注册探针，不替旧QA改写身份。 |
| opencv / pbpre4 / pbbld | 原系统OpenCV配置/头文件/库SHA与ldd前后核验；实际preflight04及七包colcon编译/链接通过，driver325.824s且reaped/source unchanged；原模型/labels与节点ELF/ldd实际核对。零节点运行/零NN，没有ROS图像闭环资格。 |
| pbprobe | 该构建后的Windows→Ubuntu-22.04实际三节点prepare 10.179s、原context reset 52.627ms和全树clean；零图像/零act/零NN，无预造generation。仅资源/复位资格，未持SDK租约，不是80ms实时自瞄或整场通过。 |
| mechanical | 从async02原ledger独立读取3个物理actuator receipt；实际pitch反馈约−0.0242→−0.0440→−0.0650rad，ctrl来自算法约−0.136rad。是关节执行/反馈证据，不是完成跟踪精度或实时性能验收。 |

async02实际10s墙钟，148raw，67原事务、66完整stdin ACK、65原模型NN stdout（末次inference_calls=65），一个退出时取消不计NN。5帧在原80ms内返回、3个独立新帧由物理关节消费，fire=0，all original transactions accounted、无adapter fault、shutdown clean；物理RTF0.547499，故整体FAIL。不能把60条late事件与6条stdout相加当66次独立输出：一条stdout在caller获取前到期会另记late。

stage01有显式QPC子阶段诊断计时开销：70原NN stdout、11及时返回、3帧物理消费，RTF0.602330，仍FAIL。backend_step P50 1.338ms/P95 4.433ms；control_snapshot P50 0.140ms，每物理步至少两次。各分段包含调度/GIL/IO争用，不能直接解释成纯CPU或推理时间。旧v2只有首推理便超时，RTF≈1的空输出负载不等价持续NN负载。

相机提供的是 MuJoCo 实际曝光像素、原标定和采样本车反馈；适配器替代 C 板通信/执行边界，完整算法产生 yaw/pitch 后才进入原租约与80/150ms门禁和真实关节。通常工业相机直接接上位机，C板交换姿态/编码器与电机控制。本包没有接实物C板，不宣称特定电流环/CAN固件、原生Windows NN、跨机LAN、完整比赛或M0–M5签收。
