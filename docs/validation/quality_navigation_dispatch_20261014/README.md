# 导航 dispatch 检查点质量记录：2026-10-14

统一入口 `tools/check_project.py` 实际 exit 0；preset、source provenance、interface、pytest 全通过。pytest 为 1144 passed、37 skipped、685 subtests，6 warnings。检查期间全部 source bytes 不变，完整命令与源 SHA 在 [manifest.json](manifest.json)，跳过原因与 warnings 在 [pytest.log](pytest.log)。

本轮包含 default-off Point-LIO dispatch/ControllerContext 诊断及相关配置、安全拒绝回归。Windows 测试中 POSIX/ROS/C++/WSL 等未执行部分按原 skip 保存，不能计作真实 LIO、SIL、NN 或完整比赛。并行资源为两个独立 C++ 构建，因此本轮耗时不作为实时性能或冷启动达标证据。

本轮未重复 camera；前轮真实 loopback camera 35 checks 独立保留在 [前轮证据](../quality_navigation_startup_20261014/README.md)。没有改动图像 80 ms、控制 150 ms、JsonLineAdapter reset 2 s 或 bridge 50 ms 的窗口。

[PRESERVATION_MANIFEST.json](PRESERVATION_MANIFEST.json) 记录全部原文件大小、SHA 和原路径；存储文件与原始 artifacts 逐字节一致，不转换换行。此质量结果不签收 M0–M5。
