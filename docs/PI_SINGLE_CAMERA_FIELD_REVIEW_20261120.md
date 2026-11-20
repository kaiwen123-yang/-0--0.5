# 11 月 20 日现场结果后的接续审阅

基于现场提交 `537e59fec68438f3c8a051b4fe82465027f0c270`。北京时间 2026-11-20。范围为 π0 / π0.5 单腕相机实际测试。

## 已经完成，可以接续的部分

已核对仓库的现场报告、session、关联报告、单帧法兰记录、两份模型配置和周日脚本。DC1 CC16762023M 固定在腕端，`wrist`、唯一有效槽 `left_wrist_0_rgb` 已成为当前事实。5,382 张原始 RGB 均配到完整实测状态，180 秒只读记录与现场显示完成。已有记录不需要为重复确认同一结论再采一遍。

这段数据仍为 `observation_only`。CAN 发送增量为 0，动作标签为 0；静止状态不能改写为动作示范。当前两个模型仅完成环境/路径/配置部署，没有真实 norm、单相机训练 checkpoint 或推理结果。

来源：[现场报告](../results/piper-real-single-v1/20261120_194402/report_zh.md)、[关联报告](../results/piper-real-single-v1/20261120_194402/association_report.json)、[模型部署记录](../results/piper-real-single-v1/20261120_194402/autodl.json)。

## 1. 用现有数据补六关节报文跨度

现场 CAN 接口 `rx_dropped` 增量为 54，而记录到的 CAN 错误帧为 0，两者统计对象不同。不能据错误帧为 0 宣称接收链路无丢弃，也不能仅凭接口计数把丢弃分配到某个关节或图像。

H0 接收器收齐 `0x2A5/0x2A6/0x2A7` 后写一条六关节行，保存 `can_first_s` 与 `can_last_s`，但未约束三个报文属于同一周期。因此原先的“整行最近收到”与“六个分量均属于新的一组”需要区分。这是需要补查的范围，并不是已经发现本次状态错配。现有结果的 5,382 条完整关联计数仍按原定义保留。

新增 [joint_packet_audit.py](../tasks/piper_real_single_v1/joint_packet_audit.py)，只读本机已有三个文件：

- `joints.csv`：全部真实关节行的三帧内核接收跨度。
- `association/observations.jsonl`：哪些原图引用了哪条关节行。
- `arm_summary.json`：本次 boot 和实际接口前后计数。

工具用十进制原始时间字符串相减，报告全部行和 RGB 实际引用的唯一行两种分布、最大跨度来源、异常行号及对应图像索引。默认 5 ms 是 200 Hz 名义周期的筛查参考，**不是新设的通过阈值**；低于该值也不能证明来自同一控制器周期。工具不改原文件，不重新关联、不生成动作、不访问硬件。

在现场机执行：

```bash
PI=/home/kaiwen/Documents/Codex/2026-11-20/https-github-com-kaiwen123-yang-0/work/pi
SESSION=/home/kaiwen/Documents/Codex/2026-11-20/https-github-com-kaiwen123-yang-0/work/field/20261120_194402

/usr/bin/python3 "$PI/tasks/piper_real_single_v1/joint_packet_audit.py" \
  --joints "$SESSION/joints.csv" \
  --observations "$SESSION/association/observations.jsonl" \
  --arm-summary "$SESSION/arm_summary.json" \
  --output "$SESSION/joint_packet_audit_20261120.json"
```

若输出已经存在，直接阅读原结果；需要新一轮分析时用新文件名。读 `all_supplied_joint_rows`、`unique_joint_rows_referenced_by_rgb`、`affected_rgb_stream_indices` 和 `anomalous_joint_rows`。有异常再按原时间定位本机 `raw/raw_can.csv`，报告实际报文、跨度和可确认的影响；没有异常也保留“54 次接口丢弃未按 ID 归因”的边界。三帧跨度并不提供相机曝光时间。

现场已于北京时间 11 月 20 日执行本命令。全部 37,993 个关节行和 RGB 引用的 5,382 个不同行均未触发 5 ms 筛查；原图关联计数保留。周日可对新采的姿态目录运行同一工具。[离线审计与发送端接入点](../results/piper-real-single-v1/20261120_194402/joint_packet_review_zh.md)

