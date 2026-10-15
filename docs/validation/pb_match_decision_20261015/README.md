# 实际 PB BT4 决策与通用注册导航检查点

父提交 `1c2e819566d93ce760e2e601b35be929298652e0`，开发分支 `work/plan-t01-t03`。
本包保留本轮源码、构建、单元/合成、standalone、失败与最终局部SIL证据，
不替代 M0–M5、移动自瞄、完整3v3/7v7、可见Qt、两机LAN、HIL或发布验收。

## 实际通过的范围

actual07 由 Windows MuJoCo 原点云/IMU，经真实 Point-LIO/SLAM/精确 stamp TF、
navigation v3 observe、decision v2 原生 PB BT4 tick、同 scan compact act、
原 Smac/FollowPath/PID、公开 SDK 授权，最后由物理底盘消费。
23 项根检查通过：7451 个 2ms 物理步，SDK受控15.0050229秒；
147 observe/tick/intent/result，15 action/132 status，136 原LIO/TF估计，
18 个原生 controller 结果中仅15个公开动作获授权，实际620个非零物理步。

原目标 operation `f53ccc1bd268cea5b89f954114c62550`，origin seq13，
navigation UUID `642bfdadacd6414386254d3888e4fcf1`，真实 succeeded/terminal/stop。
原树继续发布同目标，没有新增 synthetic final-hold 或战术完成策略。
2个真实迟动作（seq16、30）保留原candidate/原deadline，转成同source/intent/selection的
no_associated_command status，controller UUID为空，均未消费；后续帧仍继续运行。
15个最终 encode后/write前动作门均满足原50ms，最小剩余2.125745ms；这不是write完成时刻。
原图像80ms/SDK150ms门均未改，此链没有图像、自瞄或开火。

独立raw review07校验15个原costmap metadata接收、136份同次TF估计起点覆盖、
1个原目标起源；7个未就绪估计不获navigation available。
边界覆盖不代表占据、路径可行性、定位精度或官方场地标定。

显式CPython switch .001s、实读生效、finally恢复原.005s；SDK cadence .02s，授权仍.15s。
不能以一个成功样本证明调度是此前失败的唯一原因，也没有默认配置资格。
资源prepare13.9383374s，0采样/0tick/0物理；driver33.0109988s/exit0/reaped，
224执行源码不变，外层无forced、Job空。host共享收尾.9927301s<1.5s，
peer内部.725153775s<原Linux1.3s，0adapter fault。
Linux leader在原TERM区间内先获最多.8s协作，原1.17s KILL门保持；
所有owned peer先stop再等待，PRE_CLOSE前缀与最终完整日志均保存。

## 原生来源与独立证据层级

使用原 PB `IsGameStatus`、`IsStatusOK`、`IsRfidDetected` 与 `PubNav2Goal::setMessage`，
不是Python规则替代。固定 PB behavior revision `d111b635d326775c6c19aa12500a0bbd6a27a588`，
PB ROS2 fork `7d177dcfbd7dbb7f5e5cd79c4e5e3e744e389c56`，
BT.CPP4.6.2 `2a8a226fbbd99f524f0796e0d8a3145773c61c06`，
protocol1.7.0 `8912fa565a7ac57ef070df218957379123d238ee`。

BT4 clean build43.4268s/391源不变；protocol02 clean build23.1202s/17源不变；
runner03 clean build45.853s，并保存compile命令、原头闭包、ldd与32个实际加载库SHA。
native ELF SHA `31932110540f2caa4ae6969c5e41fa07c853a8a539c8d53d72a44416a9210c66`。
原XML SHA `68e216c145949538444bd8b9f9e97cc1b79b1536ddbc52a37eb00252e20c34f9`，
owned XML SHA `7a09236753e004fc9b10325c2b9713154ff9da00749deaaa3a790aaff23581dc`。
5处overlay明确为2个spin禁用、1个同步hold、2个首次估计anchor的local waypoint。
未提供RFID来源，supply输出保持抑制，未捏造未检测状态。

