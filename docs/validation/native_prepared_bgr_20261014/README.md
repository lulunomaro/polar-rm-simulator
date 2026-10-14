# Prepared-BGR 修复检查点：实时 native 仍未通过

本包保存2026-10-14三轮新失败、源/构建/配置身份、前后专测、最终资源准备与统一质量原件。它补充[旧第12轮](../wsl_native_live_20261013_attempt12/README.md)，不覆盖历史包。原六车、2ms、1440×1080、15总FPS、一视角、曝光80ms wall+sim与SDK150ms保持；M0–M5未完整签收。

## 三个不同阶段的失败

| 原件 | 真实结果 |
|---|---|
| [actual1](a1/f007.json) | 旧a808…spec因当前portable/CMake build-input身份不符，startup前严格拒绝。没有放宽hash或修改旧buildmanifest。 |
| [actual2](a2/f013.json) | native启动失败；raw0、physics0、NNrequest0、result0，只有[host startup/closed](a2/f006.json)，无Linux STARTUP/OWNED_CHILD/CLEANUP。Runtime本地clean不等于Linux整栈clean；旧记录约−1.5µs duration属于未启动测量无效，不是性能数据。启动失败根因仍开放，不能证明Linux根本没创建child。 |
| [actual3](a3/f022.json) | 5000实际步/10sim：physics10.0004716s/RTF.999952842；run+cleanup10.0587424s/ratio.994160065。148raw在原80ms、1真实native请求/0响应/0物理消费、fire0。原ELF stdin1732/1732字节、等待47.378868ms后control_timeout；实际像素退出后审计、同run出生/退出/空组/tmpfs证明通过。 |

actual3单首请求factory5.2297ms、hostprep.1399ms（receipt.0184ms），不是每帧统计、纯NN时延或同源配对性能改善。输入完整不证明NN结束，原完整T2未产出deadline内结果。physics与run+cleanup分母独立，setup也不计作推理吞吐。

[当前spec](build/f010.json) 42ea570cf52105ce40990ef262b6bb9ff4579cc19fd259d8386588f2a4ef2b29复用已有当前匹配的29TU clean checkpoint；原ELF4d357067…、原模型b53470b4…、contour-v3、config与模式保持，不重复编译或给新字节赋旧hash。build分组保留manifest/attempt/原spec/yml/generated/模式/syntax日志；不发布ELF、模型大文件、编译objects或依赖前缀。实际CPU配置与compile LATENCY源在refs，未声称新的线程配置收益。

## 修复与源版本边界

Windows私有工厂只算一次同immutable BGR的SHA。receipt配对的是same bytes对象、image、episode/frame、曝光/control/deadline、校准和own四vectors；robot/消费者/generation/binding由上游snapshot ingress与owned out path负责。receipt不是全部sensor/authority封印；有receipt却错配直接reject/STOP，无receipt的legacy/普通入口才完整host hash，LinuxSHA始终保留。没有跨帧重贴、刷新时戳或放宽80/150ms。

actual3已有validation前/后guard和WORKER phase。后继只强化慢file-open之后、最终Popen前的共享cancel/STOP/原启动deadline重检及严格tmpfs证明；检查后到达的取消交owned cleanup，不绝对声称原子竞态消失。PRE_NATIVE_EXIT区分未spawn且tmpfs_removed与实际child reaped，缺证明仍failure；15s native setup/1.3s host资源预算不扩大。零步未开始时duration=None的harness修订不改旧actual2原字节。

actual3的179份执行源在sources：执行后从当前文件逐SHA匹配原EXECUTED_SOURCE后保存，非独立preexecution capture。它们是后继最终guard之前的真实版本，不能重标最终SHA。最终guard源另在f6/linux2/start2；该版本没有重跑NN/GL live。

f1/f2/f3为各自63/55/55 passed、14 skipped、70 subtests；f4原94passed/1failed/20skip/75subtests完整保留（测试patch只观察legacy转换入口）；f5专测修正后95passed/20skip/75subtests；f6最终95passed/21明确skip/76subtests。Linux清理先13、后14 tests/unit，包含真实无害进程/STOP/SIGTERM/deadline file-setup，不是导航或NN闭环。所有skip不计通过。

独立[startup probe01](start/f008.json)6.352s与[probe02](start2/f010.json)4.315s均原ELF初始化read(0)、0NN/0physics且资源clean。它们的run/boot/PID/PGID/start/spec与tmpfs证据分别保存，不能补actual2缺失的Linux清理，更不补旧12或actual3实时0响应。

