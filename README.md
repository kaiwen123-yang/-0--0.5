# π0 / π0.5：Piper H 单相机实机准备

## 当前入口（2026-11-20）

**只使用一台现有相机，先完成标定前可做的工作；标定板预计北京时间 2026-11-22 周日到达。π0 与 π0.5 两套全参接口和配置同步准备，遥操作/示教方案暂不讨论。**

本轮用户称“外部摄像头”，历史记录为腕部 DC1。按最新外部相机意图准备，现场记录实际安装后显式选择 external_fixed 或 wrist；不因旧ROS话题名自动推断安装。

- [标定前计划与到货后顺序](docs/PI_SINGLE_CAMERA_PRECALIB_PLAN_20261120.md)
- [现在交给 Codex 的完整提示词](docs/PI_SINGLE_CAMERA_PRECALIB_PROMPT_20261120.md)
- [实机当前状态](docs/PI_REAL_TEST_STATE.md)
- [新增代码与准确用法](tasks/piper_real_single_v1/README.md)
- [DC1 畸变差异源码核对](docs/DC1_DISTORTION_SOURCE_NOTE_20261120.md)
- [执行约定](AGENTS.md)

## 本轮准备的能力

| 部分 | 已新增内容 | 现场状态 |
|---|---|---|
| 单相机数据接口 | camera_rgb、实测7D状态、明确唯一有效图像槽 | 待新会话接入 |
| 两模型全参入口 | π0连续state/mean-std，π0.5离散state/quantile；均非LoRA | 未训练 |
| 真实数据格式 | 实际动作标签、episode划分、名义20Hz时间契约 | 无本轮新示范 |
| 记录与显示 | 复用H0接收器，显示真实RGB及已落盘反馈年龄 | viewer现场未运行 |
| 关联与单帧导出 | 先行实测反馈关联、原始图像导出，不造action | 有历史H0离线分析，见本轮报告 |
| 标定工具 | 棋盘检测、内参、两种安装手眼及独立姿态报告 | 板未到，未拟合 |

本轮代码与源格式已核对，并使用有限真实历史H0数据开展离线关联；这不是本轮现场采集、标定或模型运行。实际证据与缺项见 [准备报告](results/piper-real-single-v1/20261120_preparation/report_zh.md)。

新增 tasks/piper_real_single_v1/ 独立于旧 piper_color_v1，只使用对应既有 OpenPI 环境。现场 I 工作区保留原代码和未提交修改，按新提示词选择性引入新增路径/当前文档，不用 main 的旧仿真代码覆盖它。

## 当前路线的边界

- 不等待第二台相机。无效模型图像槽 mask=False，零占位不冒充真实图像。
- B 累计4020仍是历史双相机仿真基线，不是已经适配单相机的真实策略。
- 标定前可完成采集、时序、接口、配置和工具；到货后补真实内参/手眼采集与验证，再接空间一致性和连续动作联调。
- 两模型都做全参的目标保留；96GB同卡同时启动两路全参尚无充分资源证据，不默认双开或改LoRA。
- 没有实际动作标签的只读记录不可当示范；标定成功不等于训练数据已经齐备。
- 本项目只负责π实机；dog-and-arm@284c1f3的H0作为上游事实，不接管其P0–P3/M1/门/底盘任务。

11-16 双相机R0计划/提示词已作为历史保留，由当前单相机入口替代。

## 已完成仿真结果

| 对象 | 原 48 开发 | 原 75 验证 | 结论 |
|---|---:|---:|---|
| B 累计 4020 | 25/48 | 72/75 | 正式基线；历史训练 211/240、旧独立测试 53/60 |
| E500 原数据续训 | 34/48 | 67/75 | 已完成 |
| F500 早期纠偏 | 30/48 | 65/75 | 已完成 |
| G500 固定视觉更新 | 29/48 | 64/75 | 已完成 |
| H500 持物恢复混合 | 37/48 | 65/75 | 未替代 B |
| I500 教师姿态衔接修正 | 39/48 | 69/75 | 未达到保留条件；B 继续正式 |

I 的两个补充来源为 1/2，八个恢复来源为 4/8；H 对应为 2/2、5/8。教师成功不计作自主成绩。验证已多轮参与选择，不称新独立泛化，不将这些数字当作真实机器人成功率。

- [I 最终报告](https://github.com/kaiwen123-yang/-0--0.5/blob/77c102769411e1d7fa02e98dc830cdad7bb78388/results/piper-color-v1/pi0-i500-rotation-20261104/final_report_zh.md)、[I 候选决定](https://github.com/kaiwen123-yang/-0--0.5/blob/77c102769411e1d7fa02e98dc830cdad7bb78388/results/piper-color-v1/pi0-i500-rotation-20261104/candidate_decision.json)
- [H 最终报告](https://github.com/kaiwen123-yang/-0--0.5/blob/3dd547a169c7a821fabd278af3b86a1f3d099b95/results/piper-color-v1/pi0-h500-recovery-20261103/final_report_zh.md)
- [H 后审查与当时计划（历史）](docs/PI0_H500_REVIEW_NEXT_PLAN_20261104.md)、[H 原计划（已完成）](docs/PI0_H500_PLAN_20261103.md)
- [G 审查](docs/PI0_G_COMPLETED_NEXT_REVIEW_20261103.md)、[E/F 审查](docs/PI0_REPRO_REVIEW_NEXT_PLAN_20261103.md)、[八条恢复报告](https://github.com/kaiwen123-yang/-0--0.5/blob/3dd547a169c7a821fabd278af3b86a1f3d099b95/results/piper-color-v1/pi0-held-recovery-20261103/final_report_zh.md)

H/I 和恢复数据旧启动提示词已完成，不再自动续训、扩评或重跑。详细历史数值及其当时解释保留在原报告与 Git 历史。

## 发布与保留

代码、实际配置、紧凑日志、代表证据与结论推 GitHub；大检查点、optimizer、原始数组、完整录像保留原机器供用户备份。小文件已推不代表全量二进制备份。不新增归档、重复压缩或大文件队列，不自动删除资料、不停止活动任务。

复用既有 ROS/SDK/JAX/OpenPI 环境；不改共享环境或其他项目。具体约束见 AGENTS.md。

## 复现范围与历史索引

当前是公开预训练 π0 的 Piper 颜色任务适配与闭环仿真，开始推进真实部署；尚未完成论文规模预训练、完整基准或自主实机复现。π0.5 自定义任务尚未形成同等稳定结果。

| 历史工作 | π0 | π0.5 | 口径 |
|---|---:|---:|---|
| LIBERO/Panda pilot | 183/200 | 196/200 | 每任务 5 初态 |
| Piper 迁移仿真 | 32/75 | 47/75 | 不同机器人与适配条件 |
| 旧颜色入盒 | — | 1500 更新后 0/15；D57 复评 3/15、0/15 | 历史失败保留 |

[D57 历史部署](docs/AUTODL_D57.md)；
[历史路径](deployment/d57/paths.json)；
[原项目说明](docs/PROJECT_README.md)；
[上游来源](publication/upstream-provenance.json)；
[总索引](ARTIFACT_INDEX.json)；
[历史 Release](https://github.com/kaiwen123-yang/-0--0.5/releases/tag/pi-complete-backup-20261101)。

旧 LoRA1499 缺 optimizer、旧全参1000不完整，均不能替代 B 完整状态。历史上传/清理记录保留原义，不作为本轮自动执行指令。

