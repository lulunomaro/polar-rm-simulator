# 按计划实施的进度与证据

更新至 2026-10-16（UTC+8）。按用户指定的父目录 PROJECT_PLAN.md 推进，源码工作分支为
work/plan-t01-t03，开发起点 1fdcd249be761100076670bb863c14357e8c62ed。
历史 cf6a6e4 证据、原帧、原模型及失败实验均保留。当前无 M0–M5 完整签收。

| 任务 | 当前状态与实际进展 | 尚待完成 |
| --- | --- | --- |
| T01 | 进行中：RobotIO 草案、R01–R12/A01–A15 追踪、live/offline 独立预设；新增独立导航/决策能力协商、组合图与原请求身份契约 | 最终目标机、负责人、标定、规则和指标冻结；预设仍 draft |
| T02 | 进行中：原失败保留；contour-v3修复，完整T2新构建与历史静态OFFLINE24/三次live链局部通过 | 模型漏检、PnP精度矩阵、移动/丢失重捕获仍待完整验收 |
| T03 | 仍FAIL但静态及时链恢复：本轮最终默认运行138及时结果/134独立帧执行、最长wall78.12ms；新增显式render-ready拍摄与平面Command快照，原80/150ms/ELF/模型保持 | 最终10秒RTF0.961707低于原0.98；新拍摄模式本次busy计数0，不能归因于它；移动/性能稳定性仍待验收 |
| T04 | 进行中：第六Qt新增严格aim v2选择/原授权绑定；513项/395subtests客户端回归通过；旧五版保持各自身份，既有第五版手控/PB导航5秒/30秒局部SIL保留 | 更长/可见桌面、移动完整自瞄、云台精度/实体弹丸、完整队伍算法/比赛树组合 |
| T05 | 新增显式通用aim v2源方向参考，原source/budget锁定后按当前本车yaw转换；真实MuJoCo合成指令机械正/负对照通过，修复最终Command未应用新角度 | 不补平移/目标预测/弹道；T2原生移动profile、29TU新构建、多车同时真实自瞄未验；原静止scope证据按原源保留 |
| T06 | 新增真实Slot暂停在途结果复活修复、fault与取消负例、绝对截止边界回归；全部失败和来源保留 | 系统运动/遮挡/丢失/射击/断线完整闭环矩阵仍待完成；合成/单位与无害进程不替NN实时验证 |
| T07 | 真实BT4/PB actual07健康单目标局部SIL保留；capabilities.v2完整协商与第六Qt保留；新增当前静态模型安装位姿导出，六车几何与历史相同 | 相机源码变更使旧PB自瞄mount原pin正确拒绝；须显式准备新spec再验，未自动继承旧验收；第二完整自瞄/比赛树多分支/多车仍未验 |
| T08 | 未完整实现：当前解析式简化车辆 | 真实车辆资产/动力学/轮腿策略；来源许可与策略复现 |
| T09 | 真树actual07局部SIL通过：136原LIO/精确TF、原costmap起点门、15实际公开动作/620非零物理步，原目标终态/stop与owned资源回收有证；旧失败保留 | 健康单目标非完整巡逻/交战；定位标定/精度/恢复和完整任务未验收；NavigateToPose仅单元证据 |
| T10 | 已有版本化 2026 RMUL 子集，未完整验收 | 官方规则逐条测试、资产许可和适用性 |
| T11 | 图像修复局部证据，已有源尺寸装甲和弹丸实现 | 真实装甲光学/物理标定、实体弹丸命中/热量/伤害完整证据 |
| T12 | 未验收 | 六车自有算法完整 3v3；旧算法/像素代打不计通过 |
| T13 | 本地局部修复：两独立credential/scope/lease/SDK同场30秒通过，步兵486批全部匹配，1502guard/0诊断丢弃；原host1.5s内Qt/两个WSL所有owned资源退出，原Linux1.3s不变 | 两物理电脑LAN、多人冲突/断线、更长/可见桌面、通用决策/自瞄与比赛全链 |
| T14 | 未验收 | 14 车完整 7v7、资源与实时性能 |
| T15 | 已有局部事件账本、哈希和帧证据 | 整场日志/复演/视频与关键事件、终局一致性 |
| T16 | 本机 Windows 仿真/Qt 与 WSL Linux 两次 clean native build；LF/UTF-8/socket/路径修复 | Windows native、干净第二电脑和可复现发布包 |
| T17 | 最终四阶段QA02通过：3405pass/45skip/1024subtests；492程序/测试/补丁和17884项全树输入前后相同；首轮旧mount源码pin失败保留 | 质量通过不替RTF、移动自瞄、多车/比赛/发布验收；静态恢复不关闭M0–M5 |
| T18 | 未启动真实硬件 | 先完成 SIL 与 HIL 安全方案；真实车辆专项授权仍需要 |

| 里程碑 | 状态 | 原因 |
| --- | --- | --- |
| M0 冻结基线 | 未完成 | T01 draft 和未决指标尚未冻结 |
| M1 自有真实闭环 | 进行中 | 历史静态局部证据保留；本轮实时回归退化，移动/重捕获/实体射击/可见客户端与完整回归未验收 |
| M2 通用可替换 | 未完成 | T07–T11 与两机 LAN/第二实现仍缺完整证据 |
| M3 完整 3v3 | 未完成 | 六车自有完整比赛、整场复演与换机未验收 |
| M4 完整 7v7 发布 | 未完成 | 14 车、Windows native、发布许可/包未验收 |
| M5 真实车辆 HIL | 未启动 | 依赖前置 SIL 及专项硬件授权 |

## 按渲染就绪拍摄与静态及时链恢复（2026-10-16，本轮最新）

遵照用户最新指令，本轮全部开发、排查与验证由主代理直接完成，未调用子代理。
新增显式本地`capture_policy='render_ready'`和诊断CLI选项；GL/编码忙时推迟新的authority快照，
不推进拍摄cadence或车辆轮询位置，撤权与跨回合清理仍先执行；已有帧时间、像素、标定和原80/150ms不改。
默认仍为latest_pending；该模式可能减少实际FPS，不预设其能解决RTF。

先做的OpenCV浮点/定点映射离线ABBA出现SHA差异，拒绝应用，原lens warp保持。
另外将每2ms的Command显示快照由递归asdict改为六个不可变标量直接分离，原字段/类型与负例、执行器守卫保持。
离线六Command/10000轮ABBA为asdict0.07454/0.07605s、scalars0.01213/0.01259s；仅表示该离线序列化开销，未证明生产RTF改善。

| 实际六车场景/单车静止T2，原CPU4 ELF/模型 | ready01 | default02 | 最终default03 |
| --- | --- | --- | --- |
| 相机policy | render_ready | latest_pending | latest_pending |
| scalar快照优化 | 前 | 前 | 后 |
| run加cleanup wall秒 | 10.0890160 | 10.0957523 | 10.0896508 |
| physics RTF | 0.964237 | 0.964767 | 0.961707 |
| raw /及时结果/独立帧执行 | 148 /138 /137 | 148 /136 /136 | 148 /138 /134 |
| 最大执行wall age毫秒 | 78.5482 | 75.6497 | 78.1184 |
| 原预算/像素核验/请求归账/owned清理/运行源码 | 保持/通过/通过/clean/恒定 | 保持/通过/通过/clean/恒定 | 保持/通过/通过/clean/恒定 |
| SDK/runtime error | 无 | 无 | 无 |
| 总判定 | FAIL，仅RTF | FAIL，仅RTF | FAIL，仅RTF |

三轮均零开火，无可选phase/authority计时；原150ms activation与80ms capture门限全部保持。
ready01忙时延后计数0，default对照也恢复及时链；与历史渲染读回40–50ms相比本次约8ms，
这不是隔离硬件负载的受控实验，不能把恢复归因于新增policy或scalar快照，也不据此撤销旧失败。
最终03的141笔原请求为138 stdout、1 late、1 after-pending discard、1 owned unwritten cancel，未把迟到/取消记成及时结果。
静态及时动作恢复不等于完整live资格、移动自瞄、实体命中、第二自瞄或3v3完成。

相机源码变更使历史PB mount原source pin正确拒绝，首个全量因此1fail；同次文档也曾在QA期间编辑，
不能将该轮称为整个交付树冻结通过。旧mount文件与校验器保持，新增`tools/capture_aim_mounts.py`从当前编译模型导出，
零物理步/NN/GL，六车几何与旧文件逐值相同，仅camera源码身份更新。
新mount SHA`e77f3c1c785d4791761e1a095129198c4d5dd154730f069118213a796a27acd6`。
实际mount测试改为每次提取当前模型并通过原校验器，另保留旧mount拒绝；新导出不自动重绑PB旧spec或继承旧运行资格。
早期相机测试两失败为已完成的MjData池可复用、plan字段名假设错误，保留JUnit；修正测试期望后156项通过。

最终全量另用全新目录执行；程序/测试/补丁输入由driver逐文件留存，结果和复现见
[本轮固定证据](validation/render_ready_20261016/README.md)。当前T03仍FAIL，其余T01–T18/M0–M5缺口保持。

最终QA02四阶段通过：3405pass/45skip/6既有warnings/1024subtests，pytest142.63s，driver185.366557s/exit0/reaped。
492程序/测试/补丁逐SHA不变，17884项Git已知全树输入在该轮前后相同；最终native03使用完全相同的492项程序输入。
本段结果、任务表QA数和归档在QA结束后补写，未把后补文档冒充原始检查输入。

## 原生实时诊断与存证读回优化（2026-10-16，历史检查点）

新增显式 `--profile-phases`，默认关闭；固定容量、原source6/request/frame/pixel SHA及原deadline，
只采有限标量wall/thread CPU/线程号/队列占用，关停后输出，不新复制图像、不减少实际校验。
同一probe在prepare前进入registry、async传输和writer；helper随启用路径进入源码pin。
默认无新probe时钟/锁/hash；原图像80ms、SDK150ms、owned取消/清理和人工火控保持。
whole authority step全采，详细阶段固定每50step；首次全详细采样140149条，有诊断开销且原失败保留，
后继记录8668条也仍未通过，不将减少条数当性能因果证明。

本机CPU记账正增量实测15.625ms，ns单位不意味着细粒度精度；短阶段CPU0和负wall-minus-CPU原样保留，
不能解释成GIL等待或零工作。跨线程队列只做同域wall关联，同线程/原身份才比较CPU；重叠阶段不可相加。
独立审查确认run01的binding_mismatch属于原activation期限到达后的sticky撤绑定，不是lease过期或需要重试的控制漏洞。

实测writer文件读回SHA长等待后，将固定分块64KiB改为1MiB，完整磁盘读回、size、原BGR/JSON和两次SHA均保留，
每4,665,600字节文件循环72→5、临时块上界1MiB。离线同一真实BGR暖缓存ABBA+合成Python争用线程，
每组3帧64KiB为4.7753/4.9551s，1MiB为0.5749/0.5347s，12个SHA全部相同；不是live或GIL因果结论。

| 本轮实际静态运行 | diag01，优化前/全详细 | diag02，优化前/stride50 | default03，1MiB/无额外计时 |
| --- | --- | --- | --- |
| 实际运行+清理wall秒 | 8.1634（提前停） | 10.1191 | 3.7627（提前停） |
| physics RTF | 0.642759 | 0.521594 | 0.706906 |
| raw /及时结果/独立帧消费 | 109 /0 /0 | 137 /0 /0 | 54 /0 /0 |
| SDK/runtime error | binding_mismatch | 无 | binding_mismatch |
| source/原预算/完整请求归账/owned清理 | 保持/通过/通过/clean | 保持/通过/通过/clean | 保持/通过/通过/clean |
| 总判定 | FAIL | FAIL | FAIL |

default03仅12笔queued（11笔原生前丢弃、1笔实际stdout迟到），未冒充及时NN或动作；
两个提前停的RTF不能当成完整10s稳定性，也不与旧源直接因果比较。旧全部失败原样保留，停止重复同条件NN。
下一步按完整曝光/准备/上传/响应与SDK续授权链隔离瓶颈，保持原门限，不修掉正确的过期撤权。
本轮无新模型、ELF构建、PnP矩阵、移动自瞄、第三方算法全链或比赛验收，T01–T18与M0–M5其它缺口不变。

最终QA01四阶段通过：3399pass/45skip/6既有warnings/1024subtests，pytest164.41s，driver222.722753s/exit0/reaped；
490程序/测试/补丁输入逐SHA保持。优化后focused03通过312项/46subtests；原源focused01与02及agent专项证据独立保存。
实际default03在此最终QA后执行且相同最终程序输入不变。本文结果段和归档在QA后补写。
复现、原始失败和源码见[固定证据](validation/native_phase_20261016/README.md)，计时范围见[诊断说明](NATIVE_PHASE_DIAGNOSTICS.md)。

## 第六Qt兼容与显式部署选择（2026-10-15，历史检查点）

第六完整补丁从固定client BASE独立生成，包含第五版所有改动并严格支持
`camera_gimbal_v2` / `2.0.0` / `camera+odometry` / 原source-base惯性yaw参考。
真实Qt离屏专项56pass/64subtests、继承平台32模块513pass/395subtests/0skip；
第一次完整调用因未提供旧夹具所需的父仓PYTHONPATH而collection失败3项，保留原日志，
只修运行环境后另存第二次完整结果，没有改客户端源码掩盖失败。
选择仍使用原claim/fresh-own-HUD/人工arm/空binding config，未知/混合能力和旧ROS v2拒绝。
原五份patch、manifest、checkout与历史实际SIL证据不继承第六身份，也不被覆盖。

Linux部署显式 `--client-patch-manifest` 与同一 `--client-root` 配对，
计划固定hash、doctor/服务启动前/ready后客户端取凭证前重验；setup apply/postcheck同版本。
native diagnostic也支持显式选择并在收尾核验身份，旧省略参数默认仍第一版，不自动猜版本。
新增第六手控coop模板的导航/自瞄spec仍为null，不能当成已部署算法或完整比赛。

第六33文件从固定BASE实际apply/还原和源码核验通过，独立review真实调用check_client通过；
旧五份patch/MF及138份旧checkout成员原字节不变。首次roundtrip因混用Git CRLF配置而raw-clean断言失败，
保留原命令/dirty输出；后续逐调用匹配LF或CRLF配置验证，未改全局Git设置或回写原结果。
deploy/co-op/native diagnostic三个真实dry CLI均选择同一第六身份，没有启动算法。

六车实际MuJoCo、合成camera/aim v1绑定的ABBA诊断覆盖实际active执行：
active目标路径中位数parent/current约18.75/21.00微秒，同版本样本波动大，不能据此解释实际T2退化。
旧native01/02/03的render和输入ACK墙钟对照已存；没有thread CPU证据，不能断言GIL为原因。
下一步复用profile-authority并补有界同源队列/写入wall与thread-CPU采样，停后落盘；本轮未改门限或重跑NN。

[固定证据](validation/qt_aim_reference_20261015/README.md)保存原失败、源快照和复现命令。
最终QA01四阶段通过：3332pass/45skip/6既有warnings/1024subtests，pytest227.07s，
driver329.413784s/exit0/reaped；484程序/测试/补丁输入前后逐SHA相同。
256客户端源文件在Qt测试前后相同，归档时逐文件核验后补存字节，不伪称运行前已复制。
本节、兼容文档和归档结果说明在QA后补写。M0–M5状态不变，旧实时失败不因Qt通过而签收。

