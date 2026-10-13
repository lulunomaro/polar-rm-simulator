# 实际三维扫描与 IMU，尚非导航闭环

使用当前 MuJoCo 3v3 的实体几何逐物理步 ray cast，明确的解析非重复扫描 profile、200000 次射线尝试/秒、10 Hz 扫描窗口、2 ms 实际时间量化；无回波的射线不制造点。反射率固定 100、噪声和 mount 都是显式 provisional 参数，不声称复制真实 MID360 光学或硬件标定。

第 1 轮 2 秒、1000 个物理步，19 cloud、RTF 0.99955；使用六线，仅作早期诊断。按锁定 Point-LIO 实车 `scan_line=4` 改为四线，没有修改导航 filter。第 2 轮 10 秒、5000 步、99 cloud、RTF 0.9999635，源码 SHA 在测量前后相等，errors=[]。最后扫描尚未闭合时不额外制造一帧。

每个点是 sensor-local xyz 与真实采样 offset ns。IMU 使用同 site 的 MuJoCo gyro/accelerometer，包含重力、采样时间，未输出理想 orientation。每帧 IMU 包含扫描起止时间，未按送达时刻重贴 stamp。独立 navigation schema 无 qpos、qvel、理想里程计或世界位置。

实验中的底盘激励为明确脚本经执行器产生，**未运行自家定位、规划或控制器**。图像 80 ms 与 SDK 控制 150 ms 原窗口未改。它不证明 Nav2、Point-LIO、自家导航、跨机 ROS、真实车辆、完整比赛或联合相机/native 实时性能。

[实际报告](attempt2_lines4/RESULT.json)保留逐 cloud 时间/点数/IMU 数和源 SHA；first/last observation 为原 JSON 无损 gzip。[保留清单](PRESERVATION_MANIFEST.json)记录所有 SHA。

```powershell
.venv-sim/Scripts/python.exe tools/qa_navigation_sensors.py --run --seconds 10 --out artifacts/new-navigation-sensors
```
