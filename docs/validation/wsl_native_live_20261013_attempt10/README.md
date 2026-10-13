# 第10轮：交接过期已安全丢弃，原native仍超时

同第9轮实际配置与80/150ms门限，新的slot在create/reset后复查原截止时间，过期帧丢弃而不把整个绑定置持续故障；算法实际异常仍故障停止。
运行10.02496秒，3684实际物理步，RTF **0.7349656873**；149次raw编码完成，其中148公开cache发布、148私有发布。
所有raw编码完成均80ms内（P50 29.492ms、最大36.795ms）；私有发布P50 15.237ms、最大21.815ms。
step wall P50 1.851ms、P95 8.169ms、P99 18.775ms、最大25.407ms。RTF仍显著低于第8轮，根因待实际相位诊断。

13次adapter_enqueue、11次结果；首个真正native_request是 **frame12 / observed_seq13**，曝光444ms、控制460ms。
实际RGB SHA `aae3f2c731479f57951f6aebf34b168ffe2462ff4bc1d1c91fc58b08e041c172`；实际BGR SHA `c08aaaa8b1a58d0f4f137ee462006959c9070fd2312da35f318db74a3416d817`。
这一帧private→enqueue16.488ms、enqueue→native_request12.797ms；公开编码已在enqueue之前结束。
13/13 enqueue均发生在同帧公开编码完成后，不能声称实际利用了早发布的调度窗口，也不能仅从事件顺序确定全部等待由GIL造成。

host native_request时原曝光预算剩36.865ms，bridge额外准备3.574ms后剩33.276ms。
Linux实际接收4,665,600字节，接收12.509ms、SHA1.925ms、tmpfs写2.105ms；向原ELF stdin完整写1729/1729字节。
实际native等待17.041ms后 **control_timeout**。完整pipe写入不是NN完成证据：零native_result、零物理云台消费、fire0。
owned PID699退出-15、reap，tmpfs移除，所有线程与证据worker退出，唯一实际BGR已保存并SHA核对，errors=[]、source_unchanged=true、clean_shutdown=true。
**live_static_chain_qualified=false**；不能用离线34.7–57.6ms推理回复填补本次live空结果。

原报告 exact_sensor_pixel_binding=false：末frame149在终止期间完成公开编码，未成功私有发布，严格原汇总要求每次encode都对应private publish。
SDK只有expected_runtime_stopped，没有release成功ACK；不能伪称主动release已完成，也不能把未发布尾帧称为图像替换。
已提交的frame12有完整raw/private/预算/hash关联；后续汇总修复须保留这份原报告并记录未发布原因。

命令与源码参看PLAN/EXECUTED_SOURCE；复现同第9轮命令但使用fresh output。EXECUTED_SOURCE_BYTES.json.gz保存163项原运行源字节。
PRESERVATION_MANIFEST绑定23个文件，包括sensor_12.bgr.gz：解压必须为4,665,600字节并符合上述BGR SHA。
这不是Qt可见桌面、完整比赛、Nav2、LAN或硬件验收。