## 通用aim v2与最终执行器修复（2026-10-15，历史检查点）

[本轮固定证据](validation/aim_reference_20261015/README.md)分开保存单位/合成、真实无害WSL生命周期、
真实MuJoCo合成指令机械对照和三次T2静态实时失败。新增完整v2能力协商与源方向yaw保持，
不改旧v1，不刷新原80/150ms，不把通用协议当成各队算法均已适配。
最终检查的新角度现在实际写入MuJoCo Command；同绑定源水位拒绝暂停前在途结果；
部分输入取消/零字节未发送/停止后EPIPE各按真实阶段归账，既有fault不得清洗。
helper机械试验0图像/0NN/0SDK；第五Qt及旧ROS envelope不能选择v2。

最新native03为49真实结果/32独立帧消费、RTF0.821310、原图像门与清理通过，整轮仍FAIL；
此前01缺取消终态、02包装过期归账和浮点边界、03停止后EPIPE原记录与源码均保留。
最后host窄修仅重跑无害阻塞pipe，没有重标03为最终源通过。
本轮最终QA02：3322 passed, 45 skipped, 6 warnings, 1024 subtests passed in 154.50s (0:02:34)，driver 217.932701s/reaped、472程序/测试/来源输入不变；
本节、兼容文档结果段与归档在QA后补写。无绑定六车ABBA未显示公共路径退化，不能解释实际绑定/图像链性能下降。

下一步仍需定位实际实时退化，并实施原生fixed-own-odom/tracker/pivot-relative fire的新profile和新clean build，
再验证移动、重捕获、多实例和完整比赛。T01–T18其余范围及M0–M5均不因本轮自动签收。

## T05 显式静止身份扩展（2026-10-15，历史检查点）

新增[本地scope示例](../examples/native_robot_scope.json)，将T2输入的robot/team/role/referee ID绑定到
SHA固定声明，替代包装层原先固定红方/ID7的帧构造；默认仍为red_sentry。
注册、adapter构造、native启动及WSL已准备实例交接重检原字节；HTTP config不能选择身份或文件。
Linux部署launcher的doctor、启动前文件检查、ready完整类型化声明也保持同一scope，admission不随scope扩大。
原静止速度0.03、位置漂移0.025m、稳定0.4s、固定1440×1080/K/D/安装位姿、80ms图像/150ms SDK与人工火控均保留。

| 实际顺序单车静止运行 | 红步兵01 | 蓝步兵01 |
| --- | --- | --- |
| 真实2ms物理步/仿真秒 | 4945 / 9.89 | 4991 / 9.982 |
| 物理RTF | 0.9889068252 | 0.9981690168 |
| 原始图像帧 | 148 | 148 |
| 及时原生结果 / 独立帧物理消费 | 135 / 135 | 124 / 121 |
| 最大消费capture wall age / sim age | 77.5396ms / 78ms | 79.1358ms / 78ms |
| fault / fire / 清理 | 0 / 0 / clean | 0 / 0 / clean |

两次均使用原CPU4 ELF/模型和显式CV4、pybase64_1_5_1、CPython1ms、authority mask0x10配置，
实读并finally恢复调度；driver24.6974323s/21.4255280s，exit0/reaped、各自执行源码前后一致。
全部277个实际BGR文件及反通道RGB SHA独立复核，259个及时结果的原native字段逐类型保持；
host仅添加原episode和由tracking导出的should_control。其余pending/late/discard单列，未计及时推理或消费。
Linux owned cleanup11.306/16.597ms；host runtime共享收尾76.937/88.666ms，均在原预算内。
原始stdin的team/referee字段没有独立echo记录，身份路径由scope、逐帧匹配与执行源码证明，未伪称额外wire捕获。

`pitch_link`机械helper现在要求显式曝光观察，同robot/episode、有限且不晚于当前的捕获姿态，
先按曝光姿态转惯性方向再投影当前本车base；生产原生仍输出world，helper单元证据不等于移动支持。
目前原T2 PnP/Tracker仍缺本车平移原点补偿，FireController要求pivot-relative目标，
runtime还需要真实消费时朝向投影。下一步按已保存的source-owned移动设计实施新profile和29TU新cleanbuild，
保持原deadline/物理速率后测正常速度移动、重捕获，再做多实例与完整3v3；没有移除stationary门。

QA01在来源清单缺新helper变更说明时失败，未执行pytest；QA02保留3个旧测试夹具/参数断言失败
（3120pass/45skip）；修正__new__夹具的明确身份初始化与新可选参数断言后，QA03四步骤通过，
3123pass/45明确skip/1024subtests/6既有collection warnings，测试165.15s、driver219.2396239s/exit0/reaped。
独立review01的两种跨阶段比较误判原样保留，review02严格逐原字段核对并纠正独立bootstrap/owned run ID比较后通过。
两次live之后只另改launcher的scope pin检查及一个未初始化native测试夹具；旧live执行身份不回写。
466个程序/测试/来源输入及17846个Git已知检查输入在QA期间前后不变；程序/测试最终字节与QA03一致。
本节与兼容文档的结果说明在QA结束后补写，没有冒充参与旧QA。
证据、失败及复现见[本轮固定包](validation/native_identity_scope_20261015/README.md)。M0–M5仍未完整签收。

## 真实PB比赛树最小接入（2026-10-15，历史起点，后续actual07见下文）

新增[真实BT scoped runner](../operator_native/pb_match_decision/README.md)，由BehaviorTree.CPP 4.6.2实际执行
固定PB `rmul_2025` 结构及原IsGameStatus/IsStatusOK/IsRfidDetected/PubNav2Goal C++节点；
Python peer只验证本地spec/ELF/XML/build/ENV/source后exec原runner，没有Python规则树替代。
prepare真实建factory/tree但0tick，reset仅原context；只有原decision observation v2触发一次真实tick，输出仍为原intent.v1。
navigation v3、原LIO/精确TF反馈、同scan compact act、原50/150ms及owned资源边界不变。

| 本轮实际资源/独立分支 | 事实与边界 |
| --- | --- |
| BT4 clean build | 43.4268秒，391源不变，实际构建4.6.2；没有tick或比赛验收 |
| protocol msg01/02 | 01因ROS_DISTRO环境失败保留；02耗时23.1202秒、17源不变，实际protocol-v1.7.0消息typesupport构建通过 |
| runner02/03 | 02缺`plugins.hpp`真实编译失败；03补完整固定头后45.853秒/exit0/reaped/loader通过，原失败不改写 |
| standalone01 | 真实原生5tick、原typed source/intent/节点事件闭合；healthy goal、hp199.9且RFID缺失hold、paused hold、e-stop hold、缺估计hold。输入为合成DTO，不算实际裁判触发分支 |

原XML SHA `68e216c145949538444bd8b9f9e97cc1b79b1536ddbc52a37eb00252e20c34f9`与原源保留；
owned XML明确5处overlay：两处spin禁用、原零Twist改source-bound hold、两处固定场地目标改首次估计anchor上的显式local waypoint。
ScopedPubNavGoal在本次tick内调用原`setMessage`并保存原返回/pose，不能订阅旧裸Pose后补本次身份。
RFID没有合法源，保留缺失并抑制该supply输出；不伪造NOT_DETECTED或真实补给事实。
原树没有基于导航receipt的完成guard，本轮不偷偷加synthetic finalhold；持续同几何intent与Nav2真实终态分别记账。
standalone原生SIGTERM关闭2.565ms、`protocol_interrupted=true`、tree/node/context实际关闭；
outer OWNED_CLEANUP独立证明原出生身份下group空/reaped，不把日志写完时刻叫完整I/O完成。

| 真树+导航注册实际 | 失败事实 |
| --- | --- |
| actual02 | 默认SDK cadence .05秒，7521个2ms步/受控15.0029724秒；2observe/2intent/2status、0估计/0goal/0motion，原host transaction deadline拒绝；SDK release/close Timeout，整体共享清理检查失败 |
| actual03 | 显式SDK cadence .02秒取得合法fresh授权，未改传感采样或150ms。7533个2ms步/受控15.0106135秒；16observe/16intent、15返回=2action+13status，1笔停止后中止；6精确估计/14LIO/3原生controller、2及时公开动作真实消费72非零步 |
| actual05 | 新实际代价地图起点门后149observe/149intent、148返回=5action+143status，1笔停止后中止；PUBLIC_CONSUMPTION匹配206非零步。但navpeer全部journal与decision Linux清理proof缺失，原生TF/UUID/终态审计无证，整轮FAIL |
| actual04 | 事务式拒发修复后15.006447秒受控、5119物理步，101observe/intent/status、95精确估计、101真实BT tick，0公开动作/0controller/0消费；无adapter fault，原共享清理检查全过，但运动验收仍FAIL |

03健康真实树节点产生6次原goal/setMessage事件，并有1个原目标起源匹配；这仅是实际局部事实。
随后50ms原stage超期约.739ms导致peer死亡/adapter RuntimeError，整体仍FAIL，
SDK release/close Timeout，runtime/pipeline/navpeer与shared cleanup不能判clean。
外层driver仍真实exit2/reaped/223程序源不变/无forced、Job最终空，外层 .0056381秒；
最终reap不覆盖内部资源/原期限失败。失败/原源见[02](../artifacts/pb-match-route-actual-20261015-02/RESULT.json)与
[03](../artifacts/pb-match-route-actual-20261015-03/RESULT.json)。构建和standalone原件分别在
`artifacts/pb-match-bt4-build-20261015-01`、`pb-match-interfaces-build-20261015-01/02`、
`pb-match-native-build-20261015-02/03`及`pb-match-native-standalone-20261015-01`。

普通expiry不再变格式/资源fault：候选动作严格验证后保留原candidate进REJECTED记录，
仅将其改为同source/intent/selection、controller UUID为空的`no_associated_command`，不发零速度、不刷新deadline。
generic staged peer先在独立history preview验证并编码，最终before_emit可仅将action降为有源status；
replacement再验证/编码，从原committed history重新preview，最终只提交实际wire响应。
callback拿detached副本，不能原地修改已编码消息绕过检查；write失败仍fault关闭，不重发。
action的最终50ms门在encode后/write前，status不获得额外动作权限，实际I/O仍受原host150ms约束。
source日志后越期也返回原source状态，保留原候选及独立stage_action_withheld事件；原source/scan/UUID/期限与原生接收记录严格核对。
actual04未触发迟动作，没有以本轮无故障替代迟动作现场分支证据；相应分支仍有注入时钟单元测试。
该轮原Nav2 planner日志明确首目标被“Start pose is out of costmap!”拒绝，随后地图扩张。
原生命周期刻意保留失败目标sticky、不自动重试；已补真实global costmap metadata与同次实际TF估计起点的bounds readiness，
helper的106项测试已冻结，但不是实际规划可行性证明。缺图/起点越界维持pending_navigation，等待后续原扫描，
不固定sleep、不clamp起点、不填地图或理想TF；原Smac仍自行规划。

actual05的137份available估计仅是公共feedback声明，不得写成137次原生TF/LIO精确认证：
navpeer的ROS_SOURCE/STAGES/ACT_RESULTS等journal在退出时全缺，原生来源、原UUID/目标终态、最终50ms门审计均不能闭合。
原生BT tick/公开action与206消费步的局部匹配不能替代这些缺件；decision Linux owned cleanup proof缺失也不能用native CLOSE或最终外层reap补造。
Root只读review05直接因缺ROS_SOURCE抛FileNotFoundError，没有raw审计pass，不隐藏此失败或重建缺失原件。
该次driver33.1418964秒/exit2/reaped/224程序源不变/无forced、最终Job空，仅证明外层最终收尾，不能改整轮FAIL。

已定位原ownedTree同时TERM leader与Nav2 children会打断leader的正常保存/协作清理，
正在改pipeline先向所有owned peer请求stop再等待，并由Linux owner先给leader最多.8秒协作窗口；
这消耗原总预算，不延长原1.17秒KILL阶段、Linux1.3秒或host共享1.5秒。
PB peer另补幂等signal、PRE_CLOSE快照及保存耗时，不能在缺证时先写clean。
以上为actual05之后的历史待验记录，后继06/07和最终QA15结果见下文；02–05均按原失败保留。

自有runner/glue为MIT，上游PB behavior/BehaviorTree.ROS2仍Apache-2.0、BT.CPP和protocol接口保留原MIT，
原许可证已逐字节留存，见[第三方声明](../THIRD_PARTY_NOTICES.md)。ELF/共享库不发布。
本轮没有关闭RFID/交战/感知/自瞄/自动火/完成策略/多车/Qt/长局/RTF/LAN/完整3v3/7v7或M0–M5；
先前synthetic注册成功和QA14只归其原源范围，不验证本轮真树联动。

## 真树与导航最终局部通过（actual07，2026-10-15）

[actual07](../artifacts/pb-match-route-actual-20261015-07/RESULT.json)的23项根检查全部通过；
7451个2ms物理步，SDK受控15.0050229秒，147observe/147真实C++BT tick/147返回（15action/132status），0中止事务、0adapter fault。
136份公开可用估计逐一匹配原LIO事件与原stamp TF，136次本tick原PB setMessage与真实意图对应；
唯一原目标、原navigation UUID、原scan/source/SDK与620个非零物理消费步逐项匹配。
15份实际action均有同原50ms encode后/write前门；最小剩余2.125745ms，不把门时刻当I/O完成。
原生候选有3份被抑制，其中2份真实迟动作在REJECTED保留，并只输出同source/intent/selection的无指令status；
147最终回执均与实际公开结果相同，迟动作来源无物理消费，后续帧继续运行。

独立[raw复核](../artifacts/pb-match-postqa-review-20261015-07/RESULT.json)校验15份原costmap metadata接收、
136份本次估计起点与原地图覆盖、1份原目标起源；7个未就绪估计保持pending，不补旧定位或真值。
这只证明原地图边界包含本次起点，不证明占据、路径可行性、精度或官方场地标定。
原XML的5处显式overlay仍在；RFID缺失、持续目标及无receipt完成策略的范围保持。

本轮显式CPython switch .001秒，实读生效并finally恢复原.005秒；SDK cadence仍.02秒、授权仍.15秒。
这是资源调度配置，不改变原采样/source/50/80/150ms；默认调度actual06曾在seq3宿主期限失败，
546步/1.2565519秒后停止、0动作；新关停已预算内clean，不回填为完整运行通过。
07 driver33.0109988秒/exit0/reaped/224程序源前后不变、无外层forced、Job空；
host共享收尾.9927301秒<1.5，原Linux1.3保持，正常关闭含PRE_CLOSE快照、最终完整日志与证书检查。
这次成功不能单独证明1ms是06失败的唯一原因，全部旧失败和各自源码身份保留。

