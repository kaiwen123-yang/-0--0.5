# 来源字段、物理证据和本机映射

| 来源 | 来源内可用字段和证据 | 仍待确认的本机映射 | 最少补充材料 |
|---|---|---|---|
| 本机 50 条 | J1–J6 实测 rad，最后一维为 Piper H SDK 实测 width（m）。手拖期间无 TX。观测和未来目标分别取查询时刻前最新反馈，腕图按接收时标取样。 | SDK 宽度与指垫间机械净距是两个量。现有训练合同已经成立。 | 本轮无需额外数据。 |
| A 积木 | 发布顺序 joint1…joint6、gripper。对 900,642 个原始关节状态值检验厂商 ROS 毫度转弧度网格，最大残差 0.00684 个编码刻度。action 也符合该网格。cam_gripper 直接看见夹指、积木及盒口。 | 强证据支持弧度数值尺度与字段顺序。没有定位到该 SHA 使用的采集实现、实际机器子型号、各轴方向及零位。夹爪 state/action 同落在源数值 0.00007 的格点。该量化步长不能给出 H 的 SDK 开口映射。 | 与该版本关联的驱动配置或原记录，说明机型、J1–J6 的寄存器与有符号方向、已知姿态零位，以及夹爪开/合和中间位置的原读数、比例、零点。若与 H 不同，需要可复核的几何或关节映射。 |
| B 叠碗 | 发布字段前七维标 left，后七维标 right。研究团队给出单臂叠碗、双 PiPER-X 和四 D435 的装置说明。front/head 中的夹爪与源 right_wrist 一起到达黄碗、搬到绿碗、离开。前七维夹爪随之开合，500 条中后七维夹爪回合内极差全为零。工作侧六轴符合 3.14/180000 的编码网格。 | 已审画面和数值支持**工作侧语义对应**前七维与 right_wrist，可在来源诊断中送入 left_wrist_0_rgb。未确认电缆侧别和逐机序列号。X/H 运动学与腕安装不同，夹爪数值 0.0001 的格点不能独立证明 H 的标定。 | 该装置的关节/腕相机接线或采集配置、X/H 同参考姿态、各轴方向及宽度标定。存在双臂操作时还须确认完整单臂子任务。 |
| C 四色 | 固定转换说明指明 CSV state_0..6 为 measured robot feedback，actions 为同帧发布的绝对目标。state 前六维符合 π/180000 的弧度网格，夹爪声明总宽 m。新目标在源内作为未来反馈使用。wrist_image 为工作腕，image 用于审查结果。 | 采集副本没有原发送回执；同帧目标与接触实测开口可不同。info 的 piper_standard、旧 repo_id 的 piperx 和权重路径均不能绑定实机子型号。未查到适用于这个数据版本的许可。当前腕图是否足以选中正确积木、正确盒子随阶段而变。 | 固定版本的数据授权、采集装置型号与零位、实测总宽到 H SDK 的对应、单帧决策时可见性。未来反馈版本无需把原发送回执作为必需标签。 |
| D 笔/胡萝卜 | modality.json 仅把 state[:6] 命名 joint。笔 0 号首行 J2=0.1572791，胡萝卜 30 号首行 J1=−0.0340516。服务文档声明输出相对起点，不能据此识别已发布 state 的参考系。 | 数据集或变换可能用了各自参考系。两项合计 63 条保留原件。 | 带同一回合标识的已知绝对姿态、q₀ 以及写 Parquet/读策略的变换；以首行和第二个姿态核对方向与偏置。 |
| E 官方五样本 | 原始 master 和 puppet 双侧流可查，独立保留五个 HDF。社区版本采用另一套 FK/夹爪表示。 | 批次机型、宽度标定及单腕可完成的任务边界未齐。 | 逐回合批次对应、夹爪标定、单臂完整性证据。 |

## 关节刻度证据的边界

