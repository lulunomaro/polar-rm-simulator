# 原生链分段取证、存证读回优化与实际失败

**实时自瞄仍未通过。** 本轮修复存证文件读回的过多Python分块交接，加入默认关闭、有界、同源的分段诊断。
优化后的最终默认实际运行仍提前停止、零及时动作；单位/离线优化收益不能替代闭环资格。
原图像80ms、SDK150ms、物理2ms/六车、1440×1080/15fps、ELF/ONNX及人工火控均保留。
无新模型训练、原生构建、PnP矩阵、移动自瞄、两机LAN或完整比赛验收，M0–M5未完整签收。

父提交为`0629d1f595db7895a5ce976f59dc5bd2672c1d3b`，开发分支`work/plan-t01-t03`。
固定客户端仍为第六组合补丁，未修改客户端或旧五版身份。

## 实际三次静态运行

| 项 | diag01 | diag02 | default03 |
| --- | --- | --- | --- |
| 存证读回分块 | 原64KiB | 原64KiB | 新1MiB |
| 新phase采样 | 全详细 | whole-step全采，详细每50step | 关闭所有可选authority/phase计时 |
| 实际运行加清理wall秒 | 8.1634413 | 10.1190525 | 3.7627290 |
| RTF | 0.6427592 | 0.5215940 | 0.7069063 |
| raw图像/及时结果/消费独立帧 | 109/0/0 | 137/0/0 | 54/0/0 |
| 错误 | binding_mismatch | 无 | binding_mismatch |
| 原输入预算/像素核验/请求归账/owned清理/源码 | 保持/通过/通过/clean/恒定 | 保持/通过/通过/clean/恒定 | 保持/通过/通过/clean/恒定 |
| 判定 | FAIL | FAIL | FAIL |

两次错误运行提前停，不能当成完整10秒稳定性。不同源码、采样量和运行时状态不构成受控因果对照。
default03的12笔queued请求为11笔原生前丢弃和1笔真实stdout迟到，无漏账；没有将pending或迟到推理算成及时结果。
92份完整实际BGR（18/51/23）保留本地并有完整pixel audit SHA，Git仅取每次一份真实样本。
它们是已接受存证的原始帧，不是全部300份raw发布图像，也不表示92次原生推理。

独立绑定审查确认diag01在原activation期限到达后正常撤绑定，lease检查仍过：
最后ACK2459.2370349、原expiry2459.3697906、physics close2459.3894765；确切失败HTTP时刻未单独采集。
不能以operator_status请求前采样冒充响应完成时刻。未重试或延长期限去掩盖该失败。
default03保留自己的绑定错误记录，不凭diag01审查虚构其精确失败时刻。

## 已实现与独立证据

NumericPhaseProbe仅保存原source6、request/frame/pixel SHA、原deadline和有限计时标量。
注册prepare前同实例传给authority、async和writer，新增helper随显式启用路径固定源码SHA。
默认None无新probe采样/锁/哈希/像素复制。启用容量262144，溢出拒绝完整取证；关停后才写JSON。
diag01记录140149条、diag02记录8668条，均零溢出、原始匹配无缺失；不能把complete当作实时通过。
详细每50step的取样规则在后继计划/原快照声明，未回写首次失败。

same-thread/source才能相减CPU，跨线程只比较同域wall；队列、reader验证和accepted-caller按类型化原身份关联。
短阶段CPU为零或wall-minus-CPU为负均原样保留，不称作GIL等待。
两次Windows观察到正CPU增量最小值/GCD为15.625ms；ns单位和API报告分辨率不保证细阶段精度。
inclusive阶段会重叠，抽样阶段和all-step统计也不可相加。

完整文件读回SHA固定分块64KiB→1MiB，保留size、实际磁盘读回和原两次SHA、队列容量、BGR/JSON全部字节。
每4,665,600字节的非空read循环72→5，临时块上界1MiB，没有以原内存hash冒充磁盘核验。
离线暖缓存同一真实BGR、一个明确合成Python争用线程、switch interval1ms并最终恢复：
四组ABBA各读3帧，原64KiB为4.7752665/4.9550751s，新1MiB为0.5749247/0.5346798s，12个SHA全相同。
约8.8倍墙钟改善仅属于此离线夹具；实际default03仍FAIL，没有宣称生产RTF或GIL因果得到解决。

| 验证层 | 实际结果 |
| --- | --- |
| Async/helper专项 | 138 passed，source不变/exit0/reaped；纯合成协议，无WSL/NN/GL |
| Evidence专项 | 22 passed/7 subtests；真实临时文件off/on字节相同、原SHA次数相同 |
| 最终focused03 | 312 passed/46 subtests，pytest6.37s/driver6.869961s，最终源恒定 |
| 最终完整QA01 | 四阶段通过：3399 passed/45 skipped/6既有warnings/1024 subtests |
| QA身份 | pytest164.41s，driver222.722753s/exit0/reaped；490程序/测试/补丁输入前后相同 |

default03在最终QA后执行，使用完全相同的490项最终输入；其FAIL没有被质量测试覆盖成通过。
原source amendment仅native_adapter一行记录发生数据变更，其余条目数据相同；编辑元数据在全部检查前规范为LF，
原EXTRACTION_MANIFEST未改。归档保存该语义差异核对，最终Git仍按实际受测字节提交。

## 复现与归档

使用本机已核验的原Linux spec、原模型/ELF和独立安装的第六client；这些二进制和本地配置不随仓库发布。
诊断参数与边界见[说明](../../NATIVE_PHASE_DIAGNOSTICS.md)。所有实际argv、显式环境、driver、源码快照、
JUnit、原始结果与匿名绑定/CPU审查在本包records中。三次native不得重用旧输出目录。

```powershell
.venv-sim/Scripts/python.exe tools/smoke_wsl_native_live.py --native-transport wsl_async_bgr_v3 --profile-phases
.venv-sim/Scripts/python.exe tools/check_project.py --out artifacts/YOUR_FRESH_QUALITY_DIRECTORY
```

第一条只生成计划。真实run仍须完整本地spec、root/manifest、scope、相机/codec/调度及显式run，不能把模板当已部署算法。
本轮完整QA显式使用POLAR_TEST_WSL=1与本机已核验POLAR_WSL_TEST_SPEC；最终默认native03的实际argv不带任何可选计时。

[MANIFEST.json](MANIFEST.json) 将原路径、原字节SHA映射到[records.tar.gz](records.tar.gz)的内容寻址payload，
归档逐payload顺序解压核验。私有admission、完整SDK/owner账本和无关Windows进程清单仅保留本地，记录其SHA与排除原因，
不上传明文凭证或未授权内容；公开保留同源数值phase、native原事务、完整像素核验与匿名审查。
本README、进度结果段及归档在QA后补写；[FILES.json](FILES.json) 固定包文件SHA，不自引用。

本次归档含3652条原路径记录、641份唯一payload、3份实际BGR样本，共4,499,779字节。
records.tar.gz SHA256为`1cb89be9c311d1b060eac8926edc5090aa28c51fed8bb2e8667e76fcd3049773`。