最终[QA15](../artifacts/quality-aim-followup-20261014-15/manifest.json)四步骤全部退出0：
3041passed/45明确skip/1024subtests、6条既有collection warnings；pytest149.46秒，driver196.7534391秒/exit0/reaped。
460程序/测试/来源文件及13787检查输入在运行期间SHA不变；QA后只补本文/协议/runner说明与归档，不把新文案重标为QA当时原字节。
可校验副本见[永久证据](validation/pb_match_decision_20261015/README.md)。
以上是本机Windows/WSL、实际原PB BT与生产导航经通用注册接口的健康单目标局部通过；
移动自瞄、感知/自动火、Qt可见桌面、真实裁判负分支、长局、多车、LAN、RTF矩阵与完整3v3/7v7和M0–M5仍未签收。

## 估计导航反馈与真实PB通用注册（2026-10-15，先前synthetic决策检查点）

新增[导航反馈协议](NAVIGATION_FEEDBACK_PROTOCOL.md)：navigation capabilities v3显式协商staged_scan_v1，
先发送本次原始点云/IMU执行observe，再将完整原反馈嵌入decision observation v2，最后以同一原六身份和intent执行compact act。
act不重新发送传感器、不重复发布ROS bundle、不刷新capture或deadline；Linux原50ms stage从首次发布贯穿决策与取动作，
最终Linux50ms门截至响应encode完成后、write前；Windows原150ms SDK授权包含实际I/O。
跨域wall_deadline只回显；Linux局部资源与stage使用自身clock，不减Windows时钟。
原navigation v1/v2、decision v1严格形状不变，v2决策的perception仍unavailable。

真实PB生产者以原扫描定位事件的stamp查TFBuffer中map→base_link估计，返回stamp必须精确相等且在原扫描窗口内。
原Point-LIO/loam/SLAM链和producer/二进制SHA分别记录；schema只验证声明关系，实际来源由owned生产者与原ROS审计证明。
取不到估计或Nav2尚未ACTIVE时明确unavailable，不用真值/旧pose补齐。
goal_status仅保留实际当前selection及last8历史摘要，origin与续授权分开；终态不重贴当前source，cancel ACK也不等于stop。

| 本轮注册实际 | 事实与结果 |
| --- | --- |
| attempt01 | 被选venv解释器的正常symlink被通用无别名检查误拒，peer退出/宿主EOF，0物理步/0扫描/0目标；原失败不改写 |
| attempt02（旧程序） | 显式采用已固定ENV中的venv执行路径并保留其prefix语义，源/配置/输出仍严格无别名；当次16根检查全部通过，7534个2ms物理步，受控SDK跨度15.0125695秒 |
| attempt03（最终源） | 补齐source之后与encode后/write前同一原50ms门，17根检查通过；7522个2ms物理步、SDK受控15.0054443秒、138精确估计、580非零消费步 |

attempt02有149原observe/149意图/149结果，138份可用估计均与原LIO/原stamp TF精确关联；
动作21份、状态128份，147定位、23原生controller v2结果。唯一目标UUID
`c2239986a4db479fba6fb3ad28502ce2`的origin为seq13，续授权到seq71未改写origin，
由估计map x方向+1m的synthetic策略发起，真实succeeded/terminal/stop反馈随后驱动hold。
原UUID/source/action/SDK/物理审计闭合482个非零消费步；23个controller结果不能全称为实际执行动作。
149原stage中21个授权action stage，另1个原生action被抑制；没有以迟结果补新source或把status当零速度消费。

资源prepare用11.8283445秒完成真实peer ACK，此阶段0物理步/0传感器帧/0策略调用，无投样预热，
绑定仍真实reset与完整capabilities协商。内部29.8839658秒、独立driver30.207167秒/exit0/reaped/source unchanged，
driver核对220份程序源；runtime join .6848829秒，Windows Job真实1→0、无forced、所有peer/HTTP/线程在原共享host1.5秒内clean，Linux1.3秒保持。
证据入口为[actual02 RESULT](../artifacts/registered-pb-goal-actual-20261015-02/RESULT.json)、
[driver](../artifacts/registered-pb-goal-driver-20261015-02/RESULT.json)与
[peer原件索引](../artifacts/registered-pb-goal-actual-20261015-02/PEER_EVIDENCE_INDEX.json)。
当次02没有被重标为补强后源身份。最终03见[RESULT](../artifacts/registered-pb-goal-actual-20261015-03/RESULT.json)、
[driver](../artifacts/registered-pb-goal-driver-20261015-03/RESULT.json)和[peer原件](../artifacts/registered-pb-goal-actual-20261015-03/PEER_EVIDENCE_INDEX.json)：
149原observe/149意图，148份实际返回（14 action/134 status）；1笔事务在control-stop后中止，不能称149完整返回。
138份估计全部精确匹配原LIO/TF，147定位、15原生controller结果；唯一目标
`c3fd85680bf54d459868d1c6ede6c6ff`的origin seq13和续授权seq35分开保存，真实succeeded/terminal/stop后feedback驱动final hold。
580非零消费步逐UUID/source/action/SDK回执闭合；14份public action均有对应同deadline最终encode后/write前门，
无缺失或多余gate；不把该门记录称write完成时刻。另1个原生action被抑制，保留原记录。
资源prepare11.8818648秒/0物理0扫描0策略；内部29.9700689秒/driver30.3152588秒，220程序源不变/exit0/reaped/无forced。
runtime join .7700017秒，peer内部收尾 .428730679秒（Linux本地计时，不与Windows相减），
外层Job实际1→0、总外层清理 .0052197秒；原host共享1.5秒/Linux1.3秒保持，全资源clean。
最终QA14四步骤全部退出0：2788项通过、41项明确跳过、1024子测试通过，6条既有collection warnings。
driver耗时186.8611387秒，已reap，452份程序/测试/来源文件SHA前后一致；quality记录12084份输入在检查期间未变。
本段QA结果为检查完成后补写，程序未再改动；不会把新增文档文字重标为QA期间原字节。
最终14份编码后门另经独立raw复核，最大41.657967ms、最小余期8.342033ms；
580份物理消费全部匹配实际公开action、原UUID/扫描/SDK，status与关闭中断源均未消费。
本地检查原件见[QA14](../artifacts/quality-aim-followup-20261014-14/manifest.json)，
可校验交付副本见[永久证据](validation/registered_pb_feedback_20261015/README.md)。
当前peer各诊断journal上限8192条，10Hz多事件STAGES约136秒可能触顶且明确失败，不是分钟级完整比赛入口。

这是本机Windows→WSL的真实PB导航加synthetic高层决策注册单目标局部通过：
不证明PB比赛树、该注册路径取消/替换/第二目标、定位精度/真实光学标定、RTF、相机/自瞄/射击、Qt/可见桌面、跨机DDS或完整3v3/7v7。
T01冻结条件、T04/T05移动自瞄与角色扩展、T06矩阵、T08车辆策略、T10/T11规则/资产、T12/T14整局、
T13两机、T15整场复演、T16换机/发布、T18硬件仍按上表，M0–M5均未签收。

## 通用当前目标授权插件（2026-10-15，先前检查点）

新增[active-goal插件版本](ACTIVE_GOAL_NAVIGATION_PLUGIN.md)，本地manifest显式声明capabilities.v2和
navigation-goal-result.v1；保留旧capabilities.v1的严格契约。新结果同时保存本次原intent/六身份、当前操作receipt、
原计算回调独立给出的真实goal UUID与原action或status。只有当前navigate、同目标几何、续授权恰为本次原六身份、
active非取消非terminal、原计算UUID匹配时输出动作；hold/cancel不制造零动作。
宿主仍仅放行原action DTO，新的receipt不扩大SDK授权；历史记录拒绝改写origin/UUID、逆转取消/终态及复用UUID。

通用GoalNavigationCompute接入原异步生命周期，提交后与计算后分别检查当前操作，外部executor仍由调用者拥有；
不比较foreign墙钟、不延长原50ms导航/80ms图像/150ms窗口。未来操作在旧scan结果中不作selection，
selection=None仅表示本次无可授权选择，不代表真实active已取消或停稳。cancel ACK仍不等于terminal stop。

新增模块最后专项190项通过，均exit0/reaped/source unchanged。actual01内部20检查虽过，
外层Job非空触发forced清理，整轮严格失败保留。actual02在原1.5秒清理期限内实测Job1→0/5.1622ms，
无强制终止、20检查通过、220程序源前后一致：4秒/2000物理步，红28个action/792非零消费步，
蓝28个status/0 action/0 motion消费，四独立peer与SDK/HTTP/IO均clean。
这是synthetic高层策略/UUID/常速度的真实低率MuJoCo协议路由，不能当真实Nav2/定位或比赛。
另加PBGoalControllerSource从同一原生v2回执保留UUID，26项受控测试通过，不改旧桥/配置。
后续审查发现02外层reader join仍单独给1.5秒；该脚本与当次实际快速结束记录原样保留，
未把旧记录重标为新共享期限验证。独立03把Job查询、reap、reader join与handle释放合用同一1.5秒deadline：
20检查通过，28个原action全部有实际消费/2473回执/828非零物理步，蓝仍28status/0action/0motion消费；
runtime join .0541796s，外层总清理 .005654s，Job1→0→final0、reader停/handle释放/exit0/reaped，无forced，220源不变。
最终QA13四步骤0，2550pass/41明确skip/1024subtests/6既有warning，pytest141.63s、driver182.6746119s，
435份程序/测试/来源文件前后相同；结论为checks_passed_not_milestone_acceptance。
本段QA结果文字在检查完成后填写，不宣称检查测试过事后报告文字。代码与所有原失败/执行源见
[永久证据](validation/active_goal_plugins_20261015/README.md)。真实PB原生UUID hook已另有下节所述先前证据，
当时新通用版本的PB资源所有者、实际注册组合、决策估计反馈仍待验证；本轮后续单目标进展见上节，协议fixture本身不能替代队伍算法。
当前无新增自瞄图像、移动瞄准、自动火、完整3v3、LAN、RTF或M0–M5验收。

## 真实目标 UUID、速度与物理消费关联（2026-10-15，先前检查点）

新增[服务端来源说明](NAV2_GOAL_VELOCITY.md)，在原Nav2 1.1.20控制器调用前捕获真实accepted handle/UUID，
算法计算期间不持该锁，发布v2来源结果前在真实server mutex内核对同一handle/UUID、active、cancel已接受/状态、pending/preempt。
没有把外部“最新目标”贴在旧Twist上；原插件异常路径制造的零速度也不进入v2来源结果。
独立namespace/单executable避免加载另一份controller_server_core，原PB PID ELF与旧11资产原件保持。
新配置仅换用新server ELF；新wire profile显式协商，默认v1继续严格拒绝v2，反向亦然。
源形状新增goal_uuid，物理action仍为原六身份和原velocity_body，不扩大SDK权限或期限。
桥本身只证明schema/来源守卫，不知道哪些UUID由本高层授权；独立审计再匹配原accepted目标、完整typed action与SDK/实际消费回执。
同一六身份关联多个UUID即歧义拒绝，不以latest覆盖。历史目标来源不刷新为后续authorization。

新独立构建116.925秒、3条CMake命令exit0/reaped、loader全resolved，ELF
09e70405510db579cacbf00d456391d89fdf6ce041fbc860fbc04f562993e53f；12项专项含真实C++门禁执行通过。
桥新旧57pass/23subtests；目标来源审计最终92pass/35subtests；均是对应单元/受控过程，不能当ROS闭环。
root配置/worker专项早期28pass/10明确skip/18subtests；后续配置roster及地图修补由新actual03和最终QA验证，未改旧日志身份。

| 新实际试验 | 事实与结果 |
| --- | --- |
| actual01 | 新v2 config字段未加入exact roster，READY前拒绝；无Qt/传感器/目标，失败与清理原件保留 |
| actual02 | 配置roster修复后真实server active，55原请求/53LIO，但真实全局地图持续outside；0目标/0controller/0导航，原TimeoutError安全关闭 |
| actual03 | 新显式stationary_scan_accumulation_v1配置，26根检查全过；15.0010015秒GO、238手动批全部消费/4473步，90请求/88LIO/27控制器、463非零导航步、387同一步两车非零 |

actual02真实planner仅1次resize/41次outside；旧上一轮actual04为6次resize/初始2次outside，不能归因于probe缓存。
原SLAM2.6.10移动门槛会在静止时阻止追加扫描；现有日志未直接记录每scan是否被接纳，因果解释据参数/日志/官方源码推断。
新配置只把minimum_travel_distance/heading从.1改0，保留time interval .2、map update .5、use_scan_matching=false、原滤波/PID。
仍由原SLAM累积真实扫描，不填充地图、不clamp起点、不重标TF；最终原raw map几何/数据SHA保留。
长期内存/栅格重算和性能矩阵尚待测量，本轮不以短SIL关闭该开销问题。

actual03首目标origin seq15，UUID32b1248f593b45f88f6fcf1c3f37ed79有2真实controller结果/25非零物理步，
hold取得真实cancel ACK+terminal stop后，origin seq18第二目标4d4b00dd4aa94040a9b9367488979a98有25结果/438步并成功。
原来源/UUID/动作与消费全部匹配，无歧义；action终态不宣称编码器测得零速，合法原150ms授权历史消费仍单独保留。
内部35.2830733秒/driver37.4271006秒/exit0/reaped/source unchanged/无强制直接终止，
runtime join .5917298秒、外部owner .3981158秒，原Qt/HTTP/相机/SDK/ROS组在原共享host1.5秒/Linux1.3秒内clean。
这是实际离屏两车、合成高层goal/hold策略与真实PB导航的来源闭合；无新自瞄/比赛树/可见桌面/RTF/LAN/完整对局验收。
原80ms图像/150ms控制、50ms导航、reset2秒和graph1秒保持。[独立永久包](validation/goal_velocity_20261015/README.md)保存构建、失败、成功、来源和清理证明。
最终QA12四步骤exit0/source unchanged：2360passed/41明确skip/1024subtests/6已有warnings，pytest142.76秒、
driver179.1218684秒/reaped，显式原CPU4 WSL spec无回退；424程序/测试/provenance原字节保持。
QA后仅本文结果补记、封存及Git交付，未声称新封存文件或此补记参加此前QA；其余T01–T18/M0–M5边界保持。

## 通用导航目标生命周期与真实取消确认（2026-10-15）

新增[goal-only生命周期说明](NAVIGATION_GOAL_LIFECYCLE.md)和两个显式Nav2后端：NavigateToPose，或
ComputePathToPose→FollowPath。核心只接收原decision-intent.v1，调用者拥有ROS节点/执行器并串行poll，
不阻塞等待、不发布传感器/速度、不获得actuator或真值权限。shape检查不伪造own/referee，
正常决策契约仍先验证原observation并逐字段严格匹配六身份。
新目标替换先取消旧目标，只有真实终态及stop证明才启动后继；cancel ACK本身不算终态。
原goal intent/UUID保持历史身份，后来新采样只更新authorization，不把旧成功重新标成当前帧。
host模式检查原期限；Linux opaque模式不比较Windows时钟，原传感器/控制器/SDK期限仍独立约束实际运动。
该先前goal-only第04轮当时还不是已注册的通用goal-aware速度插件，使用旧scan controller来源，未关联goal UUID；
当时也未接真实PB比赛树或导航估计反馈。后续UUID与注册反馈增量见上节，decision v1导航/感知仍保持unavailable。

