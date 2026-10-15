# 估计导航反馈与同扫描决策

本协议为通用导航插件增加显式估计反馈：真实传感器进入导航算法，导航返回有源估计，决策据此产生意图，
再由导航执行同一原扫描请求。schema检查字段及声明关系；它不能仅凭数字或SHA证明位姿不是伪造真值。
实际来源必须由固定生产者、原算法事件/TF、构建身份和owned运行审计验证。

## 显式版本与兼容

| 边界 | 显式声明 |
| --- | --- |
| navigation capabilities | `polar.sim.navigation-plugin.capabilities.v3`，在v2当前目标授权能力上增加`feedback_schema=polar.sim.navigation-feedback.v1`、`feedback_mode=staged_scan_v1` |
| navigation输入 | 仍为`polar.sim.navigation-observation.v1`、`pointcloud_imu_v1`；无理想own odometry、地图或敌方真值 |
| decision capabilities | `polar.sim.decision-plugin.capabilities.v2`、`own_referee_navigation_v2`、`exact_observation_and_navigation_feedback_v1` |
| decision输入/输出 | 输入`polar.sim.decision-observation.v2`；输出仍为原`polar.sim.decision-intent.v1`，没有执行器或开火权限 |
| navigation输出 | `polar.sim.navigation-goal-result.v1`保留当前intent、selection与实际controller UUID；只有严格动作DTO到达runtime |

旧navigation capabilities v1/v2、decision v1默认及其精确字段不变。v1的navigation/perception仍unavailable；
decision v2只新增显式导航反馈，perception仍unavailable。把feedback传给默认v1会拒绝，不默默丢弃。
capabilities在本地manifest固定，并由实际reset ACK完整核对；HTTP config仍为空，不能提交命令、模型、team scope或topic。
`custom_*`及supported_robots是能力注册规则，不按队名分派，也不能扩大admission授权。

## Feedback DTO

`polar.sim.navigation-feedback.v1`的精确顶层是：

```text
schema
source: robot_id / episode / binding_epoch / observed_seq / sim_time / wall_deadline
scan: cloud_frame_id / acquisition_start_ns / acquisition_end_ns / profile_sha256
navigation
goal_status
```

source严格回显本次扫描的原六身份，整数不接受bool替身；scan与原NAV点云逐项匹配。
即使navigation不可用也保留本次source/scan，不返回旧位姿或重贴新序号。

navigation不可用精确为`{available:false, reason:...}`，reason仅允许：

- `not_provided`：未提供该数据。
- `pending_localization`：没有本次原扫描的实际定位事件。
- `map_transform_unavailable`：该原算法时间戳的估计TF不可用。
- `staged_scan_expired`：原stage预算已过。
- `pending_navigation`：估计已存在但真实导航资源尚未ACTIVE，策略应等待。

可用时精确包含`available:true/reason:available/frame:map/child_frame:base_link`、
`stamp_ns/localization_stamp_ns/position_m[3]/rotation_xyzw[4]`和provenance。
位置单位米，有限且绝对值不超过100000；四元数xyzw须单位化。stamp必须原样等于原定位事件stamp，
位于该扫描acquisition闭区间，且不晚于原sim_time。
provenance为`method=tf_buffer_exact_localization_stamp_v1`以及三个小写SHA256：
`producer_source_sha256/localization_binary_sha256/mapping_binary_sha256`。
后两项是实际定位/建图ELF的hash，不能把源码hash叫作算法二进制证明。

PB生产者从本次原LIO source事件取得stamp，以该stamp查询TFBuffer的map→base_link并核对原返回stamp和frame。
map→odom来自原SLAM，odom→base来自原Point-LIO/loam链；允许TF2在指定原时刻处理估计链，
不改成Time(0)、nearest/latest或now，也不补理想TF。
单独的decision v2只持有feedback时只能验证声明；与NAV逐项对照和实际TF采样由builder/producer及独立审计完成。
这证明具体生产路径，不证明真实世界定位精度、无漂移或地图标定已验收。

## 当前目标与历史

goal_status没有实际snapshot时明确unavailable；可用时精确包含
`available/selection/history/operation_count/stop_requested/fault`。
history最多保留实际最后8份receipt，operation_count为完整记录数（0..256），不能把这个摘要叫完整历史。
完整lifecycle和GOAL_REPORT由owned证据保存，不因wire摘要裁剪而删除。

