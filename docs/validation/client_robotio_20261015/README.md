# Qt 通用目录与新采样检查点：2026-10-15

父提交 `e3bac435551e400501e622ee917c7311a6a9c4da`，开发分支 `work/plan-t01-t03`。
本包保存174项原文件，原始3,597,130字节、存储1,199,271字节；literal/gzip及原始SHA映射见
[PRESERVATION_MANIFEST.json](PRESERVATION_MANIFEST.json)，其SHA256为
`8b644303de7cb5c34ab5ed3bf00d807d4ba17d0e31f0dde847e6b8a181f4145d`。
路径中的20261014是原run标识，记录未改名、重判或覆盖；最终整理与交付日在15日。

## 已验证范围

| 记录 | 实际结果 | 资格 |
| --- | --- | --- |
| client-robotio-navigation01 | 原Qt offscreen 286passed/91subtests/0skip；pytest14.58s、owned外层15.1554384s/exit0/clean | 真实PySide6事件与原Jello/F2/租约回归，后端是测试夹具；无物理/工业相机/可见GUI |
| coop-robotio-options-focused04 | 53passed；1.1878273s/exit0/reaped/source unchanged | 本地选项、身份、文件变更拒绝与清理mock；之后canonical config路径修正由QA06验证 |
| navigation-reset-capture-focused02 | 43passed/2已有warnings；6.81s | 初始化90ms、旧/排队采样丢弃、真正新采样、legacy行为与reset故障；受控时钟/线程夹具 |
| qt-robotio-protocol-actual02 | 12checks全true、原身份/SDK150ms审计无错；1750步、26独立source动作、3736receipt/1247非零消费步 | 实际offscreen Qt控件→客户端解析/SDK→HTTP→MuJoCo，低点频合成协议策略；无原PlatformWindow/NN/ROS/比赛 |
| quality-aim-followup06 | 四步骤exit0/source unchanged；2037passed/40skip/1010subtests/6已有warnings | 配置、来源、接口、全量回归；不是里程碑验收 |
| client-robotio-final-dry-check01 | plan/source inspection两命令exit0 | 最终graph/选定patch原字节核验；未创建算法/物理/GUI进程 |

最终QA pytest148.02秒，外层driver191.7993803秒/reaped；显式原CPU4 spec与所有原门限保持。
QA后只有进度结果说明和本包增补；程序/测试/DEVELOPMENT_CHANGES/patch维持QA06 SHA。
包中同时保留当前文档和QA时文档hash；QA之后的说明与归档不能写成已经参与此前QA。

## 客户端与物理验证

组合patch从固定客户端基线 `0cedf99b70b1beec99865b9980af6789e6c53d99` 出发，包含全部旧patch及通用目录修改；
新manifest SHA `3916988423e6f7d3c0394d19df7a02cb241b72d28172c50d1ca6f970c9129bdc`，
新patch SHA `594b8562ba88dadf2facb59a1bdaa3517c4be22bf7397b4512d97b07c942e9e3`。
旧manifest/patch与旧review checkout原字节不变，新review checkout独立应用、reverse-check通过，没有向客户端仓库提交。
安装及配置见[客户端通用接口](../../CLIENT_ROBOTIO_INTERFACE.md)。

[实际02 RESULT](records/artifacts/qt-robotio-protocol-actual-20261014-02/RESULT.json)保留自己的确切源码，
包含实际Qt QWidget/QComboBox/QPushButton、客户端catalog/plan、独立decision/navigation JSONL进程、原SDK150ms窗口和MuJoCo执行器。
点云为显式1000 points/s实际ray/gyro/accelerometer，物理dt2ms；合成策略只输出配置目标和恒速。
世界位置只在隔离EVAL，未送给peer。两资源真实prepare .4174462秒且无观测/推理；实际binding仍有reset/能力握手。
内部用时7.0027297秒、外层8.9554348秒、源不变；runtime join .0232754秒，两个peer/Qt Job/SDK/IO/HTTP均clean。
有26个独立原动作，不将重复receipt当作新增算法输出；fire未授权给算法。

它没有运行原PlatformWindow、工业相机、GL、原F2/watch全链、ROS/WSL或队伍算法。
原F2回归来自另一真实Qt测试夹具，不能与此物理控件harness拼成原窗口闭环。
完整可见启动、RTF、MID360/SLAM、目标到达、自瞄NN、自动火、移动/多车和3v3/7v7仍未验收。
decision v1 navigation/perception仍unavailable；T2静态live/PB单目标导航的原局部资格保持，PB80ms图像失败与Tongji图像缺口未关闭。

## 原失败与修复

- 原客户端初次fixture失败、PYTHONPATH收集失败、后续Qt通过、前后三文件和export脚本均按原字节保存。
- launcher前三次专项XML与最后捕获的04保存；04后CLI带`..`路径冻结修正由QA06新增回归覆盖，旧04源码hash不重标。
- [实际01 RESULT](records/artifacts/qt-robotio-protocol-actual-20261014-01/RESULT.json)整体失败。
  create9.8134ms、reset81.6638ms后首原输入仅余24.96ms，compose等待越过deadline并fault，0物理运动；
  Qt/SDK/子进程退出证明不把此次改判为通过。
  修复只对显式通用navigation/pipeline：成功reset后按原frame_id/sim_time/host capture_wall丢弃初始化前/期间排队采样，
  等待真正新采样继续同实例；不重贴身份或期限、不伪造零速，reset失败仍故障。
  actual02用新源码重新运行，01原数据未覆盖。
- 初始化时序测试首次5fail/38pass/7.32s只保存当时源与tool摘要NOTE，原stdout未捕获。
  错误断言异步close立即完成、期待bounded latest queue保存两条结果；后续独立发布hook和有界join修正fixture，
  43pass保留原JUnit。没有补造首次完整日志或把mock时间当物理性能。
- AST-only静态记录早于protocol工具增加两处source快照，不写成最终执行字节验证；实际01/02与QA06各自绑定准确SHA。

## 完整性与复跑

`FILES.json`覆盖本包其他所有文件。校验不执行算法：

```powershell
.venv-sim/Scripts/python.exe docs/validation/client_robotio_20261015/verify_archives.py
```

gzip解压后核对original_bytes/original_sha256；保持此包不可变。
实际协议复跑使用全新输出目录和显式执行开关：

```powershell
.venv-sim/Scripts/python.exe tools/qa_qt_robotio_protocol.py --out artifacts/qt-robotio-fresh --duration 3.5 --run
```

必须先取得并核验真实本机客户端/Qt环境。公共包没有凭证、模型、ELF或私有admission数据。
各队真实wrapper、实时自瞄及比赛需新的独立原传感器→算法→执行器证据，M0–M5均未签收。