| fresh实际探针 | 结果与保留失败 |
| --- | --- |
| actual01 | peer导入缺ROOT路径，READY前失败；没有Qt/传感器/目标，Linux空组与缺client协议证明分别记录 |
| actual02 | 真Qt15.021秒、97原请求/95LIO但0目标/0导航；当时缺定位诊断，未倒填根因 |
| actual03 | 新诊断证明map/3-3 active/后端ready后真实目标已接收；Humble NumPy UUID被误拒，0导航，fault/unclean保留 |
| actual04 | 严格支持uint8[16]原UUID后，15.0248667秒、239手动批全部消费/4779物理步，95请求/93LIO/26控制器、448导航非零步、376同物理步两车非零；25根检查全过 |

UUID兼容仅接受bytes/bytearray/array('B')、严格Python int序列或exact NumPy uint8形状(16,)，
float/bool/错dtype/错shape仍拒绝。accepted handle独立保留，即使元数据失败也真实cancel并监视GetResult，
只允许一次额外只读getter请求，不重发goal/cancel；未知UUID或缺终态继续unclean。
actual04第一目标原seq16，hold原seq18，真实取消ACK/terminal/stop均确认后，seq19第二目标才发出并成功；
后续authorization seq17/42不覆盖origin。目标来自实际算法TF相对1米的合成高层策略，
TF原stamp和传感器source分开记录，不称同一扫描定位反馈或真实比赛树。
实际PB仅验证ComputePathToPose→FollowPath，NavigateToPose模式只有受控Future回归。
原80ms图像/150ms控制/50ms导航、reset2秒、Linux1.3秒及host1.5秒未改。
04 runtime join .5527946秒、外部owner .444508秒，原Qt/HTTP/相机/SDK/ROS组全部在共享原预算内退出；
内部34.7467119秒、driver37.0327612秒/exit0/reaped/source unchanged/无强制直接终止。

新生命周期38项、后端最终36项focused回归通过；早期schema/operation str子类两失败和各版本来源保留。
focused02当时执行的旧生命周期源码只保留实际SHA与日志，没有在修复前捕获完整字节，明确缺失而不重建冒充原件。
本轮失败、实际source/goal/rawROS/画面与收尾证明保存在[独立永久包](validation/navigation_goal_lifecycle_20261015/README.md)。
最终QA11四步骤exit0/source unchanged：2252passed/40明确skip/1024subtests/6已有warnings，
pytest138.65秒、driver170.0997353秒/reaped；显式同一CPU4 WSL spec，无回退，417程序/测试/provenance原字节保持。
QA后仅本文结果说明、封存及Git交付，未声称新增封存文件或此补记参加此前QA。
T01–T18其余缺口及M0–M5状态保持上表，无新自瞄/自动火/完整3v3/7v7验收。

## 原手控步兵与真实PB导航同场（2026-10-15）

新[独立联合探针](COOP_PLAYABLE_PATH.md)复用原第五客户端、Qt手动按键/鼠标/两F2和真实HTTP相机，
另一个独立credential、red_sentry motion lease和原SDK授权真实WSL Point-LIO/SLAM/Nav2/PB PID。
准备阶段physics/sensor为0，没有预喂算法；只有原Qt手动arm后才授权导航，实际ray/IMU配置200000points/s。
人工SDK原window/lease/seq/值/expiry与导航原cloud/LIO/controller/SDK150ms分别审计，
重叠用同一Windows host GO/F12区间、原2ms物理步，不拼接单车记录或转换Linux时钟。

只读实际预检11个ELF、22份配置/来源引用、ext4/Python3.10.12与原HEAD匹配；预检没有启动ROS/GL。
rclpy XML版本缺失只记null，不能据此称模块缺失；后续实际运行独立证明ROS导航。
并行清理helper只调用exact可信owner的原close，保持各Linux1.3s和同一host1.5s；
回收迟到、异常、未退出线程、错出生身份或即使已赋值的部分receipt都不能变clean。
runtime仍独占导航close，helper仅外部goal owner，避免竞态；11项/14subtests夹具不冒充实际WSL回收。

| 实际运行 | GO秒 | 原手动批/全部消费 | 手动物理消费步 | 原导航非零步 | 同物理步两车非零 | 传感器请求/LIO/控制器 | 相对目标 | 内部/driver秒 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| joint01，旧descriptor | 5 | 82/82 | 1573 | 426 | 314 | 32/30/25 | 完成 | 24.5963907/26.7151630 |
| joint02，旧descriptor | 请求30、.802秒失败 | 15/15 | 282 | 0 | 0 | 1/0/0 | 未启动 | 16.8635494/18.9804055 |
| joint03，reset策略 | 30 | 486/486 | 9904 | 476 | 410 | 198/196/28 | 完成 | 48.9283522/51.1370498 |

02原首reset约134.8ms，原采样余期不足50ms；首act响应越过原截止而TimeoutError，0导航消费。
独立observer未完成退出2；原Linux group证明空/reaped/no kill，host严格零退出检查仍unclean；两者事实分别保存。
Qt在W不足1秒时失去控制护栏并退出，不能报告30秒成功。所有source/失败/阶段和各清理证明原件保留。
仅PB导航descriptor启用已有通用discard_reset_observation_v1：context-only reset成功后丢弃旧和期间排队采样，
等待原frame/sim/hostcapture真正新样本，同实例、原身份和期限不变。runtime、算法、原50/80/150ms均未改。
实际Registry/WslNavigationAdapter/AdapterSlot配显式stub的专项最终17pass；含旧无policy只剩16ms超时、
新第一/排队采样不变丢弃与新样本原六身份接受、伪换frame/sim/hostcapture拒绝、reset失败sticky。
首轮5pass/1fail为旧queue.get已阻塞造成新测试hook未观察到消费，Event同步修正，原失败及后继16/17pass保留。

01及03全部25根检查、两独立审计通过；目标来自真实算法估计map→base TF相对1米，真实planner/path完成，
禁止世界真值回流。03原GO/F12间隔30.0193222秒、11对按键、1502guard、诊断丢弃0；
Qt清理.0454841秒、runtime join .5303054秒、外部owner .4157285秒，所有Job/ROS群组/IO/HTTP/SDK/相机在原预算内clean。
host/Qt CV4与CPython1ms实读还原，source unchanged/exit0/reaped/no forced direct termination。
目标完成后原无动作状态合法，不能说两车30秒始终运动。这是离屏两车单目标协同SIL，
无比赛树、自瞄/NN/自动火、可见桌面、RTF性能矩阵、LAN或完整3v3/7v7；其余四车没有替代策略。
继续通用goal/hold/cancel、有来源的估计/裁判反馈和比赛树连接；T01–T18/M0–M5完整资格仍按上表。

代码、所有三个实际原源/失败/画面/回执/时间/退出及质量记录见[新永久包](validation/qt_pb_coop_20261015/README.md)。
最终QA10四步骤exit0/source unchanged：2178passed/40明确skip/1024subtests/6已有warnings，
pytest137.19秒、外层driver167.9643966秒/reaped；使用同一显式CPU4 WSL spec、无回退，409程序/测试/provenance文件不变。
第五客户端和所有旧档案/补丁原字节保持，QA后仅结果说明、封存和开发分支Git交付。

## 原相机顺序修复与实际手控30秒（2026-10-15）

新手动探针使用原 PlatformWindow、真实 HTTP MuJoCo 相机、Jello Manual、watch/own HUD、原两 F2、
普通 W/S 和实际鼠标事件，由原 timer/input bridge 产生完整 SDK motion/gimbal/fire 指令。
无导航传感器/算法、ROS/NN或自动激活。独立审计按原 window/lease/seq/值/expiry 与实际 integration-entry 消费回执匹配；
世界真值仅在隔离 EVAL 中。手动 fire 始终 false，未验收实体射击。

第四客户端两次实际尝试均失败并保留。01 记录 camera-loop ValueError，原详细消息缺失，不能确定同一根因；
13批/379消费步后撤权，W不足1秒，未完成S。原RESULT混淆非零exit与Job清理，但原CLEANUP单独证明空树/回收，未回写。
02 新增透明异常观察后确认原消息 Camera time is ahead of state：frame21/episode0/watch1，
capture4.064、HUD/state4.010，相差54ms，而frame原年龄仅30.5035ms。
7批/116消费步后撤权；父级qt_wait TimeoutExpired亦保留，即使随后Job空/回收也不能报告通过。

第五完整基线补丁在验证元数据/JPEG/原TTL后、最终锁内重检身份/顺序；合法超前帧暂不安装，等待原HUD追上，
不刷新帧序号/视频/HUD/时钟锚/期限。原50ms对齐、显示TTL、算法80ms和SDK150ms均保持，
损坏/倒序/真实过期/身份变更仍拒绝，解码期间切watch/session/episode不能装旧帧。
旧四个客户端checkout/patch/manifest保持逐字节；新完整patch从固定0ced基线应用，inspect/reverse检查通过。

修复前后源码、复现和全部夹具失败保留。首轮审计测试1fail是request/receipt目标别名，改为deepcopy后13负例/匹配测试通过；
客户端最初before/focused fixture写4.010在4.011之后属测试顺序错误，后继before02才是旧产品ahead异常复现。
新12项/16subtests通过；第五客户端完整30模块496passed/363subtests/0skip，pytest21.83秒、driver22.2994786秒，
源不变、owned Job/reader回收。

| 原窗口实际运行 | GO秒 | 原SDK批量/全部消费 | 物理消费步 | 正向/反向x步 | 非零云台步 | 内部/driver秒 |
| --- | --- | --- | --- | --- | --- | --- |
| manual03，第五客户端 | 5 | 86/86 | 2511 | 1491/538 | 2511 | 11.4622931/13.4840867 |
| manual04，第五客户端 | 30 | 479/479 | 15028 | 7977/6502 | 15028 | 36.7661493/38.8301222 |

两次全部15根检查与原guard/ACK/receipt通过，exit0/source unchanged/无强制直接终止；原F12/release/close和所有Job/SDK/HTTP/相机clean。
04最初W/S各持有1.006838/1.011714秒，11对原按键、鼠标14/8像素、477变化云台ACK、1502护栏检查，诊断丢弃0，
Qt清理.0446569秒小于原1.5秒。host与Qt显式CV4/CPython1ms实读并还原；没有放宽任何门限或机器调度系统配置。
这是实际离屏手动SIL，未验收可见桌面、队伍导航/决策/自瞄、RTF/精度/射击、LAN或完整比赛。
新[手动配置](../examples/coop_camera_order_manual.json)仅dry plan通过；完整可见启动验收仍待做。

只读复核PB原配置/源码身份，不是新ROS/构建/队伍运行。历史真实Point-LIO/Nav2/PID单目标使用200000points/s ray/IMU，
现有goal wrapper仍缺通用decision_intent_v1 goal/hold/cancel及完整估计反馈；不得用最新TF/真值补齐。
下一实际场景为人工步兵与真实导航哨兵并行，再补有原采样身份的估计/裁判反馈和比赛树。
T2历史显式静态live、PB图像超80ms和同济无live图像的边界保持；T01–T18/M0–M5按上表，未签收完整对战。

最终统一QA09四步骤exit0/source unchanged：2160passed/40明确skip/1010subtests/6已有warnings，
pytest135.89秒、外层driver166.0306523秒/reaped，显式同一CPU4 WSL spec，无回退。
本轮完整代码、失败/通过、实际画面、源/时间/清理/质量保存在[独立永久包](validation/manual_camera_order_20261015/README.md)。
QA后仅结果说明/归档/Git交付，全部程序/测试/provenance与第五patch/MF保持已测SHA。

## 原窗口批量提交与短时物理协议通过（2026-10-15）

为解决原Handoff对多个真实HTTP往返预测157ms而超过150ms的问题，新增明确协商的
[control_batch_v1](CONTROL_BATCH_INTERFACE.md)。完整三通道的原租约/window/绑定/序号和值先全验证再原子提交，
任何成员失败不推进其它输入；保持独立手动fire、当前lease/window期限、旧单条接口和原时间门限。
SDK完整typed ACK、重复JSON键、窗口request-start与每个entry原expiry相对界逐项拒错，不重放。
Qt仍等原窗口ACK后新采样；仅batch能力下记录真实batch RTT会话上界，保留原window/采样20ms/唤醒5ms/余量5ms成本。

后端36专项通过，含真实锁等待/验证后过期、完整原子失败和实际HTTP；SDK53项含实际HTTP回归通过，
driver3.4094219秒/exit0/source unchanged/OwnedJob空且回收。第四客户端从固定0ced基线导出新完整补丁，
旧三个checkout/patch/manifest逐字节保持。29模块484passed/347subtests/0skip，pytest21.72秒/driver22.2378568秒；
全部owned线程/子进程clean且源不变，另21项batch专测和17模块351pass/141subtests原记录保留。
peer最初将合法seq0视为错误的纯代码问题在实际运行前修复，12个AST提取原hook/真实SDK ACK0负例检查通过；
保存修复前后源与记录，没有伪造一次Qt实际失败。

两次独立原PlatformWindow实际通过，使用显式host/Qt CV4、CPython1ms，实读后还原；
真实HTTP相机画面、Jello选择、watch、新own HUD、原两F2/焦点/输入与SDK期限均保持：

| 运行 | 实际batch ACK | 独立策略动作 | 非零物理消费步 | receipt | 内部/driver秒 |
| --- | --- | --- | --- | --- | --- |
| batch01 | 53 | 21 | 543 | 1621 | 10.6882914 / 13.5278223 |
| batch02 | 49 | 21 | 601 | 1798 | 10.1062680 / 12.1504109 |

两次原3秒GO测量后F12/release和close ACK、原typed6/SDK150ms join errors=[]、0adapterfault、source unchanged，
所有owned Job/SDK/HTTP/相机在原预算内clean；02 runtime join .0412382秒。
它们是offscreen内部show、实际MuJoCo2ms步长/1000points/s ray/IMU、两个合成JSONL策略的短时协议SIL。
没有ROS/NN/WSL/队伍算法、可见桌面、raw aim80ms、长时/RTF/SLAM/目标到达或整场比赛验收。
此前原窗口01–03失败及清理缺证保持原字节，新通过不覆盖旧失败。

最终统一QA08四步骤exit0/source unchanged：2147passed/40明确skip/1010subtests/6已有warnings，
pytest137.46秒、外层driver170.4405427秒/reaped，显式同一CPU4 WSL spec，无回退。
实际代码、完整source/失败与修复前后、两次原窗口/画面/时间/清理和质量记录在[独立永久包](validation/control_batch_20261015/README.md)。
QA后仅结果说明/归档/Git交付，程序、测试、DEVELOPMENT_CHANGES与第四patch/MF保持最终已测SHA；
历史包和旧三客户端保持。T01–T18/M0–M5仍按上表逐项资格，不能以短时协议通过签收比赛。

## 原身份、注册竞态与客户端租约修复（2026-10-15）

canonical action对六项source identity同时比较类型和值，拒绝int/float同值互换及bool；既有错误码与合法原时间戳保持。
导航canonical、自瞄canonical和实际AimPluginAdapter响应路径21项专项通过；修复前错误放行与修复后拒绝原记录均保留。
通用graph注册在临时Registry内执行，核对实际注册返回的manifest哈希，并在发布前重检graph与全部组件；
失败不改变原catalog/spec/factory对象，不执行factory。内存和实际文件交错、迟到修改、容量/组合失败18项通过，
此前A scope/hash和B descriptor混用的复现保留。没有改变nav/aim算法、ROS桥或任何期限。

