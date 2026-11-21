# 已到货 Q12-290-20 铝基棋盘板：DC1 腕部标定流程

> **2026-11-21 后续状态补记：**现场已完成内参/手眼候选和4正式＋3回溯姿态复核，源在 field/pi-single-20261120@b3bb539。新审计发现实际D在两个图像底角无正常中央分支逆解，不能按全画面验收；停止后硬件恢复也未完成。当前先读[审计结论](PI_Q12_CALIBRATION_AUDIT_20261121.md)、[新接续提示词](PI_Q12_CALIBRATION_REVIEW_NEXT_PROMPT_20261121.md)和[每日工作日志](PI_DAILY_WORK_LOG.md)，不要照本文旧提示词从头重复采集或自动恢复运动。以下保留当日采集前的原流程作历史参考。

更新：北京时间 2026-11-21。用户确认标定板已收到，无需等原计划的 11 月 22 日。对象是 Piper H、官方夹爪、腕部 DC1（CC16762023M）；唯一 π 图像槽仍为 `left_wrist_0_rgb`。本文已按 `b93ee78` 的实际采集与标定脚本核对，未执行硬件采集或求解。

## 1. 本次做什么

**把板固定到相对机械臂基座不动的桌面或支架，让机械臂带着相机从不同姿态看板；每次停稳后，同时记录 RGB 和真实法兰位姿。用这批数据先求 RGB 内参，再求腕部手眼，最后用预留姿态验证。**

内参结果是当前 640×480 接收图像的有效 `K` 和残余畸变 `D`。手眼结果是 `T_flange_camera`：把 RGB 光学坐标中的点变换到法兰坐标。现有代码文件中字段名为 `T_gripper_camera`，但 spec 的 `gripper_frame=flange_link`，本轮两者是同一含义。它不是夹爪指尖 TCP，也不是未配准深度相机的外参。

标定过程中机械臂定位由现场人员使用已有唯一操作入口完成。下述采集脚本只读图像与反馈，不负责使能、回零、移动或夹爪动作。本任务不启动 π 推理或自动任务执行。

## 2. 板参数：程序填 11×8 内角点、0.020 m

