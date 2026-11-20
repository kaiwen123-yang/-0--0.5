# π 实机当前状态

更新于北京时间 2026-11-20。**唯一 DC1 经现场照片确认装在腕端，已完成 180 秒只读实录、现场显示、真实时间关联和单帧导出。** 周日预计到板后直接采集标定姿态。[现场报告](../results/piper-real-single-v1/20261120_194402/report_zh.md) · [11 月 22 日接续提示词与命令](PI_SINGLE_CAMERA_BOARD_HANDOFF_20261122.md)

| 范围 | 状态与证据 |
|---|---|
| 代码准备 | 已选择性引入准备提交的单相机接口与两套全参配置。新增每姿态只读采集、实测法兰位姿对照、按姿态分组的 manifest 与方向复核表。[模块入口](../tasks/piper_real_single_v1/README.md) |
| 历史离线处理 | 旧 H0 摘录分析及单帧导出保留，不计入本轮统计。[历史准备报告](../results/piper-real-single-v1/20261120_preparation/report_zh.md) |
| 本轮现场 | SN CC16762023M，wrist，唯一真实槽 left_wrist_0_rgb。19:44:50 开始；5,382 个 RGB 事件、5,382 张连续原图、5,382 条完整实测 7D 状态，0 条动作标签。原始数据留在本机，绝对路径见配置。[会话](../results/piper-real-single-v1/20261120_194402/session.json) |
| 数据时间口径 | 同机同 boot 单调接收时间，分别选过去最近关节和夹爪反馈，上限 100 ms；实测年龄 P95 为 4.807/4.838 ms。180 秒现场 viewer 显示的反馈年龄另含 CSV 写盘与显示调度。[关联报告](../results/piper-real-single-v1/20261120_194402/association_report.json) |
| 位姿/FK | 用实测 J1–J6 与 Piper H SDK MDH 得到 base_link←flange_link，单姿态与控制器法兰相差 0.00545 mm / 0.000506°。六轴物理零位/符号和多姿态一致性待核实。 |
| 标定 | NOT_RUN，当前无板、无外参。11 月 22 日核实板型、几何、图像域和刚性固定；独立组验证内参和腕部手眼。RGB 工厂 D 与服务 r_k 差异已现场复核；深度未配准。 |
| 模型 | D57 实际环境、独立基础权重、数据和输出路径已核对，两份腕部全参配置与入口已就位。真实示范和新 norm 未就绪，训练、推理、容量试跑均 NOT_RUN，动作发送 0。单卡双全参无实测依据。[云端现场记录](../results/piper-real-single-v1/20261120_194402/autodl.json) |

H0 的历史接入、H500、I500 和八条恢复采集均已完成。B 累计 4020 保留为旧双相机仿真基线；仿真验证 72/75，验证集曾反复参与选择。旧双相机提示词已停用。两模型后续从有实际动作标签的真实训练 split 计算独立 norm。[标定前计划](PI_SINGLE_CAMERA_PRECALIB_PLAN_20261120.md) · [11 月 20 日已执行提示词](PI_SINGLE_CAMERA_PRECALIB_PROMPT_20261120.md)
