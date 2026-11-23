# 2026-11-23：标定后准备与 RoboMIND 实样核查

项目来源：`kaiwen123-yang/-0--0.5@72ad763699502defed9d39d51bd22a56ea2ce2e8`。日期采用北京时间。本目录是本次只读研究的紧凑证据，不是模型训练数据。

## 结论与当前入口

11/22 新标定可继续供任务采集使用。RoboMIND 有值得保留的单臂子任务；本轮尚未确认一批能直接按本机 Piper H＋DC1 单腕契约使用的完整训练数据。根据用户“公开数据不直接适用就本地采”的选择，下一轮主线是本机任务示范。

[数据决策](../../../docs/ROBOMIND_DECISION_20261123.md) · [本地操作指南](../../../docs/PI_LOCAL_DEMONSTRATION_GUIDE_20261123.md) · [Codex 执行提示词](../../../docs/PI_POST_CALIBRATION_NEXT_PROMPT_20261123.md) · [详细每日记录](../../../docs/PI_DAILY_WORK_LOG.md)。

## 项目与方法核查

| 文件 | 内容 |
|---|---|
| [calibration_review.json](calibration_review.json) | 35/7/9 分组、冻结时间与最终采样顺序、K/D/X、网格和独立误差；与旧标定区分。 |
| [control_review.json](control_review.json) | H0 静态超时修复的真实边界、当前采集/推理接口、发送日志缺口。 |
| [data_review.json](data_review.json) | 原五条 RoboMIND 记录、观测数据性质、真实 dataset / transform / train / infer 代码契约。 |
| [robomind_deep_review.json](robomind_deep_review.json) | 官方字段、处理版转换、源批次与候选段，明确时间近似不是训练禁令。 |
| [local_demonstration_review.json](local_demonstration_review.json) | Piper H 手册、厂家轨迹录放示例与本机 pyAgxArm 固定版；人工路径来源和实际重放 action 的区分。 |
| [utensils_stream_comparison.json](utensils_stream_comparison.json) | 餐具右臂 master / puppet 数值相关和滞后，仅作描述，不拟合本机零位或控制补偿。 |
| [oneworld_first_raw_metadata.json](oneworld_first_raw_metadata.json) | 实际范围读取的处理版 episode 元数据：源索引、估计频率、夹爪比例、双臂指令。 |

本目录报告的 `scope` 指各审查阶段的动作范围。审查未运行用户硬件、训练或策略推理。公开源 HDF5 的读取使用隔离 scratch 中的 h5py 依赖，不改变本机、共享 SDK 或 D57 环境。日志中提到的本机绝对路径是既有证据来源，不代表此次访问了用户电脑。

## 三条新增原始轨迹的实际检查

[视觉总审查](robomind_visual/robomind_visual_review.json) · [精确提取计数](robomind_visual/extraction_summary.json)。

| 官方任务 / episode | 原始数值行 | 成功解码源 JPEG | 关键发现 |
|---|---:|---:|---|
| 电路板 / 0623_131736 | 2,984 | 23 | 左持板→右接板→右放托盘，整段依赖双臂。 |
| 餐具 / 0617_144408 | 2,883 | 22 | 左腕图证明左臂搬白盘，但对应左侧数值全零；右侧餐具段可保留。 |
| 笔剪刀 / 0415_102035 | 2,947 | 21 | 左臂先放笔、右臂后放剪刀，左笔阶段是较好的单臂候选。 |

66 张原始 JPEG 已实际解码，另生成九张汇总图；本次提交包含九张汇总图和七张关键原始 JPEG。汇总图只作缩放排列并标注真实源行号，没有生成或改写场景内容。各 episode 的 `manifest.json` 记录检查过的全部帧及来源，**清单中其余 JPEG 和原生 NPZ 未全部提交**。需要完整再取时按固定 revision/path/行号读取，不能把这些稀疏抽帧当完整训练视频。

已验证保留的唯一源字节范围共 **10,326,467 bytes（约 9.848 MiB）**。这是缓存中完整通过 `206 / Content-Range / 长度` 检查的唯一范围，不是累计网络流量；未计中断、重试或重复传输。官网六个 AGX GIF 另作背景浏览，未绑定这三条 episode，不用于最终证明，也未提交。

### 电路板

[manifest](robomind_visual/place_circuit_board_on_tray/0623_131736/manifest.json) · [源 group attrs](robomind_visual/place_circuit_board_on_tray/0623_131736/group_attrs.json) · [前视](robomind_visual/place_circuit_board_on_tray/0623_131736/front_contact.jpg) · [左腕](robomind_visual/place_circuit_board_on_tray/0623_131736/left_contact.jpg) · [右腕](robomind_visual/place_circuit_board_on_tray/0623_131736/right_contact.jpg)。

### 餐具

[manifest](robomind_visual/place_utensils_into_plate/0617_144408/manifest.json) · [源 group attrs](robomind_visual/place_utensils_into_plate/0617_144408/group_attrs.json) · [前视](robomind_visual/place_utensils_into_plate/0617_144408/front_contact.jpg) · [左腕](robomind_visual/place_utensils_into_plate/0617_144408/left_contact.jpg) · [右腕](robomind_visual/place_utensils_into_plate/0617_144408/right_contact.jpg)。

前视最初产生过“似乎单臂完成”的暂判，左腕图片随后提供直接反证，本次最终报告已更正并保留该更正记录。

### 笔与剪刀

[manifest](robomind_visual/put_pen_and_scissors_into_bin/0415_102035/manifest.json) · [源 group attrs](robomind_visual/put_pen_and_scissors_into_bin/0415_102035/group_attrs.json) · [前视](robomind_visual/put_pen_and_scissors_into_bin/0415_102035/front_contact.jpg) · [左腕](robomind_visual/put_pen_and_scissors_into_bin/0415_102035/left_contact.jpg) · [右腕](robomind_visual/put_pen_and_scissors_into_bin/0415_102035/right_contact.jpg)。

## 证据适用范围

原始源数据为 `X-Humanoid/RoboMIND2.0-Agilex`；每条 manifest 固定 dataset revision、HDF5 路径和大小。公开处理版 OneWorld 的观察只适用于所读取的一条元数据及其公开 reader / model 说明；axiboai 仅参考公开卡，未访问受限文件。原生数值不宣称已换算成本机目标。所有检查提取保持 `training_eligible=false`。

型谱/零位/夹爪映射、完整子段边界和单腕可观测性仍未完成。数值滞后、整数时间戳和坏 EEF 字段并非自动拒绝所有模仿学习的理由。后续若使用公共源，需明确适配方案与近似、按父 episode 分组，禁止让 chunk 跨任务切片边界。
