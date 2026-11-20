# 11 月 22 日到板后接续 · DC1 腕部单相机

## 可直接交给现场 Codex 的提示词

> 继续 π 实机。先读本文件、`docs/PI_SINGLE_CAMERA_FIELD_REVIEW_20261120.md` 和 `results/piper-real-single-v1/20261120_194402/report_zh.md`。11 月 20 日已完成 180 秒只读实录、关联和单帧导出。DC1 序列号 CC16762023M，照片确认腕部支架，唯一模型槽 left_wrist_0_rgb。沿用已验机的 H0 单发布者和接收器。核实今日支架、基座、板型、尺寸、原点、固定方式和图像模式，填本次 spec。若设备内部校正状态仍未知，确认固定接收处理链后选 received，拟合有效 K 与残余 D，内部状态仍留空，不冒称 raw 或已校正。把板刚性固定到相对基座静止的桌面；现场人员用既有唯一操作入口定位，静止后逐姿态调用下方命令，预留独立组。检查图像、法兰反馈、实测关节 FK、六关节报文跨度和角点方向，按真实证据填写 review。只用 train 求解 K、D 和 T_flange_camera，报告 heldout 像素、毫米和角度误差。只有独立验证和现场几何复核通过才将结果绑定到同一安装版本。条件未满足时指出具体姿态、图像或固定问题。保留原始记录于本机。更新 π 仓库的紧凑结果和状态。机器人的使能、回零或运动不由本提示词启动。模型训练、推理、遥操作、H/I 和其他机器人任务不属于这次标定。

## 本机入口

以下变量在**各终端**设置一次。`CAL` 选择新目录，避免覆盖周日的其他会话。下例固定为当天第一个会话。

```bash
PI=/home/kaiwen/Documents/Codex/2026-11-20/https-github-com-kaiwen123-yang-0/work/pi
H0=/home/kaiwen/research/dog-and-arm
TOOLS="$PI/tasks/piper_real_single_v1"
CAL="$(dirname "$PI")/field/board_20261122_01"
SPEC="$CAL/calibration_spec.json"
```

在一个终端初始化一次，按板上标识和量具实测填写副本，沿用相机、话题、分辨率、基座和法兰定义。

```bash
mkdir "$CAL" && cp "$PI/results/piper-real-single-v1/20261120_194402/calibration_spec.json" "$SPEC"
```

- 普通棋盘填 `board.type=chessboard`、真实内角点列/行、格长（m）。用硬底板或夹具把板固定在基座所在刚性桌面，夹具放在图案外，留出边框。记录基座夹具、板四角和物理原点照片。核实后填写 `geometry_verified`、`rigid_mount_verified`、`origin_description`、`x_axis_description`、`y_axis_description`。ChArUco/AprilGrid 须先按实物字典、ID、间距接入对应检测器。
- 复核 USB 身份、`can0` 为 1 Mbps UP、ROS 图像为 640×480。检查视野中的遮挡，移开标定区的笔记本等物品后固定环境。复核腕端支架在各采集姿态下牢固、线缆有余量。
- 终端 A 检查已有发布者。若 RGB 发布者已存在就直接订阅；若没有，运行最后一行并保留该终端。

```bash
ip -details link show can0
bash "$H0/scripts/h0_ros_env.sh" ros2 topic list --no-daemon --spin-time 2
# 仅在没有运行中的 H0 相机驱动时启动
bash "$H0/scripts/h0_camera.sh"
```

终端 B 保持现场画面。单姿态记录器各自保存真实状态，此处作为构图视窗。

```bash
bash "$H0/scripts/h0_ros_env.sh" /usr/bin/python3 "$TOOLS/live_view.py" \
  --topic /wrist_camera/color/image_raw --camera-id CC16762023M --mount wrist
```

终端 C 的逐姿态入口用于当前没有活动 H0 记录器时。若已有同一会话在连续记录原图和反馈，保持现有接收器，在各稳定姿态记录其 RGB 索引及预分配的组名和 split。采集结束后按会话运行 associate_h0.py，并用 flange_observation.py 的 `--session`、`--stream-index`、`--pose-group`、`--split` 将每个真实姿态写入 `$CAL/poses/<组名>/capture.json`。

在每个已摆好、稳定且可见整板的新姿态执行**一次**。下列两条分别是训练组和独立组的调用示例，两次之间须由现场人员实际更换姿态。提前分配组名，可安排 20 个以上 train、另留 5 个以上 heldout。覆盖图像中心、边缘、不同距离和至少两个非平行旋转轴。一次姿态只能属于一个 split，避免把相邻帧当独立验证。

```bash
bash "$TOOLS/capture_pose.sh" "$CAL" train t01
# 另一个事先分配给验证集的实际姿态，静止后执行
bash "$TOOLS/capture_pose.sh" "$CAL" heldout h01
```

