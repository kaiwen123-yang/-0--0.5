# π 实机当前状态

更新于北京时间 2026-11-21。**唯一 DC1 经现场照片确认装在腕端，已完成 180 秒只读实录、现场显示、真实时间关联和单帧导出。用户确认 Q12-290-20 铝基棋盘板已到，可以开始现场参数核实与标定采集。** [现场报告](../results/piper-real-single-v1/20261120_194402/report_zh.md) · [已到货板型的流程与执行提示词](PI_Q12_BOARD_CALIBRATION_20261121.md)

| 范围 | 状态与证据 |
|---|---|
| 代码准备 | 已选择性引入准备提交的单相机接口与两套全参配置。新增每姿态只读采集、实测法兰位姿对照、按姿态分组的 manifest 与方向复核表。[模块入口](../tasks/piper_real_single_v1/README.md) |
| 历史离线处理 | 旧 H0 摘录分析及单帧导出保留，不计入本轮统计。[历史准备报告](../results/piper-real-single-v1/20261120_preparation/report_zh.md) |
| 本轮现场 | SN CC16762023M，wrist，唯一真实槽 left_wrist_0_rgb。19:44:50 开始；5,382 个 RGB 事件、5,382 张连续原图、5,382 条完整实测 7D 状态，0 条动作标签。原始数据留在本机，绝对路径见配置。[会话](../results/piper-real-single-v1/20261120_194402/session.json) |
| 数据时间口径 | 同机同 boot 单调接收时间，分别选过去最近关节和夹爪反馈，上限 100 ms；实测年龄 P95 为 4.807/4.838 ms。180 秒现场 viewer 显示的反馈年龄另含 CSV 写盘与显示调度。[关联报告](../results/piper-real-single-v1/20261120_194402/association_report.json) |
| 位姿/FK | 用实测 J1–J6 与 Piper H SDK MDH 得到 base_link←flange_link，单姿态与控制器法兰相差 0.00545 mm / 0.000506°。六轴物理零位/符号和多姿态一致性待核实。 |
| 标定 | 板已到（用户 11 月 21 日确认），采集/解算仍 NOT_RUN，无外参。厂家型号表确认 Q12-290-20 名义 12×9 方格、20 mm 格长；配置 11×8 内角点、0.020 m。已准备[本型号模板](../tasks/piper_real_single_v1/calibration_spec.q12_290_20.example.json)，实物、图像链、今日安装与多姿态来源仍待现场核实。先内参再腕部手眼，保留独立姿态验证。RGB 工厂 D 与服务 r_k 差异保留；深度未配准。 |
| 三报文离线审计 | 已运行。37,993 行的最大跨度为 0.4976 ms；5,382 张 RGB 引用的 5,382 个不同关节行最大 0.4640 ms（图像索引 3371）。5 ms 筛查标记 0 行，原完整观测仍为 5,382，接口 rx_dropped +54 的 ID 未知。[离线审计与发送端接入点](../results/piper-real-single-v1/20261120_194402/joint_packet_review_zh.md) |
| 发送端与周日配置 | H0 的命令 CSV 记录高层调用返回后的入参，TX CSV 记录底层调用前的尝试。后续在同一发送端补底层逐帧提交结果并关联独立反馈。周日副本预选 received，有效 K/残余 D 等待板图；图像链核实标志为 false，设备内部校正为 null。[周日配置](../results/piper-real-single-v1/20261120_194402/calibration_spec_20261122_prepared.json) |
| 模型 | D57 实际环境、独立基础权重、数据和输出路径已核对，两份腕部全参配置与入口已就位。真实示范和新 norm 未就绪，训练、推理、容量试跑均 NOT_RUN，动作发送 0。单卡双全参无实测依据。[云端现场记录](../results/piper-real-single-v1/20261120_194402/autodl.json) |
| RoboMIND 公开示范调研 | 已读取官方论文、发布目录、候选任务说明及一个真实 HDF5 的有限元数据；发现六关节和独立末端位置流。优先检查 V2 AgileX 牛奶搬运/石榴入盘候选，尝试公开数据训练后的零本地任务示范测试。机器人版本、单位、单臂独立性、时序仍未验收；完整转换、norm、训练均 NOT_RUN。[调研报告](ROBOMIND_FOR_PI_SINGLE_WRIST_20261120.md) · [数据侧下一步提示词](ROBOMIND_SINGLE_WRIST_NEXT_PROMPT_20261120.md) |

H0 的历史接入、H500、I500 和八条恢复采集均已完成。B 累计 4020 保留为旧双相机仿真基线；仿真验证 72/75，验证集曾反复参与选择。旧双相机提示词已停用。两模型后续从有可信动作监督、已完成语义适配的真实训练 split 计算独立 norm；训练示范可以来自公共数据，不要求全部本地自采。现有静止观测保持 observation_only。[标定前计划](PI_SINGLE_CAMERA_PRECALIB_PLAN_20261120.md) · [11 月 20 日已执行提示词](PI_SINGLE_CAMERA_PRECALIB_PROMPT_20261120.md)