每份receipt为`operation_id/origin_intent/latest_authorization/goal_uuids/state/cancel_requested/terminal/stop_confirmed`。
selection仅取实际当前active记录，不能从历史挑一个成功目标作为当前授权。
origin是原完整决策意图，latest_authorization另记后续原六身份；同generation且origin≤latest≤本次source，
不把旧完成贴到新观察。操作/目标UUID严格32位小写hex；succeeded必须有navigation UUID。
None selection仅表示本次没有选中的可授权receipt，不证明全局没有目标或已停止。
cancel ACK不等于terminal/stop，终态receipt也不证明编码器实际零速。

`NavigationFeedbackHistory`为每binding观察流提供有界连续性检查：原seq/sim不能回退；
同source只能完全相同envelope幂等；operation origin不变、latest不能回退，UUID一旦存在不能改/回空，
cancel/terminal/stop不可逆，navigation UUID不可跨operation复用。缺少selection不抹掉已有证明。
失败事务不占用UUID，最多256个operation；observe和act的不同schema流分别使用history。

## 一次observe，两阶段消费同一个原请求

1. `NavigationPluginAdapter.observe(o)`发送完整原NAV。peer仅stage一份detached原输入，真实PB发布一次原点云/IMU。
2. `build_decision_observation(o, feedback, profile='own_referee_navigation_v2')`完整嵌入feedback，
   decision返回原六身份intent。
3. `act_with_intent(o,intent)`要求o与已stage完整输入严格同值同类型；wire为compact
   `{schema,op:act,source:原六身份,intent}`，不再发送点云/IMU。
4. peer按原source引用取同一stage，一次性消费；错误source、重复/缺失stage、改输入、旧代或迟结果拒绝。
   结果仍经当前目标/UUID历史、原action和宿主SDK检查。

Linux PB本地50ms从第一次begin/publish开始，贯穿observe、决策、poll和最终动作；compact act不重新begin、不重发bundle、
不延长deadline。最终门须截至响应encode完成后、write前重新核对同一原stage，
以免source及时但后续poll/history/日志或编码已经耗尽预算；这不是write/I/O完成的50ms硬实时保证。
Windows原150ms SDK和source wall_deadline仍是宿主authority并包含实际I/O，Linux不拿它减自身clock。
准备资源的15秒预算、reset2秒、graph1秒和原Linux1.3秒/host共享1.5秒清理是独立资源界限，不扩展动作时限。
这里没有相机输入；原图像80ms若另接自瞄仍独立保留，不能从本次导航试验声称已验。

## API和本地复现

`navigation_feedback_contracts.py`提供`validate_navigation_feedback(value, observation=None)`、
`navigation_feedback`、`unavailable_navigation_feedback`、`goal_status_from_lifecycle`和`NavigationFeedbackHistory.check`。
`decision_contracts.py`提供显式profile的builder/validator；默认仍v1。
`DecisionNavigationAdapter`按observe→decision→act组合，原宿主deadline在各边界重查。

本地准备工具只生成新manifest/spec，不启动资源或喂数据：

```powershell
.venv-sim/Scripts/python.exe tools/prepare_pb_goal_plugin.py --out artifacts/pb-goal-prep-fresh --stack-config <本机已核验的v2-STACK_CONFIG.json> --environment <同配置固定的ENVIRONMENT_COMPAT_FINAL.json>
.venv-sim/Scripts/python.exe tools/qa_registered_pb_goal_sil.py --run --manifest artifacts/pb-goal-prep-fresh/robotio.json --pipeline-id custom_pb_goal_pipeline --peer-evidence-dir artifacts/pb-goal-prep-fresh/peer-evidence --out artifacts/pb-goal-actual-fresh --seconds 15 --max-wall-seconds 30
```

命令是Windows本机仿真+已准备的Ubuntu-22.04/Humble环境入口，不保证另一台电脑已有私有prefix/ELF或模型。
须使用自己按公开构建工具得到、通过原始SHA/loader检查的配置，输出必须全新；不修改旧hash或自动回退。
资源prepare完成真实ACK但0扫描/0物理/0策略调用，不能冒称算法闭环ready。
标准venv解释器可由固定ENV显式选中其symlink路径以保留prefix，源/spec/config/output仍保留严格路径边界，
不意味着任意symlink或远程命令获准。

当前PB peer每个诊断journal限制8192条，满则明确失败，不静默丢日志。
10Hz扫描、每stage多条事件时，STAGES约136秒就可能触及上限；这是当前短时验证入口的资源边界，
不能直接许诺分钟级完整比赛。长期journal持久化/轮转及其性能仍需另做有界设计和实际验证。