[第三客户端组合补丁](CLIENT_ROBOTIO_INTERFACE.md)从同一固定基线独立导出，前两patch/manifest/checkout保持原字节。
仅丢弃同episode且三个完整typed lease epoch均低于claim ACK的旧快照；不刷新HUD/时间锚、不释放新租约。
混合/缺失/bool epoch、当前owner不符、更高epoch真正撤权仍fail closed，claim不自动arm。
16模块完整原Qt offscreen回归330passed/103subtests/0skip，pytest11.94秒、owned driver12.4185秒/source unchanged/reaped；
纯transport竞态复现及所有中间失败保存，不能据此将第一次真实窗口失败归因于该竞态。

新增原PlatformWindow实际探针，保留原HTTP工业相机画面、watch/Jello、两F2、新own HUD、Qt焦点/输入、原SDK窗口和消费账本。
它只在offscreen内部show，使用1000points/s实际ray/IMU与两个合成JSONL策略；不含ROS/NN/WSL/队伍算法/可见桌面。
三次整体均失败：01第一次F2后撤权、无足够原原因码；02已绑定并有2独立动作/27非零步，随后原Handoff预算压力，
probe晚清理导致Qt Job回收未证明。03修正护栏失效立即收尾，选择第三补丁并显式host/Qt CV4与CPython1ms，实际核验并还原。
03完成真实画面与全部原guard、38 SDK激活、11独立动作、477receipt/159非零步、原typed6/SDK150ms审计无错误；
GO后2.424秒原预测157ms超150ms而撤权，cost最大window31ms/pulse32ms/control32ms，未放宽原预测或门限。
03 driver11.7951674秒/exit2/reaped/source unchanged；所有owned Job/SDK/HTTP/相机在原预算内clean，runtime join .0487345秒。
03清理成功不覆盖02失败，不把原窗口局部运动记为持续全链通过。下一步减少真实HTTP往返成本并验证持续控制；
决策定位/感知反馈仍待版本化实际算法估计来源，禁止从真值补齐。T01–T18及M0–M5其余资格保持上表边界。

最终统一QA07四步骤exit0/source unchanged，2076passed/40明确skip/1010subtests/6已有warnings；
pytest141.08秒、外层driver177.9324741秒/reaped，显式使用同一CPU4 WSL spec，无回退。
本轮代码、原失败/实际相机画面、各次源码与完整质量结果见[独立永久验证包](validation/robotio_state_qt_20261015/README.md)。
QA后只增补结果说明、封存和Git交付；程序/测试/DEVELOPMENT_CHANGES/补丁维持最终已测SHA。
没有将归档、文档或本轮失败写成队伍live、持续可见客户端或比赛通过。

## Qt 通用目录与初始化时序修复（2026-10-15）

[客户端通用接口](CLIENT_ROBOTIO_INTERFACE.md)说明新的显式组合补丁、安装及 launcher 配置。
原默认客户端 patch/manifest、旧客户端副本与全部已发布证据保持原字节；新补丁从同一固定客户端基线应用于独立 review checkout。
目录按 typed capability、transport、scope 和空 config 识别通用 navigation / decision-navigation pipeline，
WSL 自瞄声明也可被选择；没有队伍白名单，没有新增 HTTP executable/cwd/config 权限。
launcher 可选择 graph、显式 WSL prepare 和补丁 manifest，原字节冻结后分阶段重检，不自动绑定、发目标或开火。

实际 PySide6 offscreen 全客户端回归为286passed/91subtests/0skip，pytest14.58秒、外层15.155秒、owned child clean；
这是原 Qt 事件与 guard 回归，后端为测试夹具，不证明物理、算法或可见桌面。
新 Qt 控件→客户端解析/计划→HTTP→SDK→MuJoCo 协议 harness 第二次通过：1750步、26原独立动作、
3736条receipt/1247非零消费步，typed6/SDK原150ms join errors=[]；1000 points/s实际ray/IMU，两个合成策略进程，
内部7.0027297秒/外层8.9554348秒、source unchanged、全部owned tree/IO/SDK/HTTP clean。
实际资源prepare .4174462秒且无观测/推理，runtime join .0232754秒。完整记录见[新永久验证包](validation/client_robotio_20261015/README.md)。

首次 Qt 物理尝试因 create/reset 后首原帧剩余期限不足，在compose响应前过期而严格fault，整体失败、0运动；
原日志/source/timing/cleanup保持。修复仅对显式通用导航策略：成功reset后，按原frame_id/sim_time/host capture_wall丢弃初始化前及期间排队的采样，
等待独立新采样继续同实例；原六身份/80ms图像/150ms控制窗口不变，reset失败仍fault，不造零速/hold。
时序专项最终43passed/2已有warnings；首次测试fixture的5fail/38pass仅有tool摘要与当时源，说明原stdout未保存，不伪造完整失败日志。
launcher选项专项53passed/1.1878273秒只验证mock；此后修正带`..`的config路径冻结为canonical路径，并由最终统一QA验证。
协议harness保存自己当时的launcher源码，不将旧SHA改写为该后继CLI路径修正已测。

新控件harness未运行原PlatformWindow、相机/GL、原F2/watch全链、ROS/WSL或队伍算法；
没有本轮完整可见启动、SLAM/目标到达、NN/RTF、自动火或整场3v3资格。
T2/PB历史局部通过、PB80ms失败与同济图像缺口保持；T03/T07/T13/T17继续推进，M0–M5状态不变。

最终统一QA06四步骤exit0/source unchanged，2037passed/40明确skip/1010subtests/6已有warnings；
pytest148.02秒、外层driver191.7993803秒/reaped。显式选用原CPU4 spec，未自动回退算法或放宽任何门限。
QA后仅本文结果说明和新永久包增补，程序/测试/DEVELOPMENT_CHANGES/补丁维持已测SHA；
不声称QA后加入的归档或说明文本参与了此前质量检查。

## 通用接口此前交付范围（2026-10-14）

用户最新明确要求各家导航、决策、自瞄通过通用接口接入；北极熊、T2、同济只是验证实例，不构成队伍白名单。
按[通用插件接口](UNIVERSAL_PLUGIN_INTERFACES.md)推进配置、能力协商、原传感器关联、各队包装和独立算法验证。
自有客户端手控步兵 + 北极熊哨兵的[3v3 路径](COOP_PLAYABLE_PATH.md)保留为后续组合验证场景，完整对战尚未通过。

新增通用层的验证与永久证据在下一节；以下 Windows 手动入口、图像传输与比赛树审计是此前交付记录，资格保持原范围。

## 通用组件与协议物理验证（2026-10-14）

[接口与可执行示例](UNIVERSAL_PLUGIN_INTERFACES.md)公开 navigation、decision、aim 独立目录与本地 manifest graph；
`GET /v2/plugins` 按服务器 admission scope 返回能力，SDK `bind_pipeline` 在已有 motion 租约下组合决策和导航。
决策只输出 `navigate_to_pose` / `hold` / `cancel` 意图；导航只消费本车真实点云/IMU和本次意图，输出 body velocity；
自瞄仍由原工业相机图像/标定/曝光状态得到 yaw/pitch。通用角度映射支持 rad/deg、轴符号、偏置和曝光/惯性坐标。
新组件不按队名、颜色或角色分派，scene 中必须存在所声明机器人；旧 native 的 stationary red_sentry 限制另待移除。

新增 JSONL peer、ROS 2 envelope 与 owned WSL 资源准备均保留原六项 typed identity、原 wall/sim deadline，
实际 reset 对比完整 capabilities；两组件共用 2 秒 reset、1.5 秒清理，而非分别延长。协议审查修复三个注册/资源缺陷，
以及 hold/cancel 后导航回非零速度的缺口：仍将停止意图交给导航真实取消，但 host/peer 拒绝非零结果，不自动贴零。
停止专项 60 项通过，含两个真实违规本地子进程的拒绝与完整回收。此前各组件专项和初次组合失败均保留。

[永久验证包](validation/robotio_plugins_20261014/README.md)分别保存以下原记录与源码：

- 实际 Windows→WSL→Humble DDS03：两类 prepare ACK、reset <2 秒、原 source echo 五项通过；内部驱动 7.906444 秒，
  外层 8.0219407 秒退出 0/reaped/source unchanged，Linux/Windows owned tree 与 IO 线程 clean。
  输入是合成 codec fixture，不是物理传感器或队伍导航。首轮 supervisor Python 缺 NumPy、Linux group 未证明回收的失败保留；
  第二轮显式选择已核验 ext4 Python 后通过，第三轮绑定最终停止语义源码再通过，没有改装依赖或拼接旧失败。
- 双车 MuJoCo 协议 SIL03：1771 步/3.542 秒仿真、原 2ms 步长、显式 1000 点/秒实际 ray/IMU；
  四个独立 stdlib JSONL peer 在物理启动前真实 prepare 0.6567465 秒，没有观测/策略或虚假推理预热。
  两套独立供给/热量决策 fixture 经 goal-aware 导航 fixture、SDK 与安全仲裁到实际执行器；每车 26 个独立原动作，
  红步兵 2799 条 receipt/935 个非零消费步，蓝哨兵 2940 条 receipt/980 个零速消费步；原身份/SDK150ms join errors=[]。
  内部驱动 5.8676381 秒、外层 6.1212747 秒退出0/reaped/source unchanged；runtime join .0387555 秒、
  四子进程/HTTP/SDK 线程全部 clean。世界位置只在独立 EVAL，不给 peer。
  它是资源预准备 harness 的低点频协议物理消费，未验收默认服务器 JSONL 启动、RTF、SLAM、目标到达、NN、自瞄或比赛。
- SIL01 两车动作与期限审计通过，但 SDK 退出与服务关闭竞争，整体失败；SIL02 提前退出后清理通过，
  红车 act 返回越过原 deadline，严格拒绝并 fault，整体失败。修复第三轮初始化次序后再运行，前两轮原 bytes 保留。

决策 v1 `navigation` / `perception` 仍明确 unavailable，真实定位/视觉反馈的新协议与各队审核 wrapper 尚需补齐；
自动火仍 manual_only，原 Qt 通用导航选择尚待实现。实际队伍算法、第二套完整自瞄、移动/多车、完整3v3/7v7与 M0–M5 不以夹具代替。
此前 T2 三次静态实时与 PB 单目标真实导航资格保持，本轮不重复该算法运行。

统一 QA04 前三步通过，pytest 14failed/1976passed/40明确skip/1002subtests passed，源码期间不变；失败原记录保留。
旧 CLI Sensors mock 无 robot_ids 参数，旧 reset 诊断固定断言内部 exchange 恰为2秒；测试修订后分别
18passed/10subtests、4passed，增加 manifest scope/共享清理负例、真实启动开销扣除及非空 Windows 子进程回收断言。
核心没有为测试回退 scope 或延长期限。最终统一 QA05 四步骤退出0、source_unchanged=true，
1991passed/40明确skip/1010subtests/6既有warnings；pytest137.04秒、外层driver175.6930609秒/reaped。
QA后只完善此说明与新永久证据，执行程序/测试/DEVELOPMENT_CHANGES 保持QA05的逐文件SHA。

[本轮永久证据](validation/coop_stream_20261014/README.md)分别保存：

- Windows新手动入口21项专测，以及实际原Qt/仿真服务8秒配置的启动/退出；driver10.3184506s、exit0/reaped/source unchanged。
  默认人工权限仅red_infantry、非audit；服务正常退出0/clean ACK、两owned Job回收且空。客户端在清理前仍运行，随后被Job结束；
  没有本轮按键、画面、动作/命中或整局证据，game_ready=false。
- 通用WSL JSONL把慢DrvFs STOP检查移到独立owned线程，仍强制核验初始身份并遵守原1.3/1.5s清理；
  缓冲区只扫描新字节，严格JSON、大小、单请求/原期限仍拒错。102专测/2平台symlink明确skip；
  两项实际无害进程树复测exit0/9.8535942s/reaped/source unchanged，没有图像、ROS或NN。
- PB一张真实新图：capture→public23.3902ms，act入口35.0607ms，host校验12.1049ms、序列化11.9974ms；
  入队实际6,225,306B、SHA5b71884b…，Linux完整第三请求同长度，bulk接收区间9.707535ms。
  peer首次严格解码16.735ms、原bridge开始后被取消，仍无ROS publish/SourceArmors/Target或NN；原80ms失败。
  没有跨时钟相减，没有把全量字节交付写成自瞄闭环。全部节点/相机清理与设置恢复完成；原Source03保持。
- 官方独立比赛树源码d111b635…、workspace5faf964b…与依赖精确版本只读审计。
  当前导航缺bt_navigator；默认比赛树是固定目标/状态/小陀螺，没有默认视觉攻击/射击。
  另有字段、场地图、spin范围、取消重发与失效目标缺口；已逐项保存，尚未构建或运行比赛树。

最终统一QA03四步骤exit0/source unchanged；1807passed/40明确skip/1008subtests/6既有warnings，
pytest133.07s、driver168.8232764s/reaped。QA完成后仅新增本文、入口说明与永久证据，执行程序维持已测SHA。
本轮未重跑T2静态live或PB30秒导航；它们原有独立范围保持，移动/自动火/多车/完整比赛与M0–M5未签收。

## 最新静态实时自瞄与通用层复测

新[逐次验证包](validation/aim_live_followup_20261014/README.md)保留所有原失败、修复前后、真实原图和完整来源。
自家T2完整原生检测/PnP/跟踪/控制链在本机静态场景连续三次通过 `live_static_chain`：

| 尝试 | 物理RTF | 及时结果 | 独立新帧实际关节消费 | 资格 |
| --- | --- | --- | --- | --- |
| lean-before06 | 0.9984405490 | 112 | 103 | 静态实时链通过 |
| lean-repeat07 | 0.9976797995 | 114 | 100 | 静态实时链通过 |
| formal-scheduling01 | 0.9971029121 | 107 | 97 | 正式参数入口静态实时链通过 |

六车场景、2ms物理步、1440×1080/15fps单相机、静止red_sentry单算法、原模型/CPU4 ELF与80/150ms保持。
它们显式使用host CV4、pybase64 1.5.1、CPython切换间隔1ms及Windows authority线程group0/mask0x10，
未加额外authority计时探针。正式入口实读生效值并finally恢复switch5ms和原mask4294967295；
没有证明该CPU是P核，没有改变系统电源、优先级或计时器。0adapterfault/0fire/全部owned资源clean。
迟到NN仍留在原帧并拒绝，pending不计及时推理/动作；这些结果不表示全部NN小于80ms、命中精度、
可见Qt桌面、移动/多车自瞄、实体射击、整场比赛或硬件通过。默认调度配置仍未取得相同资格。

本轮修复原tracker失锁时的 `[null,null,null]` 向量：仅tracking=false允许完整空三元组，active/partial-null仍拒绝；
保留真实无目标状态，不补角度。runtime先完成分离的消费metadata，再取实际消费时刻重查门限，receipt不再共享可变字典。
源槽收到已过原deadline的返回只保存原响应并返回无动作pending，不再记及时native_result；owned stop取消不再冒充算法fault。
WSL JSONL的STOP检查按本地5ms最佳努力调度，原Event取消即时检查，完整身份/有界清理不变；新增固定scalar IO清理证据。
实际两项无害Win→WSL进程树生命周期复测8.9329773s/exit0/reaped/原source不变，不是NN或实时控制验收。