厂商 Noetic 节点按 J1 到 J6 读取反馈，将每个毫度计数乘以 0.017444/1000。Humble 节点中，反馈和控制目标均能使用同一换算。A 的状态和 action 在这个格点上的最大偏差都小于 0.007 tick，但格点无法判定流究竟来自哪条接口。B 工作侧在 3.14/180000 格点上的 P99 残差为 0.00542 tick，C state 在 π/180000 格点上的 P99 为 0.00507 tick。派生数组保留源浮点值。[厂商 Noetic 节点](https://github.com/agilexrobotics/piper_ros/blob/ac41fcbcdda598f01b51cf6175ed9a24d0dacadc/src/piper/scripts/piper_ctrl_single_node.py) · [厂商 Humble 节点](https://github.com/agilexrobotics/piper_ros/blob/017ffefa64511bc6325bd77ddc4e16065c152051/src/piper/piper/piper_ctrl_single_node.py) · [逐来源数值结果](quantization.csv)

## A 的负夹爪 action

在 200 条的 150,107 个原始行中，59,413 个负 action 分布如下。分段以 state 变化定位，使用源数值阈值标记近似阶段，不用于认定成功或改变样本。首个 state>0.05、之后首次 <0.040、再首次 >0.045、再首次 <0.015 分别提示张开、夹取、释放张开、撤离后闭合。阈值未给出完整转换的末行另列。逐回合视觉确认独立于这些阈值。

| 段 | 全部行 | 负 action 行 |
|---|---:|---:|
| 首次张开之前 | 47,373 | 42,829 |
| 张开接近 | 33,731 | 0 |
| 闭合及夹持搬运 | 49,119 | 6,364 |
| 释放张开 | 9,060 | 24 |
| 释放后再次闭合 | 10,779 | 10,166 |
| 阈值未定 | 45 | 30 |

若释放时未越过 0.045，阈值段会把后续空爪也算入闭合/搬运提示段，因此 6,364 不能视作已证实的持物负值行数。独立取完整候选中六个取样帧均不同的 105 条，查看每条搬运中间帧，8 条原 action 为负。例如 168 号帧 501 可见绿块随夹爪移动，state=0.03241，action=−0.00119。全库闭合/搬运提示段的 state 中位数 0.03234，原 action 中位数 0.00441。多数负数对应两指接近闭合，夹住物体也有负目标。空爪近闭合时可见正的 state 和负的 action。这个分布与指令和接触开口有差异相容，无法据此确定偏置或恢复下发命令。源 action 的符号和幅度全部保留。[105 个搬运帧对照](A_carry_frames.csv) · [分阶段结果](phase_summary.csv) · [逐回合阶段](phase_by_episode.csv.gz)

## B 的工作侧与第二只手

319 号帧 74，前夹爪约 0.0994；帧 99 缩到 0.0343；帧 111–136 约 0.0004；帧 161 又张到 0.0994。后夹爪在这些帧均为 −0.0008。外部视角帧 84、112、139、167 分别见到接近碗沿、抓住黄碗、移到绿碗及夹爪离开。right_wrist 依次看见黄碗沿、黄绿碗靠近及放下的碗，left_wrist 看向桌边。后六轴的单回合最大极差中位数为零、P95 为 0.01183、最大为 0.15395 源单位。专门检查了后侧运动较大的 93、117、319 号，取样帧未见第二只手承担搬运；93 号套叠末态仍单列存疑。对其余未看全的回合保留 14 维和原视频索引。来源样本不镜像、不交换关节、不翻转符号。[RoboNever 论文](https://arxiv.org/html/2605.26820v3) · [作者配套代码](https://github.com/Agentic-Intelligence-Lab/ContinualVLA/tree/d84ed7a811f95218e79ac5f0906465147ad7e1e3) · [补查帧号](B_review_frames.csv)

## C 的总宽、语言与可见性

按源 action 定位闭合（首次 <0.035 m）和释放（随后首次 >0.055 m），数值阶段由原指令阈值定义。接近阶段 state/action 中位数 67.6/68.6 mm，闭合与搬运 34.6/11.2 mm，释放 67.1/67.9 mm。另有 390 行未分配。22 号的实际画面显示将绿块送往黄盒，234–235 行邻近开口事件；31 号绿块抓取和搬运时 state 约 33.5 mm，原目标约 7.7 mm。使用未来 state 即可留下接触时的实有开口，逐库缩放会抹掉这项差异。[固定转换说明](https://huggingface.co/datasets/tianxiwei/piper-four-color-block-sorting/blob/8d5ee5d2a44dfe1798489d13c1fc0bdd168be12e/conversion_notes.json)

原审阅覆盖 12 种物色→盒色组合。31 号腕图帧 37 可见若干盒，帧 112–187 主要看见深色容器、夹爪和绿块，224–299 再次看到盒口。先前出现的目标盒并不总在当前抓取图里，释放时局部绿色也无法独立证明在多个盒中选对。当前读取器每个起点只取一幅 RGB，十步块是输出，没有图像历史。文本中同时保留物色和目标盒色。待许可清楚后，逐决定标注当帧可见的候选物/盒、遮挡及空间关系；区分由固定布局或状态可预测与图像中可辨别。[原视觉审阅](../piper_dataset_audit_20261125/visual_review.csv) · [实际读取器](../../tasks/piper_real_single_v1/dataset.py)

## 公开实现与许可检索范围（11 月 25 日）

- A 固定卡片链接通用 LeRobot；homepage、paper 与引用留空。检查固定版本仓库树、上传历史、作者 Hugging Face 主页及 GitHub 同名/完整数据集名代码检索。通用 LeRobot 当前树及无来源绑定的第三方 Piper 插件不能确定这批记录实际选择的设备、夹爪字段或采集端版本。完整数据集名的 GitHub 命中为第三方评测资料。数据卡给出 Apache-2.0。[A 固定卡片](https://huggingface.co/datasets/DRMNmadhan/piper_pickdrop_200/blob/867554b0b60c78d779e048203acb28e19fab650b/README.md)
- B 锁定的主项目 README、论文与 ContinualVLA 消费端给出设备与任务组。modality.json 和发布标签能核实字段位置。配套训练配置、另一数据集转换器和按钮裁剪脚本均不能确立本叠碗版本的原始总线接线或独立命令历史。[B 固定数据树](https://huggingface.co/datasets/Ray0v0/cl-piper-single-stack-bowls/tree/f81ff5e07c31053b39e64aa621882d6d17705d52)
- C 检查固定树、README、conversion_notes、卡片元数据、初始/上传两个提交、同账号相邻二色/blackbox 数据卡、数据集讨论列表、同作者四色模型卡和 inference_metadata，以及 GitHub 新旧完整库名和同名账户仓库。讨论列表是自动 Parquet 转换。未定位能和固定数据绑定的公开采集/转换源码或数据授权。模型卡采用 Gemma 权重条款并引用旧 repo_id，不构成数据许可或机器铭牌。没有联系发布者。[C 固定树](https://huggingface.co/datasets/tianxiwei/piper-four-color-block-sorting/tree/8d5ee5d2a44dfe1798489d13c1fc0bdd168be12e) · [发布者配套权重说明](https://huggingface.co/tianxiwei/pi05-piper-four-color-step2000/blob/c438dd02949b9a14295117a4e1e6da1b2fa1c545/README.md)
- D 检查锁定 README、modality、首行表和笔/胡萝卜原始行，检索 piper_serve_openpi.py 及同名 GitHub 账号公开仓库（含 fork）。未取得能绑定此版 Parquet 的写入参考系证据，保留原值。[冻结参考系核查](../piper_dataset_audit_20261125/D_representation.json)