standalone01 的5个实际C++ tick使用显式合成DTO：健康目标、低血量且缺RFIDhold、
暂停、e-stop、无定位。它们不代表真实比赛裁判触发负分支；actual07只有健康单目标范围。
Windows纯测试、Linux无害服务/孤儿/TERM-ignore实际测试与真实ROS/物理运行分层记录。
原许可证逐字节复制在仓库licenses，声明见THIRD_PARTY_NOTICES；本包不分发ELF/so或模型。

## 保留的失败

| 记录 | 原始结论 |
| --- | --- |
| protocol01 | 缺ROS_DISTRO，构建失败；02仅显式补构建ENV |
| runner01 | Windows短wsl.exe路径launch失败，未运行Linux构建 |
| runner02 | 原plugins.hpp闭包缺失，真实编译失败；03补固定原头 |
| route01 | 根driver graph字段错误，未运行资源或物理 |
| actual02 | 默认.05 SDK cadence原host期限失败，0运动，共享清理失败 |
| actual03 | 2及时动作/72步；下一最终50ms门晚.739304ms，peer死亡，共享清理失败 |
| actual04 | 101tick/95原估计，初始costmap不含起点，原planner aborted，0动作；清理通过，运动FAIL |
| actual05 | 5公开动作/206公共源物理步；原生journals和decision Linux清理证据缺，137只是公共估计声明，整体FAIL |
| raw review05 | 原ROS_SOURCE缺失，FileNotFoundError；无raw pass，不重建缺失记录 |
| actual06 | seq3原host期限失败，1.2565519秒/546步后stop，0动作；新清理和日志通过，整体FAIL |

不把晚到的旧birth不存在检查回填actual05清理；实际检查时boot已改变。
纯测试初始fixture失败/Windows SIGKILL常量mock失败等也保留原日志。
未在先前失败记录里补源、改时间戳、替换结果或声称当前源已验证。

## 阅读与复现

最终QA15四步骤全部退出0：3041passed、45明确skip、1024subtests、6条既有collection warnings；
pytest149.46s，driver196.7534391s/exit0/reaped。460程序/测试/归属文件及13787检查输入在检查期间未变。
QA后仅补正式文档和本新证据包；程序SHA保持，不将新文案声称为QA当时原字节。
QA原件可按manifest的original_path检索artifacts/quality-aim-followup-20261014-15与对应driver。
另有只读review08，无阻断问题，输入SHA检查前后不变；它不重复运行物理或全receipt审计。

`PRESERVATION_MANIFEST.json`列原路径、原字节SHA和保存字节SHA；大文本以mtime=0 gzip保存，
无需重跑即可校验。`FILES.json`覆盖整个包（不自引用）。
`records`使用编号短路径，原完整路径由manifest映射，兼容Windows默认Git路径长度限制。
初次深层布局触发Git路径限制、尚未写index或提交，完整原包保留在本地ignored
`artifacts/pb-match-archive-pathlength-failure-20261015-01`，没有改写其原manifest或内容。

```powershell
.venv-sim/Scripts/python.exe docs/validation/pb_match_decision_20261015/verify_archives.py
```

按manifest选原路径解压；source snapshots对应各次执行的实际源，不以当前源冒充旧运行。
构建入口为`tools/prepare_pb_match_decision.py --help`，仅`--build`真正构建；
standalone/route驱动、逐次COMMAND、PEER_SPEC与BUILD_RESULT可按manifest的artifacts原路径检索。
运行需原Ubuntu-22.04/Humble、固定ext4依赖/生产导航资产及显式本地ENV；本包不是干净第二电脑发布包，
ENV路径与ELF SHA不能自动改写成新机器资格。
所有运行输出必须用新目录；重跑脚本前选择未使用attempt，避免覆盖原证据。

准入凭据、SDK_EVENTS、用户配置、ELF/so、模型和整个外部checkout均不作为提交负载。
Git交付只推开发分支，不合并main，不发布、不训练、不测试真实硬件。
