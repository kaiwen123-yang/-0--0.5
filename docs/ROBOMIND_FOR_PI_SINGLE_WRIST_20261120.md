# RoboMIND 对 π0 / π0.5 单腕相机实机测试的适用性

更新：北京时间 2026-11-20。研究范围：Piper H 单臂、官方夹爪、唯一腕部 DC1（CC16762023M）、π0 与 π0.5 全参微调及实际测试。现场基线读取到 `22c70f39bfd48e4aebed80cadd413491b0766ae6`。本文是调研与下一步方案，未启动模型训练、推理或硬件动作。

## 1. 建议与结论

**优先用 RoboMIND 的相关公开真实示范，尝试“零本地任务示范”的首次迁移测试；暂不把批量自采示范设成开工前提。** 有动作监督的真实训练数据可以来自公共数据集，norm 也可以只由经过适配的公共训练 split 计算。此前“真实示范未就绪”不等于“必须全部由用户自行采集”。

最值得筛选的是 **RoboMIND 2.0 的 AgileX 部分**：官方项目说明有腕部视角，官方工具包含 Piper 家族运动学资产，实际发布样本中已经读到六关节、独立末端位置字段、示教侧和执行侧分开的结构。当前只能确认它是最相关的候选，尚不能确认所有轨迹的机器人版本、单位和控制语义与 Piper H 相同。[S4][S6][S7]

**手眼完成后能否立刻做任务测试，取决于并行工作是否也完成。** 手眼解决相机与机械臂的几何关系；对应任务的策略训练、动作适配、norm、连续关节目标执行与停止仍需就绪。当前 RGB＋关节接口没有自动把手眼矩阵转成操控能力的步骤。离线数据适配和训练不需要等待手眼；手眼也不是关节空间视觉策略的一般数学前提，但本项目已安排的空间一致性验证应按原计划完成。[S11]

本次研究支持“争取不采本地训练演示”，不支持“基础权重加标定即可保证成功”。没有发现能为本机单腕配置给出最低自采条数或可保证减少百分比的研究。是否最终需要少量补采，应由公共数据训练后的真实失败类型决定。

## 2. 数据集版本与范围

| 项目 | 已核对的内容 | 对本项目的意义 |
|---|---|---|
| RoboMIND 1.x | 最新 1.x 公开卡标称约 107K 轨迹、479 个任务，包含 Franka、UR、AgileX、TienKung；不同机器人相机布置不同 | AgileX 可作补充来源；不能把 Franka/UR 关节动作直接当 Piper 动作 |
| RoboMIND 2.0 | 官方标称约 310K 双臂轨迹、6 类机器人、超过 1000 小时；摘要为 739 个任务，正文表格为 759 | 当前优先版本；对任务数采用“700 余”口径，避免掩盖公开材料内部差异 |
| V2 其他部分 | 有约 12K 触觉轨迹、20K 移动操作轨迹，另有仿真部分 | 这些不应被当成独立新增规模重复相加；移动、触觉和全身数据不是当前第一轮的需要 |
| V2 AgileX 官方仓库 | 本次官方目录 API 返回 66 个任务文件夹 | 66 不是 66 个已验收单臂任务；需逐任务、逐场次筛选 |

来源：[S1]–[S6]。1.x 数据卡与论文中的实机/仿真构成和各平台计数并不完全一致，因此不把标称 107K 全部称作可直接训练的实机轨迹。2.0 总入口页面显示的局部仓库体积也不能当成所有子库的完整下载量。实际训练量和磁盘预算应按选定目录清单计算。

官方入口：