每次先启动本次 H0 接收器，再用同一图像发布者记录 3 秒，结束本次接收器。PNG、时间表、原始 CAN 和关联结果保存在 `$CAL/poses/<组名>/`。从接收窗口取中间 RGB，使用同 boot 先行关节测量生成 `capture.json`。其中有图像/位姿时间、joint FK、控制器三帧法兰反馈、两者差值和前后各 250 ms 的关节变化。失败的姿态保留现场记录，重采使用新组名。

## 角点、位姿与独立验证

```bash
/usr/bin/python3 "$TOOLS/pose_manifest.py" --cal "$CAL" --spec "$SPEC" \
  --output "$CAL/captures.jsonl" --write-review "$CAL/review.csv"
/usr/bin/python3 "$TOOLS/calibration.py" detect --spec "$SPEC" \
  --manifest "$CAL/captures.jsonl" --out "$CAL/detect"
```

逐帧查看 `detect/overlays/` 的原点与末角标签，对照同一物理角和轴向。在 `review.csv` 里按样本修正 `corner_order`（矩形可选 `reverse_180`），根据静止窗、关节及控制器法兰对应关系、基座固定和角点方向逐项写 0 或 1。方向有修改先生成一份修订 manifest 再运行 detect 到新目录，实际查看修正叠加后再确认。保留原始记录和第一份 manifest。

核对 spec 中的 `robot.pose_source_verified`，依据是本次多姿态的实际位姿、轴映射和刚性安装复核。11 月 20 日第 120 帧可复现软件 FK，单点证据不足以设置此项。同时查看六关节三报文跨度；完整合成行的新鲜度不证明每个分量来自同一周期。可对每个姿态目录运行接续审阅中的离线检查；有异常的样本回看本次原始 CAN 和静止窗后再决定是否使用。

拟合前固定实际接收流的像素几何。推荐在当前设备内部校正未知时选择 **`image_domain=received`**：以本次 640×480、MJPEG 解码后 rgb8 的未另行变换像素拟合有效 K 与五项残余畸变 D。实查今日分辨率、镜像、ROI、旋转、缩放与支架安装，把依据写入 `image_domain_evidence`；确认处理链固定、可复现后设置 `image_domain_verified=true`，并保留 `device_internal_rectification=null`。此确认针对记录的像素处理链，不是对固件是否去畸变的结论。若处理链本身尚未固定，仍只采图/检测，不拟合。

若有明确原始像素证据可选 `raw`；有明确校正证据可选 `rectified`，后者固定 D=0。不要用 CameraInfo D0 判定已校正，也不要把工厂候选系数直接写回驱动。received 模型能否描述当前流，要看独立组像素与几何误差；参数/角点约定在看独立结果前固定。若据独立结果修改模型或剔除姿态，应把该组记为开发验证并另采新独立组。输出光学系为有效 RGB 成像模型的右、下、前三轴，不能把它自动套到未配准深度或相机外壳。

```bash
/usr/bin/python3 "$TOOLS/pose_manifest.py" --cal "$CAL" --spec "$SPEC" \
  --review "$CAL/review.csv" --output "$CAL/reviewed.jsonl"
/usr/bin/python3 "$TOOLS/calibration.py" intrinsics --spec "$SPEC" \
  --manifest "$CAL/reviewed.jsonl" --out "$CAL/intrinsics"
/usr/bin/python3 "$TOOLS/calibration.py" handeye --spec "$SPEC" \
  --manifest "$CAL/reviewed.jsonl" --intrinsics "$CAL/intrinsics/intrinsics.json" \
  --method park --out "$CAL/handeye"
jq '{train_reprojection_rms_px, heldout_reprojection_rms_px, heldout_per_view}' "$CAL/intrinsics/intrinsics.json"
jq '{T_gripper_camera, train_rotation_second_to_first_ratio, heldout: .residual_summary.heldout}' "$CAL/handeye/handeye.json"
```

两条求解命令各自计算独立误差。内参固定训练所得 K/D，对每张独立图只估板姿。手眼对每个独立姿态计算 `T_base_flange × T_flange_camera × T_camera_board` 相对训练组固定板参考的残差。按 mm 和度报告分布、最大值及对应姿态，结合任务空间容差决定是否接受，保留 `FIT_REQUIRES_REVIEW` 直到完成复核。

通过后将矩阵、方向、图像域、分辨率、序列号、支架照和采集版本绑定到此次 wrist 会话，先用只读实测位姿做空间一致性核对。再由现场明确启动 H0 唯一发送端，小范围记录连续绝对目标、反馈、时刻与停止行为。动作块恢复的绝对关节目标只执行一次，无二次累加。真实示范须另外记录实际下发动作并划分 episode，两模型用各自训练 split 的 norm。