## 先前synthetic决策的实际证据与缺口

原件入口：[attempt02 RESULT](../artifacts/registered-pb-goal-actual-20261015-02/RESULT.json)、
[peer索引](../artifacts/registered-pb-goal-actual-20261015-02/PEER_EVIDENCE_INDEX.json)、
[独立driver](../artifacts/registered-pb-goal-driver-20261015-02/RESULT.json)。
attempt01误拒固定venv解释器正常symlink，0物理/0扫描，以EOF失败保留；修复后attempt02原程序16检查全过。
02资源prepare11.8283445秒、0投样；7534个2ms物理步、受控SDK15.0125695秒，149原observe/intent/result，
138份可用估计全部与原LIO/TF精确关联，147LIO/23controller v2结果。
单目标origin seq13，原navigation UUID`c2239986a4db479fba6fb3ad28502ce2`，482非零消费步；
21 action/128 status不能混记为149次运动。真实succeeded/terminal/stop经feedback使后续synthetic策略hold。

目标策略只是在首次实际估计map x方向偏移1m，保持原y/估计yaw；不是PB比赛树，也不把它限制推广为所有导航目标规范。
driver30.207167秒/exit0/reaped/无forced/220程序源不变，runtime join .6848829秒，原资源预算内clean。
02后补齐最终同50ms门，再运行[actual03](../artifacts/registered-pb-goal-actual-20261015-03/RESULT.json)：
17根检查通过，7522个2ms物理步、SDK受控15.0054443秒，149 observe/149意图、148份实际返回（14 action/134 status）。
另1笔在control-stop后中止并保留，不能算149次完整响应；149stage中14个授权action stage，另1个原生action被抑制。
138份可用估计全部匹配原LIO/精确TF，147LIO、15真实controller v2结果，唯一navigation UUID
`c3fd85680bf54d459868d1c6ede6c6ff`有580非零物理消费步，origin seq13与latest seq35不混写，真实succeeded/stop后反馈驱动final hold。
14份public action各有一个同原deadline的最终encode后/write前gate，0 unmatched；不把gate时刻称为write完成。
原[peer索引](../artifacts/registered-pb-goal-actual-20261015-03/PEER_EVIDENCE_INDEX.json)保存FEEDBACK、STAGES、EMIT_GATES、原生ROS和GOAL_REPORT。

03资源prepare11.8818648秒、0物理/0扫描/0策略；内部29.9700689秒，
[driver](../artifacts/registered-pb-goal-driver-20261015-03/RESULT.json)30.3152588秒/exit0/reaped/无forced/220程序源不变。
runtime join .7700017秒，peer内部 .428730679秒（本地计时，不跨时钟相减）；外层Job实读1→0、外层清理 .0052197秒，
所有资源仍在共享host1.5秒/Linux1.3秒内clean。02保留其当次旧程序证据。
最终QA14四步骤通过：2788项通过/41明确skip/1024子测试，452程序/测试/来源文件不变；本句为QA后补记。
原件与失败的可校验副本见[永久证据](validation/registered_pb_feedback_20261015/README.md)。

注册路径的取消/替换/第二目标、多车、感知/自瞄联调、自动火、Qt/可见桌面、RTF、跨机DDS、定位精度、
完整3v3/7v7和M0–M5均未签收。先前独立PB探针两目标成功的证据保留，但不能移用为本注册路径资格。

## 真实PB决策替换与普通expiry处理

新[BT4 scoped runner](../operator_native/pb_match_decision/README.md)用真实C++ BT与原PB条件/动作替换先前的
synthetic高层策略，仍走同一decision v2/intent v1和navigation v3，不改此协议字段。
真实BT构建与standalone五个合成DTO tick已过，不代表实际裁判分支通过。
固定原XML与明确5处spin/stop/local-waypoint overlay分别记录；缺RFID保持缺失并抑制supply输出，
原树未实现receipt完成guard，不能用先前synthetic策略的finalhold替它补一条已验证战术。

真树注册actual02默认SDK cadence .05秒，原host事务期限失败、0公开动作/0motion；
actual03显式.02秒的fresh SDK授权后有2份及时公开action/72非零物理消费步，
但随后原Linux50ms最终encode门超期.739304ms，peer退出并出现adapter/共享清理失败，两轮均FAIL。
03的16observe/16intent只有15返回（2action/13status、1停止后中止）；
6份精确LIO/TF估计、14LIO/3controller及实际健康PB节点/原setMessage局部事实不能覆盖整个FAIL。
外层最终Job空/reaped也不能替内部共享预算或SDK release/close Timeout洗成clean。
原失败见[actual02](../artifacts/pb-match-route-actual-20261015-02/RESULT.json)、
[actual03](../artifacts/pb-match-route-actual-20261015-03/RESULT.json)。SDK cadence只改变操作手发送新授权的频率，
不改变点云/IMU采样、BT输入来源、source6或原150ms。