- [RoboMIND 1.x 项目页](https://x-humanoid-robomind.github.io/)
- [RoboMIND 1.x 数据卡](https://huggingface.co/datasets/x-humanoid-robomind/RoboMIND)
- [RoboMIND 2.0 项目页](https://log2r.github.io/RoboMIND2.0/)
- [RoboMIND 2.0 数据集合](https://modelscope.cn/collections/X-Humanoid/RoboMIND20)
- [本轮优先的 V2 AgileX 子库](https://modelscope.cn/datasets/X-Humanoid/RoboMIND2.0-Agilex)

发布卡提供 Apache-2.0 许可信息；实际落地时保留所用子库的版本、许可和来源文件。无需下载全部数据集，也不需要把原始轨迹传入 GitHub。

## 3. 已查到的具体任务

下表来自官方 ModelScope API 实际返回的中文描述与 episode 目录计数。详细 URL、revision、文件大小和读取边界见 [source_probe.json](../results/robomind-research/20261120/source_probe.json)；其中三个任务又按固定 revision 独立核对，见 [pinned_task_checks.json](../results/robomind-research/20261120/pinned_task_checks.json)。

| 官方任务目录 | 官方说明 | episode 目录数 | 建议 |
|---|---|---:|---|
| `place_milk_next_to_cup` | 拿起牛奶放在杯子旁边 | 360 | 首选筛选对象；检查执行手臂、夹爪、腕部可见范围与任务独立性 |
| `place_pomegranate_in_white_plate` | 石榴放进白色盘子 | 266 | 第二候选；核实具体机器人场次，再考虑单物体抓取放置 |
| `put_scissors_into_bucket` | 将剪刀放进桶中 | 264 | 可作数据研究候选；首次现场任务优先上面两个搬运任务 |
| `transfer_banana_from_pink_plate_to_green_bowl` | 左臂取香蕉，交到右臂，再由右臂放入绿碗 | 340 | 明确含双臂交接，不能直接删除一侧就称完整单臂示范 |

**这些数量不是已验收的可用轨迹数。** 当前未解码这些任务的完整控制数值和画面，没有证明前两个任务的每个 episode 都是同型号单臂独立操作。任务名称不含“双臂”也不构成独立性证据。另一臂即使动作很小，也可能承担托举、固定、递交等必要作用。

首轮建议只选一个通过核对的抓取放置任务。先尽量复现它的物体、容器、任务指令、起始姿态和腕部可见范围，再逐步扩展位置、背景、物体变化。这是为减少同时发生的域变化而提出的实验设计，不是对零示范成功率的承诺。

## 4. 实际文件查到了什么

本次已读取下列官方真实 HDF5 的有限前缀元数据：

```text
data/agilex/place_milk_next_to_cup/success_episodes/0611_144656/data/trajectory.hdf5
revision: b21612bdf4847b20fd2792be452e194c064db852
source size: 1,004,016,688 bytes
```

使用已有系统 HDF5 库解析成功取得的 1 MiB 文件前缀，没有安装新依赖，没有下载完整轨迹或图像载荷。另有未成功返回解析结果的受限读取尝试，方法和范围均保留在证据 JSON 中；未读取的字节没有被解释成零值或损坏数据。

实际 metadata 声明 `data_type=real`、`trajectory_length=2658`，语言任务为拿起牛奶并放到杯子旁边。目录名与 metadata 记录日期不同，不能根据目录名推断采集日期、机器人代次或频率。[S6]

| 实际字段 | 实际形状 | 能说明的内容 |
|---|---|---|
| `master/arm_left_position_align/data`、右侧对应项 | `[2658,6]` | 示教侧六列位置字段存在 |
| `puppet/arm_left_position_align/data`、右侧对应项 | `[2658,6]` | 执行侧六列位置字段存在 |
| `master/end_effector_left_position_align/data`、右侧及 puppet 对应项 | `[2658]` | 有独立的单列末端位置字段，候选夹爪通道需核实定义 |
| `*/end_effector_left_pose_align/data`、右侧对应项 | `[2658,7]` | 有末端位姿字段；其参考坐标和单位仍需核实 |
| `camera_observations/timestamp` | `[2658]`，int64 | 有时间字段，未取得其数值和时间单位 |

这些流还带 `timestamp` 和 `is_intervene`。在相机型号、分辨率等元数据组中，读到的子名称为 `camera_front / camera_left / camera_right`；本轮尚未核读 RGB 图像 dataset 的完整结构和载荷。**V2 适配不能直接硬编码 V1 的 `camera_left_wrist` 路径。** 官方平台描述支持腕部相机配置，但仍应通过每个样本的元数据与画面确认实际图像键及其视角。[S4][S6][S8]

已检查的 master/puppet 左臂关节、master 左末端位置及相机 timestamp 字段属性未提供单位说明。尚未证明：关节是否为 rad；夹爪是总开口、单指位移、角度还是归一化值；master 是否经过映射才成为 follower 目标；时间戳单位和真实频率；具体机器人是否与 Piper H 兼容。**“6＋1”结构接近，是可做适配的证据，不是可以原样发到硬件的证据。**

## 5. 与当前单腕配置的兼容性

### 5.1 本体与运动学

RoboMIND 官方 AgileX URDF 引用 `piper_slave_meshes`，包含左右六轴从臂，支持“Piper 家族候选”的判断。它不能证明所有 AgileX 数据都使用同一型号。[S7]

本机使用的官方 SDK 明确区分 Piper 和 Piper H。固定源码版本 `d90e234` 的 MDH 参数如下：[S9]

| 参数 | Piper | Piper H |
|---|---:|---:|
| 第 4 节 MDH 的 d | 0.25075 m | 0.25575 m |
| 第 6 节 MDH 的 d | 0.09100 m | 0.09630 m |
| J4 预置范围 | ±100° | ±135° |
| J5 预置范围 | ±70° | ±89.5° |

长度差分别为 5.00 mm、5.30 mm，末端差异随姿态变化，不能简单说成固定 10.3 mm 偏差。官方 URDF 与 SDK MDH 的坐标定义不同，也不能逐项比较局部参数就宣称全链等价。

即使确认源数据为普通 Piper，仍可研究直接关节迁移作为实验分支，但必须明确几何差异并核对关节零位、方向和允许范围。若差异造成抓取偏差，再评估重定向或少量目标域示范；不能用一个常数平移或 norm 代替完整映射。未核清型号的场次不混进首轮同一动作语义的数据集。

源工具的 `body_Link` 是双臂平台机身参考系，不等于本机 `base_link`。若读取源末端位姿或做重定向，需要正确拆出单臂基座与法兰关系；直接使用经过核对的关节监督时，也应记录使用的是哪一侧。另一侧数据可以映射到模型的逻辑 `left_wrist_0_rgb` 槽，但不能自动进行图像镜像或关节符号翻转。[S7]

### 5.2 单相机训练与视野

当前只保留一个真实腕部 DC1 输入。RoboMIND V2 的 AgileX 实验使用前视和左右腕相机，论文成功率不等于删去两路后的成功率。[S4][S5]

适配时从训练开始就只使用选定手臂对应的腕图；本项目唯一有效槽仍为 `left_wrist_0_rgb`，其余槽 `mask=False`。不得复制图像作为有效第二视角，也不能先训三相机模型、部署时才移除前视。

检查目标物体、抓取过程和放置区域是否能由这一腕部视角观察。若初始视野完全看不到物体或目的地，优先调整同一个相机的任务布置与起始姿态，并据此筛选公开轨迹。手眼矩阵不会补回没有拍到的信息。DC1 与公开相机的视场、安装角度、分辨率、曝光、背景差异需要作为迁移条件记录，不能靠“都是 RGB”假定相同。

### 5.3 动作标签

当前本机语义固定为：

```text
state  = q1..q6 measured [rad] + measured total gripper opening [m]
action = q1..q6 absolute target [rad] + absolute total gripper opening [m]
```

公开真实示范可以满足训练资格。首选能由采集协议、代码或元数据支持其含义的目标/示教流，并核对 master 到 follower 的映射、时延和干预标记。公共数据不必具有本机 CAN 逐帧发送日志；但必须诚实标注监督来自源数据的哪条流，不能把未证实的量叫作本机实际发送目标。

已核读的官方工具链 `convert_to_lerobot.py` 示例把同一行 `puppet_state[i]` 同时放入 `action` 和 `observation.state`，并使用顶视图、默认 30 fps 等配置。该示例只能参考格式，不是本项目的现成适配器；不能不加判断直接运行。它还包含删除已有输出目录的逻辑，落地时必须保留现有数据。[S8]

若某个子集只有执行侧状态而无可靠目标流，可以另行评估“未来实测状态作为监督”的路线，但这属于不同的标签定义，需明确时间偏移和训练/执行语义。不得把同帧 `q_t` 原样拷贝成“真实目标动作”，也不得通过改 metadata 让它伪装成已满足当前 reader 的绝对目标监督。

夹爪需特别核对：源 URDF 两指各自的 prismatic 关节坐标，不能直接证明单列 HDF5 值就是本机总开口。根据真实定义做转换并保留依据，不能仅看范围 0～1 就认定归一化，也不能默认乘 2 或除 1000。[S7][S9]

### 5.4 时间与 20 Hz 数据网格

本机 dataset reader 要求真实记录经明确处理落到 20 Hz 网格。公开数据应先读取源时间数值、单位、有效节奏以及 master/puppet/图像对齐关系，再做有记录的重采样。不能仅写 `fps=20` 就称为完成。

观测应避免引入目标时刻之后才可用的反馈；动作目标按源流定义进行保持或明确的转换，不能无依据用未来命令填补当前标签。动作 chunk 不跨 episode，末尾处理沿用已说明规则。若只获得可信名义频率，应标记 nominal 时间依据，不能伪装成曝光时间或实际发送时间；与当前 reader 不一致的部分应显式实现后再使用。[S11]

### 5.5 已知数据问题与分割

官方数据工具说明 V1 的特定 UR/仿真子集中存在 puppet 末端位姿近乎恒定的问题，并建议由正确关节与 URDF 重建。该问题不证明全部 RoboMIND 无效，也不能据此假定所选 AgileX 字段已验证正常。所选少量样本应实际检查图像通道、动作范围、时间连续性和夹爪闭合过程。[S7][S8]

按完整 episode 分割 train/validation；同一场次、同一物体布局的高度相邻轨迹尽量不跨 split。不要把同一条轨迹的相邻帧随机拆开后作为泛化成绩。π0 与 π0.5 使用同一公开筛选清单和公平评测任务，但各自按当前管线计算 norm，保留独立资产和 checkpoint。π0 保留连续状态/mean-std，π0.5 保留离散状态/quantile；不套用历史 B 双相机 norm。[S11]

## 6. 论文对 π 系列实际证明了什么

V2 论文明确从公开基础权重出发，用对应任务的 RoboMIND 示范进行微调。AgileX 实验采用 Cobot Magic V2.0 与三台 Orbbec Astra（前视、左右腕）。Table 2 的部分结果如下：[S5]

| AgileX 任务 | π0 | π0.5 |
|---|---:|---:|
| Task 1，双臂三明治操作 | 0.5 | 0.6 |
| Task 4，红按钮放入对应托盘 | 0.2 | 0.4 |
| Task 5，绿按钮放入对应托盘 | 0 | 0 |
| Task 6，玩具操作与收纳 | 0.2 | 0.3 |

它支持“RoboMIND 可以用于 π 系列适配训练”，也说明训练后不同任务仍有明显差异。它没有验证本机 Piper H、单 DC1、零本地演示这一组合。论文单任务模仿学习部分写了每任务 10 次测试；VLA 小节没有独立重申，因此不根据小数步长擅自给 π 表格附加试验次数。

V1 的公共数据预训练实验仍使用专家任务子集继续微调；其背景泛化实验则显示部分模型对背景变化敏感。这些是公开数据有效但迁移条件仍重要的旁证，不能转写成 π0.5 在本机的预测成功率。[S3]

本次检查 OpenPI 官方基础模型与专家模型入口，没有找到已验证匹配“Piper H＋单 DC1 腕相机＋7D 绝对关节动作”的 RoboMIND π 专家 checkpoint。`pi0_base` 与 `pi05_base` 可作微调起点；DROID/ALOHA 专家存在不同关节维度、相机条件和动作转换，不能靠截断维度直接替代。[S10]

## 7. “少采或不采”需要区分的内容

| 本机活动 | 是否可以争取省去 | 原因 |
|---|---|---|
| 大批量任务训练演示 | **可以先不采** | 先使用经过核实的公开真实示范 |
| 计算首轮训练 norm 所需的本地演示 | **可以省去** | norm 可只来自公共训练 split |
| 手眼、几何与连续控制接口验证 | 按现有计划完成 | 它们验证本机部署条件，公共示范不能替代 |
| 实机任务评测和结果记录 | 需要 | 这是判断迁移是否成功的证据 |
| 有针对性的少量本地补采 | 先不预定为必需 | 根据失败是否属于视觉/任务域差异决定 |

“零本地任务示范”允许使用已有只读观测检查数据接口和输出，但若将本地任务轨迹、纠正片段或奖励反馈用于训练，应准确改称有本地数据适配。若在本地评测上反复挑 checkpoint、提示词或超参数，也要报告这些适配决策，并保留新的最终评测布局。

当前 5,382 帧仍是 `observation_only`、`training_eligible=false`，不会因为有公共数据而变成任务演示。已经完成的 180 秒实录与三 CAN 报文跨度审计继续沿用，不重新采集或重跑。[S11]

## 8. 建议执行顺序

### A. 现在推进：公开数据与模型准备

1. 在既有环境检查两个首选任务的少量实际 episode，核实来源、机器人、活动手臂、腕图、数值、命令流和时间定义，输出紧凑证据与不确定项。
2. 先选择一个完整可独立执行的任务，只保留对应腕图和同侧 7D 状态/动作。若一个候选不合格，转到另一个；不通过编造默认单位或重命名标签让它过关。
3. 生成可追溯的公开单腕训练集清单、明确的 20 Hz 对齐报告和 episode split；实际数据留已预留的训练机数据目录，GitHub 只收代码、清单和代表样本。
4. 分别为 π0、π0.5 准备本任务 norm 与正式全参配置。保留独立基础权重、状态处理和输出目录；不能因为单卡资源紧张自动改成 LoRA，也不自动同时启动两个全参训练。
5. 数据资格和现有资源落实后进入正式训练。无需等待手眼，但本研究回合没有执行这一步，也没有保证周日之前能训练完成。

### B. 周日 2026-11-22：现场标定与执行链

继续现有 [标定接续文档](PI_SINGLE_CAMERA_BOARD_HANDOFF_20261122.md)：板型和实物尺寸核实、received 图像链记录、内参/手眼独立组验证、安装绑定、空间一致性检查。随后由 H0 唯一发送端完成计划内连续目标跟踪与停止验证；本研究不创建新发送端，不修改 dog-and-arm。

最终 DDS 配置下的动作和多姿态零位/方向核实仍应以现场结果为准。标定输出不补造，设备内部校正未知时保留 null。相机、标定与底层控制验证可以同公开数据适配并行。

### C. 两条线汇合：零本地演示试验

先用已经适配的 checkpoint 对真实本机观测做只读推理，保存输出与时序。确认唯一发送端、动作映射、当前状态到首个目标的衔接后，再进入与训练任务相近的现场任务评测。

建议预先固定少量布局，分别记录抓取、搬运、放置、完整成功、人工介入、推理延迟和中止原因。首轮每模型 10 次可以作为探索预算，样本量很小，报告原始成功次数与布局，不称为可靠泛化上限；并采用相同复位条件和任务指令比较两模型。这是项目建议，不是论文给定门槛。

失败后先分类：

- 单位、方向、时序、动作衔接错误：修复适配/控制，不能靠加演示掩盖。
- 目标不可见或场景布置脱离训练条件：调整单相机起始姿态、任务布局和公开数据筛选。
- 物体、背景、夹爪接触等目标域差异：再考虑少量本地示范或纠正，集中覆盖失败情况。
- 需要另一臂支撑或交接：更换首轮任务，不把双臂依赖留给模型猜。

如需补采，可按“0 条先测 → 首批约 10 条针对性示范 → 仍有明确收益再增加到约 30 条”的预算阶梯推进。10/30 不是已验证最低数量，也不是成功保证；完成一档就评估失败是否减少。不要直接跳到大规模重复采集。

## 9. 本轮完成与尚未完成

**已完成：**官方论文/项目/数据卡交叉阅读；实际 AgileX 目录及任务说明查询；一个真实 HDF5 的有限元数据读取；官方转换器与 URDF 静态核对；Piper/Piper H SDK 参数核对；本方案及下一轮提示词。

**尚未完成：**完整样本图像/控制数值解码；具体场次机器人与动作单位证明；单臂独立性验收；可训练数据转换；公共训练 norm；模型微调与推理；本机任务测试。本轮没有新增硬件动作或训练作业，不能把研究结论记成现场通过。

下一轮直接使用：[RoboMIND 单腕公开数据适配提示词](ROBOMIND_SINGLE_WRIST_NEXT_PROMPT_20261120.md)。它与周日标定提示词分别处理数据侧和现场侧，二者都保持当前一台腕部相机的配置。

## 10. 一手来源

- **[S1]** [RoboMIND 1.x 官方项目](https://x-humanoid-robomind.github.io/)
- **[S2]** [RoboMIND 1.x 官方数据卡](https://huggingface.co/datasets/x-humanoid-robomind/RoboMIND)
- **[S3]** [RoboMIND 1.x 论文 v3](https://arxiv.org/html/2412.13877v3)，预训练/任务微调与背景实验。
- **[S4]** [RoboMIND 2.0 官方项目](https://log2r.github.io/RoboMIND2.0/)，规模、平台、相机与发布入口。
- **[S5]** [RoboMIND 2.0 论文 v3](https://arxiv.org/html/2512.24653v3)，§6.1.2、§6.1.4、Table 2；摘要/正文任务口径差异。
- **[S6]** [V2 AgileX 官方库](https://modelscope.cn/datasets/X-Humanoid/RoboMIND2.0-Agilex)，具体 API 与 revision 见本报告所附两份证据 JSON。
- **[S7]** [官方 dataset-utils @77d7b31](https://github.com/Open-X-Humanoid/RoboMIND-dataset-utils/tree/77d7b311cbf2f16624c941f46b2a75042858ff06)、[AgileX URDF](https://github.com/Open-X-Humanoid/RoboMIND-dataset-utils/blob/77d7b311cbf2f16624c941f46b2a75042858ff06/eepose/urdf/agilex/aloha_new.urdf)。
- **[S8]** [官方 V1 schema](https://github.com/Open-X-Humanoid/x-humanoid-training-toolchain/blob/a93473fccc2aff630d501f36f39daa22b0a368ab/scripts/configs/all_robot_h5_info_v1.2.md)、[官方转换示例](https://github.com/Open-X-Humanoid/x-humanoid-training-toolchain/blob/a93473fccc2aff630d501f36f39daa22b0a368ab/scripts/convert_to_lerobot.py)。
- **[S9]** [AgileX 官方 SDK constants.py @d90e234](https://github.com/agilexrobotics/pyAgxArm/blob/d90e234ba8e408cfa964b38aa9120b3131fc9f85/pyAgxArm/api/constants.py)、[MDH 实现](https://github.com/agilexrobotics/pyAgxArm/blob/d90e234ba8e408cfa964b38aa9120b3131fc9f85/pyAgxArm/utiles/mdh_kinematics.py)、[官方夹爪接口](https://github.com/agilexrobotics/pyAgxArm/blob/d90e234ba8e408cfa964b38aa9120b3131fc9f85/pyAgxArm/protocols/can_protocol/drivers/effector/agx_gripper/default/driver.py)。
- **[S10]** [OpenPI 官方 README @215abfb](https://github.com/Physical-Intelligence/openpi/blob/215abfb217dbac7d5f1273282331b9b1866c0479/README.md)、同版本 policies 中的 ALOHA/DROID 输入输出映射。
- **[S11]** [本项目状态](PI_REAL_TEST_STATE.md)、[本项目单相机 reader](../tasks/piper_real_single_v1/dataset.py)、[现场报告](../results/piper-real-single-v1/20261120_194402/report_zh.md)、[已完成三报文审计](../results/piper-real-single-v1/20261120_194402/joint_packet_review_zh.md)。
