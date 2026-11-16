# π0 / π0.5：Piper H 适配与实机测试

## 当前入口：π 实机 R0（2026-11-16）

**H500 与 I500 已完成，正式仿真模型仍为 π0 B。当前转入 Piper H 真实观测、现场可视化和只读推理，随后衔接真实执行、示范采集与实机适配。**

- [完整实机计划](docs/PI_REAL_TEST_PLAN_20261116.md)
- [下一轮 Codex 执行提示词](docs/PI_REAL_TEST_NEXT_PROMPT_20261116.md)
- [实机当前状态](docs/PI_REAL_TEST_STATE.md)
- [执行约定](AGENTS.md)、[发布与人工备份规则](docs/RESEARCH_PUBLISH_POLICY.md)

本次提交发布计划和入口，尚未执行 π 实机 R0。上游 H0 已完成设备采集与小幅动作联调；这不等于 π 自主实机任务已经完成。

## 下一步怎样推进

| 阶段 | 主要产物 | 当前状态 |
|---|---|---|
| R0 真实观测与只读推理 | 真实 RGB/7D 状态、现场显示、B 动作预测、实际时序 | 本轮下一任务 |
| R1 真实执行接口 | 连续目标跟踪、动作块衔接、实际发送与反馈 | 接 R0 证据推进 |
| 标定支线 | RGB 参数核对、内参、手眼及独立姿态验证 | 板在购买；不阻塞 R0 |
| R2 真实示范与适配 | 少量完整先导示范、数据划分、一次明确 π0 适配 | 尚未开始 |
| R3 自主实机 | 固定任务到保留布局的真实成功率和失败证据 | 尚未开始 |
| R4 π0.5 对照 | 相同真实输入、数据与执行口径下比较 | π0 链路稳定后 |

B 的输入需要外部与腕部两个真实 RGB 视角。H0 已确认腕部 DC1，外部相机现场状态待核实。缺第二相机时继续采集/显示/接口工作，但不以复制腕图、黑图冒充完整 B 输入。

当前动作空间为六关节位置与夹爪总开口。手眼服务于空间一致性与几何诊断；只读推理和纯关节执行接口不要求先把手眼矩阵放入策略。

本项目只负责 π 系列实际测试。dog-and-arm 的 [H0 报告](https://github.com/kaiwen123-yang/dog-and-arm/blob/284c1f3f1bb9d5096003433f6153a9c5e95d6189/reports/H0_HARDWARE_REPORT.md)作为上游证据，不在这里接管其 P0–P3、M1、门场景或底盘开发。

## 代码来源与模型来源

最新已确认运行分支为 codex/pi0-i500-rotation-20261104，提交 77c102769411e1d7fa02e98dc830cdad7bb78388；执行时保留现场真实后续改动。main 维护当前文档，不以其旧代码覆盖活动工作区。

**运行代码采用 I 分支，模型采用 B；两者不是同一个选择。** B 历史权重与原 norm 精确路径见实机计划，部署前核实实际存在位置；旧 D57 LoRA1499 不是 B。现有 deployment_io.py 仅返回动作提案，不是已完成的 CAN 执行器。

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
