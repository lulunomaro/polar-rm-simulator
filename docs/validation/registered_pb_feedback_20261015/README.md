# 真实PB通用注册与估计反馈检查点

以父目录PROJECT_PLAN.md为计划，开发父提交292eba12b3d86e3bfdcc634d8d1796f92d873b66。
这是Windows宿主→WSL内实际Point-LIO/SLAM/Nav2/PB PID，经通用注册/SDK绑定的单目标SIL。
决策为明确synthetic的“本次估计map-x+1m”策略，不是PB比赛决策树。

最终actual03通过17项根检查：7522个2ms物理步、15.0054443秒受控SDK跨度；
149份原扫描/决策意图，148份已返回结果（14action、134status），另1事务在控制停止后中断。
138份可用估计逐项匹配实际原Point-LIO事件与同原stamp的TFBuffer估计；147定位、15原生controller结果。
真实目标c3fd85680bf54d459868d1c6ede6c6ff成功、停止确认并反馈驱动后续hold；580个非零物理消费步
逐原FollowPath UUID/source/action/SDK关联。不能把15个原生结果全称为执行命令。

原Linux50ms从首次stage延续observe/decision/act，未重复发布扫描或重开deadline。
审查发现source返回后的poll/history/日志尾部缺最终门，已修复；最终14/14公开动作均另有
编码完成后、write前的同原期限EMIT_GATES记录并与完整encoded-response SHA逐条匹配。
这是写前边界，实际I/O仍由宿主原150ms窗口约束，未声称50ms硬I/O完成保证。
相机80ms保持。资源prepare为11.8818648秒、0物理/传感器/策略调用；
runtime共享host回收.7700017秒、peer本地资源.428730679秒、stack.199428347秒。
外层driver30.3152588秒、220源前后一致，Job1→0、无forced，外层回收.0052197秒。

保留attempt01的venv正常symlink误拒/0步失败；attempt02的旧程序16检查成功只证明当次source门，
未重标为最终emit门通过。staged focused01的compact-act KeyError和Windows mock失败也原样保留。
新原件包括source快照、命令、raw日志、JUNIT、SHA、独立review及每轮资源身份。

最终QA14四步骤全部退出0：2788项通过、41明确skip、1024子测试通过，6条既有collection warnings；
driver186.8611387秒/exit0/reaped，452程序/测试/来源文件前后SHA不变；quality检查期间12084份输入未变。
正式文档的QA结果文字为完成后补写；程序字节不变，不将后补文字当作QA期间原字节。
独立raw review02的503输入前后一致，final gate最大41.657967ms、最小余期8.342033ms，
580物理消费与公开action/nativeUUID/SDK/原capture精确匹配，0status或aborted源消费。

边界：本轮没有相机/自瞄/射击/Qt/可见桌面/RTF/两机DDS或完整3v3/7v7。
注册路径取消/替换/第二目标尚未验收，原独立profile的旧多目标结果不能替代。
每个诊断journal上限8192，10Hz的STAGES约136秒后会明确失败；不是分钟级完整比赛入口。
估计来源关联不等于定位精度证明。T01–T18及M0–M5当前缺口见正式IMPLEMENTATION_PROGRESS.md。

运行本目录verify_archives.py只校验字节完整性，不重新执行算法或宣布里程碑通过。
PRESERVATION_MANIFEST.json记录原件和存储SHA，FILES.json覆盖整个包；gzip固定mtime=0。
排除SDK私密事件/凭证、本机*.local.json及ELF、DLL、ONNX等二进制；既有档案、五份客户端补丁与checkout不变。