navcpu保存真实归档584点/51IMU的机械热段诊断及原ledger/source：重复copy约.14ms、未复现18–20ms峰，不实施该优化。生产尾frame点数未保存、Windows CPU计时量化不能对单调用归因；旧导航seq67尾超时仍开放。review的analyze.py与两份report原payload保持。此前文案遗漏的实际[PREPARED_REVIEW](refs/f009.json)和[REVIEW](refs/f010.json)另增明确补遗入口，原SHA分别d8ee0e5e…/e892b84d…；旧review/f001、f002不删改，不再误标缺失，也不将只读分析当实时或完整验收。

## QA与后续文档

[QA01](q1/f002.json.gz)原[pytest](q1/f004.log)为1285passed/1failed/32skip/875subtests：默认old a808 native初始化spec被严格builder门禁拒绝。没有改旧spec或自动回退。

[QA02](q2/f002.json.gz)显式POLAR_WSL_TEST_SPEC选择已有42spec：四阶段exit0、source_unchanged_during_checks=true，1286passed/33明确skip/876subtests、6已有warnings；[pytest](q2/f004.log)118.64s，driver137.4281345s/reaped。这是本机质量与软件资源初始化资格，不是实时自瞄、完整比赛或发布验收。

QA后仅修改IMPLEMENTATION_PROGRESS、WSL_NATIVE_TRANSPORT并新增本证据包。post保留首修订，post2保留最终精确receipt/guard措辞；before原字节匹配QAmap，除两文档外当时所有checked文件SHA仍相同。旧修订原件不覆盖，不声称新增归档/最终整个repo等于历史QAmap；业务.py/DEVELOPMENT无改动，也没有为低影响docs再跑全测试。

## 保存、缺件与复现

26个原证据组＋post/post2文档元数据组，552个literal payload（原550＋2份明确补遗report）；[PRESERVATION_MANIFEST.json](PRESERVATION_MANIFEST.json)和[INDEX.tsv](INDEX.tsv)逐条列原路径、SHA、大小、短文件名。大文件gzip mtime0，原有gzip保持原字节，原混UTF16/UTF8 WSL日志不重编码。STOP无扩展名身份文件同样保留。模型/ELF/objects/缓存排除在manifest，不冒称包含运行依赖。

凭据扫描曾对公开launcher.py的`credential='provisioned_in_memory_at_launch'`语义标签误拒；主代理确认该源逐字节等于已公开HEAD53fb。只按整文件SHA241fd366…＋精确key/value白名单保存，其他真实credential仍拒，不泛化跳过credential键，也不改原件。初次停止仅有结构工具观察、没有独立raw进程日志，见[MISSING_RECORDS.json](MISSING_RECORDS.json)。

包内核验在新clone无需ignored artifacts：

```powershell
.venv-sim/Scripts/python.exe docs/validation/native_prepared_bgr_20261014/verify_archives.py --archive docs/validation/native_prepared_bgr_20261014
```

它仅核stored/restored SHA、gzip和INDEX，originals_checked=false；原路径缺失列出，不把包内SHA称作当前原工作区比对。本机严格逐字节核对原件须显式选择：

```powershell
.venv-sim/Scripts/python.exe docs/validation/native_prepared_bgr_20261014/verify_archives.py --archive docs/validation/native_prepared_bgr_20261014 --check-originals
```

原件缺失/不同即失败。本机[append3-corrected.originals.json](append3-corrected.originals.json)及raw输出真实exit0，originals_checked=true、552原件全部比对、missing0；[append3-corrected.package.json](append3-corrected.package.json)是独立包内模式。首append3临时把原两review的manifest行换到refs而物理文件未变，随后纠正为保留原550行并追加2行；首日志保留，纠正后的新proof不覆盖旧记录。初次544份及随后550份保存/验证原日志与原verifier快照同样保留。没有重跑测试/ROS/WSL/NN/GL。

真实复现命令和本机spec选择见[WSL_NATIVE_TRANSPORT](../../WSL_NATIVE_TRANSPORT.md)；公开读者按当前构建脚本生成并验证自己机器的spec/可选codec身份。私有路径和原buildmanifest是原执行出处，不是跨机启动就绪声明。完整M0–M5、默认实时链、移动/开火、多车比赛、LAN/新机器/Windows-native/HIL仍未签收。

[FILES.json](FILES.json)包含本包全部精确永久文件（自身避免递归hash另列），[OLD_ARCHIVES_UNCHANGED.json](OLD_ARCHIVES_UNCHANGED.json)证明旧三包1009文件原字节保持。包内hash、原件比对、源资格、构建、资源初始化、离线算法、实时动作与完整验收分别记录。
