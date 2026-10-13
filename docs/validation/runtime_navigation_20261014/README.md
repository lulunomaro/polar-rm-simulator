# 导航运行时修复检查点

2026-10-14，81 项 focused 回归通过、52 个子测试、0 跳过；六项运行源在检查期间不变。
物理传感器预采集移到控制锁外，同一真实采集时刻重复准备不刷新字节或壁钟。
导航/JSON 工作线程及关闭路径不再无条件导入 native 视觉模块，原生子类、私有像素和取消守卫保留。
导航 enqueue 记录原 frame、profile 和采集起止，用于后续物理执行审计，无新采样或时刻改写。

`humble/RESULT.json` 是较早版本的独立 Linux 子进程证据：禁止 native/cv2 导入的 finder
下，三个导航夹具和真实 JSON child 的 reset/act/close/reap 通过；不是实际 ROS 导航。
保留误拼测试模块的失败记录，后续正确 focused 命令单独记录。

此检查点只证明局部运行时、物理传感器和进程守卫。Point-LIO/Nav2 驱动哨兵的闭环仍未通过，
没有完整比赛、Windows↔WSL部署或硬件验收。`PRESERVATION_MANIFEST.json` 核对八个原记录字节。
