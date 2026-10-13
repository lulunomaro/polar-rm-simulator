# 真实 JSONL 启动失败的复现

此前真实 Lyrical/Fast DDS 通过没有覆盖 host 的原 2 秒 reset。此次直接用 `JsonLineAdapter` 的真实 Popen、线程、排队和期限，固定本地 manifest，未修改 reset timeout 或环境清理策略。

- `module`：host 清理 PYTHONPATH 后，child 缺 rclpy，约 0.441 秒失败。
- `bootstrap`：固定 sys.path 的 fresh child 进入真实 rclpy 初始化，但原 2 秒截止前没有 ACK；约 2.016 秒含清理失败。bootstrap_enter 与 rclpy_init_begin 记录均保存，不能当作初始化完成。

两次均 0 observations / 0 actions。子进程已 reap、pipes closed、IO/peer 线程退出、DDS executor/context 关闭；clean_shutdown=true。未放宽时间，也未用 parent import 冒充 fresh child。

[保留清单](PRESERVATION_MANIFEST.json)绑定原结果、manifest、日志与阶段记录。工具 `tools/diagnose_ros2_jsonl_startup.py` 可在已审计 prefix 中重现。后续哨兵导航使用独立 Ubuntu 22.04/Humble；不把这一 Lyrical 失败混为该导航已通过或已失败。
