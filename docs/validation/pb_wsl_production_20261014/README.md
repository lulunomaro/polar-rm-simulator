# Windows→WSL production Gate 与外部导航动作验证

本包保存 2026-10-14 的单车、单 episode、单 binding 生产 Gate 路径及外部 QA action client 的真实失败和成功记录。Windows 当前工作区运行 MuJoCo/SDK authority；WSL Ubuntu 22.04/Humble 运行固定 PB2025 Point-LIO、Nav2 与原控制器。`relative_test_goal=false`，外部客户端只用 GetState 观察真实 ACTIVE 生命周期，随后提交原 Nav2 action；不通过生命周期请求替服务激活，不发布假传感器或速度。

完整来源、原 SHA、短文件名映射见 [INDEX.tsv](INDEX.tsv) 和 [PRESERVATION_MANIFEST.json](PRESERVATION_MANIFEST.json)。编号目录只为避免 Windows 长路径，不改变原件内容；大文件 gzip 的 mtime=0，原有 gzip 则保持原始字节。本包不打包 ELF、依赖前缀、venv、源码 clone 或凭据。

## 实际结果与失败边界

| 记录 | 实际物理/ROS | 原动作结果 | 范围 |
|---|---|---|---|
| [actual1](s1/f017.json) | 657 steps；9 request、7 localization；0 controller result、0非零消费 | 外部 action accepted，Smac status6/空路径；原日志 `Start pose is out of costmap` | Gate 已 ACTIVE/map2/odom11，但实际起点不在已发布全局地图半开范围内。资源组仍回收；业务失败使 peer/supervisor clean 标记为 false，不等于进程泄漏。 |
| [actual2](s2/f017.json) | 15000 steps/30sim s；299 request、297 localization、19收到的 controller result；708非零消费、19实际消费命令 | Smac15 poses/status4、FollowPath status4 | 物理 wall29.9992804s/RTF1.000023987（测量边界约1）；Gate map59/odom297。原 deadline 和全部清理检查通过。 |
| [actual3](s3/f017.json) | 15000 steps/30sim s；299 request、297 localization、19收到的 controller result；412非零消费、9实际消费命令 | Smac15 poses/status4、FollowPath status4 | 物理 wall30.0000176s/RTF0.9999994133；加入修复后的 Platform HTTP、client/admission 执行身份与保存源码。 |

实际2与3的完整逐消费独立证明分别见 [audit2成功](a2/f020.json.gz) 和 [audit3](a3/f003.json.gz)。SDK capture age 只用 Windows QPC 同域时间：2为31.105–128.798ms，3为15.783–117.573ms；六身份的值和类型、原 frame/acquisition/profile/LIO stamp、SDK ACK 与每条非零物理消费严格关联。收到结果数与实际消费命令数分别计算，不把19个收到结果都称为物理控制。

目标由真实算法估计 TF 生成：沿 map 的 x 方向偏移1m，y不变，保留原 TF stamp/方向；不是车体前向位移或定位精度测试。原 path、goal UUID、FollowPath UUID 和 GetState→ACTIVE→goal 时序均可审计。隔离 postrun qpos/ending TF 仅为评测记录，不反馈算法。没有完整任务/BT、多目标、多人、多机器人比赛、LAN/HIL 或新机器复现验收；M0–M5 不因此标通过。

## 真实地图就绪判据

外部客户端等待原 `nav2_msgs/msg/Costmap` 的 `global_costmap/costmap_raw`，按原 metadata resolution/origin/size 复算起点和目标的半开 bounds/cell，仍由原 Smac 决定可行性；不固定 sleep、不替换 planner、不输入 truth。实际2保存48个 raw receipt，实际3保存49个；每轮两个 readiness decision，最终 start=[0,153]、goal=[20,153]。两格记录 cost=255 仍不表示 free/feasible。

独立审计复算几何/索引并关联 receipt ID、header、原完整 TF/goal、topic/message type 与记录 SHA。完整网格字节没有保留，因此不声称独立重算原 `data_sha256` 或两格成本；SHA/成本只能做原记录间连续性检查。官方 raw publisher API 只读核对与真实 fixture 在 `c1/c2/path`；没有使用不持相同 mutex 的 GetCostmap 服务来冒充一致快照。

## HTTP 与统一质量检查

首 [QA01 manifest](q1/f002.json.gz) 在 interface_static 的真实 Windows oversized-body 请求中失败（10053）；pytest 与最终 source_unchanged 步骤未到达，不补写通过。它与本次导航实际1的成本地图错误、以及旧导航 attempt2 超时是不同问题。

本包 `http` 保存同一真实 loopback TCP reproducer（fake runtime，非导航/物理）：修复前36次仅12次完整413、24次10053；修复后36次全部完整413，线程均回收。原 HEAD438 server 与修复前字节一致的证据见 [BASE_IDENTITY](http/f005.json)，修复前后 [before](http/f007.json)/[after](http/f001.json) 和精确源均保存。37 focused tests、21 subtests 通过见 [focused](http/f012.json)。请求体16384 bytes、原1s总读取门限不放宽。DEVELOPMENT 原提取归属修复与更新脚本在 `refs`，actual3确实接入修复后 server `f7051d9c…`，不是给 actual2 重标新源码。

最终 [QA02 manifest](q2/f002.json.gz) 四阶段 exit0，`source_unchanged_during_checks=true`；[pytest原日志](q2/f004.log) 为1258 passed、49 explicit skips、848 subtests、6已有warnings，pytest95.109s，driver112.402s/reaped。49 skips不计通过，较旧48多一项 Windows symlink permission skip。新 focused02 为71 passed/8 skipped/105 subtests。此质量证据是配置/静态身份/合成与物理单元回归；未重跑相机/NN/GL，更不是 native 全比赛验收。

