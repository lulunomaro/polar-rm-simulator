# 通用导航插件：当前目标授权结果

新增 navigation capabilities v2 把“原扫描动作有效”与“动作属于当前授权目标”同时验证。
它按公开能力注册 `custom_*` wrapper，不以队伍名称选择算法。旧 capabilities v1、旧扫描结果和旧证据保持原语义。
本页描述协议与实现入口；当前新 profile 的实际验证数字待独立测试/运行结果确认，不预填通过。

## 显式能力声明

组件 manifest 仍使用 `polar.sim.navigation-plugins.v1`，command/cwd/supported_robots 来自可信本机文件，HTTP config仍为`{}`。
新能力必须完整声明，不能只增加一个ID：

```json
{
  "schema": "polar.sim.navigation-plugin.capabilities.v2",
  "observation_schema": "polar.sim.navigation-observation.v1",
  "action_schema": "polar.sim.action.v2",
  "status_schema": "polar.sim.navigation-status.v1",
  "sensor_profile": "pointcloud_imu_v1",
  "source_association": "exact_capture_and_active_goal_v1",
  "output_modes": ["velocity_body"],
  "fire_authority": "manual_only",
  "ui_config_contract": "empty_v1",
  "goal_input_modes": ["decision_intent_v1"],
  "goal_result_schema": "polar.sim.navigation-goal-result.v1"
}
```

reset ACK必须与本地manifest的完整能力严格匹配。JSONL act成功回执使用`result`承载下述envelope，
不能交替返回旧`action/status`。v1没有此active-goal授权声明，不能用v1通过记录替代v2验证。
注册成功或旧Qt可见目录不等于新profile已在原客户端实际操作验证。

## 结果合同

[goal_navigation_contracts.py](../rm_match/platform_v2/goal_navigation_contracts.py) 提供：

```python
validate_goal_navigation_result(value, observation, intent)
goal_navigation_result(observation, intent, selection, controller_goal_uuid, value)
GoalNavigationResultHistory().check(validated_envelope)
```

envelope精确包含`schema/source/intent/selection/controller_goal_uuid`，以及`action`或`status`二选一。
source为当前原六身份，intent为当前完整`decision-intent.v1`，连标量类型、reason及目标都不得替换。
action/status也必须回显当前原observation六身份；action仍为原`action.v2/velocity_body`，不追加UUID、理想odom或fire。

selection为None，或精确的当前操作记录：

```text
operation_id, origin_intent, latest_authorization, goal_uuids,
state, cancel_requested, terminal, stop_confirmed
```

operation_id为32位小写hex；goal_uuids含planner/navigation，各为32位小写hex或None。
origin必须是同generation的合法导航目标意图，seq/sim不晚于本次；latest原六身份不早于origin、也不晚于本次。
这只描述该结果选择的操作，不从旧历史中找一个已成功目标冒充当前授权。

包括零速度在内，**所有action**都要求：本次为navigate_to_pose、selection.state为active、没有取消/终态/停止、
origin目标与本次目标连JSON类型一起相同、latest六身份恰好为本次intent、实际controller_goal_uuid等于selection的非空navigation UUID。
hold/cancel只能返回有当前原身份的status，不能制造零动作来假报执行器已停止。
status允许原`pending_localization/no_associated_command`，controller_goal_uuid必须为None。

若回调期间操作已被更高seq更新，旧请求仍保留原source/intent，不能携带未来selection：返回no_associated_command且selection=None。
None仅表示本次结果没有选择可授权操作，**不代表**生命周期没有active或已经停止；真实新快照可独立诊断，不能拿来授权旧采样。

本模块不读取时钟，不延长原wall_deadline，也不证明UUID来自哪个实际算法句柄。
adapter调用者与原生计算hook必须提供真实来源；格式正确、甚至与selection相等的字符串，本身不是来源证明。

## 可复用compute与回调责任

[GoalNavigationCompute](../rm_match/integrations/goal_navigation_compute.py) 封装已有
[NavigationGoalLifecycle](NAVIGATION_GOAL_LIFECYCLE.md)，以一个binding为生命周期：

```python
compute = GoalNavigationCompute(
    lifecycle, sourced_controller, poll_hook=progress_owned_executor_once
)
compute.reset(original_context)
result = compute(original_navigation_observation, original_intent)
```

lifecycle显式使用`deadline_mode="opaque"`，不拿原宿主wall_deadline减Linux本地钟。
本地future观察只负责资源状态；原宿主的SDK150ms、传感器窗口、80ms相机、reset2s及权限仲裁仍独立生效。
poll_hook只能非阻塞推进已拥有executor，不发送假扫描、重贴旧帧或执行预热推理。

`sourced_controller(detached_observation, detached_intent)`必须恰好返回：

```text
{value: 原action或status, goal_uuid: 此次真实计算的FollowPath UUID或None}
```

不能从lifecycle取一个期望UUID填到回调结果。compute在回调前保存操作ID，回调后推进真实状态再核对同操作、当前授权与UUID。
合法但不属于当前授权的动作不发布，返回原source的no_associated_command；原action/schema/来源本身坏了则失败，不改成成功status。
禁止回调修改收到的原观测/意图。`last_snapshot`为detached诊断，不是本次执行器证据。

