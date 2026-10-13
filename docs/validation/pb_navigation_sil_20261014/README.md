# 自家哨兵导航：构建、启动与失败的实际记录

归档截至六轮实际 SIL。全部 `bounded_navigation_consumption_passed=false`，0 定位、0 地图、0 控制器结果、0 有效物理动作。
149 个原记录逐字节保存；大记录 gzip，清单同时核对原字节 SHA 和存储 SHA，解压后与原件一致。

| 实际运行 | 结果及边界 |
| --- | --- |
| attempt1 | 动态库路径在 Python 启动后设置导致导入失败；0 步、没有启动算法子组 |
| attempt2 | 生命周期客户端误用未初始化的默认 Context；0 步、九个子组已回收 |
| attempt3 | 父、子 DDS localhost 范围不一致，生命周期服务超时；0 步、九组已回收 |
| attempt4 | 自家代价层/PID 与 Smac 实际配置成功；仅 1 步，SDK 请求超时停止，无动作 |
| attempt5 | 15000 步/30 秒仿真、RTF 0.999315；543 次 SDK 激活，桥 reset 2.044808 秒超原 2 秒，0 数据发布 |
| attempt6 | 桥模块至 ACK 1.370686 秒，图连接 `[1,1,2,1]` 齐备；1016 步，随后 SDK lease_mismatch，0 数据发布 |

attempt6 的 ACK 计时不包含 host Popen 至模块导入；原 host reset 成功但随后失败。
其物理消费间出现 1.102492 秒间隙，工作线程无条件导入 native/cv2 的 ABI 警告也实际记录；
后续已修复运行时并另存 [局部回归](../runtime_navigation_20261014/README.md)，此处失败结果未改写。

`lio`、`terrain` 为真实六个 ROS 包的 build/ELF 审计，`plugins_unique_soname` 和 `controller_resume`
为独立实际编译。自家 `liblayers.so` 与 Nav2 同名绑定冲突只通过 owned 输出名/XML 修复，算法及类名保留。
`loader/RESULT.json.gz` 包含三个实际库的 readelf/ldd/RTLD_NOW 通过和旧冲突失败；独立类探针编译超时
另存 `PLUGIN_CLASS_TIMEOUT.json`，不能称其类实例化通过。类配置的实际证据来自 SIL4–6 节点日志。

`owned_context`、`dds_scope` 是真实无害生命周期微测试；`runtime_import` 是无 native/cv2 的独立 JSON 子进程。
`numpy2_dds` 仅消息、主题与清理，`cold_sensors` 是独立物理传感器脚本（1000 步/19 cloud），均非导航闭环。

后续修复候选补上 source 时间戳的有界乱序关联、过界数据明确丢弃、原扫描与 SDK ACK 的物理消费审计。
这些新修复不用于重判上述旧运行。80 ms 图像、150 ms 控制、2 秒 reset 门限保持，未输入理想位姿或替代算法。
Windows 工作区源码、Linux Ubuntu22.04/Humble 实际栈、Windows↔WSL部署和完整比赛分开验收；当前无完整里程碑或硬件签收。