厂家 [Q12 型号表](https://www.dfoptic.com/in-stock-standards-product/152.html) 给出如下名义几何：

| 项目 | 本型号参数 |
|---|---:|
| 型号 / 用户收到的材质 | Q12-290-20 / 铝基板 |
| 板外形 | 290×230 mm |
| 黑白图案 | 12×9 个方格，240×180 mm |
| 单格边长 | 20 mm |
| OpenCV 内角点 | 长边 11、短边 8，共 88 个 |
| 程序单位 | `square_size_m=0.020` |
| 最外侧内角点之间的跨度 | 长向 200 mm、短向 140 mm |

内角点数量由方格数各减 1 得出；外框、图案尺寸和内角点跨度是三个不同量。厂家的光刻工艺表不能替代用户这块铝基实物的精度证明，本文只据其核实名义几何。

现场先拍正面、型号标签和固定方式。数清 12×9 方格，用尺跨 10 个格距核查约 200 mm，排除型号/单位错误。若随板证书给出了明确的实际格距，记录并采用可追溯值；普通尺读数只用于粗核，不据此声称微米精度。

模板已准备在 [calibration_spec.q12_290_20.example.json](../tasks/piper_real_single_v1/calibration_spec.q12_290_20.example.json)。几何参数可预填，但 `geometry_verified` 等现场标志保持 false，核实后才能逐项更新。注意：现有 `detect` 也要求 `geometry_verified=true`。

## 3. 摆放与原点

1. 保持相机与腕部支架的相对位置不变，基座固定。板放到相机容易看到、机械臂能从不同方向观察的位置；可竖放或倾斜固定，不要求与桌面平行。
2. 板和基座在整批采集期间相对静止。采集过程中不手持板、不重新挪板。夹具放在图案外，保留四周连续白边。避免反光和夹爪遮住内角点。
3. 先拍清板的正面与边框方向。首张 t01 检测后，以实际 `ORIGIN 0` 对应的物理内角点作为本次原点；也可选它的对角并采用 `reverse_180`。依据实际角点序确认长边 +x、短边 +y，再在图案外的边框外缘标记并拍照。当前矩形排序仅支持这一对对角互换，不任意指定其他相邻角。这是人工方向参考，现有检测器不会自动识别标签。正式求解前把 spec 中待现场的原点和轴描述换成可与照片对应的实际说明。
4. 所有图中 `ORIGIN 0` 都应对应这个同一物理点，`LAST 87` 对应其对角的最后一个内角点。不要按每幅图的屏幕左上角重新定义原点。

先用实际画面调整距离：全棋盘、全部 88 个内角点和周围白边应清晰可见。作为构图建议，可先让图案宽度占画面约一半至四分之三，再安排较近/较远和偏边的姿态；倾斜时仍应看到整板。无需为本次标定购买第二台相机。

## 4. 保持本次像素处理链固定

沿用 640×480 RGB 和 `/wrist_camera/color/image_raw`。保存原始接收画面，不用截图、带字 viewer 图、缩放/裁剪/镜像后的预览图求解。核实本轮收到的分辨率、编码转换、ROI、旋转、镜像和缩放，并把实际依据填入 `image_domain_evidence`。

当前 CameraInfo 的 D 全零，但设备服务 r_k 非零；此前尚未证明固件是否内部去畸变。本次采用已有方案 `image_domain=received`：对固定的接收像素拟合有效 K 和五项残余 D。确认的是处理链可复现，`device_internal_rectification` 仍保持 null，不需要为了开始标定猜成 raw 或 rectified，也不把工厂系数直接写回驱动。

本轮为 RGB 几何标定；深度未配准这一事实保留。得到 RGB 手眼后，不能直接把原始深度按 RGB 像素取值并宣称已经获得正确三维点。

## 5. 现场命令：先采一个实际姿态看角点

先同步本轮明确文件，保留现场分支、未提交修改与活动进程。以下 `PI` 为此前已核实的工作区入口；如果现场已换目录，由 Codex 根据实际项目位置调整。所有变量需要在使用它们的各个终端分别设置。

```bash
PI=/home/kaiwen/Documents/Codex/2026-11-20/https-github-com-kaiwen123-yang-0/work/pi
H0=/home/kaiwen/research/dog-and-arm
TOOLS="$PI/tasks/piper_real_single_v1"
CAL="$(dirname "$PI")/field/board_q12_20261121_01"
SPEC="$CAL/calibration_spec.json"
```

初始化一次新会话。若 `_01` 已存在，另选 `_02`，不覆盖原数据。

```bash
mkdir "$CAL"
cp -n "$TOOLS/calibration_spec.q12_290_20.example.json" "$SPEC"
```

现场核实板型、格长、安装及处理链后编辑 `$SPEC`。检测前至少完成板几何的实际核实；内参拟合前完成图像链核实；手眼拟合前再完成固定关系和多姿态位姿来源核实。各标志分阶段填写，不能整批自动置 true。

终端 A 检查 CAN 和已有相机发布者，复用正在运行的唯一驱动。相机驱动不存在时，才运行最后一行并保持终端。

```bash
ip -details link show can0
bash "$H0/scripts/h0_ros_env.sh" ros2 topic list --no-daemon --spin-time 2
# 仅在没有正在运行的 H0 相机驱动时启动
bash "$H0/scripts/h0_camera.sh"
```

`can0` 应是既有的 1 Mbps、UP 状态；上述检查不重新配置 CAN。若已有本会话连续记录器，应沿用旧接续文档的连续记录分支，不再同时启动逐姿态接收器。

终端 B 打开构图窗口：

```bash
bash "$H0/scripts/h0_ros_env.sh" /usr/bin/python3 "$TOOLS/live_view.py" \
  --topic /wrist_camera/color/image_raw --camera-id CC16762023M --mount wrist
```

终端 C：现场人员先把机械臂移到第一个可见整板的姿态，停稳约 1～2 秒再执行。等待是操作建议，最终仍看反馈中的静止窗口；不手推处于使能保持状态的机械臂。

```bash
bash "$TOOLS/capture_pose.sh" "$CAL" train t01
/usr/bin/python3 "$TOOLS/pose_manifest.py" --cal "$CAL" --spec "$SPEC" \
  --output "$CAL/first_pose.jsonl"
/usr/bin/python3 "$TOOLS/calibration.py" detect --spec "$SPEC" \
  --manifest "$CAL/first_pose.jsonl" --out "$CAL/first_detect"
```

查看 `first_detect/overlays/`，确认实际检测到全部 88 个角点、原点/末角位置和图像清晰度。按上文以这一张的实际角点序确定物理原点与轴向，在图案外标记并拍照。t01 是正式数据的一部分，不是额外模拟测试。若要重采，保留失败记录，用新姿态名，不覆盖。

## 6. 换姿态：建议 25 个拟合姿态＋8 个独立验证姿态

下面是本项目建议的采集分配，不是厂商或 OpenCV 规定的强制数量。现有代码最低要求为检测成功后 15 个 train 和 5 个 heldout 独立姿态，采集余量用于应对模糊、遮挡和重复姿态。

| 分组 | 数量 | 如何变化 |
|---|---:|---|
| t01～t05 | 5 | 中等距离，让板在画面中心、左右、上下分布 |
| t06～t10 | 5 | 改变距离和图像覆盖范围，保留较近、较远的清晰整板视图 |
| t11～t18 | 8 | 从不同侧向、俯仰方向斜看，建议尝试约 15～35° 相对倾斜，以整板可见和实际可达为准 |
| t19～t25 | 7 | 组合侧向/俯仰与少量滚转，增加相对旋转方向和位置差异 |
| h01～h08 | 8 | 提前指定为独立验证；使用没有进入拟合组的新距离、位置和组合角度 |

每次实际换姿态、停稳，然后调用一次：

```bash
# 实际换到下一姿态后
bash "$TOOLS/capture_pose.sh" "$CAL" train t02
# ……继续实际换姿态，不用 shell 循环在同一姿态伪造多个组
# 实际换到事先分配给独立验证的姿态后
bash "$TOOLS/capture_pose.sh" "$CAL" heldout h01
```

每次脚本记录 3 秒 RGB 与接收反馈，选中间图像，并保存实测关节 FK、控制器法兰对照以及图像前后各 250 ms 的关节变化。3 秒中的相邻帧不能冒充多个独立姿态。每次过程中保持静止，等命令返回再移动。

手眼需要至少两个非平行旋转轴方向上的相对运动；只平移或只绕一个轴转会退化。OpenCV 官方文档也明确这一条件。本流程不提供盲发的固定关节角度轨迹，姿态以本机工作空间和画面为准。

在这些实际姿态中同步核查控制器法兰与 Piper H 实测关节 FK、多姿态方向和基座/法兰定义。此前单点的极小软件差值不能证明真实机械臂的绝对精度。已有 180 秒记录及三 CAN 报文跨度审计已完成，无需重跑；新增姿态只分析本次数据。

## 7. 按真实证据核对角点、静止与位姿

全部采集后生成初始清单和复核表：

```bash
/usr/bin/python3 "$TOOLS/pose_manifest.py" --cal "$CAL" --spec "$SPEC" \
  --output "$CAL/captures_initial.jsonl" --write-review "$CAL/review.csv"
/usr/bin/python3 "$TOOLS/calibration.py" detect --spec "$SPEC" \
  --manifest "$CAL/captures_initial.jsonl" --out "$CAL/detect_initial"
```

`review.csv` 的真实字段为：

```csv
sample_id,corner_order,pose_verified,static_capture_verified,board_orientation_verified
t01,detected,0,0,0
```

- `corner_order`：本矩形棋盘可选 `detected` 或 `reverse_180`。不能使用只支持正方形角点阵列的 90° 修正。
- `pose_verified`：本样本位姿来源、时间对应和定义已核对。
- `static_capture_verified`：本样本实际静止窗口已核对。
- `board_orientation_verified`：已看过最终角点叠加，确认原点和轴向对应同一物理角。

后三项逐条填写 0 或 1。先看初始叠加，再纠正有依据的角点顺序；生成新清单、重新 detect 后，才确认方向复核：

```bash
/usr/bin/python3 "$TOOLS/pose_manifest.py" --cal "$CAL" --spec "$SPEC" \
  --review "$CAL/review.csv" --output "$CAL/oriented_v1.jsonl"
/usr/bin/python3 "$TOOLS/calibration.py" detect --spec "$SPEC" \
  --manifest "$CAL/oriented_v1.jsonl" --out "$CAL/detect_oriented_v1"
# 实际查看新 overlays，完成静止/位姿/角点方向复核并编辑 review.csv 后
/usr/bin/python3 "$TOOLS/pose_manifest.py" --cal "$CAL" --spec "$SPEC" \
  --review "$CAL/review.csv" --output "$CAL/reviewed_v2.jsonl"
```

**0 不代表自动排除。** 当前表没有 `exclude` 列；完整检测到的样本若仍有未通过标志，手眼拟合会拒绝运行。确实不合格的姿态应保留原记录，在新的 `fit_manifest_v1.jsonl` 中明确筛出，并保存样本 ID、原因和计数。不要为让求解通过而把 0 批量改为 1。

manifest、review 和主要拟合结果均拒绝覆盖已有文件；修改后使用新文件名/目录。若看了独立验证结果后又据其调整模型或挑选姿态，原 heldout 应记为开发验证，再采新的最终独立组。

## 8. 求解：先内参，再手眼

拟合前确认本次 spec 的 `image_domain_verified` 及依据已填写。手眼另要求 `installation_verified`、`board.rigid_mount_verified`、`robot.pose_source_verified` 由真实记录支持。

以下默认所有 reviewed 样本通过；若生成过显式筛选清单，只把 `MANIFEST` 改成那个新文件，两步使用同一清单。

```bash
MANIFEST="$CAL/reviewed_v2.jsonl"
/usr/bin/python3 "$TOOLS/calibration.py" intrinsics --spec "$SPEC" \
  --manifest "$MANIFEST" --out "$CAL/intrinsics_v1"
/usr/bin/python3 "$TOOLS/calibration.py" handeye --spec "$SPEC" \
  --manifest "$MANIFEST" --intrinsics "$CAL/intrinsics_v1/intrinsics.json" \
  --method park --out "$CAL/handeye_v1"
```

只有 train 参加 K/D 与手眼拟合。heldout 内参评估固定 K/D，只为每张图估计板姿；这不是直接测量毫米误差。手眼验证计算：

```text
T_base_flange(i) × T_flange_camera × T_camera_board(i) = T_base_board(i)
```

板固定时，这个结果应该不随姿态明显变化。代码把 heldout 的结果与只由 train 得到的固定板参考比较，不把 heldout 加进参考拟合。矩阵命名约定为 `T_a_b` 将 b 系坐标映射到 a 系，平移单位为 m。

直接查看原始输出：

```bash
jq '{status, train_reprojection_rms_px, heldout_reprojection_rms_px, heldout_per_view}' \
  "$CAL/intrinsics_v1/intrinsics.json"
jq '{status, T_gripper_camera, train_rotation_second_to_first_ratio, heldout: .residual_summary.heldout}' \
  "$CAL/handeye_v1/handeye.json"
```

报告手眼 `translation_error_m` 时乘 1000 换成 mm；`rotation_error_deg` 已是度。列出均值、P95、最大值和最差姿态 ID。旋转激励比值只是一项诊断，非零不自动代表姿态充分。

## 9. 怎样判断这一轮可以接受

首先核实物理固定、板尺度、角点方向、有效像素域及多姿态来源，再看独立误差。作为首次桌面抓放准备的**工程目标**，可先参考：

| 指标 | 初步目标/排查依据 |
|---|---|
| 有效角点与姿态 | 每个有效样本 88 个角点；达到 train/heldout 独立姿态数量，并具有多轴旋转变化 |
| 内参 heldout | 每视图重投影 RMS 均值争取 ≤0.5 px；单图 >1 px 时重点回看该图和模型 |
| 手眼 heldout 固定板一致性 | 平移残差 P95 争取 ≤5 mm、旋转残差 P95 争取 ≤1°；最大值单独报告和审查 |
| 物理合理性 | 解出的相机相对法兰位置/方向与安装照、可量到的粗略距离一致；不存在反向、明显不合理的偏移 |

这些是本项目提出的初步参考，不是厂家保证、OpenCV 标准或代码中的自动验收阈值。固定板残差小也不等于机器人绝对定位误差同样小。最终应结合实际抓放容差与独立空间检查决定接受；后续精密装配需要更严格的任务验证。

软件输出 `FIT_REQUIRES_REVIEW` 是正常的“已拟合、待复核”状态，不应被改写成自动通过。通过后单独记录验收依据，把 K/D、矩阵、坐标方向、分辨率、相机序列号、实际处理链、支架照片和会话版本绑定。脚本不会自动发布 TF 或改写 CameraInfo。

标定板之后可以收走；相机与法兰的相对安装若改变，需重新核对/重做手眼。当前结果不能自动套给相机外壳坐标、夹爪指尖或未配准深度流。

## 10. 可直接复制给现场 Codex 的提示词

**历史提示词，已由上方新接续入口替代。** 新增长期要求：每次工作结束都要按北京时间更新唯一 `docs/PI_DAILY_WORK_LOG.md`，记录实际做了什么、解决了哪些问题及依据、未解决项、最后现场状态与下一步；不能把计划或未执行步骤写成完成。

```text
继续 π 仓库的实机标定。用户已于 2026-11-21 收到大凡光学 Q12-290-20【铝基板】，现在开始，不等原计划 11 月 22 日。

先读 AGENTS.md、docs/PI_REAL_TEST_STATE.md、docs/PI_Q12_BOARD_CALIBRATION_20261121.md，以及 tasks/piper_real_single_v1/calibration_spec.q12_290_20.example.json。保留现场分支、未提交修改和其他活动进程，复用已有 H0 相机/采集环境；不重装、不重做 180 秒采集或已完成 CAN 审计。

固定对象：Piper H、官方夹爪、腕部 DC1 CC16762023M，640×480 RGB，left_wrist_0_rgb。厂家表确认名义 12×9 方格、20mm 格长；程序 11×8 内角点、0.020m。先让现场拍正面/标签、数格和跨多格量尺，保存证据后才设 geometry_verified=true。板固定到相对基座静止的桌面/支架。首张 t01 检测后，用实际ORIGIN 0对应的物理角点（或采用reverse_180的对角）确定原点与+x/+y，在图案外标记并拍照，填写实际spec说明；不要任意指定当前排序无法表达的相邻角。

沿用 received 图像域，现场确认实际像素链后填写 image_domain_evidence 和 image_domain_verified；device_internal_rectification 未知仍为 null。不要仅因 CameraInfo D=0 判定已校正，不把 RGB 标定冒称深度配准。

你负责图像/反馈采集、显示、复核与求解。机器人位姿由现场人员通过既有唯一入口调整，采集脚本不执行使能/回零/运动。先采 t01 并检测 88 个角点，确认画面和实际方向后继续。建议总计25个train和8个heldout独立姿态，覆盖位置、距离、俯仰/侧向/滚转组合，至少两个非平行旋转轴。每姿态停稳后运行 capture_pose.sh 一次；同姿态多帧不算多姿态。

用本次多姿态检查实测关节FK、控制器法兰、静止窗、时间对应与固定关系，逐项填写review。board_orientation_verified 只有看过最终叠加后才可为1。矩形板只用 detected/reverse_180；修正角点顺序后生成新manifest、重新detect核对同一物理ORIGIN 0。review中的0不会自动排除；有坏姿态则保留原始记录、生成有理由的筛选清单，不批量置1。所有修订用新文件名，不覆盖旧结果。

只用train求内参K/D，再用Park求手眼；保留独立组评估。当前 T_gripper_camera 因 gripper_frame=flange_link 即 T_flange_camera，方向为相机到法兰。报告heldout像素误差、固定板平移mm/旋转deg的均值/P95/最大值及姿态ID，结合独立物理几何复核验收。不能把FIT_REQUIRES_REVIEW当自动通过，未运行或不满足条件的项如实记录。

通过后绑定矩阵、像素域、分辨率、序列号与本次腕端安装；更新项目状态、紧凑报告、最终配置、代表原图/角点叠加和下一步提示词并推送GitHub。大原始数据留本机。本轮不启动π自动控制/训练，不修改dog-and-arm，不扩展M1、门任务或遥操作设备讨论。
```

## 一手依据与代码入口

- [大凡厂家 Q12 精确型号表](https://www.dfoptic.com/in-stock-standards-product/152.html)：本型号几何参数。
- [OpenCV 相机标定教程](https://docs.opencv.org/4.x/dc/dbb/tutorial_py_calibration.html)：内角点、尺度、不同视角的内参求解。
- [OpenCV calibrateHandEye 文档](https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html)：矩阵方向、固定目标、多轴旋转条件。
- [本项目采集脚本](../tasks/piper_real_single_v1/capture_pose.sh)、[清单与复核表](../tasks/piper_real_single_v1/pose_manifest.py)、[位姿记录](../tasks/piper_real_single_v1/flange_observation.py)、[求解与独立残差](../tasks/piper_real_single_v1/calibration.py)。
- [旧接续文档](PI_SINGLE_CAMERA_BOARD_HANDOFF_20261122.md)：已有连续记录器分支及历史现场背景。
