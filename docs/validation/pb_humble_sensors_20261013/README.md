# 北极熊 Humble 传感器接入检查点

对应用户指定的 pb2025_sentry_nav cb97fb07，以及固定 Point-LIO / Omni PID 子模块。
PRESERVATION_MANIFEST.json 逐项记录原始路径、长度与 SHA-256；记录保留原字节。
上游源码、ROS 官方依赖和本机 ELF 仍在本地 owned artifacts，不随此记录发布。

实际 Livox ROS 消息接口已在 Ubuntu 22.04 / Humble 编译（46.84 s），未启动硬件驱动。
固定 2024/2025 CustomMsg 与 CustomPoint 原字节相同，等价记录只证明消息 ABI。
fixture/RESULT.json 使用新进程及原 JsonLineAdapter：reset 0.806705 s，act 0.051286 s，
9 项 DDS 检查与回收通过；没有定位算法或动作，原 2 s / 150 ms 限制未变。

archived 与 namespaced 是实际保存扫描的字节搬运实验：保留原 0–100 ms 输入、51 条 IMU、
584 返回点与 wall_deadline，不刷新时间。namespaced 验证独立 clock / tf_static 主题。
两项没有调用当前物理期限 authority，因此不能作为实时控制通过。
每份 RESULT.json 各自记录真正执行的 source SHA；早期 fixture 不是最新主题配置的证明。

lio_overlay 保存实际扫描到原估计结果的上下文、精确时间关联与缺失 TF 拒绝配置。
lio_build 保留三包真实编译完成的原记录（1268.513 s、源码未变、三项实际 ELF 和依赖检查）；
它们尚未启动，不能据此声称 Point-LIO / Nav2 / SLAM 或哨兵执行已通过。
default_native 保存默认 T2 29 个翻译单元的新干净构建记录：ELF SHA 仍为
4d3570674a7a150da0e86f64bbbd25adcfa8bb9e2731672ac6aeaa296cf92b42；没有替换自瞄算法。

numpy2 是后续新环境的实际 namespaced fixture：NumPy 2.2.6 / MuJoCo 3.15 / rclpy 3.3.21，
原 host reset 1.298072 s、act 0.051318 s，9 项 DDS 与清理通过，仍无定位或控制。
environment 保存 96 个官方签名/SHA 校验包、13 个官方 wheel 和实际类型序列化证据。
Humble 原导出固定 /opt 路径与当前 owned prefix 不一致：兼容层仅映射已验证的缺失路径，
原始包字节未改；真实 PUBLIC ament header / layers 链接 probe 已通过。
nav2_initial_failure 保存最初 113.1 s configure 失败；后续插件构建还发现自家 layers 与
Nav2 基础 layers 共享库重名，需要 owned 输出名与插件 XML 同步修复，当前未声称可运行。

复现入口：tools/prepare_pb_humble_interfaces.py、tools/diagnose_pb_humble_sensors.py、
tools/prepare_pb2025_lio_tf_overlay.py、tools/build_pb_nav2_plugins.py。各工具需显式 owned
输出路径及本机依赖配置；运行前看 --help。不能直接复用归档扫描进行实时资格判定。