当前新增事务式末端修复，待新实际：候选结果先完整stateless验证与history preview，再encode，
`before_emit`只收到detached副本。及时action提交对应preview并写出；普通本地expiry可将尚未发出的action
降为同source/intent/selection的`no_associated_command`，controller_goal_uuid必须为空。
replacement重新验证、从原已提交history另建preview并编码后，只提交实际wire结果，
不会先提交action再以同seq改写history，也不把迟动作换成零速度。
坏来源/UUID/shape仍严格失败，回调不能改selection或伪造新授权；原candidate保留在REJECTED记录。
GoalNavigationCompute内部已验证候选与外部实际wire历史分别记账；候选不等于公开或已消费动作。
原single-act/single-response、同seq不可改响应和禁重放不变，write失败仍fault关闭，不自动重发。

50ms门仍只对动作授权，并截至encode后/write前；有源status不获得运动权限，也不延长原stage或host150ms。
status自身编码/实际I/O仍由原宿主期限约束，不宣称Linux50ms内完成pipe写入。
修复后actual04受控15.006447秒，101原observe/intent/status、95精确估计/101真实BT tick，无adapter fault且原共享资源清理通过；
但首次规划被实际Nav2以Start pose is out of costmap拒绝、0公开动作/0物理消费，整轮仍FAIL。
原失败目标sticky语义保留；随后新增真实代价地图metadata/同次TF估计起点bounds readiness，106项helper测试已冻结。
缺图/越界继续pending_navigation，不能clamp起点、填地图或用等待时间代替实际数据；bounds就绪不声明Smac规划可行。

actual05有149observe/149intent、148公开返回（5action/143status、1停止后中止）；
PUBLIC_CONSUMPTION按原公开动作源匹配206非零物理步。137份available反馈只是公共声明，
退出前navpeer journal全缺，缺原ROS_SOURCE/STAGES/ACT_RESULTS等就无法认证原生TF/LIO、UUID、终态或最终emit门。
decision Linux cleanup proof也缺，不能用native CLOSE或外层Job最终空替补，整轮FAIL。
Root的只读raw review05因缺ROS_SOURCE直接FileNotFoundError，没有rawpass；旧失败和缺件不重建、不掩盖。

原ownedTree同时TERM leader与Nav2 children会中断协作停机和证据保存。
新修复让pipeline先对所有owned peer请求stop，再等待；Linux侧先给leader最多.8秒协作，
仍合用原1.17秒KILL阶段、1.3秒Linux和1.5秒host总预算。
PB peer已增加幂等signal、PRE_CLOSE快照与写证据耗时，未知收尾继续unclean。
actual06原宿主期限失败，546步/1.2565519秒后中止，0动作；资源与完整证据在原预算内完成，整轮仍FAIL。

最终actual07显式CPython switch .001秒（实读并恢复原.005），SDK仍.02秒/原.15秒授权。
23项检查全过：147observe/147真实BT tick/147结果=15action+132status，136原LIO/精确TF，620非零物理步；
2份真实迟动作只返回同source status，原candidate保留/无物理消费，后续交易继续。
15份公开动作最终原50ms门通过；host收尾.9927301秒<1.5，Linux1.3保持，0adapter fault。
原目标origin seq13、navigation UUID 642bfdadacd6414386254d3888e4fcf1，真实succeeded/terminal/stop后保持原树持续目标语义。
独立raw复核15份原地图metadata、136本次TF起点覆盖、7未就绪估计被抑制；bounds不声明路径可行性。
见[actual07](../artifacts/pb-match-route-actual-20261015-07/RESULT.json)和[raw复核](../artifacts/pb-match-postqa-review-20261015-07/RESULT.json)。
该单次成功不证明1ms是此前失败唯一原因；默认调度、其余实际裁判分支、多车、自瞄、长局与完整比赛仍待验。
最终QA15四步骤通过，3041passed/45明确skip/1024subtests，460程序源前后不变；本句为QA后补记。
完整原件及失败的校验副本见[永久证据](validation/pb_match_decision_20261015/README.md)。