`close()`请求停止并推进一次；若尚无真实停止证明，明确抛出`goal_navigation_stop_unproved`。
拥有者仍需在原资源预算内继续驱动取消/结果并收尾node/executor/进程，不能用取消ACK或对象析构假报clean。

## 传输入口与历史连续性

可信JSONL wrapper使用实际初始化完成的工厂：

```python
run_navigation_plugin(
    reviewed_compute_factory,
    goal_input_modes=["decision_intent_v1"],
    goal_result_profile="active_goal_v1",
)
```

资源prepare只初始化真实资源，不输入观测；binding仍需原context实际reset及能力ACK。
ROS2 envelope桥额外显式`--goal-input --goal-result-profile active_goal_v1`，外部节点必须完成相同caps/result协议。
这条新profile的真实DDS接入仍需单独验证，不把既有v1 DDS fixture通过挪用为本profile通过。
WSL沿既有owned supervisor与显式prepare，不能用裸wsl.exe或任意HTTP命令代替资源归属。

peer/compute/host各维护独立的每binding `GoalNavigationResultHistory`：最多256操作，不通过淘汰旧证据接受重复UUID。
同operation的origin不可变；UUID一旦非空不能变更或回None；不同operation不能复用navigation UUID；取消、terminal、stop不可逆。
全局原source的seq/sim及该operation的latest授权都不能倒放；同seq改来源/期限或同源换响应拒绝。
同一原六身份、完全相同envelope可重复校验幂等，适用于同一响应的两个验证边界，不允许一个act产生两份不同结果。
失败不提交新UUID归属或推进历史；selection=None也不终结旧operation。新binding建立新history。

## 当前验证与待接入范围

新增`PBGoalControllerSource`作为原PB桥的可选来源适配器，必须显式选择
`follow_path_uuid_v2`/`nav2_server_pb_pid_goal_v1`和不超过50ms的原本地等待。
`exchange_sourced(observation, transport)`先经过原桥的scan/LIO/typed6/动作校验，
再从同一不可变原payload保留UUID，并核对原完整action和本次scan slot；新scan/结束时清空，
返回前仍检查原deadline。它不从生命周期填UUID、不启动资源、不另建executor；
调用者负责原reset、stack、单caller/同线程spin、真实取消及所有owned资源的清理。
新组件的26项受控测试包括与通用compute组合，仍不是实际ROS/PB注册运行。

最初插件/传输focused为133项通过；最后定稿代码的新profile/ROS包络/契约/compute/PB来源/独立审计
专项为190项通过，原stdout/JUnit/命令与执行源均保留，源码前后一致。
这些包含真实owned JSONL进程与受控传输，不代表真实DDS、队伍算法或模型通过。

[robotio_active_goal_plugins.json](../examples/robotio_active_goal_plugins.json)与
[robotio_active_goal_navigation.json](../examples/robotio_active_goal_navigation.json)是显式协议fixture，引用tests中的synthetic后端/速度程序。
`tools/qa_active_goal_protocol_sil.py`准备两车独立decision/navigation子进程并采集真实低率ray/IMU，
用于检验新envelope→SDK仲裁→消费及hold状态，不是任何队伍SLAM/Nav2、神经网络或性能验收。
第一轮内部20项检查通过，但外层在leader退出时检测到Job非空并强制回收，所以整轮严格失败；
该记录不重判。第二轮在原共享1.5秒清理期限内观察真实Job计数1→0，间隔5.1622ms，
exit0/reaped、无强制终止，内部全部20检查通过，220份程序源码前后一致。
4秒/2000物理步，56个原decision与56个navigation结果；红方28个action、27个有实际消费、
2371个消费回执/792非零物理步，蓝方28个status、0 action/0 motion消费。
四独立peer、SDK/HTTP/IO全部回收，runtime join .0546202s。
第二轮观察支持退出记账延迟的解释，不能据此将第一轮严格失败改成通过。
随后审查发现第二轮外层reader join仍有独立1.5秒，因此保留原记录，再以独立第三轮验证统一截止：
Job查询/reap、reader join、handle释放合用同一1.5秒deadline，总耗时.005654s，全部clean，无forced。
第三轮仍20检查/2000物理步，红28原action全部消费/2473回执/828非零物理步，蓝28status/0action/0motion消费，
runtime join .0541796s、exit0/reaped、220源前后一致。最终QA13为2550pass/41skip/1024subtests，四步骤0、
435程序/测试/来源文件不变；结果文字在QA后填写。
准确的执行源和失败/通过日志见[永久证据](validation/active_goal_plugins_20261015/README.md)。

此前[真实PB goal→速度v2](NAV2_GOAL_VELOCITY.md)已有独立探针证明，仍是另一条显式PB profile，
尚未转换成这里的通用注册callback；不能据本页接口声明称PB已通过此profile。
decision v1的navigation/perception仍unavailable，没有向比赛树提供估计定位/视觉反馈。
旧客户端、可见GUI、多车性能、目标取消后的编码器零速、自动火与完整比赛均需各自实际证据。