来源：[固定 H0 接收器](https://github.com/kaiwen123-yang/dog-and-arm/blob/284c1f3f1bb9d5096003433f6153a9c5e95d6189/scripts/h0_record_arm.py)、[Linux 接口统计定义](https://docs.kernel.org/networking/statistics.html)。

## 2. 标定当前接收图像，不必先破解设备内部校正

原工具要求先在 `raw` 和 `rectified` 之间证明一个。设备内部几何处理未知时，这比求解实际图像模型所需的条件更强，会使周日流程不必要地等待固件说明。

现新增 `image_domain=received`：对稳定、可复现的 **当前接收像素** 拟合有效 K 和五项 Brown–Conrady 残余畸变 D。已知处理链、序列号、图像尺寸和安装仍须记录；设备内部是否校正继续为 `null`。这只是明确拟合对象，没有替设备内部状态作结论。五参数模型是待验证的几何近似，若实际 ISP 映射无法被充分描述，独立验证不合格时不能接受该模型。

周日在本次新 spec 中填写：

```json
{
  "image_domain": "received",
  "image_domain_verified": true,
  "device_internal_rectification": null,
  "image_domain_evidence": "按当日实查填写：640x480 MJPEG解码为rgb8；记录ROI、镜像、旋转、缩放和驱动版本；本次采集与求解不再做几何变换；设备内部处理未知"
}
```

上面的 `true` 必须由当日对固定处理链的核实支持，不因复制文本而成立。它确认的是接收像素的可复现性。已有证据明确原始几何或校正几何时，`raw` 和 `rectified` 模式继续可用；后者仍固定 D=0。原始 CameraInfo 和现场 `calibration_spec.json` 作为历史证据保留，不回写成已标定。

三个模式均使用原图，不额外去畸变/缩放。intrinsics 与 handeye 绑定同一序列号、光学系、尺寸和成像模型。输出 `T_flange_camera` 的 camera 指与有效 RGB 模型一致的光学系（右、下、前），不是外壳坐标系；若内部存在虚拟旋转，不能宣称它已等同于原始物理传感器轴。更不能套用于本次未配准深度。

依据：OpenCV 的 [calibrateCamera 与 calibrateHandEye 定义](https://docs.opencv.org/4.13.0/d9/d0c/group__calib3d.html)。对稳定接收流拟合“有效 K/残余 D”是本项目据该几何模型作出的工程选择，仍以真实独立数据评价；本次无板，未运行任何拟合。

## 3. 周日标定与之后的 π 测试

继续使用 [周日接续提示词和命令](PI_SINGLE_CAMERA_BOARD_HANDOFF_20261122.md)，无需改变腕部手眼方程：

`T_base_flange × T_flange_camera × T_camera_board = T_base_board`。

板相对基座刚性固定；采集分散的真实静止姿态，覆盖图像区域、距离和至少两个非平行旋转轴。先确认真实板型、内角点数量、格长、物理原点。当前检测器仅支持普通棋盘；如果到货型号不同，按实物接入检测器，不把未知尺寸填成建议尺寸。单姿态 FK 对照 0.00545 mm / 0.000506° 仅为软件来源一致性，不能代替多姿态物理轴和安装核对。

train 用于拟合 K/D 和手眼，heldout 独立报告像素残差、固定板平移/旋转残差以及最差姿态。heldout 的板参考仍由 train 建立。若依据该组结果调参、选模型或剔除姿态，将它记为开发验证并另留独立组。像素误差不等于机器人末端物理精度，接受条件结合首个实际任务的物体尺寸、间隙和允许误差确定。

接续顺序与实际产物：

| 环节 | 需要得到的真实结果 |
|---|---|
| 标定 | 有安装版本、光学系、K/D、T_flange_camera、独立残差和现场几何复核的资产 |
| 空间与连续目标跟踪 | 当前唯一发送端的实际绝对目标、反馈、原时间、停止行为；处理当前 URDF/实测关节边界差异，保留原测量 |
| 真实示范与数据整理 | 有动作标签的完整 episodes、原始对齐来源、任务指令、训练/验证划分 |
| 两模型全参 | 各自真实训练 split 的 norm、明确预算、分别保存的单相机 checkpoint |
| 策略实际测试 | 先看真实观测上的只读输出，再接入已验证的发送/停止链记录任务结果 |

手眼不是 RGB+关节模仿学习代码必读的张量，但它服务于本项目现场几何核对。标定完成能直接进入空间核对和连续目标跟踪，不会自动生成动作示范或已适配的 π 策略。D57 快照不证明两套全参可以同卡同时执行，继续保留两套全参目标与各自目录。

### 连续目标阶段同步记录动作，避免以后补采

不展开遥操作设备选型。先约定唯一实际发送端每条动作记录：

- `episode_id`、`command_id`、来源、控制模式，以及六关节绝对目标 rad 和夹爪总开口 m。
- 原始主机单调时刻、命令提交开始/结束、各次传输返回状态；有分帧、部分发送或失败时保留该事实，发送成功不等于物理跟踪成功。
- 请求目标与实际经过限幅/插值后提交的目标分别记录。训练监督必须有真实指令来源；反馈 q/g 仍为独立测量。
- 图像、关节、夹爪与动作分别保留原始时刻/索引。若动作由某次观测产生，记录其源观测 ID；避免以后用晚到图像反配早已发出的指令。
- 数据整理时另存 20 Hz 决策网格（50,000,000 ns 间隔）及每行对原始观测/真实动作生效区间的映射；不改写原时间，不把测量状态当动作，不把一个 episode 的动作块接到下一个 episode。

现有 `dataset.py` 只是读取已整理好的数组；发送端动作日志与这些数组之间的转换尚未实现。这项接口约定先留在接续任务中，待实际发送记录格式确定后实现转换。现有静止段继续保持 0 动作资格。

## 4. 11 月 20 日已执行的提示词（留作来源）

```text
继续 π0/π0.5 单腕相机实机。先读 AGENTS.md、docs/PI_REAL_TEST_STATE.md、
docs/PI_SINGLE_CAMERA_FIELD_REVIEW_20261120.md 和周日 BOARD_HANDOFF 文档。
保留现场 I 分支的已有工作、未提交修改和活动任务；按新增提交选择性同步
所需单相机文件/文档，遇到并行修改先对照合并，不用旧 main 仿真代码覆盖现场。

当前已确认 DC1 CC16762023M 腕部安装，两模型仅 left_wrist_0_rgb 有效。
已有 180 秒、5382 张连续原图和完整实测状态，无动作标签。
现在执行本审阅文档的 joint_packet_audit.py，读取现有 20261120_194402
会话的 joints.csv、association/observations.jsonl、arm_summary.json。
输出全部关节行、RGB 引用行的三报文跨度分布、最大来源和受影响原图索引。
有异常再按原时间读取既有 raw/raw_can.csv；不得用接口计数猜丢弃 ID。
保留原关联计数，明确短跨度也不证明同周期。无需再录同类180秒。

确认周日新 spec 可选择 received：固定接收像素上拟合有效 K/残余 D，
设备内部校正未知保持 null。只准备配置和命令，不在无板时填写真外参。
记录连续目标跟踪阶段的真实动作日志接入点及现有发送端可提供的时刻/目标，
只读相关代码，按审阅文档约定保留请求值、实际提交值和实测反馈的区别。
暂不讨论遥操作设备；本轮不启动机械臂运动、训练、推理或资源试跑。

将这次真实离线审计的小报告、结论和周日接续状态推送到 π 仓库。
明确未完成的现场条件；保留完整原始数据于本机，不归档/压缩/移动/删除，
不重装环境，不新增相机，不改 dog-and-arm，不执行 H/I 或其他机器人任务。
```

## 准备提交 282a04f 的核验范围（历史）

对照当前提交和固定 H0/OpenCV 原始文档做源码审阅；两项 Python 修改做静态语法解析，配置 JSON 做解析检查。未在此工作区运行现场 CSV 审计、相机/机械臂、模型、标定拟合或模拟测试。原有现场数据报告保持原样，状态中的待执行项与已完成项分开。
