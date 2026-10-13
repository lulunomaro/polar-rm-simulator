# ROS2 JSON信封桥：真实DDS基础证据

官方ROS2 Lyrical，Ubuntu26.04 WSL，Python3.14.4、rclpy10.0.11、rmw_fastrtps_cpp。
实际专项1test通过（未skip），本地domain79，发现范围LOCALHOST、无静态peers。
测试peer收到1个完整fixture observation、桥输出reset/action两条合法JSONL，六身份原样echo。
bridge PID757退出0、peer线程结束、ROS context关闭；只是显式零速度消息fixture，未运行导航、自瞄、物理或硬件。

actual_attempt1原缺C库、actual_attempt2原缺em模块失败均保留；actual_attempt3是真正DDS通过记录。
97个ROS官方deb经ROS公钥/InRelease/索引SHA/逐包SHA校验，7个Ubuntu C库与4个Python库经官方apt元数据验证。
包只 `dpkg-deb -x` 到本次owned prefix，不运行安装钩子、不写/etc、不更改全局环境。
PRESERVATION_MANIFEST绑定25项env/version/签名、包/抽取清单、原运行器与实际输出；不捆绑ROS编译库。

运行器原文本保存为run_actual_ros.py.txt；恢复为.py后，结合原env与经过核验的prefix可复现。依赖获取路径/版本/SHA见各PACKAGES_MANIFEST。
原host JsonLineAdapter的2s reset限制、80ms图像/物理门禁、Windows↔WSL ROS专用监督器、Nav2/TF/MID360、自家算法和两电脑LAN仍待联调。
生产配置/主题/身份/期限与源码入口见 [ROS2桥文档](../../ROS2_BRIDGE.md)。
