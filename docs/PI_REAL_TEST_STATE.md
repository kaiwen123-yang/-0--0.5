# π 实机当前状态

更新于北京时间 2026-11-21。**腕部 DC1 已完成本轮棋盘实采与候选拟合。机械臂在 u11 过渡姿态触发阻尼急停，可能触桌；回零和复采待现场恢复。** [本轮现场报告](../results/piper-real-single-v1/20261121_q12_01/report_zh.md) · [接续提示词](../results/piper-real-single-v1/20261121_q12_01/next_prompt.md)

| 范围 | 状态与证据 |
|---|---|
| 代码准备 | 已选择性引入准备提交的单相机接口与两套全参配置。新增每姿态只读采集、实测法兰位姿对照、按姿态分组的 manifest 与方向复核表。[模块入口](../tasks/piper_real_single_v1/README.md) |
| 历史离线处理 | 旧 H0 摘录分析及单帧导出保留，不计入本轮统计。[历史准备报告](../results/piper-real-single-v1/20261120_preparation/report_zh.md) |
| 本轮现场 | SN CC16762023M，wrist，唯一真实槽 left_wrist_0_rgb。19:44:50 开始；5,382 个 RGB 事件、5,382 张连续原图、5,382 条完整实测 7D 状态，0 条动作标签。原始数据留在本机，绝对路径见配置。[会话](../results/piper-real-single-v1/20261120_194402/session.json) |
| 数据时间口径 | 同机同 boot 单调接收时间，分别选过去最近关节和夹爪反馈，上限 100 ms；实测年龄 P95 为 4.807/4.838 ms。180 秒现场 viewer 显示的反馈年龄另含 CSV 写盘与显示调度。[关联报告](../results/piper-real-single-v1/20261120_194402/association_report.json) |
| 位姿/FK | 本轮 41 个真实姿态，实测 J1–J6 的 Piper H SDK FK 与控制器法兰最大差 0.0051 mm / 0.0029°。当前物理安装的空间复核见本轮报告。 |
| 标定 | 27 个合格 train，4 个合格 heldout，另有 1 个遮边预留姿态仅作诊断。训练集候选 K/D 和 Park 已求。四个 heldout 平均 0.134 px、1.895 mm、0.361°。外缘边长偏差最大 8.4 mm，未达到正式独立组数量，待复核。 [矩阵和误差](../results/piper-real-single-v1/20261121_q12_01/candidate_result.json) |
| 三报文离线审计 | 已运行。37,993 行的最大跨度为 0.4976 ms；5,382 张 RGB 引用的 5,382 个不同关节行最大 0.4640 ms（图像索引 3371）。5 ms 筛查标记 0 行，原完整观测仍为 5,382，接口 rx_dropped +54 的 ID 未知。[离线审计与发送端接入点](../results/piper-real-single-v1/20261120_194402/joint_packet_review_zh.md) |
| 发送端与接收图像域 | 已实测 H0 单一发送端的逐帧提交并与独立接收器核对，u11 超时后进入阻尼急停。CC16762023M、received、640×480 和 ROS rgb8 已核实；设备内部校正留 null。 [事件](../results/piper-real-single-v1/20261121_q12_01/stop_event.json) · [实配](../results/piper-real-single-v1/20261121_q12_01/calibration_spec.json) |
| 模型 | D57 实际环境、独立基础权重、数据和输出路径已核对，两份腕部全参配置与入口已就位。真实示范和新 norm 未就绪，训练、推理、容量试跑均 NOT_RUN，动作发送 0。单卡双全参无实测依据。[云端现场记录](../results/piper-real-single-v1/20261120_194402/autodl.json) |

H0 的历史接入、H500、I500 和八条恢复采集均已完成。B 累计 4020 保留为旧双相机仿真基线；仿真验证 72/75，验证集曾反复参与选择。旧双相机提示词已停用。两模型后续从有实际动作标签的真实训练 split 计算独立 norm。[标定前计划](PI_SINGLE_CAMERA_PRECALIB_PLAN_20261120.md) · [11 月 20 日已执行提示词](PI_SINGLE_CAMERA_PRECALIB_PROMPT_20261120.md)

