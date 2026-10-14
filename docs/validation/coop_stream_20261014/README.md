# Windows 手动入口与 JSONL 传输检查点

本包保存 227 件原始记录，原字节 13,440,204 B、存储 1,591,981 B；大件无损 gzip，其他按原字节保存。
每件原路径、大小、SHA 与存储映射见 `PRESERVATION_MANIFEST.json`，其 SHA256 为
`9a7eb7bc5f0409465998afeefae566dec676783c17271da0ea1a2668600465d4`。
创建时每件解码后与工作区原件逐字节比较通过，见 `VERIFICATION.json`。旧验证包未修改。
未打包凭据、admission、SDK_EVENTS、ELF、模型、第三方源码 clone 或依赖环境。

| 分组 | 实际证据和边界 |
| --- | --- |
| stream_focused | 修复前后原源、102通过/2 Windows symlink权限skip。保存DTO framing+JSON离线对照，不是实际OS传输或NN门限通过。 |
| stream_actual / stream_tree_a / stream_tree_b | 两项实际Windows→WSL无害进程树夹具，exit0/reaped/source unchanged，driver9.8535942s。没有图像/ROS/NN/物理控制。 |
| pb_probe / pb_driver / pb_audit | 原Source03/模型、单张真实受控MuJoCo图像，完整act字节已抵达peer，但原80ms仍失败；未ROS publish/检测/PnP/跟踪/命令。没有SDK租约或动作消费。所有节点/相机资源clean与设置恢复，不算算法通过。 |
| behavior_audit | 官方比赛树/工作区/BT依赖精确SHA、取源进程结果、逐文件哈希与只读审计。未编译/运行；默认树、导航接收入口、合法消息/场地图/spin/目标时效/取消缺口仍开放。 |
| coop_focused | 新启动器21项单位/身份/生命周期检查，exit0/reaped/source unchanged。 |
| coop_actual / coop_driver | 8秒配置的真实固定Qt与v2服务启动，driver10.3184506s/exit0/reaped/source unchanged。服务正常资源关闭确认、服务exit0；Qt在回收前仍运行，随后被owned Job结束。两个Job均空/reaped。没有观察或操作UI，未验证按键、画面、射击、导航或比赛；game_ready=false。 |
| quality / quality_driver | 最终统一QA03四步exit0/source unchanged，1807passed/40明确skip/1008subtests/6已有warnings；pytest133.07s、driver168.8232764s/reaped。只表示本地质量检查。 |
| tested_source | 六个新/修改的程序、测试与示例，原字节SHA与QA03 source_files_sha256相同。 |

PB实际追踪保持原曝光身份：capture→public23.3902ms、act入口35.0607ms；host校验12.1049ms、dumps11.9974ms。
入队6,225,306 B/SHA `5b71884b032f6e59ff09b0f116a8adb2875487db1947084866ffe587750cb210`；
实际FileIO.write完整返回、Linux第三line同长度。Linux bulk read9.707535ms、peer首strict decode16.735ms，
随后原bridge begin被取消。host/Linux时钟分别分析，不跨域相减，也不把post-dumps间隙当纯encode时间。
本次仅记录实际入队bytes的长度/SHA，没有保存完整wire副本；不能将重建JSON称为实际wire。
原观测、像素、场景隔离说明、phase、失败与清理原件均保留。

保持80ms图像/150ms SDK、Linux1.3s/host1.5s、reset2s/graph1s/ROS50ms。
新launcher8s是整套本地退出监督预算，不扩大任何adapter原期限。缺资源关闭确认或不干净进程证明仍失败。
本轮未重跑旧T2静态实时和PB单目标导航，未验证移动自瞄、自动火、多车/完整3v3、LAN或M0–M5。
QA结束后才增补入口说明、进度和本包；不称这些文档曾参与该QA。

```powershell
.venv-sim/Scripts/python.exe docs/validation/coop_stream_20261014/verify_archives.py
# 已有完整本机原实验目录时，可额外比较工作区原件。
.venv-sim/Scripts/python.exe docs/validation/coop_stream_20261014/verify_archives.py --originals
```

启动命令与下一步见 [COOP_PLAYABLE_PATH.md](../../COOP_PLAYABLE_PATH.md)。
