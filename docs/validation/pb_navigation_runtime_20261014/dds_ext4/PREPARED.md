# 待授权干净窗口的一次实际 DDS 微验收

未运行；须等待 root 确认 ext4 FINAL 身份校验完成、Point-LIO 构建及其它实际任务均结束。

固定输入环境文件：
`artifacts/pb-humble-ext4-runtime-20261014/ENVIRONMENT_COMPAT_FINAL.json`。
使用文件中的 ext4 `venv_python` 和进程级 LD；清除 PYTHONPATH/PYTHONHOME。
原环境、首次失败报告、原算法 ELF 均不覆盖。

运行（仅一次；dds/bridge_phase 目标必须尚不存在）：

```text
wsl -d Ubuntu-22.04 -- /usr/bin/python3 /mnt/c/Users/lulu/Desktop/claude/polarsimulation/polar-rm-simulator/artifacts/pb-humble-tfmessage-ext4-20261014-attempt2/run_fixture.py /mnt/c/Users/lulu/Desktop/claude/polarsimulation/polar-rm-simulator/artifacts/pb-humble-ext4-runtime-20261014/ENVIRONMENT_COMPAT_FINAL.json
```

Peer 使用 DOMAIN82、独立 namespace。显式 sensor fixture、没有 physics/LIO/Nav2/NN/goal，
不能称实际导航闭环。原 JsonLineAdapter fresh-child 2s reset、50ms ROS 等待、150ms控制期限不改。
应读取 dds/RESULT.json 九 checks + clean_shutdown；另 ACTUAL_QOS.json 验证：
TF KEEP_LAST/depth1/TRANSIENT_LOCAL/RELIABLE；request KEEP_LAST/depth8/VOLATILE/RELIABLE。
结果仍 depth1。QoS观测callback使用独立 original_callback，避免闭包自引用。

只在 peer 已导入 helper 之后为 fresh child 设置 phase env；防止 peer 抢占 O_EXCL 日志。
日志仅记录阶段/本机clock/PID/count；不写凭据、完整env或sensor正文。数据字节与原身份由九checks校验。
外层30s仅为fixture资源收尾预算，不延长原host2s。失败保存，不同配置无变化不得盲重复。

旧环境失败：`../pb-humble-tfmessage-evidence-20261014/dds/RESULT.json` reset2.036241s/Empty，
0checks、实际child/IO/peer/context全部clean。它没有触发QoS callback，不能称数据/QoS通过。
