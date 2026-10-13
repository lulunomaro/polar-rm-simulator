# Windows 模拟器接入自家 PB2025 导航

Windows MuJoCo 的点云与 IMU 已通过持久 WSL 管道接入固定版本 PB2025 的 Point-LIO、SLAM、Smac 与原 PID 控制器。内部 QA 目标的两个实际 30 秒验证见[原记录](validation/pb_wsl_navigation_20261014/README.md)；生产 Gate 关闭内部目标后，独立 ROS 客户端的 30 秒单目标验证也已通过，见[生产接入记录](validation/pb_wsl_production_20261014/README.md)。这不签收完整哨兵任务、比赛或硬件；旧内部 QA 第2轮的间歇超时根因仍未关闭。

本机需要 Ubuntu-22.04 WSL、已生成并核验的 Humble/ext4 环境和自家算法构建。[PB桥说明](PB_NAVIGATION_BRIDGE.md)记录固定源、构建与身份来源。JSON 中的配置/环境文件包含本机 owned 路径；归档没有捆绑 ELF、依赖或可直接跨机使用的 `/root` 工作区。

## 本地清单与服务

清单由可信本地操作生成。`config_ref` 和 `environment_ref` 均是 **Windows 绝对路径及对应文件的原始 SHA256**；`out` 是仓库 artifacts 内全新的绝对目录，拒绝复用、链接与路径越界。示意字段如下，须替换成实际文件和校验值：

```json
{
  "schema": "polar.sim.pb-wsl-navigation-manifest.v1",
  "config_ref": {"path": "C:/absolute/generated/stack-config.json", "sha256": "actual-64-lowercase-hex"},
  "environment_ref": {"path": "C:/absolute/generated/ENVIRONMENT_COMPAT_FINAL.json", "sha256": "actual-64-lowercase-hex"},
  "out": "C:/absolute/polar-rm-simulator/artifacts/pb-wsl-session-fresh",
  "diagnostics": true
}
```

在仓库目录启动，招生凭据与操作手范围按[招生说明](ADMISSION.md)生成：

```powershell
.venv-sim/Scripts/python.exe -m rm_match.platform_v2 `
  --admission-manifest C:/absolute/local/admission.json `
  --pb-wsl-navigation-manifest C:/absolute/local/pb-wsl-manifest.json `
  --max-wall-seconds 300 --real-time-factor 1
```

本地 WSL 入口与原 `--pb-navigation-manifest` 互斥。服务在创建仿真后端和推进物理前完成资源准备，准备总预算10秒，没有传感器、物理或模型数据预热。首个真实 adapter reset 仍为2秒、图发现1秒、Linux等待50ms；主机保留原观测期限和 SDK 150ms 窗口，不拿Linux时钟换算或重贴Windows时间。

通过 SDK 绑定 `red_sentry` 的 `navigation` 到 `custom_pb_navigation`，配置 `{}`；原招生、motion claim/renew、控制窗口与 `adapter_input` 激活仍必需。输出仅来自控制器实际计算位置传播的原请求与LIO定位身份，裸 `cmd_vel` 不授权动作。本轮实现为 episode0/binding1 单次使用；换代须收尾后以新输出目录重启整栈。

启动 JSON 给出 `pb_wsl_navigation_namespace` 和 `pb_wsl_navigation_domain=84`。自家 ROS 客户端使用相同本机生成环境、Domain84与该独立 namespace，连接其 `compute_path_to_pose` / `follow_path` action。全局 `/clock`、`/tf` 与 `/tf_static` 必须映射到该 namespace 的同名话题。生产入口等待实际 SLAM 地图、LIO 与估计 `map→base_link` 后激活服务器，不自动注入测试目标。独立外部动作客户端已验证，原完整决策/行为树仍待实测。

客户端发送首个目标前，还须确认实际全局代价地图就绪。生产首轮中服务器已 ACTIVE，但 Smac 报起点超出地图并返回 status6；第二轮订阅原 `/namespace/global_costmap/costmap_raw`，确认实际估计起点和目标落在同一份有效网格的半开边界内后再发送唯一规划请求。网格原点、尺寸、分辨率、原时间戳、接收时刻与数据 SHA 均保存；代价值不参与就绪判据，路径可行性仍由原 Smac 判定。该条件不能保证之后的地图、动态障碍或任意目标可行。

## 生产 Gate 与外部客户端实测

```powershell
.venv-sim/Scripts/python.exe tools/qa_pb_wsl_production_sil.py `
  --environment artifacts/pb-humble-ext4-runtime-20261014/ENVIRONMENT_COMPAT_FINAL.json `
  --stack-config artifacts/pb-navigation-sil-config-20261014-04.json `
  --out artifacts/pb-wsl-production-sil-fresh --seconds 30 --diagnostics --run
```

