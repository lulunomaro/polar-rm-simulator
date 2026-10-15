# 导航目标生命周期聚焦协议回归

范围：受控 backend、Future/Event 与原 JSONL/ROS envelope 单元。没有运行 ROS、WSL、导航算法、仿真物理、相机或 NN，不代表导航任务/比赛验收。

- 01：34 passed，pytest 0.34 s；原命令、stdout/stderr、JUnit 和进程返回码均保存。
- 02：36 passed / 2 failed，pytest 0.40 s。两个失败准确复现 backend 的 schema/operation_id 接受 Python str 子类；这不是外部导航算法失败。终态回退两个用例在该轮已通过主代理此前修补。
- 03：38 个新生命周期用例与原 decision_plugin、decision_bridge_core、navigation_plugin、robotio_ros2_bridge 合并，共 152 passed / 0 skipped，pytest 2.00 s，captured driver 2.3654155 s，exit 0、子进程已 wait 回收，10 份输入源码前后 SHA 一致。

新用例覆盖迟到接受与取消交错、ACK 不等于终止、新目标等待停止证明、旧 operation 回调隔离、终态同几何去重、显式 hold 后重开、原目标/后续授权来源分别保留、原 host 期限过期、opaque 时钟不跨域比较、本地 send/cancel 资源上限、恶意状态/UUID/类型拒绝、输入及快照可变对象隔离、重放/跨代拒绝、未知 start/cancel 失败不宣称 clean、历史容量有界。

`source03/` 是最终聚焦执行前逐字节快照。02 的测试和 decision_contracts 逐字节快照已保存；02 引擎 SHA 为 `5e29e2df4f37a14b13d4a83f8f847cd70598291da4bbbcf39b8624bfcb498412`，其旧完整源码在保存尝试时已由主代理修补，因此当前仅保留原执行 SHA、原失败日志/JUnit，未重构该源码。`SOURCE02_PRESERVATION.json` 明确标记这个缺件。01 仅保存原执行哈希，未声称有完整 before 源码快照。

最终新增测试 SHA：`073db6901fe02a8930d4b96d6f9d2fb392f75575dab5c7cbef44abb308843727`。最终引擎 SHA：`650862b4056c75b1e7c946255169eb0b67720f0802aa74455dcf415b5d5b58df`。不改其他生产源码、文档或 Git。