QA02 结束后，仅主文档 `docs/ROBOT_IO_V1.md`、`docs/ACCEPTANCE_TRACEABILITY.md` 修正旧范围陈述，区分默认 DTO 未达门禁、显式 PB 物理传感器/ROS 局部通过，以及 OFFLINE 13/13/241 与 live 未通过。`post` 是首份历史修订，`post2` 是最终 REV2（A02明确24次曝光中13检测帧 pose/track有效，漏检仍未签收）；两组 before/after 和逐字段声明均保留。before 精确匹配原 QA manifest，除此两文档之外所有当时 checked 文件仍是原 SHA；最终 ROBOTIO SHA=`f663ab62…`、ACCEPTANCE SHA=`e78703a9…`。REV2保存 proof.py/COMMAND/RESULT，实际 shell exit0仅有工具观察，无 rawstdout/完整 PROCESS_RESULT，不补造原始进程日志。该低影响 docs-only 修订没有再跑全测试，不声称最终整个仓库等于 QA02 全文件 map；执行源码保持已检验的 SHA。本包新归档文档同样产生在 QA02 后，属于证据保存而非执行源码改动。

## 身份、清理、时钟与缺失原件

actual3/source 保存28份原执行源码，独立 [SOURCE_SNAPSHOT_CHECK](a3/f005.json) 全部匹配原 RESULT SHA；driver/source 另保存24份测试/工具/DEVELOPMENT 身份。其他实际轮次使用各自保存的源，不混用后来修复版本。三个 `p1/p2/p3` phase audits 保存 PID/start_ticks/boot/run/spec 的匹配证明、9个 stack group 的 returncode/group_empty、peer reaped 与原 source/input SHA。

Host/Linux phase ledger 无 dropped；actual3 Host3001/Linux1500 rows、299 act 全部 collect，Host elapsed P50/P95/max=52.569/57.185/75.940ms，最小原 deadline 余4.820ms。Linux receive clock 只用于本域顺序，不与 Windows 相减。STOP duration 本身不证明因果，不能把两个 live run 的重叠耗时归因。

audit2 首次工具错误及第二次 traceback 原样保存在 `a2`：Windows Path 错把 Linux绝对 argv 当作相对路径。最终改为 PurePosixPath 并严格验证固定 argv/spec SHA，控制和消费判据不放宽。首次精确失败脚本、retry2成功脚本均保存；retry1 精确脚本原件未保存，只有记录 SHA/traceback，见 [MISSING_RECORDS.json](MISSING_RECORDS.json)，不重构历史源或原日志。

旧导航 attempt2 的 RPC timeout 根因仍开放；两次生产成功不等于该历史故障已修复。原相机80ms native live 0返回/0消费失败仍保留，不由本包导航结果替代。T01目标机/阈值/实际负责人冻结、完整M0–M5验收以及当前计划其它未达门禁，见主计划和进度文档。本包只声称上述局部实际路径通过。

## 来源分组与复现

`s1/s2/s3` 为原实际记录与各自源码，`d1/d2/d3` 为 actual drivers；`f1/f2/r6` 为 focused/早期 session修复；`p1/p2/p3` 为 phase/resource只读审计；`c1/c2/path/re/rn/pr` 为官方API fixture/路径fixture/旧reviews/计划证据层审计；`a2/a3` 为独立消费审计含工具失败；`q1/qd1/q2/qd2` 为统一质量失败/成功与 drivers；`http` 为真实HTTP前后36样本与源码；`refs` 为原环境/stack配置/归属元数据。所有短标签与完整原路径均列在 INDEX。

`post/post2` 为 QA 后两个主文档的历史/最终REV2明确修订记录，保存脚本在 refs或原组；`stop` 保存无扩展名的原STOP JSON身份记录，作为进程清理输入同样逐字节保留。`append.*` 和 `append2.*` 为两次明确追加后的新保存/验证原日志，首次 archive/verify 原日志保持不变。

在仓库根进行纯证据验证，无需启动 ROS/仿真：

```powershell
.venv-sim/Scripts/python.exe docs/validation/pb_wsl_production_20261014/verify_archives.py --archive docs/validation/pb_wsl_production_20261014
```

真实复测入口为 Windows 的 `tools/qa_pb_wsl_production_sil.py --environment <已重建并核验的ENVIRONMENT_COMPAT_FINAL.json> --stack-config <已重建并核验的本地stack配置> --out <全新目录> --seconds 30 --diagnostics --run`。先在该机器按固定构建/依赖 recipe 生成受信环境和 ELF，并核对 spec/hash/路径。原2s reset、1s graph、50ms ROS等待、150ms SDK窗口不改变；旧资料内的私有路径是原执行出处，不声称跨机直接就绪。原字节构建/环境 metadata 在 refs，执行 argv 在各 COMMAND 原件。

[archive.json](archive.json)、[verify.json](verify.json) 与相应 `.stdout.bin/.stderr.bin` 是本包真实保存和独立逐字节验证日志；[OLD438_UNCHANGED.json](OLD438_UNCHANGED.json) 核对原两包376文件仍逐字节相同。[FILES.json](FILES.json) 提供包括本包元数据/recipes的精确清单（自身另列，不作自引用hash）。归档与验证不重跑测试、ROS、WSL或算法。
