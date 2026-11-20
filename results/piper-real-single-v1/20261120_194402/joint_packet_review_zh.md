# 11 月 20 日腕部 DC1 会话 · 关节报文离线审计

**全部 37,993 条六关节反馈、RGB 引用的 5,382 条不同反馈，三报文跨度均小于 0.5 ms。** 5 ms 名义周期筛查标记 0 行，受影响图像索引为空。数据来自北京时间 19:44:50 开始的 `20261120_194402` 实录，本次在同一现场机上离线分析。[实际审计 JSON](joint_packet_audit_20261120.json)

## 报文跨度与来源

已执行准备提交 `282a04f` 的 `joint_packet_audit.py`，输入为原 `joints.csv`、`association/observations.jsonl` 和 `arm_summary.json`。按十进制时间原值计算三报文组的内核接收跨度 `(can_last_s − can_first_s) × 1,000`，单位 ms。按 boot、CSV 数据行号、主机接收时间及保存的 CAN/SDK 时间逐一核对 RGB 引用。[复现命令](../../../docs/PI_SINGLE_CAMERA_FIELD_REVIEW_20261120.md)

| 关节行集合 | 行数 | 最小 ms | P50 ms | P95 ms | P99 ms | 最大 ms | 标记行 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 完整关节 CSV | 37,993 | 0.0019 | 0.2391 | 0.2923 | 0.321508 | 0.4976 | 0 |
| RGB 实际引用的唯一关节行 | 5,382 | 0.0478 | 0.2400 | 0.2916 | 0.321719 | 0.4640 | 0 |

| 最大值来源 | CSV 数据行（从 1 起，不含表头） | 主机单调接收 ns | CAN 首 / 末内核时间 s | RGB stream_index（从 0 起） |
|---|---:|---:|---|---|
| 全部行 | 21,339 | 2390955409910 | 1795175196.9810407 / 1795175196.9815383 | 无引用 |
| RGB 引用行 | 22,628 | 2397401757284 | 1795175203.4271376 / 1795175203.4276016 | 3371（JSONL 第 3372 行） |

无缺失、无效、非有限或逆序的首末时间，无跨度 ≥ 5 ms 的关节行。异常行 `[]`，受影响 RGB 索引 `[]`，无引用不到关节行的图像。两处最大值都是正常筛查记录。原 5,382 条完整观测计数保持原义，每行均为 `action=null`、`training_eligible=false`。

短跨度只描述三条报文在内核中的到达时间，无法单独确认六轴来自控制器同一周期，也无法确定相机曝光同步。接口快照的 `rx_dropped` 从 179,918 增至 179,972（+54），记录到 CAN 错误帧 0，接口 TX 增量 0。此次无筛查异常，未展开 `raw/raw_can.csv`；54 次接口丢弃的 CAN ID 和图像归属仍未知。[原关联统计](association_report.json)

## 后续连续目标的动作日志接入点（仅源码审阅）

