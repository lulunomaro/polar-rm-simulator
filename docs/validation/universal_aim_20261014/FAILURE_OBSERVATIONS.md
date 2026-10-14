# 转录的失败观察

本文件是工具输出的说明性转录，不声称是原始 stderr。各已捕获实验的原始日志另存其 fresh artifacts 目录。

- 首轮猜错测试路径 `tests/test_host_opencv.py`，pytest 未运行任何测试；实际新文件为 `tests/test_host_opencv_threads.py`，后续独立检查通过。
- FINAL_IO cancel_wait 纯 fixture 首次只推进 1ms，未到原 5ms STOP 检查，读到 EOF；改为推进 6ms，保持生产 STOP 检查原值，后续45项检查通过。
- 初次使用错误目录 `rm_match/integrations/{native_adapter,wsl_native_adapter,wsl_registry}.py`，三次 Get-Content 未找到文件；rg 确认真实路径在 platform_v2 和 deployment 后修改，没有写入错误路径。
- Tongji actual prepare01 监督器使用 Ubuntu `/usr/bin/python3`。真实 `-m rm_match.deployment.wsl_jsonl_worker --help` 复现导入 json_adapter→platform_v2.adapters 时 `ModuleNotFoundError: numpy`，没有进入 worker.run。首次无 HELLO、清理证明缺失，原记录仍为 unclean；没有反向填成成功。第二次 fresh instance 显式选择 `.venv-linux`，原模型真实加载/零NN prepare ACK、当前 context 的 reset 和原资源清理均实际通过。
- PB preflight01 缺 `image_transport_plugins`；系统依赖01官方下载 HTTP timeout；系统依赖02使用同资产 HTTPS+完整 signed SHA，实际成功。preflight02 绝对入口漏 ROOT bootstrap，真实报 `ModuleNotFoundError: tools`；独立外 cwd 子进程测试修复。preflight03 发现 extra prefix 只有已下载包，系统已满足的 OpenCV transitive包未重复下载；不能把 extracted-byte complete 当 standalone dependency closure，保留其原始失败。
- Async01 3个真实原NN输出/PnP/tracking有效，但全部迟到丢弃；证据队列满导致 sticky fault 与 writer 清理未完成。后续先检查容量，忙时整帧 pending 不请求NN，accepted像素仍完整保存，v3在原1.5s资源预算内同时收尾。Async02 得到65真实NN stdout、66完整stdin ACK（其中一个退出时取消），5及时返回、3新帧物理消费，0fault/0fire/clean。不能把 ACK 或 pending 算 NN，也没有实时整体通过。