PB三真实节点资源已启动，但首帧未通过。controlled尝试在host序列化时过期，完整请求只有prepare/reset；
新fast受控尝试显式CV4/pybase64/1ms后capture→public16.3977ms、act入口30.4881ms，原80ms仍queue.Empty。
Linux只收部分act字节：43chunks/2334917bytes（含prepare/reset）、complete_requests=2，无完整act、无SourceArmors/Target/compute。
故未取得该图像的MLP/PnP结果或云台动作；prepare4.0485265s/reset55.7953ms、原模型/source03保持、相机/全部节点clean、设置恢复。
离线保存DTO编码对照只证明相同wire/像素，不作为推理或实时改善因果证据。同济仍仅实际模型prepare/reset，无真实图像闭环。

最终QA followup02四步exit0/source unchanged，1745passed/40明确skip/1008subtests/6既有warnings；
driver159.0866653s/reaped，pytest129.71s。首轮QA因新增原提取测试未归因失败也保留，补显式源码变更记录后再运行；
原EXTRACTION基线不改。质量检查不替代上述live、第二实现、完整比赛、发布或M0–M5签收。

## 最新代码与证据：ROS2及实时入口修复

用户最新明确要求接入 [北极熊 pb2025_sentry_nav](https://gitee.com/SMBU-POLARBEAR/pb2025_sentry_nav)
哨兵导航，源码已锁定 cb97fb07 及其 Point-LIO/Omni PID gitlink，见 [来源审计](POLARBEAR_NAVIGATION_SOURCE.md)。
Ubuntu22.04/Humble 环境与新 owned workspace 分开验证，不修改旧坏 checkout 或启硬件driver。
新 schema 只传 sensor-local点/真实offset、实际 gyro/accelerometer与合法裁判状态，无qpos/ideal odom。
等待定位是独立无动作状态，保留同代算法实例；异常/进程超时、旧帧、变代、越权仍拒绝。
服务入口 `--pb-navigation-manifest` 为显式本地注册，不给HTTP选择命令。

[实际传感器证据](validation/navigation_sensors_20261013/README.md)：四线10s/5000步/99cloud/RTF0.9999635，
原输入时刻、源码hash和无回波处理均保留。它使用物理脚本激励，尚不是自家导航算法闭环。
PB原路径的ApproxTime重贴pose时间、missingTF单位回退和wall-time速度差分必须修复；
owned overlay 已修复这些边界，实际controller入口/结果与LIO扫描绑定同一不可变上下文；
不接裸Twist后补当前identity。真实LIO/TF/terrain与PB控制器/插件已在独立workspace编译成功。

[Humble实际DDS与构建记录](validation/pb_humble_sensors_20261013/README.md)：原JsonLineAdapter新进程
reset 0.806705s、act 0.051286s，9项真实DDS/清理检查通过；后续实际归档584点、51IMU
及独立clock/tf_static主题搬运通过。后两项不是当前物理deadline authority验证，原时刻未刷新。
这些DDS早期记录不是导航闭环；后述SIL8另有真实定位/规划/物理消费证据。默认T2另有29TU新clean build，
ELF仍4d357067…，诊断profile未替换默认自瞄。

用户已明确授权把最新成果提交并推送当前开发分支；不合并main，不发布release。

本轮 [冻结质量记录](validation/quality_pb_navigation_20261013/README.md)：1118passed、10skipped、
574subtests，实际camera35checks与preset/source/interface全部通过；871项source检查期间不变。
第一轮1117passed/1failed完整保留：测试误引旧builder spec被哈希门禁拒绝；第二轮显式选择
真正新默认构建，未改旧spec或放宽门禁。Point-LIO/loam/sensor三包实际build已过；
此质量记录早于下述实际SIL，不等于导航执行通过。PB插件原layers重名已仅修owned输出库/XML绑定，
原算法/class字节不变；旧加载失败保留。

[单代 PB 导航 SIL 证据](validation/pb_navigation_sil_20261014/README.md)按轮保存当前Windows工作区
源快照与Ubuntu22.04/Humble真实Linux运行结果。固定PB插件独立构建412.657s成功，控制器
同SHA对象resume23.838s成功；三ELF真实依赖解析/加载通过。原combined600s超时保留，
构建资源预算默认1800s、可选60–3600s，不改变任何SDK时窗。真实Nav2已配置Smac、PB PID和
IntensityVoxelLayer类；独立类probe编译180s超时也保留，不覆盖为通过。

SIL attempts1–6均未形成定位→规划→控制→物理消费闭环。attempt5实际30s/15000步，
RTF0.999315、543次原150ms SDK激活；子进程reset2.0448s超原2s持续故障，0ROS请求/定位/动作。
attempt6阶段文件证明reset ACK已flush：module→ACK1.370686s，ROS imports1.099678s、
node0.131157s、图发现约.000986s（counts[1,1,2,1]），不是图等待耗尽1s。
随后SDK lease_mismatch停止，3.472802s/1016步、0定位/地图/动作消费；最大物理停顿
40.717807→41.820299约1.102492s，已定位导航worker误import native图像模块及NumPy2/cv2 ABI警告，
该导入修复的独立回归与后续SIL7结果另记，旧失败保持。启动诊断只写bounded本地phase，不改sourcewall/数据/期限。
本轮Linux全栈试验不等于Windows↔WSL桥入口、可见GUI、完整导航任务或M2通过。

导航误import native/cv2已修为仅真实 native 实例进入图像模块；独立 runtime 81passed/52subtests，
Humble fresh process 证明 navigation/JSON slot 不尝试 vision import。统一质量入口
`artifacts/quality-20261014-navigation-startup-checkpoint/manifest.json`：1139passed、36skipped、625subtests，
状态为 checks_passed_not_milestone_acceptance。它是质量检查，不替代实际导航或完整比赛。

Point-LIO 04 新 owned workspace 真实构建约25.6分钟，ELF ff6e3bde78b74edde2875984a3dc8687a6b8a65bfc172e52dbbb74630794005b；
raw/context有界exact join与未配对过界清理保留原时间/身份，旧02/03未覆盖。
新owned ext4环境保存14,899文件、1,621目录、186链接与mode核验，原前缀/环境不变；
仅受信派生pth映射新路径。三fresh导入/真实消息serialize/六车模型0step通过，未init DDS或预热NN。
FINAL ENV SHA d60183ebf62d520c72eb20b84207fa4344d8f17183bb0df8eee92f97b7f981ee。

ext4下独立DDS fixture `artifacts/pb-humble-tfmessage-ext4-20261014-attempt2/dds/RESULT.json` 九checks全通过，
原2s reset实际.454714s、act.051592s，51IMU及原bytes/time/identity/staticTF通过且clean。
额外QoS wrapper exit2如实保留：图能确认TF RELIABLE/TRANSIENT_LOCAL、request RELIABLE/VOLATILE，
但本次history UNKNOWN/depth0，不能据其测量队列深度；source/单位配置KEEP_LAST、TF1/request8另记。
首旧env2.036241s reset失败与独立类probe180s compile失败都保留，不拼接为新成功。
这些DDS检查均非physics/LIO/Nav2闭环；SIL第七轮结果见下文，仍未通过。

[新 runtime 永久记录](validation/pb_navigation_runtime_20261014/README.md)保存89项原字节/SHA，包含ext4与SIL7分开的来源。
SIL7已结束：15000步/30s，RTF0.999506，293原请求、290LIO定位事件、58map；
Smac status4成功返回14-pose路径，FollowPath接受后status6 FailedProgress，0controller result、0有效motion消费。
整体未通过，source/assets不变且九组算法进程/runtime全部clean。Windows当前源与Linux真实栈范围仍分开，
这些局部算法成功不是Win↔WSL部署、完整哨兵任务或M2验收。

原身份请求→loc一致，但287/290定位到observer时已经看到后续请求；96–148ms到达延迟是observer诊断，
不能据此推断CPP callback顺序/重贴identity。新ControllerContext default-off metadata日志限256条，
记录真实begin/finish拒绝，不改单pending、pose匹配、原sim_window或50/150ms门禁；
实际FakeROS C++对照guard/output相同。新controller-only fresh构建195.130948s通过，
ELF d4539050e0959270080044ace965a525f7653b0ef0a1715b031a06d91e156dbd实际ldd/RTLD_NOW通过，旧02原字节保持。

有界dispatch实际DDS微夹具将同51个原stamp消息消费从spin_some100.102ms降至spin_all188.399µs；
此为synthetic DDS调度证据，不是SIL/物理传感器。Point-LIO05已独立编译与依赖/源审计通过，
ELF fd2b50c7a2d1993c80fc251f201126af6d3775a813851102108dfb65e521471f；新一轮SIL8结果另存，不重判旧运行。
[最新dispatch质量记录](validation/quality_navigation_dispatch_20261014/README.md)：1144passed、37明确skip、685subtests，
preset/source/interface通过且source_unchanged=true；本轮未重复camera，前轮35checks另存。

[SIL8永久记录](validation/pb_navigation_sil_20261014_attempt8/README.md)实际退出0：30s/15000步，
RTF0.9995295364，294原请求、292真实定位、59map；Smac14-pose/status4与FollowPath/status4成功，
18controller result、779非零物理消费步，原身份/传感器/SDK150ms/wall-sim期限审计errors=[]。
source unchanged，runtime clean join .013611s，九个算法组allreap/assets unchanged；fire_permission=false。
这是本机Linux Ubuntu22.04/Humble、red_sentry单车/单代/单目标的一次局部SIL通过，不签收M1/M2或完整任务。

目标为实际算法估计map pose沿map的x方向偏移1m、y保持不变；postrun qpos[1.434108,-.0204169,.0000558]只用于隔离评测，
不进入算法、不能据此称定位精度或所有导航场景通过。旧SIL7失败仍保留。
控制器bounded前256条diag：beginaccepted18、finishpublished18，nopending35、posenotlocalized26、
finishnorequest61、requestinstalled42、locaccepted28、loccontextmismatch13、locnopending15；
它只是达到上限的日志前缀，不代表后续全部callback。安全拒绝仍工作。

独立复核779条均关联原source→SDK ACK→物理消费，0adapter fault，capture age27.298–148.928ms未超过原150ms。
292定位逐字段/类型匹配原请求；observer到达延迟P50 5.532ms/P95 6.913ms/max10.614ms是接收代理测量。
C++186个采样区间的批量callback最大数25–50、dispatch最大1.206ms；spin_all1ms为非抢占预算，非CPU硬上限，采样不等于全量统计。
raw ROS的Reached the goal为旁证；完整path/goal TF未记录，14-pose和目标来源引用冻结工具结果，未由raw ROS独立重算。

复现使用本机生成的已核验ENV/stack config与freshout，不声明归档私有路径可跨机运行：

```sh
/path/to/verified-humble-venv/bin/python tools/qa_pb_navigation_sil.py \
  --environment /path/to/generated/ENVIRONMENT_COMPAT_FINAL.json \
  --stack-config /path/to/generated/pb-navigation-sil-config.json \
  --out artifacts/pb-navigation-sil-fresh --seconds 30 --diagnostics --run
```

本轮config04 SHA affba380753b6b8eac9505098fd0bf9d8a4457a4ec2892c09c80fb3da62d5c26，
FINALd601...、Point-LIO05 fd2b50c7...、诊断controller d4539050...与build/source/ELF引用完整冻结于RESULT/PLAN。
入口/构建依据见[PB桥说明](PB_NAVIGATION_BRIDGE.md)；Windows专用入口与实际验证见下节，第二机器、更多目标/障碍/恢复与定位精度仍待验证。
fullQA1144/37skip/685subtests为独立质量证据，不能扩大本次SIL范围。

## Windows 物理仿真 → owned WSL 自家导航

[专用接入说明](PB_WSL_NAVIGATION.md)与[永久证据](validation/pb_wsl_navigation_20261014/README.md)
新增受信本地 `--pb-wsl-navigation-manifest`、持久有界管道、原主机期限校验和Linux整栈收尾。
HTTP只选择已注册ID，不选择命令；准备先于backend/physics且不预热传感器数据，原reset2s/graph1s/ROS50ms保持。
服务显示独立namespace/Domain84；生产入口没有自动测试目标。后续独立外部动作客户端的局部验证见下节，完整行为树/任务仍未验收。

| Windows→WSL实测 | 实际证据与结论 |
| --- | --- |
| attempt1 | prepare7.349s；880step/12request/10LIO/0command；真实Humble UUID ndarray(uint8,16)被旧记录校验误拒，整体失败，九组资源回收但业务CLEANUP=false；旧字节保留 |
| attempt2 | UUID修复后Smac14/status4、FollowPath/status4；3808step/20result/326非零消费；seq67主机接收超原activation deadline，SDK退出是STOP后继，30s验证失败；resource/runtime全部clean |
| attempt3 | 15000step/30simsec/299request/297LIO/42result/553非零消费；Smac14/status4与FollowPath/status4，原身份/SDK150ms/消费期限审计errors=[]；source/assets/runtime/session全部clean |
| attempt4 | 再次15000step/30simsec/299request/297LIO/55result/514非零消费；Smac14/status4与FollowPath/status4，原期限与全部收尾通过；source/assets unchanged |

第3轮原RTF .980798实际含runtime.run内部 .58698s close，不作为纯物理RTF。
第4轮分开保存实际最后physics step：29.9995142s物理区间、RTF约1.0000；
run+cleanup30.5623169s、比率.981601，join .561446s/1.5s。指标分母和源字节均保留。
新增完整raw目标TF、14pose路径/原stamp、两个action UUID/接受/状态以及退出后estimatedTF，
不使用truth、idealodom、旧cmd重贴、不同domain时钟相减或放宽80/150ms。
独立只读复核3/4全部553/514个非零消费分别关联21/20个实际消费命令及两端SDK原窗口，
host capture age分别53.988–120.290ms/51.226–140.888ms；raw目标/路径/action原时刻和UUID核验通过。
两个单车/单代/单相对目标成功短测不关闭attempt2间歇超时根因、完整哨兵任务、定位精度、第二机器或比赛验收。

新增 bounded host/Linux scalar RPC phase账本与STOP共享盘耗时元数据（只在内存记录、收尾写盘），
用于后续定位尾延迟。修复 native WSL leader先退出时可能留下孙进程的owned-group回收，
真实Linux9项清理、8项stdio夹具与Windows source/spec回归分别标明范围；它们没有NN/硬件闭环资格。
当前M0–M5完整状态保持未签收，默认T2实时仍0返回/0消费；下一步继续完整外部任务、
导航异常与恢复矩阵、自瞄首帧80ms链、长期负载，所有旧失败保留。

本轮首统一质量检查1208passed/1failed/48skip/768subtests，未标通过，见
[质量与HTTP修复记录](validation/quality_wsl_navigation_20261014/README.md)。
失败是原Operator HTTP超大正文拒绝时Windows偶发RST，40真实loopback对照中20个延迟正文全部复现；
修复先送拒绝响应/FIN，再最多64KiB/100ms总预算弃正文，accepted limit仍4096，拒绝仍先neutral。
合法正文保留原2s、改为总deadline避免逐字续时；40同脚本真实对照全部413，25focused/31subtests通过。
这与导航attempt2未关闭的跨WSL超时是两个不同故障，不能把HTTP修复计作导航尾延迟根因关闭。

最终第二轮统一质量记录 `artifacts/quality-20261014-wsl-navigation-frozen-02`：
1216passed、48明确skip、776subtests（6条已有fixture collection warnings），preset/source/interface/pytest全部退出0，
source_unchanged_during_checks=true、checks_passed_not_milestone_acceptance。
原161未改源/29归属修改/1派生fixture核验通过；本轮未重复camera，前轮35checks另存，
实际Linux清理/stdio与Windows导航3/4范围分别按上述原件记录，不以条件skip计通过。
归档只追加验证字节和此最终说明，执行源码保持质量检查时的身份；M0–M5仍未完整签收。

## 生产 Gate + 独立外部 ROS 目标客户端

新记录见[生产接入证据](validation/pb_wsl_production_20261014/README.md)，与旧内部QA3/4原字节分别保存。
内部相对目标关闭（relative_test_goal=false），生产Gate仅在实际map/LIO/估计TF出现后激活原服务器。
独立owned客户端只查询GetState与真实代价地图/TF，再向原ComputePathToPose和FollowPath发送一个估计相对目标；
它不切换生命周期、不发布sensor或cmd_vel，也不输入truth。完整自家决策/行为树尚未验证。

| 生产实测 | 原结果与限定范围 |
| --- | --- |
| attempt1 | 657step/1.314sim秒、9request/7定位/0controller/0消费；Gate ACTIVE但Smac报Start pose is out of costmap，status6/empty，失败保留；算法与外部进程组实际已reap，业务失败不标clean通过 |
| attempt2 | 实际15000step/30sim秒、物理29.999280400s/RTF1.000023987；299request/297定位/59map/19controller/708非零消费，Smac15pose/status4、FollowPath/status4；source不变，runtime/Nav九组/外部client与supervisor清理通过 |
| attempt3 | 平台HTTP修复后，28项前置源码快照含server/client/admission；15000step/30sim秒、物理30.000017600s/RTF0.999999413；299request/297定位/59map/19controller/412非零消费，Smac15pose/status4、FollowPath/status4；source与全部资源清理通过 |

首轮没有HostTimeout：13次act RPC均完整，host本域P50 52.424ms/max53.749ms；这不能关闭旧内部QA第2轮seq67故障。
修复客户端读取原global_costmap/costmap_raw：保留原网格geometry/stamp/接收clock/dataSHA、实际估计TF/目标与cell索引，
两点必须可定位到同一份有效网格的半开边界内才发唯一规划请求。cost值不决定ready、不重试planner、不替换原寻路。
未保存整个网格原字节，SHA/cell代价仅作原记录关联，不宣称独立重算；元数据bounds可独立重算。

另修复status查询busy误停act、注册准备失败吞清理错误、pre-ready清理身份核验、激活线程与栈的收尾顺序、
并发stack.stop共享原deadline及有界阶段账本的收尾写盘。host/Linux均显式记录total/dropped/capacity；
complete只表明未截尾，不表明每RPC成功。实际物理时长与run+cleanup分开，长清理不能使提前停步通过30秒验收。
导航冻结专项原日志为71passed/8明确skip/105subtests；HTTP另有37passed/21subtests/0skip。最终统一质量以新归档manifest为准。
统一质量第一轮preset/source通过但interface_static失败：v2平台MAX16384拒绝正文时Windows偶发10053，尚未执行pytest。
实际TCP对照36case中24个延迟正文均丢失413；修复flush/FIN后最多64KiB/100ms弃正文，同36case全部完整413。
合法正文沿用原1秒并限定为总读取期限，timeout/truncated返回400且不dispatch/renew；原源码与失败均保存。
修改归属保持原提取SHA，仅更新开发SHA和说明；第三轮导航使用该新HTTP源码，不以第二轮证据重标。
原80ms图像、150ms控制、reset2s/graph1s/ROS50ms均未放宽；本轮无相机/NN/射击/训练/硬件。
T07/T09/T13/T16只有上述局部增量，T01–T18其余缺口和M0–M5状态保持表中结果；默认T2实时仍0返回/0消费。

[原host2s实测](validation/ros2_startup_20261013/README.md)：Lyrical module因清理PYTHONPATH缺rclpy，
固定bootstrap仍未在原2s内完成rclpy初始化；两次0观测/0动作且清理完成，不能把先前DDS通过推成host通过。

[首帧实际分解](validation/native_first_frame_20261013/README.md)：两个诊断profile均29TU clean build，
8fresh完整检测/PnP/跟踪与清理，原actual12帧410/422ms未改。create_request仅约0.05ms，
pure preallocation没有可信改善，未生产采纳；主要infer约23–24ms，首响应最大53–56ms。
这些是独立overlay的离线记录，原default/live失败保持，未以重复同帧回复或阶段P50相减声称实时通过。

[ROS2基础桥](ROS2_BRIDGE.md) 已新增本地预注册的 navigation/aim ID和严格JSON信封；
官方Lyrical rclpy10.0.11/FastDDS在Ubuntu26.04 WSL实际通过，bridge退出0、peer/thread/context清理完成。
[永久证据](validation/ros2_dds_bridge_20261013/README.md)保留两个依赖失败和第三次实际成功，
97ROS deb+11Ubuntu依赖只解压到owned prefix并核验官方签名/SHA。它使用明确DTO/零速度fixture；
不证明host启动时窗、真实导航、自瞄、物理SIL、Nav2、TF、点云、LAN或硬件。
上述通用Lyrical桥没有Windows专用监督器；本轮另提供受审的PB/Humble Windows监督器，两个入口与证据不能混用。

JSONL修复了Windows Python3.12的monotonic/QPC origin差异；注册接口可注入与runtime相同clock，
默认统一perf_counter；实际child测试证明不误过期，排队恢复后超过原deadline会关闭child/IO并拒绝。
私有native路径默认关闭，仅两种经过review的精确native类可读sealed实际RGB，不向custom/JSON/ROS发送内部对象。
公开observation.v2仍完整base64；lease/epoch/当前activation、stationary与wall/sim80ms、150ms窗口不变。
初始化耗尽帧预算时丢弃旧帧，下一新帧可继续；算法真实异常仍持续故障直到新绑定。

[第9轮](validation/wsl_native_live_20261013_attempt9/README.md)入口ValueError/零请求/RTF0.671失败保留；
[第10轮](validation/wsl_native_live_20261013_attempt10/README.md)交接修复后有真实请求，但RTF0.735与native超时保留。
显式camera-fast/pybase641.5.1只编码原字节；缺版本/C扩展明确失败，默认stdlib不变。
[第11轮](validation/wsl_native_live_20261013_attempt11/README.md)RTF0.99464/raw148全80ms，
仍因native超时而失败，记录诊断RGB SHA耗13.597ms。
[第12轮](validation/wsl_native_live_20261013_attempt12/README.md)将诊断RGB审计移到退出后，
原BGR/传输SHA同步保留；RTF0.997734、5000步/raw148全80ms、精确存档像素审计clean。
bridge预算剩54.128ms，Linux收图7.892/hash2.024/tmpfs写2.447ms，原ELF stdin1733/1733完整，
native等待41.232ms后仍超时。零native返回、零物理云台消费、fire0，不能称实时闭环通过。
PID698已reap、tmpfs移除、所有writer/thread清理、源/扩展hash不变；168项运行源字节和实际BGR均冻结。

[原保存图tmpfs离线诊断](validation/native_tmpfs_saved_compute_20261013/README.md)四个新原ELF进程首次真实检测/PnP/跟踪/control
为34.712–57.612ms（P50 36.569）；重复同packet的.604ms不是真实新推理。
不能用离线结果填补live空响应。下一项继续原native首推理/调度与部署性能；禁止相同配置盲重跑、提高门限或预热首推理。

本轮统一质量入口 `artifacts/quality-20261013-ros2-private-native-checkpoint/manifest.json`：
1060passed、7skipped、436subtests，实际camera35checks、preset/source/interface全部通过，
723项source在检查期间不变；status仍为checks_passed_not_milestone_acceptance。
真实WSL DDS另有1项通过，未把默认ROS专项skip、单位fixture和实时native失败相加称完整接入。
测试完成后的仅文档/报告归档变更单独记录；已测业务代码不变。
本地3ecd226普通Windows clone发现随机UUID归档长路径检出失败；修复仅缩短归档目录/索引，
41项实际记录字节/SHA完全不变，原路径保存在original_path。冻结质量目录记录此失败与后续换目录复核；未启用系统长路径绕过或删去证据。

下一轮可执行诊断：在独立overlay构建中测first native read/create_request/resize/infer/post/PnP/tracker，
原41.232ms是被期限截断的整包等待，不是纯NN耗时；原common_model.hpp已LATENCY。
优先验证将Tensor/create_infer_request的纯分配移到模型setup（不set假图、不infer、不热首帧）；
必要时独立比较实际生效的inference_num_threads=1/2/4与CPU pinning，保留原ELF/spec和原模型/算法/门限。
ROS下一小验收应直接验证host原2s reset限制，不能从8s的DDS测试推出已满足。

## 实测与证据范围

T03 当前开发机 i9-13900HX/RTX 5070 Ti Laptop、Windows、Python3.12.14、MuJoCo3.15：
同六车、2ms 物理步、1440×1080、15 总 FPS、一视角、10s 无 native 测量，
RTF 0.70962 → 0.99847；独立复测 RTF 0.99846，raw P95 25.287ms、P99 26.449ms、
最大 27.662ms，118 帧全部在 80ms 内，真实像素字节一致。
Display P95 32.201ms/14.61FPS；另一次启动最大181.63ms保留。15总FPS不等于候选25FPS。
这只是实时物理/图像证据，不能替代 native、完整比赛或7v7。见 [性能报告](RUNTIME_PERFORMANCE.md)。
旧中间 RTF0.2649/0.7164 及 cProfile 干扰包均保留，未覆盖或冒充严格 A/B。

T02 contour-v3：11 张未见独立真实 MuJoCo 图像，原模型有检测的7正例全部有效pose，
角点RMSE .134–.405px、位置误差1.7–28.7mm；3负例pose0，包括原误接受的单灯条遮挡。
第8正例原模型无检测，候选也无检测。保持模型/genre/confidence及原PnP门限，
DARK仅在实际像素支持唯一完整同色双灯条时恢复颜色；目标真值仅在 native 退出后做离线评分。
见 [图像修复报告](validation/pnp_contour_v3_20261013/README.md)。v1/v2与相机fixture错误失败均保留。

完整 contour-v3 native clean build：29个翻译单元syntax/compile/link通过；
新binary SHA256 4d3570674a7a150da0e86f64bbbd25adcfa8bb9e2731672ac6aeaa296cf92b42，
spec SHA256 28d051057118c62e36fd6c7fb7adc924819168335a01e164fcea440fcaebad8b，
复合源身份绑定原T2 tracker与新frontend；94个恢复native源文件不变。
这是build证据，完整OFFLINE24跟踪/控制链另测。
原重建 artifacts/native-build-2 binary 797e6ba7...仍供历史重现；首次GCC15缺标准头失败保留。

T13/客户端：本地显式凭据禁止匿名招生、operator提权审计与跨授权车辆操作；
state无全局位姿/其他输入，frame仅JPEG+静态标定+真实时钟，无own_qpos/own_odom。
actualHTTP攻击/控制/离线生命周期回归、三项真实MuJoCo QA已过。
客户端282项实际PySide6/Qt offscreen回归、67subtests、0skip；
artifacts/operator_admission_http_gl_qt_20261013_01 的16项检查通过，
实际QApplication/app.exec/QTimer、原renderer/QImage输出PNG，motion消费108物理步、
gimbal106步、12HTTPcommands、fire0、Qt退出0。
这是实际offscreen Qt+HTTP+GL，既不是可见桌面验收，也没有native算法绑定。
完整meta requirements的WebEngine大包曾timeout；恢复实际需要的Essentials/Addons/shiboken，
未把部分安装称完整requirements安装。

本机仿真基线pytest为680passed/5failed/2skipped/187subtests；失败保留。
部署/源组合/招生边界局部回归44passed、1个Windows symlink privilege skip。
最终全量结果以 fresh quality manifest 和日志为准，不把局部项数相加为总数。

## 当前可执行后续与复现

继续OFFLINE24实际T2 tracker→有效云台→物理消费/释放链与实时 native 因果账本；
保持原80ms图像门限/150ms控制窗口，不更新时间戳、不输入目标真值、不旧算法或像素代打。
所有构建/测试先检查运行状态，输出用fresh目录。source质量入口同时绑定tracked与新模块SHA。

    python tools/validate_acceptance.py
    python tools/validate_acceptance.py --require-frozen
    python tools/check_project.py --out artifacts/quality-new --camera

第二条当前draft返回2是预期保护。Linux/WSL离线EGL当前llvmpipe，不能冒充NVIDIA实时性能。
聊天按用户最新要求每2小时自动检查并继续已授权开发；仅实质进展/失败/完成/需用户输入通知。
不合并主分支、不发布release、不训练模型、不启动真实硬件测试；当前开发分支推送已获用户授权。

## 后续发现与修复记录

初次统一质量检查 artifacts/quality-20261013-checkpoint-01：configuration/source/193项合成接口通过，
全量752passed、1failed、3skipped、216subtests；未标通过。
失败为Windows venv launcher退出后真实解释器仍持有cwd。保存process-PID实测证明，
JSONL关闭现回收owned Windows进程树并join IO线程；20次实际oversize退出和立即目录清理全过。
同时修同一次JSON快照/源hash绑定、变更policy/spec/client身份拒绝、quality自身output误算source问题。
第二轮全量785passed/4skipped/216subtests与真实camera检查通过，但检测到并发更新源码，严格门禁正确返回source_changed_during_checks；最终冻结质量报告另存。

OFFLINE24 attempt2/3均保留：startup耗尽父5s初始绑定窗口；新增独立15s实际QApplication/cv2/numpy
preload-ready握手，不提前physics/capture/native，保持父5s、子3.5s与原80/150门限。
attempt3实际握手和session通过，但原client严格拒新离线scheduler metadata；已补严格4字段解析、
未知字段/私有嵌套拒绝，282actualQt/67subtests/0skip与fresh固定base apply/幂等验证通过。
新patch SHA256 91e3653df439289e25d64eb334f9c6f6a73e0c4aa8e3615ce968010e3b1860ee。

WSL隐藏GLFW经仅进程环境D3D12/NVIDIA可实际渲染；小图能力probe不计性能通过。
原配置10s实际测量 artifacts/wsl_runtime_d3d12_20261013_01：5000真实物理步、RTF0.99995，
但renderer初始化7.119s，只有3raw/JPEG帧，render/readback P50 .740s，曝光到raw P50 .820s/最大1.148s，
135丢帧，全部发布raw超过80ms。保留完整命令/env/结果hash，不在此配置伪称native实时通过。
Windows本地GPU相机25ms证据与WSL原生链的期限缺口是两种不同证据；需继续解决跨平台完整链。

## 最终静态链与当前冻结检查点

最终默认新构建使用已通过独立图像与完整静态链的 contour-v3；显式
--corner-refinement original 保留原失败重现。再次从零构建29syntax/29compile/link通过，
ELF同4d357067...，新spec SHA256 a808f11e8f8088ba89c2cf2a8e94d4bf18c386dc69d3d4114b9b2b40e57a3cdd。

新代码的 [aftercleanup完整静态链报告](validation/pnp_contour_v3_aftercleanup_chain_20261013/README.md)
通过：24actual exposures、13/13 pose/tracking/should_control，241次真正gimbal actuator消费，fire0；
原fire controller should_shoot有7/13为true，adapter fire_permission保持false，不能把两者混写。
原native PID1216已reap、returncode -15、两pipeclosed，worker已退出且instance释放；
shared shutdown join .01395s/1.5s，unfinished/lifecycleerrors=[]，runtime.error None。
运行前后10项实际源码hash完全一致。父/子startup时窗、80/150门限及原model/94native source均保持。

owned RMCS terminate→kill→finally streams、live/offline可信native取消、迟到Popen/reset防复活，
未知Python插件只使用总1.5s等待并明确unclean，避免假clean或卡住物理authority。
Windows专用140passed/22subtests与WSL实际12lifecycle checks通过。
本轮字节规范保护已冻结overlay/patch/报告的literal SHA；常规源LF规范后更新26项提取修改归属。
本地分支检查点 1dc500d / 3160522 已保存，工作区干净；新本地clone源门禁通过，42项冻结报告/工具/源码hash与客户端patch全部一致。它不等于第二物理电脑或公开发布。


冻结的最终质量入口 artifacts/quality-20261013-frozen-checkpoint/manifest.json：
checks_passed_not_milestone_acceptance；preset、26项归属源变更/未改原字节、193项合成接口、
全量787passed/4skipped/216subtests、实际camera35checks全部通过，运行期间source_unchanged=true。
相应draft --require-frozen仍应拒绝。当前局部问题的代码/测试/失败与复现均保存；
新默认PnP修复和静态OFFLINE链已验证，M1实时/完整比赛、M2–M5仍按上表继续推进。


Windows条件跳过的2项原尺寸EGL/lens投影用WSL实际EGL另跑，2passed（6.40s），
日志 artifacts/checkpoint-clone-egl-projection.log；SIGTERM-ignore另有POSIX实际12项回归，
Windows symlink权限skip保持显式，不为测试改系统权限。最后没有遗留构建或native运行。
下一项可执行M1工作是显式Windows GPU/持久WSL native传输与真实80/150ms全链测量；
现WSL单独GLFW/D3D12原尺寸相机不满足80ms，不能直接启动该配置当实时通过。

## 显式 Windows GPU / WSL native 开发检查点

本轮新增 [WSL 传输说明](WSL_NATIVE_TRANSPORT.md)，注册和启动校验同一 raw spec、ELF、
模型、配置、生成 main、原 94 源文件及 contour-v3 复合身份。模型初始化完成后只使用
实际 Linux `read(0)` readiness；没有先拍帧、推理或推进物理。换代、取消、启动失败、
blocked pipe 和超时均回收 owned 子进程，v2 同时回收专属 0700 tmpfs。
Windows GPU 相机与 Linux ELF 组合不等于 Windows 原生构建或可见桌面验收。

v1 共享盘路径和 v2 真实 BGR pipe 明确区分、没有自动回退。v2 只传同一实际不可变
4,665,600-byte BGR，Linux 校验 SHA 后写 tmpfs，保留曝光状态、标定与时间。
Windows 端图像改由独立有界线程写入逐帧文件/manifest 并读回 SHA；收尾必须写完已接受
图像，队列满或 IO 错误不能吞掉。公共 JSON 与第三方 adapter 不获得该私有 byte 入口。

修复的边界包括：先快照再严格校验同一元数据/像素；枚举值和字段类型拒伪造 Python
等值对象；实际原子 sensor packet 帧号去重；新帧发布可及时唤醒原生调度；每个执行阶段
仍按原曝光检查 wall/sim 双 80ms；原生结果和请求统一 Windows QPC 时钟。
私有像素凭据只在相机编码工厂产生，与原始 bytes、编码字符串对象、完整帧身份、
尺寸及曝光配对；伪造、JSON 往返或错配仍严格解码，不能携带到 HTTP/公共日志。
原 150ms SDK server window、静止 red_sentry 限制和 fire_permission=false 保持。

实时实验全部保留原文件与失败结论，见 [第七轮](validation/wsl_native_live_20261013/ATTEMPT7_TOKEN_ASYNC.md)
及同目录第一至六轮。固定六车、2ms、1440×1080、15总FPS、一视角：

| 实验 | 实际边界与结果 |
| --- | --- |
| v1 第1轮 | RTF0.997893，147raw；准备已耗尽80ms，native0返回/0执行 |
| v1 第2轮 | 实际运行后统计对字符串求百分位异常；只恢复已保存的startup/请求/清理，不虚构丢失RTF/raw数据 |
| v1 第3轮 | RTF0.992233，148raw；host准备期限失败，未进入bridge native_request |
| v2 第4轮 | 1,835,008/4,665,600 bytes接收后期限耗尽，无完整ELF输入 |
| v2 第5轮 | 3,211,264 bytes接收后期限耗尽，无完整ELF输入 |
| v2 第6轮 | 首次接收完整图像；接收/核验/写tmpfs14.35ms超剩余12.56ms，在ELF stdin前拒绝 |
| v2 第7轮 | RTF0.840138，149raw均≤37.94ms；准备15.73ms，Linux完整图像阶段16.75ms，generic control_timeout；native1请求/0返回/0执行；原图保存与reap/tmpfs清理均过 |
| v2 第8轮 | RTF0.961608，149raw均≤37.661ms；实际BGR完整，原ELF stdin1733/1733字节，仍超时0返回/0执行；source unchanged与证据/清理通过 |

第七轮旧报告未记录真正写入 ELF 的字节数，不能判断开始 NN 与否；新 worker 累计
实际 os.write 返回、完整 JSON+LF 长度、输入完成标记及等待原生结果时长。完整输入不等于
推理完成或控制通过。旧报告 native_identity 中 v1 标签有误，STARTUP/请求实际均为 v2；
新 v2 checked metadata 绑定两个 pipe 程序 SHA，旧报告原字节保留。

Linux 保存实际失败帧离线诊断中，四个 fresh 模型的第一真实响应 P50 84.87ms，包含
DrvFs 文件读取；独立文件读取 P50 58.46ms 是未配对测量，不能相减宣称纯 NN 时延。
重复同帧请求约3ms绕过新帧NN，不计吞吐或实时资格。无 native、同源码相机独立实际
诊断 RTF0.998367；编码工厂仅约多0.26ms/帧，不能单凭这些数字断定第七轮退化原因。
所有诊断都是相应范围的证据，T03/M1 实时完整链仍未签收，M0–M5 状态保持上表。

新的 [第八轮实际报告](validation/wsl_native_live_20261013_attempt8/README.md) 同时保存
16个关键执行源码确切快照、实际 BGR 无损压缩、完整字节交付/CPU/清理证据。
活跃故障绑定+SDK150ms独立Windows GPU诊断RTF0.9983966，说明它们不能充分解释旧退化。
静态能力查询消除重复 descriptor 深拷贝，公开副本隔离和每阶段权限/80ms/速度/epoch
检查保留；短paired FakeBackend step+demand P50 .4919→.4026ms，不等于实际RTF。
后续补上select返回后原期限重检：过期的已可读结果不得接受。实际无害子进程验证
完整输入但回复超时、短写、跨事务计数清零、过期可读拒绝与期限内通过；不称原NN通过。
保存帧工具已兼容v2异步逐帧文件，按唯一原请求帧号/SHA及严格manifest选择，拒绝
错图、歧义和路径变化；Windows11单位通过/1symlink权限skip，Linux12单位通过。
第八轮包的解压输入与离线复现步骤已保存，离线2s等待不写成实时80ms通过。
只读 Windows 库存未在已查标准目录找到编译器/OpenVINO，未安装或下载，非全盘搜索。

本轮统一入口（需独占实际 GL/native 测试窗口，先更新修改归属 SHA）：

```powershell
$env:POLAR_TEST_WSL='1'
.venv-sim/Scripts/python.exe tools/check_project.py --out artifacts/quality-20261013-wsl-frozen-checkpoint --camera
```

唯一计数与当前代码 SHA 见该目录 manifest、pytest.xml/log 和 camera 记录。只允许
各检查退出0且 source_unchanged_during_checks=true 时声明本地质量通过，不能据此关闭
M1或发布。按计划优先继续修复实际跨平台期限；下一次实验使用新目录，保持全部旧失败。

## prepared-BGR 本轮修复检查点（2026-10-14）

[独立永久记录](validation/native_prepared_bgr_20261014/README.md)保存三轮新失败、源码/构建/配置身份、专测与清理证明。原42ea570c…spec复用已有当前匹配的29TU clean checkpoint和同4d357…ELF/原模型，没有重新赋SHA或改旧manifest；旧a808…spec因portable/CMake输入漂移在第1轮startup前严格拒绝。

第2轮native启动失败，raw0/physics0/NNrequest0，没有Linux STARTUP/OWNED_CHILD/CLEANUP证明；本地Runtime clean不能当Linux整栈clean。另一6.352s资源-only startup probe与后续成功清理均不回填此旧缺口，启动失败根因仍开放。

第3轮actual3源/codec不变，5000steps/10sim：物理10.0004716s、RTF.999952842；run+cleanup10.0587424s、比率.994160065，分母独立。148raw在原80ms、1真实native请求/0响应/0消费、fire0；原ELF stdin1732/1732字节，等待47.378868ms后期限截断。单首请求factory5.2297ms、hostprep.1399ms（receipt.0184ms）不是纯NN或每帧统计，也不是同源配对改善。退出后实际像素审计、同run/boot/PID/PGID出生/回收、空组与tmpfs删除通过。

actual3已有validation前/后guard与WORKER phase；其后仅补最终Popen前慢file-open后的共享cancel、STOP和原deadline重检，以及更严格tmpfs proof。此后到达的取消交owned cleanup处理，不声称消除所有原子竞态；新最后guard未重跑live。PRE_NATIVE_EXIT仅证明未尝试spawn且tmpfs_removed；与真正child reaped严格区分，缺证仍失败。原15s native setup/1.3s host资源收尾和80/150ms控制门限不扩大。harness未开始时duration=None，physics与run+cleanup分别记账。

后继focused06原日志95passed/21明确skip/76subtests；Linux14 tests/unit含STOP/SIGTERM/deadline file-setup；最终guard独立startup probe02准备4.315s、0NN/0physics且资源clean。它们不能给guard修补前actual3的179份执行源码重标最终SHA，也不证明最后版本实际live通过；未重复NN/GL。

统一QA01原件为1285passed/1failed/32skip/875subtests，默认旧a808初始化spec被严格builder门禁拒绝。QA02由显式POLAR_WSL_TEST_SPEC选择已有42spec，非自动fallback：1286passed/33明确skip/876subtests、6已有warnings，四阶段exit0、source_unchanged_during_checks=true；pytest118.64s，driver137.428s/reaped。QA后仅本进度说明、WSL传输说明和新永久证据增补，执行源码与DEVELOPMENT保持原已检验SHA；不声称新增文档/归档曾参与该QA。

已有生产导航单目标局部成功保持；旧导航seq67尾超时、原模型3.85m漏检、实时自瞄0响应/0消费、移动与开火、多车/完整比赛、两机LAN/第二实现、Windows native与HIL仍按T01–T18/M0–M5门禁未签收。保存帧2s等待或预加载模型不替实际live证据。

## 模型实际属性与 JSONL 进程树修复（2026-10-14）

本轮[独立证据](validation/native_runtime_threads_json_20261014/README.md)区分诊断构建、零帧资源检查、保存帧离线响应、无害进程夹具和统一QA。原生产导航已有 Windows→WSL 点云/IMU→自家Point-LIO/SLAM/Smac/PID→物理底盘的30秒单目标局部通过记录；本轮未重跑导航或完整哨兵任务。

仅 first-frame-trace 诊断 overlay 增加真实 CompiledModel 属性查询；没有 set_property、暖推理或改变原94源/模型/ROI/生产配置。新独立29syntax/29TU clean build通过，原42生产spec保持严格匹配。实际零帧read(0) readiness后记录 CPU、16推理线程、1 stream、LATENCY、f32、pinning=true、ANY_CORE，OpenCV getNumThreads=32；0图像/0NN/0physics，owned组回收与tmpfs删除通过。它不是实时性能验收。

固定原失败帧8、曝光476000000ns/control486000000ns、BGR3951a597…的8fresh ABBAABBA离线诊断保留失败：默认4进程完整提交各1700bytes、14phase完整，首次真实回复61.720/37.697/38.116/37.881ms；2秒离线等待不能替80ms live。cv1四进程仅改OPENCV_FOR_THREADS_NUM=1，实际属性仍32，均在发送首packet前严格拒绝，0stdin/0NN；comparison_complete=false，没有有效线程对照或因果改善结论。所有8组reaped/empty且tmpfs删除、源不变。下一可执行方案是在独立诊断构建中显式调用cv::setNumThreads(1)，先测实际属性再对照，不把环境变量未生效的原因写成已证。

新worker只增加每事务stdout已读字节、select可读次数、原stdin完成后首次可读/读取时长、有界前缀长度与SHA及保留buffer长度，不记录原stdout前缀文本。select、读取和解析后仍重检原deadline；0读取不证明ELF从未写出。旧actual3缺这些字段仍未知，不能补填。实际Windows→WSL无害pipe29项通过；不等于原NN实时通过。

通用JSONL插件原Windows实际复现：leader退出且close返回成功，孙进程仍存活。修复使用执行前归属的Windows Job和Linux owned session，leader先退出仍清理后代；共享1.5秒资源预算涵盖生命周期锁/回收/IO join，原reset2秒和action原deadline不扩大。取消/Job assignment/句柄关闭/IO thread启动/归属检查失败保留明确unclean proof，未spawn与reaped分开；无法验证group时只对直接Popen尝试回收，不声称未知后代已消失。Windows after02原专测29passed/2Linuxskip/2subtests；CRLF→LF仅字节规范记录另存，最终LF源实际Linux02为20passed/11Windowsskip/2subtests，包括TERM-ignore孤儿孙进程和blocked pipe实际回收。原before/after01与错误标签ERRATA全部保留。

最终统一 artifacts/quality-20261014-runtime-threads-frozen-01 四阶段退出0，1324passed/35明确skip/930subtests/6已有warnings，pytest108.77s、driver128.635s/reaped、source_unchanged_during_checks=true；显式POLAR_TEST_WSL=1/POLAR_WSL_TEST_SPEC=原42spec。QA后只有本文、WSL说明和新永久包增补，不称这些文档或归档参与此前QA。当前最新真实live自瞄仍1请求/0回复/0消费/fire0；导航与自瞄同时实时、自动开火、完整巡逻/比赛及M0–M5仍未签收。