现场 H0 的唯一操作者进程为 `scripts/h0_operator_motion.py`，用 `flock` 互斥。核对了该文件、它调用的 OSCBF `PiperDevice` 及现场 SDK 的发送代码。后续在同一发送进程内关联下列记录，无需另开控制器。[H0 唯一入口](https://github.com/kaiwen123-yang/dog-and-arm/blob/284c1f3f1bb9d5096003433f6153a9c5e95d6189/scripts/h0_operator_motion.py#L28-L55)

| 记录层 | 已有值、时刻和含义 | 后续接入位置 |
|---|---|---|
| 请求与插值 | `--start-deg`、段端点、阶段和夹爪请求可从发送端取得。每个关节周期用实际经过时间线性插值得到六维绝对 q。 | 在段请求、夹爪请求处记录来源、episode_id、command_id、源观测索引及请求时间；在 `move(q, phase)` 和 `move_gripper_m` 调用前后分别记录提交开始/结束。 |
| SDK 调用 | `motion_commands.csv` 在高层调用返回后写主机单调 ns、Unix ns、phase、关节 q（rad）或开口（m）和速度/力。当前 CSV 缺调用起始时刻、逐帧结果和命令 ID。初始 `enable_at(base)` 也会调用 MOVE_J，须单列初始化来源。 | 同一命令 ID 下分别保存原请求、插值后的 API 入参和实际编码目标；关节、夹爪分开发送，未更新的维度仅可引用有依据的上一有效提交。 |
| 实际主机提交 | SDK 处理关节限值，将 q 量化到 0.001°，编码成 0x155/156/157；夹爪总开口量化到 µm、力到 mN，编码为 0x159。H0 已有 `recorded_send` 钩子在 `comm.send` **之前**写时间、phase、CAN ID 和载荷到 `motion_sdk_tx.csv`。该记录仅证明尝试发送。 | 保留尝试帧。在实际 `send_bus.send` 调用前后按命令 ID 记录帧序号、载荷、单调时间、正常返回或异常/errno；据已成功提交的目标帧还原绝对值，单列模式/使能/停止帧及部分发送、跳过和未知状态。 |
| 实测反馈 | 只读 H0 独立保存六关节与夹爪测量、原时间及行号；段末事件还保存关节测量或夹爪开口/力。 | 用原始时刻和序号对照跟踪效果、停止行为。主机提交和物理到达分别记录。 |

H0 的 `move_j` 和夹爪高级 API 没有逐目标送达回执。SDK 的 `CanComm.send` 对识别为 ENOBUFS / ENETDOWN 的错误设置 `last_error` 后可以正常返回，后续接收又可能清除它。因此仅在外层记录“返回”、事后读取 `last_error` 或统计 TX 行数，都可能误判。应在原发送对象调用底层 python-can 的位置记录结果。只有完整所需目标帧获得主机提交证据时才标为完整提交；控制器是否采纳、跟踪或停止仍由独立反馈核对。[H0 插值、调用与 TX 钩子](https://github.com/kaiwen123-yang/dog-and-arm/blob/284c1f3f1bb9d5096003433f6153a9c5e95d6189/scripts/h0_operator_motion.py#L73-L100) · [夹爪与停止事件](https://github.com/kaiwen123-yang/dog-and-arm/blob/284c1f3f1bb9d5096003433f6153a9c5e95d6189/scripts/h0_operator_motion.py#L132-L170) · [初始化目标](https://github.com/kaiwen123-yang/OSCBF-learn/blob/2ea3f1f48d10591b2bcb770af704011b381910b7/piper_oscbf/device.py#L113-L129) · [SDK 返回与异常处理](https://github.com/agilexrobotics/pyAgxArm/blob/d90e234ba8e408cfa964b38aa9120b3131fc9f85/pyAgxArm/protocols/can_protocol/comms/can_comm.py#L191-L218)

这次只定位接入点。20 Hz 训练网格和动作块的整理仍需未来的真实动作事件，按原观测因果关系、命令有效区间和 episode 边界建立映射。本次没有产生或补填动作标签。

## 周日标定状态

独立准备的周日配置选 `image_domain=received`、`image_domain_verified=false`、`image_domain_evidence=null`、`device_internal_rectification=null`。保留 11 月 20 日现场 spec 原件。源码已核实：received 在 train 图上拟合该接收流的有效 K 和五项残余 Brown–Conrady 畸变；handeye 检查相机序列号、光学系、尺寸和模型一致性，heldout 独立评估。没有运行拟合。[周日配置](calibration_spec_20261122_prepared.json) · [接续命令](../../../docs/PI_SINGLE_CAMERA_BOARD_HANDOFF_20261122.md)

11 月 20 日记录为腕端 DC1 CC16762023M、640×480 MJPEG → ROS rgb8、无 ROI、镜像 getter 为 0。周日重新核实序列号、支架、尺寸、镜像、ROI、旋转、缩放及保存/求解端的像素处理，在当日副本填写依据后才能设置 verified=true。设备内部校正未知继续留 null。到板后还须确认实物几何、板相对基座的刚性固定、多姿态与独立验证。本次为已有观测的离线分析，运动、标定拟合、训练和推理均未运行。
