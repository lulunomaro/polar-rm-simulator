# 导航启动修复的统一质量记录

2026-10-14：1139 passed、36 skipped、625 subtests；五个质量步骤全部返回 0，1031 项源在检查期间不变。
相机检查实际使用本机 NVIDIA renderer，35 项检查通过，renderer 和工作线程关闭；仅 2 总 FPS 的本机显示检查。

本轮未开启 `POLAR_TEST_WSL`：19 项显式 WSL 无害进程专项跳过，其他跳过来自 POSIX/Linux/ROS、
C++显式专项、离屏环境或 Windows 链接权限。已有独立实际专项记录分开保存，不能与单元测试相加作为闭环。
运行期间独立 Point-LIO 编译和依赖复制仍在进行，此记录不用于冷启动时限、实时 RTF 或性能对比。

没有实际 native 自瞄、九节点导航、跨机 LAN、完整比赛或硬件签收。图像 80 ms、控制 150 ms 与
桥进程 reset 2 秒门限未改变。归档在检查结束后添加，12 个原记录的字节与 SHA 见 `PRESERVATION_MANIFEST.json`。