该入口设置 `relative_test_goal=false`。独立 owned ROS 客户端仅查询原服务器 GetState 和实际地图/定位/TF，再从原估计 pose 生成 map x+1m 的测试目标，调用原 ComputePathToPose/FollowPath；它不激活生命周期、不发布传感器或裸 cmd_vel。Nav 栈准备仍为原10秒；外部只读客户端单独准备最多5秒，均在 backend/physics 创建前完成且没有数据预热。外部 observer 的收尾预算不改变 Nav、SDK 或物理 authority 的期限。

生产第二轮实际15000步/30sim秒，物理区间29.999280400s、RTF1.000023987；299原请求、297定位、59地图、19控制器结果对应708次非零物理消费。随后修复平台 HTTP 拒绝正文收尾，再以新服务源码验证第三轮：15000步/30sim秒、物理30.000017600s、RTF0.999999413，299请求/297定位/19结果/412非零消费。两轮原 Smac 均返回15pose/status4，FollowPath/status4；source、runtime、九组原算法及独立客户端清理均通过。第三轮前置保存28项精确源码，包含新SDK server/client/admission；第二轮原源码与报告保持不变。最后物理步与运行加清理时间分别保存，清理耗时不能补足提前停止的物理运行。该测试仍为单车、单代、单个估计相对目标；原全局网格数据仅保存元数据和记录 SHA，不声称独立重算未保存的完整网格字节或定位精度。

`status()` 在有效 act 正忙时返回 `WslNavigationBusy`，不取消当前事务；协议错误和 act/reset 并发仍拒绝并停止。生产 Gate 状态保存当前 run/namespace 与实际 map/odom 计数。主机和 Linux 的阶段账本分别记录 total/dropped/capacity，complete 仅表示未截尾；有界收尾写盘失败会明确标为清理失败。准备失败的原异常与清理异常均保留，不返回虚假的 clean。

## 独立实测入口

```powershell
.venv-sim/Scripts/python.exe tools/qa_pb_wsl_navigation_sil.py `
  --environment artifacts/pb-humble-ext4-runtime-20261014/ENVIRONMENT_COMPAT_FINAL.json `
  --stack-config artifacts/pb-navigation-sil-config-20261014-04.json `
  --out artifacts/pb-wsl-navigation-sil-fresh --seconds 30 --diagnostics --run
```

这是显式 QA 相对目标：实际算法估计的 map x +1m、y不变，由原 Smac/FollowPath执行。源 stamp、完整路径与 action UUID 原样保存；真值只在退出后用于隔离评测，不作为算法输入，也不声明定位精度。本轮没有相机、自瞄、射击或GL；80ms图像门限保持但没有在这个导航实验中验收。

第3轮15000步/299请求/297定位/42控制结果/553非零消费，原报告 `physics_rtf=.980798` 的分母实际包含 `.58698s` 收尾，应读作 run+cleanup 比率。第4轮分开保存最后物理步与收尾时间：30sim秒、29.9995142s实际物理区间，RTF约1.0000；run+cleanup30.5623169s、比率.981601。第4轮55结果/514非零消费，规划14pose/status4与FollowPath/status4，两轮原身份/SDK/期限审计及九组算法收尾均通过。

共享盘 STOP、非抢占 ROS callback、管道和主机调度仍可能产生尾延迟；第2轮首 fault 是 observed_seq67，原 activation deadline后正确拒绝，不能用后续激活或两个成功短测将其根因标为关闭。`HOST_RPC_PHASES.json` 与 `LINUX_RPC_PHASES.json` 只保存有界内存元数据，收尾时写盘；各自本地时钟仅在同一进程内分析，不跨域相减。

本轮还修复 native WSL worker 的 owned Linux 进程组清理：即便原 leader先退出，仍回收其已核验PGID/SID的后代，join owned IO、核验CLEANUP身份；单独真实Linux/stdio夹具与导航SIL分别保存，不能当作原NN实时通过。
