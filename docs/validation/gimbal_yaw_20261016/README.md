# T03/T04/T06 显式 yaw 位置反馈与异步接收审计

2026-10-16，父提交4f0cb05891a99c837324ee67c9f1074905deb21e，work/plan-t01-t03。未调用子代理。
本轮真实实时回归全部FAIL，不继承前一检查点的局部实时资格；M0–M5未关闭。

## 控制改动

在已验证平面本车的position_gravity_v1上新增显式--gimbal-yaw-gain，有限无量纲值1..4，默认1。
非1值必须同时显式选择该servo；真实服务器和诊断均在模型/准入准备前拒绝无效参数，启动报告实际值。
raw_ref是原算法或手动输入的关节位置参考：有效期间ctrl_yaw=clip(raw_ref+(gain-1)*(raw_ref-own_qpos_yaw),原ctrlrange)。
这是底层外层比例位置反馈，提高了有效闭环位置刚度；不是目标速度前馈、预测、PnP或队伍算法输出替换。
模型质量/惯量/原kp/kv/阻尼/限位数组未改，但软件控制律改变，不能声称闭环增益没有变化。
指令失效/撤权时关闭额外yaw增益，仍转原当前关节保持；不延续旧角度、不修改原80ms图像/150ms控制窗口，fire权限不变。
每个原执行边界从原参考重新计算，避免三次/四次守卫累计乘增益。无需给各队自瞄新增字段或改变RobotIO动作形状。
仅适用于原gravity servo通过验证的本车模型，不据此承诺任意模型稳定。

新增24项回归覆盖正反匀速参考、六车阶跃、原参数不变、限幅、执行中撤权/禁射、过期关闭增益、跨边界不累计、无效入口提前拒绝。
明确合成Clock、实际六车MuJoCo、每150ms新零pitch/ramp yaw原输入且TTL40ms，1500x2ms步：
两方向增益1/4末段有效样本yaw参考RMS分别0.0192761833/0.0048488271rad，各126样本，原完整序列保留。
这不是原生推理、瞄准精度或实时RTF通过。

旧4f0cb05检查点源快照与当前gain1源的ABBA各1500步物理/标量trace对照：
旧0.963284/0.921289秒、新0.923942/0.962723秒；四组最终qpos/qvel/ctrl逐SHA及27000执行阶段计数相同。
墙钟有漂移、无GL/NN，不作因果提速或整套实时回归等价结论。比较01因旧源副本缺arena.xml未运行物理，
失败stderr保留；02补齐原未改场地数据后完成对照，未覆盖01。

## 四轮原生实测与失败

| 本轮native | yaw gain | authority/计时 | physics RTF | 及时结果/独立帧执行 | 末2sim秒yaw参考误差P95 rad | 拒绝项 |
| --- | --- | --- | --- | --- | --- | --- |
| 01 | 1 | 单核0x10/无额外计时 | 0.942783247 | 116/49 | 0.102419054 | physics_rtf |
| 02 | 4 | 单核0x10/无额外计时 | 0.965446060 | 112/59 | 0.030723329 | physics_rtf,original_async_transactions_accounted |
| 03 | 4 | 单核0x10+计时 | 0.814786898 | 88/48 | 0.070189217 | physics_rtf |
| 04 | 4 | 不绑定单核/无额外计时 | 0.643593944 | 32/6 | 0.217825488 | physics_rtf,actual_native_actuation,original_target_motion_proven |

全部实际六车2ms/NVIDIA GL/1440×1080/15fps上限、相同原CPU4 T2 ELF/ONNX、CV4、CPython1ms、20ms显示、
latest_pending、stationary red_infantry、对方原motion租约横移0.08m/s；只有显式增益、记录的计时/affinity条件不同。
01/02是接收审计修复前源，03/04为相同最终程序集。04只有6帧执行，未满足最少10帧运动场景证据。
均实际像素反查/SDK原授权/原80/150ms/owned清理通过、无runtime/adapter fault、fire0；原始RESULT保持失败。
01/02误差下降不能据此关闭真实动态跟踪：二者都未达到RTF0.98，后续也有明显退化。
控制参考误差来自每原独立帧写控制前的关节实测与原生角度指令，末段统计不删完整启动/实时分类样本，不是目标LOS或命中误差。

03额外phase探针完整无丢样：authority_step wall P50/P95为1.5993/7.23528ms，backend样本P50约1.0612ms；
Windows thread CPU计时呈0或15.625ms量化，不能用短span差值推断精确GIL、锁等待或其他进程占用。
04是一次取消自有authority单核绑定的诊断，结果更差，未更改默认设置或系统电源/优先级；未继续盲目重跑NN。
当前性能退化根因未定位，单独的无渲染默认物理数值等价不能排除完整线程/渲染/推理环境问题。

## 异步时间账本修复

02请求74：stdout记录26208.3414334，原deadline26208.341537300003，accepted日志26208.341553，
比原截止晚约15.7微秒。原control在先前同一host QPC采样now判断时限，_record随后另采wall_time，
因此日志发布可能跨过原截止。上层已有重新检查并记录native_response_expired_before_action，02有2个此类原响应被扣留；没有迟到执行。
旧记录缺少独立判定时刻，无法补推其值，02归账失败维持原判。

现额外记录acceptance_decision_wall=原有判定now，wall_time继续是实际日志采样，不回填/覆盖/刷新任何旧时间。
归账要求同一typed原请求/帧/响应，host时钟、原内部deadline相同且不超过原source deadline，
queued_wall<=stdout_wall<=decision_wall<=log_wall，decision严格早于原截止。
上层结果发布与每次实际执行仍重新检查原deadline；decision及时但wrapper已过期只计扣留，不能成为native_result或动作。
旧无此字段日志仍按旧wall_time判断，不能用新解析器把02改成PASS。
新增13项原control延迟记录复现/字段错型/错时钟/伪成功/截止边界负例；相关205pass。
最终专项560pass/98subtests/2既有warnings，driver33.930098秒/reaped，501程序输入前后相同。
03/04在最终源上归账通过，其中03仍有1个响应被原上层到达截止挡住；整体实时失败不因此变为通过。

## 复现与后续

在[前一servo命令](../gimbal_servo_20261016/README.md)加--gimbal-yaw-gain 4；改为1即原反馈增益。
03增加--profile-authority --profile-phases，04去掉--authority-affinity-mask；所有输出使用新--out目录。
相同参数可追加到python -m rm_match.platform_v2现有启动参数。程序/模型身份与实际环境需重新核验。
旧原T2 ELF SHA256 67819b6812c2c4a87e2b411eed49c1e01cfb67212efdd2f2e0abd2aa3a963dec，
ONNX b53470b42a5778aca8f3382ebe3c623482599cbf8ebad2e9a0dcc0c7f42c9255，本轮没有重建或换算法/模型。
目标关联、PnP精度、遮挡重捕获、动态跟踪、射击、可见Qt、多车及完整3v3仍未验收。
本轮全量质量结果待冻结后补记；完整实际BGR留本地、每轮一个真实样本进Git；模型/ELF及clear credential不公开。

永久归档4723条记录、671份唯一payload、5,627,519字节；551份完整实际BGR留本地，Git取4份真实样本，12项私有账本只列SHA。
records.tar.gz SHA256：`9abdb1533f6504373d895545760eda48a9c3c9e7bb087c6d7a133430ceb2ba9f`。
[MANIFEST.json](MANIFEST.json)映射原路径/SHA到[records.tar.gz](records.tar.gz)内容寻址payload，逐项解包核验；[FILES.json](FILES.json)固定包内文件SHA（不自引用）。
